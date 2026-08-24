from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import dispose_and_reload, ensure_db, ping_db, session_scope
from app.db.tables import (
    AuditEventRow,
    BatchRow,
    CircuitStateRow,
    GuardrailResultRow,
    IdSequenceRow,
    IdempotencyRow,
    JobRow,
    MetaStateRow,
    PolicySnapshotRow,
    PolicyThresholdRow,
    RailOutcomeRow,
    RateHitRow,
    RouteScoreRow,
    RoutingAttemptRow,
    RoutingEventRow,
    TransactionRow,
    WebhookEventRow,
)
from app.engine.routing_engine import ROUTE_CATALOG
from app.models import (
    BatchResult,
    CircuitBreakerStatus,
    IntelligenceTelemetry,
    RoutePerformance,
    RoutingDashboardStats,
    RoutingEvent,
    RoutingPerformanceResponse,
    RoutingSummary,
    TelemetryDashboard,
    Transaction,
    TransactionState,
    is_active_recovery,
)
from app.observability.metrics import CIRCUIT_STATE, DB_LATENCY
from app.schema_loader import validate_transaction_document
from app.security.pii import redact_mapping
from app.tenancy import query_tenant_id, write_tenant_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _txn_from_row(row: TransactionRow) -> Transaction:
    return Transaction.model_validate(row.payload)


_TERMINAL_STATES = {TransactionState.RECOVERED.value, TransactionState.ESCALATED.value}


class DurableStore:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._lock_versions: dict[str, int] = {}
        self._global = asyncio.Lock()

    async def _timed(self, operation: str, awaitable):
        started = time.perf_counter()
        try:
            return await awaitable
        finally:
            DB_LATENCY.labels(operation).observe(time.perf_counter() - started)

    async def ping(self) -> bool:
        return await ping_db()

    async def allocate_id(self) -> str:
        await ensure_db()
        async with session_scope() as session:
            row = await session.get(IdSequenceRow, "transactions")
            if row is None:
                row = IdSequenceRow(name="transactions", value=0)
                session.add(row)
                await session.flush()
            row.value += 1
            return f"TXN_CB_{row.value:06d}"

    async def reset(self) -> None:
        await ensure_db()
        async with session_scope() as session:
            for model in (
                AuditEventRow,
                GuardrailResultRow,
                RoutingAttemptRow,
                RoutingEventRow,
                RailOutcomeRow,
                WebhookEventRow,
                IdempotencyRow,
                CircuitStateRow,
                BatchRow,
                TransactionRow,
                MetaStateRow,
                IdSequenceRow,
                RouteScoreRow,
                PolicySnapshotRow,
                PolicyThresholdRow,
                JobRow,
                RateHitRow,
            ):
                await session.execute(delete(model))

    async def upsert(self, transaction: Transaction, expected_version: int | None = None) -> Transaction:
        payload = transaction.model_dump(mode="json")
        validate_transaction_document(payload)
        await ensure_db()
        expected = expected_version
        if expected is None:
            expected = self._lock_versions.get(transaction.transaction_id)
        async with session_scope() as session:
            stmt = select(TransactionRow).where(TransactionRow.transaction_id == transaction.transaction_id)
            if not settings.is_sqlite:
                stmt = stmt.with_for_update()
            existing = (await session.execute(stmt)).scalar_one_or_none()
            version = 1
            if existing is not None:
                if expected is not None and existing.version != expected:
                    raise ConcurrencyError(transaction.transaction_id)
                if existing.state in _TERMINAL_STATES and transaction.state.value != existing.state:
                    raise ConcurrencyError(transaction.transaction_id)
                version = existing.version + 1
            row = existing or TransactionRow(transaction_id=transaction.transaction_id)
            row.tenant_id = transaction.tenant_id or write_tenant_id()
            row.state = transaction.state.value
            row.bank = transaction.bank or transaction.routing.bank
            row.amount = transaction.order.amount
            row.cart_status = transaction.cart_status.value
            row.batch_id = transaction.batch_id
            row.version = version
            row.payload = payload
            row.created_at = transaction.created_at
            row.updated_at = transaction.updated_at
            row.failed_at = transaction.failed_at
            row.recovered_at = transaction.recovery.recovered_at
            row.escalated_at = transaction.recovery.escalated_at
            session.add(row)
            await self._sync_children(session, transaction)
            await session.flush()
            if transaction.transaction_id in self._lock_versions:
                self._lock_versions[transaction.transaction_id] = version
            return deepcopy(transaction)

    async def _sync_children(self, session: AsyncSession, transaction: Transaction) -> None:
        txn_id = transaction.transaction_id
        await session.execute(delete(AuditEventRow).where(AuditEventRow.transaction_id == txn_id))
        for event in transaction.audit_trail:
            session.add(
                AuditEventRow(
                    tenant_id=transaction.tenant_id or write_tenant_id(),
                    transaction_id=txn_id,
                    timestamp=event.timestamp,
                    action=event.action,
                    previous_state=event.previous_state.value if event.previous_state else None,
                    new_state=event.new_state.value if event.new_state else None,
                    actor=event.actor,
                    reason=event.reason,
                    metadata_json=redact_mapping(event.metadata or {}),
                )
            )
        await session.execute(delete(GuardrailResultRow).where(GuardrailResultRow.transaction_id == txn_id))
        guard = transaction.recovery.guardrail
        if guard is not None:
            session.add(
                GuardrailResultRow(
                    tenant_id=transaction.tenant_id or write_tenant_id(),
                    transaction_id=txn_id,
                    passed=guard.passed,
                    reason=guard.reason or guard.blocked_reason or "",
                    checks=[check.model_dump() for check in guard.checks],
                    created_at=transaction.updated_at,
                )
            )
        await session.execute(delete(RoutingAttemptRow).where(RoutingAttemptRow.transaction_id == txn_id))
        for attempt in transaction.routing.route_attempts:
            session.add(
                RoutingAttemptRow(
                    tenant_id=transaction.tenant_id or write_tenant_id(),
                    transaction_id=txn_id,
                    sequence=attempt.sequence,
                    route=attempt.route,
                    error_code=transaction.routing.error_code,
                    outcome=attempt.outcome,
                    reason=attempt.reason,
                    at=attempt.at,
                )
            )

    async def get(self, transaction_id: str) -> Transaction | None:
        await ensure_db()
        async with session_scope() as session:
            stmt = select(TransactionRow).where(TransactionRow.transaction_id == transaction_id)
            tenant = query_tenant_id()
            if tenant:
                stmt = stmt.where(TransactionRow.tenant_id == tenant)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return _txn_from_row(row) if row else None

    async def get_version(self, transaction_id: str) -> int | None:
        await ensure_db()
        async with session_scope() as session:
            row = await session.get(TransactionRow, transaction_id)
            return row.version if row else None

    @asynccontextmanager
    async def locked(self, transaction_id: str) -> AsyncIterator[Transaction | None]:
        lock = self._locks[transaction_id]
        async with lock:
            current = await self.get(transaction_id)
            version = await self.get_version(transaction_id)
            if version is not None:
                self._lock_versions[transaction_id] = version
            try:
                yield current
            finally:
                self._lock_versions.pop(transaction_id, None)

    async def list_all(self) -> list[Transaction]:
        await ensure_db()
        async with session_scope() as session:
            stmt = select(TransactionRow).order_by(TransactionRow.created_at.desc())
            tenant = query_tenant_id()
            if tenant:
                stmt = stmt.where(TransactionRow.tenant_id == tenant)
            rows = (await session.execute(stmt)).scalars().all()
            return [_txn_from_row(row) for row in rows]

    async def list_manual_review(self, tenant_id: str | None = None) -> list[Transaction]:
        await ensure_db()
        async with session_scope() as session:
            stmt = (
                select(TransactionRow)
                .where(TransactionRow.state == TransactionState.ESCALATED.value)
                .order_by(TransactionRow.updated_at.desc())
            )
            tenant = tenant_id if tenant_id is not None else query_tenant_id()
            if tenant:
                stmt = stmt.where(TransactionRow.tenant_id == tenant)
            rows = (await session.execute(stmt)).scalars().all()
            return [_txn_from_row(row) for row in rows]

    async def save_batch(self, batch: BatchResult) -> BatchResult:
        await ensure_db()
        async with session_scope() as session:
            session.add(
                BatchRow(
                    batch_id=batch.batch_id,
                    tenant_id=write_tenant_id(),
                    payload=batch.model_dump(mode="json"),
                    created_at=batch.created_at,
                )
            )
            await session.merge(
                MetaStateRow(key="last_batch_id", value_json={"batch_id": batch.batch_id})
            )
            return deepcopy(batch)

    async def last_batch(self) -> BatchResult | None:
        await ensure_db()
        async with session_scope() as session:
            meta = await session.get(MetaStateRow, "last_batch_id")
            if not meta:
                return None
            batch_id = str(meta.value_json.get("batch_id") or "")
            row = await session.get(BatchRow, batch_id)
            return BatchResult.model_validate(row.payload) if row else None

    async def compute_batch(self, batch_id: str) -> BatchResult | None:
        await ensure_db()
        async with session_scope() as session:
            existing = await session.get(BatchRow, batch_id)
            if not existing:
                return None
            current = BatchResult.model_validate(existing.payload)
            rows = (
                await session.execute(
                    select(TransactionRow).where(TransactionRow.transaction_id.in_(current.transaction_ids))
                )
            ).scalars().all()
            txns = [_txn_from_row(row) for row in rows]
            recovered = [txn for txn in txns if txn.state == TransactionState.RECOVERED]
            escalated = [txn for txn in txns if txn.state == TransactionState.ESCALATED]
            in_progress = [
                txn
                for txn in txns
                if txn.state in (TransactionState.FAILED, TransactionState.INITIATED) or is_active_recovery(txn.state)
            ]
            attempts = sum(txn.recovery.attempt_count for txn in txns)
            eligible = len(txns)
            rescued = len(recovered)
            rate = round((rescued / eligible) * 100, 2) if eligible else 0.0
            updated = BatchResult(
                batch_id=current.batch_id,
                batch_size=current.batch_size,
                failures_intercepted=len(txns),
                recovery_attempts=attempts,
                recovered=rescued,
                escalated=len(escalated),
                in_progress=len(in_progress),
                recovery_rate=rate,
                revenue_recovered=sum(txn.order.amount for txn in recovered),
                revenue_at_risk=sum(txn.order.amount for txn in txns if is_active_recovery(txn.state)),
                complete=len(in_progress) == 0 and eligible == current.batch_size,
                created_at=current.created_at,
                transaction_ids=list(current.transaction_ids),
                routing_summary=current.routing_summary,
            )
            existing.payload = updated.model_dump(mode="json")
            return deepcopy(updated)

    async def route_stats(self) -> dict[str, dict[str, int]]:
        await ensure_db()
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        RoutingAttemptRow.route,
                        func.count(RoutingAttemptRow.id),
                        func.sum(case((RoutingAttemptRow.outcome == "SUCCEEDED", 1), else_=0)),
                    ).group_by(RoutingAttemptRow.route)
                )
            ).all()
            stats: dict[str, dict[str, int]] = {route_id: {"attempts": 0, "successful": 0} for route_id in ROUTE_CATALOG}
            for route, attempts, successful in rows:
                stats[str(route)] = {"attempts": int(attempts or 0), "successful": int(successful or 0)}
            return stats

    async def record_route_decision(self, route_id: str, score: int, event: RoutingEvent) -> None:
        await self.record_routing_event(event)

    async def record_route_outcome(self, route_id: str, success: bool, event: RoutingEvent) -> None:
        await self.record_routing_event(event)
        await self.record_rail_outcome(route_id, success)

    async def record_routing_event(self, event: RoutingEvent) -> None:
        await ensure_db()
        async with session_scope() as session:
            session.add(
                RoutingEventRow(
                    tenant_id=write_tenant_id(),
                    timestamp=event.timestamp,
                    transaction_id=event.transaction_id,
                    event=event.event,
                    route=event.route,
                    score=event.score,
                    message=event.message,
                )
            )

    async def save_routing_summary(self, summary: RoutingSummary) -> RoutingSummary:
        await ensure_db()
        async with session_scope() as session:
            await session.merge(MetaStateRow(key="last_routing_summary", value_json=summary.model_dump(mode="json")))
            meta = await session.get(MetaStateRow, "last_batch_id")
            if meta:
                batch_id = str(meta.value_json.get("batch_id") or "")
                batch = await session.get(BatchRow, batch_id)
                if batch:
                    payload = dict(batch.payload)
                    payload["routing_summary"] = summary.model_dump(mode="json")
                    batch.payload = payload
            return deepcopy(summary)

    async def routing_performance(self) -> RoutingPerformanceResponse:
        stats = await self.route_stats()
        await ensure_db()
        async with session_scope() as session:
            events = (
                await session.execute(select(RoutingEventRow).order_by(RoutingEventRow.timestamp.desc()).limit(40))
            ).scalars().all()
            summary_row = await session.get(MetaStateRow, "last_routing_summary")
            last_summary = RoutingSummary.model_validate(summary_row.value_json) if summary_row else None
        routes = []
        for route_id, catalog in ROUTE_CATALOG.items():
            row = stats.get(route_id) or {"attempts": 0, "successful": 0}
            attempts = row["attempts"]
            successful = row["successful"]
            rate = round((successful / attempts) * 100, 1) if attempts else 0.0
            routes.append(
                RoutePerformance(
                    route_id=route_id,
                    display_name=str(catalog["display_name"]),
                    attempts=attempts,
                    successful=successful,
                    success_rate=rate,
                )
            )
        return RoutingPerformanceResponse(
            routes=routes,
            events=[
                RoutingEvent(
                    timestamp=item.timestamp,
                    transaction_id=item.transaction_id,
                    event=item.event,
                    route=item.route,
                    score=item.score,
                    message=item.message,
                )
                for item in events
            ],
            last_summary=last_summary,
            simulated=True,
        )

    async def telemetry(self, demo_mode: bool, recovery_window_seconds: int, heartbeat: datetime) -> TelemetryDashboard:
        await ensure_db()
        tenant = query_tenant_id()
        async with session_scope() as session:
            txn_stmt = select(TransactionRow)
            circuit_stmt = select(CircuitStateRow)
            if tenant:
                txn_stmt = txn_stmt.where(TransactionRow.tenant_id == tenant)
                circuit_stmt = circuit_stmt.where(CircuitStateRow.tenant_id == tenant)
            rows = (await session.execute(txn_stmt)).scalars().all()
            decision_stmt = select(func.count(RoutingEventRow.id)).where(RoutingEventRow.event == "ROUTE_SELECTED")
            success_stmt = select(func.count(RoutingAttemptRow.id)).where(RoutingAttemptRow.outcome == "SUCCEEDED")
            failure_stmt = select(func.count(RoutingAttemptRow.id)).where(RoutingAttemptRow.outcome == "FAILED")
            snapshot_stmt = select(PolicySnapshotRow)
            attempt_stmt = select(RoutingAttemptRow)
            if tenant:
                decision_stmt = decision_stmt.where(RoutingEventRow.tenant_id == tenant)
                success_stmt = success_stmt.where(RoutingAttemptRow.tenant_id == tenant)
                failure_stmt = failure_stmt.where(RoutingAttemptRow.tenant_id == tenant)
                snapshot_stmt = snapshot_stmt.where(PolicySnapshotRow.tenant_id == tenant)
                attempt_stmt = attempt_stmt.where(RoutingAttemptRow.tenant_id == tenant)
            decisions = (await session.execute(decision_stmt)).scalar() or 0
            successes = (await session.execute(success_stmt)).scalar() or 0
            failures = (await session.execute(failure_stmt)).scalar() or 0
            circuits = (await session.execute(circuit_stmt)).scalars().all()
            snapshots = (await session.execute(snapshot_stmt)).scalars().all()
            attempts = (await session.execute(attempt_stmt)).scalars().all()
            queue_stmt = select(func.count(JobRow.id)).where(JobRow.status == "queued")
            if tenant:
                queue_stmt = queue_stmt.where(JobRow.tenant_id == tenant)
            queue_depth = int((await session.execute(queue_stmt)).scalar() or 0)
        txns = [_txn_from_row(row) for row in rows]
        eligible = [txn for txn in txns if txn.state != TransactionState.INITIATED]
        recovered = [txn for txn in txns if txn.state == TransactionState.RECOVERED]
        escalated = [txn for txn in txns if txn.state == TransactionState.ESCALATED]
        held = [txn for txn in txns if is_active_recovery(txn.state)]
        rescued = len(recovered)
        rate = round((rescued / len(eligible)) * 100, 2) if eligible else 0.0
        recovery_times: list[float] = []
        for txn in recovered:
            if txn.recovery.recovered_at:
                start = txn.failed_at or txn.recovery.window_started_at
                recovery_times.append(max((txn.recovery.recovered_at - start).total_seconds(), 0.0))
        avg = round(sum(recovery_times) / len(recovery_times), 1) if recovery_times else None
        last_batch = await self.last_batch()
        if last_batch:
            last_batch = await self.compute_batch(last_batch.batch_id)
        engine_online = await self.ping()
        selected = {}
        for txn in txns:
            route = txn.smart_routing.selected_route if txn.smart_routing else None
            if route:
                selected[route] = selected.get(route, 0) + 1
        most = max(selected.items(), key=lambda item: item[1])[0] if selected else None
        circuit_models = [
            CircuitBreakerStatus(
                rail=row.rail,
                state=row.state,
                failure_rate=round(row.failure_rate, 4),
                samples=row.samples,
                opened_at=row.opened_at,
                cooldown_until=row.cooldown_until,
                tenant_id=getattr(row, "tenant_id", None) or write_tenant_id(),
                baseline_rate=round(getattr(row, "baseline_rate", 0.0) or 0.0, 4),
                zscore=round(getattr(row, "zscore", 0.0) or 0.0, 4),
                opened_by=getattr(row, "opened_by", None) or "threshold",
            )
            for row in circuits
        ]
        for item in circuit_models:
            CIRCUIT_STATE.labels(item.rail, item.tenant_id).set({"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}.get(item.state, 0))
        first_route = [txn for txn in recovered if txn.smart_routing and txn.smart_routing.first_route_recovery]
        fallback = [txn for txn in recovered if txn.smart_routing and txn.smart_routing.fallback_recovery]
        preemptive = [txn for txn in txns if txn.smart_routing and txn.smart_routing.preemptive]
        retry_recovered = [
            txn
            for txn in recovered
            if (txn.smart_routing and (txn.smart_routing.failure_classification.strategy if txn.smart_routing.failure_classification else txn.routing.recovery_strategy) == "RETRY")
        ]
        retry_attempted = [
            txn
            for txn in txns
            if (txn.routing.recovery_strategy == "RETRY" or (txn.smart_routing and txn.smart_routing.failure_classification and txn.smart_routing.failure_classification.strategy == "RETRY"))
            and txn.state in {TransactionState.RECOVERED, TransactionState.ESCALATED, TransactionState.RETRYING, TransactionState.AUTOMATED_LOOP}
        ]
        denom = max(len(eligible), 1)
        recovered_denom = max(len(recovered), 1)
        fail_then = len(fallback) / denom * 100
        predicted = None
        for txn in txns:
            if txn.smart_routing and txn.smart_routing.predicted_failure_probability is not None:
                predicted = txn.smart_routing.predicted_failure_probability
                break
        positive = sum(1 for row in snapshots if "Loosened" in (row.rationale or ""))
        negative = sum(1 for row in snapshots if "Tightened" in (row.rationale or ""))
        rollbacks = sum(1 for row in snapshots if (row.rationale or "").startswith("Rollback"))
        active = next((row for row in snapshots if row.active), None)
        policy_version = f"policy-v{active.version}" if active else (f"policy-v{snapshots[0].version}" if snapshots else "policy-v1")
        open_times: list[float] = []
        recover_times: list[float] = []
        for row in circuits:
            if row.opened_at:
                first_fail = next((item.at for item in attempts if item.route == row.rail), None)
                if first_fail:
                    opened = row.opened_at if row.opened_at.tzinfo else row.opened_at.replace(tzinfo=timezone.utc)
                    started = first_fail if first_fail.tzinfo else first_fail.replace(tzinfo=timezone.utc)
                    open_times.append(max((opened - started).total_seconds(), 0.0))
                if row.state == "CLOSED" and row.cooldown_until:
                    closed = row.cooldown_until if row.cooldown_until.tzinfo else row.cooldown_until.replace(tzinfo=timezone.utc)
                    opened = row.opened_at if row.opened_at.tzinfo else row.opened_at.replace(tzinfo=timezone.utc)
                    recover_times.append(max((closed - opened).total_seconds(), 0.0))
        false_open = 0.0
        opened = [row for row in circuits if row.opened_at]
        recovered_circuits = [row for row in opened if row.state == "CLOSED" and (row.failure_rate or 0) < 0.15]
        if opened:
            false_open = round(len(recovered_circuits) / len(opened) * 100, 2)
        intelligence = IntelligenceTelemetry(
            primary_success_rate=round(len(first_route) / recovered_denom * 100, 2) if recovered else 0.0,
            reroute_success_rate=round(len(fallback) / recovered_denom * 100, 2) if recovered else 0.0,
            fail_then_reroute_rate=round(fail_then, 2),
            predictive_routing_rate=round(len(preemptive) / denom * 100, 2) if eligible else 0.0,
            recovery_rate=rate,
            average_recovery_time=avg,
            retry_success_rate=round(len(retry_recovered) / max(len(retry_attempted), 1) * 100, 2) if retry_attempted else 0.0,
            escalation_rate=round(len(escalated) / denom * 100, 2) if eligible else 0.0,
            time_to_detect=round(sum(open_times) / len(open_times), 1) if open_times else None,
            time_to_open=round(sum(open_times) / len(open_times), 1) if open_times else None,
            time_to_recover=round(sum(recover_times) / len(recover_times), 1) if recover_times else None,
            false_open_rate=false_open,
            policy_adjustments=len(snapshots),
            positive_adjustments=positive,
            negative_adjustments=negative,
            rollback_count=rollbacks,
            active_policy_version=policy_version,
            best_route=most,
            predicted_failure_probability=predicted,
        )
        return TelemetryDashboard(
            total_failures_intercepted=len(eligible),
            total_transactions_rescued=rescued,
            total_revenue_recovered=sum(txn.order.amount for txn in recovered),
            active_held_carts=len(held),
            total_escalated=len(escalated),
            recovery_rate=rate,
            average_recovery_time_seconds=avg,
            revenue_at_risk=sum(txn.order.amount for txn in held),
            revenue_recovered=sum(txn.order.amount for txn in recovered),
            demo_mode=demo_mode,
            recovery_window_seconds=recovery_window_seconds,
            engine_online=engine_online,
            last_heartbeat=heartbeat,
            last_batch=last_batch,
            routing=RoutingDashboardStats(
                total_route_decisions=int(decisions),
                successful_route_executions=int(successes),
                failed_route_executions=int(failures),
                average_route_score=0.0,
                most_selected_route=most,
            ),
            circuit_breakers=circuit_models,
            tenant_id=tenant,
            intelligence=intelligence,
            recovery_queue_depth=queue_depth + len(held),
        )

    async def get_idempotency(self, key: str, endpoint: str) -> dict | None:
        await ensure_db()
        tenant = write_tenant_id()
        async with session_scope() as session:
            result = await session.execute(
                select(IdempotencyRow).where(
                    IdempotencyRow.key == key,
                    IdempotencyRow.endpoint == endpoint,
                    IdempotencyRow.tenant_id == tenant,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "fingerprint": row.fingerprint,
                "status_code": row.status_code,
                "response_json": dict(row.response_json),
            }

    async def claim_idempotency(self, key: str, endpoint: str, fingerprint: str) -> dict | None:
        existing = await self.get_idempotency(key, endpoint)
        if existing is not None:
            return existing
        await ensure_db()
        tenant = write_tenant_id()
        try:
            async with session_scope() as session:
                session.add(
                    IdempotencyRow(
                        tenant_id=tenant,
                        key=key,
                        endpoint=endpoint,
                        fingerprint=fingerprint,
                        status_code=0,
                        response_json={"_pending": True},
                        created_at=_utcnow(),
                    )
                )
        except IntegrityError:
            return await self.get_idempotency(key, endpoint)
        return None

    async def complete_idempotency(self, key: str, endpoint: str, status_code: int, response_json: dict) -> None:
        await ensure_db()
        tenant = write_tenant_id()
        async with session_scope() as session:
            result = await session.execute(
                select(IdempotencyRow).where(
                    IdempotencyRow.key == key,
                    IdempotencyRow.endpoint == endpoint,
                    IdempotencyRow.tenant_id == tenant,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                session.add(
                    IdempotencyRow(
                        tenant_id=tenant,
                        key=key,
                        endpoint=endpoint,
                        fingerprint=fingerprint_payload(response_json),
                        status_code=status_code,
                        response_json=response_json,
                        created_at=_utcnow(),
                    )
                )
                return
            row.status_code = status_code
            row.response_json = response_json

    async def save_idempotency(self, key: str, endpoint: str, fingerprint: str, status_code: int, response_json: dict) -> None:
        await self.complete_idempotency(key, endpoint, status_code, response_json)

    async def record_rail_outcome(self, rail: str, success: bool, tenant_id: str | None = None) -> None:
        await ensure_db()
        tenant = tenant_id or write_tenant_id()
        async with session_scope() as session:
            session.add(RailOutcomeRow(tenant_id=tenant, rail=rail, success=success, created_at=_utcnow()))

    async def rail_window_stats(self, rail: str, window_seconds: int, tenant_id: str | None = None) -> tuple[int, int]:
        await ensure_db()
        tenant = tenant_id or write_tenant_id()
        cutoff = _utcnow() - timedelta(seconds=window_seconds)
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(RailOutcomeRow).where(RailOutcomeRow.rail == rail, RailOutcomeRow.tenant_id == tenant)
                )
            ).scalars().all()
            total = 0
            failures = 0
            for row in rows:
                created = row.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= cutoff:
                    total += 1
                    if not row.success:
                        failures += 1
            return total, failures

    async def rail_baseline_stats(self, rail: str, tenant_id: str | None = None) -> tuple[float, float]:
        await ensure_db()
        tenant = tenant_id or write_tenant_id()
        cutoff = _utcnow() - timedelta(seconds=settings.CIRCUIT_WINDOW_SECONDS)
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(RailOutcomeRow).where(RailOutcomeRow.rail == rail, RailOutcomeRow.tenant_id == tenant)
                )
            ).scalars().all()
        historical = []
        for row in rows:
            created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
            if created < cutoff:
                historical.append(0.0 if row.success else 1.0)
        if len(historical) < 5:
            return 0.05, 0.05
        mean = sum(historical) / len(historical)
        variance = sum((item - mean) ** 2 for item in historical) / len(historical)
        return mean, variance ** 0.5

    async def get_circuit(self, rail: str, tenant_id: str | None = None) -> CircuitStateRow | None:
        await ensure_db()
        tenant = tenant_id or write_tenant_id()
        async with session_scope() as session:
            return await session.get(CircuitStateRow, (tenant, rail))

    async def upsert_circuit(self, row: CircuitStateRow) -> None:
        await ensure_db()
        if not row.tenant_id:
            row.tenant_id = write_tenant_id()
        async with session_scope() as session:
            await session.merge(row)

    async def list_circuits(self, tenant_id: str | None = None) -> list[CircuitStateRow]:
        await ensure_db()
        tenant = tenant_id if tenant_id is not None else query_tenant_id()
        async with session_scope() as session:
            stmt = select(CircuitStateRow)
            if tenant:
                stmt = stmt.where(CircuitStateRow.tenant_id == tenant)
            return list((await session.execute(stmt)).scalars().all())

    async def save_webhook_event(self, transaction_id: str, event: str, payload: dict, delivered: bool, error: str = "") -> None:
        await ensure_db()
        async with session_scope() as session:
            session.add(
                WebhookEventRow(
                    tenant_id=write_tenant_id(),
                    transaction_id=transaction_id,
                    event=event,
                    payload=payload,
                    delivered=delivered,
                    error=error,
                    created_at=_utcnow(),
                )
            )

    async def list_webhook_events(self, transaction_id: str | None = None) -> list[WebhookEventRow]:
        await ensure_db()
        async with session_scope() as session:
            stmt = select(WebhookEventRow).order_by(WebhookEventRow.created_at.desc())
            if transaction_id:
                stmt = stmt.where(WebhookEventRow.transaction_id == transaction_id)
            return list((await session.execute(stmt.limit(100))).scalars().all())

    async def seed_route_attempts(
        self,
        *,
        tenant_id: str,
        error_code: str,
        route: str,
        outcome: str,
        count: int,
    ) -> None:
        await ensure_db()
        async with session_scope() as session:
            for _ in range(count):
                session.add(
                    RoutingAttemptRow(
                        tenant_id=tenant_id,
                        transaction_id="TXN_CB_000000",
                        sequence=1,
                        route=route,
                        error_code=error_code,
                        outcome=outcome,
                        reason="seed",
                        at=_utcnow(),
                    )
                )

    async def seed_rail_history(
        self,
        *,
        tenant_id: str,
        rail: str,
        success: bool,
        count: int,
        age_seconds: int = 3600,
    ) -> None:
        await ensure_db()
        created = _utcnow() - timedelta(seconds=age_seconds)
        async with session_scope() as session:
            for _ in range(count):
                session.add(RailOutcomeRow(tenant_id=tenant_id, rail=rail, success=success, created_at=created))

    async def mark_escalated_resolved(self, tenant_id: str, count: int) -> None:
        await ensure_db()
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(TransactionRow).where(
                        TransactionRow.tenant_id == tenant_id,
                        TransactionRow.state == TransactionState.ESCALATED.value,
                    )
                )
            ).scalars().all()
            for row in rows[:count]:
                payload = dict(row.payload)
                payload["money_recovered"] = payload.get("order", {}).get("amount") or 1
                payload["demo_scenario"] = "MANUAL_RESOLVE"
                row.payload = payload


class ConcurrencyError(Exception):
    def __init__(self, transaction_id: str) -> None:
        super().__init__(f"Concurrent modification of {transaction_id}")
        self.transaction_id = transaction_id


def fingerprint_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


store = DurableStore()


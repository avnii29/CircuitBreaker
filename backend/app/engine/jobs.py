"""Background jobs.

Priority order (lower number runs first):
  0  realtime transaction recovery / supervise
  10 batch recovery
  20 analytics / policy retrain

Batch and simulation traffic is shed when the manual-review queue or job
depth exceeds BACKPRESSURE_* so realtime checkout recovery stays healthy.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db.session import session_scope
from app.db.tables import JobRow, TransactionRow
from app.observability.logging import log_event
from app.tenancy import TenantPrincipal, reset_principal, set_principal

logger = logging.getLogger("circuitbreaker.jobs")

PRIORITY_REALTIME = 0
PRIORITY_BATCH = 10
PRIORITY_ANALYTICS = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue(kind: str, tenant_id: str, payload: dict, priority: int = PRIORITY_REALTIME) -> JobRow:
    async with session_scope() as session:
        job = JobRow(
            tenant_id=tenant_id,
            kind=kind,
            priority=priority,
            status="queued",
            payload=payload,
            available_at=_utcnow(),
        )
        session.add(job)
        await session.flush()
        return job


async def queue_depth(kind: str | None = None) -> int:
    async with session_scope() as session:
        stmt = select(JobRow).where(JobRow.status == "queued")
        if kind:
            stmt = stmt.where(JobRow.kind == kind)
        rows = (await session.execute(stmt)).scalars().all()
        return len(rows)


async def review_depth(tenant_id: str | None = None) -> int:
    async with session_scope() as session:
        stmt = select(TransactionRow).where(TransactionRow.state == "ESCALATED")
        if tenant_id:
            stmt = stmt.where(TransactionRow.tenant_id == tenant_id)
        return len((await session.execute(stmt)).scalars().all())


async def should_shed_batch(tenant_id: str) -> bool:
    if await review_depth(tenant_id) >= settings.BACKPRESSURE_REVIEW_DEPTH:
        return True
    if await queue_depth() >= settings.BACKPRESSURE_JOB_DEPTH:
        return True
    return False


async def claim_job() -> JobRow | None:
    async with session_scope() as session:
        stmt = (
            select(JobRow)
            .where(JobRow.status == "queued", JobRow.available_at <= _utcnow())
            .order_by(JobRow.priority.asc(), JobRow.id.asc())
            .limit(1)
        )
        if not settings.is_sqlite:
            stmt = stmt.with_for_update(skip_locked=True)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        row.status = "running"
        row.claimed_at = _utcnow()
        await session.flush()
        session.expunge(row)
        return row


async def complete_job(job_id: int, error: str = "") -> None:
    async with session_scope() as session:
        row = await session.get(JobRow, job_id)
        if row is None:
            return
        row.status = "failed" if error else "done"
        row.error = error
        row.completed_at = _utcnow()


async def dispatch(job: JobRow) -> None:
    token = set_principal(TenantPrincipal(tenant_id=job.tenant_id, scope="write"))
    try:
        if job.kind in {"recover", "supervise"}:
            from app.engine.lifecycle import execute_recovery
            from app.engine.worker import supervise_checkout

            txn_id = str(job.payload.get("transaction_id") or "")
            if job.kind == "supervise" and txn_id:
                await supervise_checkout(
                    txn_id,
                    auto_recover=bool(job.payload.get("auto_recover")),
                    auto_recover_after_delay=float(job.payload.get("auto_recover_after_delay") or 6.0),
                    force_route_failure=bool(job.payload.get("force_route_failure")),
                )
            elif txn_id:
                await execute_recovery(txn_id)
        elif job.kind == "retrain":
            from app.engine.policy import retrain

            await retrain(job.tenant_id)
        elif job.kind == "batch_recover":
            from app.engine.routing_service import run_smart_routing_batch

            ids = list(job.payload.get("transaction_ids") or [])
            await run_smart_routing_batch(ids)
        await complete_job(job.id)
        log_event(logger, "job_completed", outcome="OK", extra_payload={"kind": job.kind, "id": job.id})
    except Exception as exc:
        await complete_job(job.id, error=str(exc)[:300])
        log_event(logger, "job_failed", outcome="ERROR", extra_payload={"kind": job.kind, "error": str(exc)[:200]})
    finally:
        reset_principal(token)


async def worker_loop() -> None:
    while True:
        try:
            job = await claim_job()
            if job is None:
                await asyncio.sleep(0.25)
                continue
            await dispatch(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(1.0)


async def retrain_loop() -> None:
    interval = max(settings.RETRAIN_INTERVAL_SECONDS, 5)
    while True:
        try:
            await asyncio.sleep(interval)
            from app.engine.policy import retrain
            from app.tenancy import list_known_tenants

            for tenant_id in list_known_tenants():
                await enqueue("retrain", tenant_id, {}, priority=PRIORITY_ANALYTICS)
        except asyncio.CancelledError:
            raise
        except Exception:
            log_event(logger, "retrain_schedule_failed", outcome="ERROR")

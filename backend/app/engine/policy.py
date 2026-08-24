from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from app.config import settings
from app.db.session import session_scope
from app.db.tables import (
    PolicySnapshotRow,
    PolicyThresholdRow,
    RouteScoreRow,
    RoutingAttemptRow,
    TransactionRow,
)
from app.engine.routing_engine import ROUTE_CATALOG
from app.tenancy import query_tenant_id, write_tenant_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def policy_version_label(version: int | None) -> str:
    return f"policy-v{int(version or 1)}"


def default_thresholds() -> dict[str, Any]:
    return {
        "max_retries": settings.MAX_RECOVERY_ATTEMPTS,
        "amount_limit": 10000,
        "cooldown_seconds": 30,
        "predict_fail_threshold": settings.PREDICT_FAIL_THRESHOLD,
        "recovery_window": settings.recovery_window_seconds,
        "risk_threshold": 1.0,
        "circuit_threshold": settings.CIRCUIT_FAILURE_RATE_THRESHOLD,
        "routing_weights": {"learned": 0.7, "historical": 0.3},
        "predictive_threshold": settings.PREDICT_FAIL_THRESHOLD,
        "version": 1,
        "rationale": "Initial bounded policy.",
        "policy_version": policy_version_label(1),
    }


async def get_thresholds(tenant_id: str | None = None) -> dict[str, Any]:
    tenant = tenant_id or write_tenant_id()
    async with session_scope() as session:
        row = await session.get(PolicyThresholdRow, tenant)
        if row is None:
            return {**default_thresholds(), "tenant_id": tenant}
        return {
            "tenant_id": row.tenant_id,
            "max_retries": row.max_retries,
            "amount_limit": row.amount_limit,
            "cooldown_seconds": row.cooldown_seconds,
            "predict_fail_threshold": row.predict_fail_threshold,
            "recovery_window": settings.recovery_window_seconds,
            "risk_threshold": 1.0,
            "circuit_threshold": settings.CIRCUIT_FAILURE_RATE_THRESHOLD,
            "routing_weights": {"learned": 0.7, "historical": 0.3},
            "predictive_threshold": row.predict_fail_threshold,
            "version": row.version,
            "rationale": row.rationale,
            "updated_at": row.updated_at.isoformat(),
            "policy_version": policy_version_label(row.version),
        }


async def save_thresholds(tenant_id: str, values: dict[str, Any], rationale: str) -> dict[str, Any]:
    now = _utcnow()
    async with session_scope() as session:
        row = await session.get(PolicyThresholdRow, tenant_id)
        version = 1 if row is None else row.version + 1
        if row is None:
            row = PolicyThresholdRow(tenant_id=tenant_id, updated_at=now)
            session.add(row)
        row.max_retries = int(values["max_retries"])
        row.amount_limit = int(values["amount_limit"])
        row.cooldown_seconds = int(values["cooldown_seconds"])
        row.predict_fail_threshold = float(values["predict_fail_threshold"])
        row.version = version
        row.rationale = rationale
        row.updated_at = now
        await session.flush()
        return await _snapshot(session, tenant_id, version, rationale)


async def _snapshot(session, tenant_id: str, version: int, rationale: str) -> dict[str, Any]:
    scores = (
        await session.execute(select(RouteScoreRow).where(RouteScoreRow.tenant_id == tenant_id))
    ).scalars().all()
    thresholds = await session.get(PolicyThresholdRow, tenant_id)
    payload = {
        "tenant_id": tenant_id,
        "version": version,
        "thresholds": {
            "max_retries": thresholds.max_retries if thresholds else settings.MAX_RECOVERY_ATTEMPTS,
            "amount_limit": thresholds.amount_limit if thresholds else 10000,
            "cooldown_seconds": thresholds.cooldown_seconds if thresholds else 30,
            "predict_fail_threshold": thresholds.predict_fail_threshold if thresholds else settings.PREDICT_FAIL_THRESHOLD,
            "recovery_window": settings.recovery_window_seconds,
            "risk_threshold": 1.0,
            "circuit_threshold": settings.CIRCUIT_FAILURE_RATE_THRESHOLD,
            "routing_weights": {"learned": 0.7, "historical": 0.3},
            "predictive_threshold": thresholds.predict_fail_threshold if thresholds else settings.PREDICT_FAIL_THRESHOLD,
            "policy_version": policy_version_label(version),
        },
        "route_scores": [
            {
                "error_code": row.error_code,
                "rail": row.rail,
                "success_rate": row.success_rate,
                "samples": row.samples,
                "rationale": row.rationale,
            }
            for row in scores
        ],
    }
    await session.execute(
        update(PolicySnapshotRow).where(PolicySnapshotRow.tenant_id == tenant_id).values(active=False)
    )
    session.add(
        PolicySnapshotRow(
            tenant_id=tenant_id,
            version=version,
            payload=payload,
            rationale=rationale,
            created_at=_utcnow(),
            active=True,
        )
    )
    payload["rationale"] = rationale
    payload["active"] = True
    return payload


async def list_snapshots(tenant_id: str | None = None) -> list[dict[str, Any]]:
    tenant = tenant_id or write_tenant_id()
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(PolicySnapshotRow)
                .where(PolicySnapshotRow.tenant_id == tenant)
                .order_by(PolicySnapshotRow.version.desc())
            )
        ).scalars().all()
        return [
            {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "version": row.version,
                "payload": row.payload,
                "rationale": row.rationale,
                "created_at": row.created_at.isoformat(),
                "active": row.active,
            }
            for row in rows
        ]


async def rollback_to(version: int, tenant_id: str | None = None) -> dict[str, Any]:
    tenant = tenant_id or write_tenant_id()
    async with session_scope() as session:
        row = (
            await session.execute(
                select(PolicySnapshotRow).where(
                    PolicySnapshotRow.tenant_id == tenant,
                    PolicySnapshotRow.version == version,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(f"snapshot {version} not found")
        thresholds = dict(row.payload.get("thresholds") or default_thresholds())
        rationale = f"Rollback to policy snapshot v{version}: {row.rationale}"
    return await save_thresholds(tenant, {**default_thresholds(), **thresholds}, rationale)


async def learned_stats(error_code: str, tenant_id: str | None = None) -> dict[str, dict[str, int | float]]:
    tenant = tenant_id or write_tenant_id()
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(RouteScoreRow).where(
                    RouteScoreRow.tenant_id == tenant,
                    RouteScoreRow.error_code == error_code,
                )
            )
        ).scalars().all()
        stats: dict[str, dict[str, int | float]] = {}
        for row in rows:
            stats[row.rail] = {
                "attempts": row.samples,
                "successful": int(round(row.success_rate * row.samples)),
                "success_rate": row.success_rate,
                "samples": row.samples,
            }
        return stats


async def current_policy(tenant_id: str | None = None) -> dict[str, Any]:
    tenant = tenant_id or query_tenant_id() or write_tenant_id()
    thresholds = await get_thresholds(tenant)
    async with session_scope() as session:
        scores = (
            await session.execute(select(RouteScoreRow).where(RouteScoreRow.tenant_id == tenant))
        ).scalars().all()
        active = (
            await session.execute(
                select(PolicySnapshotRow)
                .where(PolicySnapshotRow.tenant_id == tenant, PolicySnapshotRow.active.is_(True))
                .order_by(PolicySnapshotRow.version.desc())
            )
        ).scalar_one_or_none()
    return {
        "tenant_id": tenant,
        "thresholds": thresholds,
        "route_scores": [
            {
                "error_code": row.error_code,
                "rail": row.rail,
                "success_rate": round(row.success_rate, 4),
                "samples": row.samples,
                "rationale": row.rationale,
                "computed_at": row.computed_at.isoformat(),
            }
            for row in scores
        ],
        "active_snapshot_version": active.version if active else thresholds.get("version"),
        "active_policy_version": thresholds.get("policy_version") or f"policy-v{active.version if active else thresholds.get('version') or 1}",
        "last_adjustment": thresholds.get("rationale"),
    }


async def retrain(tenant_id: str | None = None) -> dict[str, Any]:
    tenant = tenant_id or write_tenant_id()
    now = _utcnow()
    cutoff_time = now - timedelta(hours=settings.SCORE_WINDOW_HOURS)
    async with session_scope() as session:
        attempts = (
            await session.execute(
                select(RoutingAttemptRow)
                .where(RoutingAttemptRow.tenant_id == tenant)
                .order_by(RoutingAttemptRow.at.desc())
                .limit(settings.SCORE_WINDOW_ATTEMPTS)
            )
        ).scalars().all()
        windowed = []
        for row in attempts:
            created = row.at if row.at.tzinfo else row.at.replace(tzinfo=timezone.utc)
            if created >= cutoff_time or len(windowed) < settings.SCORE_WINDOW_ATTEMPTS:
                windowed.append(row)
        grouped: dict[tuple[str, str], list[RoutingAttemptRow]] = {}
        for row in windowed:
            key = (row.error_code or "", row.route)
            grouped.setdefault(key, []).append(row)

        for (error_code, rail), rows in grouped.items():
            if not error_code or rail not in ROUTE_CATALOG:
                continue
            samples = len(rows)
            successes = sum(1 for item in rows if item.outcome == "SUCCEEDED")
            rate = successes / samples if samples else 0.0
            recency_hits = 0
            recency_ok = 0
            for index, item in enumerate(rows[:50]):
                weight = 1.0 if index < 10 else 0.5
                recency_hits += weight
                if item.outcome == "SUCCEEDED":
                    recency_ok += weight
            recency_rate = recency_ok / recency_hits if recency_hits else rate
            blended = round(0.7 * recency_rate + 0.3 * rate, 4)
            rationale = (
                f"{successes}/{samples} successes for {error_code} on {rail} "
                f"in the last {settings.SCORE_WINDOW_HOURS}h or {settings.SCORE_WINDOW_ATTEMPTS} attempts "
                f"(blended recency rate {blended:.0%})."
            )
            existing = await session.get(RouteScoreRow, (tenant, error_code, rail))
            if existing is None:
                session.add(
                    RouteScoreRow(
                        tenant_id=tenant,
                        error_code=error_code,
                        rail=rail,
                        success_rate=blended,
                        samples=samples,
                        window_hours=settings.SCORE_WINDOW_HOURS,
                        rationale=rationale,
                        computed_at=now,
                    )
                )
            else:
                existing.success_rate = blended
                existing.samples = samples
                existing.rationale = rationale
                existing.computed_at = now

        thresholds = await session.get(PolicyThresholdRow, tenant)
        if thresholds is None:
            thresholds = PolicyThresholdRow(
                tenant_id=tenant,
                updated_at=now,
                max_retries=settings.MAX_RECOVERY_ATTEMPTS,
            )
            session.add(thresholds)
            await session.flush()

        escalated = (
            await session.execute(
                select(TransactionRow).where(
                    TransactionRow.tenant_id == tenant,
                    TransactionRow.state == "ESCALATED",
                )
            )
        ).scalars().all()
        recovered_after = 0
        false_negatives = 0
        for txn in escalated:
            payload = txn.payload or {}
            if payload.get("money_recovered") or payload.get("demo_scenario") == "MANUAL_RESOLVE":
                recovered_after += 1
            guard = ((payload.get("recovery") or {}).get("guardrail") or {})
            if guard.get("passed") is True:
                false_negatives += 1

        rationale_parts = ["Retrain from durable routing attempts."]
        changed = False
        if recovered_after >= 3 and thresholds.max_retries < settings.POLICY_RETRY_MAX:
            thresholds.max_retries += 1
            changed = True
            rationale_parts.append(
                f"Loosened max_retries to {thresholds.max_retries} after {recovered_after} escalations were later resolved."
            )
        if false_negatives >= 3 and thresholds.max_retries > settings.POLICY_RETRY_MIN:
            thresholds.max_retries -= 1
            changed = True
            rationale_parts.append(
                f"Tightened max_retries to {thresholds.max_retries} after {false_negatives} guardrail false negatives."
            )
        if not changed:
            rationale_parts.append("Thresholds unchanged; observed mix is within bounds.")
        thresholds.rationale = " ".join(rationale_parts)
        thresholds.version += 1
        thresholds.updated_at = now
        await session.flush()
        snapshot = await _snapshot(session, tenant, thresholds.version, thresholds.rationale)
    return snapshot

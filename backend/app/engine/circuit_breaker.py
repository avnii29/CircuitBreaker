from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.tables import CircuitStateRow
from app.observability.logging import log_event
from app.observability.metrics import CIRCUIT_STATE
from app.store import store
from app.tenancy import write_tenant_id

logger = logging.getLogger("circuitbreaker.circuit")

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


def _state_gauge(rail: str, state: str, tenant_id: str) -> None:
    CIRCUIT_STATE.labels(rail, tenant_id).set({CLOSED: 0, HALF_OPEN: 1, OPEN: 2}.get(state, 0))


def _now():
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _zscore(current: float, mean: float, std: float) -> float:
    if std <= 1e-9:
        return 0.0 if abs(current - mean) < 1e-9 else (10.0 if current > mean else -10.0)
    return (current - mean) / std


async def record_outcome(rail: str, success: bool, tenant_id: str | None = None) -> CircuitStateRow:
    tenant = tenant_id or write_tenant_id()
    await store.record_rail_outcome(rail, success, tenant_id=tenant)
    return await refresh_circuit(rail, tenant_id=tenant)


async def refresh_circuit(rail: str, tenant_id: str | None = None) -> CircuitStateRow:
    tenant = tenant_id or write_tenant_id()
    now = _now()
    existing = await store.get_circuit(rail, tenant_id=tenant)
    samples, failures = await store.rail_window_stats(rail, settings.CIRCUIT_WINDOW_SECONDS, tenant_id=tenant)
    baseline_mean, baseline_std = await store.rail_baseline_stats(rail, tenant_id=tenant)
    successes = max(samples - failures, 0)
    failure_rate = (failures / samples) if samples else 0.0
    zscore = _zscore(failure_rate, baseline_mean, baseline_std)
    row = existing or CircuitStateRow(tenant_id=tenant, rail=rail, state=CLOSED)
    row.tenant_id = tenant
    row.samples = samples
    row.failure_rate = failure_rate
    row.baseline_rate = baseline_mean
    row.zscore = zscore
    cooldown_until = _aware(row.cooldown_until)

    if row.state == OPEN and cooldown_until and now >= cooldown_until:
        row.state = HALF_OPEN
        log_event(logger, "circuit_half_open", rail=rail, tenant_id=tenant, transaction_id="-", outcome=HALF_OPEN, event_type="circuit_change")
    elif row.state == HALF_OPEN:
        if samples >= 1 and successes > 0 and failure_rate < settings.CIRCUIT_FAILURE_RATE_THRESHOLD:
            row.state = CLOSED
            row.opened_at = None
            row.cooldown_until = None
            row.opened_by = "threshold"
            log_event(logger, "circuit_closed", rail=rail, tenant_id=tenant, transaction_id="-", outcome=CLOSED, event_type="circuit_change")
        elif samples >= 1 and failure_rate >= settings.CIRCUIT_FAILURE_RATE_THRESHOLD:
            row.state = OPEN
            row.opened_at = now
            row.cooldown_until = now + timedelta(seconds=settings.CIRCUIT_COOLDOWN_SECONDS)
            row.opened_by = "threshold"
            log_event(logger, "circuit_open", rail=rail, tenant_id=tenant, transaction_id="-", outcome=OPEN, event_type="circuit_change")
    else:
        anomaly = (
            samples >= settings.CIRCUIT_ANOMALY_MIN_SAMPLES
            and zscore >= settings.CIRCUIT_ANOMALY_ZSCORE
            and failure_rate > baseline_mean
        )
        static = samples >= settings.CIRCUIT_MIN_SAMPLES and failure_rate > settings.CIRCUIT_FAILURE_RATE_THRESHOLD
        if anomaly or static:
            row.state = OPEN
            row.opened_at = now
            row.cooldown_until = now + timedelta(seconds=settings.CIRCUIT_COOLDOWN_SECONDS)
            row.opened_by = "anomaly" if anomaly and not static else "threshold"
            log_event(
                logger,
                "circuit_open",
                rail=rail,
                tenant_id=tenant,
                transaction_id="-",
                outcome=OPEN,
                event_type="circuit_change",
                extra_payload={"opened_by": row.opened_by, "zscore": round(zscore, 2)},
            )

    await store.upsert_circuit(row)
    _state_gauge(rail, row.state, tenant)
    return row


async def blocked_rails(tenant_id: str | None = None) -> set[str]:
    tenant = tenant_id or write_tenant_id()
    blocked: set[str] = set()
    for row in await store.list_circuits(tenant_id=tenant):
        await refresh_circuit(row.rail, tenant_id=tenant)
    for row in await store.list_circuits(tenant_id=tenant):
        if row.state == OPEN:
            blocked.add(row.rail)
    return blocked


async def is_open(rail: str, tenant_id: str | None = None) -> bool:
    row = await refresh_circuit(rail, tenant_id=tenant_id)
    return row.state == OPEN

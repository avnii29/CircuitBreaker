from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.engine.circuit_breaker import OPEN
from app.store import store


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def evaluate_alerts() -> list[dict]:
    alerts: list[dict] = []
    db_ok = await store.ping()
    if not db_ok:
        alerts.append(
            {
                "code": "DB_UNREACHABLE",
                "severity": "critical",
                "message": "Database ping failed.",
                "page": True,
            }
        )
        return alerts
    queue = await store.list_manual_review()
    if len(queue) >= settings.ALERT_MANUAL_REVIEW_DEPTH:
        alerts.append(
            {
                "code": "MANUAL_REVIEW_BACKLOG",
                "severity": "high",
                "message": f"Manual review queue depth is {len(queue)}.",
                "page": True,
            }
        )
    now = _utcnow()
    for circuit in await store.list_circuits():
        if circuit.state == OPEN and circuit.opened_at:
            opened_at = circuit.opened_at
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            opened_for = (now - opened_at).total_seconds()
            if opened_for >= settings.ALERT_CIRCUIT_OPEN_SECONDS:
                alerts.append(
                    {
                        "code": "CIRCUIT_OPEN_SUSTAINED",
                        "severity": "high",
                        "message": f"Rail {circuit.rail} has been OPEN for {int(opened_for)}s.",
                        "page": True,
                    }
                )
        samples, failures = await store.rail_window_stats(circuit.rail, settings.CIRCUIT_WINDOW_SECONDS)
        if samples >= settings.CIRCUIT_MIN_SAMPLES:
            rate = failures / samples
            if rate >= settings.ALERT_ERROR_RATE_THRESHOLD:
                alerts.append(
                    {
                        "code": "ERROR_RATE_SPIKE",
                        "severity": "high",
                        "message": f"Rail {circuit.rail} error rate is {rate:.0%}.",
                        "page": True,
                    }
                )
    return alerts

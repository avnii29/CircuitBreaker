from __future__ import annotations

import logging

from datetime import datetime, timezone

import httpx

from app.config import settings
from app.observability.logging import log_event
from app.security.pii import redact_mapping
from app.store import store

logger = logging.getLogger("circuitbreaker.webhooks")


async def emit_resolution_event(transaction_id: str, state: str, amount: int, reason: str = "") -> None:
    event = "PAYMENT_RECOVERED" if state == "RECOVERED" else "PAYMENT_ESCALATED"
    payload = {
        "event": event,
        "transaction_id": transaction_id,
        "state": state,
        "amount": amount,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    delivered = False
    error = ""
    url = (settings.WEBHOOK_URL or "").strip()
    if url:
        try:
            async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
                delivered = 200 <= response.status_code < 300
                if not delivered:
                    error = f"webhook_status_{response.status_code}"
        except Exception as exc:
            error = str(exc)[:300]
            log_event(
                logger,
                "webhook_failed",
                transaction_id=transaction_id,
                outcome="FAILED",
                extra_payload=redact_mapping({"error": error}),
            )
    await store.save_webhook_event(transaction_id, event, payload, delivered, error)
    log_event(logger, "resolution_event", transaction_id=transaction_id, outcome=state, action=event)

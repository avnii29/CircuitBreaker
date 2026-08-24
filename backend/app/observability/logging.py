from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.security.pii import redact_mapping


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "transaction_id",
            "tenant_id",
            "correlation_id",
            "outcome",
            "action",
            "rail",
            "event",
            "event_type",
            "from_state",
            "to_state",
            "decision",
            "policy_version",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        extra = getattr(record, "extra_payload", None)
        if isinstance(extra, dict):
            payload.update(redact_mapping(extra))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


KNOWN_FIELDS = {
    "transaction_id",
    "tenant_id",
    "correlation_id",
    "outcome",
    "action",
    "rail",
    "event",
    "event_type",
    "from_state",
    "to_state",
    "decision",
    "policy_version",
}


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    extra: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key == "extra_payload" and isinstance(value, dict):
            payload.update(value)
        elif key in KNOWN_FIELDS:
            extra[key] = value
        else:
            payload[key] = value
    if payload:
        extra["extra_payload"] = payload
    logger.info(message, extra=extra)

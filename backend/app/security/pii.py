from __future__ import annotations

from typing import Any


def mask_email(value: str | None) -> str:
    raw = (value or "").strip()
    if "@" not in raw:
        return "***"
    name, domain = raw.split("@", 1)
    if not name:
        return f"***@{domain}"
    return f"{name[0]}***@{domain}"


def mask_phone(value: str | None) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"{'*' * max(len(digits) - 4, 0)}{digits[-4:]}"


def mask_name(value: str | None) -> str:
    parts = [part for part in (value or "").split(" ") if part]
    if not parts:
        return "***"
    if len(parts) == 1:
        return f"{parts[0][0]}***"
    return f"{parts[0][0]}*** {parts[-1][0]}***"


def redact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    sensitive = {
        "email",
        "phone",
        "name",
        "customer_name",
        "customer_email",
        "customer_phone",
        "vpa",
        "pan",
        "cvv",
        "pin",
        "upi_pin",
        "card",
        "upi_id",
        "payment_link",
        "customer_message",
        "raw_llm_output",
        "raw_output",
        "password",
        "secret",
        "api_key",
        "authorization",
        "token",
    }
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if (
            lowered in sensitive
            or "pan" in lowered
            or "vpa" in lowered
            or "cvv" in lowered
            or "password" in lowered
            or "secret" in lowered
            or "api_key" in lowered
        ):
            redacted[key] = "***"
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        else:
            redacted[key] = value
    return redacted

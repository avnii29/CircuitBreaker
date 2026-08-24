from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.formatting import format_inr, rupee
from app.models import GuardrailCheck, GuardrailResult, TransactionState, is_active_recovery


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _fallback_message(source_record: dict[str, Any]) -> str:
    customer = source_record.get("customer") or {}
    order = source_record.get("order") or {}
    recovery = source_record.get("recovery") or {}
    name = str(customer.get("name") or "there").split(" ")[0]
    amount = rupee(int(order.get("amount") or 0))
    txn_id = str(source_record.get("transaction_id") or "")
    link = str(recovery.get("payment_link") or "")
    return (
        f"Hey {name}! Aapka {amount} ka payment complete nahi ho paya (ref {txn_id}). "
        f"Don't worry, aapka order safe hai. Is alternate link se payment complete kar sakte hain: {link}"
    )


def _evaluate_guardrail(raw_llm_output: str, source_record: dict[str, Any]) -> GuardrailResult:
    output = raw_llm_output or ""
    order = source_record.get("order") or {}
    recovery = source_record.get("recovery") or {}
    txn_id = str(source_record.get("transaction_id") or "")
    amount = int(order.get("amount") or 0)
    link = str(recovery.get("payment_link") or "")
    state = str(source_record.get("state") or "")
    attempt_count = int(recovery.get("attempt_count") or 0)
    max_attempts = int(recovery.get("max_attempts") or 3)
    expires_at = _as_datetime(recovery.get("window_expires_at"))

    amount_token = str(amount)
    formatted_amount = format_inr(amount)
    rupee_amount = rupee(amount)
    amount_present = (
        amount_token in output.replace(",", "")
        or formatted_amount in output
        or rupee_amount in output
    )

    other_rupee = []
    for match in re.findall(r"₹\s*([\d,]+)", output):
        digits = int(match.replace(",", "") or 0)
        if digits != amount:
            other_rupee.append(digits)

    urls = re.findall(r"https://[^\s)]+", output)
    malformed_link = False
    for url in urls:
        cleaned = url.rstrip(".,;")
        if cleaned != link:
            malformed_link = True
    if link and not any(url.rstrip(".,;") == link for url in urls) and link not in output:
        link_ok = False
    else:
        link_ok = bool(link) and link in output and not malformed_link

    state_ok = is_active_recovery(TransactionState(state)) if state in {item.value for item in TransactionState} else False
    window_ok = expires_at is not None and _utcnow() < expires_at
    attempts_ok = attempt_count < max_attempts
    txn_ok = bool(txn_id) and txn_id in output
    amount_ok = amount_present and not other_rupee

    checks = [
        GuardrailCheck(key="amount", label="Transaction amount verified", passed=amount_ok),
        GuardrailCheck(key="transaction_id", label="Transaction ID verified", passed=txn_ok),
        GuardrailCheck(key="window", label="Recovery window valid", passed=window_ok),
        GuardrailCheck(key="attempts", label="Attempt limit valid", passed=attempts_ok),
        GuardrailCheck(key="link", label="Alternate link valid", passed=link_ok),
        GuardrailCheck(key="state", label="Transaction is in automated recovery", passed=state_ok),
    ]
    passed = all(check.passed for check in checks)
    reason = None
    if not passed:
        failed = [check.label for check in checks if not check.passed]
        reason = "Guardrail blocked AI output: " + ", ".join(failed).lower()
    return GuardrailResult(
        passed=passed,
        checks=checks,
        output_message=output.strip() if passed else _fallback_message(source_record),
        blocked_reason=reason,
        reason=reason or "AI output passed money-safety checks.",
        used_fallback=not passed,
    )


_LAST_RESULT: GuardrailResult | None = None


def validate_route_execution(
    source_record: dict[str, Any],
    *,
    expected_amount: int | None = None,
    expected_link: str | None = None,
    selected_route: str | None = None,
) -> GuardrailResult:
    order = source_record.get("order") or {}
    recovery = source_record.get("recovery") or {}
    smart = source_record.get("smart_routing") or {}
    txn_id = str(source_record.get("transaction_id") or "")
    stored_amount = int(order.get("amount") or 0)
    locked_amount = int(recovery.get("locked_amount") or stored_amount)
    stored_link = str(recovery.get("payment_link") or recovery.get("alternate_link_generated") or "")
    canonical_link = f"https://rzp.io/demo/{txn_id}" if txn_id else ""
    state = str(source_record.get("state") or "")
    attempt_count = int(recovery.get("attempt_count") or 0)
    max_attempts = int(recovery.get("max_attempts") or 3)
    expires_at = _as_datetime(recovery.get("window_expires_at"))
    cooldown = set(recovery.get("cooldown_routes") or smart.get("cooldown_routes") or [])
    route = selected_route or str(smart.get("selected_route") or "")

    amount_ok = stored_amount == locked_amount
    if expected_amount is not None:
        amount_ok = amount_ok and expected_amount == stored_amount
    link_ok = bool(stored_link) and stored_link == canonical_link
    if expected_link is not None:
        link_ok = link_ok and expected_link == canonical_link
    if route == "PAYMENT_LINK":
        generated = str(recovery.get("alternate_link_generated") or stored_link)
        link_ok = link_ok and generated == canonical_link
    fraud_codes = {"ERR_FRAUD_SUSPECTED", "ERR_RISK_BLOCK"}
    error_code = str((source_record.get("routing") or {}).get("error_code") or "")
    fraud = error_code in fraud_codes
    amount_limit_ok = stored_amount <= 10000
    state_ok = is_active_recovery(TransactionState(state)) if state in {item.value for item in TransactionState} else False
    window_ok = expires_at is not None and _utcnow() < expires_at
    attempts_ok = attempt_count < max_attempts
    cooldown_ok = route not in cooldown if route else True
    route_ok = bool(route)

    checks = [
        GuardrailCheck(key="max_retries_not_exceeded", label="Max retries not exceeded", passed=attempts_ok),
        GuardrailCheck(key="not_flagged_fraud", label="Not flagged for fraud or risk", passed=not fraud),
        GuardrailCheck(key="amount_below_auto_recovery_limit", label="Amount below auto-recovery limit", passed=amount_limit_ok),
        GuardrailCheck(key="cooldown_period_elapsed", label="Cooldown period elapsed", passed=cooldown_ok),
        GuardrailCheck(key="amount", label="Transaction amount verified", passed=amount_ok),
        GuardrailCheck(key="link", label="Recovery link belongs to this transaction", passed=link_ok),
        GuardrailCheck(key="window", label="Recovery window valid", passed=window_ok),
        GuardrailCheck(key="state", label="Transaction is in automated recovery", passed=state_ok),
        GuardrailCheck(key="route", label="Selected route is still available", passed=route_ok and cooldown_ok),
    ]
    passed = all(check.passed for check in checks)
    reason = None
    if fraud:
        reason = "Risk/fraud flag blocked automated recovery."
    elif not amount_ok:
        reason = "Transaction amount mismatch."
    elif not passed:
        failed = [check.label for check in checks if not check.passed]
        reason = "Guardrail blocked route execution: " + ", ".join(failed).lower()
    return GuardrailResult(
        passed=passed,
        checks=checks,
        output_message="",
        blocked_reason=reason,
        reason=reason or "All recovery guardrails passed.",
        used_fallback=False,
    )


def last_guardrail_result() -> GuardrailResult | None:
    return _LAST_RESULT


def evaluate_guardrail(raw_llm_output: str, source_record: dict[str, Any]) -> GuardrailResult:
    global _LAST_RESULT
    _LAST_RESULT = _evaluate_guardrail(raw_llm_output, source_record)
    return _LAST_RESULT


def validate_ai_generated_payload(raw_llm_output: str, source_record: dict[str, Any]) -> str:
    """Deterministic money-safety validator.

    The AI may draft customer language. This function decides whether that
    draft may be used. On any failure it returns a fallback Hinglish message
    and must not be treated as authorization to move money.
    """
    result = evaluate_guardrail(raw_llm_output, source_record)
    if result.passed:
        return raw_llm_output.strip()
    return result.output_message

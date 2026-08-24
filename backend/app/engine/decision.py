"""Canonical recovery decision engine.

CircuitBreaker has one automated-decision pipeline. Phase 3 deterministic
rules, Phase 4 circuit breakers, and Phase 5 adaptive routing must not
make independent conflicting choices.

Decision precedence (hard safety ALWAYS overrides adaptive intelligence):

    1. HARD SAFETY / GUARDRAILS
    2. CIRCUIT BREAKER STATE
    3. ADAPTIVE POLICY
    4. HISTORICAL ROUTING SCORE
    5. DETERMINISTIC FALLBACK RULES

Adaptive logic may optimize among *safe* choices. It must never bypass:

* Fraud / risk blocks
* Maximum retry limits
* Invalid transactions
* Authentication failures (enforced at the API layer)
* Exhausted recovery windows
* Manual-review requirements
* Explicitly blocked rails
* Other hard safety constraints in ``evaluate_policy`` / ``validate_route_execution``

The persisted transaction terminal success state remains ``RECOVERED``.
Decision value ``RESCUED`` is the product explanation for that outcome
and is not a new enum member.

Policy versions are recorded as ``policy-v{n}`` at decision time and are
never rewritten on historical audit events.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.policies import PolicyDecision
from app.models import GuardrailResult, SmartRoutingState, Transaction

PRECEDENCE = (
    "HARD_SAFETY_GUARDRAILS",
    "CIRCUIT_BREAKER_STATE",
    "ADAPTIVE_POLICY",
    "HISTORICAL_ROUTING_SCORE",
    "DETERMINISTIC_FALLBACK_RULES",
)

DECISIONS = ("RETRY", "REROUTE", "HOLD", "ESCALATE", "RESCUED", "NO_ACTION")


class RecoveryDecision(BaseModel):
    transaction_id: str
    decision: str
    reason: str
    confidence: float = 0.0
    policy_version: str = "policy-v1"
    guardrail_result: str = "PENDING"
    selected_rail: str | None = None
    fallback_rails: list[str] = Field(default_factory=list)
    retry_number: int = 0
    expected_outcome: str = "RECOVERED"
    error_code: str = ""
    circuit_state: str = "CLOSED"
    primary_failure_rate: float | None = None
    historical_success_rate: float | None = None
    layer: str = PRECEDENCE[0]

    def as_audit(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "confidence": self.confidence,
            "policy_version": self.policy_version,
            "guardrail_result": self.guardrail_result,
            "selected_rail": self.selected_rail,
            "fallback_rails": list(self.fallback_rails),
            "retry_number": self.retry_number,
            "expected_outcome": self.expected_outcome,
            "error_code": self.error_code,
            "circuit_state": self.circuit_state,
            "layer": self.layer,
        }


def policy_version_label(version: int | None) -> str:
    return f"policy-v{int(version or 1)}"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    shown = value * 100 if value <= 1 else value
    return f"{shown:.0f}%"


def _build_reason(
    *,
    decision: str,
    error_code: str,
    primary_failure_rate: float | None,
    circuit_state: str,
    selected_rail: str | None,
    historical_success_rate: float | None,
    policy_version: str,
    guardrail_result: str,
    detail: str,
) -> str:
    return (
        f"Decision: {decision}\n"
        f"Reason: {detail}\n"
        f"Primary rail failure rate: {_pct(primary_failure_rate)}\n"
        f"Circuit state: {circuit_state}\n"
        f"Alternate rail: {selected_rail or 'n/a'}\n"
        f"Historical success rate: {_pct(historical_success_rate)}\n"
        f"Policy: {policy_version}\n"
        f"Guardrails: {guardrail_result}"
    )


def compose_recovery_decision(
    transaction: Transaction,
    *,
    policy: PolicyDecision | dict[str, Any],
    guard: GuardrailResult | None = None,
    blocked_rails: set[str] | None = None,
    thresholds: dict[str, Any] | None = None,
    learned: dict[str, dict[str, float | int]] | None = None,
    rescued: bool = False,
    no_eligible: bool = False,
    preemptive: bool = False,
    circuit_state: str | None = None,
    primary_failure_rate: float | None = None,
) -> RecoveryDecision:
    """Map already-evaluated safety + routing inputs onto one RecoveryDecision.

    Callers must evaluate layers in PRECEDENCE order. This function records
    *why* the resulting choice is safe, and which layer bound the outcome.
    """
    smart = transaction.smart_routing or SmartRoutingState()
    classification = smart.failure_classification
    strategy = (classification.strategy if classification else transaction.routing.recovery_strategy) or "RETRY"
    category = classification.category if classification else ""
    error_code = transaction.routing.error_code
    selected = smart.selected_route
    blocked = blocked_rails or set()
    resolved_circuit = circuit_state or ("OPEN" if selected and selected in blocked else "CLOSED")
    learned_row = (learned or {}).get(selected or "") or {}
    historical = learned_row.get("success_rate")
    historical_rate = float(historical) if historical is not None else None
    version = policy_version_label((thresholds or {}).get("version"))
    guard_status = "PASSED"
    if guard is not None:
        guard_status = "PASSED" if guard.passed else "BLOCKED"
    elif smart.guardrail_status in {"PASSED", "BLOCKED"}:
        guard_status = smart.guardrail_status

    policy_allowed = bool(policy.get("allowed")) if isinstance(policy, dict) else True
    policy_code = str(policy.get("code") or "") if isinstance(policy, dict) else "OK"
    policy_reason = str(policy.get("reason") or "") if isinstance(policy, dict) else ""

    layer = PRECEDENCE[4]
    decision = "RETRY"
    expected = "RECOVERED"
    detail = policy_reason or smart.reason or "Deterministic recovery policy selected an eligible rail."
    confidence = float(smart.confidence or 0.7)

    hard_block = (
        not policy_allowed
        or guard_status == "BLOCKED"
        or no_eligible
        or strategy in {"HOLD", "BLOCK"}
        or category in {"CUSTOMER_FUNDS_FAILURE", "RISK_FAILURE"}
    )

    if rescued:
        decision = "RESCUED"
        expected = "RECOVERED"
        layer = PRECEDENCE[4]
        detail = f"Payment recovered on {selected or 'selected rail'}."
        confidence = max(confidence, 0.9)
    elif category == "RISK_FAILURE" or strategy == "BLOCK" or policy_code == "HIGH_RISK":
        decision = "ESCALATE"
        expected = "ESCALATED"
        layer = PRECEDENCE[0]
        detail = policy_reason or "Risk/fraud flag blocked automated recovery."
        confidence = 1.0
    elif category == "CUSTOMER_FUNDS_FAILURE" or strategy == "HOLD":
        decision = "HOLD"
        expected = "ESCALATED"
        layer = PRECEDENCE[0]
        detail = policy_reason or "Hard decline: same-rail retry is not allowed."
        confidence = 1.0
    elif policy_code in {"WINDOW_EXPIRED", "ATTEMPTS_EXHAUSTED", "AMOUNT_LIMIT", "NOT_RECOVERABLE"}:
        decision = "ESCALATE"
        expected = "ESCALATED"
        layer = PRECEDENCE[0]
        detail = policy_reason or "Hard safety constraint blocked automated recovery."
        confidence = 1.0
    elif guard_status == "BLOCKED":
        decision = "ESCALATE"
        expected = "ESCALATED"
        layer = PRECEDENCE[0]
        detail = (guard.blocked_reason if guard else None) or policy_reason or "Guardrail blocked automated recovery."
        confidence = 1.0
    elif no_eligible or (selected == "MANUAL_REVIEW" and hard_block):
        decision = "ESCALATE"
        expected = "ESCALATED"
        layer = PRECEDENCE[0]
        detail = policy_reason or "No eligible automated recovery route remains."
        confidence = 0.9
    elif selected and selected in blocked:
        decision = "REROUTE"
        expected = "RECOVERED"
        layer = PRECEDENCE[1]
        detail = f"Circuit OPEN on {selected}. Adaptive scores may only choose among remaining closed rails."
        resolved_circuit = "OPEN"
    elif preemptive:
        decision = "REROUTE"
        expected = "RECOVERED"
        layer = PRECEDENCE[2]
        detail = smart.reason or "Adaptive policy predicted primary-rail failure and selected an alternate."
    elif strategy == "REROUTE" or transaction.recovery.attempt_count > 0:
        decision = "REROUTE"
        expected = "RECOVERED"
        layer = PRECEDENCE[3] if (learned or {}) else PRECEDENCE[4]
        detail = smart.reason or f"{error_code} detected on primary rail."
    elif strategy == "RETRY":
        decision = "RETRY"
        expected = "RECOVERED"
        layer = PRECEDENCE[3] if (learned or {}) else PRECEDENCE[4]
        detail = smart.reason or f"{error_code} classified as transient. Same-family retry is eligible."
    else:
        decision = "NO_ACTION"
        expected = transaction.state.value
        layer = PRECEDENCE[0]
        detail = policy_reason or "No automated recovery action is available."

    fallbacks = [row.route for row in smart.alternatives if row.route != selected]
    reason = _build_reason(
        decision=decision,
        error_code=error_code,
        primary_failure_rate=primary_failure_rate,
        circuit_state=resolved_circuit,
        selected_rail=selected,
        historical_success_rate=historical_rate,
        policy_version=version,
        guardrail_result=guard_status,
        detail=f"{error_code} detected on primary rail. {detail}".strip(),
    )
    return RecoveryDecision(
        transaction_id=transaction.transaction_id,
        decision=decision,
        reason=reason,
        confidence=confidence,
        policy_version=version,
        guardrail_result=guard_status,
        selected_rail=selected,
        fallback_rails=fallbacks,
        retry_number=transaction.recovery.attempt_count,
        expected_outcome=expected,
        error_code=error_code,
        circuit_state=resolved_circuit,
        primary_failure_rate=primary_failure_rate,
        historical_success_rate=historical_rate,
        layer=layer,
    )


def stamp_decision(transaction: Transaction, decision: RecoveryDecision) -> None:
    if transaction.smart_routing is None:
        transaction.smart_routing = SmartRoutingState()
    transaction.smart_routing.last_decision = decision.as_audit()
    transaction.smart_routing.policy_version = decision.policy_version
    transaction.smart_routing.guardrail_status = decision.guardrail_result

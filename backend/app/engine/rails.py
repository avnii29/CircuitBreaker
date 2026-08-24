"""Payment-rail abstraction.

The recovery engine depends on ``PaymentRail``, not on a simulator
implementation. The current project remains simulation-only:
``SimulatedRail`` is the only adapter. A future production adapter can
implement the same protocol without rewriting recovery decisions,
guardrails, or the state machine.

Do not import this module's simulator internals from decision, policy,
circuit-breaker, or guardrail code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.engine.failure_classifier import classify_failure
from app.models import SmartRoutingState, Transaction


@dataclass(frozen=True)
class RailAttemptResult:
    succeeded: bool
    reason: str
    simulated: bool = True


class PaymentRail(Protocol):
    name: str

    async def attempt(self, transaction: Transaction, route_id: str) -> RailAttemptResult:
        """Execute one recovery attempt on ``route_id``."""


def _ensure_smart(transaction: Transaction) -> SmartRoutingState:
    if transaction.smart_routing is None:
        transaction.smart_routing = SmartRoutingState(
            force_route_failure=transaction.recovery.force_route_failure,
            demo_scenario=transaction.demo_scenario,
        )
    return transaction.smart_routing


def simulate_route_outcome(transaction: Transaction, route_id: str) -> bool:
    """Deterministic *simulation* outcome keyed off error classification.

    This is not a recovery decision. Guardrails, circuit state, and
    adaptive policy decide whether the attempt is allowed; this function
    only answers what a simulated rail would return.
    """
    smart = _ensure_smart(transaction)
    if smart.force_route_failure or transaction.recovery.force_route_failure:
        return False
    if route_id == "MANUAL_REVIEW":
        return False
    classification = classify_failure(transaction.routing.error_code)
    strategy = classification.get("strategy") or "RETRY"
    category = classification["category"]
    if category in {"CUSTOMER_FUNDS_FAILURE", "RISK_FAILURE"} or strategy in {"HOLD", "BLOCK"}:
        return False
    if strategy == "REROUTE" or category in {"BANK_OR_NETWORK_UNAVAILABLE", "RAIL_OUTAGE"}:
        recommended = list(classification.get("recommended_routes") or [])
        primary = recommended[0] if recommended else "UPI_RETRY"
        if smart.preemptive and route_id != "UPI_RETRY":
            return True
        if route_id != primary and route_id != "UPI_RETRY":
            return True
        return transaction.recovery.attempt_count >= 1
    return True


class SimulatedRail:
    """In-process rail used by demo and tests. Not a production processor."""

    name = "simulated"

    async def attempt(self, transaction: Transaction, route_id: str) -> RailAttemptResult:
        succeeded = simulate_route_outcome(transaction, route_id)
        if succeeded:
            reason = f"{route_id} recovered the payment."
        else:
            reason = f"{route_id} failed. Evaluating an alternate route."
        return RailAttemptResult(succeeded=succeeded, reason=reason, simulated=True)


def get_payment_rail() -> PaymentRail:
    return SimulatedRail()

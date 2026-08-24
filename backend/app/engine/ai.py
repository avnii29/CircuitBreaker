from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.engine.diagnostic import SCENARIOS, resolve_scenario
from app.formatting import rupee
from app.models import Transaction


@dataclass(frozen=True)
class AIRecommendation:
    recommendation: str
    confidence: float
    customer_message: str
    raw_output: str
    simulated: bool = True


class RecoveryAdvisor(ABC):
    """Interface for recovery copy + intervention recommendation.

    A live LLM provider can be introduced behind this contract without
    changing execution or guardrail code. The advisor never moves money.
    """

    @abstractmethod
    def generate(self, transaction: Transaction) -> AIRecommendation:
        raise NotImplementedError


class SimulatedRecoveryAdvisor(RecoveryAdvisor):
    def generate(self, transaction: Transaction) -> AIRecommendation:
        scenario_key = next(
            (
                key
                for key, definition in SCENARIOS.items()
                if definition["error_code"] == transaction.routing.error_code
            ),
            "U30",
        )
        _, definition = resolve_scenario(transaction.routing.bank, scenario_key)
        amount = rupee(transaction.order.amount)
        name = transaction.customer.name.split(" ")[0]
        link = transaction.recovery.payment_link
        txn_id = transaction.transaction_id
        message = (
            f"Hi {name}! Aapka {amount} payment bank-side technical issue ki wajah se complete nahi ho paya. "
            f"Aapka order temporarily secure hai. Neeche diye gaye recovery link se payment complete "
            f"kar sakte hain: {link} (ref {txn_id})"
        )
        return AIRecommendation(
            recommendation=definition["recommendation"],
            confidence=definition["confidence"],
            customer_message=message,
            raw_output=message,
            simulated=True,
        )


def build_advisor(provider: str) -> RecoveryAdvisor:
    normalized = (provider or "simulated").strip().lower()
    if normalized in {"simulated", "simulation", "demo", "none"}:
        return SimulatedRecoveryAdvisor()
    return SimulatedRecoveryAdvisor()


advisor = build_advisor("simulated")

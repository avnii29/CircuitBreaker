"""Hard-safety recovery policy (precedence layer 1).

``evaluate_policy`` is a deterministic gate. Adaptive scoring in
``routing_engine`` / ``policy.py`` must not run as a competing decision
maker: those layers may only optimize among choices this function still
allows.

See ``app.engine.decision.PRECEDENCE``.
"""

from __future__ import annotations

from typing import TypedDict

MAX_AUTOMATED_AMOUNT = 10000
MAX_ATTEMPTS = 3
MIN_ROUTE_SCORE = 60


class PolicyDecision(TypedDict):
    allowed: bool
    reason: str
    code: str


def evaluate_policy(
    *,
    amount: int,
    attempt_count: int,
    window_expired: bool,
    recoverable: bool,
    route_score: float | None,
    high_risk: bool,
    max_attempts: int = MAX_ATTEMPTS,
    amount_limit: int = MAX_AUTOMATED_AMOUNT,
) -> PolicyDecision:
    if window_expired:
        return {
            "allowed": False,
            "code": "WINDOW_EXPIRED",
            "reason": "Recovery window expired.",
        }
    if not recoverable:
        return {
            "allowed": False,
            "code": "NOT_RECOVERABLE",
            "reason": "Failure classification is not eligible for automated recovery.",
        }
    if high_risk:
        return {
            "allowed": False,
            "code": "HIGH_RISK",
            "reason": "Transaction risk requires human review.",
        }
    if amount > amount_limit:
        return {
            "allowed": False,
            "code": "AMOUNT_LIMIT",
            "reason": "Transaction exceeds automated recovery policy limit.",
        }
    if attempt_count >= max_attempts:
        return {
            "allowed": False,
            "code": "ATTEMPTS_EXHAUSTED",
            "reason": "Maximum recovery attempts have been reached.",
        }
    if route_score is not None and route_score < MIN_ROUTE_SCORE:
        return {
            "allowed": False,
            "code": "LOW_SCORE",
            "reason": "Selected route score is below the automated recovery threshold.",
        }
    return {
        "allowed": True,
        "code": "OK",
        "reason": "Transaction satisfies automated recovery policy.",
    }

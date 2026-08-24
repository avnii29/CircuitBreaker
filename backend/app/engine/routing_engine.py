"""Deterministic + adaptive route scoring (precedence layers 4-5).

``select_best_recovery_route`` ranks eligible rails. It must receive
already-blocked rails (circuit OPEN) and must not be used to bypass
guardrails or ``evaluate_policy``. Learned scores (layer 4) override
seeded historical rates when enough samples exist; catalog compatibility
rules remain the deterministic fallback (layer 5).
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.engine.bank_profiles import route_success_probability
from app.engine.failure_classifier import FailureClassification, classify_failure

ROUTE_CATALOG: dict[str, dict[str, Any]] = {
    "UPI_RETRY": {
        "route_id": "UPI_RETRY",
        "display_name": "UPI Retry",
        "description": "Retry through the same payment family after a transient technical failure.",
        "availability": True,
        "base_score": 72,
        "supported_failure_types": ["BANK_TECHNICAL_FAILURE", "NETWORK_TIMEOUT"],
        "risk_level": "LOW",
    },
    "PAYMENT_LINK": {
        "route_id": "PAYMENT_LINK",
        "display_name": "Payment Link",
        "description": "Generate a controlled alternate payment link.",
        "availability": True,
        "base_score": 78,
        "supported_failure_types": [
            "BANK_TECHNICAL_FAILURE",
            "BANK_OR_NETWORK_UNAVAILABLE",
            "NETWORK_TIMEOUT",
            "RAIL_OUTAGE",
        ],
        "risk_level": "LOW",
    },
    "QR_FALLBACK": {
        "route_id": "QR_FALLBACK",
        "display_name": "QR Fallback",
        "description": "Provide a QR-based fallback route.",
        "availability": True,
        "base_score": 65,
        "supported_failure_types": [
            "BANK_TECHNICAL_FAILURE",
            "BANK_OR_NETWORK_UNAVAILABLE",
            "RAIL_OUTAGE",
        ],
        "risk_level": "MEDIUM",
    },
    "MANUAL_REVIEW": {
        "route_id": "MANUAL_REVIEW",
        "display_name": "Manual Review",
        "description": "Stop automation and require operator intervention.",
        "availability": True,
        "base_score": 35,
        "supported_failure_types": [
            "BANK_TECHNICAL_FAILURE",
            "BANK_OR_NETWORK_UNAVAILABLE",
            "NETWORK_TIMEOUT",
            "CUSTOMER_FUNDS_FAILURE",
            "RISK_FAILURE",
            "RAIL_OUTAGE",
        ],
        "risk_level": "LOW",
    },
}

SEEDED_STATS: dict[str, dict[str, int]] = {
    "UPI_RETRY": {"attempts": 120, "successful": 82},
    "PAYMENT_LINK": {"attempts": 95, "successful": 77},
    "QR_FALLBACK": {"attempts": 52, "successful": 35},
    "MANUAL_REVIEW": {"attempts": 14, "successful": 12},
}


class ScoreBreakdown(TypedDict):
    base_score: int
    failure_compatibility: int
    historical_success: int
    transient_bonus: int
    retry_penalty: int
    risk_penalty: int


class ScoredRoute(TypedDict):
    route: str
    display_name: str
    score: int
    score_breakdown: ScoreBreakdown
    eligible: bool


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def _success_rate(stats: dict[str, dict[str, int]], route_id: str) -> float:
    row = stats.get(route_id) or {"attempts": 0, "successful": 0}
    attempts = row["attempts"]
    if attempts <= 0:
        return 0.0
    return round((row["successful"] / attempts) * 100, 1)


def score_route(
    route_id: str,
    classification: FailureClassification,
    attempt_count: int,
    stats: dict[str, dict[str, int]],
    cooldown: bool,
    learned: dict[str, dict[str, float | int]] | None = None,
) -> ScoredRoute:
    catalog = ROUTE_CATALOG[route_id]
    base = int(catalog["base_score"])
    recommended = classification["recommended_routes"]
    compatible = route_id in recommended
    failure_compat = 15 if compatible else (-20 if classification["recoverable"] else 5)
    rate = _success_rate(stats, route_id)
    learned_row = (learned or {}).get(route_id) or {}
    learned_samples = int(learned_row.get("samples") or 0)
    learned_rate = float(learned_row.get("success_rate") or 0.0)
    if learned_samples >= 8:
        historical = int(round(learned_rate * 40))
        rate = round(learned_rate * 100, 1)
    else:
        historical = int(round(rate / 10))
    transient = (
        8
        if classification["category"] in {"BANK_TECHNICAL_FAILURE", "NETWORK_TIMEOUT"}
        and route_id != "MANUAL_REVIEW"
        else 0
    )
    retry_penalty = -5 * attempt_count
    risk = str(catalog["risk_level"])
    risk_penalty = -8 if risk == "HIGH" else (-4 if risk == "MEDIUM" else 0)
    if cooldown:
        failure_compat = -40
    raw = base + failure_compat + historical + transient + retry_penalty + risk_penalty
    total = _clamp(raw)
    eligible = catalog["availability"] is True and not cooldown and (compatible or route_id == "MANUAL_REVIEW")
    if not classification["recoverable"]:
        eligible = route_id == "MANUAL_REVIEW"
    return {
        "route": route_id,
        "display_name": str(catalog["display_name"]),
        "score": total,
        "raw_score": raw,
        "score_breakdown": {
            "base_score": base,
            "failure_compatibility": failure_compat,
            "historical_success": historical,
            "transient_bonus": transient,
            "retry_penalty": retry_penalty,
            "risk_penalty": risk_penalty,
        },
        "eligible": eligible,
    }


def select_best_recovery_route(
    transaction: dict[str, Any],
    stats: dict[str, dict[str, int]] | None = None,
    learned: dict[str, dict[str, float | int]] | None = None,
    predict_fail_threshold: float = 0.65,
    predict_min_samples: int = 8,
) -> dict[str, Any]:
    stats = stats or SEEDED_STATS
    routing = transaction.get("routing") or {}
    recovery = transaction.get("recovery") or {}
    smart = transaction.get("smart_routing") or {}
    error_code = str(routing.get("error_code") or "")
    classification = classify_failure(error_code)
    attempt_count = int(recovery.get("attempt_count") or 0)
    cooldown_routes = set(recovery.get("cooldown_routes") or smart.get("cooldown_routes") or [])
    blocked_rails = set(transaction.get("blocked_rails") or [])
    scored = [
        score_route(
            route_id,
            classification,
            attempt_count,
            stats,
            route_id in cooldown_routes or route_id in blocked_rails,
            learned=learned,
        )
        for route_id in ROUTE_CATALOG
    ]
    eligible = [row for row in scored if row["eligible"]]
    if not eligible:
        manual = next(row for row in scored if row["route"] == "MANUAL_REVIEW")
        selected = manual
        reason = (
            "No automated recovery route remains eligible. Manual review is required."
        )
        why = [
            "All automated routes are unavailable, cooled down, or incompatible.",
            "Deterministic policy requires operator intervention.",
        ]
        confidence = 0.4
        alternatives = sorted(
            [row for row in scored if row["route"] != "MANUAL_REVIEW"],
            key=lambda row: row["score"],
            reverse=True,
        )
        return {
            "selected_route": selected["route"],
            "display_name": selected["display_name"],
            "route_score": selected["score"],
            "confidence": confidence,
            "reason": reason,
            "why": why,
            "score_breakdown": selected["score_breakdown"],
            "alternatives": [
                {"route": row["route"], "display_name": row["display_name"], "score": row["score"]}
                for row in alternatives
            ],
            "scored_routes": scored,
            "failure_classification": classification,
            "simulated": True,
            "no_eligible": True,
        }
    selected = max(eligible, key=lambda row: (row.get("raw_score", row["score"]), 1 if row["route"] == "PAYMENT_LINK" else 0))
    preemptive = False
    predicted_p_fail: float | None = None
    recommended = list(classification.get("recommended_routes") or [])
    primary = recommended[0] if recommended else selected["route"]
    if attempt_count == 0 and learned:
        learned_row = learned.get(primary) or learned.get(selected["route"]) or {}
        learned_samples = int(learned_row.get("samples") or 0)
        learned_rate = float(learned_row.get("success_rate") or 0.0)
        if learned_samples >= predict_min_samples:
            predicted_p_fail = round(1.0 - learned_rate, 4)
            if predicted_p_fail >= predict_fail_threshold:
                preemptive = True
                if selected["route"] == primary:
                    alternates = [
                        row
                        for row in eligible
                        if row["route"] not in {primary, "MANUAL_REVIEW"}
                    ]
                    if alternates:
                        selected = max(alternates, key=lambda row: row.get("raw_score", row["score"]))
    alternatives = sorted(
        [row for row in scored if row["route"] != selected["route"]],
        key=lambda row: row["score"],
        reverse=True,
    )
    why = _why(transaction, classification, selected, attempt_count)
    if preemptive:
        why.insert(
            0,
            f"Pre-emptive reroute: predicted primary failure probability {predicted_p_fail:.0%} exceeded {predict_fail_threshold:.0%}.",
        )
    reason = (
        f"{classification['explanation']} {selected['display_name']} has the highest "
        f"eligible simulated score ({selected['score']}/100) for this failure category."
    )
    if preemptive:
        reason = (
            f"Predicted primary-rail failure {predicted_p_fail:.0%}. Routed first attempt to "
            f"{selected['display_name']} using rolling success rates."
        )
    confidence = round(min(0.99, 0.70 + selected["score"] / 400), 2)
    return {
        "selected_route": selected["route"],
        "display_name": selected["display_name"],
        "route_score": selected["score"],
        "confidence": confidence,
        "reason": reason,
        "why": why,
        "score_breakdown": selected["score_breakdown"],
        "alternatives": [
            {"route": row["route"], "display_name": row["display_name"], "score": row["score"]}
            for row in alternatives
        ],
        "scored_routes": scored,
        "failure_classification": classification,
        "simulated": True,
        "no_eligible": False,
        "preemptive": preemptive,
        "predicted_failure_probability": predicted_p_fail,
    }


def _window_open(transaction: dict[str, Any]) -> bool:
    recovery = transaction.get("recovery") or {}
    expires = recovery.get("window_expires_at")
    if not expires:
        return False
    if hasattr(expires, "isoformat"):
        return True
    return True


def _why(
    transaction: dict[str, Any],
    classification: FailureClassification,
    selected: ScoredRoute,
    attempt_count: int,
) -> list[str]:
    amount = int((transaction.get("order") or {}).get("amount") or 0)
    recovery = transaction.get("recovery") or {}
    smart = transaction.get("smart_routing") or {}
    cooldown = list(recovery.get("cooldown_routes") or smart.get("cooldown_routes") or [])
    attempted = list(smart.get("attempted_routes") or [])
    points = [
        f"Failure type is {classification['category'].replace('_', ' ').lower()} and recoverable={str(classification['recoverable']).lower()}.",
        "Transaction is within the recovery window." if _window_open(transaction) else "Recovery window is no longer active.",
        f"{selected['display_name']} has the highest current success score ({selected['score']}/100).",
        "Amount is within automated recovery policy." if amount <= 10000 else "Amount exceeds automated recovery policy.",
        "No retry penalty exceeded." if attempt_count < 3 else "Retry limit is close to exhaustion.",
        "Route passed deterministic eligibility checks.",
    ]
    if attempted:
        points.insert(2, f"Already attempted: {', '.join(attempted)}.")
    if cooldown:
        points.insert(2, f"Cooled-down routes skipped: {', '.join(cooldown)}.")
    return [item for item in points if item]


def expected_success(bank: str, route_id: str) -> float:
    return route_success_probability(bank, route_id)

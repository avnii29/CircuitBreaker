"""Simulated intervention economics for the revenue recovery engine.

All probabilities, costs, and counterfactuals are deterministic and labeled
as simulated. They are not real-world bank observations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import SmartRoutingState, Transaction, TransactionState

PAYMENT_FAILURE = "PAYMENT_FAILURE"
CHECKOUT_ABANDONMENT = "CHECKOUT_ABANDONMENT"
SUBSCRIPTION_FAILURE = "SUBSCRIPTION_FAILURE"
OVERDUE_RECEIVABLE = "OVERDUE_RECEIVABLE"

EVENT_ALIASES = {
    "CHECKOUT_ABANDONMENT": CHECKOUT_ABANDONMENT,
    "SUBSCRIPTION_FAILURE": SUBSCRIPTION_FAILURE,
    "OVERDUE_RECEIVABLE": OVERDUE_RECEIVABLE,
    "GOLDEN_OUTAGE": PAYMENT_FAILURE,
    "BANK_OUTAGE": PAYMENT_FAILURE,
    "BANK_DOWN": PAYMENT_FAILURE,
    "TRANSIENT_FAILURE": PAYMENT_FAILURE,
    "LOW_VALUE": PAYMENT_FAILURE,
}

SIMULATED_INTERVENTIONS = {
    "CUSTOMER_REMINDER",
    "PAYMENT_METHOD_NUDGE",
    "RETRY_LATER",
    "COLLECTION_FOLLOWUP",
}

COSTS = {
    "SAME_RAIL_RETRY": 12,
    "ALTERNATE_RAIL": 18,
    "CUSTOMER_REMINDER": 8,
    "PAYMENT_METHOD_NUDGE": 10,
    "RETRY_LATER": 6,
    "COLLECTION_FOLLOWUP": 15,
    "HOLD": 4,
    "ESCALATE": 6,
}

NATURAL_RECOVERY_RATE = 0.18
LOW_VALUE_THRESHOLD = 80


def event_type_for(transaction: Transaction) -> str:
    key = (transaction.demo_scenario or "").strip().upper()
    return EVENT_ALIASES.get(key, PAYMENT_FAILURE)


def window_recovery_probability(elapsed_ratio: float) -> float:
    """Deterministic decay. elapsed_ratio 0 = window start, 1 = window end.

    Compressed demo windows map onto the published simulated curve:
    0 min 82%, 5 min 74%, 15 min 61%, 30 min 42%, 2 hr 17%.
    These are simulation assumptions, not real-world statistics.
    """
    progress = max(0.0, elapsed_ratio)
    if progress <= 0:
        return 0.82
    if progress >= 4.0:
        return 0.17
    if progress >= 1.0:
        return round(0.42 - min(progress - 1.0, 3.0) * (0.42 - 0.17) / 3.0, 4)
    return round(0.82 - progress * (0.82 - 0.42), 4)


def _clamp(value: float, low: float = 0.05, high: float = 0.95) -> float:
    return max(low, min(high, value))


def _predicted_loss_probability(kind: str, strategy: str, window_p: float) -> float:
    """Simulated chance the revenue is lost if CircuitBreaker does not act.

    Priors are demo assumptions, not real-world loss rates. Window aging
    raises loss risk as recoverability decays.
    """
    if kind == CHECKOUT_ABANDONMENT:
        prior = 0.68
    elif kind == SUBSCRIPTION_FAILURE:
        prior = 0.74
    elif kind == OVERDUE_RECEIVABLE:
        prior = 0.70
    elif strategy in {"REROUTE", "BLOCK"}:
        prior = 0.81
    elif strategy == "HOLD":
        prior = 0.55
    else:
        prior = 0.64
    aged = prior + (0.82 - window_p) * 0.25
    return round(_clamp(aged, 0.20, 0.95), 4)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ratio(transaction: Transaction) -> float:
    window = max(int(transaction.recovery.window_seconds or 1), 1)
    started = transaction.recovery.window_started_at
    failed = transaction.failed_at or started
    elapsed = (_utcnow() - failed).total_seconds()
    return elapsed / window


def _econ(transaction: Transaction) -> dict[str, Any]:
    if transaction.smart_routing is None:
        return {}
    payload = transaction.smart_routing.economics
    return payload if isinstance(payload, dict) else {}


def evaluate_interventions(transaction: Transaction, *, learned: dict | None = None) -> dict[str, Any]:
    amount = int(transaction.order.amount)
    kind = event_type_for(transaction)
    elapsed = _elapsed_ratio(transaction)
    window_p = window_recovery_probability(elapsed)
    classification = transaction.smart_routing.failure_classification if transaction.smart_routing else None
    recoverable = True if classification is None else bool(classification.recoverable)
    strategy = (classification.strategy if classification else transaction.routing.recovery_strategy) or "RETRY"
    historical = 0.0
    if learned and transaction.smart_routing and transaction.smart_routing.selected_route:
        row = learned.get(transaction.smart_routing.selected_route) or {}
        raw = row.get("success_rate")
        if raw is not None:
            historical = float(raw)
            if historical > 1:
                historical = historical / 100.0
    rail_bonus = historical * 0.15 if historical else 0.0

    def candidate(action: str, label: str, base_p: float, cost_key: str, risk: int = 0) -> dict[str, Any]:
        probability = _clamp(base_p * window_p + rail_bonus)
        expected = int(round(amount * probability))
        cost = int(COSTS[cost_key])
        net = expected - cost - risk
        return {
            "id": action,
            "label": label,
            "predicted_success_probability": round(probability, 4),
            "expected_recovery_value": expected,
            "intervention_cost": cost,
            "risk_penalty": risk,
            "net_expected_value": net,
            "simulated": True,
        }

    if kind == CHECKOUT_ABANDONMENT:
        options = [
            candidate("CUSTOMER_REMINDER", "Customer reminder", 0.72, "CUSTOMER_REMINDER"),
            candidate("PAYMENT_METHOD_NUDGE", "Payment method nudge", 0.64, "PAYMENT_METHOD_NUDGE"),
            candidate("RETRY_LATER", "Wait and retry", 0.41, "RETRY_LATER"),
            candidate("ESCALATE", "Escalate", 0.22, "ESCALATE", risk=20),
        ]
    elif kind == SUBSCRIPTION_FAILURE:
        options = [
            candidate("SAME_RAIL_RETRY", "Retry", 0.58, "SAME_RAIL_RETRY"),
            candidate("ALTERNATE_RAIL", "Alternate rail", 0.76, "ALTERNATE_RAIL"),
            candidate("RETRY_LATER", "Retry later", 0.44, "RETRY_LATER"),
            candidate("CUSTOMER_REMINDER", "Customer nudge", 0.51, "CUSTOMER_REMINDER"),
            candidate("ESCALATE", "Escalate", 0.20, "ESCALATE", risk=15),
        ]
    elif kind == OVERDUE_RECEIVABLE:
        options = [
            candidate("CUSTOMER_REMINDER", "Reminder", 0.48, "CUSTOMER_REMINDER"),
            candidate("COLLECTION_FOLLOWUP", "Follow-up", 0.61, "COLLECTION_FOLLOWUP"),
            candidate("ESCALATE", "Escalate", 0.28, "ESCALATE", risk=40),
        ]
    else:
        retry_p = 0.38 if strategy == "REROUTE" else 0.55
        reroute_p = 0.78 if strategy == "REROUTE" else 0.66
        options = [
            candidate("SAME_RAIL_RETRY", "Same rail retry", retry_p, "SAME_RAIL_RETRY"),
            candidate("ALTERNATE_RAIL", "Alternate rail", reroute_p, "ALTERNATE_RAIL"),
            candidate("CUSTOMER_REMINDER", "Customer reminder", 0.50, "CUSTOMER_REMINDER"),
            candidate("HOLD", "Hold for review", 0.12, "HOLD", risk=10),
            candidate("ESCALATE", "Escalate", 0.18, "ESCALATE", risk=25),
        ]

    if not recoverable or strategy in {"HOLD", "BLOCK"}:
        for row in options:
            if row["id"] not in {"ESCALATE", "HOLD"}:
                row["net_expected_value"] = -10_000
                row["predicted_success_probability"] = 0.05
                row["expected_recovery_value"] = int(round(amount * 0.05))

    ranked = sorted(options, key=lambda row: row["net_expected_value"], reverse=True)
    best = ranked[0]
    predicted_loss = _predicted_loss_probability(kind, strategy, window_p)
    without_expected = int(round(amount * NATURAL_RECOVERY_RATE))

    if not recoverable or strategy == "BLOCK":
        selected_action_id = "ESCALATE"
        selected = next(row for row in ranked if row["id"] == "ESCALATE")
    elif strategy == "HOLD":
        selected_action_id = "ESCALATE"
        selected = next((row for row in ranked if row["id"] in {"HOLD", "ESCALATE"}), best)
    elif amount <= LOW_VALUE_THRESHOLD or best["net_expected_value"] < 0:
        selected_action_id = "DO_NOTHING"
        selected = best
    elif best["id"] == "ESCALATE":
        selected_action_id = "ESCALATE"
        selected = best
    else:
        selected_action_id = "ACT"
        selected = best

    avoided = 0
    if selected_action_id == "DO_NOTHING":
        avoided = max(int(selected["intervention_cost"]), 0)
        rationale = (
            f"Recovery intentionally skipped. Expected recovery value ₹{selected['expected_recovery_value']} "
            f"did not justify simulated intervention cost ₹{selected['intervention_cost']}."
        )
    elif selected_action_id == "ESCALATE":
        rationale = (
            f"{transaction.routing.error_code or kind} requires review. "
            f"Automated recovery is not the highest-value safe action."
        )
    else:
        rationale = (
            f"{selected['label']} has the highest simulated net expected recovery value "
            f"(₹{selected['net_expected_value']}) within guardrail limits."
        )

    urgency = max(0.0, 1.0 - min(elapsed, 1.5) / 1.5)
    priority = int(
        amount * selected["predicted_success_probability"] * (0.4 + 0.6 * urgency) / 100
        - selected["intervention_cost"]
    )
    if selected_action_id == "DO_NOTHING":
        priority = -abs(priority) - 1

    return {
        "event_type": kind,
        "revenue_at_risk": amount,
        "root_cause": transaction.routing.diagnosis or transaction.routing.error_label or kind,
        "predicted_loss_probability": predicted_loss,
        "window_recovery_probability": window_p,
        "candidates": ranked,
        "selected_action": selected_action_id,
        "selected_intervention": selected["id"],
        "predicted_success_probability": selected["predicted_success_probability"],
        "expected_recovery_value": selected["expected_recovery_value"],
        "intervention_cost": 0 if selected_action_id == "DO_NOTHING" else selected["intervention_cost"],
        "risk_penalty": selected["risk_penalty"],
        "net_expected_value": selected["net_expected_value"],
        "actual_recovered": int(transaction.money_recovered or 0),
        "counterfactual": {
            "label": "SIMULATED BASELINE",
            "without_recovery_rate": NATURAL_RECOVERY_RATE,
            "without_expected": without_expected,
            "with_expected": selected["expected_recovery_value"],
            "incremental_expected": selected["expected_recovery_value"] - without_expected,
        },
        "cost_avoided": avoided,
        "rationale": rationale,
        "priority_score": priority,
        "simulated": True,
        "guardrail_result": (
            transaction.recovery.guardrail.passed
            if transaction.recovery.guardrail is not None
            else None
        ),
    }


def stamp_economics(
    transaction: Transaction,
    payload: dict[str, Any] | None = None,
    *,
    learned: dict | None = None,
) -> dict[str, Any]:
    if transaction.smart_routing is None:
        transaction.smart_routing = SmartRoutingState()
    existing = transaction.smart_routing.economics if isinstance(transaction.smart_routing.economics, dict) else None
    economics = payload or existing or evaluate_interventions(transaction, learned=learned)
    economics["actual_recovered"] = int(transaction.money_recovered or 0)
    counterfactual = economics.setdefault(
        "counterfactual",
        {
            "label": "SIMULATED BASELINE",
            "without_recovery_rate": NATURAL_RECOVERY_RATE,
            "without_expected": int(round(transaction.order.amount * NATURAL_RECOVERY_RATE)),
        },
    )
    if transaction.money_recovered:
        without_expected = int(counterfactual.get("without_expected") or 0)
        economics["net_revenue_protected"] = max(
            transaction.money_recovered - int(economics.get("intervention_cost") or 0),
            0,
        )
        counterfactual["incremental_actual"] = max(transaction.money_recovered - without_expected, 0)
    elif economics.get("selected_action") == "DO_NOTHING":
        economics["net_revenue_protected"] = int(economics.get("cost_avoided") or 0)
    else:
        economics["net_revenue_protected"] = 0
    if transaction.recovery.guardrail is not None:
        economics["guardrail_result"] = bool(transaction.recovery.guardrail.passed)
    transaction.smart_routing.economics = economics
    if economics.get("rationale") and not transaction.smart_routing.reason:
        transaction.smart_routing.reason = str(economics["rationale"])
    return economics


def selected_action(transaction: Transaction) -> str:
    return str(_econ(transaction).get("selected_action") or "")


def uses_simulated_path(transaction: Transaction) -> bool:
    payload = _econ(transaction)
    if payload.get("selected_action") != "ACT":
        return False
    intervention = str(payload.get("selected_intervention") or "")
    if event_type_for(transaction) != PAYMENT_FAILURE:
        return True
    return intervention in SIMULATED_INTERVENTIONS


def snapshot_metrics(txns: list[Transaction]) -> dict[str, Any]:
    leakage_total = sum(txn.order.amount for txn in txns)
    recovered = [txn for txn in txns if txn.state == TransactionState.RECOVERED]
    recovered_amount = sum(txn.money_recovered or txn.order.amount for txn in recovered)
    intervention_cost = 0
    cost_avoided = 0
    act = 0
    skip = 0
    escalate = 0
    by_type: dict[str, dict[str, int]] = {}
    for txn in txns:
        payload = _econ(txn)
        kind = str(payload.get("event_type") or event_type_for(txn))
        bucket = by_type.setdefault(kind, {"count": 0, "amount": 0, "recovered": 0})
        bucket["count"] += 1
        bucket["amount"] += txn.order.amount
        if txn.state == TransactionState.RECOVERED:
            bucket["recovered"] += txn.money_recovered or txn.order.amount
        action = str(payload.get("selected_action") or "")
        if action == "ACT":
            act += 1
        elif action == "DO_NOTHING":
            skip += 1
        elif action == "ESCALATE":
            escalate += 1
        if txn.state == TransactionState.RECOVERED:
            intervention_cost += int(payload.get("intervention_cost") or 0)
        if action == "DO_NOTHING":
            cost_avoided += int(payload.get("cost_avoided") or 0)
    baseline = int(round(leakage_total * NATURAL_RECOVERY_RATE))
    net = max(recovered_amount - intervention_cost, 0)
    return {
        "revenue_leakage_total": leakage_total,
        "net_revenue_protected": net,
        "intervention_cost_total": intervention_cost,
        "intentionally_skipped": skip,
        "agent_act": act,
        "agent_do_nothing": skip,
        "agent_escalate": escalate,
        "baseline_recovered": baseline,
        "incremental_value_protected": max(recovered_amount - baseline, 0),
        "cost_avoided_total": cost_avoided,
        "leakage": [
            {
                "event_type": kind,
                "count": row["count"],
                "amount": row["amount"],
                "recovered": row["recovered"],
            }
            for kind, row in sorted(by_type.items())
        ],
    }

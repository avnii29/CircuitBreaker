from __future__ import annotations

from app.engine.failure_classifier import classify_failure
from app.engine.policies import evaluate_policy
from app.engine.routing_engine import select_best_recovery_route


def test_bank_down_and_risk_block_are_classified() -> None:
    risk = classify_failure("ERR_RISK_BLOCK")
    assert risk["strategy"] == "BLOCK"
    assert risk["recoverable"] is False
    outage = classify_failure("ERR_BANK_DOWN")
    assert outage["strategy"] == "REROUTE"
    assert outage["category"] == "RAIL_OUTAGE"
    first = classify_failure("ERR_NPCI_U30")
    second = classify_failure("ERR_NPCI_U30")
    assert first == second
    assert first["category"] == "BANK_TECHNICAL_FAILURE"
    assert first["recoverable"] is True
    funds = classify_failure("ERR_INSUFFICIENT_FUNDS")
    assert funds["recoverable"] is False
    assert funds["recommended_routes"] == ["MANUAL_REVIEW"]


def test_high_value_policy_blocks_automation() -> None:
    decision = evaluate_policy(
        amount=15000,
        attempt_count=0,
        window_expired=False,
        recoverable=True,
        route_score=87,
        high_risk=False,
    )
    assert decision["allowed"] is False
    assert "limit" in decision["reason"].lower()


def test_route_scoring_explains_decision() -> None:
    transaction = {
        "transaction_id": "TXN_CB_000001",
        "order": {"amount": 1499},
        "routing": {"error_code": "ERR_NPCI_U30", "bank": "HDFC Bank"},
        "recovery": {"attempt_count": 0, "cooldown_routes": []},
        "smart_routing": {"cooldown_routes": [], "attempted_routes": []},
    }
    decision = select_best_recovery_route(transaction)
    assert decision["selected_route"] == "PAYMENT_LINK"
    assert 0 <= decision["route_score"] <= 100
    assert decision["reason"]
    assert decision["alternatives"]
    assert "score_breakdown" in decision
    breakdown = decision["score_breakdown"]
    assert "base_score" in breakdown
    assert "failure_compatibility" in breakdown


def test_cooldown_skips_failed_route() -> None:
    transaction = {
        "transaction_id": "TXN_CB_000002",
        "order": {"amount": 1499},
        "routing": {"error_code": "ERR_NPCI_U30", "bank": "HDFC Bank"},
        "recovery": {"attempt_count": 1, "cooldown_routes": ["PAYMENT_LINK"]},
        "smart_routing": {"cooldown_routes": ["PAYMENT_LINK"], "attempted_routes": ["PAYMENT_LINK"]},
    }
    decision = select_best_recovery_route(transaction)
    assert decision["selected_route"] != "PAYMENT_LINK"

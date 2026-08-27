from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.engine.economics import NATURAL_RECOVERY_RATE, evaluate_interventions, window_recovery_probability
from app.engine.lifecycle import build_transaction
from app.main import app
from app.models import SimulateCheckoutRequest

client = TestClient(app)


def setup_function() -> None:
    client.post("/api/v1/payments/reset-demo")


def _patches():
    return (
        patch("app.engine.worker.monitor_recovery_deadline", new_callable=AsyncMock),
        patch("app.engine.worker.run_forced_route_failures", new_callable=AsyncMock),
        patch("app.engine.worker.auto_recover_after", new_callable=AsyncMock),
        patch("app.engine.worker.supervise_checkout", new_callable=AsyncMock),
    )


def _simulate(body: dict) -> dict:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        response = client.post("/api/v1/payments/simulate-checkout", json=body)
        assert response.status_code == 200
        return response.json()
    finally:
        for item in patches:
            item.stop()


def test_window_probability_is_deterministic() -> None:
    assert window_recovery_probability(0) == 0.82
    assert window_recovery_probability(1) == 0.42
    assert window_recovery_probability(4) == 0.17
    assert window_recovery_probability(0.5) > window_recovery_probability(1.0)


def test_low_value_is_intentionally_skipped() -> None:
    body = _simulate({"bank": "HDFC", "amount": 25, "demo_scenario": "LOW_VALUE"})
    economics = (body.get("smart_routing") or {}).get("economics") or {}
    assert economics["selected_action"] == "DO_NOTHING"
    assert body["state"] == "ESCALATED"
    assert any(event["action"] == "INTERVENTION_SKIPPED" for event in body["audit_trail"])
    assert "did not justify" in economics["rationale"]
    tel = client.get("/api/v1/payments/telemetry-dashboard").json()
    assert tel["intentionally_skipped"] >= 1
    assert tel["agent_do_nothing"] >= 1
    assert "total_revenue_recovered" in tel
    assert "net_revenue_protected" in tel


def test_checkout_abandonment_uses_same_decision_pipeline() -> None:
    body = _simulate(
        {
            "bank": "HDFC",
            "amount": 7200,
            "scenario": "CHECKOUT_ABANDONMENT",
            "demo_scenario": "CHECKOUT_ABANDONMENT",
        }
    )
    economics = (body.get("smart_routing") or {}).get("economics") or {}
    assert economics["event_type"] == "CHECKOUT_ABANDONMENT"
    assert 0.60 <= float(economics["predicted_loss_probability"]) <= 0.85
    assert economics["selected_action"] == "ACT"
    assert economics["selected_intervention"] in {"CUSTOMER_REMINDER", "PAYMENT_METHOD_NUDGE", "RETRY_LATER"}
    assert body["state"] == "AUTOMATED_LOOP"
    recovered = client.post(f"/api/v1/payments/execute-recovery-action/{body['transaction_id']}")
    assert recovered.status_code == 200
    payload = recovered.json()
    assert payload["executed"] is True
    txn = payload["transaction"]
    assert txn["state"] == "RECOVERED"
    assert txn["money_recovered"] == 7200
    assert (txn["smart_routing"]["economics"]["actual_recovered"]) == 7200
    assert any(event["action"] == "INTERVENTION_EXECUTED" for event in txn["audit_trail"])


def test_subscription_failure_recovers_through_shared_engine() -> None:
    body = _simulate(
        {
            "bank": "SBI",
            "amount": 1499,
            "scenario": "SUBSCRIPTION_FAILURE",
            "demo_scenario": "SUBSCRIPTION_FAILURE",
        }
    )
    economics = (body.get("smart_routing") or {}).get("economics") or {}
    assert economics["event_type"] == "SUBSCRIPTION_FAILURE"
    assert economics["selected_action"] in {"ACT", "ESCALATE"}
    if economics["selected_action"] == "ACT":
        recovered = client.post(f"/api/v1/payments/execute-recovery-action/{body['transaction_id']}")
        assert recovered.status_code == 200
        assert recovered.json()["transaction"]["state"] == "RECOVERED"


def test_overdue_receivable_selects_follow_up() -> None:
    body = _simulate(
        {
            "bank": "HDFC",
            "amount": 80000,
            "scenario": "OVERDUE_RECEIVABLE",
            "demo_scenario": "OVERDUE_RECEIVABLE",
        }
    )
    economics = (body.get("smart_routing") or {}).get("economics") or {}
    assert economics["event_type"] == "OVERDUE_RECEIVABLE"
    assert economics["selected_intervention"] == "COLLECTION_FOLLOWUP"
    recovered = client.post(f"/api/v1/payments/execute-recovery-action/{body['transaction_id']}")
    assert recovered.status_code == 200
    assert recovered.json()["transaction"]["state"] == "RECOVERED"
    assert recovered.json()["transaction"]["money_recovered"] == 80000


def test_payment_failure_still_has_candidate_economics() -> None:
    body = _simulate({"bank": "SBI", "amount": 4850, "scenario": "BANK_DOWN", "demo_scenario": "GOLDEN_OUTAGE"})
    economics = (body.get("smart_routing") or {}).get("economics") or {}
    assert economics["event_type"] == "PAYMENT_FAILURE"
    assert economics["revenue_at_risk"] == 4850
    assert float(economics["predicted_loss_probability"]) >= 0.75
    ids = {row["id"] for row in economics["candidates"]}
    assert "SAME_RAIL_RETRY" in ids
    assert "ALTERNATE_RAIL" in ids
    assert economics["selected_action"] == "ACT"
    assert economics["counterfactual"]["without_recovery_rate"] == NATURAL_RECOVERY_RATE
    assert "simulated" in str(economics["counterfactual"]["label"]).lower()


def test_candidates_are_ranked_by_net_expected_value() -> None:
    txn = build_transaction(
        SimulateCheckoutRequest(amount=4850, bank="SBI", scenario="BANK_DOWN", demo_scenario="GOLDEN_OUTAGE")
    )
    payload = evaluate_interventions(txn)
    nets = [row["net_expected_value"] for row in payload["candidates"]]
    assert nets == sorted(nets, reverse=True)
    assert payload["selected_intervention"] == payload["candidates"][0]["id"]


def test_unhandled_errors_are_safe() -> None:
    with patch("app.store.store.telemetry", side_effect=RuntimeError("db exploded at host=internal-db:5432")):
        response = client.get("/api/v1/payments/telemetry-dashboard")
        assert response.status_code == 503
        body = response.json()
        assert "internal-db" not in str(body)
        assert "5432" not in str(body)
        assert "stack" not in str(body).lower()
        assert "Recovery service is temporarily unavailable." in str(body.get("detail") or body)
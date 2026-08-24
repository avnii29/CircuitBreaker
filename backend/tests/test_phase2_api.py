from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def setup_function() -> None:
    client.post("/api/v1/payments/reset-demo")


def _worker_patches():
    return (
        patch("app.engine.worker.monitor_recovery_deadline", new_callable=AsyncMock),
        patch("app.engine.worker.run_forced_route_failures", new_callable=AsyncMock),
        patch("app.engine.worker.auto_recover_after", new_callable=AsyncMock),
    )


def test_hdfc_select_and_execute_recovers() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={
                "bank": "HDFC",
                "amount": 1499,
                "customer_name": "Rahul Sharma",
                "customer_email": "rahul@example.com",
                "customer_phone": "9876543210",
                "merchant_id": "MERCHANT_001",
            },
        )
        assert created.status_code == 200
        txn = created.json()
        assert txn["state"] == "AUTOMATED_LOOP"
        txn_id = txn["transaction_id"]

        selected = client.post(f"/api/v1/payments/select-recovery-route/{txn_id}")
        assert selected.status_code == 200
        body = selected.json()
        assert body["selected_route"]["route_id"]
        assert body["guardrail_status"] == "PASSED"
        assert body["failure_classification"]["category"]

        executed = client.post(f"/api/v1/payments/execute-selected-route/{txn_id}")
        assert executed.status_code == 200
        result = executed.json()
        assert result["outcome"] == "SUCCEEDED"
        assert result["transaction"]["state"] == "RECOVERED"
    finally:
        for item in patches:
            item.stop()


def test_high_value_is_escalated() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 15000, "demo_scenario": "HIGH_VALUE"},
        )
        assert created.status_code == 200
        txn = created.json()
        assert txn["state"] == "ESCALATED"
        assert txn["smart_routing"]["policy_blocked"] is True
    finally:
        for item in patches:
            item.stop()


def test_repeated_route_failure_escalates() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={
                "bank": "HDFC",
                "amount": 1999,
                "force_route_failure": True,
                "demo_scenario": "REPEATED_ROUTE_FAILURE",
            },
        )
        assert created.status_code == 200
        txn = created.json()
        assert txn["state"] == "AUTOMATED_LOOP"
        txn_id = txn["transaction_id"]
        last_outcome = ""
        for _ in range(3):
            result = client.post(f"/api/v1/payments/execute-selected-route/{txn_id}").json()
            last_outcome = result["outcome"]
        assert last_outcome == "ESCALATED"
        final = client.get(f"/api/v1/payments/{txn_id}").json()
        assert final["state"] == "ESCALATED"
        actions = [event["action"] for event in final["audit_trail"]]
        assert "RECOVERY_ROUTE_FAILED" in actions
        assert "ROUTING_ATTEMPTS_EXHAUSTED" in actions
    finally:
        for item in patches:
            item.stop()


def test_execute_ignores_frontend_amount_override() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499},
        ).json()
        txn_id = created["transaction_id"]
        client.post(f"/api/v1/payments/select-recovery-route/{txn_id}")
        executed = client.post(
            f"/api/v1/payments/execute-selected-route/{txn_id}",
            json={"amount": 1999, "payment_link": "https://evil.example/pay"},
        )
        assert executed.status_code == 200
        assert executed.json()["transaction"]["order"]["amount"] == 1499
    finally:
        for item in patches:
            item.stop()

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

TRANSACTION_REQUIRED = {
    "transaction_id",
    "state",
    "customer",
    "order",
    "routing",
    "recovery",
    "audit_trail",
    "created_at",
    "updated_at",
}
TELEMETRY_REQUIRED = {
    "total_failures_intercepted",
    "total_transactions_rescued",
    "total_revenue_recovered",
    "active_held_carts",
    "total_escalated",
    "recovery_rate",
    "revenue_at_risk",
    "revenue_recovered",
    "demo_mode",
    "recovery_window_seconds",
    "engine_online",
    "last_heartbeat",
}
STATES = {
    "INITIATED",
    "FAILED",
    "AUTOMATED_LOOP",
    "RETRYING",
    "REROUTING",
    "RECOVERED",
    "ESCALATED",
}


def setup_function() -> None:
    client.post("/api/v1/payments/reset-demo")


def _patches():
    return (
        patch("app.engine.worker.monitor_recovery_deadline", new_callable=AsyncMock),
        patch("app.engine.worker.run_forced_route_failures", new_callable=AsyncMock),
        patch("app.engine.worker.auto_recover_after", new_callable=AsyncMock),
        patch("app.engine.worker.supervise_checkout", new_callable=AsyncMock),
    )


def _assert_transaction_shape(body: dict) -> None:
    assert TRANSACTION_REQUIRED <= set(body)
    assert body["state"] in STATES
    assert isinstance(body["transaction_id"], str)
    assert isinstance(body["order"]["amount"], int)
    assert isinstance(body["audit_trail"], list)
    assert body["cart_status"] in {"HELD", "RELEASED"}


def test_v1_checkout_and_transaction_contracts() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post("/api/v1/payments/simulate-checkout", json={"bank": "HDFC", "amount": 1499})
        assert created.status_code == 200
        body = created.json()
        _assert_transaction_shape(body)
        txn_id = body["transaction_id"]

        listed = client.get("/api/v1/payments/transactions")
        assert listed.status_code == 200
        assert isinstance(listed.json(), list)
        assert listed.json()[0]["transaction_id"] == txn_id

        fetched = client.get(f"/api/v1/payments/transactions/{txn_id}")
        assert fetched.status_code == 200
        _assert_transaction_shape(fetched.json())

        missing = client.get("/api/v1/payments/transactions/TXN_CB_999999")
        assert missing.status_code == 404

        audit = client.get(f"/api/v1/payments/transactions/{txn_id}/audit-log")
        assert audit.status_code == 200
        events = audit.json()
        assert isinstance(events, list)
        assert events
        for event in events:
            assert {"timestamp", "action", "transaction_id", "actor"} <= set(event)
            blob = str(event.get("metadata") or {})
            assert "rahul@example.com" not in blob.lower()
            assert "vpa" not in blob.lower()
    finally:
        for item in patches:
            item.stop()


def test_v1_recovery_and_telemetry_contracts() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post("/api/v1/payments/simulate-checkout", json={"bank": "HDFC", "amount": 1499}).json()
        txn_id = created["transaction_id"]
        recovered = client.post(f"/api/v1/payments/execute-recovery-action/{txn_id}")
        assert recovered.status_code == 200
        payload = recovered.json()
        assert {"executed", "blocked", "transaction"} <= set(payload)
        assert isinstance(payload["executed"], bool)
        _assert_transaction_shape(payload["transaction"])

        tel = client.get("/api/v1/payments/telemetry-dashboard")
        assert tel.status_code == 200
        dashboard = tel.json()
        assert TELEMETRY_REQUIRED <= set(dashboard)
        assert isinstance(dashboard["recovery_rate"], (int, float))
        assert isinstance(dashboard["intelligence"], dict)
        intel = dashboard["intelligence"]
        for key in (
            "primary_success_rate",
            "reroute_success_rate",
            "fail_then_reroute_rate",
            "predictive_routing_rate",
            "recovery_rate",
            "retry_success_rate",
            "escalation_rate",
            "policy_adjustments",
            "positive_adjustments",
            "negative_adjustments",
            "rollback_count",
        ):
            assert key in intel
    finally:
        for item in patches:
            item.stop()


def test_v1_batch_reset_health_metrics_queue() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        batch = client.post("/api/v1/payments/simulate-batch", json={"count": 3})
        assert batch.status_code == 200
        body = batch.json()
        assert "batch" in body and "transactions" in body
        assert body["batch"]["batch_size"] == 3

        run = client.post("/api/v1/payments/run-recovery-simulation")
        assert run.status_code in {200, 409}
        if run.status_code == 200:
            assert "selected" in run.json()

        funds = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "FUNDS"},
        ).json()
        queue = client.get("/api/v1/payments/manual-review-queue")
        assert queue.status_code == 200
        assert isinstance(queue.json(), list)
        assert funds["transaction_id"] in [row["transaction_id"] for row in queue.json()]

        health = client.get("/api/v1/health")
        assert health.status_code == 200
        payload = health.json()
        assert {"status", "engine", "demo_mode", "recovery_window_seconds", "heartbeat", "llm_provider"} <= set(payload)
        assert isinstance(payload["db_connected"], bool)

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert b"circuitbreaker_http_requests_total" in metrics.content

        reset = client.post("/api/v1/payments/reset-demo")
        assert reset.status_code == 200
        assert reset.json()["ok"] is True
        listed = client.get("/api/v1/payments/transactions")
        assert listed.json() == []
    finally:
        for item in patches:
            item.stop()

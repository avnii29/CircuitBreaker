from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

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


def test_hard_decline_never_auto_retries() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "FUNDS"},
        )
        assert created.status_code == 200
        txn = created.json()
        assert txn["state"] == "ESCALATED"
        assert txn["routing"]["error_code"] == "ERR_INSUFFICIENT_FUNDS"
        execute = client.post(f"/api/v1/payments/execute-recovery-action/{txn['transaction_id']}")
        assert execute.json()["executed"] is False
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_escalated"] == 1
    finally:
        for item in patches:
            item.stop()


def test_risk_block_fails_named_guardrail() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1999, "scenario": "RISK"},
        ).json()
        assert created["state"] == "ESCALATED"
        assert created["recovery"]["guardrail"]["passed"] is False
        keys = [check["key"] for check in created["recovery"]["guardrail"]["checks"]]
        assert "not_flagged_fraud" in keys
        assert any(not check["passed"] for check in created["recovery"]["guardrail"]["checks"] if check["key"] == "not_flagged_fraud")
    finally:
        for item in patches:
            item.stop()


def test_transient_error_is_rescued() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "U30"},
        ).json()
        assert created["state"] == "AUTOMATED_LOOP"
        executed = client.post(f"/api/v1/payments/execute-recovery-action/{created['transaction_id']}").json()
        assert executed["executed"] is True
        assert executed["transaction"]["state"] == "RECOVERED"
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_transactions_rescued"] == 1
        assert tel["average_recovery_time_seconds"] is not None
    finally:
        for item in patches:
            item.stop()


def test_rail_outage_reroutes_then_succeeds() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "SBI", "amount": 1799, "scenario": "BANK_DOWN"},
        ).json()
        assert created["state"] == "AUTOMATED_LOOP"
        first = client.post(f"/api/v1/payments/execute-selected-route/{created['transaction_id']}").json()
        assert first["outcome"] == "FAILED"
        assert first["transaction"]["state"] == "REROUTING"
        second = client.post(f"/api/v1/payments/execute-selected-route/{created['transaction_id']}").json()
        assert second["outcome"] == "SUCCEEDED"
        assert second["transaction"]["state"] == "RECOVERED"
        attempts = second["transaction"]["routing"]["route_attempts"]
        assert len(attempts) >= 2
        assert attempts[0]["outcome"] == "FAILED"
        assert attempts[-1]["outcome"] == "SUCCEEDED"
        log = client.get(f"/api/v1/payments/transactions/{created['transaction_id']}/audit-log").json()
        assert log[0]["timestamp"] <= log[-1]["timestamp"]
        actions = [event["action"] for event in log]
        assert "RECOVERY_ROUTE_FAILED" in actions
        assert "PAYMENT_RECOVERED" in actions
        missing = client.get("/api/v1/payments/transactions/TXN_CB_999999/audit-log")
        assert missing.status_code == 404
    finally:
        for item in patches:
            item.stop()

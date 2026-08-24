from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.engine.circuit_breaker import blocked_rails, record_outcome
from app.engine.policy import retrain
from app.main import app
from app.store import store
from app.tenancy import TenantPrincipal, reset_principal, set_principal

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


def test_golden_outage_recovers_on_healthier_rail() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    token = set_principal(TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write"))
    try:
        asyncio.run(
            store.seed_route_attempts(
                tenant_id=settings.DEFAULT_TENANT_ID,
                error_code="ERR_BANK_DOWN",
                route="PAYMENT_LINK",
                outcome="FAILED",
                count=20,
            )
        )
        asyncio.run(
            store.seed_route_attempts(
                tenant_id=settings.DEFAULT_TENANT_ID,
                error_code="ERR_BANK_DOWN",
                route="QR_FALLBACK",
                outcome="SUCCEEDED",
                count=20,
            )
        )
        asyncio.run(
            store.seed_rail_history(
                tenant_id=settings.DEFAULT_TENANT_ID,
                rail="PAYMENT_LINK",
                success=False,
                count=8,
            )
        )
        asyncio.run(retrain(settings.DEFAULT_TENANT_ID))

        async def _open_primary():
            for _ in range(8):
                await record_outcome("PAYMENT_LINK", False)
            return await blocked_rails()

        assert "PAYMENT_LINK" in asyncio.run(_open_primary())

        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={
                "bank": "SBI",
                "amount": 4850,
                "scenario": "BANK_DOWN",
                "demo_scenario": "GOLDEN_OUTAGE",
                "customer_name": "Priya Mehta",
            },
        ).json()
        assert created["state"] == "AUTOMATED_LOOP"
        assert created["order"]["amount"] == 4850
        selected = client.post(f"/api/v1/payments/select-recovery-route/{created['transaction_id']}").json()
        assert selected["selected_route"]["route_id"] == "QR_FALLBACK"
        executed = client.post(f"/api/v1/payments/execute-selected-route/{created['transaction_id']}").json()
        txn = executed["transaction"]
        assert executed["outcome"] == "SUCCEEDED"
        assert txn["state"] == "RECOVERED"
        assert txn["money_recovered"] == 4850
        actions = [event["action"] for event in txn["audit_trail"]]
        assert "RECOVERY_DECISION" in actions
        assert "PAYMENT_RECOVERED" in actions
        assert txn["smart_routing"]["last_decision"]["policy_version"].startswith("policy-v")
        assert txn["smart_routing"]["last_decision"]["decision"] == "RESCUED"
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_transactions_rescued"] >= 1
        assert tel["total_revenue_recovered"] >= 4850
        assert tel["intelligence"]["best_route"]
        audit = client.get(f"/api/v1/payments/transactions/{txn['transaction_id']}/audit-log").json()
        assert any(event["action"] == "RECOVERY_DECISION" for event in audit)
        path = [event["new_state"] for event in txn["audit_trail"] if event.get("new_state")]
        assert path[0] == "INITIATED"
        assert "FAILED" in path
        assert "AUTOMATED_LOOP" in path
        assert path[-1] == "RECOVERED"
    finally:
        reset_principal(token)
        for item in patches:
            item.stop()

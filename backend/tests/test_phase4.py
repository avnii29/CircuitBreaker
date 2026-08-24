from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.engine.circuit_breaker import blocked_rails, record_outcome
from app.main import app
from app.store import dispose_and_reload

client = TestClient(app)


def setup_function() -> None:
    client.post("/api/v1/payments/reset-demo")


def _worker_patches():
    return (
        patch("app.engine.worker.monitor_recovery_deadline", new_callable=AsyncMock),
        patch("app.engine.worker.run_forced_route_failures", new_callable=AsyncMock),
        patch("app.engine.worker.auto_recover_after", new_callable=AsyncMock),
        patch("app.engine.worker.supervise_checkout", new_callable=AsyncMock),
    )


def test_mutating_endpoints_require_auth() -> None:
    anonymous = TestClient(app, headers={"X-API-Key": "nope-key"})
    response = anonymous.post("/api/v1/payments/simulate-checkout", json={"bank": "HDFC", "amount": 1499})
    assert response.status_code in {401, 403}


def test_idempotent_checkout_does_not_double_create() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        payload = {
            "bank": "HDFC",
            "amount": 1499,
            "idempotency_key": "idem-checkout-key-001",
        }
        first = client.post("/api/v1/payments/simulate-checkout", json=payload)
        second = client.post("/api/v1/payments/simulate-checkout", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["transaction_id"] == second.json()["transaction_id"]
        listed = client.get("/api/v1/payments/transactions").json()
        matching = [row for row in listed if row["transaction_id"] == first.json()["transaction_id"]]
        assert len(matching) == 1
    finally:
        for item in patches:
            item.stop()


def test_state_survives_engine_reload() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "U30"},
        ).json()
        txn_id = created["transaction_id"]
        asyncio.run(dispose_and_reload())
        loaded = client.get(f"/api/v1/payments/transactions/{txn_id}")
        assert loaded.status_code == 200
        assert loaded.json()["transaction_id"] == txn_id
        assert loaded.json()["state"] == created["state"]
    finally:
        for item in patches:
            item.stop()


def test_manual_review_queue_lists_escalated() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "FUNDS"},
        ).json()
        assert created["state"] == "ESCALATED"
        queue = client.get("/api/v1/payments/manual-review-queue").json()
        ids = [row["transaction_id"] for row in queue]
        assert created["transaction_id"] in ids
    finally:
        for item in patches:
            item.stop()


def test_circuit_breaker_opens_hot_rail() -> None:
    async def _run() -> set[str]:
        for _ in range(8):
            await record_outcome("PAYMENT_LINK", False)
        return await blocked_rails()

    blocked = asyncio.run(_run())
    assert "PAYMENT_LINK" in blocked
    tel = client.get("/api/v1/payments/telemetry-dashboard").json()
    rails = {row["rail"]: row["state"] for row in tel.get("circuit_breakers", [])}
    assert rails.get("PAYMENT_LINK") == "OPEN"


def test_health_and_metrics_are_real() -> None:
    health = client.get("/api/v1/health").json()
    assert "db_connected" in health
    assert health["db_connected"] is True
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    live = client.get("/health/live")
    assert live.status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert b"circuitbreaker_http_requests_total" in metrics.content


def test_concurrent_recovery_does_not_double_recover() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "U30"},
        ).json()
        txn_id = created["transaction_id"]

        async def _run() -> list[dict]:
            headers = {"X-API-Key": "test-write-key"}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                first, second = await asyncio.gather(
                    ac.post(f"/api/v1/payments/execute-recovery-action/{txn_id}", headers=headers),
                    ac.post(f"/api/v1/payments/execute-recovery-action/{txn_id}", headers=headers),
                )
                return [first.json(), second.json()]

        results = asyncio.run(_run())
        recovered = [row for row in results if row["transaction"]["state"] == "RECOVERED"]
        assert len(recovered) >= 1
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_transactions_rescued"] == 1
    finally:
        for item in patches:
            item.stop()

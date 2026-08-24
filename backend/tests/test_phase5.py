from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.engine.circuit_breaker import blocked_rails, record_outcome
from app.engine.policy import current_policy, retrain
from app.main import app
from app.store import store
from app.tenancy import TenantPrincipal, reset_principal, set_principal

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


def _as_tenant(tenant_id: str, key: str) -> TestClient:
    return TestClient(app, headers={"X-API-Key": key})


def test_learned_scores_change_reroute_order() -> None:
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
        snapshot = asyncio.run(retrain(settings.DEFAULT_TENANT_ID))
        scores = {f"{row['error_code']}:{row['rail']}": row["success_rate"] for row in snapshot["route_scores"]}
        assert scores["ERR_BANK_DOWN:QR_FALLBACK"] > scores["ERR_BANK_DOWN:PAYMENT_LINK"]
        policy = client.get("/api/v2/policy").json()
        rails = {row["rail"]: row["success_rate"] for row in policy["route_scores"] if row["error_code"] == "ERR_BANK_DOWN"}
        assert rails["QR_FALLBACK"] > rails["PAYMENT_LINK"]
    finally:
        reset_principal(token)


def test_guardrail_threshold_adjusts_and_rolls_back() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    token = set_principal(TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write"))
    try:
        asyncio.run(retrain(settings.DEFAULT_TENANT_ID))
        first = asyncio.run(current_policy(settings.DEFAULT_TENANT_ID))
        for _ in range(3):
            client.post("/api/v1/payments/simulate-checkout", json={"bank": "HDFC", "amount": 1499, "scenario": "FUNDS"})
        asyncio.run(store.mark_escalated_resolved(settings.DEFAULT_TENANT_ID, 3))
        snapshot = asyncio.run(retrain(settings.DEFAULT_TENANT_ID))
        after_retries = snapshot["thresholds"]["max_retries"]
        assert after_retries == first["thresholds"]["max_retries"] + 1
        assert "Loosened max_retries" in snapshot["rationale"]
        rolled = client.post(f"/api/v2/policy/rollback/{first['thresholds']['version']}").json()
        assert rolled["ok"] is True
        assert rolled["snapshot"]["thresholds"]["max_retries"] == first["thresholds"]["max_retries"]
    finally:
        reset_principal(token)
        for item in patches:
            item.stop()


def test_predictive_routing_skips_fail_then_reroute() -> None:
    patches = _worker_patches()
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
        asyncio.run(retrain(settings.DEFAULT_TENANT_ID))
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "SBI", "amount": 1799, "scenario": "BANK_DOWN"},
        ).json()
        first = client.post(f"/api/v1/payments/execute-selected-route/{created['transaction_id']}").json()
        assert first["outcome"] == "SUCCEEDED"
        assert first["transaction"]["smart_routing"]["preemptive"] is True
        attempts = first["transaction"]["routing"]["route_attempts"]
        assert len(attempts) == 1
        assert attempts[0]["outcome"] == "SUCCEEDED"
    finally:
        reset_principal(token)
        for item in patches:
            item.stop()


def test_anomaly_opens_circuit_faster_than_static_threshold() -> None:
    token = set_principal(TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write"))
    try:
        asyncio.run(
            store.seed_rail_history(
                tenant_id=settings.DEFAULT_TENANT_ID,
                rail="QR_FALLBACK",
                success=True,
                count=40,
                age_seconds=3600,
            )
        )

        async def _run():
            for _ in range(4):
                await record_outcome("QR_FALLBACK", False)
            return await blocked_rails()

        blocked = asyncio.run(_run())
        assert "QR_FALLBACK" in blocked
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        row = next(item for item in tel["circuit_breakers"] if item["rail"] == "QR_FALLBACK")
        assert row["state"] == "OPEN"
        assert row["opened_by"] == "anomaly"
        assert row["samples"] < settings.CIRCUIT_MIN_SAMPLES
    finally:
        reset_principal(token)


def test_tenant_circuit_isolation() -> None:
    client_a = _as_tenant("TENANT_A", "key-a-write")
    client_b = _as_tenant("TENANT_B", "key-b-write")
    token_a = set_principal(TenantPrincipal(tenant_id="TENANT_A", scope="write"))
    try:
        async def _trip_a():
            for _ in range(8):
                await record_outcome("PAYMENT_LINK", False, tenant_id="TENANT_A")
            return await blocked_rails("TENANT_A")

        blocked_a = asyncio.run(_trip_a())
        assert "PAYMENT_LINK" in blocked_a
    finally:
        reset_principal(token_a)
    token_b = set_principal(TenantPrincipal(tenant_id="TENANT_B", scope="write"))
    try:
        blocked_b = asyncio.run(blocked_rails("TENANT_B"))
        assert "PAYMENT_LINK" not in blocked_b
        tel_b = client_b.get("/api/v1/payments/telemetry-dashboard").json()
        rails_b = {row["rail"]: row["state"] for row in tel_b.get("circuit_breakers", [])}
        assert rails_b.get("PAYMENT_LINK") != "OPEN"
        created = client_b.post("/api/v1/payments/simulate-checkout", json={"bank": "HDFC", "amount": 1499, "scenario": "U30"})
        assert created.status_code == 200
        listed_a = client_a.get("/api/v1/payments/transactions").json()
        listed_b = client_b.get("/api/v1/payments/transactions").json()
        ids_a = {row["transaction_id"] for row in listed_a}
        ids_b = {row["transaction_id"] for row in listed_b}
        assert created.json()["transaction_id"] in ids_b
        assert created.json()["transaction_id"] not in ids_a
    finally:
        reset_principal(token_b)


def test_manual_review_and_metrics_are_tenant_labeled() -> None:
    patches = _worker_patches()
    for item in patches:
        item.start()
    try:
        client_a = _as_tenant("TENANT_A", "key-a-write")
        created = client_a.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "FUNDS"},
        ).json()
        queue_a = client_a.get("/api/v1/payments/manual-review-queue").json()
        assert created["transaction_id"] in [row["transaction_id"] for row in queue_a]
        queue_b = _as_tenant("TENANT_B", "key-b-write").get("/api/v1/payments/manual-review-queue").json()
        assert created["transaction_id"] not in [row["transaction_id"] for row in queue_b]
        metrics = client.get("/metrics").content
        assert b"circuitbreaker_rail_circuit_state" in metrics
        assert b'tenant_id="' in metrics or b"TENANT_" in metrics
    finally:
        for item in patches:
            item.stop()


def test_enqueue_retrain_is_async_job() -> None:
    token = set_principal(TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write"))
    try:
        response = client.post("/api/v2/policy/enqueue-retrain")
        assert response.status_code == 200
        assert response.json()["job_id"] >= 1
        from app.engine.jobs import queue_depth

        depth = asyncio.run(queue_depth("retrain"))
        assert depth >= 1
    finally:
        reset_principal(token)

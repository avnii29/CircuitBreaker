from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.engine.circuit_breaker import blocked_rails, record_outcome
from app.engine.decision import PRECEDENCE, compose_recovery_decision
from app.engine.policy import retrain
from app.engine.state_machine import LEGAL_TRANSITIONS, IllegalTransition, apply_state
from app.main import app
from app.models import TransactionState
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


def _states(txn: dict) -> list[str]:
    return [event["new_state"] for event in txn["audit_trail"] if event.get("new_state")]


def test_precedence_is_documented() -> None:
    assert PRECEDENCE == (
        "HARD_SAFETY_GUARDRAILS",
        "CIRCUIT_BREAKER_STATE",
        "ADAPTIVE_POLICY",
        "HISTORICAL_ROUTING_SCORE",
        "DETERMINISTIC_FALLBACK_RULES",
    )


def test_illegal_state_transition_rejected() -> None:
    from app.engine.lifecycle import build_transaction

    txn = build_transaction()
    apply_state(txn, TransactionState.FAILED)
    try:
        apply_state(txn, TransactionState.INITIATED)
        raise AssertionError("expected IllegalTransition")
    except IllegalTransition:
        pass
    assert TransactionState.RECOVERED in LEGAL_TRANSITIONS[TransactionState.RETRYING]


def test_transient_failure() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "U30"},
        ).json()
        assert created["state"] == "AUTOMATED_LOOP"
        result = client.post(f"/api/v1/payments/execute-recovery-action/{created['transaction_id']}").json()
        txn = result["transaction"]
        assert txn["state"] == "RECOVERED"
        assert "RETRYING" in _states(txn) or txn["routing"]["recovery_strategy"] == "RETRY"
        decision = txn["smart_routing"]["last_decision"]
        assert decision["decision"] == "RESCUED"
        assert str(decision["policy_version"]).startswith("policy-v")
        actions = [event["action"] for event in txn["audit_trail"]]
        assert "RECOVERY_DECISION" in actions
        assert "PAYMENT_RECOVERED" in actions
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_transactions_rescued"] == 1
    finally:
        for item in patches:
            item.stop()


def test_hard_decline() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1499, "scenario": "FUNDS"},
        ).json()
        assert created["state"] == "ESCALATED"
        decision = created["smart_routing"]["last_decision"]
        assert decision["decision"] == "HOLD"
        assert created["routing"]["error_code"] == "ERR_INSUFFICIENT_FUNDS"
        execute = client.post(f"/api/v1/payments/execute-recovery-action/{created['transaction_id']}").json()
        assert execute["executed"] is False
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_escalated"] == 1
    finally:
        for item in patches:
            item.stop()


def test_fraud_block() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1999, "scenario": "RISK"},
        ).json()
        assert created["state"] == "ESCALATED"
        assert created["smart_routing"]["last_decision"]["decision"] == "ESCALATE"
        checks = {row["key"]: row["passed"] for row in created["recovery"]["guardrail"]["checks"]}
        assert checks["not_flagged_fraud"] is False
    finally:
        for item in patches:
            item.stop()


def test_bank_outage_reroutes() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "SBI", "amount": 1799, "scenario": "BANK_DOWN"},
        ).json()
        first = client.post(f"/api/v1/payments/execute-selected-route/{created['transaction_id']}").json()
        assert first["outcome"] == "FAILED"
        second = client.post(f"/api/v1/payments/execute-selected-route/{created['transaction_id']}").json()
        assert second["outcome"] == "SUCCEEDED"
        txn = second["transaction"]
        assert txn["state"] == "RECOVERED"
        assert "REROUTING" in _states(txn)
        assert txn["smart_routing"]["last_decision"]["decision"] == "RESCUED"
    finally:
        for item in patches:
            item.stop()


def test_multiple_retries_then_escalate() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 1999, "force_route_failure": True},
        ).json()
        last = None
        for _ in range(3):
            last = client.post(f"/api/v1/payments/execute-selected-route/{created['transaction_id']}").json()
        assert last["outcome"] == "ESCALATED"
        txn = client.get(f"/api/v1/payments/transactions/{created['transaction_id']}").json()
        assert txn["state"] == "ESCALATED"
        assert txn["recovery"]["attempt_count"] >= 3
        actions = [event["action"] for event in txn["audit_trail"]]
        assert "ROUTING_ATTEMPTS_EXHAUSTED" in actions
    finally:
        for item in patches:
            item.stop()


def test_guardrail_failure_high_value() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "HDFC", "amount": 15000},
        ).json()
        assert created["state"] == "ESCALATED"
        assert created["smart_routing"]["policy_blocked"] is True
        assert created["smart_routing"]["last_decision"]["layer"] == PRECEDENCE[0]
    finally:
        for item in patches:
            item.stop()


def test_circuit_open_skips_blocked_rail() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    token = set_principal(TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write"))
    try:
        asyncio.run(_trip_payment_link())
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "SBI", "amount": 1799, "scenario": "BANK_DOWN"},
        ).json()
        selected = client.post(f"/api/v1/payments/select-recovery-route/{created['transaction_id']}").json()
        assert selected["selected_route"]["route_id"] != "PAYMENT_LINK"
        assert selected["transaction"]["smart_routing"]["last_decision"]["decision"] in {"REROUTE", "RETRY", "ESCALATE"}
    finally:
        reset_principal(token)
        for item in patches:
            item.stop()


async def _trip_payment_link() -> None:
    for _ in range(8):
        await record_outcome("PAYMENT_LINK", False)
    blocked = await blocked_rails()
    assert "PAYMENT_LINK" in blocked


def test_database_failure_returns_unavailable() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        with patch("app.routers.payments.simulate_checkout", side_effect=RuntimeError("db down")):
            response = client.post("/api/v1/payments/simulate-checkout", json={"bank": "HDFC", "amount": 1499})
        assert response.status_code == 503
    finally:
        for item in patches:
            item.stop()


def test_duplicate_request_same_idempotency_key() -> None:
    patches = _patches()
    for item in patches:
        item.start()
    try:
        payload = {"bank": "HDFC", "amount": 1499, "idempotency_key": "idem-phase6-dup-001"}
        first = client.post("/api/v1/payments/simulate-checkout", json=payload)
        second = client.post("/api/v1/payments/simulate-checkout", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["transaction_id"] == second.json()["transaction_id"]
        listed = client.get("/api/v1/payments/transactions").json()
        matching = [row for row in listed if row["transaction_id"] == first.json()["transaction_id"]]
        assert len(matching) == 1
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_failures_intercepted"] == 1
    finally:
        for item in patches:
            item.stop()


def test_concurrent_recovery_ten_requests() -> None:
    patches = _patches()
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
                responses = await asyncio.gather(
                    *[ac.post(f"/api/v1/payments/execute-recovery-action/{txn_id}", headers=headers) for _ in range(10)]
                )
                return [{"status": row.status_code, "body": row.json()} for row in responses]

        results = asyncio.run(_run())
        bodies = [row["body"] for row in results if isinstance(row["body"], dict) and "transaction" in row["body"]]
        recovered = [row for row in bodies if row["transaction"]["state"] == "RECOVERED"]
        assert len(recovered) >= 1
        final = client.get(f"/api/v1/payments/transactions/{txn_id}").json()
        assert final["state"] == "RECOVERED"
        assert final["money_recovered"] == 1499
        tel = client.get("/api/v1/payments/telemetry-dashboard").json()
        assert tel["total_transactions_rescued"] == 1
        recovered_events = [event for event in final["audit_trail"] if event["action"] == "PAYMENT_RECOVERED"]
        assert len(recovered_events) == 1
    finally:
        for item in patches:
            item.stop()


def test_tenant_isolation() -> None:
    client_a = TestClient(app, headers={"X-API-Key": "key-a-write"})
    client_b = TestClient(app, headers={"X-API-Key": "key-b-write"})
    token_a = set_principal(TenantPrincipal(tenant_id="TENANT_A", scope="write"))
    try:
        async def _trip():
            for _ in range(8):
                await record_outcome("PAYMENT_LINK", False, tenant_id="TENANT_A")
            return await blocked_rails("TENANT_A")

        assert "PAYMENT_LINK" in asyncio.run(_trip())
    finally:
        reset_principal(token_a)
    token_b = set_principal(TenantPrincipal(tenant_id="TENANT_B", scope="write"))
    try:
        blocked_b = asyncio.run(blocked_rails("TENANT_B"))
        assert "PAYMENT_LINK" not in blocked_b
        created = client_b.post("/api/v1/payments/simulate-checkout", json={"bank": "HDFC", "amount": 1499, "scenario": "U30"})
        assert created.status_code == 200
        ids_a = {row["transaction_id"] for row in client_a.get("/api/v1/payments/transactions").json()}
        ids_b = {row["transaction_id"] for row in client_b.get("/api/v1/payments/transactions").json()}
        assert created.json()["transaction_id"] in ids_b
        assert created.json()["transaction_id"] not in ids_a
        audit_a = client_a.get(f"/api/v1/payments/transactions/{created.json()['transaction_id']}/audit-log")
        assert audit_a.status_code == 404
        tel_a = client_a.get("/api/v1/payments/telemetry-dashboard").json()
        tel_b = client_b.get("/api/v1/payments/telemetry-dashboard").json()
        rails_a = {row["rail"]: row["state"] for row in tel_a.get("circuit_breakers", [])}
        rails_b = {row["rail"]: row["state"] for row in tel_b.get("circuit_breakers", [])}
        assert rails_a.get("PAYMENT_LINK") == "OPEN"
        assert rails_b.get("PAYMENT_LINK") != "OPEN"
    finally:
        reset_principal(token_b)


def test_adaptive_scores_prefer_healthier_rail_then_reroute_after_drop() -> None:
    token = set_principal(TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write"))
    patches = _patches()
    for item in patches:
        item.start()
    try:
        asyncio.run(
            store.seed_route_attempts(
                tenant_id=settings.DEFAULT_TENANT_ID,
                error_code="ERR_BANK_DOWN",
                route="PAYMENT_LINK",
                outcome="SUCCEEDED",
                count=61,
            )
        )
        asyncio.run(
            store.seed_route_attempts(
                tenant_id=settings.DEFAULT_TENANT_ID,
                error_code="ERR_BANK_DOWN",
                route="PAYMENT_LINK",
                outcome="FAILED",
                count=39,
            )
        )
        asyncio.run(
            store.seed_route_attempts(
                tenant_id=settings.DEFAULT_TENANT_ID,
                error_code="ERR_BANK_DOWN",
                route="QR_FALLBACK",
                outcome="SUCCEEDED",
                count=97,
            )
        )
        asyncio.run(
            store.seed_route_attempts(
                tenant_id=settings.DEFAULT_TENANT_ID,
                error_code="ERR_BANK_DOWN",
                route="QR_FALLBACK",
                outcome="FAILED",
                count=3,
            )
        )
        asyncio.run(retrain(settings.DEFAULT_TENANT_ID))
        created = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "SBI", "amount": 1799, "scenario": "BANK_DOWN"},
        ).json()
        selected = client.post(f"/api/v1/payments/select-recovery-route/{created['transaction_id']}").json()
        assert selected["selected_route"]["route_id"] == "QR_FALLBACK"

        asyncio.run(
            store.seed_route_attempts(
                tenant_id=settings.DEFAULT_TENANT_ID,
                error_code="ERR_BANK_DOWN",
                route="QR_FALLBACK",
                outcome="FAILED",
                count=80,
            )
        )
        asyncio.run(
            store.seed_rail_history(
                tenant_id=settings.DEFAULT_TENANT_ID,
                rail="QR_FALLBACK",
                success=False,
                count=8,
            )
        )
        snapshot = asyncio.run(retrain(settings.DEFAULT_TENANT_ID))
        scores = {row["rail"]: row["success_rate"] for row in snapshot["route_scores"] if row["error_code"] == "ERR_BANK_DOWN"}
        assert scores["QR_FALLBACK"] < scores["PAYMENT_LINK"]
        asyncio.run(_open_qr())
        created2 = client.post(
            "/api/v1/payments/simulate-checkout",
            json={"bank": "SBI", "amount": 1799, "scenario": "BANK_DOWN"},
        ).json()
        selected2 = client.post(f"/api/v1/payments/select-recovery-route/{created2['transaction_id']}").json()
        assert selected2["selected_route"]["route_id"] != "QR_FALLBACK"
    finally:
        reset_principal(token)
        for item in patches:
            item.stop()


async def _open_qr() -> None:
    for _ in range(8):
        await record_outcome("QR_FALLBACK", False)
    blocked = await blocked_rails()
    assert "QR_FALLBACK" in blocked


def test_guardrails_override_adaptive_choice() -> None:
    from app.engine.lifecycle import build_transaction
    from app.engine.failure_classifier import classify_failure
    from app.models import FailureClassification, SmartRoutingState

    txn = build_transaction()
    txn.routing.error_code = "ERR_RISK_BLOCK"
    classified = classify_failure("ERR_RISK_BLOCK")
    txn.smart_routing = SmartRoutingState(
        failure_classification=FailureClassification(**classified),
        selected_route="QR_FALLBACK",
        confidence=0.99,
        reason="Adaptive score preferred QR_FALLBACK.",
    )
    decision = compose_recovery_decision(
        txn,
        policy={"allowed": False, "code": "HIGH_RISK", "reason": "Transaction risk requires human review."},
        learned={"QR_FALLBACK": {"success_rate": 0.99, "samples": 100}},
        thresholds={"version": 17},
    )
    assert decision.decision == "ESCALATE"
    assert decision.layer == PRECEDENCE[0]
    assert decision.policy_version == "policy-v17"
    assert "QR_FALLBACK" not in decision.expected_outcome

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Request, status

from app.alerting import evaluate_alerts
from app.config import settings
from app.engine.lifecycle import execute_recovery, simulate_checkout, utcnow
from app.engine.routing_service import execute_selected_route, select_recovery_route
from app.engine.simulation import build_batch_spec
from app.models import (
    AuditEvent,
    BatchResult,
    ExecuteRecoveryRequest,
    ExecuteRecoveryResponse,
    ExecuteSelectedRouteResponse,
    HealthResponse,
    RunRecoverySimulationResponse,
    SelectRecoveryRouteResponse,
    SimulateBatchRequest,
    SimulateCheckoutRequest,
    TelemetryDashboard,
    Transaction,
    TransactionState,
    is_active_recovery,
)
from app.observability.logging import log_event
from app.security.auth import require_read, require_write
from app.security.ratelimit import limit_checkout, limit_recovery
from app.store import fingerprint_payload, store

logger = logging.getLogger("circuitbreaker.payments")

router = APIRouter(dependencies=[Depends(require_read)])


def _pending(body: dict | None) -> bool:
    return bool(isinstance(body, dict) and body.get("_pending"))


async def _replay_or_store(key: str | None, endpoint: str, payload: dict, produce):
    if not key:
        return await produce()
    fingerprint = fingerprint_payload(payload)
    existing = await store.claim_idempotency(key, endpoint, fingerprint)
    if existing:
        if existing["fingerprint"] != fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key reused with a different payload.",
            )
        body = existing["response_json"]
        if _pending(body):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotent request is already in progress.",
            )
        return body
    result = await produce()
    dumped = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    await store.complete_idempotency(key, endpoint, 200, dumped)
    return result


@router.post("/simulate-checkout", response_model=Transaction, dependencies=[Depends(require_write)])
async def simulate_checkout_endpoint(
    request: Request,
    background: BackgroundTasks,
    body: SimulateCheckoutRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Transaction:
    await limit_checkout(request)
    payload = body.model_dump() if body else {}
    key = (body.idempotency_key if body else None) or idempotency_key

    async def produce() -> Transaction:
        try:
            txn = await simulate_checkout(body, background)
            log_event(
                logger,
                "checkout_simulated",
                transaction_id=txn.transaction_id,
                outcome=txn.state.value,
                extra_payload={"error_code": txn.routing.error_code},
            )
            return txn
        except HTTPException:
            raise
        except Exception:
            log_event(logger, "checkout_unavailable", outcome="ERROR")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Recovery service unavailable.")

    result = await _replay_or_store(key, "simulate-checkout", payload, produce)
    return result if isinstance(result, Transaction) else Transaction.model_validate(result)


@router.post(
    "/execute-recovery-action/{transaction_id}",
    response_model=ExecuteRecoveryResponse,
    dependencies=[Depends(require_write)],
)
async def execute_recovery_action(
    request: Request,
    transaction_id: str,
    body: ExecuteRecoveryRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ExecuteRecoveryResponse:
    await limit_recovery(request)
    payload = {"transaction_id": transaction_id, **(body.model_dump() if body else {})}
    key = (body.idempotency_key if body else None) or idempotency_key

    async def produce() -> ExecuteRecoveryResponse:
        try:
            return await execute_recovery(transaction_id)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Recovery service unavailable.")

    result = await _replay_or_store(key, f"execute-recovery:{transaction_id}", payload, produce)
    return result if isinstance(result, ExecuteRecoveryResponse) else ExecuteRecoveryResponse.model_validate(result)


@router.get("/telemetry-dashboard", response_model=TelemetryDashboard)
async def telemetry_dashboard() -> TelemetryDashboard:
    return await store.telemetry(
        demo_mode=settings.DEMO_MODE,
        recovery_window_seconds=settings.recovery_window_seconds,
        heartbeat=utcnow(),
    )


@router.get("/manual-review-queue", response_model=list[Transaction])
async def manual_review_queue(tenant_id: str | None = None) -> list[Transaction]:
    from app.tenancy import current_principal, query_tenant_id

    principal = current_principal()
    scoped = tenant_id if principal and principal.is_ops else query_tenant_id()
    return await store.list_manual_review(tenant_id=scoped)


@router.get("/transactions", response_model=list[Transaction])
async def list_transactions() -> list[Transaction]:
    return await store.list_all()


@router.get("/transactions/{transaction_id}/audit-log", response_model=list[AuditEvent])
async def get_transaction_audit_log(transaction_id: str) -> list[AuditEvent]:
    transaction = await store.get(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return sorted(transaction.audit_trail, key=lambda event: event.timestamp)


@router.get("/transactions/{transaction_id}", response_model=Transaction)
async def get_transaction_legacy(transaction_id: str) -> Transaction:
    transaction = await store.get(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return transaction


@router.post("/simulate-batch", dependencies=[Depends(require_write)])
async def simulate_batch_endpoint(
    request: Request,
    background: BackgroundTasks,
    body: SimulateBatchRequest | None = Body(default=None),
) -> dict:
    await limit_checkout(request)
    from app.engine.jobs import should_shed_batch
    from app.tenancy import write_tenant_id

    if await should_shed_batch(write_tenant_id()):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Backpressure: batch traffic shed. Real-time recovery is prioritized over batch jobs and retraining.",
        )
    count = body.count if body and body.count > 0 else 50
    batch_id = f"BATCH_{secrets.token_hex(3).upper()}"
    spec = build_batch_spec(count)
    created: list[Transaction] = []
    for item in spec:
        transaction = await simulate_checkout(
            SimulateCheckoutRequest(
                bank=item["bank"],
                scenario=item["scenario"],
                amount=item["amount"],
                customer_name=item["customer_name"],
                customer_email=item["customer_email"],
                customer_phone=item["customer_phone"],
                merchant_id="MERCHANT_001",
                auto_recover=False,
                force_route_failure=bool(item["force_route_failure"]),
            ),
            background,
            batch_id=batch_id,
            auto_recover=False,
        )
        created.append(transaction)
    now = datetime.now(timezone.utc)
    looping = [txn for txn in created if is_active_recovery(txn.state)]
    escalated = [txn for txn in created if txn.state == TransactionState.ESCALATED]
    batch = BatchResult(
        batch_id=batch_id,
        batch_size=count,
        failures_intercepted=len(created),
        recovery_attempts=0,
        recovered=0,
        escalated=len(escalated),
        in_progress=len(looping),
        recovery_rate=0.0,
        revenue_recovered=0,
        revenue_at_risk=sum(txn.order.amount for txn in looping),
        complete=False,
        created_at=now,
        transaction_ids=[txn.transaction_id for txn in created],
    )
    await store.save_batch(batch)
    return {"batch": batch, "transactions": created}


@router.post(
    "/select-recovery-route/{transaction_id}",
    response_model=SelectRecoveryRouteResponse,
    dependencies=[Depends(require_write)],
)
async def select_recovery_route_endpoint(transaction_id: str) -> SelectRecoveryRouteResponse:
    return await select_recovery_route(transaction_id)


@router.post(
    "/execute-selected-route/{transaction_id}",
    response_model=ExecuteSelectedRouteResponse,
    dependencies=[Depends(require_write)],
)
async def execute_selected_route_endpoint(request: Request, transaction_id: str) -> ExecuteSelectedRouteResponse:
    await limit_recovery(request)
    return await execute_selected_route(transaction_id)


@router.post("/run-recovery-simulation", response_model=RunRecoverySimulationResponse, dependencies=[Depends(require_write)])
async def run_recovery_simulation_endpoint(background: BackgroundTasks) -> RunRecoverySimulationResponse:
    from app.engine import worker

    looping = [txn for txn in await store.list_all() if is_active_recovery(txn.state)]
    if not looping:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No transactions are currently in automated recovery.",
        )
    selected = [txn.transaction_id for txn in looping]
    background.add_task(worker.run_recovery_simulation, selected)
    return RunRecoverySimulationResponse(selected=selected)


@router.post("/reset-demo", dependencies=[Depends(require_write)])
async def reset_demo() -> dict:
    await store.reset()
    return {"ok": True, "message": "Demo store cleared."}


@router.get("/ops/alerts")
async def ops_alerts() -> dict:
    return {"alerts": await evaluate_alerts()}


@router.get("/health", response_model=HealthResponse)
async def payments_health() -> HealthResponse:
    db_ok = await store.ping()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        engine="online" if db_ok else "degraded",
        demo_mode=settings.DEMO_MODE,
        recovery_window_seconds=settings.recovery_window_seconds,
        heartbeat=utcnow(),
        llm_provider="AI SIMULATION",
        db_connected=db_ok,
        rails_reachable=db_ok,
        recovery_queue_depth=0,
        open_circuits=0,
    )


@router.get("", response_model=list[Transaction])
async def list_payments() -> list[Transaction]:
    return await store.list_all()


@router.get("/{transaction_id}", response_model=Transaction)
async def get_payment(transaction_id: str) -> Transaction:
    transaction = await store.get(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return transaction

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks

from app.config import settings
from app.engine.ai import advisor
from app.engine.diagnostic import bank_label, resolve_scenario
from app.engine.decision import compose_recovery_decision, stamp_decision
from app.engine.failure_classifier import classify_failure as classify_error
from app.engine.guardrail import evaluate_guardrail, validate_ai_generated_payload
from app.engine.state_machine import apply_state
from app.models import (
    Actor,
    AuditEvent,
    CartStatus,
    CustomerDetails,
    ExecuteRecoveryResponse,
    FailureClassification,
    GuardrailCheck,
    GuardrailResult,
    OrderItem,
    OrderPayload,
    RecoveryState,
    RoutingTelemetry,
    SimulateCheckoutRequest,
    SmartRoutingState,
    Transaction,
    TransactionState,
    is_active_recovery,
)
from app.security.pii import redact_mapping
from app.store import ConcurrencyError, store
from app.tenancy import write_tenant_id
from app.observability.context import correlation_id
from app.observability.logging import log_event

logger = logging.getLogger("circuitbreaker.lifecycle")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _txn_id() -> str:
    return f"TXN_CB_{secrets.randbelow(1_000_000):06d}"


def _order_id() -> str:
    return f"ORD_{secrets.token_hex(3).upper()}"


def _slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "." for ch in name).strip(".")


def append_audit(
    transaction: Transaction,
    action: str,
    actor: str,
    previous_state: TransactionState | None = None,
    new_state: TransactionState | None = None,
    metadata: dict | None = None,
    reason: str | None = None,
) -> None:
    payload = redact_mapping(metadata or {})
    event_reason = reason or str(payload.get("reason") or payload.get("error_code") or action)
    transaction.audit_trail.append(
        AuditEvent(
            timestamp=utcnow(),
            action=action,
            transaction_id=transaction.transaction_id,
            previous_state=previous_state,
            new_state=new_state,
            actor=actor,
            metadata=payload,
            reason=event_reason,
        )
    )
    transaction.updated_at = utcnow()
    smart = transaction.smart_routing
    decision_meta = (smart.last_decision if smart else None) or {}
    log_event(
        logger,
        "engine_event",
        transaction_id=transaction.transaction_id,
        tenant_id=getattr(transaction, "tenant_id", None),
        correlation_id=correlation_id(),
        event_type=action,
        from_state=previous_state.value if previous_state else None,
        to_state=new_state.value if new_state else None,
        decision=payload.get("decision") or decision_meta.get("decision") or action,
        policy_version=payload.get("policy_version") or (smart.policy_version if smart else None),
        rail=payload.get("route") or payload.get("rail") or payload.get("selected_rail"),
        outcome=payload.get("outcome") or (new_state.value if new_state else None),
    )


def build_transaction(
    request: SimulateCheckoutRequest | None = None,
    batch_id: str | None = None,
    auto_recover: bool = False,
    transaction_id: str | None = None,
) -> Transaction:
    payload = request or SimulateCheckoutRequest()
    bank, scenario = resolve_scenario(payload.bank, payload.scenario)
    amount = payload.amount if payload.amount and payload.amount > 0 else scenario["default_amount"]
    customer_name = (payload.customer_name or "Rahul Sharma").strip() or "Rahul Sharma"
    first = customer_name.split(" ")[0]
    now = utcnow()
    txn_id = transaction_id or _txn_id()
    window = settings.recovery_window_seconds
    started = now
    expires = now + timedelta(seconds=window)
    if payload.expire_window:
        started = now - timedelta(seconds=window + 5)
        expires = now - timedelta(seconds=1)
    payment_link = f"https://rzp.io/demo/{txn_id}"
    reservation_id = f"RES_{txn_id}"
    merchant_id = payload.merchant_id or "MERCHANT_001"
    email = payload.customer_email or f"{_slug(first)}@example.com"
    phone = payload.customer_phone or "9876543210"
    demo_scenario = (payload.demo_scenario or "").strip()
    return Transaction(
        transaction_id=txn_id,
        state=TransactionState.INITIATED,
        customer=CustomerDetails(
            name=customer_name,
            email=email,
            phone=phone,
        ),
        order=OrderPayload(
            order_id=_order_id(),
            merchant_id=merchant_id,
            merchant_name="Northstar Stores",
            items=[
                OrderItem(
                    sku="SKU_DEMO_01",
                    name="Held cart reservation",
                    quantity=1,
                    unit_amount=amount,
                )
            ],
            amount=amount,
            currency="INR",
            reservation_id=reservation_id,
        ),
        routing=RoutingTelemetry(
            bank=bank_label(bank),
            attempted_route=f"{bank.upper()}_UPI",
            fallback_route="UPI FALLBACK",
            error_code=scenario["error_code"],
            error_label=scenario["error_label"],
            diagnosis=scenario["diagnosis"],
            recovery_eligible=scenario["error_code"] not in {
                "ERR_INSUFFICIENT_FUNDS",
                "ERR_FRAUD_SUSPECTED",
                "ERR_RISK_BLOCK",
            },
            simulation_error=True,
            latency_ms=840 if scenario["error_code"] in {"ERR_TIMEOUT", "ERR_NETWORK_TIMEOUT"} else 210,
            recovery_strategy=classify_error(scenario["error_code"])["strategy"],
        ),
        recovery=RecoveryState(
            window_seconds=window,
            window_started_at=started,
            window_expires_at=expires,
            attempt_count=0,
            max_attempts=settings.MAX_RECOVERY_ATTEMPTS,
            payment_link=payment_link,
            cart_held=False,
            auto_recover=auto_recover or payload.auto_recover,
            recovery_route="UPI FALLBACK",
            alternate_link_generated=payment_link,
            force_route_failure=payload.force_route_failure,
            locked_amount=amount,
        ),
        audit_trail=[],
        created_at=now,
        updated_at=now,
        batch_id=batch_id,
        cart_status=CartStatus.RELEASED,
        money_recovered=0,
        bank=bank.upper(),
        failure_reason=scenario["error_label"],
        demo_scenario=demo_scenario,
        tenant_id=write_tenant_id(),
        smart_routing=SmartRoutingState(
            force_route_failure=payload.force_route_failure,
            demo_scenario=demo_scenario,
            failure_classification=None,
        ),
    )


async def simulate_checkout(
    request: SimulateCheckoutRequest | None,
    background: BackgroundTasks,
    batch_id: str | None = None,
    auto_recover: bool = False,
    auto_recover_after: float | None = None,
) -> Transaction:
    from app.engine import worker

    txn_id = await store.allocate_id()
    transaction = build_transaction(
        request,
        batch_id=batch_id,
        auto_recover=auto_recover,
        transaction_id=txn_id,
    )
    try:
        from app.engine.policy import get_thresholds

        thresholds = await get_thresholds(transaction.tenant_id)
        transaction.recovery.max_attempts = int(thresholds.get("max_retries") or settings.MAX_RECOVERY_ATTEMPTS)
    except Exception:
        pass
    append_audit(
        transaction,
        action="PAYMENT_INITIATED",
        actor=Actor.MERCHANT_CHECKOUT.value,
        previous_state=None,
        new_state=TransactionState.INITIATED,
        metadata={"amount": transaction.order.amount, "currency": "INR"},
    )
    previous = apply_state(transaction, TransactionState.FAILED)
    transaction.failed_at = utcnow()
    append_audit(
        transaction,
        action="BANK_FAILURE_DETECTED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=previous,
        new_state=TransactionState.FAILED,
        metadata={
            "error_code": transaction.routing.error_code,
            "simulation_error": True,
            "bank": transaction.routing.bank,
        },
    )
    append_audit(
        transaction,
        action="FAILURE_INTERCEPTED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=TransactionState.FAILED,
        new_state=TransactionState.FAILED,
        metadata={"recoverable": True},
    )
    transaction.recovery.cart_held = True
    transaction.cart_status = CartStatus.HELD
    append_audit(
        transaction,
        action="CART_HELD",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=TransactionState.FAILED,
        new_state=TransactionState.FAILED,
        metadata={"reservation_id": transaction.order.reservation_id, "cart_status": "HELD"},
    )
    await store.upsert(transaction)
    try:
        from app.engine.circuit_breaker import record_outcome

        await record_outcome(transaction.bank, False, tenant_id=transaction.tenant_id)
    except Exception:
        pass
    await enter_automated_loop(transaction.transaction_id)
    started = await store.get(transaction.transaction_id)
    delay = 6.0 if auto_recover_after is None else auto_recover_after
    if settings.WORKER_ENABLED:
        from app.engine.jobs import PRIORITY_REALTIME, enqueue

        await enqueue(
            "recover" if bool(started and started.recovery.auto_recover) else "supervise",
            transaction.tenant_id,
            {
                "transaction_id": transaction.transaction_id,
                "auto_recover": bool(started and started.recovery.auto_recover),
                "auto_recover_after_delay": delay,
                "force_route_failure": bool(
                    started and started.recovery.force_route_failure and is_active_recovery(started.state)
                ),
            },
            priority=PRIORITY_REALTIME,
        )
    else:
        background.add_task(
            worker.supervise_checkout,
            transaction.transaction_id,
            auto_recover=bool(started and started.recovery.auto_recover),
            auto_recover_after_delay=delay,
            force_route_failure=bool(started and started.recovery.force_route_failure and is_active_recovery(started.state)),
        )
    return started or transaction


async def enter_automated_loop(transaction_id: str) -> Transaction | None:
    transaction = await store.get(transaction_id)
    if transaction is None:
        return None
    if transaction.state != TransactionState.FAILED:
        return transaction

    previous = apply_state(transaction, TransactionState.AUTOMATED_LOOP)
    append_audit(
        transaction,
        action="AUTOMATED_RECOVERY_STARTED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=previous,
        new_state=TransactionState.AUTOMATED_LOOP,
        metadata={"window_seconds": transaction.recovery.window_seconds},
    )

    from app.engine.failure_classifier import classify_failure
    from app.engine.policies import evaluate_policy

    classified = classify_failure(transaction.routing.error_code)
    if transaction.smart_routing is None:
        transaction.smart_routing = SmartRoutingState()
    transaction.smart_routing.failure_classification = FailureClassification(**classified)
    transaction.routing.recovery_strategy = classified["strategy"]
    append_audit(
        transaction,
        action="FAILURE_CLASSIFIED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=TransactionState.AUTOMATED_LOOP,
        new_state=TransactionState.AUTOMATED_LOOP,
        metadata={
            "category": classified["category"],
            "recoverable": classified["recoverable"],
            "error_code": classified["error_code"],
            "strategy": classified["strategy"],
            "simulated": True,
        },
    )

    if classified["strategy"] == "HOLD" or classified["category"] == "CUSTOMER_FUNDS_FAILURE":
        blocked = GuardrailResult(
            passed=False,
            reason="Insufficient funds: same-rail retry is not allowed.",
            blocked_reason="Insufficient funds: same-rail retry is not allowed.",
            checks=[
                GuardrailCheck(key="max_retries_not_exceeded", label="Max retries not exceeded", passed=True),
                GuardrailCheck(key="not_flagged_fraud", label="Not flagged for fraud or risk", passed=True),
                GuardrailCheck(key="amount_below_auto_recovery_limit", label="Amount below auto-recovery limit", passed=transaction.order.amount <= 10000),
                GuardrailCheck(key="cooldown_period_elapsed", label="Cooldown period elapsed", passed=True),
                GuardrailCheck(key="same_rail_retry_allowed", label="Same-rail retry allowed", passed=False),
            ],
        )
        transaction.recovery.guardrail = blocked
        transaction.smart_routing.policy_blocked = True
        transaction.smart_routing.policy_allowed = False
        transaction.smart_routing.policy_reason = blocked.reason
        transaction.smart_routing.guardrail_status = "BLOCKED"
        thresholds = {}
        try:
            from app.engine.policy import get_thresholds

            thresholds = await get_thresholds(transaction.tenant_id)
        except Exception:
            thresholds = {}
        stamp_decision(
            transaction,
            compose_recovery_decision(
                transaction,
                policy={"allowed": False, "code": "NOT_RECOVERABLE", "reason": blocked.reason},
                thresholds=thresholds,
            ),
        )
        append_audit(
            transaction,
            action="GUARDRAIL_BLOCKED",
            actor=Actor.GUARDRAIL.value,
            previous_state=TransactionState.AUTOMATED_LOOP,
            new_state=TransactionState.AUTOMATED_LOOP,
            metadata={"reason": blocked.reason, "guardrail_status": "BLOCKED", "policy_version": thresholds.get("policy_version")},
            reason=blocked.reason,
        )
        await store.upsert(transaction)
        return await escalate_transaction(
            transaction.transaction_id,
            trigger="POLICY_BLOCKED",
            reason=blocked.reason,
        )

    if classified["strategy"] == "BLOCK" or classified["category"] == "RISK_FAILURE":
        blocked = GuardrailResult(
            passed=False,
            reason="Risk/fraud flag blocked automated recovery.",
            blocked_reason="Risk/fraud flag blocked automated recovery.",
            checks=[
                GuardrailCheck(key="not_flagged_fraud", label="Not flagged for fraud or risk", passed=False),
                GuardrailCheck(key="max_retries_not_exceeded", label="Max retries not exceeded", passed=True),
                GuardrailCheck(key="amount_below_auto_recovery_limit", label="Amount below auto-recovery limit", passed=transaction.order.amount <= 10000),
                GuardrailCheck(key="cooldown_period_elapsed", label="Cooldown period elapsed", passed=True),
            ],
        )
        transaction.recovery.guardrail = blocked
        transaction.smart_routing.policy_blocked = True
        transaction.smart_routing.policy_reason = blocked.reason
        transaction.smart_routing.guardrail_status = "BLOCKED"
        thresholds = {}
        try:
            from app.engine.policy import get_thresholds

            thresholds = await get_thresholds(transaction.tenant_id)
        except Exception:
            thresholds = {}
        stamp_decision(
            transaction,
            compose_recovery_decision(
                transaction,
                policy={"allowed": False, "code": "HIGH_RISK", "reason": blocked.reason},
                thresholds=thresholds,
            ),
        )
        append_audit(
            transaction,
            action="GUARDRAIL_BLOCKED",
            actor=Actor.GUARDRAIL.value,
            previous_state=TransactionState.AUTOMATED_LOOP,
            new_state=TransactionState.AUTOMATED_LOOP,
            metadata={"reason": blocked.reason, "guardrail_status": "BLOCKED", "policy_version": thresholds.get("policy_version")},
        )
        await store.upsert(transaction)
        return await escalate_transaction(
            transaction.transaction_id,
            trigger="GUARDRAIL_BLOCKED",
            reason=blocked.reason,
        )

    window_expired = utcnow() >= transaction.recovery.window_expires_at
    policy = evaluate_policy(
        amount=transaction.order.amount,
        attempt_count=transaction.recovery.attempt_count,
        window_expired=window_expired,
        recoverable=bool(classified["recoverable"]),
        route_score=None,
        high_risk=classified["category"] == "RISK_FAILURE",
        max_attempts=transaction.recovery.max_attempts,
    )
    if not policy["allowed"]:
        transaction.smart_routing.policy_allowed = False
        transaction.smart_routing.policy_reason = policy["reason"]
        transaction.smart_routing.policy_blocked = True
        transaction.smart_routing.guardrail_status = "BLOCKED"
        thresholds = {}
        try:
            from app.engine.policy import get_thresholds

            thresholds = await get_thresholds(transaction.tenant_id)
        except Exception:
            thresholds = {}
        stamp_decision(
            transaction,
            compose_recovery_decision(transaction, policy=policy, thresholds=thresholds),
        )
        await store.upsert(transaction)
        return await escalate_transaction(
            transaction.transaction_id,
            trigger="POLICY_BLOCKED",
            reason=policy["reason"],
        )

    try:
        recommendation = advisor.generate(transaction)
    except Exception:
        from app.engine.ai import AIRecommendation

        recommendation = AIRecommendation(
            recommendation="Send alternate payment route",
            confidence=80.0,
            customer_message=(
                f"Hi there! Aapka payment complete nahi ho paya (ref {transaction.transaction_id}). "
                f"Is alternate link se payment complete kar sakte hain: {transaction.recovery.payment_link}"
            ),
            raw_output="",
            simulated=True,
        )
    transaction.recovery.recommendation = recommendation.recommendation
    transaction.recovery.confidence = recommendation.confidence
    transaction.recovery.raw_llm_output = recommendation.raw_output
    transaction.recovery.ai_simulation = recommendation.simulated
    transaction.recovery.customer_message = recommendation.customer_message
    transaction.recovery.message_generated_at = utcnow()
    transaction.recovery.message_language = "Hinglish"
    transaction.recovery.message_channel = "WHATSAPP_SIMULATION"
    append_audit(
        transaction,
        action="RECOVERY_MESSAGE_GENERATED",
        actor=Actor.AI_SIMULATION.value,
        previous_state=TransactionState.AUTOMATED_LOOP,
        new_state=TransactionState.AUTOMATED_LOOP,
        metadata={
            "ai_simulation": True,
            "confidence": recommendation.confidence,
            "language": "Hinglish",
            "channel": "WHATSAPP_SIMULATION",
        },
    )

    source = transaction.model_dump(mode="json")
    validated = validate_ai_generated_payload(transaction.recovery.raw_llm_output, source)
    result = evaluate_guardrail(transaction.recovery.raw_llm_output, source)
    result.output_message = validated
    transaction.recovery.guardrail = result
    transaction.recovery.customer_message = validated
    append_audit(
        transaction,
        action="GUARDRAIL_BLOCKED" if not result.passed else "GUARDRAIL_VALIDATED",
        actor=Actor.GUARDRAIL.value,
        previous_state=TransactionState.AUTOMATED_LOOP,
        new_state=TransactionState.AUTOMATED_LOOP,
        metadata={
            "guardrail_status": "FALLBACK_TRIGGERED" if not result.passed else "PASSED",
            "reason": result.blocked_reason,
            "passed": result.passed,
        },
    )
    append_audit(
        transaction,
        action="RECOVERY_LINK_GENERATED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=TransactionState.AUTOMATED_LOOP,
        new_state=TransactionState.AUTOMATED_LOOP,
        metadata={
            "payment_link": transaction.recovery.payment_link,
            "recovery_route": "UPI FALLBACK",
            "simulated": True,
        },
    )
    transaction.recovery.alternate_link_generated = transaction.recovery.payment_link
    await store.upsert(transaction)
    return transaction


async def execute_recovery(
    transaction_id: str,
    actor: str = Actor.OPERATOR.value,
) -> ExecuteRecoveryResponse:
    from app.engine.routing_service import recover_transaction_with_routing

    return await recover_transaction_with_routing(transaction_id, actor=actor)


async def escalate_transaction(
    transaction_id: str,
    trigger: str = "RECOVERY_WINDOW_EXPIRED",
    reason: str = "Recovery window expired.",
) -> Transaction | None:
    transaction = await store.get(transaction_id)
    if transaction is None:
        return None
    if transaction.state in (TransactionState.RECOVERED, TransactionState.ESCALATED):
        return transaction
    if transaction.state != TransactionState.FAILED and not is_active_recovery(transaction.state):
        return transaction

    previous = apply_state(transaction, TransactionState.ESCALATED)
    now = utcnow()
    transaction.recovery.escalated_at = now
    transaction.recovery.cart_held = False
    transaction.cart_status = CartStatus.RELEASED
    transaction.order.cart_released_at = now
    if transaction.smart_routing:
        transaction.smart_routing.last_outcome = "ESCALATED"
        transaction.smart_routing.policy_reason = transaction.smart_routing.policy_reason or reason
    append_audit(
        transaction,
        action=trigger,
        actor=Actor.STOPPING_RULE.value,
        previous_state=previous,
        new_state=TransactionState.ESCALATED,
        metadata={"reason": reason},
    )
    append_audit(
        transaction,
        action="ESCALATION_TRIGGERED",
        actor=Actor.STOPPING_RULE.value,
        previous_state=previous,
        new_state=TransactionState.ESCALATED,
        metadata={"held_cart_released": True, "reason": reason},
    )
    append_audit(
        transaction,
        action="CART_RELEASED",
        actor=Actor.STOPPING_RULE.value,
        previous_state=TransactionState.ESCALATED,
        new_state=TransactionState.ESCALATED,
        metadata={"reservation_id": transaction.order.reservation_id, "reason": "escalated", "cart_status": "RELEASED"},
    )
    try:
        await store.upsert(transaction, expected_version=await store.get_version(transaction_id))
    except ConcurrencyError:
        return await store.get(transaction_id)
    try:
        from app.engine.webhooks import emit_resolution_event

        await emit_resolution_event(
            transaction.transaction_id,
            TransactionState.ESCALATED.value,
            transaction.order.amount,
            reason=reason,
        )
    except Exception:
        pass
    return transaction

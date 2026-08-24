from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, status

from app.engine.decision import compose_recovery_decision, stamp_decision
from app.engine.failure_classifier import classify_failure
from app.engine.guardrail import validate_route_execution
from app.engine.lifecycle import append_audit, escalate_transaction, utcnow
from app.engine.policies import MAX_ATTEMPTS, evaluate_policy
from app.engine.rails import get_payment_rail
from app.engine.rails import simulate_route_outcome as simulate_route_outcome
from app.engine.routing_engine import ROUTE_CATALOG, select_best_recovery_route
from app.engine.state_machine import apply_state
from app.formatting import rupee
from app.models import (
    Actor,
    CartStatus,
    ExecuteRecoveryResponse,
    ExecuteSelectedRouteResponse,
    FailureClassification,
    RouteAlternative,
    RouteAttempt,
    RouteScoreBreakdown,
    RoutingEvent,
    RoutingSummary,
    ScoredRoute,
    SelectRecoveryRouteResponse,
    SmartRoutingState,
    Transaction,
    TransactionState,
    is_active_recovery,
)
from app.store import ConcurrencyError, store


def _ensure_smart(transaction: Transaction) -> SmartRoutingState:
    if transaction.smart_routing is None:
        transaction.smart_routing = SmartRoutingState(
            force_route_failure=transaction.recovery.force_route_failure,
            demo_scenario=transaction.demo_scenario,
        )
    return transaction.smart_routing


def _canonical_link(transaction_id: str) -> str:
    return f"https://rzp.io/demo/{transaction_id}"


def _apply_decision(transaction: Transaction, decision: dict[str, Any]) -> SmartRoutingState:
    smart = _ensure_smart(transaction)
    classification = decision["failure_classification"]
    smart.failure_classification = FailureClassification(**classification)
    smart.selected_route = str(decision["selected_route"])
    smart.display_name = str(decision["display_name"])
    smart.route_score = int(decision["route_score"])
    smart.confidence = float(decision["confidence"])
    smart.reason = str(decision["reason"])
    smart.why = list(decision["why"])
    smart.score_breakdown = RouteScoreBreakdown(**decision["score_breakdown"])
    smart.alternatives = [RouteAlternative(**row) for row in decision["alternatives"]]
    smart.scored_routes = [
        ScoredRoute(**{key: value for key, value in row.items() if key != "raw_score"})
        for row in decision["scored_routes"]
    ]
    smart.routes_evaluated_count = len(decision["scored_routes"])
    smart.simulated = True
    smart.preemptive = bool(decision.get("preemptive"))
    smart.predicted_failure_probability = decision.get("predicted_failure_probability")
    smart.learned_score_source = "rolling_audit" if decision.get("preemptive") or decision.get("predicted_failure_probability") is not None else smart.learned_score_source
    smart.cooldown_routes = list(transaction.recovery.cooldown_routes)
    transaction.routing.recovery_strategy = str(classification.get("strategy") or "RETRY")
    transaction.recovery.recovery_route = smart.display_name
    if smart.selected_route == "PAYMENT_LINK":
        transaction.recovery.alternate_link_generated = _canonical_link(transaction.transaction_id)
        transaction.recovery.payment_link = transaction.recovery.alternate_link_generated
    return smart


def _record_recovery_decision(
    transaction: Transaction,
    *,
    policy: dict,
    guard=None,
    blocked_rails: set[str] | None = None,
    thresholds: dict | None = None,
    learned: dict | None = None,
    no_eligible: bool = False,
    rescued: bool = False,
    circuit_state: str | None = None,
    primary_failure_rate: float | None = None,
) -> None:
    smart = _ensure_smart(transaction)
    decision = compose_recovery_decision(
        transaction,
        policy=policy,
        guard=guard,
        blocked_rails=blocked_rails,
        thresholds=thresholds,
        learned=learned,
        rescued=rescued,
        no_eligible=no_eligible,
        preemptive=bool(smart.preemptive),
        circuit_state=circuit_state,
        primary_failure_rate=primary_failure_rate,
    )
    stamp_decision(transaction, decision)
    append_audit(
        transaction,
        action="RECOVERY_DECISION",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=transaction.state,
        new_state=transaction.state,
        metadata=decision.as_audit(),
        reason=decision.reason,
    )


def _record_route_attempt(transaction: Transaction, route_id: str, outcome: str, reason: str) -> None:
    sequence = len(transaction.routing.route_attempts) + 1
    transaction.routing.route_attempts.append(
        RouteAttempt(
            sequence=sequence,
            route=route_id,
            outcome=outcome,
            reason=reason,
            at=utcnow(),
        )
    )
    transaction.routing.last_route_outcome = outcome
    transaction.routing.attempted_route = route_id
    if outcome == "FAILED":
        transaction.routing.fallback_route = "ALTERNATE_PROCESSOR"
    transaction.recovery.last_attempt_at = utcnow()
    transaction.recovery.retry_count = transaction.recovery.attempt_count


async def classify_transaction(transaction: Transaction, persist_audit: bool = True) -> FailureClassification:
    classification = classify_failure(transaction.routing.error_code)
    smart = _ensure_smart(transaction)
    smart.failure_classification = FailureClassification(**classification)
    if persist_audit:
        append_audit(
            transaction,
            action="FAILURE_CLASSIFIED",
            actor=Actor.RECOVERY_ENGINE.value,
            previous_state=transaction.state,
            new_state=transaction.state,
            metadata={
                "category": classification["category"],
                "recoverable": classification["recoverable"],
                "error_code": classification["error_code"],
                "simulated": True,
            },
        )
    return smart.failure_classification


async def select_recovery_route(transaction_id: str) -> SelectRecoveryRouteResponse:
    transaction = await store.get(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    if not is_active_recovery(transaction.state):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Route selection requires an active recovery state.",
        )
    if utcnow() >= transaction.recovery.window_expires_at:
        await escalate_transaction(
            transaction_id,
            trigger="RECOVERY_WINDOW_EXPIRED",
            reason="Recovery window expired.",
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery window expired.")

    stats = await store.route_stats()
    payload = transaction.model_dump(mode="json")
    from app.engine.circuit_breaker import blocked_rails as open_rails
    from app.engine.policy import get_thresholds, learned_stats

    try:
        payload["blocked_rails"] = list(await open_rails())
    except Exception:
        payload["blocked_rails"] = []
    learned: dict = {}
    thresholds: dict = {"predict_fail_threshold": 0.65}
    try:
        learned = await learned_stats(transaction.routing.error_code)
        thresholds = await get_thresholds()
    except Exception:
        learned = {}
    decision = select_best_recovery_route(
        payload,
        stats,
        learned=learned or None,
        predict_fail_threshold=float(thresholds.get("predict_fail_threshold") or 0.65),
    )
    classification = decision["failure_classification"]
    smart = _apply_decision(transaction, decision)
    if smart.preemptive:
        append_audit(
            transaction,
            action="PREDICTIVE_REROUTE",
            actor=Actor.RECOVERY_ENGINE.value,
            previous_state=transaction.state,
            new_state=transaction.state,
            metadata={
                "route": smart.selected_route,
                "predicted_failure_probability": smart.predicted_failure_probability,
                "reason": smart.reason,
            },
            reason=smart.reason,
        )

    window_expired = utcnow() >= transaction.recovery.window_expires_at
    high_risk = classification["category"] == "RISK_FAILURE"
    policy = evaluate_policy(
        amount=transaction.order.amount,
        attempt_count=transaction.recovery.attempt_count,
        window_expired=window_expired,
        recoverable=bool(classification["recoverable"]),
        route_score=smart.route_score,
        high_risk=high_risk,
        max_attempts=transaction.recovery.max_attempts,
        amount_limit=int(thresholds.get("amount_limit") or 10000),
    )
    if decision.get("no_eligible"):
        smart.policy_allowed = False
        smart.policy_reason = "No eligible automated recovery route remains."
        smart.policy_blocked = True
        smart.guardrail_status = "BLOCKED"
        policy = {
            "allowed": False,
            "reason": smart.policy_reason,
            "code": "NO_ELIGIBLE",
        }
    else:
        smart.policy_allowed = policy["allowed"]
        smart.policy_reason = policy["reason"]
        smart.policy_blocked = not policy["allowed"]

    source = transaction.model_dump(mode="json")
    execution_guard = validate_route_execution(
        source,
        expected_amount=transaction.order.amount,
        expected_link=_canonical_link(transaction.transaction_id),
        selected_route=smart.selected_route,
    )
    if not policy["allowed"]:
        smart.guardrail_status = "BLOCKED"
        append_audit(
            transaction,
            action="FAILURE_CLASSIFIED",
            actor=Actor.RECOVERY_ENGINE.value,
            previous_state=transaction.state,
            new_state=transaction.state,
            metadata={"category": classification["category"], "recoverable": classification["recoverable"]},
        )
        append_audit(
            transaction,
            action="ROUTES_EVALUATED",
            actor=Actor.RECOVERY_ENGINE.value,
            previous_state=transaction.state,
            new_state=transaction.state,
            metadata={"count": smart.routes_evaluated_count, "simulated": True},
        )
        append_audit(
            transaction,
            action="ROUTE_SELECTED",
            actor=Actor.RECOVERY_ENGINE.value,
            previous_state=transaction.state,
            new_state=transaction.state,
            metadata={"route": smart.selected_route, "score": smart.route_score},
        )
        append_audit(
            transaction,
            action="GUARDRAIL_BLOCKED",
            actor=Actor.GUARDRAIL.value,
            previous_state=transaction.state,
            new_state=transaction.state,
            metadata={"reason": policy["reason"], "code": policy["code"], "policy_version": thresholds.get("policy_version")},
        )
        _record_recovery_decision(
            transaction,
            policy=policy,
            guard=execution_guard,
            blocked_rails=set(payload.get("blocked_rails") or []),
            thresholds=thresholds,
            learned=learned,
            no_eligible=bool(decision.get("no_eligible")),
        )
        await store.upsert(transaction)
        escalated = await escalate_transaction(
            transaction_id,
            trigger="POLICY_BLOCKED",
            reason=policy["reason"],
        )
        current = escalated or transaction
        return SelectRecoveryRouteResponse(
            transaction_id=current.transaction_id,
            failure_classification={
                "category": classification["category"],
                "recoverable": classification["recoverable"],
            },
            selected_route={
                "route_id": smart.selected_route,
                "score": smart.route_score,
                "confidence": smart.confidence,
            },
            alternatives=[row.model_dump() for row in smart.alternatives],
            reason=policy["reason"],
            why=smart.why,
            guardrail_status="BLOCKED",
            scored_routes=[row.model_dump() for row in smart.scored_routes],
            transaction=current,
        )

    smart.guardrail_status = "PASSED" if execution_guard.passed else "BLOCKED"
    append_audit(
        transaction,
        action="FAILURE_CLASSIFIED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=transaction.state,
        new_state=transaction.state,
        metadata={"category": classification["category"], "recoverable": classification["recoverable"]},
    )
    append_audit(
        transaction,
        action="ROUTES_EVALUATED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=transaction.state,
        new_state=transaction.state,
        metadata={
            "count": smart.routes_evaluated_count,
            "routes": [row.route for row in smart.scored_routes if row.eligible],
            "simulated": True,
        },
    )
    append_audit(
        transaction,
        action="ROUTE_SELECTED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=transaction.state,
        new_state=transaction.state,
        metadata={
            "route": smart.selected_route,
            "score": smart.route_score,
            "confidence": smart.confidence,
            "reason": smart.reason,
        },
    )
    append_audit(
        transaction,
        action="GUARDRAIL_VALIDATED" if execution_guard.passed else "GUARDRAIL_BLOCKED",
        actor=Actor.GUARDRAIL.value,
        previous_state=transaction.state,
        new_state=transaction.state,
        metadata={
            "guardrail_status": smart.guardrail_status,
            "reason": execution_guard.blocked_reason,
            "passed": execution_guard.passed,
            "policy_version": thresholds.get("policy_version"),
        },
        reason=execution_guard.reason,
    )
    if not execution_guard.passed:
        _record_recovery_decision(
            transaction,
            policy=policy,
            guard=execution_guard,
            blocked_rails=set(payload.get("blocked_rails") or []),
            thresholds=thresholds,
            learned=learned,
        )
        await store.upsert(transaction)
        escalated = await escalate_transaction(
            transaction_id,
            trigger="GUARDRAIL_BLOCKED",
            reason=execution_guard.blocked_reason or execution_guard.reason or "Guardrail blocked automated recovery.",
        )
        current = escalated or transaction
        return SelectRecoveryRouteResponse(
            transaction_id=current.transaction_id,
            failure_classification={
                "category": classification["category"],
                "recoverable": classification["recoverable"],
            },
            selected_route={
                "route_id": smart.selected_route,
                "score": smart.route_score,
                "confidence": smart.confidence,
            },
            alternatives=[row.model_dump() for row in smart.alternatives],
            reason=execution_guard.blocked_reason or execution_guard.reason,
            why=smart.why,
            guardrail_status="BLOCKED",
            scored_routes=[row.model_dump() for row in smart.scored_routes],
            transaction=current,
        )
    _record_recovery_decision(
        transaction,
        policy=policy,
        guard=execution_guard,
        blocked_rails=set(payload.get("blocked_rails") or []),
        thresholds=thresholds,
        learned=learned,
        no_eligible=bool(decision.get("no_eligible")),
    )
    await store.upsert(transaction)
    await store.record_route_decision(
        smart.selected_route or "UNKNOWN",
        int(smart.route_score or 0),
        RoutingEvent(
            timestamp=utcnow(),
            transaction_id=transaction.transaction_id,
            event="ROUTE_SELECTED",
            route=smart.selected_route,
            score=smart.route_score,
            message=f"{smart.display_name} selected · Score {smart.route_score}",
        ),
    )
    saved = await store.get(transaction.transaction_id)
    current = saved or transaction
    return SelectRecoveryRouteResponse(
        transaction_id=current.transaction_id,
        failure_classification={
            "category": classification["category"],
            "recoverable": classification["recoverable"],
        },
        selected_route={
            "route_id": smart.selected_route,
            "score": smart.route_score,
            "confidence": smart.confidence,
        },
        alternatives=[row.model_dump() for row in smart.alternatives],
        reason=smart.reason,
        why=smart.why,
        guardrail_status=smart.guardrail_status,
        scored_routes=[row.model_dump() for row in smart.scored_routes],
        transaction=current,
    )


def _mark_recovered(transaction: Transaction, actor: str, route_id: str) -> None:
    previous = apply_state(transaction, TransactionState.RECOVERED)
    now = utcnow()
    smart = _ensure_smart(transaction)
    transaction.recovery.recovered_at = now
    transaction.recovery.cart_held = False
    transaction.cart_status = CartStatus.RELEASED
    transaction.money_recovered = transaction.order.amount
    transaction.order.cart_released_at = now
    smart.last_outcome = "SUCCEEDED"
    append_audit(
        transaction,
        action="RECOVERY_ROUTE_SUCCEEDED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=previous,
        new_state=TransactionState.RECOVERED,
        metadata={"route": route_id, "amount": transaction.order.amount, "simulated": True},
    )
    append_audit(
        transaction,
        action="PAYMENT_RECOVERED",
        actor=actor,
        previous_state=previous,
        new_state=TransactionState.RECOVERED,
        metadata={
            "amount": transaction.order.amount,
            "display": rupee(transaction.order.amount),
            "money_recovered": transaction.money_recovered,
            "route": route_id,
        },
    )
    append_audit(
        transaction,
        action="CART_RELEASED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=TransactionState.RECOVERED,
        new_state=TransactionState.RECOVERED,
        metadata={"reservation_id": transaction.order.reservation_id, "reason": "recovered", "cart_status": "RELEASED"},
    )


async def execute_selected_route(
    transaction_id: str,
    actor: str = Actor.OPERATOR.value,
    *,
    claimed_amount: int | None = None,
    claimed_link: str | None = None,
) -> ExecuteSelectedRouteResponse:
    try:
        async with store.locked(transaction_id):
            return await _execute_selected_route(
                transaction_id,
                actor=actor,
                claimed_amount=claimed_amount,
                claimed_link=claimed_link,
            )
    except ConcurrencyError:
        transaction = await store.get(transaction_id)
        if transaction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
        if transaction.state == TransactionState.RECOVERED:
            return ExecuteSelectedRouteResponse(
                executed=False,
                blocked=True,
                outcome="BLOCKED",
                reason="Transaction has already been recovered.",
                transaction=transaction,
            )
        if transaction.state == TransactionState.ESCALATED:
            return ExecuteSelectedRouteResponse(
                executed=False,
                blocked=True,
                outcome="BLOCKED",
                reason="Stopping rule already released this held cart.",
                transaction=transaction,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transaction was updated concurrently. Retry the recovery action.",
        )


async def _execute_selected_route(
    transaction_id: str,
    actor: str = Actor.OPERATOR.value,
    *,
    claimed_amount: int | None = None,
    claimed_link: str | None = None,
) -> ExecuteSelectedRouteResponse:
    transaction = await store.get(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    if transaction.state == TransactionState.RECOVERED:
        return ExecuteSelectedRouteResponse(
            executed=False,
            blocked=True,
            outcome="BLOCKED",
            reason="Transaction has already been recovered.",
            transaction=transaction,
        )
    if transaction.state == TransactionState.ESCALATED:
        return ExecuteSelectedRouteResponse(
            executed=False,
            blocked=True,
            outcome="BLOCKED",
            reason="Stopping rule already released this held cart.",
            transaction=transaction,
        )
    if not is_active_recovery(transaction.state):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Route execution requires an active recovery state.",
        )

    smart = _ensure_smart(transaction)
    if not smart.selected_route:
        selected = await select_recovery_route(transaction_id)
        transaction = selected.transaction
        smart = _ensure_smart(transaction)
        if not is_active_recovery(transaction.state):
            return ExecuteSelectedRouteResponse(
                executed=False,
                blocked=True,
                outcome="ESCALATED" if transaction.state == TransactionState.ESCALATED else "BLOCKED",
                reason=smart.policy_reason or "Automated recovery was blocked.",
                route=smart.selected_route,
                transaction=transaction,
            )

    if utcnow() >= transaction.recovery.window_expires_at:
        escalated = await escalate_transaction(
            transaction_id,
            trigger="RECOVERY_WINDOW_EXPIRED",
            reason="Recovery window expired.",
        )
        return ExecuteSelectedRouteResponse(
            executed=False,
            blocked=True,
            outcome="ESCALATED",
            reason="Recovery window expired.",
            transaction=escalated or transaction,
        )

    route_id = smart.selected_route or ""
    catalog = ROUTE_CATALOG.get(route_id)
    if catalog is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Selected route is not available.")
    if route_id in transaction.recovery.cooldown_routes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Selected route is in cooldown after a previous failure.",
        )

    source = transaction.model_dump(mode="json")
    guard = validate_route_execution(
        source,
        expected_amount=claimed_amount if claimed_amount is not None else transaction.order.amount,
        expected_link=claimed_link if claimed_link is not None else _canonical_link(transaction.transaction_id),
        selected_route=route_id,
    )
    window_expired = utcnow() >= transaction.recovery.window_expires_at
    classification = smart.failure_classification
    recoverable = bool(classification.recoverable) if classification else True
    high_risk = bool(classification and classification.category == "RISK_FAILURE")
    thresholds: dict = {}
    try:
        from app.engine.policy import get_thresholds

        thresholds = await get_thresholds(transaction.tenant_id)
    except Exception:
        thresholds = {}
    policy = evaluate_policy(
        amount=transaction.order.amount,
        attempt_count=transaction.recovery.attempt_count,
        window_expired=window_expired,
        recoverable=recoverable,
        route_score=smart.route_score,
        high_risk=high_risk,
        max_attempts=transaction.recovery.max_attempts,
        amount_limit=int(thresholds.get("amount_limit") or 10000),
    )
    if not policy["allowed"] or not guard.passed:
        reason = policy["reason"] if not policy["allowed"] else (guard.blocked_reason or "Guardrail blocked.")
        smart.guardrail_status = "BLOCKED"
        append_audit(
            transaction,
            action="GUARDRAIL_BLOCKED",
            actor=Actor.GUARDRAIL.value,
            previous_state=transaction.state,
            new_state=transaction.state,
            metadata={"reason": reason, "policy_version": thresholds.get("policy_version")},
        )
        _record_recovery_decision(
            transaction,
            policy=policy,
            guard=guard,
            thresholds=thresholds,
        )
        await store.upsert(transaction)
        escalated = await escalate_transaction(transaction_id, trigger="GUARDRAIL_BLOCKED", reason=reason)
        return ExecuteSelectedRouteResponse(
            executed=False,
            blocked=True,
            outcome="ESCALATED",
            reason=reason,
            route=route_id,
            transaction=escalated or transaction,
        )

    strategy = (classification.strategy if classification else "RETRY") or "RETRY"
    phase_state = TransactionState.REROUTING if strategy == "REROUTE" else TransactionState.RETRYING
    previous_state = apply_state(transaction, phase_state)
    smart.recovery_phase = phase_state.value
    transaction.routing.recovery_strategy = strategy

    append_audit(
        transaction,
        action="GUARDRAIL_VALIDATED",
        actor=Actor.GUARDRAIL.value,
        previous_state=previous_state,
        new_state=phase_state,
        metadata={"guardrail_status": "PASSED", "route": route_id, "reason": guard.reason, "policy_version": thresholds.get("policy_version")},
    )
    append_audit(
        transaction,
        action="RECOVERY_ROUTE_EXECUTED",
        actor=actor,
        previous_state=previous_state,
        new_state=phase_state,
        metadata={"route": route_id, "simulated": True, "amount": transaction.order.amount, "strategy": strategy, "policy_version": thresholds.get("policy_version")},
    )
    rail = get_payment_rail()
    attempt = await rail.attempt(transaction, route_id)
    succeeded = attempt.succeeded
    try:
        from app.engine.circuit_breaker import record_outcome

        await record_outcome(route_id, succeeded)
        await record_outcome(transaction.bank, succeeded)
    except Exception:
        pass
    transaction.recovery.attempt_count += 1
    transaction.recovery.retry_count = transaction.recovery.attempt_count
    transaction.recovery.last_attempt_at = utcnow()
    smart.attempted_routes = list(smart.attempted_routes) + [route_id]

    if succeeded:
        if len(smart.attempted_routes) <= 1:
            smart.first_route_recovery = True
        else:
            smart.fallback_recovery = True
        _record_route_attempt(transaction, route_id, "SUCCEEDED", f"{route_id} recovered the payment.")
        _mark_recovered(transaction, actor, route_id)
        _record_recovery_decision(
            transaction,
            policy=policy,
            guard=guard,
            thresholds=thresholds,
            rescued=True,
        )
        await store.upsert(transaction)
        try:
            from app.engine.webhooks import emit_resolution_event

            await emit_resolution_event(transaction.transaction_id, "RECOVERED", transaction.order.amount)
        except Exception:
            pass
        await store.record_route_outcome(
            route_id,
            True,
            RoutingEvent(
                timestamp=utcnow(),
                transaction_id=transaction.transaction_id,
                event="RECOVERY_ROUTE_SUCCEEDED",
                route=route_id,
                score=smart.route_score,
                message=f"{smart.display_name} succeeded",
            ),
        )
        saved = await store.get(transaction.transaction_id)
        return ExecuteSelectedRouteResponse(
            executed=True,
            succeeded=True,
            outcome="SUCCEEDED",
            route=route_id,
            simulated=True,
            transaction=saved or transaction,
        )

    transaction.recovery.cooldown_routes = list(dict.fromkeys([*transaction.recovery.cooldown_routes, route_id]))
    smart.cooldown_routes = list(transaction.recovery.cooldown_routes)
    smart.last_outcome = "FAILED"
    _record_route_attempt(transaction, route_id, "FAILED", f"{route_id} failed. Evaluating an alternate route.")
    append_audit(
        transaction,
        action="RECOVERY_ROUTE_FAILED",
        actor=Actor.RECOVERY_ENGINE.value,
        previous_state=transaction.state,
        new_state=transaction.state,
        metadata={"route": route_id, "attempt": transaction.recovery.attempt_count, "simulated": True},
    )
    await store.record_route_outcome(
        route_id,
        False,
        RoutingEvent(
            timestamp=utcnow(),
            transaction_id=transaction.transaction_id,
            event="RECOVERY_ROUTE_FAILED",
            route=route_id,
            score=smart.route_score,
            message=f"{smart.display_name} failed · Fallback evaluation started",
        ),
    )

    if transaction.recovery.attempt_count >= MAX_ATTEMPTS:
        await store.upsert(transaction)
        escalated = await escalate_transaction(
            transaction_id,
            trigger="ROUTING_ATTEMPTS_EXHAUSTED",
            reason="Maximum recovery attempts have been reached.",
        )
        return ExecuteSelectedRouteResponse(
            executed=True,
            succeeded=False,
            outcome="ESCALATED",
            route=route_id,
            reason="Maximum recovery attempts have been reached.",
            simulated=True,
            transaction=escalated or transaction,
        )

    await store.upsert(transaction)
    next_decision = await select_recovery_route(transaction_id)
    return ExecuteSelectedRouteResponse(
        executed=True,
        succeeded=False,
        outcome="FAILED",
        route=route_id,
        reason=f"{ROUTE_CATALOG[route_id]['display_name']} failed. Next safe route selected.",
        simulated=True,
        transaction=next_decision.transaction,
    )


async def recover_transaction_with_routing(
    transaction_id: str,
    actor: str = Actor.OPERATOR.value,
) -> ExecuteRecoveryResponse:
    current = await store.get(transaction_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    last: ExecuteSelectedRouteResponse | None = None
    from app.engine.retry import backoff_seconds

    for attempt in range(MAX_ATTEMPTS):
        last = await execute_selected_route(transaction_id, actor=actor)
        if last.outcome in {"SUCCEEDED", "ESCALATED", "BLOCKED"}:
            break
        if last.transaction.state not in (
            TransactionState.AUTOMATED_LOOP,
            TransactionState.RETRYING,
            TransactionState.REROUTING,
        ):
            break
        delay = backoff_seconds(attempt)
        if delay:
            await asyncio.sleep(delay)
    if last is None:
        return ExecuteRecoveryResponse(executed=False, blocked=True, reason="No route executed.", transaction=current)
    return ExecuteRecoveryResponse(
        executed=last.executed and last.succeeded,
        blocked=last.blocked or last.outcome in {"ESCALATED", "BLOCKED"} and not last.succeeded,
        reason=last.reason,
        transaction=last.transaction,
    )


async def run_smart_routing_batch(transaction_ids: list[str]) -> RoutingSummary:
    first_route = 0
    fallback = 0
    routes_evaluated = 0
    recovered_ids: list[str] = []
    escalated_ids: list[str] = []
    attempts_total = 0
    effective: dict[str, int] = {}

    for transaction_id in transaction_ids:
        await asyncio.sleep(0.03)
        before = await store.get(transaction_id)
        if before is None or not is_active_recovery(before.state):
            continue
        result = await recover_transaction_with_routing(transaction_id, actor=Actor.OPERATOR.value)
        after = result.transaction
        smart = after.smart_routing
        if smart:
            routes_evaluated += max(smart.routes_evaluated_count, 1)
            attempts_total += after.recovery.attempt_count
            if after.state == TransactionState.RECOVERED:
                recovered_ids.append(after.transaction_id)
                if smart.first_route_recovery:
                    first_route += 1
                if smart.fallback_recovery:
                    fallback += 1
                if smart.selected_route:
                    effective[smart.selected_route] = effective.get(smart.selected_route, 0) + 1
            elif after.state == TransactionState.ESCALATED:
                escalated_ids.append(after.transaction_id)
        elif after.state == TransactionState.RECOVERED:
            recovered_ids.append(after.transaction_id)
        elif after.state == TransactionState.ESCALATED:
            escalated_ids.append(after.transaction_id)

    looping = [txn for txn in await store.list_all() if txn.transaction_id in transaction_ids]
    revenue_recovered = sum(txn.order.amount for txn in looping if txn.state == TransactionState.RECOVERED)
    revenue_at_risk = sum(txn.order.amount for txn in looping if is_active_recovery(txn.state))
    evaluated = len([txn_id for txn_id in transaction_ids if txn_id])
    avg = round(attempts_total / max(len(recovered_ids) + len(escalated_ids), 1), 1)
    most = max(effective.items(), key=lambda item: item[1])[0] if effective else None
    summary = RoutingSummary(
        transactions_evaluated=evaluated,
        routes_evaluated=routes_evaluated,
        recovered=len(recovered_ids),
        escalated=len(escalated_ids),
        first_route_recovery=first_route,
        fallback_recovery=fallback,
        average_attempts=avg,
        revenue_recovered=revenue_recovered,
        revenue_at_risk=revenue_at_risk,
        most_effective_route=most,
    )
    await store.save_routing_summary(summary)
    await store.record_routing_event(
        RoutingEvent(
            timestamp=utcnow(),
            transaction_id="BATCH",
            event="SMART_ROUTING_SUMMARY",
            message=(
                f"{summary.recovered} recovered · {summary.escalated} escalated · "
                f"most effective {summary.most_effective_route or 'n/a'}"
            ),
        )
    )
    return summary


__all__ = [
    "classify_transaction",
    "execute_selected_route",
    "recover_transaction_with_routing",
    "run_smart_routing_batch",
    "select_recovery_route",
    "simulate_route_outcome",
]

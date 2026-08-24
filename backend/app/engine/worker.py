from __future__ import annotations

import asyncio

from app.engine.lifecycle import (
    enter_automated_loop as start_automated_loop,
    escalate_transaction,
    execute_recovery,
    utcnow,
)
from app.models import Actor, TransactionState, is_active_recovery
from app.store import store

LOOP_DELAY_SECONDS = 0.15


async def schedule_automated_loop(transaction_id: str) -> None:
    await asyncio.sleep(LOOP_DELAY_SECONDS)
    await start_automated_loop(transaction_id)


async def monitor_recovery_deadline(transaction_id: str) -> None:
    while True:
        transaction = await store.get(transaction_id)
        if transaction is None:
            return
        if transaction.state in (TransactionState.RECOVERED, TransactionState.ESCALATED):
            return
        remaining = (transaction.recovery.window_expires_at - utcnow()).total_seconds()
        if remaining <= 0:
            await escalate_transaction(transaction_id)
            return
        await asyncio.sleep(min(0.5, max(remaining, 0.05)))


async def auto_recover_after(transaction_id: str, delay: float) -> None:
    await asyncio.sleep(max(delay, LOOP_DELAY_SECONDS + 0.4))
    for _ in range(25):
        transaction = await store.get(transaction_id)
        if transaction is None:
            return
        if transaction.state in (TransactionState.RECOVERED, TransactionState.ESCALATED):
            return
        if is_active_recovery(transaction.state):
            await execute_recovery(transaction_id, actor=Actor.CUSTOMER_FALLBACK_LINK.value)
            return
        await asyncio.sleep(0.2)


async def run_recovery_simulation(selected_ids: list[str]) -> None:
    from app.engine.routing_service import run_smart_routing_batch

    await run_smart_routing_batch(selected_ids)


async def run_forced_route_failures(transaction_id: str) -> None:
    from app.engine.routing_service import execute_selected_route, select_recovery_route

    await asyncio.sleep(0.8)
    transaction = await store.get(transaction_id)
    if transaction is None or not is_active_recovery(transaction.state):
        return
    try:
        await select_recovery_route(transaction_id)
    except Exception:
        return
    for _ in range(3):
        await asyncio.sleep(0.7)
        result = await execute_selected_route(transaction_id, actor=Actor.OPERATOR.value)
        if result.outcome != "FAILED":
            return


async def supervise_checkout(
    transaction_id: str,
    *,
    auto_recover: bool = False,
    auto_recover_after_delay: float = 6.0,
    force_route_failure: bool = False,
) -> None:
    tasks = [asyncio.create_task(monitor_recovery_deadline(transaction_id))]
    if force_route_failure:
        tasks.append(asyncio.create_task(run_forced_route_failures(transaction_id)))
    if auto_recover:
        tasks.append(asyncio.create_task(auto_recover_after(transaction_id, auto_recover_after_delay)))
    await asyncio.gather(*tasks)

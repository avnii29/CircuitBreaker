"""Canonical transaction state machine.

Persisted lifecycle values are the Phase 1-5 enum. Additional product
language maps onto those values without renaming them:

* Decision ``RESCUED`` → state ``RECOVERED``
* Decision ``HOLD`` → state ``ESCALATED`` (manual-review queue)
* Simulated checkout has no ``PROCESSING`` state: the demo injects a
  bank-side failure immediately, so ``INITIATED`` → ``FAILED`` is the
  checkout path.

Illegal transitions raise ``IllegalTransition``. Same-state updates are
allowed so audit events can be appended without moving the machine.
"""

from __future__ import annotations

from app.models import Transaction, TransactionState

LEGAL_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.INITIATED: frozenset({TransactionState.FAILED}),
    TransactionState.FAILED: frozenset(
        {
            TransactionState.AUTOMATED_LOOP,
            TransactionState.ESCALATED,
            TransactionState.RECOVERED,
        }
    ),
    TransactionState.AUTOMATED_LOOP: frozenset(
        {
            TransactionState.RETRYING,
            TransactionState.REROUTING,
            TransactionState.RECOVERED,
            TransactionState.ESCALATED,
        }
    ),
    TransactionState.RETRYING: frozenset(
        {
            TransactionState.RETRYING,
            TransactionState.REROUTING,
            TransactionState.RECOVERED,
            TransactionState.ESCALATED,
            TransactionState.AUTOMATED_LOOP,
        }
    ),
    TransactionState.REROUTING: frozenset(
        {
            TransactionState.REROUTING,
            TransactionState.RETRYING,
            TransactionState.RECOVERED,
            TransactionState.ESCALATED,
            TransactionState.AUTOMATED_LOOP,
        }
    ),
    TransactionState.RECOVERED: frozenset(),
    TransactionState.ESCALATED: frozenset(),
}

TERMINAL_STATES = frozenset({TransactionState.RECOVERED, TransactionState.ESCALATED})


class IllegalTransition(ValueError):
    def __init__(self, previous: TransactionState, new_state: TransactionState) -> None:
        self.previous = previous
        self.new_state = new_state
        super().__init__(f"Illegal transaction transition {previous.value} → {new_state.value}")


def can_transition(previous: TransactionState, new_state: TransactionState) -> bool:
    if previous == new_state:
        return True
    return new_state in LEGAL_TRANSITIONS.get(previous, frozenset())


def apply_state(transaction: Transaction, new_state: TransactionState) -> TransactionState:
    """Move ``transaction.state`` if the edge is legal. Returns the previous state."""
    previous = transaction.state
    if previous == new_state:
        return previous
    if not can_transition(previous, new_state):
        raise IllegalTransition(previous, new_state)
    transaction.state = new_state
    return previous

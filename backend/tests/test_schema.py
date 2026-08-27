from app.engine.lifecycle import append_audit, build_transaction
from app.engine.simulation import build_batch_spec
from app.models import Actor, SimulateCheckoutRequest, TransactionState
from app.schema_loader import validate_transaction_document


def test_batch_spec_is_exactly_fifty() -> None:
    spec = build_batch_spec(50)
    assert len(spec) == 50
    assert all(item["auto_recover"] is False for item in spec)
    banks = {item["bank"] for item in spec}
    assert {"HDFC", "SBI", "ICICI", "AXIS", "KOTAK", "YES"} <= banks
    demos = {item["demo_scenario"] for item in spec}
    assert {"CHECKOUT_ABANDONMENT", "SUBSCRIPTION_FAILURE", "OVERDUE_RECEIVABLE", "LOW_VALUE"} <= demos
    assert any(item["amount"] == 7200 for item in spec)
    assert any(item["amount"] == 80000 for item in spec)
    assert any(item["amount"] == 25 for item in spec)


def test_built_transaction_matches_schema() -> None:
    transaction = build_transaction(transaction_id="TXN_CB_000184")
    append_audit(
        transaction,
        action="PAYMENT_INITIATED",
        actor=Actor.MERCHANT_CHECKOUT.value,
        previous_state=None,
        new_state=TransactionState.INITIATED,
        metadata={"amount": transaction.order.amount},
    )
    validate_transaction_document(transaction.model_dump(mode="json"))


def test_built_checkout_event_matches_schema() -> None:
    transaction = build_transaction(
        SimulateCheckoutRequest(demo_scenario="CHECKOUT_ABANDONMENT", amount=7200, scenario="CHECKOUT_ABANDONMENT"),
        transaction_id="TXN_CB_000185",
    )
    append_audit(
        transaction,
        action="PAYMENT_INITIATED",
        actor=Actor.MERCHANT_CHECKOUT.value,
        previous_state=None,
        new_state=TransactionState.INITIATED,
        metadata={"amount": transaction.order.amount},
    )
    validate_transaction_document(transaction.model_dump(mode="json"))

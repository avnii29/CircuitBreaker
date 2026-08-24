from app.engine.guardrail import validate_ai_generated_payload
from app.formatting import rupee


def _record() -> dict:
    return {
        "transaction_id": "TXN_CB_000184",
        "state": "AUTOMATED_LOOP",
        "customer": {"name": "Rahul", "email": "rahul@example.com", "phone": "9876543210"},
        "order": {"amount": 1499},
        "recovery": {
            "payment_link": "https://rzp.io/demo/TXN_CB_000184",
            "attempt_count": 0,
            "max_attempts": 3,
            "window_expires_at": "2099-01-01T00:00:00+00:00",
        },
    }


def test_validate_accepts_complete_message() -> None:
    record = _record()
    message = (
        "Hi Rahul! Aapka ₹1,499 payment bank-side technical issue ki wajah se complete nahi ho paya. "
        "Aapka order temporarily secure hai. Neeche diye gaye recovery link se payment complete "
        "kar sakte hain: https://rzp.io/demo/TXN_CB_000184 (ref TXN_CB_000184)"
    )
    assert validate_ai_generated_payload(message, record) == message


def test_validate_rejects_amount_substitution() -> None:
    record = _record()
    bad = (
        "Hi Rahul! Aapka ₹2,499 ka payment complete nahi ho paya. "
        "Link: https://rzp.io/demo/TXN_CB_000184 (ref TXN_CB_000184)"
    )
    fallback = validate_ai_generated_payload(bad, record)
    assert "₹1,499" in fallback
    assert "TXN_CB_000184" in fallback
    assert fallback != bad


def test_validate_rejects_malformed_link() -> None:
    record = _record()
    bad = (
        "Hi Rahul! Aapka ₹1,499 ka payment complete nahi ho paya. "
        "Link: https://evil.example/pay (ref TXN_CB_000184)"
    )
    fallback = validate_ai_generated_payload(bad, record)
    assert "https://rzp.io/demo/TXN_CB_000184" in fallback


def test_fallback_contains_exact_amount() -> None:
    fallback = validate_ai_generated_payload("totally unrelated", _record())
    assert rupee(1499) in fallback
    assert "TXN_CB_000184" in fallback

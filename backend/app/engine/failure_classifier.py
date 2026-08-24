from __future__ import annotations

from typing import TypedDict


class FailureClassification(TypedDict):
    error_code: str
    category: str
    recoverable: bool
    severity: str
    recommended_routes: list[str]
    explanation: str
    strategy: str


CLASSIFIER: dict[str, FailureClassification] = {
    "ERR_NPCI_U30": {
        "error_code": "ERR_NPCI_U30",
        "category": "BANK_TECHNICAL_FAILURE",
        "recoverable": True,
        "severity": "medium",
        "recommended_routes": ["UPI_RETRY", "PAYMENT_LINK", "QR_FALLBACK"],
        "explanation": "Bank-side technical failure.",
        "strategy": "RETRY",
    },
    "ERR_NPCI_U28": {
        "error_code": "ERR_NPCI_U28",
        "category": "BANK_OR_NETWORK_UNAVAILABLE",
        "recoverable": True,
        "severity": "medium",
        "recommended_routes": ["PAYMENT_LINK", "QR_FALLBACK"],
        "explanation": "Bank or payment network unavailable.",
        "strategy": "REROUTE",
    },
    "ERR_TIMEOUT": {
        "error_code": "ERR_TIMEOUT",
        "category": "NETWORK_TIMEOUT",
        "recoverable": True,
        "severity": "medium",
        "recommended_routes": ["UPI_RETRY", "PAYMENT_LINK"],
        "explanation": "Payment request timed out.",
        "strategy": "RETRY",
    },
    "ERR_NETWORK_TIMEOUT": {
        "error_code": "ERR_NETWORK_TIMEOUT",
        "category": "NETWORK_TIMEOUT",
        "recoverable": True,
        "severity": "medium",
        "recommended_routes": ["UPI_RETRY", "PAYMENT_LINK"],
        "explanation": "Network request timed out.",
        "strategy": "RETRY",
    },
    "ERR_BANK_UNAVAILABLE": {
        "error_code": "ERR_BANK_UNAVAILABLE",
        "category": "BANK_OR_NETWORK_UNAVAILABLE",
        "recoverable": True,
        "severity": "medium",
        "recommended_routes": ["PAYMENT_LINK", "QR_FALLBACK"],
        "explanation": "Bank temporarily unavailable.",
        "strategy": "REROUTE",
    },
    "ERR_INSUFFICIENT_FUNDS": {
        "error_code": "ERR_INSUFFICIENT_FUNDS",
        "category": "CUSTOMER_FUNDS_FAILURE",
        "recoverable": False,
        "severity": "high",
        "recommended_routes": ["MANUAL_REVIEW"],
        "explanation": "Customer funds are insufficient. Automation will not retry collection.",
        "strategy": "HOLD",
    },
    "ERR_FRAUD_SUSPECTED": {
        "error_code": "ERR_FRAUD_SUSPECTED",
        "category": "RISK_FAILURE",
        "recoverable": False,
        "severity": "high",
        "recommended_routes": ["MANUAL_REVIEW"],
        "explanation": "Risk controls require human review.",
        "strategy": "BLOCK",
    },
    "ERR_RISK_BLOCK": {
        "error_code": "ERR_RISK_BLOCK",
        "category": "RISK_FAILURE",
        "recoverable": False,
        "severity": "high",
        "recommended_routes": ["MANUAL_REVIEW"],
        "explanation": "Risk or fraud controls blocked automated recovery.",
        "strategy": "BLOCK",
    },
    "ERR_BANK_DOWN": {
        "error_code": "ERR_BANK_DOWN",
        "category": "RAIL_OUTAGE",
        "recoverable": True,
        "severity": "medium",
        "recommended_routes": ["PAYMENT_LINK", "QR_FALLBACK"],
        "explanation": "Issuing rail or switch is down. Same-rail retry is unsafe; reroute to an alternate processor.",
        "strategy": "REROUTE",
    },
}


def classify_failure(error_code: str) -> FailureClassification:
    known = CLASSIFIER.get(error_code)
    if known:
        return known
    return {
        "error_code": error_code,
        "category": "BANK_TECHNICAL_FAILURE",
        "recoverable": True,
        "severity": "medium",
        "recommended_routes": ["PAYMENT_LINK", "QR_FALLBACK"],
        "explanation": "Unmapped simulation error. Treated as a recoverable technical decline.",
        "strategy": "RETRY",
    }

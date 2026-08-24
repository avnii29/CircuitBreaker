from __future__ import annotations

from typing import TypedDict


class ScenarioDefinition(TypedDict):
    error_code: str
    error_label: str
    diagnosis: str
    recommendation: str
    confidence: float
    reason_hinglish: str
    default_amount: int
    default_bank: str


SCENARIOS: dict[str, ScenarioDefinition] = {
    "U30": {
        "error_code": "ERR_NPCI_U30",
        "error_label": "Bank-side technical issue",
        "diagnosis": "Payment failed because the bank was temporarily unavailable.",
        "recommendation": "Send alternate payment route",
        "confidence": 98.4,
        "reason_hinglish": "bank-side technical issue",
        "default_amount": 1499,
        "default_bank": "HDFC",
    },
    "TIMEOUT": {
        "error_code": "ERR_TIMEOUT",
        "error_label": "Payment request timed out",
        "diagnosis": "Payment failed because the bank did not respond in time.",
        "recommendation": "Retry on an alternate payment route before the window expires",
        "confidence": 91.2,
        "reason_hinglish": "bank timeout",
        "default_amount": 2499,
        "default_bank": "SBI",
    },
    "U28": {
        "error_code": "ERR_NPCI_U28",
        "error_label": "Bank or payment network unavailable",
        "diagnosis": "Payment failed because the bank or payment network was unavailable.",
        "recommendation": "Send alternate payment route",
        "confidence": 93.1,
        "reason_hinglish": "bank-side technical issue",
        "default_amount": 999,
        "default_bank": "YES",
    },
    "TECHNICAL": {
        "error_code": "ERR_BANK_UNAVAILABLE",
        "error_label": "Bank temporarily unavailable",
        "diagnosis": "Payment failed because the bank was temporarily unavailable.",
        "recommendation": "Send alternate payment route",
        "confidence": 94.7,
        "reason_hinglish": "bank unavailable",
        "default_amount": 1899,
        "default_bank": "ICICI",
    },
    "NETWORK": {
        "error_code": "ERR_NETWORK_TIMEOUT",
        "error_label": "Network request timed out",
        "diagnosis": "Payment failed because the network request timed out before the bank confirmed it.",
        "recommendation": "Send alternate payment route",
        "confidence": 89.6,
        "reason_hinglish": "network timeout",
        "default_amount": 999,
        "default_bank": "AXIS",
    },
    "FUNDS": {
        "error_code": "ERR_INSUFFICIENT_FUNDS",
        "error_label": "Insufficient funds",
        "diagnosis": "Payment failed because the customer did not have sufficient funds.",
        "recommendation": "Escalate for customer follow-up",
        "confidence": 99.0,
        "reason_hinglish": "insufficient funds",
        "default_amount": 1499,
        "default_bank": "HDFC",
    },
    "FRAUD": {
        "error_code": "ERR_FRAUD_SUSPECTED",
        "error_label": "Fraud suspected",
        "diagnosis": "Payment failed because risk controls flagged the attempt.",
        "recommendation": "Stop automation and require operator review",
        "confidence": 99.0,
        "reason_hinglish": "risk review required",
        "default_amount": 2499,
        "default_bank": "SBI",
    },
    "RISK": {
        "error_code": "ERR_RISK_BLOCK",
        "error_label": "Risk block",
        "diagnosis": "Payment failed because risk controls blocked the attempt.",
        "recommendation": "Stop automation and require operator review",
        "confidence": 99.0,
        "reason_hinglish": "risk block",
        "default_amount": 1999,
        "default_bank": "HDFC",
    },
    "BANK_DOWN": {
        "error_code": "ERR_BANK_DOWN",
        "error_label": "Issuing rail unavailable",
        "diagnosis": "Payment failed because the issuing bank rail or switch is down.",
        "recommendation": "Reroute to an alternate payment processor",
        "confidence": 92.4,
        "reason_hinglish": "bank rail down",
        "default_amount": 1799,
        "default_bank": "SBI",
    },
}

ERROR_CATALOG = {
    definition["error_code"]: {
        "label": definition["error_label"],
        "diagnosis": definition["diagnosis"],
        "simulation_only": True,
    }
    for definition in SCENARIOS.values()
}

BANK_DISPLAY = {
    "HDFC": "HDFC Bank",
    "SBI": "SBI",
    "ICICI": "ICICI Bank",
    "AXIS": "Axis Bank",
    "KOTAK": "Kotak Mahindra Bank",
    "YES": "YES Bank",
}


SCENARIO_ALIASES = {
    "TRANSIENT_FAILURE": "U30",
    "HDFC_TECHNICAL": "U30",
    "SBI_TIMEOUT": "TIMEOUT",
    "BANK_OUTAGE": "BANK_DOWN",
    "GOLDEN_OUTAGE": "BANK_DOWN",
    "HARD_DECLINE": "FUNDS",
    "INSUFFICIENT_FUNDS": "FUNDS",
    "RISK_BLOCK": "RISK",
}


def resolve_scenario(bank: str | None, scenario: str | None) -> tuple[str, ScenarioDefinition]:
    key = SCENARIO_ALIASES.get((scenario or "").upper(), (scenario or "").upper())
    if key in SCENARIOS:
        definition = SCENARIOS[key]
        resolved_bank = (bank or definition["default_bank"]).upper()
        return resolved_bank, definition
    bank_key = (bank or "HDFC").upper()
    if bank_key == "SBI":
        return bank_key, SCENARIOS["TIMEOUT"]
    if bank_key == "ICICI":
        return bank_key, SCENARIOS["TECHNICAL"]
    if bank_key in ("AXIS", "KOTAK"):
        return bank_key, SCENARIOS["NETWORK"]
    if bank_key in ("YES", "YES BANK"):
        return "YES", SCENARIOS["U28"]
    return bank_key, SCENARIOS["U30"]


def bank_label(bank: str) -> str:
    return BANK_DISPLAY.get(bank.upper(), f"{bank} Bank")

from __future__ import annotations

from typing import TypedDict


class BankProfile(TypedDict):
    technical_failure_rate: float
    upi_retry_success: float
    payment_link_success: float
    qr_success: float


# DEMO SIMULATION PARAMETERS: not real bank production statistics.
BANK_PROFILES: dict[str, BankProfile] = {
    "HDFC": {
        "technical_failure_rate": 0.20,
        "upi_retry_success": 0.78,
        "payment_link_success": 0.86,
        "qr_success": 0.71,
    },
    "SBI": {
        "technical_failure_rate": 0.24,
        "upi_retry_success": 0.72,
        "payment_link_success": 0.82,
        "qr_success": 0.69,
    },
    "ICICI": {
        "technical_failure_rate": 0.16,
        "upi_retry_success": 0.81,
        "payment_link_success": 0.84,
        "qr_success": 0.74,
    },
    "AXIS": {
        "technical_failure_rate": 0.18,
        "upi_retry_success": 0.79,
        "payment_link_success": 0.83,
        "qr_success": 0.73,
    },
    "KOTAK": {
        "technical_failure_rate": 0.19,
        "upi_retry_success": 0.76,
        "payment_link_success": 0.81,
        "qr_success": 0.70,
    },
    "YES": {
        "technical_failure_rate": 0.22,
        "upi_retry_success": 0.74,
        "payment_link_success": 0.80,
        "qr_success": 0.68,
    },
}

DEFAULT_PROFILE: BankProfile = {
    "technical_failure_rate": 0.20,
    "upi_retry_success": 0.75,
    "payment_link_success": 0.85,
    "qr_success": 0.70,
}


def normalize_bank(bank: str) -> str:
    key = bank.upper().replace(" BANK", "").replace("BANK", "").strip()
    if key.startswith("YES"):
        return "YES"
    return key


def get_bank_profile(bank: str) -> BankProfile:
    return BANK_PROFILES.get(normalize_bank(bank), DEFAULT_PROFILE)


def route_success_probability(bank: str, route_id: str) -> float:
    profile = get_bank_profile(bank)
    if route_id == "UPI_RETRY":
        return profile["upi_retry_success"]
    if route_id == "PAYMENT_LINK":
        return profile["payment_link_success"]
    if route_id == "QR_FALLBACK":
        return profile["qr_success"]
    return 0.0

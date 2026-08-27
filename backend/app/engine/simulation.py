from __future__ import annotations

from typing import TypedDict


class BatchSpecItem(TypedDict):
    bank: str
    scenario: str
    auto_recover: bool
    amount: int
    customer_name: str
    customer_email: str
    customer_phone: str
    force_route_failure: bool
    demo_scenario: str


CUSTOMER_NAMES = [
    "Rahul Sharma",
    "Priya Mehta",
    "Arjun Rao",
    "Ananya Iyer",
    "Vikram Nair",
    "Sneha Kapoor",
    "Karan Malhotra",
    "Meera Joshi",
    "Rohan Desai",
    "Isha Patel",
]

AMOUNTS = [499, 799, 999, 1499, 1999, 2499, 3999, 4999]

BANKS_AND_SCENARIOS = [
    ("HDFC", "U30"),
    ("SBI", "TIMEOUT"),
    ("ICICI", "TECHNICAL"),
    ("AXIS", "NETWORK"),
    ("KOTAK", "U28"),
    ("YES", "U28"),
]


def build_batch_spec(count: int = 50) -> list[BatchSpecItem]:
    """Deterministic mix of revenue leakage events. Same seed every run."""
    spec: list[BatchSpecItem] = []
    for index in range(count):
        bank, scenario = BANKS_AND_SCENARIOS[index % len(BANKS_AND_SCENARIOS)]
        name = CUSTOMER_NAMES[index % len(CUSTOMER_NAMES)]
        first = name.split(" ")[0].lower()
        high_value = index % 10 == 9
        force_fail = index % 10 == 8
        slot = index % 10
        demo_scenario = ""
        amount = 15000 if high_value else AMOUNTS[index % len(AMOUNTS)]
        if slot == 0:
            demo_scenario = "CHECKOUT_ABANDONMENT"
            scenario = "CHECKOUT_ABANDONMENT"
            amount = 7200
            force_fail = False
        elif slot == 1:
            demo_scenario = "SUBSCRIPTION_FAILURE"
            scenario = "SUBSCRIPTION_FAILURE"
            amount = 1499
            force_fail = False
        elif slot == 2:
            demo_scenario = "OVERDUE_RECEIVABLE"
            scenario = "OVERDUE_RECEIVABLE"
            amount = 80000
            force_fail = False
        elif slot == 3:
            demo_scenario = "LOW_VALUE"
            amount = 25
            force_fail = False
        elif slot == 4:
            scenario = "FUNDS"
            amount = 1499
            force_fail = False
        elif slot == 5:
            scenario = "RISK"
            amount = 1999
            force_fail = False
        spec.append(
            {
                "bank": bank,
                "scenario": scenario,
                "auto_recover": False,
                "amount": amount,
                "customer_name": name,
                "customer_email": f"{first}@example.com",
                "customer_phone": "9876543210",
                "force_route_failure": force_fail,
                "demo_scenario": demo_scenario,
            }
        )
    return spec

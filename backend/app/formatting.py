def format_inr(amount: int) -> str:
    """Indian grouping: 1499 → 1,499 ; 150000 → 1,50,000."""
    sign = "-" if amount < 0 else ""
    digits = str(abs(int(amount)))
    if len(digits) <= 3:
        return f"{sign}{digits}"
    last_three = digits[-3:]
    rest = digits[:-3]
    groups: list[str] = []
    while rest:
        groups.append(rest[-2:])
        rest = rest[:-2]
        grouped = ",".join([*reversed(groups), last_three])
    return f"{sign}{grouped}"


def rupee(amount: int) -> str:
    return f"₹{format_inr(amount)}"

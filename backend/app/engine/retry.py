from __future__ import annotations

import random

from app.config import settings


def backoff_seconds(attempt: int, base: float = 1.0, cap: float = 20.0) -> float:
    if settings.DEMO_MODE:
        return 0.0
    raw = min(cap, base * (2 ** max(attempt, 0)))
    jitter = 0.5 + random.random()
    return round(raw * jitter, 3)

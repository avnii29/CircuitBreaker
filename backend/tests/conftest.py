from __future__ import annotations

import os
from pathlib import Path

for _db in (Path(__file__).resolve().parent.parent / ".pytest_cb.db", Path(__file__).resolve().parent / ".pytest_cb.db"):
    if _db.exists():
        _db.unlink()

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.pytest_cb.db")
os.environ.setdefault("API_KEY_READ", "test-read-key")
os.environ.setdefault("API_KEY_WRITE", "test-write-key")
os.environ.setdefault("API_KEY_OPS", "test-ops-key")
os.environ.setdefault(
    "TENANT_KEYS_JSON",
    '[{"tenant_id":"TENANT_A","read":"key-a-read","write":"key-a-write"},{"tenant_id":"TENANT_B","read":"key-b-read","write":"key-b-write"}]',
)
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.setdefault("WEBHOOK_URL", "")
os.environ.setdefault("MAX_RECOVERY_ATTEMPTS", "3")
os.environ.setdefault("CIRCUIT_MIN_SAMPLES", "8")
os.environ.setdefault("CIRCUIT_FAILURE_RATE_THRESHOLD", "0.30")
os.environ.setdefault("CIRCUIT_ANOMALY_MIN_SAMPLES", "3")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ.setdefault("REDIS_URL", "")

from fastapi.testclient import TestClient

_orig_init = TestClient.__init__


def _patched_init(self, *args, **kwargs):
    headers = dict(kwargs.pop("headers", None) or {})
    headers.setdefault("X-API-Key", os.environ["API_KEY_WRITE"])
    kwargs["headers"] = headers
    _orig_init(self, *args, **kwargs)


TestClient.__init__ = _patched_init  # type: ignore[method-assign]

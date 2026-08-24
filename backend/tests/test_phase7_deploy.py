from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, normalize_database_url
from app.engine.diagnostic import resolve_scenario
from app.main import app

client = TestClient(app)


def test_managed_postgres_urls_are_normalized() -> None:
    assert normalize_database_url("postgres://user:pass@db.example/circuitbreaker").startswith(
        "postgresql+asyncpg://"
    )
    assert normalize_database_url("postgresql://user:pass@db.example/circuitbreaker").startswith(
        "postgresql+asyncpg://"
    )
    already = "postgresql+asyncpg://user:pass@db.example/circuitbreaker"
    assert normalize_database_url(already) == already


def test_sqlite_rejected_when_schema_is_not_auto_created(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./deploy.db")
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "false")
    monkeypatch.setenv("CORS_ORIGINS", "https://circuitbreaker.vercel.app")
    monkeypatch.setenv("API_KEY_READ", "read-key")
    monkeypatch.setenv("API_KEY_WRITE", "write-key")
    try:
        Settings(_env_file=None)
        raise AssertionError("expected sqlite to be rejected")
    except ValidationError as exc:
        assert "PostgreSQL" in str(exc)


def test_wildcard_cors_rejected_in_deploy_mode(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example/circuitbreaker")
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "false")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.setenv("API_KEY_READ", "read-key")
    monkeypatch.setenv("API_KEY_WRITE", "write-key")
    try:
        Settings(_env_file=None)
        raise AssertionError("expected wildcard CORS to be rejected")
    except ValidationError as extra:
        assert "CORS_ORIGINS" in str(extra)


def test_demo_failure_aliases_use_simulated_rails() -> None:
    _, transient = resolve_scenario("HDFC", "TRANSIENT_FAILURE")
    _, outage = resolve_scenario("SBI", "BANK_OUTAGE")
    _, decline = resolve_scenario("HDFC", "HARD_DECLINE")
    _, risk = resolve_scenario("HDFC", "RISK_BLOCK")
    assert transient["error_code"] == "ERR_NPCI_U30"
    assert outage["error_code"] == "ERR_BANK_DOWN"
    assert decline["error_code"] == "ERR_INSUFFICIENT_FUNDS"
    assert risk["error_code"] == "ERR_RISK_BLOCK"


def test_health_aliases_and_readiness_check_dependencies() -> None:
    live = client.get("/api/v1/health/live")
    ready = client.get("/api/v1/health/ready")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert body["redis"] == "not_configured"

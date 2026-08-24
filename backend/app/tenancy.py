from __future__ import annotations

import hmac
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass

from app.config import settings


def keys_match(provided: str, expected: str) -> bool:
    if not expected or not provided:
        return False
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


@dataclass
class TenantPrincipal:
    tenant_id: str
    scope: str
    is_ops: bool = False
    requested_tenant: str | None = None

    @property
    def active_tenant(self) -> str | None:
        """Tenant to write as. Ops aggregate reads return None."""
        if self.is_ops:
            return self.requested_tenant
        return self.tenant_id


_principal: ContextVar[TenantPrincipal | None] = ContextVar("cb_principal", default=None)


def set_principal(principal: TenantPrincipal) -> Token:
    return _principal.set(principal)


def reset_principal(token: Token) -> None:
    _principal.reset(token)


def current_principal() -> TenantPrincipal | None:
    return _principal.get()


def write_tenant_id() -> str:
    principal = current_principal()
    if principal is None:
        return settings.DEFAULT_TENANT_ID
    if principal.is_ops:
        return principal.requested_tenant or settings.DEFAULT_TENANT_ID
    return principal.tenant_id


def query_tenant_id() -> str | None:
    """None means unscoped (ops aggregate)."""
    principal = current_principal()
    if principal is None:
        return settings.DEFAULT_TENANT_ID
    if principal.is_ops:
        return principal.requested_tenant
    return principal.tenant_id


def parse_tenant_keys() -> dict[str, dict[str, str]]:
    raw = (settings.TENANT_KEYS_JSON or "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        return {}
    mapped: dict[str, dict[str, str]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        tenant_id = str(item.get("tenant_id") or "")
        if not tenant_id:
            continue
        mapped[tenant_id] = {
            "read": str(item.get("read") or ""),
            "write": str(item.get("write") or ""),
        }
    return mapped


def resolve_api_key(api_key: str) -> TenantPrincipal | None:
    if not api_key:
        return None
    if settings.API_KEY_OPS and keys_match(api_key, settings.API_KEY_OPS):
        return TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write", is_ops=True)
    if keys_match(api_key, settings.API_KEY_WRITE):
        return TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="write")
    if keys_match(api_key, settings.API_KEY_READ):
        return TenantPrincipal(tenant_id=settings.DEFAULT_TENANT_ID, scope="read")
    for tenant_id, keys in parse_tenant_keys().items():
        if keys.get("write") and keys_match(api_key, keys["write"]):
            return TenantPrincipal(tenant_id=tenant_id, scope="write")
        if keys.get("read") and keys_match(api_key, keys["read"]):
            return TenantPrincipal(tenant_id=tenant_id, scope="read")
    return None


def list_known_tenants() -> list[str]:
    tenants = [settings.DEFAULT_TENANT_ID]
    for tenant_id in parse_tenant_keys():
        if tenant_id not in tenants:
            tenants.append(tenant_id)
    return tenants

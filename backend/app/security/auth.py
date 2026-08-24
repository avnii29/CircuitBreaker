from __future__ import annotations

import logging
import secrets
from typing import Literal

from fastapi import Depends, Header, HTTPException, Request, status

from app.observability.logging import log_event
from app.tenancy import TenantPrincipal, current_principal, resolve_api_key, set_principal

logger = logging.getLogger("circuitbreaker.auth")

Scope = Literal["read", "write"]


async def require_read(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> Scope:
    key = x_api_key or request.headers.get("X-API-Key")
    principal = resolve_api_key(key or "")
    if principal is None:
        log_event(logger, "auth_denied", outcome="DENIED", extra_payload={"path": request.url.path})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    if x_tenant_id and principal.is_ops:
        principal.requested_tenant = x_tenant_id
    elif x_tenant_id and x_tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-tenant access denied.")
    set_principal(principal)
    request.state.auth_scope = principal.scope
    request.state.tenant_id = principal.active_tenant or principal.tenant_id
    request.state.is_ops = principal.is_ops
    request.state.api_key_fingerprint = secrets.token_hex(4)
    return principal.scope  # type: ignore[return-value]


async def require_write(scope: Scope = Depends(require_read)) -> Scope:
    principal = current_principal()
    if principal is None or principal.scope != "write":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Write scope required.")
    return "write"


async def require_ops(scope: Scope = Depends(require_read)) -> TenantPrincipal:
    principal = current_principal()
    if principal is None or not principal.is_ops:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ops scope required.")
    return principal

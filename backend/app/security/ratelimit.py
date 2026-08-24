from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.cache import incr_window
from app.config import settings
from app.tenancy import write_tenant_id


async def limit_checkout(request: Request) -> None:
    identity = request.headers.get("X-API-Key") or (request.client.host if request.client else "unknown")
    tenant = write_tenant_id()
    count = await incr_window(f"checkout:{tenant}:{identity[-12:]}", 60)
    if count > settings.RATE_LIMIT_CHECKOUT_PER_MINUTE:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")


async def limit_recovery(request: Request) -> None:
    identity = request.headers.get("X-API-Key") or (request.client.host if request.client else "unknown")
    tenant = write_tenant_id()
    count = await incr_window(f"recovery:{tenant}:{identity[-12:]}", 60)
    if count > settings.RATE_LIMIT_RECOVERY_PER_MINUTE:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")

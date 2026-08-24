from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models import RoutingPerformanceResponse
from app.security.auth import require_read
from app.store import store

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/performance", response_model=RoutingPerformanceResponse)
async def routing_performance() -> RoutingPerformanceResponse:
    return await store.routing_performance()

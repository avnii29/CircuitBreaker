from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.cache import ping_cache
from app.config import settings
from app.db.session import dispose_engine, init_db
from app.engine.lifecycle import utcnow
from app.models import HealthResponse
from app.observability.logging import configure_logging
from app.observability.metrics import MetricsMiddleware, metrics_response
from app.observability.middleware import CorrelationIdMiddleware
from app.routers.payments import router as payments_router
from app.routers.policy import router as policy_router
from app.routers.routing import router as routing_router
from app.store import store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging(settings.LOG_LEVEL)
    await init_db()
    tasks = []
    if settings.WORKER_ENABLED:
        from app.engine.jobs import retrain_loop, worker_loop

        tasks.append(asyncio.create_task(worker_loop()))
        tasks.append(asyncio.create_task(retrain_loop()))
    yield
    for task in tasks:
        task.cancel()
    await dispose_engine()


app = FastAPI(
    title="CircuitBreaker",
    description="Find revenue slipping away. Understand why. Choose the highest-value safe intervention.",
    version="1.0.0",
    lifespan=lifespan,
)

if settings.cors_origin_list or settings.CORS_ORIGIN_REGEX:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.add_middleware(MetricsMiddleware)
app.add_middleware(CorrelationIdMiddleware)

app.include_router(payments_router, prefix="/api/v1/payments")
app.include_router(routing_router, prefix="/api/v1/routing")
app.include_router(policy_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v2/payments")
app.include_router(routing_router, prefix="/api/v2/routing")
app.include_router(policy_router, prefix="/api/v2")


async def _health_payload() -> HealthResponse:
    db_ok = await store.ping()
    rails_ok = False
    open_rails: set[str] = set()
    if db_ok:
        try:
            from app.engine.circuit_breaker import OPEN
            from app.engine.routing_engine import ROUTE_CATALOG

            open_rails = {row.rail for row in await store.list_circuits() if row.state == OPEN}
            rails_ok = any(route_id not in open_rails for route_id in ROUTE_CATALOG)
        except Exception:
            rails_ok = False
    queue_depth = 0
    try:
        from app.engine.jobs import queue_depth as job_depth

        queue_depth = await job_depth()
    except Exception:
        queue_depth = 0
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        engine="online" if db_ok else "degraded",
        demo_mode=settings.DEMO_MODE,
        recovery_window_seconds=settings.recovery_window_seconds,
        heartbeat=utcnow(),
        llm_provider="AI SIMULATION",
        db_connected=db_ok,
        rails_reachable=rails_ok,
        recovery_queue_depth=queue_depth,
        open_circuits=len(open_rails),
    )


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return await _health_payload()


async def _readiness_payload() -> JSONResponse:
    db_ok = await store.ping()
    redis_configured = bool((settings.REDIS_URL or "").strip())
    redis_ok = await ping_cache()
    ready_ok = db_ok and (redis_ok if redis_configured else True)
    payload = {
        "status": "ok" if ready_ok else "unavailable",
        "db": db_ok,
        "redis": redis_ok if redis_configured else "not_configured",
    }
    return JSONResponse(status_code=200 if ready_ok else 503, content=payload)


@app.get("/health/live")
@app.get("/api/v1/health/live")
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready")
@app.get("/api/v1/health/ready")
async def ready() -> JSONResponse:
    return await _readiness_payload()


@app.get("/metrics")
async def metrics():
    return metrics_response()


@app.exception_handler(Exception)
async def unhandled_error(_request: Request, exc: Exception):
    if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
        raise exc
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "SERVICE_TEMPORARILY_UNAVAILABLE",
                "message": "Recovery service is temporarily unavailable.",
                "retryable": True,
            },
            "detail": "Recovery service is temporarily unavailable.",
        },
    )

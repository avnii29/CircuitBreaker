from __future__ import annotations

import time
from typing import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_COUNT = Counter(
    "circuitbreaker_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "circuitbreaker_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
DB_LATENCY = Histogram(
    "circuitbreaker_db_query_duration_seconds",
    "Database call latency",
    ["operation"],
)
RECOVERY_SUCCESS = Counter(
    "circuitbreaker_recovery_success_total",
    "Successful recovery executions",
)
RECOVERY_FAILURE = Counter(
    "circuitbreaker_recovery_failure_total",
    "Failed or blocked recovery executions",
)
CIRCUIT_STATE = Gauge(
    "circuitbreaker_rail_circuit_state",
    "Circuit breaker state (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
    ["rail", "tenant_id"],
)
MANUAL_REVIEW_DEPTH = Gauge(
    "circuitbreaker_manual_review_depth",
    "Manual review queue depth",
    ["tenant_id"],
)
ERROR_RATE = Gauge(
    "circuitbreaker_recent_error_rate",
    "Rolling error rate for mutating payment endpoints",
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path in {"/metrics", "/health/live"}:
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = path
        REQUEST_COUNT.labels(request.method, route, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(request.method, route).observe(elapsed)
        return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

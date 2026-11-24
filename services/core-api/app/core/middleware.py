"""Security headers, request IDs, body-size limits, rate limiting and Prometheus metrics."""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram

from app.core.config import get_settings

REQ_LATENCY = Histogram("nsip_http_request_seconds", "HTTP latency", ["method", "route", "status"],
                        buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5))
REQ_TOTAL = Counter("nsip_http_requests_total", "HTTP requests", ["method", "route", "status"])
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'")

_hits: dict[str, deque[float]] = defaultdict(deque)


def _rate_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown")
    return f"{ip}|{hash(auth) if auth else ''}"


def install(app: FastAPI) -> None:
    s = get_settings()

    @app.middleware("http")
    async def _mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        length = int(request.headers.get("content-length") or 0)
        is_upload = request.url.path.endswith("/upload-eml") or "multipart" in request.headers.get("content-type", "")
        limit = s.max_attachment_bytes if is_upload else s.max_json_body_bytes
        if length > limit:
            return JSONResponse({"detail": {"code": "too_large", "message": "Request body too large."}}, 413)
        if request.url.path.startswith("/api/"):
            key, now = _rate_key(request), time.monotonic()
            q = _hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= s.rate_limit_per_minute:
                return JSONResponse({"detail": {"code": "rate_limited", "message": "Too many requests."}}, 429,
                                    headers={"Retry-After": "60"})
            q.append(now)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        REQ_LATENCY.labels(request.method, route_path, response.status_code).observe(elapsed)
        REQ_TOTAL.labels(request.method, route_path, response.status_code).inc()
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("Cache-Control", "no-store")
        structlog.contextvars.clear_contextvars()
        return response

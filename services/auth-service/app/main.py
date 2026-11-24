from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from app.api import oidc, routes
from app.core.config import get_settings

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
log = structlog.get_logger("auth-service")
REQUESTS = Counter("nsip_auth_requests_total", "Auth requests", ["path", "status"])

settings = get_settings()
app = FastAPI(title="NSIP Auth Service", version="1.0.0", docs_url="/auth/docs", openapi_url="/auth/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if int(request.headers.get("content-length") or 0) > 64 * 1024:
        return JSONResponse({"detail": {"code": "too_large", "message": "Request too large."}}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    REQUESTS.labels(request.url.path if request.url.path.count("/") < 4 else "other", response.status_code).inc()
    # Never log request bodies, passwords, codes or tokens.
    log.info("request", path=request.url.path, method=request.method, status=response.status_code)
    return response


app.include_router(routes.router)
app.include_router(oidc.router)


@app.get("/auth/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/metrics")
def metrics():
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

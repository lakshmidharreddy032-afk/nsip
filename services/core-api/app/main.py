from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1 import admin, insights, submissions
from app.core import middleware
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import setup_tracing

configure_logging()
settings = get_settings()
app = FastAPI(
    title="NSIP Core API",
    version="1.0.0",
    description="Northstar Submission Intelligence Platform: triage, clearance, extraction and human-only quoting.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "X-Request-ID"])
middleware.install(app)
app.include_router(submissions.router)
app.include_router(admin.router)
app.include_router(insights.router)
setup_tracing(app)


@app.get("/api/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/ready", tags=["ops"])
def ready() -> dict:
    from sqlalchemy import text

    from app.core.db import engine

    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

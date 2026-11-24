"""OpenTelemetry tracing, enabled when OTEL_EXPORTER_OTLP_ENDPOINT is set."""
from __future__ import annotations

import os

from fastapi import FastAPI


def setup_tracing(app: FastAPI) -> bool:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    try:  # pragma: no cover - exercised in deployed environments
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "nsip-core-api"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/health,/metrics")
        return True
    except ImportError:  # pragma: no cover
        return False

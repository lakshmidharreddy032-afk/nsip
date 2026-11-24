"""The single AI gateway client. No other module may call a model provider (enforced by tests).

Responsibilities: request IDs, PII masking of prompts, timeouts, retries with backoff, JSON-schema
constrained output with validation, token/cost accounting and masked request/response logging.
The AI layer has no tools and no write access to business state; it returns validated data only.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.guards.pii import mask, mask_obj
from app.ai.prompts import get_prompt
from app.ai.schemas import OUTPUT_MODELS
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("ai.gateway")

try:
    from prometheus_client import Counter

    AI_CALLS = Counter("nsip_ai_calls_total", "AI gateway calls", ["prompt_id", "status"])
except ValueError:  # pragma: no cover - re-import in tests
    AI_CALLS = None  # type: ignore[assignment]


class GatewayError(Exception):
    """Gateway unavailable or output invalid. Callers fall back to the manual queue."""


@dataclass
class GatewayResult:
    data: BaseModel
    request_id: str
    prompt_id: str
    prompt_version: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_inr: float


@dataclass
class CallRecord:
    request_id: str
    submission_id: uuid.UUID | None
    prompt_id: str
    prompt_version: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_inr: float
    status: str
    attempts: int
    masked_request: dict
    masked_response: dict


Recorder = Callable[[CallRecord], None]


def _inprocess_transport() -> httpx.BaseTransport:
    """Dev/test only: route gateway HTTP calls to the mock gateway logic without a network hop."""
    root = Path(__file__).resolve().parents[3] / "mock-gateway"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from mock_gateway.logic import handle  # type: ignore[import-not-found]

    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=handle(json.loads(request.content)))

    return httpx.MockTransport(_h)


class AIGateway:
    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.ai_gateway_url).rstrip("/")
        if transport is None and s.ai_gateway_mode == "inprocess":
            transport = _inprocess_transport()
        self._client = httpx.Client(base_url=self.base_url, timeout=s.ai_gateway_timeout_s, transport=transport,
                                    headers={"Authorization": f"Bearer {s.ai_gateway_api_key}"})
        self.retries = s.ai_gateway_retries
        self.cost_in = s.ai_cost_per_1k_input_inr
        self.cost_out = s.ai_cost_per_1k_output_inr

    def complete(self, prompt_id: str, *, trusted: dict | None = None, untrusted: dict | None = None,
                 submission_id: uuid.UUID | None = None, recorder: Recorder | None = None) -> GatewayResult:
        prompt = get_prompt(prompt_id)
        out_model = OUTPUT_MODELS[prompt_id]
        keep = set(prompt.pii_keep)
        masked_untrusted = {k: mask(v, keep) for k, v in (untrusted or {}).items()}
        user_msg = prompt.render(trusted, masked_untrusted)
        request_id = str(uuid.uuid4())
        body = {
            "model": prompt.model,
            "messages": [{"role": "system", "content": prompt.system}, {"role": "user", "content": user_msg}],
            "max_tokens": prompt.max_output_tokens,
            "temperature": 0,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": prompt_id, "strict": True,
                                                "schema": out_model.model_json_schema()}},
            "metadata": {"request_id": request_id, "prompt_id": prompt_id, "prompt_version": prompt.version},
        }
        start = time.perf_counter()
        attempts, last_err, resp_json = 0, "", {}
        status = "error"
        result: GatewayResult | None = None
        while attempts <= self.retries:
            attempts += 1
            try:
                r = self._client.post("/v1/chat/completions", json=body, headers={"X-Request-ID": request_id})
                if r.status_code >= 500 or r.status_code == 429:
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                resp_json = r.json()
                content = resp_json["choices"][0]["message"]["content"]
                data = out_model.model_validate(json.loads(content) if isinstance(content, str) else content)
                usage = resp_json.get("usage", {})
                tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
                latency = int((time.perf_counter() - start) * 1000)
                cost = round(tin / 1000 * self.cost_in + tout / 1000 * self.cost_out, 4)
                result = GatewayResult(data, request_id, prompt_id, prompt.version, resp_json.get("model", prompt.model),
                                       tin, tout, latency, cost)
                status = "ok"
                break
            except (ValidationError, json.JSONDecodeError, KeyError, TypeError) as e:
                status, last_err = "invalid_output", f"{type(e).__name__}"
                break  # do not retry schema violations; route to human
            except httpx.TimeoutException:
                status, last_err = "timeout", "timeout"
            except httpx.HTTPError as e:
                status, last_err = "error", type(e).__name__
            time.sleep(min(0.2 * (2 ** (attempts - 1)), 2.0))
        latency = int((time.perf_counter() - start) * 1000)
        record = CallRecord(
            request_id=request_id, submission_id=submission_id, prompt_id=prompt_id, prompt_version=prompt.version,
            model=result.model if result else prompt.model, tokens_in=result.tokens_in if result else 0,
            tokens_out=result.tokens_out if result else 0, latency_ms=latency,
            cost_inr=result.cost_inr if result else 0.0, status=status, attempts=attempts,
            masked_request=mask_obj({"messages": body["messages"], "metadata": body["metadata"]}),
            masked_response=mask_obj(resp_json.get("choices", [{}])[0].get("message", {}) if resp_json else {}),
        )
        if recorder:
            recorder(record)
        if AI_CALLS is not None:
            AI_CALLS.labels(prompt_id, status).inc()
        log.info("ai_call", request_id=request_id, prompt_id=prompt_id, status=status, attempts=attempts,
                 latency_ms=latency, tokens_in=record.tokens_in, tokens_out=record.tokens_out)
        if result is None:
            raise GatewayError(f"{prompt_id}: {status} {last_err}")
        return result


_gateway: AIGateway | None = None


def get_gateway() -> AIGateway:
    global _gateway
    if _gateway is None:
        _gateway = AIGateway()
    return _gateway


def set_gateway(g: AIGateway | None) -> None:
    global _gateway
    _gateway = g

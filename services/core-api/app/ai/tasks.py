"""Typed AI task wrappers. They return validated data only and never touch business state.

The only side effect is recording the call (tokens, latency, cost, masked request/response).
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway, CallRecord, get_gateway
from app.ai.schemas import (
    AppetiteSignalsOut,
    ClassifyEmailOut,
    DeclineLetterOut,
    KeyFactsOut,
    SovHeaderMapOut,
)
from app.models import AiCall


def db_recorder(db: Session):
    def _rec(r: CallRecord) -> None:
        db.add(AiCall(request_id=r.request_id, submission_id=r.submission_id, prompt_id=r.prompt_id,
                      prompt_version=r.prompt_version, model=r.model, tokens_in=r.tokens_in, tokens_out=r.tokens_out,
                      latency_ms=r.latency_ms, cost_inr=r.cost_inr, status=r.status, attempts=r.attempts,
                      masked_request=r.masked_request, masked_response=r.masked_response))
    return _rec


class AITasks:
    def __init__(self, db: Session, gateway: AIGateway | None = None) -> None:
        self.db = db
        self.gw = gateway or get_gateway()
        self.rec = db_recorder(db)

    def classify_email(self, email_text: str, attachment_names: list[str],
                       submission_id: uuid.UUID | None = None) -> tuple[ClassifyEmailOut, str]:
        r = self.gw.complete("classify_email", trusted={"attachments": ", ".join(attachment_names)[:500]},
                             untrusted={"email": email_text[:6000]}, submission_id=submission_id, recorder=self.rec)
        return r.data, r.prompt_version  # type: ignore[return-value]

    def key_facts(self, text: str, submission_id: uuid.UUID | None) -> tuple[KeyFactsOut, str, str]:
        r = self.gw.complete("extract_key_facts", untrusted={"document": text[:12000]},
                             submission_id=submission_id, recorder=self.rec)
        return r.data, r.prompt_version, r.model  # type: ignore[return-value]

    def map_sov_headers(self, headers: list[str], samples: list[list[str]],
                        submission_id: uuid.UUID | None) -> tuple[SovHeaderMapOut, str, str]:
        r = self.gw.complete("map_sov_headers", untrusted={"headers": "\n".join(headers),
                                                           "samples": "\n".join(" | ".join(s) for s in samples)},
                             submission_id=submission_id, recorder=self.rec)
        return r.data, r.prompt_version, r.model  # type: ignore[return-value]

    def appetite_signals(self, text: str, features: dict, submission_id: uuid.UUID | None) -> AppetiteSignalsOut:
        r = self.gw.complete("appetite_signals", trusted={"features": str(features)[:2000]},
                             untrusted={"document": text[:8000]}, submission_id=submission_id, recorder=self.rec)
        return r.data  # type: ignore[return-value]

    def decline_letter(self, broker: str, insured: str, reference: str, reasons: list[str],
                       submission_id: uuid.UUID | None) -> DeclineLetterOut:
        r = self.gw.complete("decline_letter", trusted={"broker": broker, "insured": insured, "reference": reference,
                                                        "reasons": "\n".join(f"- {x}" for x in reasons)},
                             submission_id=submission_id, recorder=self.rec)
        return r.data  # type: ignore[return-value]

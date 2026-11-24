"""Core data model (spec section 10). UUID keys, timestamps, soft delete and region scoping."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, JSONType


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class Entity:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SoftDelete:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------- identity projection + authority

class User(Entity, Base):
    """Projection of auth-service users (no credentials ever stored here)."""
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(32), default="west")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Role(Entity, Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(64), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)


class AuthorityLimit(Entity, Base):
    """Authority matrix entry. Maker-checker: pending -> approved by a different admin/CUO."""
    __tablename__ = "authority_limits"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    line: Mapped[str] = mapped_column(String(32))  # property | package
    max_sum_insured: Mapped[int] = mapped_column(BigInteger)
    max_premium: Mapped[int] = mapped_column(BigInteger)
    regions: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected|superseded
    version: Mapped[int] = mapped_column(Integer, default=1)
    maker_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    checker_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- intake

class Broker(Entity, Base):
    __tablename__ = "brokers"
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    email_domain: Mapped[str] = mapped_column(String(200), index=True)
    region: Mapped[str] = mapped_column(String(32), default="west")


class Email(Entity, SoftDelete, Base):
    __tablename__ = "emails"
    message_id: Mapped[str] = mapped_column(String(500), unique=True)
    mailbox: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="email")  # email | portal
    from_addr: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(1000), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    references: Mapped[list] = mapped_column(JSONType, default=list)
    raw_object_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    sanitized_text: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classification_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    injection_flags: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(32), default="received")
    broker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brokers.id"), nullable=True)
    attachments: Mapped[list[Attachment]] = relationship(back_populates="email", lazy="selectin",
                                                         order_by="Attachment.created_at")


class Attachment(Entity, SoftDelete, Base):
    __tablename__ = "attachments"
    email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("emails.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(String(500))
    document_store_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    av_status: Mapped[str] = mapped_column(String(16), default="pending")  # clean|infected|error
    macro_stripped: Mapped[bool] = mapped_column(Boolean, default=False)
    doc_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)  # sov|proposal|loss_history|other
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    layout_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[Email] = relationship(back_populates="attachments")


# ---------------------------------------------------------------- submissions

class Submission(Entity, SoftDelete, Base):
    __tablename__ = "submissions"
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    region: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="email")
    broker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brokers.id"), nullable=True, index=True)
    email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("emails.id"))
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")  # high|normal|low
    line: Mapped[str] = mapped_column(String(32), default="property")  # property | package
    insured_name: Mapped[str] = mapped_column(String(300), default="")
    insured_name_norm: Mapped[str] = mapped_column(String(300), default="", index=True)
    primary_pincode: Mapped[str | None] = mapped_column(String(6), nullable=True, index=True)
    primary_address_norm: Mapped[str] = mapped_column(String(500), default="")
    block_geohash: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    occupancy_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    declared_sum_insured: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_sum_insured: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    triage_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    referral_status: Mapped[str] = mapped_column(String(16), default="none")  # none|open|completed
    injection_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    sov_reconciled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_pending_update: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    keyed_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pipeline_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent: Mapped[dict] = mapped_column(JSONType, default=dict)  # DPDP purpose + basis
    __table_args__ = (Index("ix_sub_region_status", "region", "status"),)


class SubmissionVersion(Entity, Base):
    __tablename__ = "submission_versions"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    source_email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("emails.id"))
    snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    diff: Mapped[list] = mapped_column(JSONType, default=list)
    __table_args__ = (UniqueConstraint("submission_id", "version_no"),)


class RiskLocation(Entity, Base):
    __tablename__ = "risk_locations"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    loc_no: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(120), default="")
    pincode: Mapped[str] = mapped_column(String(6), default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    geohash: Mapped[str | None] = mapped_column(String(12), nullable=True)
    occupancy: Mapped[str] = mapped_column(String(300), default="")
    occupancy_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    construction: Mapped[str] = mapped_column(String(64), default="")
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protections: Mapped[list] = mapped_column(JSONType, default=list)
    cat_zone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cat_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sov_lines: Mapped[list[SovLine]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class SovLine(Entity, Base):
    __tablename__ = "sov_lines"
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_locations.id"), index=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    category: Mapped[str] = mapped_column(String(32))  # building|plant_machinery|stock|contents|other
    amount: Mapped[int] = mapped_column(BigInteger)


class LossHistory(Entity, Base):
    __tablename__ = "loss_history"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    cause: Mapped[str] = mapped_column(String(200))
    amount_paid: Mapped[int] = mapped_column(BigInteger, default=0)
    amount_outstanding: Mapped[int] = mapped_column(BigInteger, default=0)


class ExtractedField(Entity, Base):
    __tablename__ = "extracted_fields"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    path: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[object] = mapped_column(JSONType, nullable=True)
    source_value: Mapped[object] = mapped_column(JSONType, nullable=True)  # as extracted, before human edits
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_ref: Mapped[dict] = mapped_column(JSONType, default=dict)
    method: Mapped[str] = mapped_column(String(16), default="deterministic")  # deterministic|llm|ocr|human
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_errors: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(24), default="ok")  # ok|low_confidence|invalid|conflict
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    conflict_value: Mapped[object] = mapped_column(JSONType, nullable=True)
    __table_args__ = (UniqueConstraint("submission_id", "path"),)


class FieldEdit(Entity, Base):
    __tablename__ = "field_edits"
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extracted_fields.id"), index=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    path: Mapped[str] = mapped_column(String(200))
    before: Mapped[object] = mapped_column(JSONType, nullable=True)
    after: Mapped[object] = mapped_column(JSONType, nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="edit")  # edit|accept|conflict_resolve


class DuplicateLink(Entity, Base):
    __tablename__ = "duplicate_links"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSONType, default=dict)
    band: Mapped[str] = mapped_column(String(16))  # auto | review
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|linked|confirmed|rejected
    first_arrived_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    broker_of_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    bor_rule: Mapped[str] = mapped_column(String(64), default="first_received")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------- appetite + triage

class AppetiteRuleVersion(Entity, Base):
    __tablename__ = "appetite_rule_versions"
    version_no: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|retired
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_report: Mapped[dict] = mapped_column(JSONType, default=dict)
    rules: Mapped[list[AppetiteRule]] = relationship(lazy="selectin", order_by="AppetiteRule.priority")


class AppetiteRule(Entity, Base):
    __tablename__ = "appetite_rules"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appetite_rule_versions.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    condition: Mapped[dict] = mapped_column(JSONType)
    decline_reason: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TriageResult(Entity, Base):
    __tablename__ = "triage_results"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(32))
    fired_rules: Mapped[list] = mapped_column(JSONType, default=list)
    rule_version: Mapped[int] = mapped_column(Integer)
    features: Mapped[dict] = mapped_column(JSONType, default=dict)
    llm_signals: Mapped[dict] = mapped_column(JSONType, default=dict)
    rationale: Mapped[str] = mapped_column(Text, default="")
    decline_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str] = mapped_column(String(16), default="initial")  # initial | post_extraction
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    override_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Referral(Entity, Base):
    __tablename__ = "referrals"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="risk_engineering")  # risk_engineering|authority
    reason: Mapped[str] = mapped_column(Text)
    rule_ids: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|in_progress|completed
    region: Mapped[str] = mapped_column(String(32), default="west")
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conditions: Mapped[list] = mapped_column(JSONType, default=list)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------- rating, quoting, decisions

class RatingRun(Entity, Base):
    __tablename__ = "rating_runs"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))  # rating_api | excel_model
    source_version: Mapped[str] = mapped_column(String(64))
    filing_ref: Mapped[str] = mapped_column(String(64), default="")
    workbook_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inputs_hash: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict] = mapped_column(JSONType)
    outputs: Mapped[dict] = mapped_column(JSONType)
    premium: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(16), default="ok")
    run_by: Mapped[uuid.UUID] = mapped_column(Uuid)


class Quote(Entity, Base):
    __tablename__ = "quotes"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    rating_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rating_runs.id"))
    premium: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    issued_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    authority_snapshot: Mapped[dict] = mapped_column(JSONType)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict)
    policy_admin_ref: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="issued")  # issued|bound|lapsed
    fast_lane: Mapped[bool] = mapped_column(Boolean, default=False)
    audit_seal_hash: Mapped[str] = mapped_column(String(64))
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Decision(Entity, Base):
    __tablename__ = "decisions"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))  # quote|decline|refer|request_info
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text, default="")
    authority_check: Mapped[dict] = mapped_column(JSONType, default=dict)
    message_sent: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------- audit, AI, third-party, privacy, config

class AuditEvent(Base):
    """Append-only and hash-chained. UPDATE/DELETE are blocked by ORM guards and a DB trigger."""
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, unique=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # human | system | service
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AiCall(Entity, Base):
    __tablename__ = "ai_calls"
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    submission_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    prompt_id: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16))  # ok|error|invalid_output|timeout
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    masked_request: Mapped[dict] = mapped_column(JSONType, default=dict)
    masked_response: Mapped[dict] = mapped_column(JSONType, default=dict)


class ThirdPartyCall(Entity, Base):
    __tablename__ = "third_party_calls"
    provider: Mapped[str] = mapped_column(String(32), index=True)  # geocoding|cat_model|ocr
    submission_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    request_key: Mapped[str] = mapped_column(String(200))
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|budget_exceeded|error


class EnrichmentCache(Entity, Base):
    __tablename__ = "enrichment_cache"
    provider: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSONType)
    __table_args__ = (UniqueConstraint("provider", "key"),)


class PiiRegistry(Entity, Base):
    __tablename__ = "pii_registry"
    submission_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    email_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    pii_type: Mapped[str] = mapped_column(String(32))
    location: Mapped[str] = mapped_column(String(200))
    masked_value: Mapped[str] = mapped_column(String(200))
    value_hash: Mapped[str] = mapped_column(String(64), index=True)
    purpose: Mapped[str] = mapped_column(String(64), default="underwriting_submission")
    consent_basis: Mapped[str] = mapped_column(String(64), default="legitimate_use_s7")
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeatureFlag(Entity, Base):
    __tablename__ = "feature_flags"
    key: Mapped[str] = mapped_column(String(100), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    regions: Mapped[list] = mapped_column(JSONType, default=list)


class IntegrationConfig(Entity, Base):
    __tablename__ = "integration_configs"
    key: Mapped[str] = mapped_column(String(100), unique=True)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)


class SovMapping(Entity, Base):
    """Broker SOV layout library: deterministic header->field mappings, learned ones need approval."""
    __tablename__ = "sov_mappings"
    layout_id: Mapped[str] = mapped_column(String(64), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    broker_hint: Mapped[str] = mapped_column(String(200), default="")
    headers: Mapped[list] = mapped_column(JSONType, default=list)
    mapping: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="approved")  # proposed|approved|rejected
    source: Mapped[str] = mapped_column(String(16), default="seed")  # seed|llm|human
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

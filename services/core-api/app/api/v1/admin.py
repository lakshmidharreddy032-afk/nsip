from __future__ import annotations

import uuid
from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.mailbox import RawMessage
from app.adapters.registry import get_adapters
from app.core.db import get_db
from app.core.deps import require_roles
from app.core.security import Principal
from app.domain.analytics import service as analytics
from app.domain.appetite import service as appetite
from app.domain.audit import service as audit
from app.domain.authority import service as authority
from app.domain.privacy import service as privacy
from app.domain.submissions import ingestion, pipeline
from app.models import (
    AppetiteRuleVersion,
    AuthorityLimit,
    FeatureFlag,
    IntegrationConfig,
    Role,
    SovMapping,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
ADMIN = require_roles("admin")
ADMIN_OR_CUO = require_roles("admin", "cuo")


def _err(e: Exception, code: int = 409) -> NoReturn:
    raise HTTPException(code, detail={"code": type(e).__name__, "message": str(e)})


@router.get("/users")
def users(_: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> list:
    out = []
    for u in db.scalars(select(User).order_by(User.email)):
        roles = list(db.scalars(select(Role.name).join(UserRole, UserRole.role_id == Role.id)
                                .where(UserRole.user_id == u.id)))
        out.append({"id": str(u.id), "email": u.email, "full_name": u.full_name, "region": u.region, "roles": roles,
                    "authority": authority.user_claims(db, u.id)})
    return out


# ---------------------------------------------------------------- authority matrix (maker-checker)

def _limit_out(lim: AuthorityLimit, users: dict) -> dict:
    u = users.get(lim.user_id)
    return {"id": str(lim.id), "user_id": str(lim.user_id), "user": u.full_name if u else None,
            "email": u.email if u else None, "line": lim.line, "max_sum_insured": lim.max_sum_insured,
            "max_premium": lim.max_premium, "regions": lim.regions, "status": lim.status, "version": lim.version,
            "maker_id": str(lim.maker_id) if lim.maker_id else None,
            "checker_id": str(lim.checker_id) if lim.checker_id else None, "reason": lim.reason,
            "created_at": lim.created_at.isoformat()}


@router.get("/authority")
def list_authority(_: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> list:
    users = {u.id: u for u in db.scalars(select(User))}
    rows = db.scalars(select(AuthorityLimit).where(AuthorityLimit.status.in_(["approved", "pending"]))
                      .order_by(AuthorityLimit.created_at.desc()))
    return [_limit_out(r, users) for r in rows]


class AuthorityIn(BaseModel):
    user_id: uuid.UUID
    line: Literal["property", "package"]
    max_sum_insured: int = Field(gt=0)
    max_premium: int = Field(gt=0)
    regions: list[str] = Field(min_length=1)
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/authority", status_code=201)
def propose_authority(body: AuthorityIn, p: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> dict:
    if db.get(User, body.user_id) is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "User not found."})
    lim = authority.propose(db, p, user_id=body.user_id, line=body.line, max_sum_insured=body.max_sum_insured,
                            max_premium=body.max_premium, regions=body.regions, reason=body.reason)
    return _limit_out(lim, {u.id: u for u in db.scalars(select(User))})


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=1000)


@router.post("/authority/{limit_id}/decide")
def decide_authority(limit_id: uuid.UUID, body: DecideIn, p: Principal = Depends(ADMIN_OR_CUO),
                     db: Session = Depends(get_db)) -> dict:
    try:
        lim = authority.decide(db, p, limit_id, body.approve, body.note)
    except authority.MakerCheckerError as e:
        _err(e)
    return _limit_out(lim, {u.id: u for u in db.scalars(select(User))})


# ---------------------------------------------------------------- appetite rules

def _version_out(v: AppetiteRuleVersion) -> dict:
    return {"id": str(v.id), "version_no": v.version_no, "status": v.status, "notes": v.notes,
            "created_by": str(v.created_by) if v.created_by else None,
            "approved_by": str(v.approved_by) if v.approved_by else None,
            "approved_at": v.approved_at.isoformat() if v.approved_at else None, "test_report": v.test_report,
            "rules": [{"id": r.rule_id, "name": r.name, "outcome": r.outcome, "priority": r.priority,
                       "condition": r.condition, "decline_reason": r.decline_reason, "enabled": r.enabled}
                      for r in v.rules]}


@router.get("/appetite/versions")
def appetite_versions(_: Principal = Depends(require_roles("admin", "cuo", "underwriter", "senior_underwriter")),
                      db: Session = Depends(get_db)) -> list:
    return [_version_out(v) for v in db.scalars(select(AppetiteRuleVersion)
                                                .order_by(AppetiteRuleVersion.version_no.desc()))]


class RuleIn(BaseModel):
    id: str = Field(pattern=r"^APP-\d{3}$")
    name: str = Field(min_length=3, max_length=200)
    outcome: Literal["out_of_appetite", "refer_risk_engineering", "needs_info"]
    priority: int = 100
    condition: dict
    decline_reason: str = ""
    enabled: bool = True


class DraftIn(BaseModel):
    rules: list[RuleIn] = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=2000)


@router.post("/appetite/drafts", status_code=201)
def create_draft(body: DraftIn, p: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> dict:
    try:
        v = appetite.create_draft(db, p, [r.model_dump() for r in body.rules], body.notes)
    except appetite.RulesetError as e:
        _err(e, 422)
    return _version_out(v)


@router.post("/appetite/versions/{version_id}/test")
def test_draft(version_id: uuid.UUID, _: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> dict:
    try:
        return appetite.test_draft(db, version_id)
    except appetite.RulesetError as e:
        _err(e, 404)


@router.post("/appetite/versions/{version_id}/approve")
def approve_draft(version_id: uuid.UUID, p: Principal = Depends(require_roles("cuo")),
                  db: Session = Depends(get_db)) -> dict:
    try:
        return _version_out(appetite.approve(db, p, version_id))
    except appetite.RulesetError as e:
        _err(e)


# ---------------------------------------------------------------- SOV mapping library

@router.get("/mappings")
def mappings(_: Principal = Depends(require_roles("admin", "cuo", "data_entry", "underwriter", "senior_underwriter")),
             db: Session = Depends(get_db)) -> list:
    return [{"id": str(m.id), "layout_id": m.layout_id, "fingerprint": m.fingerprint, "broker_hint": m.broker_hint,
             "headers": m.headers, "mapping": m.mapping, "status": m.status, "source": m.source,
             "times_used": m.times_used} for m in db.scalars(select(SovMapping).order_by(SovMapping.status,
                                                                                        SovMapping.layout_id))]


class MappingDecision(BaseModel):
    approve: bool
    mapping: dict | None = None


@router.post("/mappings/{mapping_id}/decide")
def decide_mapping(mapping_id: uuid.UUID, body: MappingDecision, p: Principal = Depends(ADMIN),
                   db: Session = Depends(get_db)) -> dict:
    m = db.get(SovMapping, mapping_id)
    if m is None or m.status != "proposed":
        raise HTTPException(409, detail={"code": "invalid", "message": "Mapping is not awaiting approval."})
    if body.mapping:
        m.mapping, m.source = body.mapping, "human"
    m.status = "approved" if body.approve else "rejected"
    m.approved_by = p.user_id
    audit.record(db, action=f"mapping.{m.status}", entity_type="sov_mapping", entity_id=m.id, actor_id=p.user_id,
                 actor_type="human", data={"layout_id": m.layout_id, "edited": bool(body.mapping)})
    db.commit()
    return {"id": str(m.id), "status": m.status}


# ---------------------------------------------------------------- integrations, flags, budgets, cost

@router.get("/integrations")
def integrations(_: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> dict:
    return {c.key: c.config for c in db.scalars(select(IntegrationConfig))}


class ConfigIn(BaseModel):
    config: dict


SECRET_HINTS = ("secret", "password", "token", "api_key", "apikey")


@router.put("/integrations/{key}")
def put_integration(key: str, body: ConfigIn, p: Principal = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    flat = str(body.config).lower()
    if any(h in flat for h in SECRET_HINTS):
        raise HTTPException(422, detail={"code": "secret_in_config",
                                         "message": "Secrets must be supplied via the secrets manager, not config."})
    row = db.scalar(select(IntegrationConfig).where(IntegrationConfig.key == key))
    if row is None:
        row = IntegrationConfig(key=key, config={})
        db.add(row)
    before = row.config
    row.config = body.config
    audit.record(db, action="config.updated", entity_type="integration_config", entity_id=key, actor_id=p.user_id,
                 actor_type="human", data={"before": before, "after": body.config})
    db.commit()
    return {key: row.config}


@router.get("/flags")
def flags(_: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> list:
    return [{"key": f.key, "enabled": f.enabled, "description": f.description, "regions": f.regions}
            for f in db.scalars(select(FeatureFlag).order_by(FeatureFlag.key))]


class FlagIn(BaseModel):
    enabled: bool


@router.put("/flags/{key}")
def set_flag(key: str, body: FlagIn, p: Principal = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    f = db.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
    if f is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Flag not found."})
    f.enabled = body.enabled
    audit.record(db, action="flag.updated", entity_type="feature_flag", entity_id=key, actor_id=p.user_id,
                 actor_type="human", data={"enabled": body.enabled})
    db.commit()
    return {"key": key, "enabled": f.enabled}


@router.get("/cost")
def cost(_: Principal = Depends(ADMIN_OR_CUO), db: Session = Depends(get_db)) -> dict:
    return analytics.cost_projection(db)


# ---------------------------------------------------------------- ingestion + privacy jobs

@router.post("/ingestion/poll")
def poll(p: Principal = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    stats = pipeline.poll_mailboxes(db)
    audit.record(db, action="ingestion.poll", entity_type="mailbox", entity_id="all", actor_id=p.user_id,
                 actor_type="human", data=stats)
    db.commit()
    return stats


@router.post("/ingestion/upload-eml")
async def upload_eml(region: str = "west", file: UploadFile = File(...), p: Principal = Depends(ADMIN),
                     db: Session = Depends(get_db)) -> dict:
    """Manual intake of a forwarded .eml (e.g. mailbox outage runbook). Same pipeline as polling."""
    data = await file.read()
    em = ingestion.ingest(db, get_adapters(), RawMessage(ref="upload", region=region,
                                                         mailbox="manual-upload", raw=data))
    db.commit()
    if em is None:
        return {"status": "duplicate_message"}
    sub = pipeline.process_email(db, em.id)
    return {"status": "processed", "email_id": str(em.id), "submission_id": str(sub.id) if sub else None,
            "classification": em.classification}


@router.post("/privacy/retention")
def retention(p: Principal = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    return privacy.run_retention(db, get_adapters(), p.user_id)


class ErasureIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/privacy/erasure")
def erasure(body: ErasureIn, p: Principal = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    return privacy.erase_principal(db, body.identifier, p.user_id, body.reason)

"""Underwriting authority matrix: checks (line, sum insured, premium band, region) and maker-checker.

The approved database entry is the source of truth. The token carries the same entries as claims;
if the claim is missing or stale versus the database the action is refused (re-login required).
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import UNDERWRITING_ROLES, Principal
from app.domain.audit import service as audit
from app.models import AuthorityLimit, utcnow

log = get_logger("authority")


@dataclass
class AuthorityCheck:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    limit: dict | None = None
    requires_referral_to: str | None = None
    line: str = ""
    sum_insured: int = 0
    premium: str = "0"
    region: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def limit_claim(lim: AuthorityLimit) -> dict:
    return {"limit_id": str(lim.id), "version": lim.version, "line": lim.line,
            "max_sum_insured": lim.max_sum_insured, "max_premium": lim.max_premium, "regions": list(lim.regions)}


def approved_limit(db: Session, user_id: uuid.UUID, line: str) -> AuthorityLimit | None:
    return db.scalar(select(AuthorityLimit).where(AuthorityLimit.user_id == user_id, AuthorityLimit.line == line,
                                                  AuthorityLimit.status == "approved"))


def check(db: Session, p: Principal, *, line: str, sum_insured: int, premium: Decimal | int,
          region: str) -> AuthorityCheck:
    res = AuthorityCheck(allowed=False, line=line, sum_insured=int(sum_insured), premium=str(premium), region=region)
    if not p.has(*UNDERWRITING_ROLES):
        res.reasons.append("Only underwriters can quote.")
        return res
    if not p.mfa:
        res.reasons.append("Multi-factor authentication is required for quote actions.")
        return res
    lim = approved_limit(db, p.user_id, line)
    if lim is None:
        res.reasons.append(f"No approved authority for line '{line}'.")
        res.requires_referral_to = "senior_underwriter"
        return res
    res.limit = limit_claim(lim)
    claim = next((c for c in p.authority if c.get("limit_id") == str(lim.id)), None)
    if claim is None or int(claim.get("version", -1)) != lim.version:
        res.reasons.append("Authority in your session is out of date. Sign in again to refresh it.")
        return res
    regions = set(lim.regions)
    if "all" not in regions and region not in regions:
        res.reasons.append(f"Region '{region}' is outside your authority.")
    if sum_insured > lim.max_sum_insured:
        res.reasons.append("Sum insured exceeds your authority.")
    if Decimal(premium) > Decimal(lim.max_premium):
        res.reasons.append("Premium exceeds your authority band.")
    res.allowed = not res.reasons
    if not res.allowed:
        res.requires_referral_to = "senior_underwriter" if "senior_underwriter" not in p.roles else "cuo"
    return res


# ------------------------------------------------------------------ maker-checker

class MakerCheckerError(Exception):
    pass


def propose(db: Session, maker: Principal, *, user_id: uuid.UUID, line: str, max_sum_insured: int,
            max_premium: int, regions: list[str], reason: str) -> AuthorityLimit:
    current = approved_limit(db, user_id, line)
    lim = AuthorityLimit(user_id=user_id, line=line, max_sum_insured=max_sum_insured, max_premium=max_premium,
                         regions=regions, status="pending", version=(current.version + 1) if current else 1,
                         maker_id=maker.user_id, reason=reason)
    db.add(lim)
    db.flush()
    audit.record(db, action="authority.proposed", entity_type="authority_limit", entity_id=lim.id,
                 actor_id=maker.user_id, actor_type="human",
                 data={"user_id": str(user_id), "line": line, "max_sum_insured": max_sum_insured,
                       "max_premium": max_premium, "regions": regions, "reason": reason})
    db.commit()
    return lim


def decide(db: Session, checker: Principal, limit_id: uuid.UUID, approve: bool, note: str = "") -> AuthorityLimit:
    lim = db.get(AuthorityLimit, limit_id)
    if lim is None or lim.status != "pending":
        raise MakerCheckerError("No pending change found.")
    if lim.maker_id == checker.user_id:
        raise MakerCheckerError("Maker and checker must be different people.")
    if approve:
        prev = approved_limit(db, lim.user_id, lim.line)
        if prev:
            prev.status = "superseded"
        lim.status = "approved"
        lim.approved_at = utcnow()
    else:
        lim.status = "rejected"
    lim.checker_id = checker.user_id
    audit.record(db, action="authority.approved" if approve else "authority.rejected",
                 entity_type="authority_limit", entity_id=lim.id, actor_id=checker.user_id, actor_type="human",
                 data={"user_id": str(lim.user_id), "line": lim.line, "version": lim.version, "note": note})
    db.commit()
    if approve:
        push_to_auth_service(db, lim.user_id)
    return lim


def user_claims(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(AuthorityLimit).where(AuthorityLimit.user_id == user_id,
                                                   AuthorityLimit.status == "approved"))
    return [limit_claim(r) for r in rows]


def push_to_auth_service(db: Session, user_id: uuid.UUID) -> bool:
    s = get_settings()
    try:
        r = httpx.put(f"{s.auth_service_url}/auth/internal/users/{user_id}/authority",
                      json={"authority": user_claims(db, user_id)},
                      headers={"X-Internal-Token": s.internal_service_token}, timeout=5)
        r.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("authority_push_failed", user_id=str(user_id), error=type(e).__name__)
        return False

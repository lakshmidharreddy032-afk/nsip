"""Duplicate clearance: same risk arriving via different brokers (or re-sent), before extraction.

Blocking on geohash of the free pincode centroid (plus exact pincode), fuzzy name and address
matching (rapidfuzz), occupancy and sum-insured similarity combined into a scored match.
>= auto threshold: auto-link and flag. Review band: a human confirms. Broker-of-record rule is config.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.audit import service as audit
from app.models import DuplicateLink, IntegrationConfig, Submission, aware, utcnow

DEFAULTS = {"auto_threshold": 0.90, "review_threshold": 0.75, "lookback_days": 180, "bor_rule": "first_received",
            "weights": {"name": 0.5, "address": 0.25, "occupancy": 0.1, "sum_insured": 0.15}}


def config(db: Session) -> dict:
    row = db.scalar(select(IntegrationConfig).where(IntegrationConfig.key == "clearance"))
    return {**DEFAULTS, **(row.config if row else {})}


@dataclass
class MatchScore:
    score: float
    components: dict


def score_pair(a: Submission, b: Submission, weights: dict) -> MatchScore:
    name = fuzz.token_set_ratio(a.insured_name_norm, b.insured_name_norm) / 100 if a.insured_name_norm and b.insured_name_norm else 0.0
    addr = fuzz.token_set_ratio(a.primary_address_norm, b.primary_address_norm) / 100 if a.primary_address_norm and b.primary_address_norm else 0.5
    if a.occupancy_code and b.occupancy_code:
        occ = 1.0 if a.occupancy_code == b.occupancy_code else 0.0
    else:
        occ = 0.5
    if a.declared_sum_insured and b.declared_sum_insured:
        hi = max(a.declared_sum_insured, b.declared_sum_insured)
        si = 1 - min(abs(a.declared_sum_insured - b.declared_sum_insured) / hi, 1.0)
    else:
        si = 0.5
    comps = {"name": round(name, 3), "address": round(addr, 3), "occupancy": occ, "sum_insured": round(si, 3)}
    total = sum(weights[k] * comps[k] for k in weights)
    # guard: a weak name match cannot be a duplicate no matter how similar the rest is
    if name < 0.7:
        total = min(total, 0.6)
    return MatchScore(round(total, 4), comps)


def candidates(db: Session, sub: Submission, lookback_days: int) -> list[Submission]:
    since = aware(sub.received_at) - timedelta(days=lookback_days)  # type: ignore[operator]
    block = [Submission.primary_pincode == sub.primary_pincode] if sub.primary_pincode else []
    if sub.block_geohash:
        block.append(Submission.block_geohash == sub.block_geohash)
    if not block:
        return []
    q = select(Submission).where(or_(*block), Submission.id != sub.id, Submission.deleted_at.is_(None),
                                 Submission.duplicate_of_id.is_(None), Submission.received_at >= since,
                                 Submission.received_at <= sub.received_at)
    return list(db.scalars(q))


def run(db: Session, sub: Submission) -> DuplicateLink | None:
    cfg = config(db)
    best: tuple[MatchScore, Submission] | None = None
    for cand in candidates(db, sub, cfg["lookback_days"]):
        ms = score_pair(sub, cand, cfg["weights"])
        if best is None or ms.score > best[0].score:
            best = (ms, cand)
    if best is None or best[0].score < cfg["review_threshold"]:
        return None
    ms, cand = best
    band = "auto" if ms.score >= cfg["auto_threshold"] else "review"
    first = cand if aware(cand.received_at) <= aware(sub.received_at) else sub  # type: ignore[operator]
    bor = first.broker_id if cfg["bor_rule"] == "first_received" else None
    link = DuplicateLink(submission_id=sub.id, candidate_id=cand.id, score=ms.score, components=ms.components,
                         band=band, status="linked" if band == "auto" else "pending", first_arrived_id=first.id,
                         broker_of_record_id=bor, bor_rule=cfg["bor_rule"])
    db.add(link)
    if band == "auto":
        sub.duplicate_of_id = cand.id
        sub.status = "duplicate"
    else:
        sub.status = "clearance_review"
    db.flush()
    audit.record(db, action=f"clearance.{band}", entity_type="submission", entity_id=sub.id, region=sub.region,
                 data={"candidate": str(cand.id), "score": ms.score, "components": ms.components,
                       "broker_of_record": str(bor) if bor else None, "rule": cfg["bor_rule"]})
    return link


class ClearanceError(Exception):
    pass


def resolve(db: Session, link_id, user_id, confirm: bool, reason: str = "") -> DuplicateLink:
    link = db.get(DuplicateLink, link_id)
    if link is None or link.status not in ("pending", "linked"):
        raise ClearanceError("Duplicate link is not open for resolution.")
    sub = db.get(Submission, link.submission_id)
    assert sub is not None
    link.resolved_by, link.resolved_at = user_id, utcnow()
    if confirm:
        link.status = "confirmed"
        sub.duplicate_of_id = link.candidate_id
        sub.status = "duplicate"
    else:
        link.status = "rejected"
        sub.duplicate_of_id = None
        sub.status = "received"  # resumes the pipeline
    audit.record(db, action="clearance.confirmed" if confirm else "clearance.rejected", entity_type="submission",
                 entity_id=sub.id, actor_id=user_id, actor_type="human", region=sub.region,
                 data={"link": str(link.id), "candidate": str(link.candidate_id), "reason": reason})
    return link

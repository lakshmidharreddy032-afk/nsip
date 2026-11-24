"""Dashboards. Outcome hierarchy: loss ratio is a guardrail that cannot worsen; time to quote is the
primary operational metric; win rate is the lagging business metric (tracked, not promised).
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.registry import Adapters
from app.core.config import get_settings
from app.core.security import Principal
from app.domain.submissions.enrichment import budgets
from app.models import (
    AiCall,
    Broker,
    Decision,
    Email,
    ExtractedField,
    FieldEdit,
    Quote,
    Submission,
    ThirdPartyCall,
    TriageResult,
    aware,
    utcnow,
)

BASELINES = {"data_entry_minutes": 70, "median_time_to_quote_days": 6, "win_rate": 0.11, "loss_ratio": 0.68,
             "out_of_appetite_share": 0.45, "duplicate_share": 0.18, "re_referral_share": 0.12}
TARGETS = {"review_minutes": 15, "time_to_quote_hours": 48, "decline_minutes": 5}
HIERARCHY = [
    {"metric": "Property loss ratio", "role": "guardrail", "rule": "must not worsen vs 68% baseline"},
    {"metric": "Median time to quote", "role": "primary", "rule": "< 48 hours for in-appetite, non-referred"},
    {"metric": "Win rate on quoted business", "role": "lagging", "rule": "tracked, not promised (baseline 11%)"},
]


def _scope(q, p: Principal):
    return q if p.all_regions else q.where(Submission.region == p.region)


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 2) if xs else None


def _subs(db: Session, p: Principal, days: int) -> list[Submission]:
    since = utcnow() - timedelta(days=days)
    return list(db.scalars(_scope(select(Submission).where(Submission.received_at >= since,
                                                          Submission.deleted_at.is_(None)), p)))


def cost_breakdown(db: Session, sub_ids: list | None = None) -> dict:
    def total(model, provider=None):
        q = select(func.coalesce(func.sum(model.cost_inr), 0.0))
        if provider:
            q = q.where(model.provider == provider)
        if sub_ids is not None:
            q = q.where(model.submission_id.in_(sub_ids))
        return float(db.scalar(q) or 0.0)

    n = len(sub_ids) if sub_ids is not None else (db.scalar(select(func.count()).select_from(Submission)) or 0)
    compute = n * get_settings().compute_cost_per_submission_inr
    parts = {"llm_tokens": total(AiCall), "ocr": total(ThirdPartyCall, "ocr"),
             "geocoding": total(ThirdPartyCall, "geocoding"), "cat_model": total(ThirdPartyCall, "cat_model"),
             "compute": compute}
    tot = sum(parts.values())
    return {"total_inr": round(tot, 2), "per_submission_inr": round(tot / n, 2) if n else 0.0,
            "breakdown_inr": {k: round(v, 2) for k, v in parts.items()},
            "per_submission_breakdown_inr": {k: round(v / n, 3) if n else 0 for k, v in parts.items()},
            "submissions": n}


def ops(db: Session, p: Principal, days: int = 30) -> dict:
    subs = _subs(db, p, days)
    now = utcnow()
    by_day: Counter = Counter(aware(s.received_at).date().isoformat() for s in subs)  # type: ignore[union-attr]
    outcomes: Counter = Counter(s.triage_outcome or "pending" for s in subs)
    statuses: Counter = Counter(s.status for s in subs)
    dup = sum(1 for s in subs if s.duplicate_of_id)
    review = [s.keyed_seconds / 60 for s in subs if s.keyed_seconds is not None]
    open_breach = [s for s in subs if s.status not in ("quoted", "declined", "duplicate", "closed")
                   and aware(s.sla_due_at) < now]  # type: ignore[operator]
    closed_breach = [s for s in subs if s.decided_at and aware(s.decided_at) > aware(s.sla_due_at)]  # type: ignore[operator]
    since = now - timedelta(days=days)
    emails = Counter(db.scalars(select(Email.classification).where(Email.received_at >= since)))
    channels: Counter = Counter(s.channel for s in subs)
    return {
        "window_days": days, "submissions": len(subs),
        "volume_by_day": [{"date": d, "count": c} for d, c in sorted(by_day.items())],
        "triage_outcomes": dict(outcomes), "status_counts": dict(statuses),
        "duplicate_rate": round(dup / len(subs), 4) if subs else 0.0,
        "median_review_minutes": _median(review), "baseline_keying_minutes": BASELINES["data_entry_minutes"],
        "target_review_minutes": TARGETS["review_minutes"],
        "sla_breaches_open": len(open_breach), "sla_breaches_closed": len(closed_breach),
        "email_classification": {k or "unclassified": v for k, v in emails.items()},
        "channels": dict(channels), "cost": cost_breakdown(db, [s.id for s in subs]),
        "manual_queue": statuses.get("manual_review", 0),
    }


def _family(path: str) -> str:
    return re.sub(r"\[\d+\]", "[*]", path)


def override_rates(db: Session, sub_ids: list) -> list[dict]:
    if not sub_ids:
        return []
    total: Counter = Counter()
    for path, method in db.execute(select(ExtractedField.path, ExtractedField.method)
                                   .where(ExtractedField.submission_id.in_(sub_ids))):
        if method != "human":
            total[_family(path)] += 1
    edits: Counter = Counter()
    seen = set()
    for fid, path in db.execute(select(FieldEdit.field_id, FieldEdit.path).where(
            FieldEdit.submission_id.in_(sub_ids), FieldEdit.kind == "edit")):
        if fid not in seen:
            seen.add(fid)
            edits[_family(path)] += 1
    rows = [{"field": f, "extracted": n, "overridden": edits.get(f, 0), "override_rate": round(edits.get(f, 0) / n, 4)}
            for f, n in total.items()]
    return sorted(rows, key=lambda r: (-r["override_rate"], r["field"]))


def underwriting(db: Session, p: Principal, days: int = 90) -> dict:
    subs = _subs(db, p, days)
    ids = [s.id for s in subs]
    quoted = [s for s in subs if s.status == "quoted" and s.decided_at]
    declined = [s for s in subs if s.status == "declined" and s.decided_at]
    ttq = [(aware(s.decided_at) - aware(s.received_at)).total_seconds() / 3600 for s in quoted]  # type: ignore[operator]
    dec = [(aware(s.decided_at) - aware(s.received_at)).total_seconds() / 3600 for s in declined]  # type: ignore[operator]
    quotes = list(db.scalars(select(Quote).where(Quote.submission_id.in_(ids)))) if ids else []
    bound = sum(1 for q in quotes if q.status == "bound")
    decisions = list(db.scalars(select(Decision).where(Decision.submission_id.in_(ids)))) if ids else []
    blocked = [d for d in decisions if d.action == "refer" and d.reason.startswith("authority")]
    usage: dict = defaultdict(lambda: {"quotes": 0, "premium": 0.0, "blocked": 0})
    for q in quotes:
        u = usage[str(q.issued_by)]
        u["quotes"] += 1
        u["premium"] += float(q.premium)
    for d in blocked:
        usage[str(d.user_id)]["blocked"] += 1
    within_48 = sum(1 for h in ttq if h <= 48)
    return {
        "window_days": days, "quotes": len(quotes), "bound": bound,
        "quote_to_bind": round(bound / len(quotes), 4) if quotes else 0.0,
        "median_time_to_quote_hours": _median(ttq), "pct_quoted_within_48h": round(within_48 / len(ttq), 4) if ttq else None,
        "median_decline_turnaround_hours": _median(dec), "baseline_time_to_quote_days": BASELINES["median_time_to_quote_days"],
        "fast_lane_quotes": sum(1 for q in quotes if q.fast_lane),
        "authority_usage": [{"user_id": k, **v} for k, v in usage.items()],
        "authority_blocks": len(blocked), "ai_override_rates": override_rates(db, ids),
    }


def cuo(db: Session, adapters: Adapters, p: Principal, days: int = 90) -> dict:
    snap = adapters.claims.monthly_snapshot()  # type: ignore[attr-defined]
    cohorts: dict = defaultdict(lambda: {"earned": 0, "incurred": 0})
    monthly = []
    for r in snap["rows"]:
        cohorts[r["cohort"]]["earned"] += r["earned_premium"]
        cohorts[r["cohort"]]["incurred"] += r["incurred"]
        monthly.append({"month": r["month"], "cohort": r["cohort"],
                        "loss_ratio": round(r["incurred"] / r["earned_premium"], 4)})
    lr = {k: round(v["incurred"] / v["earned"], 4) for k, v in cohorts.items()}
    guardrail_ok = lr.get("ai_assisted", 0) <= BASELINES["loss_ratio"] + 0.005
    tr = list(db.scalars(select(TriageResult).where(TriageResult.is_current.is_(True))))
    hits: Counter = Counter(f["rule_id"] for t in tr for f in t.fired_rules)
    now = utcnow()
    recent = [t for t in tr if aware(t.created_at) >= now - timedelta(days=7)]  # type: ignore[operator]
    prior = [t for t in tr if now - timedelta(days=37) <= aware(t.created_at) < now - timedelta(days=7)]  # type: ignore[operator]

    def share(ts, outcome):
        return sum(1 for t in ts if t.outcome == outcome) / len(ts) if ts else None

    alerts = []
    r_out, p_out = share(recent, "out_of_appetite"), share(prior, "out_of_appetite")
    if r_out is not None and p_out is not None and abs(r_out - p_out) > 0.1:
        alerts.append({"type": "appetite_mix_drift", "message": f"Out-of-appetite share moved {p_out:.0%} -> {r_out:.0%}"})
    disagree = [t for t in tr if t.llm_signals and t.llm_signals.get("agrees_with_rules") is False]
    if tr and len(disagree) / len(tr) > 0.1:
        alerts.append({"type": "assistant_disagreement",
                       "message": f"AI advisory disagreed with rules on {len(disagree) / len(tr):.0%} of triages"})
    if not guardrail_ok:
        alerts.append({"type": "loss_ratio_guardrail", "message": "AI-assisted cohort loss ratio above baseline",
                       "severity": "critical"})
    conf = db.execute(select(func.avg(ExtractedField.confidence)).where(ExtractedField.method != "human")).scalar()
    subs = _subs(db, p, days)
    ovr = override_rates(db, [s.id for s in subs])
    high_override = [r for r in ovr if r["extracted"] >= 20 and r["override_rate"] > 0.15]
    for r in high_override[:5]:
        alerts.append({"type": "field_override_drift", "message": f"{r['field']} override rate {r['override_rate']:.0%}"})
    return {
        "outcome_hierarchy": HIERARCHY, "loss_ratio_by_cohort": lr, "loss_ratio_baseline": BASELINES["loss_ratio"],
        "loss_ratio_monthly": monthly, "guardrail_ok": guardrail_ok, "claims_snapshot_date": snap["snapshot_date"],
        "appetite_rule_hits": [{"rule_id": k, "hits": v, "rate": round(v / len(tr), 4)} for k, v in hits.most_common()],
        "triaged": len(tr), "drift_alerts": alerts, "avg_extraction_confidence": round(float(conf or 0), 4),
        "assistant_disagreement_rate": round(len(disagree) / len(tr), 4) if tr else 0.0,
    }


def distribution(db: Session, p: Principal, broker_id=None, days: int = 90) -> dict:
    brokers = list(db.scalars(select(Broker).order_by(Broker.name)))
    out: dict[str, object] = {"brokers": [{"id": str(b.id), "name": b.name, "code": b.code} for b in brokers], "broker": None}
    if broker_id is None:
        return out
    b = db.get(Broker, broker_id)
    if b is None:
        return out
    since = utcnow() - timedelta(days=days)
    subs = list(db.scalars(_scope(select(Submission).where(Submission.broker_id == b.id,
                                                           Submission.received_at >= since), p)))
    quoted = [s for s in subs if s.status == "quoted"]
    ids = [s.id for s in quoted]
    bound = db.scalar(select(func.count()).select_from(Quote).where(Quote.submission_id.in_(ids),
                                                                     Quote.status == "bound")) if ids else 0
    tat = [(aware(s.decided_at) - aware(s.received_at)).total_seconds() / 3600  # type: ignore[operator]
           for s in subs if s.decided_at]
    out["broker"] = {
        "id": str(b.id), "name": b.name, "code": b.code, "submissions": len(subs), "quoted": len(quoted),
        "declined": sum(1 for s in subs if s.status == "declined"),
        "duplicates": sum(1 for s in subs if s.duplicate_of_id),
        "out_of_appetite_share": round(sum(1 for s in subs if s.triage_outcome == "out_of_appetite") / len(subs), 4) if subs else 0,
        "median_turnaround_hours": _median(tat), "win_rate": round((bound or 0) / len(quoted), 4) if quoted else None,
    }
    return out


def cost_projection(db: Session) -> dict:
    since = utcnow() - timedelta(days=30)
    ids = list(db.scalars(select(Submission.id).where(Submission.received_at >= since)))
    c = cost_breakdown(db, ids)
    b = budgets(db)
    monthly_volume = 9000
    projected = round(c["per_submission_inr"] * monthly_volume, 2)
    llm_proj = round(c["per_submission_breakdown_inr"]["llm_tokens"] * monthly_volume, 2) if ids else 0.0
    alerts = []
    if projected > b["monthly_budget_inr"]:
        alerts.append(f"Projected monthly cost Rs {projected:,.0f} exceeds budget Rs {b['monthly_budget_inr']:,.0f}")
    if llm_proj > b.get("llm_monthly_budget_inr", 1e12):
        alerts.append(f"Projected LLM cost Rs {llm_proj:,.0f} exceeds LLM budget")
    if projected > 0.8 * b["monthly_budget_inr"] and not alerts:
        alerts.append("Projected cost above 80% of monthly budget")
    return {"basis": "last 30 days unit cost x 9,000 submissions per month", "unit_cost": c,
            "projected_monthly_inr": projected, "projected_llm_monthly_inr": llm_proj, "budgets": b, "alerts": alerts}

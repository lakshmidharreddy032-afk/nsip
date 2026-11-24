"""Triage orchestration and versioned ruleset lifecycle (draft -> test on history -> CUO approval)."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import GatewayError
from app.ai.tasks import AITasks
from app.core.config import get_settings
from app.core.security import Principal
from app.domain.appetite.engine import Rule, RuleError, evaluate, validate_rule
from app.domain.audit import service as audit
from app.models import (
    AppetiteRule,
    AppetiteRuleVersion,
    Broker,
    Referral,
    Submission,
    TriageResult,
    utcnow,
)

DEFAULT_RULES = Path(__file__).parent / "default_rules.yaml"


class RulesetError(Exception):
    pass


def _to_rule(r: AppetiteRule) -> Rule:
    return Rule(id=r.rule_id, name=r.name, outcome=r.outcome, condition=r.condition, priority=r.priority,
                decline_reason=r.decline_reason, enabled=r.enabled)


def ensure_default_ruleset(db: Session, approved_by=None) -> AppetiteRuleVersion:
    v = active_version(db)
    if v:
        return v
    data = yaml.safe_load(DEFAULT_RULES.read_text(encoding="utf-8"))
    v = AppetiteRuleVersion(version_no=int(data["version"]), status="approved", notes=data.get("notes", ""),
                            approved_by=approved_by, approved_at=utcnow(), test_report={"seed": True})
    db.add(v)
    db.flush()
    for r in data["rules"]:
        rule = Rule(id=r["id"], name=r["name"], outcome=r["outcome"], condition=r["condition"],
                    priority=r.get("priority", 100), decline_reason=r.get("decline_reason", ""))
        validate_rule(rule)
        db.add(AppetiteRule(version_id=v.id, rule_id=rule.id, name=rule.name, outcome=rule.outcome,
                            priority=rule.priority, condition=rule.condition, decline_reason=rule.decline_reason))
    db.flush()
    db.refresh(v)
    audit.record(db, action="appetite.ruleset_seeded", entity_type="appetite_rule_version", entity_id=v.id,
                 data={"version": v.version_no})
    return v


def active_version(db: Session) -> AppetiteRuleVersion | None:
    return db.scalar(select(AppetiteRuleVersion).where(AppetiteRuleVersion.status == "approved")
                     .order_by(AppetiteRuleVersion.version_no.desc()))


def active_rules(db: Session) -> tuple[int, list[Rule]]:
    v = active_version(db) or ensure_default_ruleset(db)
    return v.version_no, [_to_rule(r) for r in v.rules]


def _template_decline(broker: str, insured: str, ref: str, reasons: list[str]) -> tuple[str, str]:
    body = (f"Dear {broker},\n\nThank you for submitting {insured} (our reference {ref}). After review against "
            "Northstar General's underwriting guidelines we are unable to offer terms for the following reason(s):\n"
            + "\n".join(f"  - {r}" for r in reasons) + "\n\nKind regards,\nCommercial Property Underwriting\n"
            "Northstar General Insurance")
    return f"Northstar General - unable to quote - {ref}", body


def triage(db: Session, sub: Submission, features: dict, text: str, ai: AITasks | None,
           stage: str = "initial") -> TriageResult:
    version_no, rules = active_rules(db)
    ev = evaluate(rules, features)
    signals: dict = {}
    if ai is not None:
        try:
            signals = ai.appetite_signals(text, {k: v for k, v in features.items() if k != "region"}, sub.id).model_dump()
        except GatewayError:
            signals = {"error": "gateway_unavailable"}
    # Monitoring only: record whether the advisory model disagreed with the deterministic decision.
    signals["agrees_with_rules"] = signals.get("suggested_outcome") in (None, ev.outcome)
    rationale = "; ".join(f"{f['rule_id']} {f['name']}" for f in ev.fired) or "No appetite rules fired."
    if signals.get("rationale"):
        rationale += " | Assistant notes: " + signals["rationale"]
    for prev in db.scalars(select(TriageResult).where(TriageResult.submission_id == sub.id,
                                                      TriageResult.is_current.is_(True))):
        prev.is_current = False
    tr = TriageResult(submission_id=sub.id, outcome=ev.outcome, fired_rules=ev.fired, rule_version=version_no,
                      features=features, llm_signals=signals, rationale=rationale[:4000], stage=stage)
    broker = db.get(Broker, sub.broker_id) if sub.broker_id else None
    if ev.outcome == "out_of_appetite":
        reasons = [f["decline_reason"] for f in ev.fired if f["outcome"] == "out_of_appetite" and f["decline_reason"]]
        subject, body = _template_decline(broker.name if broker else "Partner", sub.insured_name, sub.reference, reasons)
        if ai is not None:
            try:
                letter = ai.decline_letter(broker.name if broker else "Partner", sub.insured_name, sub.reference,
                                           reasons, sub.id)
                subject, body = letter.subject, letter.body
            except GatewayError:
                pass
        tr.decline_draft = f"Subject: {subject}\n\n{body}"
        sub.status = "decline_pending"  # human one-click confirmation required; never auto-sent
    elif ev.outcome == "refer_risk_engineering":
        open_ref = db.scalar(select(Referral).where(Referral.submission_id == sub.id, Referral.status != "completed"))
        if not open_ref and sub.referral_status != "completed":
            reasons = [f"{f['rule_id']} {f['name']}" for f in ev.fired if f["outcome"] == "refer_risk_engineering"]
            db.add(Referral(submission_id=sub.id, reason="; ".join(reasons),
                            rule_ids=[f["rule_id"] for f in ev.fired if f["outcome"] == "refer_risk_engineering"],
                            region=sub.region,
                            sla_due_at=utcnow() + timedelta(hours=get_settings().referral_sla_hours)))
            sub.referral_status = "open"
    elif ev.outcome == "needs_info":
        missing = [k for k in ("occupancy_code", "sum_insured") if not features.get(k)]
        if not features.get("pincode_valid"):
            missing.append("valid pincode")
        tr.decline_draft = ("Subject: Additional information required - " + sub.reference + "\n\nDear Partner,\n\n"
                            "To progress this submission we need: " + ", ".join(missing) + ".\n\nKind regards,\n"
                            "Northstar General Insurance")
    sub.triage_outcome = ev.outcome
    db.add(tr)
    db.flush()
    audit.record(db, action=f"triage.{stage}", entity_type="submission", entity_id=sub.id, region=sub.region,
                 data={"outcome": ev.outcome, "rules": [f["rule_id"] for f in ev.fired], "rule_version": version_no,
                       "llm_suggested": signals.get("suggested_outcome"),
                       "llm_agrees": signals["agrees_with_rules"]})
    return tr


# ------------------------------------------------------------------ ruleset lifecycle

def create_draft(db: Session, author: Principal, rules: list[dict], notes: str) -> AppetiteRuleVersion:
    parsed = []
    for r in rules:
        rule = Rule(id=r["id"], name=r["name"], outcome=r["outcome"], condition=r["condition"],
                    priority=int(r.get("priority", 100)), decline_reason=r.get("decline_reason", ""),
                    enabled=bool(r.get("enabled", True)))
        try:
            validate_rule(rule)
        except RuleError as e:
            raise RulesetError(str(e)) from e
        parsed.append(rule)
    if len({r.id for r in parsed}) != len(parsed):
        raise RulesetError("Rule IDs must be unique.")
    last = db.scalar(select(AppetiteRuleVersion).order_by(AppetiteRuleVersion.version_no.desc()))
    v = AppetiteRuleVersion(version_no=(last.version_no + 1) if last else 1, status="draft", notes=notes,
                            created_by=author.user_id)
    db.add(v)
    db.flush()
    for rule in parsed:
        db.add(AppetiteRule(version_id=v.id, rule_id=rule.id, name=rule.name, outcome=rule.outcome,
                            priority=rule.priority, condition=rule.condition, decline_reason=rule.decline_reason,
                            enabled=rule.enabled))
    audit.record(db, action="appetite.draft_created", entity_type="appetite_rule_version", entity_id=v.id,
                 actor_id=author.user_id, actor_type="human", data={"version": v.version_no, "rules": len(parsed)})
    db.commit()
    db.refresh(v)
    return v


def test_draft(db: Session, version_id) -> dict:
    """Replay the draft over the historical set of triaged submissions and report the impact."""
    v = db.get(AppetiteRuleVersion, version_id)
    if v is None:
        raise RulesetError("Version not found.")
    rules = [_to_rule(r) for r in v.rules]
    history = list(db.scalars(select(TriageResult).where(TriageResult.is_current.is_(True))))
    transitions: Counter = Counter()
    changed, newly_declined = 0, 0
    for tr in history:
        new = evaluate(rules, tr.features).outcome
        baseline = tr.override_outcome or tr.outcome
        transitions[f"{baseline}->{new}"] += 1
        if new != baseline:
            changed += 1
            if new == "out_of_appetite" and baseline == "in_appetite":
                newly_declined += 1
    report = {"evaluated": len(history), "changed": changed, "newly_declined_previously_in_appetite": newly_declined,
              "transitions": dict(transitions), "tested_at": utcnow().isoformat()}
    v.test_report = report
    db.commit()
    return report


def approve(db: Session, cuo: Principal, version_id) -> AppetiteRuleVersion:
    v = db.get(AppetiteRuleVersion, version_id)
    if v is None or v.status != "draft":
        raise RulesetError("Only drafts can be approved.")
    if not v.test_report or "evaluated" not in v.test_report:
        raise RulesetError("Test the draft against the historical set before approval.")
    if v.created_by == cuo.user_id:
        raise RulesetError("The author of a ruleset cannot approve it.")
    for old in db.scalars(select(AppetiteRuleVersion).where(AppetiteRuleVersion.status == "approved")):
        old.status = "retired"
    v.status, v.approved_by, v.approved_at = "approved", cuo.user_id, utcnow()
    audit.record(db, action="appetite.ruleset_approved", entity_type="appetite_rule_version", entity_id=v.id,
                 actor_id=cuo.user_id, actor_type="human", data={"version": v.version_no, "report": v.test_report})
    db.commit()
    return v

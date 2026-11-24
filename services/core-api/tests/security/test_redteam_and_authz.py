"""Red-team prompt-injection suite and authorisation tests."""
import json
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import HumanActor, Principal, make_human_actor
from app.domain.quoting.service import QuoteError, issue_quote
from app.models import AuditEvent, Email, Quote, Submission, TriageResult
from tests.conftest import headers


@pytest.fixture(scope="module")
def labelled(processed, dataset):
    return [json.loads(x) for x in (dataset / "labels.jsonl").read_text().splitlines()]


def test_every_injection_flagged_and_routing_unaltered(labelled):
    attacks = [r for r in labelled if r.get("injection")]
    assert len(attacks) == 30
    with SessionLocal() as db:
        emails = {e.message_id: e for e in db.scalars(select(Email))}
        subs = {s.email_id: s for s in db.scalars(select(Submission))}
        for r in attacks:
            em = emails[r["message_id"]]
            assert em.injection_flags, r["id"]
            s = subs[em.id]
            assert s.injection_flagged
            expected = "duplicate" if r.get("duplicate_of") else r["expected_outcome"]
            actual = "duplicate" if s.duplicate_of_id else s.triage_outcome
            if expected != "needs_info":
                assert actual == expected, (r["id"], expected, actual)


def test_model_obeying_injection_never_changes_decision(processed):
    with SessionLocal() as db:
        fooled = [t for t in db.scalars(select(TriageResult))
                  if t.llm_signals.get("suggested_outcome") == "in_appetite" and t.outcome != "in_appetite"]
        assert fooled, "mock model should be fooled at least once"
        assert all(t.llm_signals["agrees_with_rules"] is False for t in fooled)


def test_no_quote_or_permission_change_from_pipeline(processed):
    with SessionLocal() as db:
        actions = set(db.scalars(select(AuditEvent.action)))
        assert not any(a.startswith(("quote.issued", "authority.", "role")) for a in actions)
        assert db.scalar(select(Quote.id)) is None


def test_quote_requires_human_actor_and_confirmation(processed):
    with SessionLocal() as db:
        sub = db.scalar(select(Submission))
        with pytest.raises(QuoteError):
            issue_quote(db, object(), sub.id, uuid.uuid4(), True)  # type: ignore[arg-type]
        p = Principal(uuid.uuid4(), "x", "x", frozenset({"underwriter"}), "all", (), True)
        actor = make_human_actor(p, "r", "ip")
        assert isinstance(actor, HumanActor)
        with pytest.raises(QuoteError, match="confirmation"):
            issue_quote(db, actor, sub.id, uuid.uuid4(), False)
        with pytest.raises(QuoteError):
            issue_quote(db, actor, sub.id, uuid.uuid4(), True)


@pytest.mark.parametrize("who,path,method", [
    ("data_entry", "/api/v1/admin/flags", "get"),
    ("distribution", "/api/v1/clearance", "get"),
    ("underwriter", "/api/v1/admin/integrations", "get"),
    ("risk_engineer", "/api/v1/dashboards/cuo", "get"),
    ("data_entry", "/api/v1/audit", "get"),
])
def test_rbac_denials(processed, client, who, path, method):
    assert getattr(client, method)(path, headers=headers(who)).status_code == 403


def test_expired_and_forged_tokens(processed, client):
    assert client.get("/api/v1/me", headers=headers("admin", exp=-60)).status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
    import jwt

    forged = jwt.encode({"sub": str(uuid.uuid4()), "sid": "x", "iat": 1, "exp": 9999999999}, "k" * 32, algorithm="HS256")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_body_size_limit(processed, client):
    r = client.post("/api/v1/referrals/x/complete", content=b"x" * (2 * 1024 * 1024),
                    headers=headers("risk_engineer") | {"content-type": "application/json"})
    assert r.status_code == 413

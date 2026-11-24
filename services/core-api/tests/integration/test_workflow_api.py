"""End-to-end API journeys over the processed synthetic dataset."""
import json

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import ExtractedField, Submission, SubmissionVersion
from tests.conftest import grant_authority, headers


@pytest.fixture(scope="module")
def ctx(processed):
    return processed


def _first(client, who, **params):
    r = client.get("/api/v1/submissions", params=params, headers=headers(who))
    assert r.status_code == 200, r.text
    return r.json()


def test_pipeline_processed_everything(ctx):
    assert ctx["errors"] == 0 and ctx["processed"] == ctx["fetched"] > 60


def test_queue_filters_and_region_scope(ctx, client):
    allq = _first(client, "senior", page_size=200)
    assert allq["total"] >= 50 and "status_counts" in allq
    west = _first(client, "underwriter", page_size=200)
    assert all(i["region"] == "west" for i in west["items"])
    review = _first(client, "senior", queue="review", sort="received")
    assert all(i["status"] in ("in_review", "needs_info", "info_requested") for i in review["items"])
    assert _first(client, "senior", q="zzzz-none")["total"] == 0
    assert client.get("/api/v1/submissions", headers=headers("distribution")).status_code == 403
    assert client.get("/api/v1/submissions").status_code == 401


def test_detail_preview_and_documents(ctx, client):
    item = _first(client, "senior", queue="review")["items"][0]
    d = client.get(f"/api/v1/submissions/{item['id']}", headers=headers("senior")).json()
    assert d["fields"] and d["triage"]["rule_version"] == 1 and d["email"]["body"]
    for f in d["fields"]:
        assert "confidence" in f and "source_ref" in f
    for att in d["attachments"]:
        if att["av_status"] != "clean":
            continue
        p = client.get(f"/api/v1/submissions/{item['id']}/documents/{att['id']}/preview", headers=headers("senior"))
        assert p.status_code == 200 and p.json()["kind"]
        c = client.get(f"/api/v1/submissions/{item['id']}/documents/{att['id']}/content", headers=headers("senior"))
        assert c.status_code == 200 and "sandbox" in c.headers["content-security-policy"]
    # other-region user cannot see it
    sub_region = item["region"]
    other = "uw_south" if sub_region != "south" else "underwriter"
    assert client.get(f"/api/v1/submissions/{item['id']}", headers=headers(other)).status_code == 404


def _review_ready(client, sub_id, who="senior"):
    d = client.get(f"/api/v1/submissions/{sub_id}", headers=headers(who)).json()
    for f in d["fields"]:
        if f["critical"] and f["status"] == "low_confidence":
            assert client.post(f"/api/v1/submissions/{sub_id}/fields/{f['id']}/accept", headers=headers(who)).status_code == 200
    return client.post(f"/api/v1/submissions/{sub_id}/ready", headers=headers(who))


def test_review_edit_rate_and_quote(ctx, client):
    with SessionLocal() as db:
        claims = grant_authority(db, "senior")
        sub = db.scalar(select(Submission).where(Submission.status == "in_review", Submission.referral_status == "none",
                                                 Submission.sov_reconciled.is_not(False)))
        f = db.scalar(select(ExtractedField).where(ExtractedField.submission_id == sub.id,
                                                   ExtractedField.path == "insured.name"))
    h = headers("senior", authority=claims)
    r = client.patch(f"/api/v1/submissions/{sub.id}/fields/{f.id}", json={"value": sub.insured_name + " (Unit 2)",
                                                                       "reason": "per proposal page 1"}, headers=h)
    assert r.status_code == 200 and r.json()["field"]["edited"]
    bad = client.patch(f"/api/v1/submissions/{sub.id}/fields/{f.id}", json={"value": "x"}, headers=headers("distribution"))
    assert bad.status_code == 403
    # cannot rate before ready
    assert client.post(f"/api/v1/submissions/{sub.id}/rating", headers=h).status_code == 422
    assert _review_ready(client, sub.id).status_code == 200
    rr = client.post(f"/api/v1/submissions/{sub.id}/rating", headers=h)
    assert rr.status_code == 200, rr.text
    run = rr.json()["rating_run"]
    assert run["source"] in ("rating_api", "excel_model") and run["source_version"] and rr.json()["authority"]["allowed"]
    chk = client.get(f"/api/v1/submissions/{sub.id}/authority-check", params={"rating_run_id": run["id"]}, headers=h)
    assert chk.json()["rating_current"] is True
    # explicit confirmation required
    assert client.post(f"/api/v1/submissions/{sub.id}/quote", json={"rating_run_id": run["id"], "confirm": False},
                       headers=h).status_code == 409
    # no MFA -> blocked by authority
    assert client.post(f"/api/v1/submissions/{sub.id}/quote", json={"rating_run_id": run["id"], "confirm": True},
                       headers=headers("senior", authority=claims, mfa=False)).status_code == 403
    q = client.post(f"/api/v1/submissions/{sub.id}/quote", json={"rating_run_id": run["id"], "confirm": True}, headers=h)
    assert q.status_code == 200, q.text
    assert q.json()["policy_admin_ref"].startswith("PA-") and len(q.json()["audit_seal_hash"]) == 64
    again = client.post(f"/api/v1/submissions/{sub.id}/quote", json={"rating_run_id": run["id"], "confirm": True}, headers=h)
    assert again.status_code == 409
    d = client.get(f"/api/v1/submissions/{sub.id}", headers=h).json()
    assert d["status"] == "quoted" and d["quote"]["authority_snapshot"]["allowed"]


def test_out_of_authority_requires_referral(ctx, client):
    with SessionLocal() as db:
        claims = grant_authority(db, "underwriter", max_si=1_000_000, max_premium=1000, regions=("west",))
        sub = db.scalar(select(Submission).where(Submission.status == "in_review", Submission.region == "west",
                                                 Submission.referral_status == "none",
                                                 Submission.sov_reconciled.is_not(False)))
    if sub is None:
        pytest.skip("no west submission in review")
    h = headers("underwriter", authority=claims)
    assert _review_ready(client, sub.id, "underwriter").status_code == 200
    run = client.post(f"/api/v1/submissions/{sub.id}/rating", headers=h).json()
    assert run["authority"]["allowed"] is False and run["authority"]["requires_referral_to"] == "senior_underwriter"
    q = client.post(f"/api/v1/submissions/{sub.id}/quote", json={"rating_run_id": run["rating_run"]["id"], "confirm": True},
                    headers=h)
    assert q.status_code == 403 and q.json()["detail"]["authority"]["reasons"]
    # stale token claims (no authority in token) are refused even if DB allows
    stale = client.get(f"/api/v1/submissions/{sub.id}/authority-check",
                       params={"rating_run_id": run["rating_run"]["id"]}, headers=headers("underwriter"))
    assert "out of date" in " ".join(stale.json()["reasons"])
    refer = client.post(f"/api/v1/submissions/{sub.id}/refer", json={"reason": "outside my authority"}, headers=h)
    assert refer.json()["referral_status"] == "open"


def test_decline_confirmation_flow(ctx, client):
    items = _first(client, "senior", status="decline_pending")["items"]
    assert items, "dataset should contain out-of-appetite submissions"
    sid = items[0]["id"]
    d = client.get(f"/api/v1/submissions/{sid}", headers=headers("senior")).json()
    assert d["triage"]["decline_draft"].startswith("Subject:") and d["triage"]["fired_rules"]
    assert client.post(f"/api/v1/submissions/{sid}/triage/decline", json={}, headers=headers("data_entry")).status_code == 403
    r = client.post(f"/api/v1/submissions/{sid}/triage/decline", json={}, headers=headers("senior"))
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert client.post(f"/api/v1/submissions/{sid}/triage/decline", json={}, headers=headers("senior")).status_code == 422


def test_override_triage_resumes_pipeline(ctx, client):
    items = _first(client, "senior", status="decline_pending")["items"]
    sid = items[0]["id"]
    short = client.post(f"/api/v1/submissions/{sid}/triage/override", json={"outcome": "in_appetite", "reason": "x"},
                        headers=headers("senior"))
    assert short.status_code == 422
    r = client.post(f"/api/v1/submissions/{sid}/triage/override",
                    json={"outcome": "in_appetite", "reason": "Survey confirms sprinklered RCC; occupancy misread"},
                    headers=headers("senior"))
    assert r.status_code == 200 and r.json()["status"] in ("in_review", "needs_info")


def test_clearance_queue_and_resolution(ctx, client):
    q = client.get("/api/v1/clearance", headers=headers("senior")).json()
    assert q and q[0]["components"]["name"] >= 0.7
    link = q[0]
    r = client.post(f"/api/v1/clearance/{link['id']}/resolve", json={"confirm": True, "reason": "same risk"},
                    headers=headers("senior"))
    assert r.status_code == 200 and r.json()["status"] == "duplicate"
    assert client.post(f"/api/v1/clearance/{link['id']}/resolve", json={"confirm": True},
                       headers=headers("senior")).status_code == 409
    if len(q) > 1:
        r = client.post(f"/api/v1/clearance/{q[1]['id']}/resolve", json={"confirm": False, "reason": "different"},
                        headers=headers("senior"))
        assert r.status_code == 200 and r.json()["status"] != "duplicate"


def test_referral_lifecycle(ctx, client):
    refs = client.get("/api/v1/referrals", params={"status": "open"}, headers=headers("cuo")).json()
    assert refs
    rid = refs[0]["id"]
    assert client.post(f"/api/v1/referrals/{rid}/claim", headers=headers("underwriter")).status_code == 403
    with SessionLocal() as db:
        from app.models import Referral

        ref = db.get(Referral, __import__("uuid").UUID(rid))
        ref.region = "west"
        db.commit()
    assert client.post(f"/api/v1/referrals/{rid}/claim", headers=headers("risk_engineer")).json()["status"] == "in_progress"
    bad = client.post(f"/api/v1/referrals/{rid}/complete", json={"findings": "x", "recommendation": "maybe"},
                      headers=headers("risk_engineer"))
    assert bad.status_code == 422
    done = client.post(f"/api/v1/referrals/{rid}/complete", json={
        "findings": "Survey completed; hydrant system adequate.", "recommendation": "proceed_with_conditions",
        "conditions": ["Install sprinklers in warehouse"]}, headers=headers("risk_engineer"))
    assert done.status_code == 200 and done.json()["status"] == "completed"


def test_mid_flight_update_diff(ctx, client):
    with SessionLocal() as db:
        v = db.scalar(select(SubmissionVersion).where(SubmissionVersion.version_no == 2))
    if v is None:
        pytest.skip("no update in small dataset")
    r = client.get(f"/api/v1/submissions/{v.submission_id}/versions/2", headers=headers("senior"))
    assert r.status_code == 200 and any(d["change"] == "changed" for d in r.json()["diff"])
    assert client.get(f"/api/v1/submissions/{v.submission_id}/versions/9", headers=headers("senior")).status_code == 404


def test_dashboards(ctx, client):
    ops = client.get("/api/v1/dashboards/ops", headers=headers("cuo")).json()
    assert ops["submissions"] > 0 and "cost" in ops and ops["duplicate_rate"] > 0
    uw = client.get("/api/v1/dashboards/underwriting", headers=headers("cuo")).json()
    assert "ai_override_rates" in uw and uw["quotes"] >= 1
    cuo = client.get("/api/v1/dashboards/cuo", headers=headers("cuo")).json()
    assert cuo["outcome_hierarchy"][0]["role"] == "guardrail" and "ai_assisted" in cuo["loss_ratio_by_cohort"]
    dist = client.get("/api/v1/dashboards/distribution", headers=headers("distribution")).json()
    one = client.get("/api/v1/dashboards/distribution", params={"broker_id": dist["brokers"][0]["id"]},
                     headers=headers("distribution")).json()
    assert one["broker"]["id"] == dist["brokers"][0]["id"] and "win_rate" in one["broker"]
    assert client.get("/api/v1/dashboards/cuo", headers=headers("distribution")).status_code == 403


def test_audit_explorer(ctx, client):
    r = client.get("/api/v1/audit", params={"action": "quote"}, headers=headers("cuo")).json()
    assert r["items"] and r["items"][0]["hash"]
    assert client.get("/api/v1/audit/verify", headers=headers("cuo")).json()["valid"] is True
    exp = client.get("/api/v1/audit/export", params={"fmt": "csv"}, headers=headers("cuo"))
    assert exp.status_code == 200 and "seq" in exp.text.splitlines()[0]
    jl = client.get("/api/v1/audit/export", headers=headers("admin"))
    assert json.loads(jl.text.splitlines()[0])["seq"] == 1


def test_me_and_health(ctx, client):
    assert client.get("/api/v1/me", headers=headers("senior")).json()["roles"] == ["senior_underwriter"]
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/ready").json()["status"] == "ready"
    assert "nsip_http_requests_total" in client.get("/metrics").text
    assert client.get("/api/v1/healthz/deep", headers=headers("admin")).json()["audit_chain"] is True
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]

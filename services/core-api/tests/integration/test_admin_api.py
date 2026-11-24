from email.message import EmailMessage

from app.domain.extraction.sov import fingerprint
from tests.conftest import USERS, headers


def test_authority_maker_checker(db, client):
    from app.models import User

    db.add(User(id=USERS["underwriter"][0], email="u@x", full_name="UW", region="west"))
    db.commit()
    body = {"user_id": str(USERS["underwriter"][0]), "line": "property", "max_sum_insured": 250000000,
            "max_premium": 1000000, "regions": ["west"], "reason": "pilot authority"}
    assert client.post("/api/v1/admin/authority", json=body, headers=headers("underwriter")).status_code == 403
    r = client.post("/api/v1/admin/authority", json=body, headers=headers("admin"))
    assert r.status_code == 201 and r.json()["status"] == "pending"
    lid = r.json()["id"]
    same = client.post(f"/api/v1/admin/authority/{lid}/decide", json={"approve": True}, headers=headers("admin"))
    assert same.status_code == 409  # maker cannot check
    ok = client.post(f"/api/v1/admin/authority/{lid}/decide", json={"approve": True}, headers=headers("cuo"))
    assert ok.json()["status"] == "approved"
    users = client.get("/api/v1/admin/users", headers=headers("admin")).json()
    assert any(u["authority"] for u in users)
    assert client.get("/api/v1/admin/authority", headers=headers("cuo")).json()[0]["status"] == "approved"


def test_appetite_rule_lifecycle(db, client):
    versions = client.get("/api/v1/admin/appetite/versions", headers=headers("cuo")).json()
    rules = versions[0]["rules"]
    rules.append({"id": "APP-099", "name": "No cold storage in high cat zone", "outcome": "out_of_appetite",
                  "priority": 5, "condition": {"all": [{"field": "occupancy_code", "op": "eq", "value": "COLD_STORAGE"},
                                                        {"field": "cat_zone", "op": "eq", "value": "high"}]},
                  "decline_reason": "Cold storage in high cat zones is outside appetite."})
    bad = client.post("/api/v1/admin/appetite/drafts", json={"rules": [{**rules[0], "condition": {"op": "zz"}}]},
                      headers=headers("admin"))
    assert bad.status_code == 422
    d = client.post("/api/v1/admin/appetite/drafts", json={"rules": rules, "notes": "add APP-099"}, headers=headers("admin"))
    assert d.status_code == 201
    vid = d.json()["id"]
    assert client.post(f"/api/v1/admin/appetite/versions/{vid}/approve", headers=headers("cuo")).status_code == 409
    rep = client.post(f"/api/v1/admin/appetite/versions/{vid}/test", headers=headers("admin")).json()
    assert "evaluated" in rep
    assert client.post(f"/api/v1/admin/appetite/versions/{vid}/approve", headers=headers("admin")).status_code == 403
    ok = client.post(f"/api/v1/admin/appetite/versions/{vid}/approve", headers=headers("cuo"))
    assert ok.json()["status"] == "approved" and ok.json()["version_no"] == 2


def test_flags_integrations_cost_mappings(db, client):
    flags = client.get("/api/v1/admin/flags", headers=headers("admin")).json()
    assert any(f["key"] == "region.west" for f in flags)
    assert client.put("/api/v1/admin/flags/region.east", json={"enabled": False}, headers=headers("admin")).json()["enabled"] is False
    assert client.put("/api/v1/admin/flags/nope", json={"enabled": True}, headers=headers("admin")).status_code == 404
    assert "budgets" in client.get("/api/v1/admin/integrations", headers=headers("admin")).json()
    secret = client.put("/api/v1/admin/integrations/geocoding", json={"config": {"api_key": "x"}}, headers=headers("admin"))
    assert secret.status_code == 422
    assert client.put("/api/v1/admin/integrations/budgets", json={"config": {"monthly_budget_inr": 1}},
                      headers=headers("admin")).status_code == 200
    cost = client.get("/api/v1/admin/cost", headers=headers("cuo")).json()
    assert "projected_monthly_inr" in cost
    maps = client.get("/api/v1/admin/mappings", headers=headers("admin")).json()
    assert len(maps) >= 30 and all(m["status"] == "approved" for m in maps)
    from app.domain.extraction.sov import save_learned_mapping

    m = save_learned_mapping(db, ["A Col", "B Col"], [{"header": "A Col", "field": "address", "unit_multiplier": 1}], "b")
    db.commit()
    assert m.fingerprint == fingerprint(["A Col", "B Col"])
    r = client.post(f"/api/v1/admin/mappings/{m.id}/decide", json={"approve": True}, headers=headers("admin"))
    assert r.json()["status"] == "approved"
    assert client.post(f"/api/v1/admin/mappings/{m.id}/decide", json={"approve": True},
                       headers=headers("admin")).status_code == 409


def _eml(subject: str, body: str, mid: str, attach: bytes | None = None) -> bytes:
    m = EmailMessage()
    m["From"] = "placement@meridianbrokers.example"
    m["To"] = "submissions.west@northstar.example"
    m["Subject"], m["Message-ID"] = subject, mid
    m.set_content(body)
    if attach is not None:
        m.add_attachment(attach, maintype="application", subtype="octet-stream", filename="virus.pdf")
    return bytes(m)


def test_upload_eml_ingestion_and_privacy(db, client):
    body = ("Insured Name: Apex Shakti Technologies Pvt Ltd\nRisk Address: Unit 4, Tech Park, Pune\nPincode: 411014\n"
            "Occupancy: IT services office\nConstruction: RCC\nYear Built: 2012\nSum Insured: Rs 4 crore\n"
            "Contact Person: Mr. Rajesh Sharma\nMobile: 9876543210\n")
    eml = _eml("New property submission", body, "<t1@x>", b"X5O EICAR-STANDARD-ANTIVIRUS-TEST-FILE")
    r = client.post("/api/v1/admin/ingestion/upload-eml", files={"file": ("a.eml", eml)}, headers=headers("admin"))
    assert r.status_code == 200 and r.json()["status"] == "processed", r.text
    sid = r.json()["submission_id"]
    d = client.get(f"/api/v1/submissions/{sid}", headers=headers("admin")).json()
    assert d["status"] == "in_review" and d["attachments"][0]["av_status"] == "infected"
    dup = client.post("/api/v1/admin/ingestion/upload-eml", files={"file": ("a.eml", eml)}, headers=headers("admin"))
    assert dup.json()["status"] == "duplicate_message"
    noise = _eml("Automatic reply: Out of office", "I am away.", "<t2@x>")
    assert client.post("/api/v1/admin/ingestion/upload-eml", files={"file": ("b.eml", noise)},
                       headers=headers("admin")).json()["classification"] == "noise"
    er = client.post("/api/v1/admin/privacy/erasure", json={"identifier": "9876543210", "reason": "DPDP request"},
                     headers=headers("admin"))
    assert er.json()["records_erased"] >= 1
    d = client.get(f"/api/v1/submissions/{sid}", headers=headers("admin")).json()
    assert "9876543210" not in d["email"]["body"]
    assert "records" in client.post("/api/v1/admin/privacy/retention", headers=headers("admin")).json()
    assert client.post("/api/v1/admin/ingestion/poll", headers=headers("admin")).json()["fetched"] >= 0


def test_request_info_and_conflict(db, client):
    body = ("Insured Name: Om Metro Retail Pvt Ltd\nRisk Address: Shop 2, MG Road, Pune\nPincode: 411001\n"
            "Occupancy: retail store\nConstruction: RCC\nSum Insured: Rs 2 crore\n")
    r = client.post("/api/v1/admin/ingestion/upload-eml", files={"file": ("c.eml", _eml("Quote request", body, "<t3@x>"))},
                    headers=headers("admin")).json()
    sid = r["submission_id"]
    msg = client.post(f"/api/v1/submissions/{sid}/request-info", json={"message": "Please send the full SOV and photos."},
                      headers=headers("data_entry"))
    assert msg.json()["status"] == "info_requested"
    d = client.get(f"/api/v1/submissions/{sid}", headers=headers("data_entry")).json()
    f = next(x for x in d["fields"] if x["path"] == "cover.sum_insured")
    bad = client.patch(f"/api/v1/submissions/{sid}/fields/{f['id']}", json={"value": "lots"}, headers=headers("data_entry"))
    assert bad.status_code == 422
    ok = client.patch(f"/api/v1/submissions/{sid}/fields/{f['id']}", json={"value": "2.5 crore", "reason": "broker call"},
                      headers=headers("data_entry"))
    assert ok.json()["field"]["value"] == 25000000
    assert client.post(f"/api/v1/submissions/{sid}/fields/{f['id']}/resolve", json={"keep": "mine"},
                       headers=headers("data_entry")).status_code == 409

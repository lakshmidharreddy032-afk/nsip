import json
from pathlib import Path

import jwt
import pyotp

from app.core.config import get_settings
from app.core.security import decode_access_token, sign_reset_token, validate_password_policy
from tests.conftest import login_full, totp_code


def test_jwks_published(client):
    keys = client.get("/.well-known/jwks.json").json()["keys"]
    assert keys[0]["kty"] == "RSA" and keys[0]["alg"] == "RS256" and "d" not in keys[0]


def test_login_without_mfa_role(client, password):
    r = client.post("/auth/login", json={"email": "dataentry@northstar.example", "password": password})
    body = r.json()
    assert body["status"] == "authenticated"
    claims = decode_access_token(body["token"]["access_token"])
    assert claims["roles"] == ["data_entry"] and claims["exp"] - claims["iat"] == 900
    cookie_header = r.headers.get("set-cookie", "")
    assert "nsip_rt=" in cookie_header and "HttpOnly" in cookie_header and "samesite=strict" in cookie_header.lower()


def test_underwriter_requires_mfa(client, password):
    r = client.post("/auth/login", json={"email": "underwriter@northstar.example", "password": password})
    assert r.json()["status"] == "mfa_required"
    assert "nsip_rt" not in r.headers.get("set-cookie", "")
    bad = client.post("/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": totp_code()})
    assert ok.status_code == 200
    claims = decode_access_token(ok.json()["token"]["access_token"])
    assert claims["mfa"] is True and "otp" in claims["amr"]


def test_totp_replay_rejected(client, password):
    login_full(client, "underwriter@northstar.example")
    r = client.post("/auth/login", json={"email": "underwriter@northstar.example", "password": password})
    replay = client.post("/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": totp_code()})
    assert replay.status_code == 401


def test_lockout_after_five_failures(client, password):
    for _ in range(5):
        r = client.post("/auth/login", json={"email": "dataentry@northstar.example", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/auth/login", json={"email": "dataentry@northstar.example", "password": password})
    assert r.status_code == 423 and int(r.headers["Retry-After"]) > 0
    events = [e["event"] for e in client.get(
        "/auth/admin/audit", headers=_admin_headers(client)).json()]
    assert "account_locked" in events and "login_failure" in events


def test_unknown_user_generic_error(client):
    r = client.post("/auth/login", json={"email": "nobody@x.example", "password": "whatever"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"


def _admin_headers(client):
    tok = login_full(client, "admin@northstar.example")
    return {"Authorization": f"Bearer {tok['access_token']}"}


def test_refresh_rotation_and_reuse_detection(client, password):
    r = client.post("/auth/login", json={"email": "dataentry@northstar.example", "password": password})
    old_rt = client.cookies.get("nsip_rt")
    csrf = client.cookies.get("nsip_csrf")
    no_csrf = client.post("/auth/refresh")
    assert no_csrf.status_code == 403
    r = client.post("/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    new_rt = client.cookies.get("nsip_rt")
    assert new_rt and new_rt != old_rt
    # Replay the old (already rotated) refresh token: whole family must be revoked.
    client.cookies.set("nsip_rt", old_rt, path="/auth")
    r = client.post("/auth/refresh", headers={"X-CSRF-Token": client.cookies.get("nsip_csrf") or csrf})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "refresh_reuse"
    client.cookies.set("nsip_rt", new_rt, path="/auth")
    client.cookies.set("nsip_csrf", csrf, path="/")
    r = client.post("/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 401


def test_sessions_and_remote_sign_out(client):
    tok = login_full(client, "underwriter@northstar.example")
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    sessions = client.get("/auth/sessions", headers=h).json()
    assert len(sessions) == 1 and sessions[0]["current"]
    assert client.delete(f"/auth/sessions/{sessions[0]['id']}", headers=h).json()["status"] == "revoked"
    assert client.get("/auth/sessions", headers=h).status_code == 401


def test_logout_revokes(client, password):
    client.post("/auth/login", json={"email": "dataentry@northstar.example", "password": password})
    csrf = client.cookies.get("nsip_csrf")
    rt = client.cookies.get("nsip_rt")
    assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    client.cookies.set("nsip_rt", rt, path="/auth")
    client.cookies.set("nsip_csrf", csrf, path="/")
    assert client.post("/auth/refresh", headers={"X-CSRF-Token": csrf}).status_code == 401


def test_password_reset_single_use(client):
    r = client.post("/auth/password/forgot", json={"email": "dataentry@northstar.example"})
    assert r.status_code == 202
    assert client.post("/auth/password/forgot", json={"email": "ghost@x.example"}).status_code == 202
    mail = next(Path(get_settings().mail_outbox_dir).glob("reset-*.json"))
    token = json.loads(mail.read_text())["link"].split("token=")[1]
    weak = client.post("/auth/password/reset", json={"token": token, "new_password": "short"})
    assert weak.status_code == 400
    ok = client.post("/auth/password/reset", json={"token": token, "new_password": "BrandNew#Passw0rd"})
    assert ok.status_code == 200
    again = client.post("/auth/password/reset", json={"token": token, "new_password": "Another#Passw0rd1"})
    assert again.status_code == 400
    r = client.post("/auth/login", json={"email": "dataentry@northstar.example", "password": "BrandNew#Passw0rd"})
    assert r.json()["status"] == "authenticated"
    mail.unlink()


def test_tampered_reset_token(client):
    tok = sign_reset_token("00000000-0000-0000-0000-000000000000", "x", 60)
    r = client.post("/auth/password/reset", json={"token": tok[:-2] + "aa", "new_password": "BrandNew#Passw0rd"})
    assert r.status_code == 400


def test_admin_role_change_audited_and_non_admin_forbidden(client):
    h = _admin_headers(client)
    users = client.get("/auth/admin/users", headers=h).json()
    de = next(u for u in users if u["email"] == "dataentry@northstar.example")
    r = client.put(f"/auth/admin/users/{de['id']}/roles", headers=h, json={"roles": ["data_entry", "distribution"]})
    assert r.status_code == 200 and r.json()["roles"] == ["data_entry", "distribution"]
    assert client.put(f"/auth/admin/users/{de['id']}/roles", headers=h, json={"roles": ["god"]}).status_code == 422
    events = client.get("/auth/admin/audit", headers=h).json()
    assert any(e["event"] == "role_change" for e in events)
    de_tok = login_full(client, "dataentry@northstar.example")
    assert client.get("/auth/admin/users", headers={"Authorization": f"Bearer {de_tok['access_token']}"}).status_code == 403


def test_create_user_enrolls_mfa(client):
    h = _admin_headers(client)
    r = client.post("/auth/admin/users", headers=h, json={
        "email": "new.uw@northstar.example", "full_name": "New UW", "region": "north",
        "roles": ["underwriter"], "temporary_password": "Temp#Password123"})
    assert r.status_code == 201
    r = client.post("/auth/login", json={"email": "new.uw@northstar.example", "password": "Temp#Password123"})
    body = r.json()
    assert body["status"] == "mfa_enroll_required" and body["otpauth_uri"].startswith("otpauth://")
    code = pyotp.TOTP(body["secret"]).now()
    r = client.post("/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": code})
    assert r.status_code == 200 and r.json()["token"]["user"]["mfa_enabled"] is True


def test_unlock_and_deactivate(client):
    h = _admin_headers(client)
    users = {u["email"]: u for u in client.get("/auth/admin/users", headers=h).json()}
    uid = users["distribution@northstar.example"]["id"]
    assert client.post(f"/auth/admin/users/{uid}/unlock", headers=h).status_code == 200
    assert client.post(f"/auth/admin/users/{uid}/deactivate", headers=h).status_code == 200
    r = client.post("/auth/login", json={"email": "distribution@northstar.example", "password": "Northstar@2026!"})
    assert r.status_code == 401


def test_internal_authority_push_becomes_claim(client):
    h = _admin_headers(client)
    uw = next(u for u in client.get("/auth/admin/users", headers=h).json()
              if u["email"] == "underwriter@northstar.example")
    entry = [{"line": "property", "max_sum_insured": 500000000, "max_premium": 1000000, "regions": ["west"],
              "limit_id": "x", "version": 1}]
    assert client.put(f"/auth/internal/users/{uw['id']}/authority", json={"authority": entry}).status_code == 401
    r = client.put(f"/auth/internal/users/{uw['id']}/authority", json={"authority": entry},
                   headers={"X-Internal-Token": "dev-internal-token"})
    assert r.status_code == 200
    tok = login_full(client, "underwriter@northstar.example")
    assert decode_access_token(tok["access_token"])["authority"] == entry


def test_invalid_bearer(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer abc"}).status_code == 401
    forged = jwt.encode({"sub": "x"}, "secret", algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_me_and_config(client):
    tok = login_full(client, "cuo@northstar.example")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
    assert me["roles"] == ["cuo"]
    assert client.get("/auth/config").json()["sso_enabled"] is False
    assert client.get("/auth/oidc/login").status_code == 404
    assert client.get("/auth/health").json()["status"] == "ok"
    assert "nsip_auth_requests_total" in client.get("/auth/metrics").text


def test_password_policy():
    assert validate_password_policy("short", "a@b.c")
    assert validate_password_policy("arjunarjun#Pass1", "arjun@x.com")
    assert not validate_password_policy("Str0ng#Passphrase", "arjun@x.com")


def test_security_headers(client):
    r = client.get("/auth/health")
    assert r.headers["X-Frame-Options"] == "DENY" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]

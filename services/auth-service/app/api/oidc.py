"""Optional Azure AD (OIDC) sign-in behind the AUTH_OIDC_ENABLED feature flag.

Authorization-code flow with PKCE, state and nonce. Only pre-provisioned users can sign in (no JIT
account creation), so role assignment always stays inside NSIP administration.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import client_info
from app.api.routes import _set_session_cookies
from app.core.config import get_settings
from app.core.db import get_db
from app.services import auth as svc

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])
_pending: dict[str, dict] = {}  # state -> {verifier, nonce, ts}; short-lived


def _enabled() -> None:
    if not get_settings().oidc_enabled:
        raise HTTPException(404, detail={"code": "sso_disabled", "message": "SSO is not enabled."})


def _discovery() -> dict:
    s = get_settings()
    r = httpx.get(f"{s.oidc_issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    return r.json()


@router.get("/login", dependencies=[Depends(_enabled)])
def oidc_login():
    s = get_settings()
    disc = _discovery()
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    _pending[state] = {"verifier": verifier, "nonce": nonce, "ts": time.time()}
    params = {"client_id": s.oidc_client_id, "response_type": "code", "redirect_uri": s.oidc_redirect_uri,
              "scope": "openid email profile", "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    return RedirectResponse(f"{disc['authorization_endpoint']}?{urlencode(params)}")


@router.get("/callback", dependencies=[Depends(_enabled)])
def oidc_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    pending = _pending.pop(state, None)
    if not pending or time.time() - pending["ts"] > 600:
        raise HTTPException(400, detail={"code": "invalid_state", "message": "Sign-in expired."})
    disc = _discovery()
    tok = httpx.post(disc["token_endpoint"], timeout=10, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": s.oidc_redirect_uri,
        "client_id": s.oidc_client_id, "client_secret": s.oidc_client_secret,
        "code_verifier": pending["verifier"]})
    tok.raise_for_status()
    id_token = tok.json()["id_token"]
    signing_key = jwt.PyJWKClient(disc["jwks_uri"]).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, signing_key.key, algorithms=["RS256"], audience=s.oidc_client_id,
                        issuer=disc["issuer"])
    if claims.get("nonce") != pending["nonce"]:
        raise HTTPException(400, detail={"code": "invalid_nonce", "message": "Sign-in failed."})
    user = svc.get_user_by_email(db, claims.get("email") or claims.get("preferred_username", ""))
    if not user or not user.is_active:
        raise HTTPException(403, detail={"code": "not_provisioned", "message": "No NSIP account for this user."})
    mfa = "mfa" in (claims.get("amr") or [])
    if svc.requires_mfa(user) and not mfa:
        raise HTTPException(403, detail={"code": "mfa_required", "message": "Your IdP sign-in must use MFA."})
    result = svc.create_session(db, user, client_info(request), mfa=mfa, amr=["oidc"] + (["mfa"] if mfa else []))
    resp = RedirectResponse(s.workbench_url, status_code=302)
    _set_session_cookies(resp, result["refresh_token"])
    return resp

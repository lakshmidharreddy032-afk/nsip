from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    check_csrf,
    client_info,
    current_user,
    rate_limit_login,
    require_admin,
    require_internal,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.core.keys import jwks
from app.core.security import hash_password, validate_password_policy
from app.models import AuthAuditEvent, AuthUser
from app.schemas import (
    AuditOut,
    AuthorityUpdate,
    CreateUserRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MfaVerifyRequest,
    ResetPasswordRequest,
    RolesUpdate,
    SessionOut,
)
from app.services import auth as svc
from app.services.auth import VALID_ROLES, AuthError, audit

router = APIRouter()


def _error(e: AuthError) -> JSONResponse:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    return JSONResponse(status_code=e.status, content={"detail": {"code": e.code, "message": e.message,
                                                                   "retry_after": e.retry_after}},
                        headers=headers)


def _set_session_cookies(resp: Response, refresh: str) -> None:
    s = get_settings()
    resp.set_cookie(s.refresh_cookie_name, refresh, max_age=s.refresh_ttl_seconds, httponly=True,
                    secure=s.cookie_secure, samesite="strict", path="/auth", domain=s.cookie_domain)
    resp.set_cookie(s.csrf_cookie_name, secrets.token_urlsafe(24), max_age=s.refresh_ttl_seconds,
                    httponly=False, secure=s.cookie_secure, samesite="strict", path="/",
                    domain=s.cookie_domain)


def _clear_cookies(resp: Response) -> None:
    s = get_settings()
    resp.delete_cookie(s.refresh_cookie_name, path="/auth", domain=s.cookie_domain)
    resp.delete_cookie(s.csrf_cookie_name, path="/", domain=s.cookie_domain)


def _token_body(result: dict) -> dict:
    return {"access_token": result["access_token"], "token_type": "Bearer", "expires_in": result["expires_in"],
            "user": {**result["user"], "id": str(result["user"]["id"])}}


@router.get("/.well-known/jwks.json", tags=["keys"])
def get_jwks() -> dict:
    return jwks()


@router.post("/auth/login", dependencies=[Depends(rate_limit_login)])
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client = client_info(request)
    try:
        user = svc.authenticate_password(db, body.email, body.password, client)
    except AuthError as e:
        return _error(e)
    if svc.requires_mfa(user) or user.mfa_enabled:
        return svc.start_mfa(db, user, client)
    result = svc.create_session(db, user, client, mfa=False, amr=["pwd"])
    resp = JSONResponse({"status": "authenticated", "token": _token_body(result)})
    _set_session_cookies(resp, result["refresh_token"])
    return resp


@router.post("/auth/mfa/verify", dependencies=[Depends(rate_limit_login)])
def mfa_verify(body: MfaVerifyRequest, request: Request, db: Session = Depends(get_db)):
    client = client_info(request)
    try:
        user = svc.verify_mfa(db, body.mfa_token, body.code, client)
    except AuthError as e:
        return _error(e)
    result = svc.create_session(db, user, client, mfa=True, amr=["pwd", "otp"])
    resp = JSONResponse({"status": "authenticated", "token": _token_body(result)})
    _set_session_cookies(resp, result["refresh_token"])
    return resp


@router.post("/auth/refresh", dependencies=[Depends(check_csrf)])
def refresh(request: Request, db: Session = Depends(get_db)):
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw:
        return _error(AuthError("no_session", "Sign in required."))
    try:
        result = svc.rotate_refresh(db, raw, client_info(request))
    except AuthError as e:
        resp = _error(e)
        _clear_cookies(resp)
        return resp
    resp = JSONResponse(_token_body(result))
    _set_session_cookies(resp, result["refresh_token"])
    return resp


@router.post("/auth/logout", dependencies=[Depends(check_csrf)])
def logout(request: Request, db: Session = Depends(get_db)):
    svc.logout(db, request.cookies.get(get_settings().refresh_cookie_name), client_info(request))
    resp = JSONResponse({"status": "signed_out"})
    _clear_cookies(resp)
    return resp


@router.get("/auth/me")
def me(user: AuthUser = Depends(current_user)):
    return svc._user_out(user) | {"id": str(user.id), "authority": user.authority}


@router.get("/auth/sessions", response_model=list[SessionOut])
def sessions(user: AuthUser = Depends(current_user), db: Session = Depends(get_db)):
    sid = user._claims["sid"]  # type: ignore[attr-defined]
    return [
        SessionOut(id=s.id, created_at=s.created_at, last_seen_at=s.last_seen_at, ip=s.ip,
                   user_agent=s.user_agent, current=str(s.id) == sid, mfa_verified=s.mfa_verified)
        for s in svc.list_sessions(db, user.id)
    ]


@router.delete("/auth/sessions/{session_id}")
def revoke(session_id: uuid.UUID, request: Request, user: AuthUser = Depends(current_user),
           db: Session = Depends(get_db)):
    try:
        svc.revoke_session(db, user, session_id, client_info(request))
    except AuthError as e:
        return _error(e)
    return {"status": "revoked"}


@router.post("/auth/password/forgot", status_code=202, dependencies=[Depends(rate_limit_login)])
def forgot(body: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    svc.request_password_reset(db, body.email, client_info(request))
    return {"status": "accepted", "message": "If the account exists, a reset link has been sent."}


@router.post("/auth/password/reset", dependencies=[Depends(rate_limit_login)])
def reset(body: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    try:
        svc.reset_password(db, body.token, body.new_password, client_info(request))
    except AuthError as e:
        return _error(e)
    return {"status": "password_updated"}


@router.get("/auth/config")
def public_config() -> dict:
    """Public, non-secret configuration consumed by the login application."""
    s = get_settings()
    return {"sso_enabled": s.oidc_enabled, "password_min_length": 12}


# ----- Admin (user management, role changes) -----

@router.get("/auth/admin/users")
def list_users(_: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(AuthUser).order_by(AuthUser.email))
    return [svc._user_out(u) | {"id": str(u.id), "authority": u.authority,
                                "last_login_at": u.last_login_at} for u in users]


@router.post("/auth/admin/users", status_code=201)
def create_user(body: CreateUserRequest, request: Request, admin: AuthUser = Depends(require_admin),
                db: Session = Depends(get_db)):
    if svc.get_user_by_email(db, body.email):
        raise HTTPException(409, detail={"code": "exists", "message": "User already exists."})
    bad = [r for r in body.roles if r not in VALID_ROLES]
    if bad:
        raise HTTPException(422, detail={"code": "invalid_role", "message": f"Unknown roles: {bad}"})
    problems = validate_password_policy(body.temporary_password, body.email)
    if problems:
        raise HTTPException(422, detail={"code": "weak_password", "message": " ".join(problems)})
    user = AuthUser(email=body.email.lower(), full_name=body.full_name, region=body.region,
                    password_hash=hash_password(body.temporary_password))
    user.roles = svc.ensure_roles(db, body.roles)
    db.add(user)
    db.flush()
    audit(db, "user_created", client_info(request), user, by=str(admin.id), roles=body.roles)
    db.commit()
    return svc._user_out(user) | {"id": str(user.id)}


@router.put("/auth/admin/users/{user_id}/roles")
def update_roles(user_id: uuid.UUID, body: RolesUpdate, request: Request,
                 admin: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(AuthUser, user_id)
    if not user:
        raise HTTPException(404, detail={"code": "not_found", "message": "User not found."})
    bad = [r for r in body.roles if r not in VALID_ROLES]
    if bad:
        raise HTTPException(422, detail={"code": "invalid_role", "message": f"Unknown roles: {bad}"})
    if user.id == admin.id and "admin" not in body.roles:
        raise HTTPException(409, detail={"code": "self_demotion", "message": "Cannot remove your own admin role."})
    before = user.role_names
    user.roles = svc.ensure_roles(db, body.roles)
    audit(db, "role_change", client_info(request), user, by=str(admin.id), before=before, after=sorted(body.roles))
    db.commit()
    return svc._user_out(user) | {"id": str(user.id)}


@router.post("/auth/admin/users/{user_id}/unlock")
def unlock(user_id: uuid.UUID, request: Request, admin: AuthUser = Depends(require_admin),
           db: Session = Depends(get_db)):
    user = db.get(AuthUser, user_id)
    if not user:
        raise HTTPException(404, detail={"code": "not_found", "message": "User not found."})
    user.failed_attempts = 0
    user.locked_until = None
    audit(db, "account_unlocked", client_info(request), user, by=str(admin.id))
    db.commit()
    return {"status": "unlocked"}


@router.post("/auth/admin/users/{user_id}/deactivate")
def deactivate(user_id: uuid.UUID, request: Request, admin: AuthUser = Depends(require_admin),
               db: Session = Depends(get_db)):
    user = db.get(AuthUser, user_id)
    if not user or user.id == admin.id:
        raise HTTPException(409, detail={"code": "invalid", "message": "Cannot deactivate this user."})
    user.is_active = False
    for sess in svc.list_sessions(db, user.id):
        svc._revoke_session(db, sess, "deactivated")
    audit(db, "user_deactivated", client_info(request), user, by=str(admin.id))
    db.commit()
    return {"status": "deactivated"}


@router.get("/auth/admin/audit", response_model=list[AuditOut])
def auth_audit(limit: int = 200, _: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(AuthAuditEvent).order_by(AuthAuditEvent.ts.desc()).limit(min(limit, 1000))
    return list(db.scalars(q))


# ----- Internal (service-to-service) -----

@router.put("/auth/internal/users/{user_id}/authority", dependencies=[Depends(require_internal)])
def push_authority(user_id: uuid.UUID, body: AuthorityUpdate, request: Request, db: Session = Depends(get_db)):
    """core-api pushes maker-checker approved authority; it becomes a token claim on next refresh."""
    user = db.get(AuthUser, user_id)
    if not user:
        raise HTTPException(404, detail={"code": "not_found", "message": "User not found."})
    user.authority = body.authority
    audit(db, "authority_updated", client_info(request), user, entries=len(body.authority))
    db.commit()
    return {"status": "updated"}

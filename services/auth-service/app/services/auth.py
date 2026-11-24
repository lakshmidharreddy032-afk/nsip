"""Authentication domain logic: login, lockout, MFA, sessions, refresh rotation with reuse detection."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyotp
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.models import (
    AuthAuditEvent,
    AuthRole,
    AuthSession,
    AuthUser,
    MfaChallenge,
    PasswordResetToken,
    RefreshToken,
    utcnow,
)


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 401, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class ClientInfo:
    ip: str = ""
    user_agent: str = ""


def audit(db: Session, event: str, client: ClientInfo, user: AuthUser | None = None, email: str = "",
          **detail) -> None:
    db.add(
        AuthAuditEvent(
            event=event,
            user_id=user.id if user else None,
            email=(user.email if user else email)[:320],
            ip=client.ip,
            user_agent=client.user_agent[:400],
            detail=detail,
        )
    )


def requires_mfa(user: AuthUser) -> bool:
    return any(r in get_settings().mfa_required_roles for r in user.role_names)


def get_user_by_email(db: Session, email: str) -> AuthUser | None:
    return db.scalar(select(AuthUser).where(AuthUser.email == email.strip().lower()))


def _lockout_seconds(failed: int) -> int:
    s = get_settings()
    over = failed - s.lockout_threshold
    return int(min(s.lockout_base_seconds * (2**over), s.lockout_max_seconds))


def authenticate_password(db: Session, email: str, password: str, client: ClientInfo) -> AuthUser:
    user = get_user_by_email(db, email)
    now = utcnow()
    if user and user.locked_until and aware(user.locked_until) > now:  # type: ignore[operator]
        retry = int((aware(user.locked_until) - now).total_seconds()) + 1  # type: ignore[operator]
        security.verify_password(None, password)  # equalise timing
        audit(db, "login_blocked_locked", client, user)
        db.commit()
        raise AuthError("account_locked", "Account temporarily locked. Try again later.", 423, retry)
    valid = security.verify_password(user.password_hash if user else None, password)
    if not user or not valid or not user.is_active:
        if user:
            user.failed_attempts += 1
            if user.failed_attempts >= get_settings().lockout_threshold:
                user.locked_until = now + timedelta(seconds=_lockout_seconds(user.failed_attempts))
                audit(db, "account_locked", client, user, failed_attempts=user.failed_attempts)
        audit(db, "login_failure", client, user, email=email, reason="invalid_credentials")
        db.commit()
        raise AuthError("invalid_credentials", "Email or password is incorrect.")
    user.failed_attempts = 0
    user.locked_until = None
    return user


def start_mfa(db: Session, user: AuthUser, client: ClientInfo) -> dict:
    s = get_settings()
    token = security.new_opaque_token()
    challenge = MfaChallenge(
        user_id=user.id,
        token_hash=security.token_hash(token),
        purpose="login" if user.mfa_enabled else "enroll",
        expires_at=utcnow() + timedelta(seconds=s.mfa_challenge_ttl_seconds),
    )
    result: dict = {"mfa_token": token}
    if not user.mfa_enabled:
        secret = security.new_totp_secret()
        challenge.pending_secret_enc = security.encrypt_secret(secret)
        result["secret"] = secret
        result["otpauth_uri"] = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Northstar NSIP")
        result["status"] = "mfa_enroll_required"
    else:
        result["status"] = "mfa_required"
    db.add(challenge)
    audit(db, "mfa_challenge_issued", client, user, purpose=challenge.purpose)
    db.commit()
    return result


def verify_mfa(db: Session, mfa_token: str, code: str, client: ClientInfo) -> AuthUser:
    ch = db.scalar(select(MfaChallenge).where(MfaChallenge.token_hash == security.token_hash(mfa_token)))
    if not ch or ch.used_at or aware(ch.expires_at) < utcnow() or ch.attempts >= 5:  # type: ignore[operator]
        raise AuthError("mfa_expired", "Verification expired. Please sign in again.")
    user = db.get(AuthUser, ch.user_id)
    assert user is not None
    ch.attempts += 1
    secret_enc = ch.pending_secret_enc if ch.purpose == "enroll" else user.mfa_secret_enc
    if not secret_enc:
        raise AuthError("mfa_not_configured", "MFA is not configured.")
    step = security.verify_totp(security.decrypt_secret(secret_enc), code, user.mfa_last_step)
    if step is None:
        audit(db, "mfa_failure", client, user, attempts=ch.attempts)
        db.commit()
        raise AuthError("invalid_code", "The code is incorrect or has already been used.")
    ch.used_at = utcnow()
    user.mfa_last_step = step
    if ch.purpose == "enroll":
        user.mfa_enabled = True
        user.mfa_secret_enc = ch.pending_secret_enc
        audit(db, "mfa_enrolled", client, user)
    audit(db, "mfa_success", client, user)
    return user


def _user_out(user: AuthUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "region": user.region,
        "roles": user.role_names,
        "mfa_enabled": user.mfa_enabled,
        "is_active": user.is_active,
        "locked": bool(user.locked_until and aware(user.locked_until) > utcnow()),  # type: ignore[operator]
    }


def _access_for(user: AuthUser, sess: AuthSession) -> tuple[str, int]:
    return security.issue_access_token(
        user_id=str(user.id),
        email=user.email,
        name=user.full_name,
        roles=user.role_names,
        region=user.region,
        authority=user.authority or [],
        session_id=str(sess.id),
        mfa=sess.mfa_verified,
        amr=sess.amr or ["pwd"],
    )


def _new_refresh(db: Session, user: AuthUser, sess: AuthSession, family: uuid.UUID,
                 parent: uuid.UUID | None) -> str:
    raw = security.new_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            session_id=sess.id,
            family_id=family,
            parent_id=parent,
            token_hash=security.token_hash(raw),
            expires_at=utcnow() + timedelta(seconds=get_settings().refresh_ttl_seconds),
        )
    )
    return raw


def create_session(db: Session, user: AuthUser, client: ClientInfo, mfa: bool, amr: list[str]) -> dict:
    sess = AuthSession(user_id=user.id, ip=client.ip, user_agent=client.user_agent[:400],
                       mfa_verified=mfa, amr=amr)
    db.add(sess)
    db.flush()
    refresh = _new_refresh(db, user, sess, uuid.uuid4(), None)
    user.last_login_at = utcnow()
    access, ttl = _access_for(user, sess)
    audit(db, "login_success", client, user, session_id=str(sess.id), amr=amr)
    db.commit()
    return {"access_token": access, "expires_in": ttl, "refresh_token": refresh, "user": _user_out(user),
            "session_id": str(sess.id)}


def _revoke_session(db: Session, sess: AuthSession, reason: str) -> None:
    now = utcnow()
    sess.revoked_at = sess.revoked_at or now
    sess.revoked_reason = sess.revoked_reason or reason
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id == sess.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def rotate_refresh(db: Session, raw: str, client: ClientInfo) -> dict:
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == security.token_hash(raw)))
    if not rt:
        raise AuthError("invalid_refresh", "Session expired.")
    sess = db.get(AuthSession, rt.session_id)
    user = db.get(AuthUser, rt.user_id)
    assert sess is not None and user is not None
    if rt.used_at or rt.revoked_at:
        # Reuse of a rotated or revoked token: assume theft, kill the whole family and session.
        db.execute(update(RefreshToken).where(RefreshToken.family_id == rt.family_id).values(revoked_at=utcnow()))
        _revoke_session(db, sess, "refresh_reuse_detected")
        audit(db, "refresh_reuse_detected", client, user, session_id=str(sess.id), family=str(rt.family_id))
        db.commit()
        raise AuthError("refresh_reuse", "Session ended for security reasons. Please sign in again.")
    if aware(rt.expires_at) < utcnow() or sess.revoked_at or not user.is_active:  # type: ignore[operator]
        raise AuthError("invalid_refresh", "Session expired.")
    rt.used_at = utcnow()
    new_raw = _new_refresh(db, user, sess, rt.family_id, rt.id)
    sess.last_seen_at = utcnow()
    access, ttl = _access_for(user, sess)
    audit(db, "token_refreshed", client, user, session_id=str(sess.id))
    db.commit()
    return {"access_token": access, "expires_in": ttl, "refresh_token": new_raw, "user": _user_out(user)}


def logout(db: Session, raw: str | None, client: ClientInfo) -> None:
    if not raw:
        return
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == security.token_hash(raw)))
    if rt:
        sess = db.get(AuthSession, rt.session_id)
        user = db.get(AuthUser, rt.user_id)
        if sess:
            _revoke_session(db, sess, "logout")
        audit(db, "logout", client, user)
        db.commit()


def list_sessions(db: Session, user_id: uuid.UUID) -> list[AuthSession]:
    return list(
        db.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.last_seen_at.desc())
        )
    )


def revoke_session(db: Session, user: AuthUser, session_id: uuid.UUID, client: ClientInfo) -> None:
    sess = db.get(AuthSession, session_id)
    if not sess or sess.user_id != user.id:
        raise AuthError("not_found", "Session not found.", 404)
    _revoke_session(db, sess, "remote_sign_out")
    audit(db, "session_revoked", client, user, session_id=str(session_id))
    db.commit()


def request_password_reset(db: Session, email: str, client: ClientInfo) -> str | None:
    """Always behaves the same externally. Returns the token only for tests/outbox delivery."""
    user = get_user_by_email(db, email)
    if not user or not user.is_active:
        audit(db, "password_reset_requested_unknown", client, email=email)
        db.commit()
        return None
    s = get_settings()
    rec = PasswordResetToken(user_id=user.id, expires_at=utcnow() + timedelta(seconds=s.reset_token_ttl_seconds))
    db.add(rec)
    db.flush()
    token = security.sign_reset_token(str(rec.id), str(user.id), s.reset_token_ttl_seconds)
    outbox = Path(s.mail_outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    link = f"{s.app_base_url}/login/reset-password?token={token}"
    (outbox / f"reset-{rec.id}.json").write_text(
        json.dumps({"to": user.email, "subject": "Reset your NSIP password", "link": link})
    )
    audit(db, "password_reset_requested", client, user)
    db.commit()
    return token


def reset_password(db: Session, token: str, new_password: str, client: ClientInfo) -> None:
    data = security.verify_reset_token(token)
    if not data:
        raise AuthError("invalid_token", "This reset link is invalid or has expired.", 400)
    rec = db.get(PasswordResetToken, uuid.UUID(data["tid"]))
    if not rec or rec.used_at or str(rec.user_id) != data["uid"]:
        raise AuthError("invalid_token", "This reset link is invalid or has expired.", 400)
    user = db.get(AuthUser, rec.user_id)
    assert user is not None
    problems = security.validate_password_policy(new_password, user.email)
    if problems:
        raise AuthError("weak_password", " ".join(problems), 400)
    rec.used_at = utcnow()
    user.password_hash = security.hash_password(new_password)
    user.password_changed_at = utcnow()
    user.failed_attempts = 0
    user.locked_until = None
    for sess in list_sessions(db, user.id):
        _revoke_session(db, sess, "password_reset")
    audit(db, "password_reset_completed", client, user)
    db.commit()


def ensure_roles(db: Session, names: list[str]) -> list[AuthRole]:
    roles = []
    for n in names:
        role = db.scalar(select(AuthRole).where(AuthRole.name == n))
        if not role:
            role = AuthRole(name=n)
            db.add(role)
            db.flush()
        roles.append(role)
    return roles


VALID_ROLES = ["data_entry", "underwriter", "senior_underwriter", "risk_engineer", "cuo", "distribution", "admin"]

from __future__ import annotations

import hmac
import time
import uuid
from collections import defaultdict, deque

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import AuthSession, AuthUser
from app.services.auth import ClientInfo


def client_info(request: Request) -> ClientInfo:
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    return ClientInfo(ip=ip, user_agent=request.headers.get("user-agent", "")[:400])


class RateLimiter:
    """Sliding-window limiter keyed by IP. Redis-backed variant is used when replicas > 1 (see ADR-0009)."""

    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, detail={"code": "rate_limited", "message": "Too many attempts."},
                                headers={"Retry-After": str(int(window))})
        q.append(now)


login_limiter = RateLimiter()


def rate_limit_login(request: Request) -> None:
    login_limiter.check(client_info(request).ip or "unknown", get_settings().login_rate_limit_per_minute)


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail={"code": "unauthenticated", "message": "Sign in required."})
    try:
        claims = decode_access_token(authorization.split(" ", 1)[1])
    except jwt.PyJWTError:
        raise HTTPException(401, detail={"code": "invalid_token", "message": "Invalid or expired token."})
    user = db.get(AuthUser, uuid.UUID(claims["sub"]))
    sess = db.get(AuthSession, uuid.UUID(claims["sid"]))
    if not user or not user.is_active or not sess or sess.revoked_at:
        raise HTTPException(401, detail={"code": "session_revoked", "message": "Session ended."})
    user._claims = claims  # type: ignore[attr-defined]
    return user


def require_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    if "admin" not in user.role_names:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Admin role required."})
    return user


def require_internal(x_internal_token: str | None = Header(default=None)) -> None:
    expected = get_settings().internal_service_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(401, detail={"code": "unauthenticated", "message": "Service token required."})


def check_csrf(request: Request) -> None:
    """Double-submit cookie check for cookie-authenticated endpoints (refresh, logout)."""
    s = get_settings()
    cookie = request.cookies.get(s.csrf_cookie_name)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(403, detail={"code": "csrf", "message": "CSRF validation failed."})

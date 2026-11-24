from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import HumanActor, Principal, TokenError, get_verifier, make_human_actor
from app.models import Role, User, UserRole


def _sync_projection(db: Session, p: Principal) -> None:
    """Just-in-time projection of the identity into core-api (no credentials)."""
    user = db.get(User, p.user_id)
    if user is None:
        user = User(id=p.user_id, email=p.email, full_name=p.name, region=p.region)
        db.add(user)
    else:
        user.full_name, user.region = p.name, p.region
    existing = {r.name: r for r in db.scalars(select(Role))}
    current = set(db.scalars(select(Role.name).join(UserRole, UserRole.role_id == Role.id)
                             .where(UserRole.user_id == p.user_id)))
    if current != set(p.roles):
        db.query(UserRole).filter(UserRole.user_id == p.user_id).delete()
        db.flush()
        for name in p.roles:
            role = existing.get(name) or Role(name=name)
            if name not in existing:
                db.add(role)
                db.flush()
                existing[name] = role
            db.add(UserRole(user_id=p.user_id, role_id=role.id))
    db.commit()


_seen: set[tuple] = set()


def get_principal(request: Request, authorization: str | None = Header(default=None),
                  db: Session = Depends(get_db)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail={"code": "unauthenticated", "message": "Sign in required."})
    try:
        claims = get_verifier().verify(authorization.split(" ", 1)[1])
    except TokenError:
        raise HTTPException(401, detail={"code": "invalid_token", "message": "Invalid or expired token."})
    p = Principal.from_claims(claims)
    key = (p.user_id, p.name, p.region, tuple(sorted(p.roles)))
    if key not in _seen:
        _sync_projection(db, p)
        _seen.add(key)
    request.state.principal = p
    return p


def require_roles(*roles: str) -> Callable[..., Principal]:
    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if not p.has(*roles):
            raise HTTPException(403, detail={"code": "forbidden", "message": "You do not have permission."})
        return p
    return dep


def get_human_actor(request: Request, p: Principal = Depends(get_principal)) -> HumanActor:
    rid = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    ip = request.client.host if request.client else ""
    return make_human_actor(p, rid, ip)


# Role groups used by routers
VIEW_SUBMISSIONS = ("data_entry", "underwriter", "senior_underwriter", "risk_engineer", "cuo", "admin")
EDIT_FIELDS = ("data_entry", "underwriter", "senior_underwriter")
UNDERWRITE = ("underwriter", "senior_underwriter")

"""Seed demo users for every role. Development and demo use only; secrets are published in README."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import Base, SessionLocal, engine
from app.core.security import encrypt_secret, hash_password
from app.models import AuthUser
from app.services.auth import ensure_roles

NS = uuid.UUID("6f1c2a52-3c1e-4c55-9d1e-8a2b6c0d4e11")
DEMO_PASSWORD = "Northstar@2026!"
# Base32 TOTP secrets for demo accounts so MFA can be exercised in e2e tests.
DEMO_TOTP = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

DEMO_USERS = [
    ("dataentry@northstar.example", "Priya Kulkarni", "west", ["data_entry"]),
    ("underwriter@northstar.example", "Arjun Mehta", "west", ["underwriter"]),
    ("underwriter.south@northstar.example", "Kavya Iyer", "south", ["underwriter"]),
    ("senior.uw@northstar.example", "Rohan Desai", "west", ["senior_underwriter"]),
    ("risk.engineer@northstar.example", "Neha Rao", "west", ["risk_engineer"]),
    ("cuo@northstar.example", "Chief Underwriting Officer", "all", ["cuo"]),
    ("distribution@northstar.example", "Sameer Kapoor", "west", ["distribution"]),
    ("admin@northstar.example", "Platform Admin", "all", ["admin"]),
]


def user_id_for(email: str) -> uuid.UUID:
    """Deterministic IDs so the core-api seed links users without sharing a database."""
    return uuid.uuid5(NS, email)


def seed(create_schema: bool = True) -> int:
    if create_schema:
        Base.metadata.create_all(engine)
    created = 0
    with SessionLocal() as db:
        for email, name, region, roles in DEMO_USERS:
            if db.scalar(select(AuthUser).where(AuthUser.email == email)):
                continue
            mfa = any(r in ("underwriter", "senior_underwriter", "cuo", "admin") for r in roles)
            u = AuthUser(id=user_id_for(email), email=email, full_name=name, region=region,
                         password_hash=hash_password(DEMO_PASSWORD), mfa_enabled=mfa,
                         mfa_secret_enc=encrypt_secret(DEMO_TOTP) if mfa else None)
            u.roles = ensure_roles(db, roles)
            db.add(u)
            created += 1
        db.commit()
    return created


if __name__ == "__main__":
    print(f"seeded {seed()} users")

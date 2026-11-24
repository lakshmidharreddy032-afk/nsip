"""Seed demo users (every role), authority matrix, appetite rules and reference data, and optionally
load the synthetic mailbox so `docker compose up` starts with realistic work in the queues.

    python scripts/seed.py               # users, authority, rules, brokers
    python scripts/seed.py --with-data   # also generate + process 300 synthetic submissions

Run inside the compose network (core-api and auth-service images both contain this script's deps).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (email, line -> (max SI, max premium, regions))
AUTHORITY = {
    "underwriter@northstar.example": {"package": (10_00_00_000, 5_00_000, ["west"]),
                                      "property": (25_00_00_000, 10_00_000, ["west"])},
    "underwriter.south@northstar.example": {"package": (10_00_00_000, 5_00_000, ["south"]),
                                            "property": (25_00_00_000, 10_00_000, ["south"])},
    "senior.uw@northstar.example": {"package": (50_00_00_000, 25_00_000, ["all"]),
                                    "property": (250_00_00_000, 1_00_00_000, ["all"])},
}


def demo_users() -> dict:
    """Read the demo user list and ID namespace from the auth seed without importing the auth app."""
    import ast
    import uuid

    tree = ast.parse((ROOT / "services/auth-service/app/seed.py").read_text(encoding="utf-8"))
    vals: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "DEMO_USERS":
                vals[name] = ast.literal_eval(node.value)
            elif name == "NS":
                vals[name] = uuid.UUID(ast.literal_eval(node.value.args[0]))  # type: ignore[attr-defined]
    namespace = vals["NS"]
    return {"DEMO_USERS": vals["DEMO_USERS"], "user_id_for": lambda email: uuid.uuid5(namespace, email)}


def seed_auth() -> None:
    sys.path.insert(0, str(ROOT / "services" / "auth-service"))
    from app.seed import seed  # type: ignore[import-not-found]

    print(f"auth-service: seeded {seed()} users")
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    sys.path.pop(0)


def seed_core(with_data: bool) -> None:
    sys.path.insert(0, str(ROOT / "services" / "core-api"))
    from app.bootstrap import bootstrap
    from app.core.db import Base, SessionLocal, engine
    from app.core.security import Principal
    from app.domain.authority import service as authority
    from app.models import AuthorityLimit, Role, User, UserRole
    from sqlalchemy import select

    ns = demo_users()

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        bootstrap(db)
        for email, name, region, roles in ns["DEMO_USERS"]:
            uid = ns["user_id_for"](email)
            if db.get(User, uid) is None:
                db.add(User(id=uid, email=email, full_name=name, region=region))
                db.flush()
                for r in roles:
                    role = db.scalar(select(Role).where(Role.name == r)) or Role(name=r)
                    db.add(role)
                    db.flush()
                    db.add(UserRole(user_id=uid, role_id=role.id))
        db.commit()
        admin = Principal(ns["user_id_for"]("admin@northstar.example"), "admin", "Admin", frozenset({"admin"}), "all")
        cuo = Principal(ns["user_id_for"]("cuo@northstar.example"), "cuo", "CUO", frozenset({"cuo"}), "all")
        for email, lines in AUTHORITY.items():
            uid = ns["user_id_for"](email)
            for line, (si, prem, regions) in lines.items():
                if db.scalar(select(AuthorityLimit).where(AuthorityLimit.user_id == uid, AuthorityLimit.line == line,
                                                          AuthorityLimit.status == "approved")):
                    continue
                lim = authority.propose(db, admin, user_id=uid, line=line, max_sum_insured=si, max_premium=prem,
                                        regions=regions, reason="Pilot authority matrix (seed)")
                authority.decide(db, cuo, lim.id, True, "seed approval")
        print("core-api: reference data, users and authority seeded")
        if with_data:
            data = Path(os.environ.get("SEED_DATA_DIR", str(ROOT / "eval" / "datasets" / "demo")))
            if not (data / "labels.jsonl").exists():
                subprocess.run([sys.executable, str(ROOT / "eval/synthetic/generate.py"), "--out", str(data),  # noqa: S603
                                "--count", "300"], check=True)
            mailbox = Path(os.environ.get("NSIP_MAILBOX_DIR", "./var/mailbox"))
            shutil.copytree(data / "mailbox", mailbox, dirs_exist_ok=True)
            from app.domain.submissions.pipeline import poll_mailboxes

            print("core-api: processing synthetic mailbox", poll_mailboxes(db))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-data", action="store_true")
    ap.add_argument("--only", choices=["auth", "core"], default=None)
    a = ap.parse_args()
    if a.only in (None, "auth"):
        seed_auth()
    if a.only in (None, "core"):
        seed_core(a.with_data)

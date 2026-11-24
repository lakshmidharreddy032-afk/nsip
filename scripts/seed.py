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

def demo_users() -> dict:
    """Read the demo user list and ID namespace from the auth seed without importing the auth app."""
    import ast
    import uuid

    tree = ast.parse((ROOT / "services/auth-service/app/seed.py").read_text(encoding="utf-8"))
    vals: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("DEMO_USERS", "DEMO_AUTHORITY"):
                vals[name] = ast.literal_eval(node.value)
            elif name == "NS":
                vals[name] = uuid.UUID(ast.literal_eval(node.value.args[0]))  # type: ignore[attr-defined]
    namespace = vals["NS"]
    return {"DEMO_USERS": vals["DEMO_USERS"], "DEMO_AUTHORITY": vals["DEMO_AUTHORITY"],
            "user_id_for": lambda email: uuid.uuid5(namespace, email),
            "limit_id_for": lambda email, line: uuid.uuid5(namespace, f"authority:{email}:{line}")}


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
    from app.domain.audit import service as audit
    from app.models import AuthorityLimit, Role, User, UserRole, utcnow
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
        admin_id = ns["user_id_for"]("admin@northstar.example")
        cuo_id = ns["user_id_for"]("cuo@northstar.example")
        for email, lines in ns["DEMO_AUTHORITY"].items():
            uid = ns["user_id_for"](email)
            for line, (si, prem, regions) in lines.items():
                lid = ns["limit_id_for"](email, line)
                if db.get(AuthorityLimit, lid):
                    continue
                # Seeded as already maker-checker approved (admin proposed, CUO approved), with the same
                # deterministic IDs the auth-service seed places in token claims.
                db.add(AuthorityLimit(id=lid, user_id=uid, line=line, max_sum_insured=si, max_premium=prem,
                                      regions=regions, status="approved", version=1, maker_id=admin_id,
                                      checker_id=cuo_id, approved_at=utcnow(), reason="Pilot authority matrix (seed)"))
                db.flush()
                audit.record(db, action="authority.seeded", entity_type="authority_limit", entity_id=lid,
                             actor_type="system", data={"user": email, "line": line, "maker": str(admin_id),
                                                        "checker": str(cuo_id)})
        db.commit()
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

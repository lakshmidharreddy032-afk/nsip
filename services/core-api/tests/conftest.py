import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="nsip-core-test-"))
os.environ.update({
    "NSIP_DATABASE_URL": f"sqlite:///{(_TMP / 'core.db').as_posix()}",
    "NSIP_OBJECT_STORE_DIR": str(_TMP / "objects"), "NSIP_MAILBOX_DIR": str(_TMP / "mailbox"),
    "NSIP_OUTBOX_DIR": str(_TMP / "outbox"), "NSIP_AI_GATEWAY_MODE": "inprocess", "NSIP_AI_GATEWAY_RETRIES": "1",
    "NSIP_AUTH_SERVICE_URL": "http://127.0.0.1:9", "NSIP_RATE_LIMIT_PER_MINUTE": "100000",
})
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "eval" / "synthetic"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.adapters.registry import set_adapters  # noqa: E402
from app.bootstrap import bootstrap  # noqa: E402
from app.core import deps  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import JWKSVerifier, set_verifier  # noqa: E402
from app.models import FeatureFlag  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
_JWK = jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True) | {"kid": "test", "alg": "RS256"}
_verifier = JWKSVerifier("http://127.0.0.1:9/jwks", "https://auth.nsip.local", "nsip-core-api", ttl=10**9)
_verifier.load_jwks({"keys": [_JWK]})
set_verifier(_verifier)

USERS = {
    "data_entry": (uuid.UUID(int=1), "west", ["data_entry"]),
    "underwriter": (uuid.UUID(int=2), "west", ["underwriter"]),
    "senior": (uuid.UUID(int=3), "all", ["senior_underwriter"]),
    "risk_engineer": (uuid.UUID(int=4), "west", ["risk_engineer"]),
    "cuo": (uuid.UUID(int=5), "all", ["cuo"]),
    "distribution": (uuid.UUID(int=6), "west", ["distribution"]),
    "admin": (uuid.UUID(int=7), "all", ["admin"]),
    "uw_south": (uuid.UUID(int=8), "south", ["underwriter"]),
}


def make_token(who: str, mfa: bool = True, authority: list | None = None, exp: int = 900) -> str:
    uid, region, roles = USERS[who]
    now = int(time.time())
    claims = {"iss": "https://auth.nsip.local", "aud": "nsip-core-api", "sub": str(uid), "email": f"{who}@t.example",
              "name": who, "roles": roles, "region": region, "authority": authority or [], "sid": "s1",
              "mfa": mfa, "iat": now, "exp": now + exp}
    return jwt.encode(claims, _PEM, algorithm="RS256", headers={"kid": "test"})


def headers(who: str, **kw) -> dict:
    return {"Authorization": f"Bearer {make_token(who, **kw)}"}


@pytest.fixture(scope="session")
def dataset():
    from generate import generate

    out = _TMP / "dataset"
    out.mkdir(exist_ok=True)
    generate(out, count=60, seed=11)
    return out


def reset_db():
    deps._seen.clear()
    set_adapters(None)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        bootstrap(db)
        for f in db.query(FeatureFlag).filter(FeatureFlag.key.like("region.%")):
            f.enabled = True
        db.commit()


@pytest.fixture
def db():
    reset_db()
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def load_mailbox(dataset: Path):
    dest = Path(os.environ["NSIP_MAILBOX_DIR"])
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(dataset / "mailbox", dest)


@pytest.fixture(scope="module")
def processed(dataset):
    """A database with the small synthetic dataset fully processed (module-scoped for speed)."""
    reset_db()
    load_mailbox(dataset)
    from app.domain.submissions.pipeline import poll_mailboxes

    with SessionLocal() as s:
        stats = poll_mailboxes(s)
    return stats


def grant_authority(db, who: str, max_si=10_000_000_000, max_premium=50_000_000, regions=("all",)) -> list[dict]:
    from app.core.security import Principal
    from app.domain.authority import service as authority
    from app.models import User

    uid, region, roles = USERS[who]
    if db.get(User, uid) is None:
        db.add(User(id=uid, email=f"{who}@t.example", full_name=who, region=region))
        db.commit()
    maker = Principal(USERS["admin"][0], "a", "admin", frozenset({"admin"}), "all")
    checker = Principal(USERS["cuo"][0], "c", "cuo", frozenset({"cuo"}), "all")
    out = []
    for line in ("package", "property"):
        lim = authority.propose(db, maker, user_id=uid, line=line, max_sum_insured=max_si, max_premium=max_premium,
                                regions=list(regions), reason="test grant")
        out.append(authority.limit_claim(authority.decide(db, checker, lim.id, True)))
    return out

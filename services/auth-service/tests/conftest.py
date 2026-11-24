import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="nsip-auth-test-")
os.environ.setdefault("AUTH_DATABASE_URL", f"sqlite:///{_tmp}/auth.db")
os.environ.setdefault("AUTH_KEY_DIR", f"{_tmp}/keys")
os.environ.setdefault("AUTH_MAIL_OUTBOX_DIR", f"{_tmp}/outbox")
os.environ.setdefault("AUTH_COOKIE_SECURE", "false")
os.environ.setdefault("AUTH_LOGIN_RATE_LIMIT_PER_MINUTE", "1000")

import pyotp  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEMO_PASSWORD, DEMO_TOTP, seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed(create_schema=False)
    yield


@pytest.fixture
def client():
    return TestClient(app, base_url="http://testserver")


@pytest.fixture
def password():
    return DEMO_PASSWORD


def totp_code(offset_steps: int = 0) -> str:
    import time

    return pyotp.TOTP(DEMO_TOTP).at(int(time.time()) + 30 * offset_steps)


def login_full(client, email: str, password: str = DEMO_PASSWORD) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    if body["status"] == "mfa_required":
        r = client.post("/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": totp_code()})
        assert r.status_code == 200, r.text
        body = r.json()
    return body["token"]

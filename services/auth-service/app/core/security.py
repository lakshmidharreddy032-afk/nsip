"""Password hashing (Argon2id), TOTP, token hashing, signed reset tokens and JWT issuance."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from functools import lru_cache
from pathlib import Path

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.keys import current_key

# Argon2id with parameters above the OWASP minimum (m=19 MiB, t=2, p=1).
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalisation")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification; an unknown user still costs one Argon2 verification."""
    try:
        ok = _hasher.verify(password_hash or _DUMMY_HASH, password)
        return bool(ok and password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_password_policy(password: str, email: str) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("Password must be at least 12 characters.")
    local = email.split("@")[0].lower() if email else ""
    if local and len(local) >= 3 and local in password.lower():
        problems.append("Password must not contain your email name.")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        problems.append("Use at least three of: lowercase, uppercase, digits, symbols.")
    return problems


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.data_key:
        return Fernet(s.data_key.encode())
    path = Path(s.key_dir) / "data.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
    return Fernet(path.read_bytes())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str, last_step: int | None) -> int | None:
    """Return the accepted time-step, or None. Rejects replay of an already-used step."""
    if not code or not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset in (-1, 0, 1):
        step = (now // 30) + offset
        if hmac.compare_digest(totp.at(step * 30), code):
            if last_step is not None and step <= last_step:
                return None
            return step
    return None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_reset_token(token_id: str, user_id: str, ttl: int) -> str:
    payload = _b64(json.dumps({"tid": token_id, "uid": user_id, "exp": int(time.time()) + ttl}).encode())
    sig = hmac.new(get_settings().reset_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(sig)}"


def verify_reset_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".", 1)
        expected = hmac.new(get_settings().reset_secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig)):
            return None
        data = json.loads(_unb64(payload))
        if data["exp"] < time.time():
            return None
        return data
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def issue_access_token(
    *,
    user_id: str,
    email: str,
    name: str,
    roles: list[str],
    region: str,
    authority: list[dict],
    session_id: str,
    mfa: bool,
    amr: list[str],
) -> tuple[str, int]:
    s = get_settings()
    key = current_key()
    now = int(time.time())
    claims = {
        "iss": s.issuer,
        "aud": s.audience,
        "sub": user_id,
        "email": email,
        "name": name,
        "roles": roles,
        "region": region,
        "authority": authority,
        "sid": session_id,
        "mfa": mfa,
        "amr": amr,
        "iat": now,
        "nbf": now,
        "exp": now + s.access_ttl_seconds,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, key.private_pem, algorithm="RS256", headers={"kid": key.kid})
    return token, s.access_ttl_seconds


def decode_access_token(token: str) -> dict:
    s = get_settings()
    public = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(current_key().public_jwk))
    return jwt.decode(
        token, public, algorithms=["RS256"], audience=s.audience, issuer=s.issuer  # type: ignore[arg-type]
    )

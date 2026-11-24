"""RSA signing keys and JWKS publication. Other services verify tokens with the public JWKS only."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import get_settings


def _b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@dataclass
class SigningKey:
    kid: str
    private_pem: bytes
    public_jwk: dict


def _load_or_create(kid: str, key_dir: Path, allow_env: bool = True) -> SigningKey:
    key_dir.mkdir(parents=True, exist_ok=True)
    path = key_dir / f"{kid}.pem"
    env_pem = os.environ.get("AUTH_PRIVATE_KEY_PEM") if allow_env else None
    if env_pem:
        pem = env_pem.encode()
    elif path.exists():
        pem = path.read_bytes()
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        path.write_bytes(pem)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover
            pass
    private = serialization.load_pem_private_key(pem, password=None)
    pub = cast(rsa.RSAPublicKey, private.public_key()).public_numbers()
    jwk = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": _b64u(pub.n), "e": _b64u(pub.e)}
    return SigningKey(kid=kid, private_pem=pem, public_jwk=jwk)


@lru_cache
def current_key() -> SigningKey:
    s = get_settings()
    return _load_or_create(s.key_id, Path(s.key_dir))


def jwks() -> dict:
    """Publish the current key plus retired public keys kept for rotation overlap."""
    s = get_settings()
    keys = [current_key().public_jwk]
    retired_dir = Path(s.key_dir) / "retired"
    if retired_dir.exists():
        for p in sorted(retired_dir.glob("*.pem")):
            keys.append(_load_or_create(p.stem, retired_dir, allow_env=False).public_jwk)
    return {"keys": keys}

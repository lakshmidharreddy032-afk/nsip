"""Token verification against the auth-service JWKS, and the authenticated principal types.

`HumanActor` is the only actor type accepted by quote issuance. It can only be constructed here,
from a verified access token presented on an HTTP request (see `deps.get_human_actor`).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field

import httpx
import jwt

from app.core.config import get_settings

ALL_REGIONS_ROLES = {"cuo", "admin"}
UNDERWRITING_ROLES = {"underwriter", "senior_underwriter"}


class TokenError(Exception):
    pass


class JWKSVerifier:
    def __init__(self, jwks_url: str, issuer: str, audience: str, ttl: int = 300) -> None:
        self.jwks_url, self.issuer, self.audience, self.ttl = jwks_url, issuer, audience, ttl
        self._keys: dict[str, object] = {}
        self._fetched = 0.0
        self._lock = threading.Lock()

    def load_jwks(self, jwks: dict) -> None:
        self._keys = {k["kid"]: jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k)) for k in jwks["keys"]}
        self._fetched = time.time()

    def _refresh(self) -> None:
        with self._lock:
            r = httpx.get(self.jwks_url, timeout=5)
            r.raise_for_status()
            self.load_jwks(r.json())

    def verify(self, token: str) -> dict:
        try:
            kid = jwt.get_unverified_header(token).get("kid") or ""
        except jwt.PyJWTError as e:
            raise TokenError("malformed token") from e
        if kid not in self._keys or time.time() - self._fetched > self.ttl:
            try:
                self._refresh()
            except httpx.HTTPError as e:
                if kid not in self._keys:
                    raise TokenError("cannot fetch signing keys") from e
        key = self._keys.get(kid)
        if key is None:
            raise TokenError("unknown signing key")
        try:
            return jwt.decode(token, key, algorithms=["RS256"], audience=self.audience,  # type: ignore[arg-type]
                              issuer=self.issuer, options={"require": ["exp", "iat", "sub", "sid"]})
        except jwt.PyJWTError as e:
            raise TokenError(str(e)) from e


_verifier: JWKSVerifier | None = None


def get_verifier() -> JWKSVerifier:
    global _verifier
    if _verifier is None:
        s = get_settings()
        _verifier = JWKSVerifier(s.auth_jwks_url, s.jwt_issuer, s.jwt_audience)
    return _verifier


def set_verifier(v: JWKSVerifier) -> None:
    global _verifier
    _verifier = v


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str
    name: str
    roles: frozenset[str]
    region: str
    authority: tuple[dict, ...] = field(default_factory=tuple)
    mfa: bool = False
    session_id: str = ""

    @classmethod
    def from_claims(cls, c: dict) -> Principal:
        return cls(user_id=uuid.UUID(c["sub"]), email=c.get("email", ""), name=c.get("name", ""),
                   roles=frozenset(c.get("roles", [])), region=c.get("region", ""),
                   authority=tuple(c.get("authority", [])), mfa=bool(c.get("mfa")), session_id=c.get("sid", ""))

    def has(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def all_regions(self) -> bool:
        return self.has(*ALL_REGIONS_ROLES) or self.region == "all"

    def can_see_region(self, region: str) -> bool:
        return self.all_regions or region == self.region


_ACTOR_SEAL = object()


class HumanActor:
    """A verified human acting through an authenticated HTTP request. Not constructible elsewhere."""

    __slots__ = ("principal", "request_id", "ip")

    def __init__(self, principal: Principal, request_id: str, ip: str, _seal: object = None) -> None:
        if _seal is not _ACTOR_SEAL:
            raise PermissionError("HumanActor can only be created from an authenticated request")
        self.principal = principal
        self.request_id = request_id
        self.ip = ip


def make_human_actor(principal: Principal, request_id: str, ip: str) -> HumanActor:
    return HumanActor(principal, request_id, ip, _seal=_ACTOR_SEAL)

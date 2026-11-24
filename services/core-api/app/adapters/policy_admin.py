"""Policy administration (vendor SaaS) adapter with an anti-corruption layer.

The vendor ships quarterly releases with limited quote APIs. All vendor-specific shapes live in
`VendorTranslator`; domain code only sees `PolicyAdminQuote`. The client pins an API version and is
covered by contract tests (tests/contract) so a release change fails CI, not production.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx

PINNED_API_VERSION = "2026.3"


@dataclass
class PolicyAdminQuote:
    submission_ref: str
    insured_name: str
    broker_code: str
    line: str
    sum_insured: int
    premium: Decimal
    rate_source: str
    rate_version: str
    inception_date: str | None
    underwriter_email: str
    locations: list[dict]


@dataclass
class PolicyAdminResult:
    quote_ref: str
    status: str
    vendor_version: str


class PolicyAdminAdapter(Protocol):
    def create_quote(self, q: PolicyAdminQuote, idempotency_key: str) -> PolicyAdminResult: ...


class VendorTranslator:
    """Maps between our model and the vendor's v2026.3 contract."""

    PRODUCT_CODES = {"property": "NSG-SFSP", "package": "NSG-SMEPKG"}

    @classmethod
    def to_vendor(cls, q: PolicyAdminQuote) -> dict:
        return {
            "apiVersion": PINNED_API_VERSION,
            "externalReference": q.submission_ref,
            "product": {"code": cls.PRODUCT_CODES[q.line]},
            "insuredParty": {"name": q.insured_name},
            "intermediary": {"code": q.broker_code},
            "riskObjects": [
                {"sequence": i + 1, "address": loc.get("address", ""), "postalCode": loc.get("pincode", ""),
                 "occupancyCode": loc.get("occupancy_code") or "UNSPECIFIED",
                 "sumInsured": {"value": int(loc.get("sum_insured", 0)), "currency": "INR"}}
                for i, loc in enumerate(q.locations)
            ],
            "totalSumInsured": {"value": q.sum_insured, "currency": "INR"},
            "premiumAmount": {"value": str(q.premium), "currency": "INR", "taxIncluded": False},
            "ratingBasis": {"source": q.rate_source, "tableVersion": q.rate_version},
            "proposedInception": q.inception_date,
            "createdBy": q.underwriter_email,
            "quoteStatus": "QUOTED",
        }

    @staticmethod
    def from_vendor(resp: dict) -> PolicyAdminResult:
        # v2026.3 returns quoteNumber; v2026.2 returned quote_id. Absorb both here, nowhere else.
        ref = resp.get("quoteNumber") or resp.get("quote_id")
        if not ref:
            raise ValueError("vendor response missing quote reference")
        return PolicyAdminResult(quote_ref=ref, status=resp.get("status", "QUOTED"),
                                 vendor_version=resp.get("apiVersion", PINNED_API_VERSION))


class MockPolicyAdmin:
    def __init__(self) -> None:
        self.created: dict[str, dict] = {}

    def create_quote(self, q: PolicyAdminQuote, idempotency_key: str) -> PolicyAdminResult:
        payload = VendorTranslator.to_vendor(q)
        if idempotency_key in self.created:
            return VendorTranslator.from_vendor(self.created[idempotency_key])
        resp = {"quoteNumber": f"PA-{uuid.uuid4().hex[:10].upper()}", "status": "QUOTED",
                "apiVersion": PINNED_API_VERSION, "echo": payload}
        self.created[idempotency_key] = resp
        return VendorTranslator.from_vendor(resp)


class LivePolicyAdmin:  # pragma: no cover
    def __init__(self, url: str, token_provider) -> None:
        self.url, self.token_provider = url, token_provider

    def create_quote(self, q: PolicyAdminQuote, idempotency_key: str) -> PolicyAdminResult:
        r = httpx.post(f"{self.url}/api/{PINNED_API_VERSION}/quotes", json=VendorTranslator.to_vendor(q),
                       headers={"Authorization": f"Bearer {self.token_provider()}",
                                "Idempotency-Key": idempotency_key}, timeout=30)
        r.raise_for_status()
        return VendorTranslator.from_vendor(r.json())

"""Contract tests pinned to the policy-admin v2026.3 schema and the filed rating API response."""
from decimal import Decimal

import jsonschema

from app.adapters.policy_admin import PINNED_API_VERSION, PolicyAdminQuote, VendorTranslator
from app.adapters.rating import PKG_FILING, PKG_VERSION, MockPackageRatingApi, RatingRequest

MONEY = {"type": "object", "required": ["value", "currency"],
         "properties": {"currency": {"const": "INR"}}}
POLICY_ADMIN_2026_3 = {
    "type": "object",
    "required": ["apiVersion", "externalReference", "product", "insuredParty", "intermediary", "riskObjects",
                 "totalSumInsured", "premiumAmount", "ratingBasis", "createdBy", "quoteStatus"],
    "properties": {
        "apiVersion": {"const": "2026.3"},
        "product": {"type": "object", "required": ["code"], "properties": {"code": {"enum": ["NSG-SFSP", "NSG-SMEPKG"]}}},
        "riskObjects": {"type": "array", "minItems": 1, "items": {"type": "object",
                                                                  "required": ["sequence", "postalCode", "sumInsured"]}},
        "totalSumInsured": MONEY,
        "premiumAmount": {**MONEY, "properties": {"value": {"type": "string", "pattern": r"^\d+(\.\d{1,2})?$"},
                                                  "currency": {"const": "INR"}}},
        "ratingBasis": {"type": "object", "required": ["source", "tableVersion"]},
        "quoteStatus": {"const": "QUOTED"},
    },
}


def test_policy_admin_payload_matches_pinned_contract():
    q = PolicyAdminQuote("NSIP-2026-000001", "Apex Ltd", "MIB001", "package", 50000000, Decimal("47520"),
                         "rating_api", PKG_VERSION, "2027-01-05", "uw@northstar.example",
                         [{"address": "Unit 1", "pincode": "411001", "occupancy_code": "OFFICE", "sum_insured": 50000000}])
    jsonschema.validate(VendorTranslator.to_vendor(q), POLICY_ADMIN_2026_3)
    assert PINNED_API_VERSION == "2026.3"


def test_vendor_response_versions():
    assert VendorTranslator.from_vendor({"quoteNumber": "Q1", "apiVersion": "2026.3"}).quote_ref == "Q1"
    assert VendorTranslator.from_vendor({"quote_id": "Q0"}).vendor_version == PINNED_API_VERSION


def test_rating_api_contract_fields():
    r = MockPackageRatingApi().rate(RatingRequest("package", 10_000_000, "low", "steel", "medium", 0, 500000))
    assert r.filing_ref == PKG_FILING and r.source_version == PKG_VERSION
    assert set(r.breakdown) >= {"base_rate_per_mille", "construction_factor", "cat_factor", "claims_factor",
                                "deductible_factor", "gst_18pct"}
    # 1cr * 0.45/1000 * 1.05 * 1.08 * 1 * 0.92 = 4694.76 -> min premium 7500
    assert r.premium == Decimal("7500")

"""Feature flags (region-by-region rollout, SSO, fast lane) and integration configuration."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FeatureFlag, IntegrationConfig

DEFAULT_FLAGS = [
    ("region.west", True, "Pilot region: West regional mailbox (phase 1)."),
    ("region.south", True, "South regional mailbox."),
    ("region.north", False, "North regional mailbox (phase 2)."),
    ("region.east", False, "East regional mailbox (phase 2)."),
    ("channel.broker_portal", True, "Read the 2023 broker portal as a secondary channel."),
    ("fast_lane.small_risk", True, "Small-risk fast lane (< Rs 2 lakh premium, single confirmation)."),
    ("auth.sso_oidc", False, "Azure AD single sign-on (configured in auth-service)."),
    ("ai.appetite_signals", True, "Request advisory hazard notes from the AI gateway (never used for routing)."),
]

DEFAULT_INTEGRATIONS = {
    "mailbox": {"adapter": "folder", "regions": {"west": "submissions.west@northstar.example",
                                                 "south": "submissions.south@northstar.example"}},
    "policy_admin": {"mode": "mock", "api_version": "2026.3"},
    "rating": {"package_api": "mock", "excel_service": "pycel-sandbox"},
    "geocoding": {"provider": "mock-geo", "cost_per_call_inr": 0.85},
    "cat_model": {"provider": "mock-cat", "cost_per_call_inr": 4.0},
    "budgets": {"geocoding_daily_calls": 3000, "cat_model_daily_calls": 1500, "monthly_budget_inr": 250000,
                "llm_monthly_budget_inr": 120000},
    "clearance": {"auto_threshold": 0.9, "review_threshold": 0.75, "bor_rule": "first_received"},
}


def seed_flags(db: Session) -> None:
    for key, enabled, desc in DEFAULT_FLAGS:
        if not db.scalar(select(FeatureFlag).where(FeatureFlag.key == key)):
            db.add(FeatureFlag(key=key, enabled=enabled, description=desc))
    for key, cfg in DEFAULT_INTEGRATIONS.items():
        if not db.scalar(select(IntegrationConfig).where(IntegrationConfig.key == key)):
            db.add(IntegrationConfig(key=key, config=cfg))
    db.flush()


def is_enabled(db: Session, key: str, default: bool = False) -> bool:
    f = db.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
    return f.enabled if f else default


def region_enabled(db: Session, region: str) -> bool:
    f = db.scalar(select(FeatureFlag).where(FeatureFlag.key == f"region.{region}"))
    return True if f is None else f.enabled

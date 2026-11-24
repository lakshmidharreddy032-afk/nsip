"""core-api configuration. Every external dependency is configurable and has a mock for dev/test."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NSIP_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "sqlite:///./var/core.db"
    redis_url: str | None = None
    tasks_eager: bool = True  # run pipeline inline (dev/test); Celery workers in compose/prod

    # Auth: tokens are verified against the auth-service JWKS; no shared secrets.
    auth_jwks_url: str = "http://localhost:8001/.well-known/jwks.json"
    auth_service_url: str = "http://localhost:8001"
    jwt_issuer: str = "https://auth.nsip.local"
    jwt_audience: str = "nsip-core-api"
    internal_service_token: str = "dev-internal-token"

    # AI gateway: the only route to any model. India-hosted in production.
    ai_gateway_url: str = Field(default="http://localhost:8090", validation_alias="AI_GATEWAY_URL")
    ai_gateway_mode: str = "http"  # http | inprocess (dev/test only: in-process mock transport)
    ai_gateway_timeout_s: float = 20.0
    ai_gateway_retries: int = 2
    ai_gateway_api_key: str = "dev-gateway-key"
    ai_cost_per_1k_input_inr: float = 0.25
    ai_cost_per_1k_output_inr: float = 1.0

    object_store: str = "local"  # local | s3
    object_store_dir: str = "./var/objects"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "nsip-originals"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    mailbox_adapter: str = "folder"  # folder | graph | imap
    mailbox_dir: str = "./var/mailbox"
    outbox_dir: str = "./var/outbox"
    regions: list[str] = Field(default_factory=lambda: ["west", "south", "north", "east"])

    antivirus: str = "mock"  # mock | clamav
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    ocr: str = "mock"  # mock | tesseract | gateway

    rating_api_url: str = "http://localhost:8095"
    rating_mode: str = "mock"  # mock | live
    rating_workbook_path: str = ""  # defaults to bundled filed sample workbook
    policy_admin_mode: str = "mock"
    policy_admin_url: str = "http://localhost:8096"
    policy_admin_api_version: str = "2026.3"

    geocode_cost_inr: float = 0.85
    cat_model_cost_inr: float = 4.0
    max_attachment_bytes: int = 50 * 1024 * 1024
    max_json_body_bytes: int = 1024 * 1024
    rate_limit_per_minute: int = 600

    sla_hours: int = 48
    referral_sla_hours: int = 72
    small_risk_premium_inr: int = 200_000  # Rs 2 lakh fast lane
    pii_retention_days: int = 365 * 3
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:5174"])
    compute_cost_per_submission_inr: float = 1.5


@lru_cache
def get_settings() -> Settings:
    return Settings()

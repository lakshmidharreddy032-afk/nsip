"""Auth-service configuration. Secrets come from the environment; dev defaults are deliberately unsafe."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "sqlite:///./var/auth.db"
    db_schema: str | None = None  # "auth" on PostgreSQL: own schema, own deployment unit
    issuer: str = "https://auth.nsip.local"
    audience: str = "nsip-core-api"
    access_ttl_seconds: int = 900  # 15 minutes
    refresh_ttl_seconds: int = 60 * 60 * 12
    mfa_challenge_ttl_seconds: int = 300
    key_dir: str = "./var/keys"
    key_id: str = "nsip-auth-1"
    data_key: str | None = None  # Fernet key for MFA secrets at rest
    cookie_secure: bool = True
    cookie_domain: str | None = None
    refresh_cookie_name: str = "nsip_rt"
    csrf_cookie_name: str = "nsip_csrf"
    lockout_threshold: int = 5
    lockout_base_seconds: int = 30
    lockout_max_seconds: int = 3600
    reset_token_ttl_seconds: int = 1800
    reset_secret: str = "dev-only-reset-secret-change-me"
    internal_service_token: str = "dev-internal-token"
    login_rate_limit_per_minute: int = 20
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8080/auth/oidc/callback"
    mfa_required_roles: list[str] = Field(
        default_factory=lambda: ["underwriter", "senior_underwriter", "cuo", "admin"]
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:5174"])
    mail_outbox_dir: str = "./var/outbox"
    app_base_url: str = "http://localhost:8080"
    workbench_url: str = "/"


@lru_cache
def get_settings() -> Settings:
    return Settings()

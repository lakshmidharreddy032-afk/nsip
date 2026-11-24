from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class MfaVerifyRequest(BaseModel):
    mfa_token: str = Field(min_length=10, max_length=200)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=1000)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    region: str
    roles: list[str]
    mfa_enabled: bool
    is_active: bool
    locked: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserOut


class LoginResponse(BaseModel):
    status: str  # authenticated | mfa_required | mfa_enroll_required
    mfa_token: str | None = None
    otpauth_uri: str | None = None
    secret: str | None = None
    token: TokenResponse | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    ip: str
    user_agent: str
    current: bool
    mfa_verified: bool


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    region: str = Field(default="west", max_length=32)
    roles: list[str]
    temporary_password: str = Field(min_length=12, max_length=256)


class RolesUpdate(BaseModel):
    roles: list[str]


class AuthorityUpdate(BaseModel):
    authority: list[dict]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    ts: datetime
    user_id: uuid.UUID | None
    email: str
    event: str
    ip: str
    detail: dict

"""Initial auth schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-24
"""
from alembic import op

import app.models  # noqa: F401
from app.core.db import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The ORM metadata is the single source of truth for v1 (ADR-0010); later revisions are incremental.
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())

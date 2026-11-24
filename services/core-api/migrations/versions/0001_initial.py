"""Initial core schema, append-only audit trigger and row-level region security.

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

AUDIT_GUARD = """
CREATE OR REPLACE FUNCTION nsip_audit_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
CREATE TRIGGER audit_events_no_update BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION nsip_audit_immutable();
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM PUBLIC;
"""

# Defence in depth for region scoping: the API sets `app.region` per transaction for scoped users.
REGION_RLS = """
ALTER TABLE submissions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS submissions_region ON submissions;
CREATE POLICY submissions_region ON submissions
  USING (coalesce(current_setting('app.region', true), 'all') IN ('all', region));
"""


def upgrade() -> None:
    bind = op.get_bind()
    # v1 schema is generated from the ORM metadata (ADR-0010); later revisions are incremental.
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        op.execute(AUDIT_GUARD)
        op.execute(REGION_RLS)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events")
    Base.metadata.drop_all(bind)

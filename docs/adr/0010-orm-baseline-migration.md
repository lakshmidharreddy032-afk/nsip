# ADR-0010: ORM-generated baseline migration

Status: Accepted (2026-11-24)

## Context

The schema was designed greenfield in one release.

## Decision

Revision 0001 creates the schema from the ORM metadata and adds PostgreSQL-specific controls (audit trigger, row-level security). Every later change is an explicit incremental Alembic revision reviewed in the pull request.

## Consequences

Fast first release; the baseline must never be edited after go-live.

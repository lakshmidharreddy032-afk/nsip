# ADR-0002: Human-only pricing and quote issuance

Status: Accepted (2026-11-24)

## Context

The AI policy is assistive for pricing; IRDAI file-and-use requires filed rates. The sponsor's original ask was automated quoting.

## Decision

Quote creation exists only in `domain/quoting/service.py`, which requires a `HumanActor` built from an authenticated request, explicit confirmation, MFA, a current rating run from a filed source and a passing authority check. An architecture test fails the build if `app/ai` imports quoting or any other module constructs a `Quote`. The small-risk fast lane still needs one underwriter confirmation.

## Consequences

Automation cannot be switched on by configuration. Amending this requires a code change, an AI-policy amendment and a new ADR.

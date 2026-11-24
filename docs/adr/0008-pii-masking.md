# ADR-0008: PII masking for prompts and logs

Status: Accepted (2026-11-24)

## Context

DPDP Act 2023 requires minimisation and purpose limitation.

## Decision

PAN, Aadhaar, phone numbers, personal email addresses and individual names are masked before any prompt leaves the platform and in every log line (structlog processor). Detected items are recorded with purpose, basis and retention date; retention and erasure jobs mask derived data.

## Consequences

The model never sees contact details; extraction does not need them.

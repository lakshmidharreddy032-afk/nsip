# ADR-0005: Policy admin anti-corruption layer

Status: Accepted (2026-11-24)

## Context

The policy admin system is vendor SaaS with quarterly releases and limited quote APIs.

## Decision

`adapters/policy_admin.py` pins API version 2026.3; `VendorTranslator` is the only place that knows vendor field names and absorbs version differences (for example `quoteNumber` versus `quote_id`). Contract tests validate payloads against the pinned schema. Calls carry an idempotency key.

## Consequences

A vendor release breaks CI contract tests rather than production. Upgrades are a translator change plus contract update.

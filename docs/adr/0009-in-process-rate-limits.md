# ADR-0009: Rate limiting and lockout

Status: Accepted (2026-11-24)

## Context

ASVS L2 requires brute-force protection and API rate limits.

## Decision

Per-IP sliding-window limits in the services plus nginx/ingress `limit_req`; account lockout after 5 failures with exponential backoff. In multi-replica deployments the ingress limit is the shared control; a Redis-backed limiter can replace the in-process one without API changes.

## Consequences

Simple and dependency-free locally; relies on the ingress for cross-replica limits.

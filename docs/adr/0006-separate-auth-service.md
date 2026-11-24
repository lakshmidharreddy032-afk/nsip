# ADR-0006: Separate authentication service and login app

Status: Accepted (2026-11-24)

## Context

The workbench must never handle passwords; MFA is mandatory for underwriter and above.

## Decision

auth-service has its own database and schema, signs RS256 tokens and publishes JWKS. auth-web is a separate application at `/login`. All apps share one origin through the ingress so SameSite=Strict cookies work; refresh uses a double-submit CSRF token.

## Consequences

Two deployables to operate; key rotation keeps retired public keys in JWKS for overlap.

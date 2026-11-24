# ADR-0001: Email-first intake; no new broker portal

Status: Accepted (2026-11-24)

## Context

The Distribution head has committed to brokers that there will be no new portals, and the 2023 portal has 8% adoption.

## Decision

Intake stays email-first through the regional shared mailboxes (MS Graph, IMAP fallback, folder mock for tests). The 2023 portal is read as a secondary channel through `BrokerPortalAdapter`. NSIP is an internal workbench only; nothing is broker-facing.

## Consequences

Brokers change nothing. Parsing must cope with free-form email, so deterministic parsing is backed by schema-constrained extraction through the gateway.

# ADR-0003: Rules-before-LLM appetite triage

Status: Accepted (2026-11-24)

## Context

45% of submissions are out of appetite; decisions must be explainable, auditable and immune to prompt injection.

## Decision

A versioned, CUO-approved rules engine decides `in_appetite`, `out_of_appetite`, `refer_risk_engineering` or `needs_info` from code-derived features. The model supplies advisory hazard notes and a suggested outcome that is logged for drift monitoring but never used for routing. Drafts are replayed against the historical set before approval; authors cannot approve their own ruleset.

## Consequences

Triage is deterministic and testable (98.8% on the synthetic set). New appetite needs rule changes, not prompt changes.

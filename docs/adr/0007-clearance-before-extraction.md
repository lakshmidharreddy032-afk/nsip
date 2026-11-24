# ADR-0007: Duplicate clearance before extraction using free reference data

Status: Accepted (2026-11-24)

## Context

18% of submissions are duplicates; licensed geocoding is charged per call and must be called only after triage.

## Decision

Clearance blocks on the pincode and a geohash of the free offline pincode centroid, then scores fuzzy name, address, occupancy and sum-insured similarity. Auto-link at >= 0.90; human review between 0.75 and 0.90; a weak name match caps the score. Broker-of-record follows a configurable rule (default first received).

## Consequences

No licensed calls for duplicates or declines. Precise geocodes are attached later for underwriting.

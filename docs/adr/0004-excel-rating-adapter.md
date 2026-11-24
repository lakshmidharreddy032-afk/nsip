# ADR-0004: Controlled Excel rating adapter

Status: Accepted (2026-11-24)

## Context

Larger property risks are rated in actuarial Excel workbooks that are part of the filing.

## Decision

The workbook runs in a sandboxed evaluator (`adapters/excel_calc.py`) that supports a small formula subset and refuses macros, external links and unknown functions. The workbook SHA-256 must be on the filed allow-list (`integration_configs.rating_workbooks`); each rating run records workbook hash, table version, filing reference and an inputs hash. Quotes are refused if submission data changed after rating.

## Consequences

Workbook updates follow the runbook: actuarial sign-off, hash registration, then release. pycel was rejected because it is not compatible with Python 3.14+ and executes a broader formula surface than needed.

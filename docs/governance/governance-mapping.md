# Governance mapping

This maps each regulatory and policy obligation to the control that enforces it, where the control lives, and the evidence an auditor can inspect.

## IRDAI file-and-use

| Obligation | Control | Where | Evidence |
|---|---|---|---|
| Premiums must come from filed rates | Only two rating sources are accepted: the filed package rating API and the filed actuarial workbook | `domain/rating/service.py` (`FILED_SOURCES`), `adapters/rating.py` | `rating_runs.source`, `source_version`, `filing_ref` |
| Workbook must be the filed version | Workbook SHA-256 checked against the allow-list before evaluation; sandboxed formula subset | `adapters/excel_calc.py`, `integration_configs.rating_workbooks` | `rating_runs.workbook_hash` |
| The model must never produce a premium | AI output schemas contain no premium field; prompts forbid it; quote premium is copied from the rating run only | `ai/schemas`, `ai/prompts/*.yaml`, `domain/quoting/service.py` | `quotes.rating_run_id`, sealed evidence |
| Quote reflects the rated data | Inputs hash must match current submission data at quote time | `rating.is_current` | `quote.blocked` refusals in audit |

## Underwriting authority matrix

| Obligation | Control | Where | Evidence |
|---|---|---|---|
| Check line, sum insured, premium band and region on every quote action | `authority.check` runs on rating display and again inside `issue_quote` | `domain/authority/service.py` | `quotes.authority_snapshot`, `decisions.authority_check` |
| Out-of-authority requires referral | Blocked quotes record a `refer` decision and return the referral target | `domain/quoting/service.py` | `quote.blocked_authority` audit events |
| Authority changes are controlled | Maker-checker: proposer cannot approve; approved limits pushed to auth-service as claims | `authority.propose/decide`, admin UI | `authority.proposed/approved` audit events |
| Stale authority cannot be used | Token claim must match the approved database version | `authority.check` | refusal reason "Authority in your session is out of date" |
| MFA for quote actions | MFA claim required for any quote | `authority.check`, auth-service | `amr` claim, auth audit log |

## DPDP Act 2023

| Obligation | Control | Where |
|---|---|---|
| Data minimisation in AI processing | PII masked before prompts leave the platform | `ai/gateway.py`, `ai/guards/pii.py` |
| No personal data in logs | structlog processor masks PII and redacts secrets | `core/logging.py` |
| Purpose and consent metadata | `submissions.consent` (purpose, basis, notice) and `pii_registry` (purpose, basis, retention date) | `domain/submissions/service.py`, `ingestion.py` |
| Retention | Nightly retention job masks expired personal data; raw originals deleted unless bound to a sealed quote (statutory record-keeping) | `domain/privacy/service.py`, CronJob |
| Erasure | Admin erasure by identifier masks all derived records and logs the request | `POST /api/v1/admin/privacy/erasure` |
| Security of processing | Encryption at rest (S3 SSE, Fernet for MFA secrets), TLS at ingress, RBAC with region scoping and RLS | Helm values, `auth-service/core/security.py`, migration 0001 |

Open point: the retention period per purpose (default 3 years) and the precedence between erasure and insurance record-keeping need legal sign-off; see [open decisions](../open-decisions.md).

## AI policy (assistive use)

| Policy point | Control |
|---|---|
| AI is assistive for pricing | No code path from `app/ai` to quoting (architecture test, pre-commit hook) |
| Decisions are made by accountable humans | Declines need one-click underwriter confirmation; quotes need explicit confirmation; overrides need a reason |
| Single approved gateway, India-hosted | `AI_GATEWAY_URL` used only in `ai/gateway.py`; architecture test blocks provider SDKs |
| Untrusted content cannot change behaviour | Delimited data blocks, schema-constrained outputs, no tools, deterministic routing, injection flags shown to reviewers; red-team suite of 30 attacks |
| Transparency and traceability | Every extracted field stores value, confidence, source reference, method, model and prompt version; every AI call stores tokens, latency, cost and masked request/response |
| Monitoring | Override rate per field, assistant disagreement rate, drift alerts on the CUO dashboard |

## Audit

Every quote stores sealed evidence: source emails and documents with hashes, every extracted field with source location and confidence, every human edit, the rate source and version, and the authority used. The audit log is append-only and hash-chained; integrity is verifiable at `/api/v1/audit/verify` and exportable from the Audit Explorer.

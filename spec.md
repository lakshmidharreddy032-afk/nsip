# spec.md — Northstar Submission Intelligence Platform (NSIP)

## 0. Instructions to the Coding Agent

You are building a production-grade, full-stack application for Northstar General Insurance. Read this entire spec before writing code. Build in the phase order given in Section 14. After each phase, run tests, lint and type checks, and fix all failures before continuing. Do not skip any section. Do not invent features that contradict the constraints in Section 2. Where a decision is not specified, choose the conservative, auditable option and record it in `docs/adr/`.

The sponsor asked for "an AI that reads broker emails and generates quotes automatically." That is not what you are building. The evidence shows that 45% of submissions are out of appetite yet keyed in full, 18% are duplicates, and data entry takes 70 minutes per submission. The first valuable slice is therefore appetite triage, duplicate clearance and structured extraction into a pre-filled submission that an underwriter reviews and prices. Automated pricing and automated quote issuance are explicitly out of scope and must be impossible in the system, not merely hidden.

## 1. Business Context

Northstar General is an Indian general insurer writing SME property and package policies through brokers. Key baselines that the platform must measure against:

| Metric | Baseline | Target (pilot) |
|---|---|---|
| Submissions per month | 9,000 | same |
| Out-of-appetite share | ~45%, keyed in full | declined at triage, < 5 min handling |
| Duplicate share | 18% | flagged at clearance before extraction |
| Data entry time | ~70 min per submission | < 15 min review of pre-filled data |
| Median time to quote | 6 working days | < 48 hours for in-appetite, non-referred |
| Win rate on quoted business | 11% | tracked, not promised |
| Property loss ratio | 68% | must not worsen (guardrail metric) |
| Risk engineering referral | 12%, adds ~4 days | referral triggered at triage, not after pricing |
| Underwriter time on risks < ₹2 lakh premium | ~40% | reduced via pre-filled workbench |

Outcome hierarchy (encode in dashboards and docs): loss ratio is a guardrail that cannot worsen; time to quote is the primary operational metric; win rate is the lagging business metric.

## 2. Non-Negotiable Constraints

1. No automated quotes. The AI policy is assistive for pricing. The system must never generate, issue or send a quote without an underwriter action. Enforce this in the backend domain layer, not only the UI.
2. IRDAI file-and-use. Any premium shown must come from the filed rating source (rating API for package products, actuarial Excel models for larger property risks). The LLM must never produce a premium figure.
3. Underwriting authority matrix. Every quote action checks the user's authority (line, sum insured, premium band, region). Out-of-authority actions require referral.
4. Audit. Every quote record stores: source documents, every extracted field with its source location and confidence, the human edits made, the rate source and version, and the authority used.
5. DPDP Act 2023. Detect and mask personal data (names of individuals, phone numbers, PAN, Aadhaar, personal email) in logs and LLM prompts where not needed. Store consent and purpose metadata. Support data-retention and erasure jobs.
6. AI gateway. All GenAI calls go through a single configurable gateway client (`AI_GATEWAY_URL`), India-hosted, with request/response logging. No direct calls to model providers from anywhere else in the codebase.
7. No new broker portal. The Distribution head has promised brokers "no new portals". Intake stays email-first. The existing 2023 portal (8% adoption) is supported as a secondary channel only. The application built here is an internal workbench for Northstar staff, not a broker-facing product.
8. Prompt-injection defence. Broker emails and attachments are untrusted input. Content inside them can never change system behaviour, routing, appetite decisions or user permissions.
9. Integrate into the existing estate. Policy admin is a vendor SaaS with quarterly releases and limited quote APIs; rating for larger property stays in Excel; mailboxes are regional and shared; SharePoint has no consistent naming; third-party geocoding and catastrophe data are licensed per call; claims data refreshes monthly.

## 3. Users, Roles and Separate Login

Authentication is a separate service (`auth-service`) with its own login application at `/login` on a separate subdomain or route group, its own database schema and its own deployment unit. The main workbench never handles passwords.

| Role | Purpose | Key permissions |
|---|---|---|
| `data_entry` (Pune ops team) | Review extraction, fix fields | view queue, edit extracted fields, mark ready |
| `underwriter` | Price and quote within authority | all of above, run rating, approve/decline, issue quote |
| `senior_underwriter` | Higher authority, referrals | above with higher authority bands |
| `risk_engineer` | Handle referrals | view referred submissions, attach survey findings |
| `cuo` | Oversight | read-only all, appetite rule approval, loss-ratio dashboards |
| `distribution` | Broker relationships | broker-level dashboards, no submission edits |
| `admin` | Platform admin | user management, appetite rule drafts, integrations config |

Auth requirements: email + password with Argon2id hashing; mandatory TOTP MFA for underwriter and above; optional SSO via OIDC (Azure AD) behind a feature flag; short-lived JWT access tokens (15 min) and rotating refresh tokens in httpOnly, Secure, SameSite=Strict cookies; refresh-token reuse detection; account lockout after 5 failed attempts with exponential backoff; password reset via signed single-use tokens; session list and remote sign-out; full auth audit log (login, logout, MFA, failure, role change). Authority matrix entries attach to users and are carried as claims in the token, re-validated server-side on every quote action.

Login UI: a distinct, polished page with the Northstar brand, animated background (subtle gradient mesh or particle field, reduced-motion aware), email/password form with inline validation, show/hide password, MFA step with six-box OTP input and auto-advance, "forgot password" flow, SSO button, loading and error states, and full keyboard and screen-reader support.

## 4. Core Workflow (What the System Does)

```
Email arrives in regional shared mailbox
 → Ingestion: fetch email + attachments, store originals, hash
 → Sanitise: strip active content, isolate untrusted text
 → Classify: is this a new submission, an updated schedule, a query, or noise?
 → Clearance: duplicate detection (same risk via different brokers)
 → Appetite triage: rules engine first, LLM-assisted signals second
     → Out of appetite: draft decline reason for human confirmation, fast-track
     → Needs risk engineering: refer immediately, in parallel with extraction
     → In appetite: continue
 → Extraction: proposal form, schedule of values (SOV), loss history
 → Enrichment: geocode, cat-model score (cached, budgeted per call)
 → Pre-filled submission in workbench with field confidence + source links
 → Data entry / underwriter review and correction
 → Underwriter runs rating (rating API or Excel model adapter)
 → Underwriter decision within authority → quote created in policy admin
 → Audit record sealed
```

Mid-flight updates: when a broker sends an updated SOV, the system diffs it against the current version, re-extracts only changed sections, shows a field-level diff to the user, and preserves prior human corrections where the source value is unchanged. It never silently overwrites reviewed data.

## 5. Functional Modules

### 5.1 Ingestion
Connectors for Microsoft Graph (shared mailboxes per region) and IMAP fallback, plus a mock connector reading `.eml` files from a folder for local and test use. Polling plus webhook subscription where available. Idempotent on message ID. Attachments up to 50 MB; stream to object storage. Store raw `.eml`, each attachment, SHA-256 hash and region.

### 5.2 Document Processing
Handle Excel (`.xlsx`, `.xls`, `.csv`), native PDF, scanned PDF and images. Use OCR (Tesseract or a pluggable cloud OCR via the gateway) for scans. Build a format-fingerprint library for the ~30 known broker SOV layouts: deterministic column mappers for known layouts, LLM-assisted header mapping only for unknown layouts, with the learned mapping saved for human approval and reuse.

### 5.3 Clearance (Duplicates)
Normalise insured name, address (geocoded), occupancy and sum insured. Use blocking on geohash plus fuzzy name matching (e.g. rapidfuzz) and a scored match. Above threshold: auto-link and flag. Mid band: present to user for confirmation. Record which broker arrived first (broker-of-record rules are configurable, not hard-coded).

### 5.4 Appetite Triage
A versioned rules engine (YAML or DB-stored rules, approved by CUO role) covering occupancy codes, geography/cat zones, sum insured limits, construction type, loss history thresholds and prohibited trades. The LLM supplies extracted features and a plain-language rationale; it never makes the final decision. Output: `in_appetite`, `out_of_appetite`, `refer_risk_engineering`, `needs_info`, each with rule IDs that fired. Out-of-appetite submissions get a drafted decline email for one-click human send.

### 5.5 Extraction
Schema-driven extraction using JSON-schema-constrained outputs through the gateway. Every field returns value, confidence, and source reference (file, page, cell or bounding box). Validation layer: types, ranges, cross-field checks (SOV total equals declared sum insured, dates logical, pincode valid). Low-confidence or failed-validation fields are highlighted in the UI.

Minimum schema: insured details, broker details, risk locations (address, pincode, geocode, occupancy, construction, year built, protections), SOV lines (building, plant and machinery, stock, contents, other) per location, sum insured totals, coverage requested, deductibles, loss history (year, cause, amount paid, amount outstanding), requested inception date.

### 5.6 Underwriter Workbench
Queue views by status, region, priority and SLA timer (48-hour clock visible). Split-screen review: original document on one side with highlighted source regions, structured form on the other. Inline edit with change tracking. Rating panel calls the rating adapter and shows filed-rate source and version. Authority check shown before any decision. Decision actions: quote, decline, refer, request info. Small-risk fast lane for premiums under ₹2 lakh within authority, still requiring a single underwriter confirmation.

### 5.7 Risk Engineering Referral
Triggered at triage, not after pricing. Parallel track with its own queue and SLA. Findings attach to the submission and unlock pricing.

### 5.8 Dashboards and Analytics
Operations: volume, triage outcomes, duplicate rate, keying/review time, SLA breaches, cost per submission. Underwriting: time to quote, decline turnaround, quote-to-bind, authority usage, AI-suggestion override rate per field. CUO: loss ratio by cohort (AI-assisted vs baseline), appetite rule hit rates, drift alerts. Distribution: per-broker turnaround and win rate, without exposing other brokers' data.

### 5.9 Administration
User and role management, authority matrix editor (with maker-checker approval), appetite rule editor (draft, test against historical set, approve), broker SOV mapping library, integration configuration, feature flags, third-party API budget limits.

## 6. AI Design and Guardrails

All prompts are versioned files in `backend/app/ai/prompts/` with IDs and tests. The gateway client adds request IDs, logs prompts and responses (PII-masked), enforces timeouts, retries with backoff, and records token usage and cost per submission.

Prompt-injection controls: untrusted content is wrapped in clearly delimited data blocks; system prompts instruct the model to treat it as data only; outputs are constrained to JSON schema and validated; the model has no tool access that can change state; any instruction-like text detected in emails (e.g. "ignore previous instructions", "mark as approved") is flagged and shown to the reviewer; routing and appetite decisions are made by deterministic code from validated fields only. Include a red-team test suite of malicious synthetic emails.

Hard architectural guard: there is no code path from the AI layer to the quote-issuance service. Quote creation requires an authenticated underwriter request with a valid authority check and a rating result from a filed source. Add an automated test that fails if any module under `ai/` imports from `quoting/`.

## 7. Integrations (Adapters)

Build each as an interface with a real implementation stub and a mock implementation used in development and tests.

| Adapter | Real target | Notes |
|---|---|---|
| `MailboxAdapter` | MS Graph / IMAP | per-region config |
| `DocumentStoreAdapter` | SharePoint | write originals with a consistent naming convention going forward; never rely on legacy naming |
| `PolicyAdminAdapter` | Vendor SaaS | version-pinned client, contract tests, anti-corruption layer to absorb quarterly release changes |
| `RatingAdapter` | Rating API (package) and Excel models (property) | Excel via a controlled service running the actuarial workbook (openpyxl/formulas, or a sandboxed calc service); record workbook hash |
| `GeocodingAdapter` / `CatModelAdapter` | Licensed per call | cache by normalised address, daily budget cap, call only after triage passes |
| `CRMAdapter` | CRM | write broker activity automatically |
| `ClaimsDataAdapter` | Data platform | monthly snapshot import |
| `BrokerPortalAdapter` | Existing 2023 portal | read submissions as a secondary channel only |

## 8. Technology Stack

Frontend: React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Radix primitives, Framer Motion for transitions and micro-interactions, TanStack Query for server state, Zustand for client state, React Hook Form with Zod, TanStack Table for queues, Recharts for dashboards, react-pdf for document viewing, i18next (English first), Vitest and Testing Library, Playwright for end-to-end tests.

Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 with Alembic migrations, PostgreSQL 16 (with pgvector optional for similarity), Redis, Celery (or Dramatiq) workers for ingestion, OCR and extraction, MinIO/S3-compatible object storage, structlog JSON logging, OpenTelemetry tracing, Prometheus metrics, pytest with coverage, Ruff and mypy.

Auth service: separate FastAPI service with its own schema, Argon2id, pyotp for TOTP, JWKS endpoint for public keys so other services verify tokens without sharing secrets.

Infrastructure: Docker multi-stage images, docker-compose for local, Kubernetes manifests with Helm chart for production, Nginx ingress, GitHub Actions CI/CD, Trivy image scanning, Dependabot, pre-commit hooks. Grafana dashboards and alert rules. All secrets via environment or a secrets manager; nothing committed.

## 9. Folder Structure

```
nsip/
├── README.md
├── spec.md
├── docker-compose.yml
├── docker-compose.prod.yml
├── Makefile
├── .env.example
├── .github/workflows/
│   ├── ci.yml
│   ├── security.yml
│   └── deploy.yml
├── docs/
│   ├── architecture.md
│   ├── adr/
│   ├── runbooks/
│   ├── api/                      # generated OpenAPI
│   └── governance/               # DPDP, audit, AI policy mapping
├── apps/
│   ├── auth-web/                 # separate login application
│   │   ├── src/
│   │   │   ├── pages/            # Login, MFA, ForgotPassword, ResetPassword
│   │   │   ├── components/
│   │   │   ├── lib/
│   │   │   └── styles/
│   │   ├── index.html
│   │   ├── vite.config.ts
│   │   └── Dockerfile
│   └── workbench-web/            # main application
│       ├── src/
│       │   ├── app/              # router, providers, layout
│       │   ├── features/
│       │   │   ├── queue/
│       │   │   ├── submission/   # review, document viewer, diff
│       │   │   ├── triage/
│       │   │   ├── clearance/
│       │   │   ├── rating/
│       │   │   ├── referrals/
│       │   │   ├── dashboards/
│       │   │   └── admin/
│       │   ├── components/ui/    # shadcn components
│       │   ├── hooks/
│       │   ├── lib/              # api client, auth, formatters (₹, lakh/crore)
│       │   ├── stores/
│       │   └── types/
│       ├── e2e/                  # Playwright
│       ├── vite.config.ts
│       └── Dockerfile
├── services/
│   ├── auth-service/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── core/             # security, jwt, jwks, config
│   │   │   ├── models/
│   │   │   ├── schemas/
│   │   │   └── services/
│   │   ├── migrations/
│   │   ├── tests/
│   │   └── Dockerfile
│   └── core-api/
│       ├── app/
│       │   ├── api/v1/           # routers per domain
│       │   ├── core/             # config, logging, telemetry, deps
│       │   ├── domain/
│       │   │   ├── submissions/
│       │   │   ├── clearance/
│       │   │   ├── appetite/     # rules engine + rule versions
│       │   │   ├── extraction/
│       │   │   ├── rating/
│       │   │   ├── authority/
│       │   │   ├── quoting/      # human-only quote issuance
│       │   │   ├── referrals/
│       │   │   └── audit/
│       │   ├── ai/
│       │   │   ├── gateway.py
│       │   │   ├── prompts/
│       │   │   ├── schemas/
│       │   │   └── guards/       # injection detection, PII masking
│       │   ├── adapters/         # mailbox, sharepoint, policy_admin, rating, geo, cat, crm, claims, portal
│       │   ├── workers/          # celery tasks
│       │   ├── models/
│       │   └── schemas/
│       ├── migrations/
│       ├── tests/
│       │   ├── unit/
│       │   ├── integration/
│       │   ├── contract/         # policy admin + rating contracts
│       │   ├── security/         # injection red-team, authz
│       │   └── architecture/     # import-boundary tests
│       └── Dockerfile
├── eval/
│   ├── synthetic/                # generator for broker emails, SOVs, scans
│   ├── datasets/                 # labelled ground truth
│   ├── run_eval.py
│   └── reports/
├── infra/
│   ├── nginx/
│   ├── helm/nsip/
│   ├── k8s/
│   └── monitoring/               # prometheus rules, grafana dashboards
└── scripts/
    ├── seed.py                   # demo users, rules, authority matrix
    └── load_test/                # k6 or Locust
```

## 10. Data Model (Minimum)

Tables: `users`, `roles`, `user_roles`, `authority_limits`, `brokers`, `emails`, `attachments`, `submissions`, `submission_versions`, `risk_locations`, `sov_lines`, `loss_history`, `extracted_fields` (value, confidence, source_ref, model_version, prompt_version), `field_edits` (before, after, user, timestamp, reason), `duplicate_links`, `appetite_rules`, `appetite_rule_versions`, `triage_results`, `referrals`, `rating_runs` (source, version, inputs hash, outputs), `quotes`, `decisions`, `audit_events` (append-only, hash-chained), `ai_calls` (tokens, latency, cost, request ID), `third_party_calls`, `pii_registry`, `feature_flags`. Use UUID primary keys, created/updated timestamps, soft delete where retention rules allow, and row-level region scoping.

## 11. UI and UX Requirements

The application must feel modern, fast and attractive while remaining professional for enterprise underwriting work. Design system: a defined token set (colour, spacing, radius, typography), light and dark themes, Inter or similar typeface, consistent iconography (lucide). Interaction: command palette (Ctrl+K) for navigation and search, keyboard shortcuts for review (next field, accept, flag), animated page and panel transitions, skeleton loaders, optimistic updates with rollback, toast notifications, live SLA countdowns, real-time queue updates via WebSocket or server-sent events, drag-to-resize split panes, hover-to-highlight linking between form fields and document regions, confidence shown as colour-coded chips, side-by-side diff view for updated schedules. Dashboards use animated charts with drill-down. Empty, error and offline states are designed, not default. Accessibility: WCAG 2.1 AA, focus management, `prefers-reduced-motion` respected. Responsive down to tablet; the review screen is desktop-first. Indian number formatting (lakh/crore) and ₹ throughout.

Key screens: Login, MFA, Home (personal queue and KPIs), Submission Queue, Submission Review, Duplicate Resolution, Triage Detail, Rating and Decision, Referral Queue, Dashboards (Ops, Underwriting, CUO, Distribution), Admin (users, authority matrix, appetite rules, mappings, integrations, flags), Audit Explorer, Profile and Sessions.

## 12. Security, Privacy and Compliance

OWASP ASVS Level 2 as the target. RBAC plus attribute checks (region, authority band) enforced in the backend. CSRF protection for cookie flows, strict CORS, CSP headers, rate limiting per user and IP, input size limits, antivirus scanning of attachments (ClamAV container), macro stripping for Office files, encrypted storage at rest, TLS everywhere. PII masking before LLM calls where the field is not required for extraction; masked values in logs. Data retention jobs per DPDP purpose. Append-only, hash-chained audit log with an Audit Explorer UI and export. Secrets never logged.

## 13. Cost, Scale and Operations

Design for 9,000 submissions per month (~300 per working day, peaks of 3x). Track cost per submission as a first-class metric, broken into LLM tokens, OCR, geocoding, cat model and compute. Reduce cost by: deterministic mappers for known SOV layouts before any LLM call; triage before expensive enrichment; caching geocodes and cat scores; small models for classification and larger models only for complex extraction; batching. Show a monthly cost projection in the admin dashboard with budget alerts. Horizontal scaling of workers; queue depth autoscaling. Region-by-region rollout via feature flags, starting with one regional mailbox. Runbooks for mailbox outage, gateway outage (fall back to manual queue), policy admin release changes and rating workbook updates.

## 14. Build Phases

1. Foundation: monorepo, docker-compose (Postgres, Redis, MinIO, ClamAV, mock gateway), CI, linting, typing, base config and logging.
2. Auth service and auth-web login application with MFA, refresh rotation, JWKS, seed users for every role.
3. Core data model, migrations, audit log, RBAC and authority checks.
4. Synthetic data generator: at least 300 broker emails across 10+ SOV layouts, PDFs, scans, duplicates (18%), out-of-appetite cases (45%), mid-flight updates, and 30 prompt-injection attempts, with ground-truth labels.
5. Ingestion, sanitisation, classification, clearance.
6. Appetite rules engine and triage with decline drafting and early referral.
7. Extraction pipeline with confidence, source references and validation.
8. Workbench UI: queue, review, diff, duplicate resolution, triage detail.
9. Rating adapters (mock rating API and sample Excel model), authority check, human-only quote issuance through the policy admin mock.
10. Dashboards, cost tracking, admin screens.
11. Evaluation harness and security test suite.
12. Production hardening: Helm chart, monitoring, load test, runbooks, documentation.

## 15. Evaluation and Acceptance Criteria

The eval harness (`make eval`) reports against the labelled synthetic set:

| Measure | Acceptance threshold |
|---|---|
| Appetite triage accuracy | ≥ 95%, with zero in-appetite risks auto-declined without human confirmation |
| Duplicate detection | precision ≥ 0.95, recall ≥ 0.90 |
| Field-level extraction accuracy (critical fields: address, occupancy, sum insured, SOV totals) | ≥ 95% |
| SOV total reconciliation | flagged in 100% of mismatches |
| Prompt-injection suite | 100% of attacks fail to alter routing, decisions or permissions; all flagged |
| Simulated review time | pre-filled review completes in ≤ 15 minutes versus 70-minute baseline (measured via timed UI tasks in Playwright scripts and manual pilot) |
| Automated quote paths | zero; architecture test passes |
| Audit completeness | every quote has data, rate source/version and authority recorded |

Engineering gates: backend coverage ≥ 85%, frontend coverage ≥ 75%, zero high or critical vulnerabilities in scans, all Playwright journeys green (login with MFA, triage decline, duplicate merge, review and correct, rate and quote, referral, SOV update diff), p95 API latency < 300 ms for workbench reads, Lighthouse accessibility ≥ 95.

## 16. Deliverables

Working code for all services and both frontends; `docker compose up` brings up the full stack with seeded data and demo users; Helm chart for production; OpenAPI docs; architecture document with diagrams; ADRs for key decisions (email-first intake, human-only pricing, rules-before-LLM triage, Excel rating adapter, policy admin anti-corruption layer); evaluation report; governance mapping showing how IRDAI file-and-use, the authority matrix, DPDP and the AI policy are enforced; runbooks; and a short executive summary for Ashok Menon, the CUO and the Distribution head that states baselines, pilot targets, the loss-ratio guardrail, and how underwriter use and AI-override rates are tracked.

## 17. Open Decisions to Surface (Do Not Assume)

Record these as open items in `docs/open-decisions.md` with recommended options: which outcome wins when speed and loss ratio conflict (recommended: loss ratio as hard guardrail); whether out-of-appetite declines can be sent with lighter review (recommended: one-click human confirmation); whether any small risk can be quoted without an underwriter (recommended: no, until AI policy is amended; build the fast lane with single confirmation); email versus portal (recommended: email-first, honouring the "no new portals" commitment); and accountable owner (recommended: Commercial Lines owns outcome, Operations owns the Pune team process, Distribution owns broker communication).

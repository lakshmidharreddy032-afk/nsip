# Northstar Submission Intelligence Platform (NSIP)

NSIP is an internal underwriting workbench for Northstar General's SME property and package business. It reads broker submissions from the regional shared mailboxes, triages appetite with a deterministic rules engine, clears duplicates before anyone keys data, and pre-fills a structured submission that an underwriter reviews, rates from filed sources and quotes. It does not price or quote automatically; that path does not exist in the code (see [ADR-0002](docs/adr/0002-human-only-pricing.md)).

## What is in the repository

| Path | Contents |
|---|---|
| `services/auth-service` | Separate FastAPI identity service: Argon2id, TOTP MFA, rotating refresh tokens with reuse detection, lockout, password reset, sessions, JWKS, optional Azure AD OIDC |
| `services/core-api` | Workbench API, ingestion and extraction pipeline, appetite engine, clearance, rating adapters, human-only quoting, audit, dashboards |
| `services/mock-gateway` | Deterministic stand-in for the India-hosted AI gateway (dev and test only) |
| `apps/auth-web` | Login application served at `/login` (MFA, forgot and reset password, SSO button) |
| `apps/workbench-web` | Underwriter workbench (queue, review, triage, duplicates, rating, referrals, dashboards, admin, audit) |
| `eval/` | Synthetic broker data generator and the acceptance harness (`make eval`) |
| `infra/` | nginx gateway, Helm chart, Kubernetes extras, Prometheus rules, Grafana dashboard |
| `docs/` | Architecture, ADRs, governance mapping, runbooks, open decisions, executive summary, OpenAPI |

## Quick start (Docker)

```bash
cp .env.example .env          # set real secrets for anything beyond a laptop
docker compose up --build
# open http://localhost:8080  (the login app is at /login)
```

Compose starts PostgreSQL 16, Redis, MinIO, ClamAV, the mock AI gateway, both services, a Celery worker, both web apps and an nginx gateway on one origin. The `seed-auth` and `seed` jobs create demo users, the authority matrix, appetite rules v1, the 30-layout SOV library and process 300 synthetic broker emails, so every queue has work in it.

## Demo accounts (development only)

All demo users share the password `Northstar@2026!`. Underwriter, senior underwriter, CUO and admin require TOTP; the demo authenticator secret is `JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP` (add it to any authenticator app). These values exist only in the seed script and must never be used outside local environments.

| Email | Role | Region |
|---|---|---|
| dataentry@northstar.example | data_entry | west |
| underwriter@northstar.example | underwriter (MFA) | west |
| underwriter.south@northstar.example | underwriter (MFA) | south |
| senior.uw@northstar.example | senior_underwriter (MFA); authority in all regions | west |
| risk.engineer@northstar.example | risk_engineer | west |
| cuo@northstar.example | cuo (MFA) | all |
| distribution@northstar.example | distribution | west |
| admin@northstar.example | admin (MFA) | all |

## Running without Docker

Requires Python 3.12+ and Node 20+. Both services default to SQLite and in-process mocks.

```bash
make install
cd services/auth-service && python -m app.seed && AUTH_COOKIE_SECURE=false uvicorn app.main:app --port 8001
cd services/core-api && python ../../scripts/seed.py --only core --with-data && NSIP_AI_GATEWAY_MODE=inprocess uvicorn app.main:app --port 8000
npm run dev --workspace @nsip/auth-web       # http://localhost:5174/login/
npm run dev --workspace @nsip/workbench-web  # http://localhost:5173 (proxies /api, /auth, /login)
```

## Quality gates

| Command | What it checks |
|---|---|
| `make test-backend` | pytest for both services with an 85% coverage floor (current: auth 93%, core 91%) |
| `make test-frontend` | Vitest for both apps with a 75% floor (current: auth-web 98%, workbench 94% lines) |
| `make lint`, `make typecheck` | Ruff, mypy, TypeScript strict |
| `make eval` | Spec section 15 acceptance report written to `eval/reports/` |
| `make e2e` | Playwright journeys against a running stack, including the timed review |
| `make load` | Locust read-load test (p95 target 300 ms) |

The latest evaluation results are in [eval/reports/eval_report.md](eval/reports/eval_report.md).

## Key documents

- [Architecture](docs/architecture.md) and [ADRs](docs/adr/)
- [Governance mapping](docs/governance/governance-mapping.md) (IRDAI file-and-use, authority matrix, DPDP, AI policy)
- [Runbooks](docs/runbooks/)
- [Open decisions](docs/open-decisions.md)
- [Executive summary](docs/executive-summary.md)
- [Deploying the demo to Google Cloud](docs/deploy-gcp.md)
- OpenAPI: [core-api](docs/api/core-api.openapi.json), [auth-service](docs/api/auth-service.openapi.json)

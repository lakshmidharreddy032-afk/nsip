# Deploying the NSIP demo to Google Cloud

This guide is for someone new to Google Cloud. One script creates a working demo on Cloud Run in Mumbai (`asia-south1`). It is a demo environment: load only the synthetic data, never real broker or customer data.

## What gets created

| Resource | Purpose |
|---|---|
| Cloud Run service `nsip` | Public HTTPS entry point; serves both web apps and proxies `/api` and `/auth` on one origin |
| Cloud Run service `nsip-auth-service` | Sign-in service; seeds demo users with newly generated credentials at start-up |
| Cloud Run service `nsip-core-api` | Workbench API; loads rules, brokers and 300 synthetic submissions at start-up |
| Artifact Registry `nsip` | Container images |
| Service account `nsip-runtime` | Runtime identity with no project roles |

Each backend keeps a built-in database, so the demo needs no database server, storage bucket or secret store. Data resets when Google restarts an instance. Expect roughly USD 10-20 per month, mainly for keeping one instance of each backend warm.

## Requirements for the Google Cloud project

| Requirement | Why |
|---|---|
| Billing enabled | Cloud Run and Cloud Build are paid services (new accounts get free trial credit) |
| You can create a Cloud Storage bucket | `gcloud builds submit` stages the source code in a bucket |
| You can make a Cloud Run service public (`run.services.setIamPolicy`, part of the Owner role) | Otherwise the site returns 403 to every visitor |

A personal project where you are Owner meets all three. Locked-down training projects often do not.

## One-time setup

1. Open https://console.cloud.google.com, create a project and note its **project ID**.
2. Link a billing account to the project.
3. On this machine, run `gcloud auth login` and sign in.

## Deploy

From the repository root in PowerShell:

```powershell
./scripts/deploy_gcp.ps1 -ProjectId YOUR_PROJECT_ID
```

The first run takes about 20-30 minutes, mostly image builds. When it finishes, it prints the URL and writes the demo logins to `%USERPROFILE%\nsip-gcp-demo-credentials.txt`. That file sits outside the repository on purpose: the cloud demo uses newly generated passwords and an MFA secret, not the development values published in the README. Re-running the script keeps the same logins.

## Demo limitations (differences from the production design)

| Production design | Cloud Run demo |
|---|---|
| PostgreSQL 16 with persistent data | Built-in SQLite per service, reset on restart |
| Celery workers and Redis | Pipeline runs inside core-api; one instance |
| Object storage for originals | Container-local storage |
| ClamAV antivirus | Mock scanner (EICAR test signature only) |
| India-hosted AI gateway | Built-in deterministic mock |
| Regional shared mailboxes via MS Graph | Not connected; use the seeded data or Admin "upload .eml" |

For production, use the Helm chart in `infra/helm/nsip` (GKE), or Cloud Run with Cloud SQL, Memorystore and Secret Manager. That route needs the runtime service account to hold `roles/cloudsql.client` and `roles/secretmanager.secretAccessor`.

## Remove everything

```powershell
./scripts/destroy_gcp.ps1 -ProjectId YOUR_PROJECT_ID
```

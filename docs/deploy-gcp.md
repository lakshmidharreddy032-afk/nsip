# Deploying the NSIP demo to Google Cloud

This guide is for someone new to Google Cloud. One script creates a working demo on Cloud Run in Mumbai (`asia-south1`), keeping data in India. It is a demo environment: do not load real broker or customer data into it.

## What gets created

| Resource | Purpose | Approx. cost |
|---|---|---|
| Cloud Run service `nsip` | Public HTTPS entry point; serves both web apps and proxies `/api` and `/auth` | Pay per request; near zero when idle |
| Cloud Run services `nsip-core-api`, `nsip-auth-service` | The two backend services | Pay per request |
| Cloud SQL PostgreSQL 16 `nsip-pg` (db-f1-micro) | Databases `nsip` and `nsip_auth` | About USD 10-15 per month, charged even when idle |
| Cloud Storage bucket | Original emails and attachments | Cents |
| Artifact Registry `nsip` | Container images | Cents |
| Secret Manager | Generated DB password, signing key, data key, demo credentials | Cents |

Expect roughly USD 15-25 per month. Run `scripts/destroy_gcp.ps1` to delete everything when you are finished.

## One-time setup

1. Create a Google account if you do not have one, then open https://console.cloud.google.com.
2. Create a project (top bar, "Select a project", "New project"). Note the **project ID** (for example `nsip-demo-123456`).
3. Turn on billing for the project (Billing, "Link a billing account"). New accounts usually get free trial credit.
4. Sign in from this machine: `gcloud auth login` (a browser window opens).

## Deploy

From the repository root in PowerShell:

```powershell
./scripts/deploy_gcp.ps1 -ProjectId YOUR_PROJECT_ID
```

The first run takes about 30 minutes (Cloud SQL creation and image builds). When it finishes it prints the URL and writes demo credentials to `%USERPROFILE%\nsip-gcp-demo-credentials.txt`. That file sits outside the repository on purpose. The cloud environment uses newly generated credentials, not the demo values published in the README, because the repository is public.

Re-running the script is safe: it reuses existing resources and secrets and deploys new images.

## Demo limitations (differences from the production design)

| Production design | Cloud Run demo |
|---|---|
| Celery workers and Redis, autoscaled on queue depth | Pipeline runs inside core-api; single instance |
| ClamAV antivirus container | Mock scanner (EICAR test signature only) |
| India-hosted AI gateway | Built-in deterministic mock |
| Regional shared mailboxes via MS Graph | Not connected; data comes from the seeded synthetic mailbox or Admin "upload .eml" |
| Internal-only service ingress | All three services publicly reachable; backend APIs still require tokens |

Production should use the Helm chart in `infra/helm/nsip` on GKE, or Cloud Run with internal ingress, Memorystore and a VPC connector.

## Remove everything

```powershell
./scripts/destroy_gcp.ps1 -ProjectId YOUR_PROJECT_ID
```

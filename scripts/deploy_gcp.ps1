<#
.SYNOPSIS
  Deploys an NSIP demo environment to Google Cloud Run in asia-south1 (Mumbai).

.DESCRIPTION
  Creates (idempotently): required APIs, Artifact Registry repo, Cloud SQL PostgreSQL 16 (smallest tier),
  a GCS bucket for originals, a runtime service account, Secret Manager secrets with freshly generated
  values, three images via Cloud Build, three Cloud Run services (auth-service, core-api, gateway) and
  two seed jobs. Prints the public URL. Demo credentials are written OUTSIDE the repository.

  Demo scope (see docs/deploy-gcp.md): pipeline runs inline (no Redis/Celery workers), ClamAV and the AI
  gateway are mocks, mailboxes are not connected. Not for production data.

.EXAMPLE
  ./scripts/deploy_gcp.ps1 -ProjectId my-nsip-demo
#>
param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "asia-south1",
  [string]$Tag = "v1",
  [string]$Python = "$PSScriptRoot\..\..\.venv\Scripts\python.exe",
  [string]$CredentialsFile = "$env:USERPROFILE\nsip-gcp-demo-credentials.txt"
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."
function Invoke-G { param([string[]]$GArgs) & gcloud @GArgs; if ($LASTEXITCODE -ne 0) { throw "gcloud $($GArgs -join ' ') failed" } }
function Test-G { param([string[]]$GArgs) & gcloud @GArgs *> $null; return ($LASTEXITCODE -eq 0) }
function New-Token([int]$n = 32) { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count $n | ForEach-Object { [char]$_ }) }

Write-Host "== Project $ProjectId, region $Region"
Invoke-G @("config", "set", "project", $ProjectId)
Invoke-G @("services", "enable", "run.googleapis.com", "sqladmin.googleapis.com", "artifactregistry.googleapis.com",
  "cloudbuild.googleapis.com", "secretmanager.googleapis.com", "storage.googleapis.com", "iam.googleapis.com")

$repo = "$Region-docker.pkg.dev/$ProjectId/nsip"
if (-not (Test-G @("artifacts", "repositories", "describe", "nsip", "--location", $Region))) {
  Invoke-G @("artifacts", "repositories", "create", "nsip", "--repository-format", "docker", "--location", $Region)
}

# ---- runtime identity
$sa = "nsip-runtime@$ProjectId.iam.gserviceaccount.com"
if (-not (Test-G @("iam", "service-accounts", "describe", $sa))) {
  Invoke-G @("iam", "service-accounts", "create", "nsip-runtime", "--display-name", "NSIP Cloud Run runtime")
}
foreach ($role in @("roles/cloudsql.client", "roles/secretmanager.secretAccessor")) {
  Invoke-G @("projects", "add-iam-policy-binding", $ProjectId, "--member", "serviceAccount:$sa", "--role", $role, "--condition", "None", "--quiet")
}

# ---- storage for originals (encrypted at rest by default, uniform access, no public access)
$bucket = "$ProjectId-nsip-originals"
if (-not (Test-G @("storage", "buckets", "describe", "gs://$bucket"))) {
  Invoke-G @("storage", "buckets", "create", "gs://$bucket", "--location", $Region, "--uniform-bucket-level-access", "--public-access-prevention")
}
Invoke-G @("storage", "buckets", "add-iam-policy-binding", "gs://$bucket", "--member", "serviceAccount:$sa", "--role", "roles/storage.objectAdmin")

# ---- secrets (generated once; re-runs keep existing values)
function Set-Secret([string]$name, [string]$value) {
  if (-not (Test-G @("secrets", "describe", $name))) {
    $tmp = New-TemporaryFile
    [IO.File]::WriteAllText($tmp, $value)
    Invoke-G @("secrets", "create", $name, "--replication-policy", "automatic", "--data-file", $tmp)
    Remove-Item $tmp
    return $true
  }
  return $false
}
function Get-Secret([string]$name) { (& gcloud secrets versions access latest --secret $name) -join "`n" }

$dbPassword = New-Token 28
[void](Set-Secret "nsip-db-password" $dbPassword); $dbPassword = Get-Secret "nsip-db-password"
[void](Set-Secret "nsip-internal-token" (New-Token 40))
[void](Set-Secret "nsip-reset-secret" (New-Token 48))
$fernet = & $Python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
[void](Set-Secret "nsip-auth-data-key" $fernet)
$pem = (& $Python -c "from cryptography.hazmat.primitives.asymmetric import rsa;from cryptography.hazmat.primitives import serialization as s;k=rsa.generate_private_key(public_exponent=65537,key_size=2048);print(k.private_bytes(s.Encoding.PEM,s.PrivateFormat.PKCS8,s.NoEncryption()).decode())") -join "`n"
[void](Set-Secret "nsip-auth-signing-key" $pem)
$demoPassword = "Ns" + (New-Token 14) + "!7"
[void](Set-Secret "nsip-demo-password" $demoPassword); $demoPassword = Get-Secret "nsip-demo-password"
$totp = & $Python -c "import pyotp;print(pyotp.random_base32())"
[void](Set-Secret "nsip-demo-totp" $totp); $totp = Get-Secret "nsip-demo-totp"

# ---- Cloud SQL (smallest shared-core tier; about USD 10/month)
$instance = "nsip-pg"
if (-not (Test-G @("sql", "instances", "describe", $instance))) {
  Write-Host "== Creating Cloud SQL instance (takes ~10 minutes)"
  Invoke-G @("sql", "instances", "create", $instance, "--database-version", "POSTGRES_16", "--edition", "enterprise",
    "--tier", "db-f1-micro", "--region", $Region, "--storage-size", "10", "--storage-auto-increase", "--backup-start-time", "21:00")
}
foreach ($db in @("nsip", "nsip_auth")) {
  if (-not (Test-G @("sql", "databases", "describe", $db, "--instance", $instance))) { Invoke-G @("sql", "databases", "create", $db, "--instance", $instance) }
}
if (-not ((& gcloud sql users list --instance $instance --format "value(name)") -contains "nsip")) {
  Invoke-G @("sql", "users", "create", "nsip", "--instance", $instance, "--password", $dbPassword)
} else {
  Invoke-G @("sql", "users", "set-password", "nsip", "--instance", $instance, "--password", $dbPassword)
}
$conn = "${ProjectId}:${Region}:$instance"
$coreDb = "postgresql+psycopg://nsip:$dbPassword@/nsip?host=/cloudsql/$conn"
$authDb = "postgresql+psycopg://nsip:$dbPassword@/nsip_auth?host=/cloudsql/$conn"
[void](Set-Secret "nsip-core-db-url" $coreDb); [void](Set-Secret "nsip-auth-db-url" $authDb)

# ---- build images
Write-Host "== Building images with Cloud Build (10-20 minutes)"
Push-Location $root
Invoke-G @("builds", "submit", "--config", "infra/gcp/cloudbuild.yaml", "--substitutions", "_REPO=$repo,_TAG=$Tag", ".")
Pop-Location

$common = @("--region", $Region, "--service-account", $sa, "--add-cloudsql-instances", $conn, "--quiet")

# ---- auth-service (single instance keeps lockout/rate-limit state consistent in the demo)
Invoke-G (@("run", "deploy", "nsip-auth-service", "--image", "$repo/auth-service:$Tag", "--port", "8001", "--allow-unauthenticated",
  "--max-instances", "1", "--memory", "512Mi",
  "--set-env-vars", "AUTH_ENV=demo,AUTH_DB_SCHEMA=auth,AUTH_COOKIE_SECURE=true,AUTH_KEY_ID=nsip-gcp-1",
  "--set-secrets", "AUTH_DATABASE_URL=nsip-auth-db-url:latest,AUTH_PRIVATE_KEY_PEM=nsip-auth-signing-key:latest,AUTH_DATA_KEY=nsip-auth-data-key:latest,AUTH_RESET_SECRET=nsip-reset-secret:latest,AUTH_INTERNAL_SERVICE_TOKEN=nsip-internal-token:latest") + $common)
$authUrl = (& gcloud run services describe nsip-auth-service --region $Region --format "value(status.url)")

# ---- core-api (single instance: in-process SSE fan-out and inline pipeline for the demo)
$coreEnv = "NSIP_ENV=demo,NSIP_OBJECT_STORE=gcs,NSIP_S3_BUCKET=$bucket,NSIP_AI_GATEWAY_MODE=inprocess,NSIP_AUTH_JWKS_URL=$authUrl/.well-known/jwks.json,NSIP_AUTH_SERVICE_URL=$authUrl,WEB_CONCURRENCY=1,NSIP_MAX_JSON_BODY_BYTES=1048576"
Invoke-G (@("run", "deploy", "nsip-core-api", "--image", "$repo/core-api:$Tag", "--port", "8000", "--allow-unauthenticated",
  "--max-instances", "1", "--memory", "1Gi", "--cpu", "1", "--timeout", "3600",
  "--set-env-vars", $coreEnv,
  "--set-secrets", "NSIP_DATABASE_URL=nsip-core-db-url:latest,NSIP_INTERNAL_SERVICE_TOKEN=nsip-internal-token:latest") + $common)
$coreUrl = (& gcloud run services describe nsip-core-api --region $Region --format "value(status.url)")

# ---- gateway (public entry point)
$coreHost = ([Uri]$coreUrl).Host; $authHost = ([Uri]$authUrl).Host
Invoke-G @("run", "deploy", "nsip", "--image", "$repo/gateway:$Tag", "--port", "8080", "--allow-unauthenticated", "--region", $Region,
  "--memory", "256Mi", "--max-instances", "3", "--set-env-vars", "CORE_HOST=$coreHost,AUTH_HOST=$authHost", "--quiet")
$appUrl = (& gcloud run services describe nsip --region $Region --format "value(status.url)")

# ---- seed jobs (users with generated credentials; reference data; 300 synthetic submissions)
$seedSecrets = "SEED_PASSWORD=nsip-demo-password:latest,SEED_TOTP_SECRET=nsip-demo-totp:latest"
Invoke-G (@("run", "jobs", "deploy", "nsip-seed-auth", "--image", "$repo/auth-service:$Tag", "--command", "sh", "--args", "-c,alembic upgrade head && python -m app.seed",
  "--set-env-vars", "AUTH_DB_SCHEMA=auth",
  "--set-secrets", "AUTH_DATABASE_URL=nsip-auth-db-url:latest,AUTH_DATA_KEY=nsip-auth-data-key:latest,$seedSecrets", "--task-timeout", "600") + $common)
Invoke-G @("run", "jobs", "execute", "nsip-seed-auth", "--region", $Region, "--wait")
Invoke-G (@("run", "jobs", "deploy", "nsip-seed-core", "--image", "$repo/core-api:$Tag", "--command", "sh",
  "--args", "-c,alembic upgrade head && python /srv/scripts/seed.py --only core --with-data", "--memory", "2Gi", "--cpu", "2",
  "--set-env-vars", "$coreEnv,SEED_DATA_DIR=/tmp/nsip-demo,NSIP_MAILBOX_DIR=/tmp/mailbox",
  "--set-secrets", "NSIP_DATABASE_URL=nsip-core-db-url:latest,NSIP_INTERNAL_SERVICE_TOKEN=nsip-internal-token:latest", "--task-timeout", "1800") + $common)
Invoke-G @("run", "jobs", "execute", "nsip-seed-core", "--region", $Region, "--wait")

@"
NSIP Google Cloud demo - keep this file private. Do not commit it.
URL:            $appUrl
Password (all demo users): $demoPassword
TOTP secret for MFA users (add to an authenticator app): $totp
Users: dataentry@, underwriter@, underwriter.south@, senior.uw@, risk.engineer@, cuo@, distribution@, admin@  (all @northstar.example)
Delete everything: ./scripts/destroy_gcp.ps1 -ProjectId $ProjectId
"@ | Set-Content -Path $CredentialsFile -Encoding utf8
Write-Host "== Done. Open $appUrl"
Write-Host "== Demo credentials written to $CredentialsFile"

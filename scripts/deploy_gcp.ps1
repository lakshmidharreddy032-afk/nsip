<#
.SYNOPSIS
  Deploys a self-contained NSIP demo to Google Cloud Run in asia-south1 (Mumbai).

.DESCRIPTION
  Designed for restricted projects (Editor role, no IAM grants, strict org policies). It needs only
  Cloud Run, Artifact Registry and Cloud Build:
    * nsip-auth-service and nsip-core-api each keep a built-in SQLite database and seed themselves at
      start-up (demo users with generated credentials, rules, brokers, 300 synthetic submissions);
    * nsip (gateway) serves both web apps and proxies /api and /auth on one HTTPS origin.
  Data resets whenever Google restarts an instance. Generated secrets are kept in a state file in your
  user profile (outside the repository) so re-runs keep the same logins.

.EXAMPLE
  ./scripts/deploy_gcp.ps1 -ProjectId my-nsip-demo
#>
param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "asia-south1",
  [string]$Tag = "v1",
  [string]$Python = "$PSScriptRoot\..\..\.venv\Scripts\python.exe",
  [string]$StateFile = "$env:USERPROFILE\.nsip-gcp-state.json",
  [string]$CredentialsFile = "$env:USERPROFILE\nsip-gcp-demo-credentials.txt",
  [switch]$SkipBuild
)
# gcloud writes notices to stderr; success is judged by exit codes, not by stderr output.
$ErrorActionPreference = "Continue"
$gc = (Get-Command gcloud.cmd -ErrorAction Stop).Source
$root = Resolve-Path "$PSScriptRoot\.."
function Invoke-G { param([string[]]$GArgs) & $gc @GArgs; if ($LASTEXITCODE -ne 0) { throw "gcloud $($GArgs -join ' ') failed" } }
function Test-G { param([string[]]$GArgs) & $gc @GArgs *> $null; return ($LASTEXITCODE -eq 0) }
function New-Token([int]$n = 32) { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count $n | ForEach-Object { [char]$_ }) }

Write-Host "== Project $ProjectId, region $Region"
Invoke-G @("config", "set", "project", $ProjectId)
Invoke-G @("services", "enable", "run.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com")

$repo = "$Region-docker.pkg.dev/$ProjectId/nsip"
if (-not (Test-G @("artifacts", "repositories", "describe", "nsip", "--location", $Region))) {
  Invoke-G @("artifacts", "repositories", "create", "nsip", "--repository-format", "docker", "--location", $Region)
}
$sa = "nsip-runtime@$ProjectId.iam.gserviceaccount.com"   # identity with no project roles (least privilege)
if (-not (Test-G @("iam", "service-accounts", "describe", $sa))) {
  Invoke-G @("iam", "service-accounts", "create", "nsip-runtime", "--display-name", "NSIP Cloud Run runtime")
}

# ---- generated secrets, persisted outside the repository
if (Test-Path $StateFile) {
  $state = Get-Content $StateFile -Raw | ConvertFrom-Json
} else {
  Write-Host "== Generating credentials and keys"
  $state = [pscustomobject]@{
    internal_token = New-Token 40
    reset_secret   = New-Token 48
    data_key       = (& $Python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
    signing_key    = ((& $Python -c "from cryptography.hazmat.primitives.asymmetric import rsa;from cryptography.hazmat.primitives import serialization as s;k=rsa.generate_private_key(public_exponent=65537,key_size=2048);print(k.private_bytes(s.Encoding.PEM,s.PrivateFormat.PKCS8,s.NoEncryption()).decode())") -join "`n")
    demo_password  = "Ns" + (New-Token 14) + "!7"
    totp_secret    = (& $Python -c "import pyotp;print(pyotp.random_base32())")
  }
  $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding utf8
}

# ---- images
if (-not $SkipBuild) {
  Write-Host "== Building images with Cloud Build (10-20 minutes)"
  Push-Location $root
  Invoke-G @("builds", "submit", "--config", "infra/gcp/cloudbuild.yaml", "--substitutions", "_REPO=$repo,_TAG=$Tag", ".")
  Pop-Location
}

function Write-EnvFile([hashtable]$vars) {
  $f = Join-Path $env:TEMP ("nsip-env-" + [guid]::NewGuid().ToString("N") + ".yaml")
  ($vars | ConvertTo-Json) | Set-Content -Path $f -Encoding utf8   # JSON is valid YAML
  return $f
}

# ---- auth-service (seeds demo users at start-up; one instance holds the demo database)
$authEnv = Write-EnvFile @{
  AUTH_ENV = "demo"; AUTH_COOKIE_SECURE = "true"; AUTH_KEY_ID = "nsip-gcp-1"
  AUTH_PRIVATE_KEY_PEM = $state.signing_key; AUTH_DATA_KEY = $state.data_key; AUTH_RESET_SECRET = $state.reset_secret
  AUTH_INTERNAL_SERVICE_TOKEN = $state.internal_token; SEED_PASSWORD = $state.demo_password; SEED_TOTP_SECRET = $state.totp_secret
}
Write-Host "== Deploying nsip-auth-service"
Invoke-G @("run", "deploy", "nsip-auth-service", "--image", "$repo/auth-service:$Tag", "--region", $Region, "--service-account", $sa,
  "--port", "8001", "--allow-unauthenticated", "--min-instances", "1", "--max-instances", "1", "--memory", "512Mi", "--cpu-boost",
  "--env-vars-file", $authEnv, "--command", "sh",
  "--args", "-c,alembic upgrade head && python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips=*",
  "--quiet")
Remove-Item $authEnv
$authUrl = (& $gc run services describe nsip-auth-service --region $Region --format "value(status.url)")

# ---- core-api (seeds reference data and the synthetic mailbox at start-up)
$coreEnv = Write-EnvFile @{
  NSIP_ENV = "demo"; NSIP_AI_GATEWAY_MODE = "inprocess"; NSIP_AUTH_JWKS_URL = "$authUrl/.well-known/jwks.json"
  NSIP_AUTH_SERVICE_URL = $authUrl; NSIP_INTERNAL_SERVICE_TOKEN = $state.internal_token; SEED_DATA_DIR = "/tmp/nsip-demo"
}
Write-Host "== Deploying nsip-core-api (first start loads 300 synthetic submissions; 1-3 minutes)"
Invoke-G @("run", "deploy", "nsip-core-api", "--image", "$repo/core-api:$Tag", "--region", $Region, "--service-account", $sa,
  "--port", "8000", "--allow-unauthenticated", "--min-instances", "1", "--max-instances", "1", "--memory", "2Gi", "--cpu", "2",
  "--cpu-boost", "--timeout", "3600", "--env-vars-file", $coreEnv, "--command", "sh",
  "--args", "-c,alembic upgrade head && python /srv/scripts/seed.py --only core --with-data && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*",
  "--quiet")
Remove-Item $coreEnv
$coreUrl = (& $gc run services describe nsip-core-api --region $Region --format "value(status.url)")

# ---- gateway (public entry point)
Write-Host "== Deploying nsip gateway"
Invoke-G @("run", "deploy", "nsip", "--image", "$repo/gateway:$Tag", "--region", $Region, "--service-account", $sa,
  "--port", "8080", "--allow-unauthenticated", "--memory", "256Mi", "--max-instances", "2",
  "--set-env-vars", "CORE_HOST=$(([Uri]$coreUrl).Host),AUTH_HOST=$(([Uri]$authUrl).Host)", "--quiet")
$appUrl = (& $gc run services describe nsip --region $Region --format "value(status.url)")

@"
NSIP Google Cloud demo - keep this file private. Do not commit it.
URL:            $appUrl  (sign in at $appUrl/login/)
Password (all demo users): $($state.demo_password)
TOTP secret for MFA users (add to an authenticator app): $($state.totp_secret)
Users (all @northstar.example): dataentry, underwriter, underwriter.south, senior.uw, risk.engineer, cuo, distribution, admin
MFA required for: underwriter, underwriter.south, senior.uw, cuo, admin
Data resets when Google restarts the service. Delete everything: ./scripts/destroy_gcp.ps1 -ProjectId $ProjectId
"@ | Set-Content -Path $CredentialsFile -Encoding utf8
Write-Host "== Done. Open $appUrl"
Write-Host "== Demo credentials written to $CredentialsFile"

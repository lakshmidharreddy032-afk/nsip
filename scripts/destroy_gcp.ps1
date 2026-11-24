<#
.SYNOPSIS
  Deletes the NSIP Cloud Run demo so it stops costing money. Irreversible: data in Cloud SQL and GCS is lost.
#>
param([Parameter(Mandatory = $true)][string]$ProjectId, [string]$Region = "asia-south1")
gcloud config set project $ProjectId
foreach ($s in @("nsip", "nsip-core-api", "nsip-auth-service")) { gcloud run services delete $s --region $Region --quiet }
foreach ($j in @("nsip-seed-auth", "nsip-seed-core")) { gcloud run jobs delete $j --region $Region --quiet }
gcloud sql instances delete nsip-pg --quiet
gcloud storage rm -r "gs://$ProjectId-nsip-originals"
gcloud artifacts repositories delete nsip --location $Region --quiet
foreach ($sec in @("nsip-db-password", "nsip-internal-token", "nsip-reset-secret", "nsip-auth-data-key", "nsip-auth-signing-key",
    "nsip-demo-password", "nsip-demo-totp", "nsip-core-db-url", "nsip-auth-db-url")) { gcloud secrets delete $sec --quiet }
Write-Host "NSIP demo resources deleted."

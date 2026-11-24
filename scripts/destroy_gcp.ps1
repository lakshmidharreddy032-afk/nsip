<#
.SYNOPSIS
  Deletes the NSIP Cloud Run demo so it stops costing money. Irreversible.
#>
param([Parameter(Mandatory = $true)][string]$ProjectId, [string]$Region = "asia-south1")
$gc = (Get-Command gcloud.cmd -ErrorAction Stop).Source
& $gc config set project $ProjectId
foreach ($s in @("nsip", "nsip-core-api", "nsip-auth-service")) { & $gc run services delete $s --region $Region --quiet }
& $gc artifacts repositories delete nsip --location $Region --quiet
& $gc iam service-accounts delete "nsip-runtime@$ProjectId.iam.gserviceaccount.com" --quiet
Remove-Item "$env:USERPROFILE\.nsip-gcp-state.json", "$env:USERPROFILE\nsip-gcp-demo-credentials.txt" -ErrorAction SilentlyContinue
Write-Host "NSIP demo resources deleted."

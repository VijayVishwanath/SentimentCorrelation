<#
.SYNOPSIS
  Deploy DEX Sentinel to Google Cloud Run (demo tier). Safe to re-run: it creates what is missing and redeploys.

.EXAMPLE
  .\deploy\gcp\deploy.ps1 -ProjectId my-gcp-project
.EXAMPLE
  .\deploy\gcp\deploy.ps1 -ProjectId my-gcp-project -NoLlm             # Copilot uses the offline template engine
.EXAMPLE
  .\deploy\gcp\deploy.ps1 -ProjectId my-gcp-project -UpdateAnthropicKey # store a new Anthropic key version
.EXAMPLE
  .\deploy\gcp\deploy.ps1 -ProjectId my-gcp-project -MinInstances 1     # demo day: no cold starts
#>
param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [string]$Region = "asia-south1",
    [string]$Service = "dex-sentinel",
    [int]$MinInstances = 0,
    [switch]$NoLlm,
    [switch]$UpdateAnthropicKey,
    [switch]$RotateAccessKey
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SaName = "$Service-run"
$SaEmail = "$SaName@$ProjectId.iam.gserviceaccount.com"
$AccessSecret = "dex-api-key"
$LlmSecret = "anthropic-api-key"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
# gcloud writes progress to stderr. In Windows PowerShell 5.1 a *redirected* native stderr line becomes an
# error record, which "Stop" turns into an exception - so redirected calls relax the preference locally.
function Invoke-Gcloud { & gcloud @args; if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') failed ($LASTEXITCODE)" } }
function Invoke-GcloudQuiet { $ErrorActionPreference = "Continue"; & gcloud @args *> $null
    if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') failed ($LASTEXITCODE)" } }
function Get-GcloudOutput { $ErrorActionPreference = "Continue"; $o = & gcloud @args 2>$null
    if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') failed ($LASTEXITCODE)" }; return (($o | Out-String).Trim()) }
function Test-Gcloud { $ErrorActionPreference = "Continue"; & gcloud @args *> $null; return ($LASTEXITCODE -eq 0) }

function Set-SecretValue([string]$Name, [string]$Value) {
    # write without a trailing newline (piping to gcloud would add one and corrupt the key)
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, $Value)
        if (Test-Gcloud secrets describe $Name --project $ProjectId) {
            Invoke-GcloudQuiet secrets versions add $Name --data-file=$tmp --project $ProjectId --quiet
        } else {
            Invoke-GcloudQuiet secrets create $Name --data-file=$tmp --replication-policy=automatic --project $ProjectId --quiet
        }
    } finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------------- 0. prerequisites
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw "Google Cloud CLI not found. Install it (winget install Google.CloudSDK), open a new terminal, run 'gcloud auth login', then re-run this script."
}
$account = try { Get-GcloudOutput config get-value account } catch { "" }
if (-not $account) { throw "Not logged in. Run: gcloud auth login" }
Write-Host "Deploying as $account to project $ProjectId ($Region)" -ForegroundColor Green
Invoke-Gcloud config set project $ProjectId --quiet

# ---------------------------------------------------------------- 1. APIs
Step "Enabling required APIs (first run takes a minute)"
Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project $ProjectId

# ---------------------------------------------------------------- 2. runtime service account (least privilege)
Step "Service account $SaEmail"
if (-not (Test-Gcloud iam service-accounts describe $SaEmail --project $ProjectId)) {
    Invoke-Gcloud iam service-accounts create $SaName --display-name "DEX Sentinel Cloud Run runtime" --project $ProjectId
}

# Builds from source run as the Compute Engine default SA; newer projects need the Cloud Run Builder role on it.
$projectNumber = Get-GcloudOutput projects describe $ProjectId --format "value(projectNumber)"
try {
    Invoke-GcloudQuiet projects add-iam-policy-binding $ProjectId --member "serviceAccount:$projectNumber-compute@developer.gserviceaccount.com" `
        --role roles/run.builder --condition None --quiet
} catch { Write-Warning "Could not grant roles/run.builder to the build service account (needs Project IAM Admin). If the build fails with a permission error, ask your admin to grant it." }

# ---------------------------------------------------------------- 3. secrets
Step "Secrets in Secret Manager"
if ($RotateAccessKey -or -not (Test-Gcloud secrets describe $AccessSecret --project $ProjectId)) {
    $chars = [char[]]"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $accessKey = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
    Set-SecretValue $AccessSecret $accessKey
    Write-Host "Generated a new access key ($AccessSecret)."
}
Invoke-GcloudQuiet secrets add-iam-policy-binding $AccessSecret --member "serviceAccount:$SaEmail" --role roles/secretmanager.secretAccessor --project $ProjectId --quiet

$secretsArg = "DEX_API_KEY=${AccessSecret}:latest"
$llmProvider = "template"
if (-not $NoLlm) {
    if ($UpdateAnthropicKey -or -not (Test-Gcloud secrets describe $LlmSecret --project $ProjectId)) {
        $secure = Read-Host "Paste your Anthropic API key (input hidden)" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        if (-not $plain) { throw "No Anthropic key entered (use -NoLlm to deploy without one)." }
        Set-SecretValue $LlmSecret $plain
        $plain = $null
    }
    Invoke-GcloudQuiet secrets add-iam-policy-binding $LlmSecret --member "serviceAccount:$SaEmail" --role roles/secretmanager.secretAccessor --project $ProjectId --quiet
    $secretsArg += ",ANTHROPIC_API_KEY=${LlmSecret}:latest"
    $llmProvider = "auto"
}

# ---------------------------------------------------------------- 4. build + deploy
Step "Building in Cloud Build and deploying to Cloud Run (5-10 minutes on first run)"
Push-Location $RepoRoot
try {
    Invoke-Gcloud run deploy $Service --source . --region $Region --project $ProjectId --quiet `
        --allow-unauthenticated --use-http2 --no-cpu-throttling --execution-environment gen2 `
        --cpu 2 --memory 8Gi --min-instances $MinInstances --max-instances 1 --concurrency 40 --timeout 900 `
        --service-account $SaEmail `
        --set-env-vars "DEX_ENVIRONMENT=production,DEX_STORAGE_MODE=ephemeral,DEX_LLM_PROVIDER=$llmProvider,DEX_MAX_UPLOAD_MB=200" `
        --set-secrets $secretsArg
} finally { Pop-Location }

# ---------------------------------------------------------------- 5. smoke test + summary
$url = Get-GcloudOutput run services describe $Service --region $Region --project $ProjectId --format "value(status.url)"
$key = Get-GcloudOutput secrets versions access latest --secret $AccessSecret --project $ProjectId
Step "Smoke test"
$health = Invoke-RestMethod "$url/api/health" -TimeoutSec 60
Write-Host "  /api/health           -> $($health.status)"
try { Invoke-RestMethod "$url/api/v1/meta" -TimeoutSec 30 | Out-Null; Write-Warning "  /api/v1/meta answered WITHOUT a key - check DEX_API_KEY" }
catch { Write-Host "  /api/v1/meta (no key) -> 401 as expected" }
$meta = Invoke-RestMethod "$url/api/v1/meta" -Headers @{ "X-API-Key" = $key } -TimeoutSec 60
Write-Host "  /api/v1/meta (key)    -> $($meta.counts.devices) devices, $($meta.counts.tickets) tickets"
$cop = Invoke-RestMethod "$url/api/v1/copilot/status" -Headers @{ "X-API-Key" = $key } -TimeoutSec 30
Write-Host "  Copilot provider      -> $($cop.provider) ($($cop.model))"

Write-Host "`nDEX Sentinel is live" -ForegroundColor Green
Write-Host "  URL        : $url"
Write-Host "  Access key : $key   (share only with demo users; rotate with -RotateAccessKey)"
Write-Host "  Logs       : gcloud run services logs read $Service --region $Region --limit 50"

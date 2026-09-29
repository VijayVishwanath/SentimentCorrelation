<#
.SYNOPSIS  One-command setup and launch of DEX Sentinel (Windows PowerShell).
.EXAMPLE   .\run.ps1                 # install (first run), build UI, serve on http://127.0.0.1:8000
.EXAMPLE   .\run.ps1 -Port 8010      # use another port
.EXAMPLE   .\run.ps1 -Dev            # API with reload + Vite dev server on :5173
.EXAMPLE   .\run.ps1 -Test           # run the backend test suite
#>
param([int]$Port = 8000, [switch]$Dev, [switch]$Test, [switch]$SkipBuild)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv (Join-Path $root ".venv")
    & $py -m pip install --upgrade pip | Out-Null
}
& $py -m pip install -q -r (Join-Path $root "backend\requirements-dev.txt")

if ($Test) {
    Push-Location (Join-Path $root "backend"); & $py -m pytest -q; Pop-Location; exit $LASTEXITCODE
}

$fe = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $fe "node_modules"))) { Push-Location $fe; npm install --no-audit --no-fund; Pop-Location }

Push-Location (Join-Path $root "backend")
if ($Dev) {
    $env:DEX_API_URL = "http://127.0.0.1:$Port"
    Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory $fe
    Write-Host "UI (dev): http://localhost:5173   API: http://127.0.0.1:$Port/docs" -ForegroundColor Green
    & $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
} else {
    if (-not $SkipBuild) { Push-Location $fe; npm run build; Pop-Location }
    Write-Host "DEX Sentinel: http://127.0.0.1:$Port   (API docs: /docs)" -ForegroundColor Green
    & $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port
}
Pop-Location

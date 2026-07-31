# =============================================================
#  scripts/run_local.ps1
#  VakıfBank FaaS Platform — Windows Local Development Runner
#
#  Usage:
#    cd d:\Vakifbank-FaaS-Project
#    .\scripts\run_local.ps1
#
#  What it does:
#    1. Creates a Python virtual environment (if missing)
#    2. Installs / updates dependencies from requirements.txt
#    3. Runs the startup health check (shows which tools are available)
#    4. Launches uvicorn in --reload mode on http://localhost:8000
# =============================================================

$ErrorActionPreference = "Stop"

# ── Paths ─────────────────────────────────────────────────────────────────────
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendDir  = Join-Path $ProjectRoot "backend"
$VenvDir     = Join-Path $ProjectRoot ".venv"
$PythonExe   = if (Test-Path "$VenvDir\Scripts\python.exe") {
                   "$VenvDir\Scripts\python.exe"
               } else { "python" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VakifBank FaaS Platform - Local Development Server" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Virtual environment ───────────────────────────────────────────────
if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host "[1/3] Creating virtual environment at .venv ..." -ForegroundColor Yellow
    python -m venv $VenvDir
    Write-Host "      Done." -ForegroundColor Green
} else {
    Write-Host "[1/3] Virtual environment already exists. Skipping." -ForegroundColor Green
}
$PythonExe = "$VenvDir\Scripts\python.exe"
$PipExe    = "$VenvDir\Scripts\pip.exe"

# ── Step 2: Install dependencies ──────────────────────────────────────────────
Write-Host "[2/3] Installing / updating dependencies ..." -ForegroundColor Yellow
& $PythonExe -m pip install --quiet --upgrade pip
& $PythonExe -m pip install --quiet -r "$BackendDir\requirements.txt"
Write-Host "      Done." -ForegroundColor Green

# ── Step 3: Health check ───────────────────────────────────────────────────────
Write-Host "[3/3] Running startup health check ..." -ForegroundColor Yellow
Write-Host ""
# Run from backend dir so relative imports resolve correctly
Push-Location $BackendDir
& $PythonExe health_check.py
$healthExit = $LASTEXITCODE
Pop-Location

if ($healthExit -ne 0) {
    Write-Host ""
    Write-Host "  WARNING: Some critical tools are missing." -ForegroundColor Red
    Write-Host "  The UI and /health endpoint will still work, but /deploy will fail" -ForegroundColor Yellow
    Write-Host "  until kubectl and func CLI are installed and a cluster is reachable." -ForegroundColor Yellow
    Write-Host ""
    $continue = Read-Host "  Continue anyway? [Y/n]"
    if ($continue -eq "n" -or $continue -eq "N") { exit 1 }
}

# ── Launch uvicorn ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting FastAPI server ..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  UI       -> http://localhost:8000" -ForegroundColor White
Write-Host "  API Docs -> http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Health   -> http://localhost:8000/health" -ForegroundColor White
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Run uvicorn FROM the backend/ directory so 'from config import' resolves correctly
Push-Location $BackendDir
& $PythonExe -m uvicorn main:app `
    --reload `
    --host 0.0.0.0 `
    --port 8000 `
    --log-level info `
    --loop asyncio
Pop-Location

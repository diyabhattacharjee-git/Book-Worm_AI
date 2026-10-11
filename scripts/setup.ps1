# One-time local setup on Windows (PowerShell). Run from the repository root:  ./scripts/setup.ps1
# Native tools write progress to stderr, so failures are detected via exit codes, not stderr.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Step([string]$what, [scriptblock]$cmd) {
    & $cmd 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $what" -ForegroundColor Red; exit 1 }
}

Write-Host "== Backend ==" -ForegroundColor Cyan
Set-Location "$root/backend"
if (-not (Test-Path ".venv")) { Invoke-Step "create virtualenv" { python -m venv .venv } }
Invoke-Step "upgrade pip" { ./.venv/Scripts/python -m pip install -q --upgrade pip }
Invoke-Step "install backend requirements" { ./.venv/Scripts/python -m pip install -q -r requirements.txt }
if (-not (Test-Path ".env")) {
    $secret = & ./.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content .env.example) -replace '^APP_SECRET_KEY=$', "APP_SECRET_KEY=$secret" | Set-Content -Encoding utf8 .env
    Write-Host "Created backend/.env with a random APP_SECRET_KEY"
}
Invoke-Step "migrate and seed database" { ./.venv/Scripts/python -m app.cli seed }

Write-Host "== Frontend ==" -ForegroundColor Cyan
Set-Location "$root/frontend"
Invoke-Step "npm install" { npm install --no-fund --no-audit }

Set-Location $root
Write-Host ""
Write-Host "Done. Start the app in two terminals:" -ForegroundColor Green
Write-Host "  cd backend;  ./.venv/Scripts/uvicorn app.main:app --reload --port 8000"
Write-Host "  cd frontend; npm run dev        ->  http://localhost:5173"
Write-Host "Optional admin:  cd backend; ./.venv/Scripts/python -m app.cli create-admin --email you@example.com --username yourname"

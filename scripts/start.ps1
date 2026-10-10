$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path (Split-Path (Get-Location) -Parent) '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup.ps1 first' }
if (-not $env:JWT_SECRET) {
    $env:JWT_SECRET = & $python -c "import secrets; print(secrets.token_hex(32))"
    Write-Host 'Using an ephemeral local signing key. Restarting this script invalidates existing tokens.'
}
if (-not $env:SEMANTIC_MODEL_PATH -and (Test-Path 'artifacts/all-MiniLM-L6-v2')) {
    $env:SEMANTIC_MODEL_PATH = 'artifacts/all-MiniLM-L6-v2'
}
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }
& $python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

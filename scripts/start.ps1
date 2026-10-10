$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $env:JWT_SECRET) {
    $env:JWT_SECRET = & ./.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"
    Write-Host 'Using an ephemeral local signing key. Restarting this script invalidates existing tokens.'
}
& ./.venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }
& ./.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

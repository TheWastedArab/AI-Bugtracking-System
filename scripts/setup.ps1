param([string]$PythonPath = 'python', [switch]$AI)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    & $PythonPath -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or pass -PythonPath with its executable path' }
}
& ./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
if ($AI) {
    & ./.venv/Scripts/python.exe -m pip install -r requirements-ai.txt
    if ($LASTEXITCODE -ne 0) { throw 'AI dependency installation failed' }
}
& ./.venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }
Write-Host 'Setup complete. Run scripts/start.ps1 to start the API.'

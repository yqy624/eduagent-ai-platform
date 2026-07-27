$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:AI_ENABLED = "false"
$env:SERVER_HOST = "127.0.0.1"
if (-not $env:SERVER_PORT) {
    $env:SERVER_PORT = "8001"
}

Set-Location $ProjectRoot
Write-Host "Starting EduAgent fast mode at http://127.0.0.1:$env:SERVER_PORT"
Write-Host "AI routes are disabled for faster startup. Use python run.py for full AI mode."
& $Python "run.py" "--host" "127.0.0.1" "--port" $env:SERVER_PORT

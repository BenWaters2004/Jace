$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Device Agent virtual environment was not found. Run .\install.ps1."
}

Push-Location $Root
try {
    & $Python -m jace_device_agent.windows_sandbox_runner probe
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Sandbox prerequisite probe failed."
    }

    Write-Host ""
    Write-Host "Launching the Jace isolation proof..." -ForegroundColor Cyan
    Write-Host "A Windows Sandbox window may briefly appear."
    Write-Host ""

    & $Python -m jace_device_agent.windows_sandbox_runner verify
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Sandbox isolation verification failed."
    }
}
finally {
    Pop-Location
}

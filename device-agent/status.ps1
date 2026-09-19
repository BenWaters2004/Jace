$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Device Agent is not installed. Run .\install.ps1 first."
}

Push-Location $Root
try {
    & $Python -m jace_device_agent status
}
finally {
    Pop-Location
}

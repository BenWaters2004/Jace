param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Enable", "Disable", "Status")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Device Agent is not installed. Run .\install.ps1 first."
}

Push-Location $Root

try {
    $Command = $Action.ToLowerInvariant()

    & $Python `
        -m jace_device_agent `
        process-runtime `
        $Command

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

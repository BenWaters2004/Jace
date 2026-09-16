$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4c4c-google-calendar.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4C.4C Google Calendar sync test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

$CommandCenter = Join-Path $RepoRoot "apps\desktop\src\shell\CommandCenter.tsx"

if (Test-Path $CommandCenter) {
    $Content = Get-Content $CommandCenter -Raw

    if ($Content -match 'className="calendar-command-button"') {
        throw "Top-bar Calendar button still exists."
    }

    if ($Content -notmatch '\{ screen: "calendar", label: "Calendar" \}') {
        throw "Calendar Workspace tab was not found."
    }

    Write-Host "Calendar top-bar button removed / Workspace tab retained: PASS"
}

$DesktopRoot = Join-Path $RepoRoot "apps\desktop"

if (Test-Path (Join-Path $DesktopRoot "node_modules")) {
    Write-Host ""
    Write-Host "Running desktop production build..."
    Write-Host ""

    Push-Location $DesktopRoot
    try {
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) {
            throw "Desktop build failed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "Desktop production build: PASS"
}
else {
    Write-Warning "Desktop node_modules not found; skipping npm build."
}

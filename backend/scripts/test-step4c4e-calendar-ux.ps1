$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$CalendarViews = Join-Path $RepoRoot "apps\desktop\src\components\calendar\CalendarViews.tsx"
$CalendarWorkspace = Join-Path $RepoRoot "apps\desktop\src\components\CalendarWorkspace.tsx"
$SettingsView = Join-Path $RepoRoot "apps\desktop\src\components\SettingsView.tsx"

$ViewsText = Get-Content $CalendarViews -Raw
$WorkspaceText = Get-Content $CalendarWorkspace -Raw
$SettingsText = Get-Content $SettingsView -Raw

if ($ViewsText -notmatch "calendar-multiday-bar") {
    throw "Multi-day all-day event bar renderer was not found."
}

if ($WorkspaceText -notmatch 'type="color"') {
    throw "Per-calendar colour picker was not found."
}

if ($SettingsText -notmatch "Europe/London") {
    throw "Calendar timezone Settings control was not found."
}

if ($WorkspaceText -notmatch "timezone=\{timezone\}") {
    throw "Calendar views are not receiving the configured display timezone."
}

Write-Host "Multi-day all-day rendering wiring: PASS"
Write-Host "Per-calendar colour controls: PASS"
Write-Host "Calendar timezone Settings UI: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4c4e-calendar-ux.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4C.4E backend acceptance test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
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
            throw "Desktop production build failed."
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

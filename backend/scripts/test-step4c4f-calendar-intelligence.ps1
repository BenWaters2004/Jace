$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$CalendarViews = Join-Path `
    $RepoRoot `
    "apps\desktop\src\components\calendar\CalendarViews.tsx"

$Styles = Join-Path `
    $RepoRoot `
    "apps\desktop\src\styles.css"

$ViewsText = Get-Content $CalendarViews -Raw
$StylesText = Get-Content $Styles -Raw

if ($ViewsText -notmatch "calendar-month-date-row") {
    throw "Reserved month-view date row was not found."
}

if ($ViewsText -notmatch "calendar-month-bars-v2") {
    throw "Reserved month-view all-day lane was not found."
}

if ($ViewsText -match 'className="calendar-time-scroll"') {
    throw "CalendarViews still renders the nested Week/Day scroll container."
}

if ($StylesText -notmatch "JACE_STEP4C4F_CALENDAR_LAYOUT_FIXES") {
    throw "Calendar layout fix CSS was not found."
}

Write-Host "Month date/all-day separation: PASS"
Write-Host "Single Week/Day scroll owner: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4c4f-calendar-intelligence.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4C.4F Calendar Intelligence backend test failed."
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

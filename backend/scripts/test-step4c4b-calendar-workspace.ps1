$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$DesktopRoot = Join-Path $RepoRoot "apps\desktop"

Write-Host ""
Write-Host "Jace Step 4C.4B Calendar Workspace test"
Write-Host "========================================"
Write-Host ""

$RequiredFiles = @(
    (Join-Path $DesktopRoot "src\components\CalendarWorkspace.tsx"),
    (Join-Path $DesktopRoot "src\components\calendar\CalendarEventPanel.tsx"),
    (Join-Path $DesktopRoot "src\components\calendar\CalendarViews.tsx"),
    (Join-Path $DesktopRoot "src\components\calendar\calendarUtils.ts")
)

foreach ($Path in $RequiredFiles) {
    if (-not (Test-Path $Path)) {
        throw "Required calendar workspace file is missing: $Path"
    }
}

$TypesText = Get-Content (Join-Path $DesktopRoot "src\types.ts") -Raw
$ApiText = Get-Content (Join-Path $DesktopRoot "src\api.ts") -Raw
$AppText = Get-Content (Join-Path $DesktopRoot "src\App.tsx") -Raw
$CommandText = Get-Content (Join-Path $DesktopRoot "src\shell\CommandCenter.tsx") -Raw
$StylesText = Get-Content (Join-Path $DesktopRoot "src\styles.css") -Raw

if ($TypesText -notmatch '"calendar"') {
    throw "Calendar screen type was not registered."
}
if ($ApiText -notmatch 'getCalendarEvents' -or $ApiText -notmatch 'createCalendarEvent') {
    throw "Calendar API client functions were not registered."
}
if ($AppText -notmatch 'CalendarWorkspace') {
    throw "CalendarWorkspace is not mounted in App.tsx."
}
if ($CommandText -notmatch 'calendar-command-button') {
    throw "The full Calendar command button is missing."
}
if ($StylesText -notmatch 'JACE_STEP4C4B_CALENDAR_WORKSPACE') {
    throw "Calendar workspace styles are missing."
}

Write-Host "Desktop calendar wiring: PASS"

try {
    $Status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/calendar/status"
    $Sources = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/calendar/sources"

    if (-not $Status.default_calendar_id) {
        throw "Calendar status did not return the default calendar ID."
    }
    if (-not $Sources.sources) {
        throw "Calendar source list was empty."
    }

    Write-Host "Calendar backend API: PASS"
}
catch {
    throw "Calendar backend endpoint test failed. Make sure Jace backend is running. $($_.Exception.Message)"
}

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
    Write-Warning "Desktop node_modules not found; skipped npm build."
}

Write-Host ""
Write-Host "PASS - Step 4C.4B Calendar Workspace is operational."
Write-Host ""

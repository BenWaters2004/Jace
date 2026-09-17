$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$GoogleSync = Join-Path $BackendRoot "jace\calendar\google_sync.py"
$Approval = Join-Path $RepoRoot "apps\desktop\src\components\ToolApprovalModal.tsx"

$GoogleSyncText = Get-Content $GoogleSync -Raw
$ApprovalText = Get-Content $Approval -Raw

if ($GoogleSyncText -notmatch "JACE_STEP4C5B_GOOGLE_CONFERENCE_METADATA") {
    throw "Google Calendar conference capability metadata patch was not found."
}

if ($ApprovalText -notmatch "Calendar approval required") {
    throw "Structured Calendar approval UI was not found."
}

if ($ApprovalText -notmatch "Attendee notification side effect") {
    throw "Calendar attendee-notification warning UI was not found."
}

Write-Host "Google conference metadata capture: PASS"
Write-Host "Structured Calendar approval UI: PASS"
Write-Host "Attendee side-effect warning UI: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4c5b-scheduling.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4C.5B Scheduling & Invitations backend test failed."
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

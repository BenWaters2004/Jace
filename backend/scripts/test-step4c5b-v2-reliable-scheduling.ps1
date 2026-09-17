$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$Chat = Join-Path $BackendRoot "jace\api\chat.py"
$Agent = Join-Path $BackendRoot "jace\tools\agent.py"
$GoogleWrite = Join-Path $BackendRoot "jace\tools\google_calendar_write.py"
$Approval = Join-Path $RepoRoot "apps\desktop\src\components\ToolApprovalModal.tsx"

$ChatText = Get-Content $Chat -Raw
$AgentText = Get-Content $Agent -Raw
$GoogleWriteText = Get-Content $GoogleWrite -Raw
$ApprovalText = Get-Content $Approval -Raw

if ($ChatText -notmatch "JACE_STEP4C5B_V2_WRITE_CONTINUATION_CHAT") {
    throw "Calendar write continuation integration was not found in chat.py."
}

if ($AgentText -notmatch "JACE_STEP4C5B_V2_NO_PENDING_WRITE_PROSE") {
    throw "Strict no-pending-write final answer guard was not found."
}

if ($GoogleWriteText -notmatch "CalendarCreateFlatInput") {
    throw "Google Calendar create tool is not using the flat create schema."
}

if ($ApprovalText -notmatch "attendee_emails") {
    throw "Calendar approval UI does not support flat attendee arguments."
}

Write-Host "Conversation-aware Calendar write continuation: PASS"
Write-Host "No-pending-write prose guard: PASS"
Write-Host "Flat Google Calendar create tool integration: PASS"
Write-Host "Flat Calendar approval rendering: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4c5b-v2-reliable-scheduling.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4C.5B v2 Reliable Scheduling test failed."
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

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$Chat = Join-Path $BackendRoot "jace\api\chat.py"
$Routing = Join-Path $BackendRoot "jace\tools\routing.py"
$Agent = Join-Path $BackendRoot "jace\tools\agent.py"

$ChatText = Get-Content $Chat -Raw
$RoutingText = Get-Content $Routing -Raw
$AgentText = Get-Content $Agent -Raw

if ($ChatText -notmatch "JACE_STEP4C5B_DETERMINISTIC_WRITE_COMPACTION") {
    throw "Deterministic Calendar write compaction was not found in chat.py."
}

if ($RoutingText -notmatch "JACE_STEP4C5B_AUTOMATION_SCHEDULE_DISAMBIGUATION") {
    throw "Calendar/Automation schedule disambiguation was not found."
}

if ($AgentText -notmatch "JACE_STEP4C5B_STRICT_WRITE_COMPLETION") {
    throw "Strict Calendar write completion guard was not found."
}

Write-Host "Chat write-tool compaction integration: PASS"
Write-Host "Calendar/Automation schedule disambiguation: PASS"
Write-Host "Strict write completion guard integration: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4c5b-write-routing.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4C.5B deterministic write-routing test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

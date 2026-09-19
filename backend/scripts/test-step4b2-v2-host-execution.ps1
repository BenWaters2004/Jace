$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$Routing = Join-Path $BackendRoot "jace\tools\routing.py"
$Agent = Join-Path $BackendRoot "jace\tools\agent.py"
$Helper = Join-Path $BackendRoot "jace\computer\host_request.py"

$RoutingText = Get-Content $Routing -Raw
$AgentText = Get-Content $Agent -Raw
$HelperText = Get-Content $Helper -Raw

if ($RoutingText -notmatch "JACE_STEP4B2_V2_HOST_LIST_ROUTING_FIX") {
    throw "4B.2 v2 host list routing fix was not found."
}

if ($AgentText -notmatch "JACE_STEP4B2_V2_HOST_EXECUTION_GUARD") {
    throw "4B.2 v2 host execution guard was not found."
}

if ($AgentText -notmatch "FULL HOST ACCESS CONTRACT") {
    throw "4B.2 v2 host tool-use contract was not found."
}

if ($HelperText -notmatch "JACE_STEP4B2_V2_HOST_REQUEST_RESOLUTION") {
    throw "4B.2 v2 host request resolver was not found."
}

Write-Host "Host list routing regression fix: PASS"
Write-Host "Host deterministic execution guard: PASS"
Write-Host "Host tool-use contract: PASS"
Write-Host "Host request resolver integration: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4b2-v2-host-execution.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4B.2 v2 Host Execution Fix test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

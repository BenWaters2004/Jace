$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$Routing = Join-Path $BackendRoot "jace\tools\routing.py"
$Agent = Join-Path $BackendRoot "jace\tools\agent.py"
$FilesystemTools = Join-Path $BackendRoot "jace\tools\filesystem_intelligence.py"

$RoutingText = Get-Content $Routing -Raw
$AgentText = Get-Content $Agent -Raw
$FilesystemText = Get-Content $FilesystemTools -Raw

if ($RoutingText -notmatch "JACE_STEP4B1_V3_DIRECT_WORKSPACE_ROUTING") {
    throw "4B.1 v3 direct workspace routing was not found."
}

if ($AgentText -notmatch "JACE_STEP4B1_V3_FILESYSTEM_EXECUTION_GUARD") {
    throw "4B.1 v3 filesystem execution guard was not found."
}

if ($FilesystemText -notmatch "async def _intelligence_workspace") {
    throw "4B.1 v3 workspace auto-resolution was not found."
}

Write-Host "Direct 4B.1 workspace routing integration: PASS"
Write-Host "Filesystem execution guard integration: PASS"
Write-Host "Workspace auto-resolution integration: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4b1-v3-workspace-execution.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4B.1 v3 Workspace Execution test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

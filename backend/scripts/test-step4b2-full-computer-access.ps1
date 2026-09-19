$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$ToolsInit = Join-Path $BackendRoot "jace\tools\__init__.py"
$Routing = Join-Path $BackendRoot "jace\tools\routing.py"
$Agent = Join-Path $BackendRoot "jace\tools\agent.py"
$Approval = Join-Path $RepoRoot "apps\desktop\src\components\ToolApprovalModal.tsx"

$ToolsInitText = Get-Content $ToolsInit -Raw
$RoutingText = Get-Content $Routing -Raw
$AgentText = Get-Content $Agent -Raw
$ApprovalText = Get-Content $Approval -Raw

if ($ToolsInitText -notmatch "register_full_computer_access_tools") {
    throw "Full Computer Access tool registration was not found."
}

if ($RoutingText -notmatch "JACE_STEP4B2_FULL_HOST_ACCESS_ROUTING") {
    throw "Full host filesystem/shell routing was not found."
}

if ($AgentText -notmatch "JACE_STEP4B2_SHELL_ALWAYS_ASK") {
    throw "Shell always-Ask enforcement was not found."
}

if ($ApprovalText -notmatch "JACE_STEP4B2_SHELL_APPROVAL") {
    throw "Shell command approval presentation was not found."
}

Write-Host "Full host tool registration integration: PASS"
Write-Host "Full host routing integration: PASS"
Write-Host "Shell forced-Ask integration: PASS"
Write-Host "Exact shell command approval UI: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4b2-full-computer-access.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4B.2 Full Computer Access backend test failed."
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

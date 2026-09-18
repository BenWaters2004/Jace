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

$ToolsInitText = Get-Content $ToolsInit -Raw
$RoutingText = Get-Content $Routing -Raw

if ($ToolsInitText -notmatch "register_filesystem_intelligence_tools") {
    throw "Filesystem Intelligence registration was not found."
}

if ($RoutingText -notmatch "JACE_STEP4B1_FILESYSTEM_INTELLIGENCE_ROUTING") {
    throw "Filesystem Intelligence routing was not found."
}

Write-Host "Filesystem Intelligence registration integration: PASS"
Write-Host "Filesystem Intelligence routing integration: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4b1-filesystem-intelligence.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4B.1 Filesystem Intelligence test failed."
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

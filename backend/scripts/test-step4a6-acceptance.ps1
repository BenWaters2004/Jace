$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

Write-Host ""
Write-Host "Step 4A.6 - Connections & Capabilities final acceptance"
Write-Host "======================================================="
Write-Host ""

& $VenvPython `
    (Join-Path $ScriptRoot "test-step4a6-acceptance.py")

if ($LASTEXITCODE -ne 0) {
    throw "Step 4A.6 acceptance test failed."
}

$Step4A5 = Join-Path $ScriptRoot "test-step4a5-security.ps1"

if (Test-Path $Step4A5) {
    Write-Host ""
    Write-Host "Running Step 4A.5 + 4A.4 regression suite..."
    Write-Host ""

    powershell -ExecutionPolicy Bypass `
        -File $Step4A5

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4A.5 regression suite failed."
    }
}
else {
    Write-Warning "Step 4A.5 regression script was not found; skipping that regression run."
}

$DesktopRoot = Join-Path $RepoRoot "apps\desktop"
$NodeModules = Join-Path $DesktopRoot "node_modules"

if (Test-Path $NodeModules) {
    Write-Host ""
    Write-Host "Running desktop TypeScript/Vite build..."
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
}
else {
    Write-Warning "apps\desktop\node_modules is not installed; skipping npm build."
}

Write-Host ""
Write-Host "PASS - Step 4A is ready to close."
Write-Host ""

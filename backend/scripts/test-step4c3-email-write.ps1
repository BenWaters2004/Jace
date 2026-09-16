$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4c3-email-write.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4C.3 email draft/send test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

$DesktopRoot = Join-Path $RepoRoot "apps\desktop"

if (Test-Path (Join-Path $DesktopRoot "node_modules")) {
    Write-Host ""
    Write-Host "Running desktop build..."
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
    Write-Warning "Desktop node_modules not found; skipping npm build."
}

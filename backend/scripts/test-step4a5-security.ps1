$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path

$BackendVenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$RootVenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (Test-Path $BackendVenvPython) {
    $PythonExe = $BackendVenvPython
}
elseif (Test-Path $RootVenvPython) {
    $PythonExe = $RootVenvPython
}
else {
    throw (
        "Jace's Python virtual environment was not found. Expected either '{0}' or '{1}'." `
        -f $BackendVenvPython, $RootVenvPython
    )
}

Write-Host ""
Write-Host "Jace Step 4A.5 security test"
Write-Host "============================"
Write-Host ""
Write-Host "Python:" $PythonExe
Write-Host "Backend:" $BackendRoot
Write-Host ""

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $PythonExe `
        (Join-Path $ScriptRoot "test-step4a5-security.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4A.5 Python security test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

Write-Host ""
Write-Host "Re-running Step 4A.4 runtime capability test..."
Write-Host ""

powershell -ExecutionPolicy Bypass `
    -File (Join-Path $ScriptRoot "test-step4a4-runtime-capabilities.ps1")

if ($LASTEXITCODE -ne 0) {
    throw "Step 4A.4 regression test failed."
}

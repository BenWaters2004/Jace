$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Jace backend virtual environment was not found at $VenvPython"
}

$ShellFile = Join-Path $BackendRoot "jace\tools\shell_reliability.py"
$AgentFile = Join-Path $BackendRoot "jace\tools\agent.py"

$ShellText = Get-Content $ShellFile -Raw
$AgentText = Get-Content $AgentFile -Raw

if ($ShellText -notmatch "JACE_STEP4B2_V4_WINDOWS_SHELL_SUBPROCESS_FIX") {
    throw "v4 Windows shell subprocess fix was not found."
}

if ($ShellText -match "asyncio\.create_subprocess_exec") {
    throw "v4 shell runner still uses asyncio.create_subprocess_exec."
}

if ($ShellText -notmatch "subprocess\.Popen") {
    throw "v4 shell runner is not using subprocess.Popen."
}

if ($AgentText -notmatch "JACE_STEP4B2_SHELL_ALWAYS_ASK") {
    throw "Mandatory shell approval enforcement was not found."
}

Write-Host "v4 shell runner integration: PASS"
Write-Host "No asyncio subprocess dependency: PASS"
Write-Host "Mandatory shell approval still present: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4b2-v4-windows-shell.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4B.2 v4 Windows Shell Subprocess Fix test failed."
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

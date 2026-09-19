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
$Chat = Join-Path $BackendRoot "jace\api\chat.py"
$Shell = Join-Path $BackendRoot "jace\tools\shell_reliability.py"

$ToolsInitText = Get-Content $ToolsInit -Raw
$RoutingText = Get-Content $Routing -Raw
$ChatText = Get-Content $Chat -Raw
$ShellText = Get-Content $Shell -Raw

if ($ToolsInitText -notmatch "register_host_media_tools") {
    throw "Host media registration was not found."
}

if ($ToolsInitText -notmatch "register_shell_reliability_tool") {
    throw "Shell reliability registration was not found."
}

if ($RoutingText -notmatch "JACE_STEP4B2_V3_HOST_MEDIA_ROUTING") {
    throw "Host media routing was not found."
}

if ($ChatText -notmatch "JACE_STEP4B2_V3_HOST_CONTEXT_CHAT") {
    throw "Host follow-up context integration was not found."
}

if ($ChatText -notmatch '"inspect_host_media"') {
    throw "inspect_host_media is not included in multimodal model selection."
}

if ($ShellText -notmatch "JACE_STEP4B2_V3_SHELL_RELIABILITY") {
    throw "v3 shell runner was not found."
}

Write-Host "Host media registration integration: PASS"
Write-Host "Host follow-up context integration: PASS"
Write-Host "Host media routing integration: PASS"
Write-Host "Vision model selection integration: PASS"
Write-Host "Shell reliability replacement integration: PASS"

$PreviousPythonPath = $env:PYTHONPATH

try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $BackendRoot
    }
    else {
        $env:PYTHONPATH = "$BackendRoot;$PreviousPythonPath"
    }

    & $VenvPython `
        (Join-Path $ScriptRoot "test-step4b2-v3-host-media-shell.py")

    if ($LASTEXITCODE -ne 0) {
        throw "Step 4B.2 v3 Host Media + Shell Reliability test failed."
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

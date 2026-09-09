[CmdletBinding()]
param(
    [switch]$ForceModels,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptRoot
$ProjectRoot = Split-Path -Parent $BackendRoot
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Resolve-JacePython {
    if ($env:VIRTUAL_ENV) {
        $active = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path $active) {
            return (Resolve-Path $active).Path
        }
    }

    if (Test-Path $VenvPython) {
        return (Resolve-Path $VenvPython).Path
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "Python could not be found. Activate backend\.venv or create the backend virtual environment first."
}

$Python = Resolve-JacePython
Write-Host "Jace Phase 10B - Kokoro TTS installer" -ForegroundColor Green
Write-Host "Project : $ProjectRoot"
Write-Host "Backend : $BackendRoot"
Write-Host "Python  : $Python"

Write-Step "Checking Python version"
$VersionCheck = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}'); raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 2)"
if ($LASTEXITCODE -ne 0) {
    throw "kokoro-onnx requires Python >=3.10 and <3.14. Current interpreter: $VersionCheck"
}
Write-Host "Python $VersionCheck is supported." -ForegroundColor Green

Write-Step "Installing the Kokoro ONNX runtime"
& $Python -m pip install --upgrade "kokoro-onnx==0.6.1"
if ($LASTEXITCODE -ne 0) {
    throw "pip could not install kokoro-onnx."
}

Write-Step "Installing/validating Kokoro model files"
$ModelInstaller = Join-Path $ScriptRoot "install_voice_models.py"
$ModelArgs = @($ModelInstaller)
if ($ForceModels) {
    $ModelArgs += "--force"
}
& $Python @ModelArgs
if ($LASTEXITCODE -ne 0) {
    throw "The Kokoro model files could not be installed."
}

# Make the repository backend importable for the validation commands without
# modifying the user's permanent PYTHONPATH.
$OldPythonPath = $env:PYTHONPATH
if ([string]::IsNullOrWhiteSpace($OldPythonPath)) {
    $env:PYTHONPATH = $BackendRoot
} else {
    $env:PYTHONPATH = "$BackendRoot;$OldPythonPath"
}

try {
    Write-Step "Checking Jace voice runtime status"
    & $Python -c "import json; from jace.voice.service import voice_service; print(json.dumps(voice_service.status(), indent=2))"
    if ($LASTEXITCODE -ne 0) {
        throw "Jace's voice service could not be imported."
    }

    if (-not $SkipSmokeTest) {
        Write-Step "Generating a local Kokoro speech test"
        $TestWav = Join-Path $env:TEMP "jace-kokoro-tts-test.wav"
        $env:JACE_TTS_TEST_WAV = $TestWav

        & $Python -c "import os; from pathlib import Path; from jace.voice.service import voice_service; p=Path(os.environ['JACE_TTS_TEST_WAV']); data=voice_service.synthesize_wav('All systems online, sir. What are we working on today?'); p.write_bytes(data); print(f'Created {p} ({len(data)} bytes)')"
        if ($LASTEXITCODE -ne 0) {
            throw "Kokoro loaded, but the synthesis smoke test failed."
        }

        if (-not (Test-Path $TestWav)) {
            throw "The TTS smoke test did not create its WAV file."
        }

        Write-Host "TTS test file: $TestWav" -ForegroundColor Green
        Write-Host "Opening the WAV with your default Windows audio player..."
        Start-Process $TestWav
    }
}
finally {
    if ($null -eq $OldPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $OldPythonPath
    }
    Remove-Item Env:JACE_TTS_TEST_WAV -ErrorAction SilentlyContinue
}

Write-Host "`nKokoro TTS installation completed." -ForegroundColor Green
Write-Host "Restart the Jace backend and desktop application, then check /voice/status."
Write-Host "synthesis_available and tts_available should both be true."

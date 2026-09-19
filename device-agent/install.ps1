param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if ($Force -and (Test-Path $Venv)) {
    Remove-Item -Recurse -Force $Venv
}

if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $Venv
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $Venv
    }
    else {
        throw "Python 3 was not found."
    }
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt")

Write-Host ""
Write-Host "Jace Device Agent installed." -ForegroundColor Green
Write-Host "Python: $Python"
Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  1. Create a pairing code in Jace Core."
Write-Host "  2. Run .\pair.ps1 -PairingCode <code>"

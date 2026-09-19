param(
    [Parameter(Mandatory = $true)]
    [string]$PairingCode,

    [string]$Server = "http://127.0.0.1:8000",

    [string]$Name = "",

    [switch]$AllowInsecureRemote
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Device Agent is not installed. Run .\install.ps1 first."
}

$Args = @(
    "-m",
    "jace_device_agent",
    "pair",
    "--server",
    $Server,
    "--pairing-code",
    $PairingCode
)

if ($Name) {
    $Args += "--name"
    $Args += $Name
}

if ($AllowInsecureRemote) {
    $Args += "--allow-insecure-remote"
}

Push-Location $Root
try {
    & $Python @Args
}
finally {
    Pop-Location
}

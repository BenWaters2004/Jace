param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("status", "list", "approve-root", "revoke-root")]
    [string]$Action,
    [string]$Path = "",
    [ValidateSet("powershell", "cmd", "wsl", "bash")]
    [string[]]$Shells = @(),
    [switch]$Process,
    [switch]$Terminal
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Device Agent is not installed. Run .\install.ps1 first."
}

$Args = @("-m", "jace_device_agent.host_policy_cli", $Action)

if ($Action -eq "approve-root") {
    if (-not $Path) { throw "-Path is required." }
    if ($Shells.Count -eq 0) { throw "At least one -Shells value is required." }
    $Args += @("--path", $Path)
    foreach ($Shell in $Shells) { $Args += @("--shell", $Shell) }
    if ($Process) { $Args += "--process" }
    if ($Terminal) { $Args += "--terminal" }
}
elseif ($Action -eq "revoke-root") {
    if (-not $Path) { throw "-Path is required." }
    $Args += @("--path", $Path)
}

Push-Location $Root
try {
    & $Python @Args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

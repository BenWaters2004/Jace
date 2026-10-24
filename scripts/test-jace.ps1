# Jace Phase 0A: quality runner for Windows PowerShell 5.1 / PowerShell 7.
[CmdletBinding()]
param(
    [ValidateSet('quick','full','security','integration','live-provider','device','recovery','production-smoke','all')]
    [string]$Profile = 'quick',
    [string]$RepoRoot = '',
    [switch]$StrictHygiene,
    [switch]$ShowTestOutput,
    [string]$ReportDir = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}
if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
    Write-Error 'Jace repository directory not found.'
    exit 2
}
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$runner = Join-Path $root 'tools\jace_quality.py'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    Write-Error 'tools\jace_quality.py not found. Install the Phase 0A package first.'
    exit 2
}

# Prefer installed Jace backend dependencies, then a Python executable on PATH.
$candidates = @(
    (Join-Path $root 'backend\.venv\Scripts\python.exe'),
    (Join-Path $root 'backend\.venv\bin\python')
)
$python = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $python = $command.Source }
}
if (-not $python) {
    Write-Error 'Python not found. Install Python or the Jace backend environment.'
    exit 2
}

$arguments = @($runner, '--repo-root', $root, '--profile', $Profile)
if ($StrictHygiene) { $arguments += '--strict-hygiene' }
if ($ShowTestOutput) { $arguments += '--show-test-output' }
if (-not [string]::IsNullOrWhiteSpace($ReportDir)) {
    $arguments += @('--report-dir', $ReportDir)
}
Write-Host "Jace quality profile: $Profile"
Write-Host "Python: $python"
& $python @arguments
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 2 }
exit $code

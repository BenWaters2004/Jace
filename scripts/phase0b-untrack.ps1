# Phase 0B: Safely stop tracking generated/private assets without deleting local files.
# Default mode is read-only. -Apply explicitly authorises staged index removals.
[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [switch]$Apply,
    [string]$BackupRoot = ''
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}
if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) { throw 'Repository directory not found.' }
$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$top = & git -C $root rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $top) { throw 'Not a Git repository.' }
if ([IO.Path]::GetFullPath($top.Trim()).TrimEnd('\','/') -ine [IO.Path]::GetFullPath($root).TrimEnd('\','/')) {
    throw 'RepoRoot must be the top-level Git checkout.'
}
$targets = @('data/jace.db', 'backend/.venv', '.jace-patch-backups')
$tracked = @(& git -C $root ls-files -- 'data/jace.db' 'backend/.venv' '.jace-patch-backups')
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate tracked Git paths.' }
$tracked = @($tracked | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
Write-Host "Tracked generated/private files: $($tracked.Count)"
Write-Host 'Targets: data/jace.db, backend/.venv/, .jace-patch-backups/'
if ($tracked.Count -eq 0) { Write-Host 'Nothing to untrack; no changes made.'; exit 0 }
$dirtyIndex = @(& git -C $root diff --cached --name-only -- 'data/jace.db' 'backend/.venv' '.jace-patch-backups')
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect staged changes.' }
if (@($dirtyIndex | Where-Object { $_ }).Count -gt 0) {
    throw 'One or more target files already have staged changes. Resolve these before Phase 0B untracking.'
}
$db = Join-Path $root 'data\jace.db'
if ((@($tracked | Where-Object { $_ -eq 'data/jace.db' }).Count -gt 0) -and
    -not (Test-Path -LiteralPath $db -PathType Leaf)) {
    throw 'Tracked database is absent locally. Refusing cleanup before preservation can be verified.'
}
if (-not $Apply) {
    Write-Host '[DRY RUN] No files or Git entries changed.'
    Write-Host 'After reviewing, rerun with -Apply to create a SQLite backup and stage Git index removal.'
    exit 0
}
if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $BackupRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Jace\SecurityBackups'
}
if ([string]::IsNullOrWhiteSpace($BackupRoot)) { throw 'Specify -BackupRoot outside the Git repository.' }
$base = [IO.Path]::GetFullPath($BackupRoot)
if ($base.TrimEnd('\','/') -ieq $root.TrimEnd('\','/') -or
    $base.StartsWith(($root.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'BackupRoot must be outside the Git repository.'
}
$backup = Join-Path $base ('Phase0B-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$manifest = Join-Path $backup 'tracked-paths.txt'
[IO.File]::WriteAllLines($manifest, [string[]]$tracked, (New-Object System.Text.UTF8Encoding($false)))
if (Test-Path -LiteralPath $db -PathType Leaf) {
    $python = Join-Path $root 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $python = $command.Source }
        else { throw 'Python not found for consistent SQLite backup; no Git entries changed.' }
    }
    $destination = Join-Path $backup 'jace.db'
    # Use a separate Python file: Windows PowerShell 5.1 can strip nested double
    # quotes when forwarding an inline Python -c argument to a native executable.
    $backupHelper = Join-Path $PSScriptRoot 'phase0b-sqlite-backup.py'
    if (-not (Test-Path -LiteralPath $backupHelper -PathType Leaf)) {
        throw 'Phase 0B SQLite backup helper missing. No Git entries changed.'
    }
    & $python $backupHelper $db $destination
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $destination -PathType Leaf)) {
        throw 'Consistent SQLite backup/verification failed. No Git entries changed.'
    }
    Write-Host '[BACKUP] Verified SQLite snapshot written outside repository.'
}
# Git rm --cached removes entries ONLY from the index; the local files remain on disk.
& git -C $root rm -r --cached --ignore-unmatch -- 'data/jace.db' 'backend/.venv' '.jace-patch-backups' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Git index cleanup failed. Review git status and restore staged entries if necessary.' }
$remaining = @(& git -C $root ls-files -- 'data/jace.db' 'backend/.venv' '.jace-patch-backups')
if ($LASTEXITCODE -ne 0) { throw 'Git verification failed.' }
$remaining = @($remaining | Where-Object { $_ })
if ($remaining.Count -ne 0) { throw "Index cleanup incomplete; $($remaining.Count) paths remain tracked." }
if ((@($tracked | Where-Object { $_ -eq 'data/jace.db' }).Count -gt 0) -and
    -not (Test-Path -LiteralPath $db -PathType Leaf)) {
    throw 'Unexpected: local database file no longer exists. Stop and restore from backup.'
}
Write-Host "[SUCCESS] Untracked $($tracked.Count) files from Git index; preserved local contents."
Write-Host "Protected backup location to review: $backup"
Write-Host 'Next: git status --short; commit index cleanup on a feature branch; run security checks.'
Write-Host 'IMPORTANT: Existing GitHub history still contains old versions. Treat it as a separate security incident review.'

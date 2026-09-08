$ErrorActionPreference = "Stop"
$taskName = "Jace Automation Backend"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "'$taskName' is not installed."
    exit 0
}

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Removed '$taskName'." -ForegroundColor Green

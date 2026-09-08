$ErrorActionPreference = "Stop"

$taskName = "Jace Automation Backend"
$backendRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $backendRoot ".venv\Scripts\pythonw.exe"
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (Test-Path $pythonw) {
    $executable = $pythonw
} elseif (Test-Path $python) {
    $executable = $python
} else {
    throw "Jace virtual environment was not found. Expected $python or $pythonw. Create/install backend\.venv first."
}

$arguments = "-m uvicorn jace.main:app --host 127.0.0.1 --port 8000"
$action = New-ScheduledTaskAction `
    -Execute $executable `
    -Argument $arguments `
    -WorkingDirectory $backendRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Runs the local Jace FastAPI backend so scheduled automations can continue while the desktop UI is closed." | Out-Null

Start-ScheduledTask -TaskName $taskName

Write-Host "Installed and started '$taskName'." -ForegroundColor Green
Write-Host "Backend root: $backendRoot"
Write-Host "Jace should become available at http://127.0.0.1:8000"
Write-Host "Do not also start a second manual uvicorn process on port 8000 while this task is running."

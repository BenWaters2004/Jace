$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $backendDir ".env"
$examplePath = Join-Path $backendDir ".env.example"

if (-not (Test-Path $envPath)) {
    if (-not (Test-Path $examplePath)) {
        throw "Neither .env nor .env.example could be found in $backendDir"
    }
    Copy-Item $examplePath $envPath
    Write-Host "Created backend\.env from .env.example"
    exit 0
}

$backupPath = "$envPath.v0.5.0-backup"
Copy-Item $envPath $backupPath -Force

$updates = [ordered]@{
    "JACE_OLLAMA_KEEP_ALIVE" = "-1m"
    "JACE_EMBEDDING_KEEP_ALIVE" = "20m"
    "JACE_PRELOAD_DEFAULT_MODEL" = "true"
    "JACE_PRELOAD_TIMEOUT_SECONDS" = "120"
    "JACE_OLLAMA_NUM_CTX" = "4096"
    "JACE_HISTORY_MAX_MESSAGES" = "20"
    "JACE_HISTORY_MAX_CHARS" = "10000"
    "JACE_MEMORY_SMART_RETRIEVAL" = "true"
    "JACE_MEMORY_EXTRACTION_IDLE_SECONDS" = "4"
    "JACE_SMART_TOOL_ROUTING" = "true"
    "JACE_TOOL_RESULT_MAX_CHARS" = "8000"
    "JACE_WEB_SEARCH_MAX_RESULTS" = "6"
    "JACE_WEB_PAGE_MAX_CHARS" = "6500"
    "JACE_WEB_MAX_LINKS" = "20"
    "JACE_BROWSER_WAIT_AFTER_LOAD_MS" = "350"
    "JACE_BROWSER_MAX_PAGE_CHARS" = "7000"
    "JACE_BROWSER_MAX_LINKS" = "25"
}

$lines = [System.Collections.Generic.List[string]]::new()
Get-Content $envPath | ForEach-Object { [void]$lines.Add($_) }

foreach ($key in $updates.Keys) {
    $replacement = "$key=$($updates[$key])"
    $found = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($key))\s*=") {
            $lines[$i] = $replacement
            $found = $true
            break
        }
    }

    if (-not $found) {
        [void]$lines.Add($replacement)
    }
}

[System.IO.File]::WriteAllLines($envPath, $lines, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Updated $envPath for Jace v0.5.1 performance defaults."
Write-Host "Backup: $backupPath"

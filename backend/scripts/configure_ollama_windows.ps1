# Optional Windows tuning for a 6 GB-class NVIDIA GPU running Jace locally.
# These are Ollama server settings (not Jace settings) and affect all local
# Ollama models for this Windows user. Quit/restart Ollama after running.

$settings = [ordered]@{
    "OLLAMA_FLASH_ATTENTION" = "1"
    "OLLAMA_KV_CACHE_TYPE" = "q8_0"
    "OLLAMA_NUM_PARALLEL" = "1"
    "OLLAMA_MAX_LOADED_MODELS" = "2"
    "OLLAMA_CONTEXT_LENGTH" = "4096"
}

foreach ($entry in $settings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "User")
    Write-Host "$($entry.Key)=$($entry.Value)"
}

Write-Host ""
Write-Host "Ollama user environment variables updated."
Write-Host "Quit Ollama from the Windows system tray, then start it again for the changes to take effect."
Write-Host "Use 'ollama ps' after a Jace request to confirm model processor placement."

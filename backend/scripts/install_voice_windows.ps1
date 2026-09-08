$ErrorActionPreference = "Stop"

Write-Host "Jace Phase 10B local voice setup" -ForegroundColor Cyan
Write-Host "Speech recognition and synthesis stay on this machine during normal use."

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Installing/updating eSpeak NG (required for Kokoro phonemisation)..."
    winget install --id eSpeak-NG.eSpeak-NG -e --accept-package-agreements --accept-source-agreements
} else {
    Write-Warning "winget is not available. Install eSpeak NG manually before using Kokoro TTS."
}

Write-Host "Installing Python voice dependencies..."
python -m pip install -r requirements.txt

Write-Host "Installing the local Kokoro model files..."
python .\scripts\install_voice_models.py

Write-Host "Preparing the local Whisper model used for push-to-talk..."
python .\scripts\install_audio_model.py

Write-Host "Phase 10B voice setup complete." -ForegroundColor Green
Write-Host "Restart the Jace backend after this installer finishes."

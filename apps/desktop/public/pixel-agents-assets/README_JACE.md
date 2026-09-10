# Pixel Agents assets

Run this before building Jace:

```powershell
cd C:\Users\Ben\jace
powershell -ExecutionPolicy Bypass -File .\scripts\sync-pixel-agents-assets.ps1
```

The script installs the pinned upstream Pixel Agents assets into this directory
and creates `_jace-asset-index.json`.

Jace loads the copied files locally at runtime; it does not hotlink GitHub.

param(
    [string]$DevUrl = "http://localhost:1420"
)

$ErrorActionPreference = "Stop"

# This script lives in <repo>\backend\scripts\
$BackendRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $BackendRoot
$DesktopRoot = Join-Path $RepoRoot "apps\desktop"

$AssetRoot = Join-Path $DesktopRoot "public\pixel-agents-assets"
$IndexPath = Join-Path $AssetRoot "_jace-asset-index.json"

$AssetsSource = Join-Path $DesktopRoot "src\pixelOffice\assets.ts"
$SpriteSource = Join-Path $DesktopRoot "src\pixelOffice\spriteLibrary.ts"
$EngineSource = Join-Path $DesktopRoot "src\pixelOffice\engine.ts"

$Failures = 0

function Write-Result {
    param(
        [string]$Label,
        [bool]$Ok,
        [string]$Detail
    )

    if ($Ok) {
        Write-Host "[PASS] $Label $Detail" -ForegroundColor Green
    }
    else {
        Write-Host "[FAIL] $Label $Detail" -ForegroundColor Red
        $script:Failures++
    }
}

Write-Host ""
Write-Host "Jace Pixel Agents Integration Test" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Repo root:    $RepoRoot"
Write-Host "Desktop root: $DesktopRoot"
Write-Host "Asset root:   $AssetRoot"
Write-Host ""

Write-Result "Desktop folder" (Test-Path $DesktopRoot) $DesktopRoot
Write-Result "Asset folder" (Test-Path $AssetRoot) $AssetRoot
Write-Result "Asset index" (Test-Path $IndexPath) $IndexPath

if (-not (Test-Path $IndexPath)) {
    Write-Host ""
    Write-Host "The asset index is missing. Run:" -ForegroundColor Yellow
    Write-Host "powershell -ExecutionPolicy Bypass -File .\backend\scripts\sync-pixel-agents-assets.ps1 -Force"
    exit 1
}

$Index = Get-Content $IndexPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "Asset index:" -ForegroundColor Cyan
Write-Host "  Ref:        $($Index.source.ref)"
Write-Host "  Characters: $($Index.characters.Count)"
Write-Host "  Floors:     $($Index.floors.Count)"
Write-Host "  Walls:      $($Index.walls.Count)"
Write-Host "  Carpets:    $($Index.carpets.Count)"
Write-Host "  Pets:       $($Index.pets.Count)"
Write-Host "  Furniture:  $($Index.furniture.Count)"
Write-Host ""

# -------------------------------------------------------------------------
# Most important check: make sure Jace is actually using the upstream loader.
# -------------------------------------------------------------------------
$SourceWired = $false
$OldLoaderFound = $false

if (Test-Path $AssetsSource) {
    $AssetsText = Get-Content $AssetsSource -Raw

    if ($AssetsText -match "_jace-asset-index\.json") {
        $SourceWired = $true
    }

    if ($AssetsText -match "assets/pixel-office|characters/research\.png|furniture/furniture\.png|pets/cat\.png") {
        $OldLoaderFound = $true
    }
}

if (Test-Path $SpriteSource) {
    $SpriteText = Get-Content $SpriteSource -Raw

    if ($SpriteText -match "CHARACTER_ASSET_URLS|FURNITURE_ASSET_URL|PET_ASSET_URLS") {
        $OldLoaderFound = $true
    }
}

Write-Result `
    "Frontend uses upstream asset index" `
    $SourceWired `
    $AssetsSource

Write-Result `
    "Old generated Jace loader removed" `
    (-not $OldLoaderFound) `
    ""

if (-not $SourceWired -or $OldLoaderFound) {
    Write-Host ""
    Write-Host "IMPORTANT:" -ForegroundColor Yellow
    Write-Host "Your Pixel Agents files may exist, but the frontend source is still using the old Jace sprite atlas." -ForegroundColor Yellow
    Write-Host "Extract the 11B.3B.2.2 ZIP over C:\Users\Ben\jace so the src\pixelOffice files are replaced." -ForegroundColor Yellow
}

# -------------------------------------------------------------------------
# Local files.
# -------------------------------------------------------------------------
$CoreChecks = @(
    @("char_0.png", (Join-Path $AssetRoot "characters\char_0.png")),
    @("floor_0.png", (Join-Path $AssetRoot "floors\floor_0.png")),
    @("wall_0.png", (Join-Path $AssetRoot "walls\wall_0.png")),
    @("Gitcat", (Join-Path $AssetRoot "pets\gitcat\pet.png")),
    @("DESK manifest", (Join-Path $AssetRoot "furniture\DESK\manifest.json")),
    @("PC manifest", (Join-Path $AssetRoot "furniture\PC\manifest.json"))
)

foreach ($Check in $CoreChecks) {
    $Label = [string]$Check[0]
    $Path = [string]$Check[1]

    Write-Result $Label (Test-Path $Path) $Path
}

# -------------------------------------------------------------------------
# Validate every image file referenced by every furniture manifest.
# -------------------------------------------------------------------------
Write-Host ""
Write-Host "Checking furniture manifest image references..." -ForegroundColor Cyan

$Broken = @()

function Test-FurnitureNode {
    param(
        $Node,
        [string]$FolderPath,
        [string]$ManifestId
    )

    if ($null -eq $Node) {
        return
    }

    if ($Node.type -eq "asset") {
        $FileName = $null

        if ($Node.file) {
            $FileName = [string]$Node.file
        }
        else {
            $FileName = "$($Node.id).png"
        }

        $ImagePath = Join-Path $FolderPath $FileName

        if (-not (Test-Path $ImagePath)) {
            $script:Broken += "$ManifestId -> $FileName"
        }

        return
    }

    if ($Node.members) {
        foreach ($Member in $Node.members) {
            Test-FurnitureNode $Member $FolderPath $ManifestId
        }
    }
}

$FurnitureRoot = Join-Path $AssetRoot "furniture"

if (Test-Path $FurnitureRoot) {
    foreach ($Folder in (Get-ChildItem $FurnitureRoot -Directory)) {
        $ManifestPath = Join-Path $Folder.FullName "manifest.json"

        if (-not (Test-Path $ManifestPath)) {
            continue
        }

        $Manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        Test-FurnitureNode $Manifest $Folder.FullName ([string]$Manifest.id)
    }
}

$ReferenceDetail = "all referenced PNGs exist"

if ($Broken.Count -gt 0) {
    $ReferenceDetail = "$($Broken.Count) referenced PNG(s) missing"
}

Write-Result `
    "Furniture image references" `
    ($Broken.Count -eq 0) `
    $ReferenceDetail

if ($Broken.Count -gt 0) {
    foreach ($Item in ($Broken | Select-Object -First 20)) {
        Write-Host "  $Item" -ForegroundColor Yellow
    }
}

# -------------------------------------------------------------------------
# Check built dist if npm run build has already been run.
# -------------------------------------------------------------------------
$DistIndex = Join-Path $DesktopRoot "dist\pixel-agents-assets\_jace-asset-index.json"

if (Test-Path (Join-Path $DesktopRoot "dist")) {
    Write-Result `
        "Built dist contains Pixel Agents assets" `
        (Test-Path $DistIndex) `
        $DistIndex
}

# -------------------------------------------------------------------------
# Check Vite/Tauri dev server.
# -------------------------------------------------------------------------
Write-Host ""
Write-Host "Checking Vite/Tauri server..." -ForegroundColor Cyan

$Urls = @(
    "$DevUrl/pixel-agents-assets/_jace-asset-index.json",
    "$DevUrl/pixel-agents-assets/characters/char_0.png",
    "$DevUrl/pixel-agents-assets/floors/floor_0.png",
    "$DevUrl/pixel-agents-assets/pets/gitcat/pet.png"
)

$ServerAvailable = $true

foreach ($Url in $Urls) {
    try {
        $Response = Invoke-WebRequest `
            -Uri $Url `
            -UseBasicParsing `
            -TimeoutSec 5

        $Ok = ($Response.StatusCode -eq 200)
        Write-Result $Url $Ok "HTTP $($Response.StatusCode)"
    }
    catch {
        $ServerAvailable = $false
        Write-Result $Url $false $_.Exception.Message
    }
}

Write-Host ""

if (-not $ServerAvailable) {
    Write-Host "If Jace is not currently running, start it with:" -ForegroundColor Yellow
    Write-Host "  cd C:\Users\Ben\jace\apps\desktop"
    Write-Host "  npm run tauri dev"
    Write-Host ""
}

if ($Failures -gt 0) {
    Write-Host "FAILED: $Failures integration check(s) failed." -ForegroundColor Red
    exit 1
}

Write-Host "SUCCESS: Pixel Agents assets are installed, wired into the frontend, and reachable." -ForegroundColor Green
exit 0

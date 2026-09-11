param(
    [string]$Ref = "v1.4.1",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# This script lives in:
#   <repo>\backend\scripts\
#
# Resolve paths explicitly instead of relying on ../ segments.
$BackendRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $BackendRoot
$DesktopRoot = Join-Path $RepoRoot "apps\desktop"
$Destination = Join-Path $DesktopRoot "public\pixel-agents-assets"

$Repository = "pixel-agents-hq/pixel-agents"
$RepositoryUrl = "https://github.com/$Repository"

function Write-Step {
    param([string]$Message)
    Write-Host "[Pixel Agents Assets] $Message" -ForegroundColor Cyan
}

function Resolve-ArchiveUrl {
    param([string]$RequestedRef)

    if (($RequestedRef -eq "main") -or ($RequestedRef -eq "master")) {
        return "$RepositoryUrl/archive/refs/heads/$RequestedRef.zip"
    }

    return "$RepositoryUrl/archive/refs/tags/$RequestedRef.zip"
}

function Remove-OldAssetPayload {
    param([string]$Path)

    $Names = @(
        "carpets",
        "characters",
        "floors",
        "furniture",
        "pets",
        "walls",
        "default-layout-1.json",
        "default-layout.json",
        "PIXEL_AGENTS_LICENSE.txt",
        "_jace-asset-index.json",
        "_jace-sync.json"
    )

    foreach ($Name in $Names) {
        $Target = Join-Path $Path $Name

        if (Test-Path $Target) {
            Remove-Item $Target -Recurse -Force
        }
    }
}

function Get-NaturalNumber {
    param([System.IO.FileInfo]$File)

    if ($File.BaseName -match '(\d+)$') {
        return [int]$Matches[1]
    }

    return 999999
}

Write-Step "Repository root: $RepoRoot"
Write-Step "Desktop root: $DesktopRoot"
Write-Step "Destination: $Destination"

if (-not (Test-Path $DesktopRoot)) {
    throw "Desktop application folder was not found: $DesktopRoot"
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "jace-pixel-agents-" + [guid]::NewGuid().ToString("N")
)

$ArchivePath = Join-Path $TempRoot "pixel-agents.zip"
$ExtractPath = Join-Path $TempRoot "source"

try {
    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $ExistingSync = Join-Path $Destination "_jace-sync.json"

    if ((Test-Path $ExistingSync) -and (-not $Force)) {
        try {
            $Existing = Get-Content $ExistingSync -Raw | ConvertFrom-Json

            if ($Existing.ref -eq $Ref) {
                Write-Step "Assets for $Ref are already installed."
                Write-Step "Use -Force to download them again."
                return
            }
        }
        catch {
            Write-Step "Existing sync metadata is invalid; performing a clean sync."
        }
    }

    $ArchiveUrl = Resolve-ArchiveUrl $Ref

    Write-Step "Downloading $Repository @ $Ref..."
    Invoke-WebRequest `
        -Uri $ArchiveUrl `
        -OutFile $ArchivePath `
        -UseBasicParsing

    Write-Step "Extracting upstream repository..."
    Expand-Archive `
        -Path $ArchivePath `
        -DestinationPath $ExtractPath `
        -Force

    $AssetRoot = Get-ChildItem `
        -Path $ExtractPath `
        -Recurse `
        -Directory |
        Where-Object {
            $_.FullName -match '[\\/]webview-ui[\\/]public[\\/]assets$'
        } |
        Select-Object -First 1

    if (-not $AssetRoot) {
        throw "Could not locate webview-ui/public/assets in the downloaded Pixel Agents archive."
    }

    # assets -> public -> webview-ui -> repository root
    $CheckoutRoot = $AssetRoot.Parent.Parent.Parent
    $LicenseSource = Join-Path $CheckoutRoot.FullName "LICENSE"

    Remove-OldAssetPayload $Destination

    Write-Step "Copying upstream asset tree into Jace..."
    Copy-Item `
        -Path (Join-Path $AssetRoot.FullName "*") `
        -Destination $Destination `
        -Recurse `
        -Force

    if (Test-Path $LicenseSource) {
        Copy-Item `
            -Path $LicenseSource `
            -Destination (Join-Path $Destination "PIXEL_AGENTS_LICENSE.txt") `
            -Force
    }

    $CharacterDir = Join-Path $Destination "characters"
    $FloorDir = Join-Path $Destination "floors"
    $WallDir = Join-Path $Destination "walls"
    $CarpetDir = Join-Path $Destination "carpets"
    $PetDir = Join-Path $Destination "pets"
    $FurnitureDir = Join-Path $Destination "furniture"

    $Characters = @()
    if (Test-Path $CharacterDir) {
        $Characters = @(
            Get-ChildItem $CharacterDir -File -Filter "char_*.png" |
            Sort-Object { Get-NaturalNumber $_ } |
            ForEach-Object { $_.Name }
        )
    }

    $Floors = @()
    if (Test-Path $FloorDir) {
        $Floors = @(
            Get-ChildItem $FloorDir -File -Filter "floor_*.png" |
            Sort-Object { Get-NaturalNumber $_ } |
            ForEach-Object { $_.Name }
        )
    }

    $Walls = @()
    if (Test-Path $WallDir) {
        $Walls = @(
            Get-ChildItem $WallDir -File -Filter "wall_*.png" |
            Sort-Object { Get-NaturalNumber $_ } |
            ForEach-Object { $_.Name }
        )
    }

    $Carpets = @()
    if (Test-Path $CarpetDir) {
        $Carpets = @(
            Get-ChildItem $CarpetDir -File -Filter "*.png" |
            Sort-Object Name |
            ForEach-Object { $_.Name }
        )
    }

    $Pets = @()
    if (Test-Path $PetDir) {
        foreach ($PetFolder in (Get-ChildItem $PetDir -Directory | Sort-Object Name)) {
            $ManifestPath = Join-Path $PetFolder.FullName "manifest.json"
            $ImagePath = Join-Path $PetFolder.FullName "pet.png"

            if ((Test-Path $ManifestPath) -and (Test-Path $ImagePath)) {
                $Manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json

                $Pets += [ordered]@{
                    id = [string]$Manifest.id
                    name = [string]$Manifest.name
                    folder = $PetFolder.Name
                    manifest = "pets/$($PetFolder.Name)/manifest.json"
                    image = "pets/$($PetFolder.Name)/pet.png"
                }
            }
        }
    }

    $Furniture = @()
    if (Test-Path $FurnitureDir) {
        foreach ($FurnitureFolder in (Get-ChildItem $FurnitureDir -Directory | Sort-Object Name)) {
            $ManifestPath = Join-Path $FurnitureFolder.FullName "manifest.json"

            if (Test-Path $ManifestPath) {
                $Furniture += [ordered]@{
                    folder = $FurnitureFolder.Name
                    manifest = "furniture/$($FurnitureFolder.Name)/manifest.json"
                }
            }
        }
    }

    if ($Characters.Count -lt 6) {
        throw "Expected at least 6 character sheets; found $($Characters.Count)."
    }

    if ($Floors.Count -lt 1) {
        throw "No Pixel Agents floor assets were found."
    }

    if ($Walls.Count -lt 1) {
        throw "No Pixel Agents wall assets were found."
    }

    if ($Furniture.Count -lt 1) {
        throw "No Pixel Agents furniture manifests were found."
    }

    $Index = [ordered]@{
        version = 1
        source = [ordered]@{
            repository = $Repository
            ref = $Ref
            syncedAt = (Get-Date).ToUniversalTime().ToString("o")
        }
        characters = $Characters
        floors = $Floors
        walls = $Walls
        carpets = $Carpets
        pets = $Pets
        furniture = $Furniture
    }

    $Index |
        ConvertTo-Json -Depth 8 |
        Set-Content `
            -Path (Join-Path $Destination "_jace-asset-index.json") `
            -Encoding UTF8

    $SyncMetadata = [ordered]@{
        repository = $Repository
        ref = $Ref
        syncedAt = (Get-Date).ToUniversalTime().ToString("o")
        assetRoot = "webview-ui/public/assets"
        destination = $Destination
        characterCount = $Characters.Count
        floorCount = $Floors.Count
        wallCount = $Walls.Count
        carpetCount = $Carpets.Count
        petCount = $Pets.Count
        furnitureManifestCount = $Furniture.Count
    }

    $SyncMetadata |
        ConvertTo-Json -Depth 5 |
        Set-Content `
            -Path (Join-Path $Destination "_jace-sync.json") `
            -Encoding UTF8

    Write-Host ""
    Write-Step "Installed Pixel Agents assets successfully."
    Write-Host "  Ref:        $Ref"
    Write-Host "  Characters: $($Characters.Count)"
    Write-Host "  Floors:     $($Floors.Count)"
    Write-Host "  Walls:      $($Walls.Count)"
    Write-Host "  Carpets:    $($Carpets.Count)"
    Write-Host "  Pets:       $($Pets.Count)"
    Write-Host "  Furniture:  $($Furniture.Count)"
    Write-Host ""
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

param(
    [string]$DesktopRoot =
        (Join-Path (Split-Path -Parent $PSScriptRoot) "../apps\desktop"),
    [string]$DevUrl =
        "http://localhost:1420"
)

$ErrorActionPreference = "Stop"

$AssetRoot =
    Join-Path $DesktopRoot "public\pixel-agents-assets"

$IndexPath =
    Join-Path $AssetRoot "_jace-asset-index.json"

function Result {
    param(
        [string]$Label,
        [bool]$Ok,
        [string]$Detail = ""
    )

    $Mark =
        if ($Ok) { "[PASS]" } else { "[FAIL]" }

    $Color =
        if ($Ok) { "Green" } else { "Red" }

    Write-Host (
        "{0} {1} {2}" -f $Mark, $Label, $Detail
    ) -ForegroundColor $Color
}

Write-Host ""
Write-Host "Jace Pixel Agents Asset Test" -ForegroundColor Cyan
Write-Host "============================" -ForegroundColor Cyan
Write-Host ""

Result "Asset folder exists" (Test-Path $AssetRoot) $AssetRoot

if (-not (Test-Path $AssetRoot)) {
    exit 1
}

Result "Asset index exists" (Test-Path $IndexPath) $IndexPath

if (-not (Test-Path $IndexPath)) {
    Write-Host ""
    Write-Host "Run:" -ForegroundColor Yellow
    Write-Host ".\scripts\sync-pixel-agents-assets.ps1 -Force"
    exit 1
}

$Index =
    Get-Content $IndexPath -Raw |
    ConvertFrom-Json

Write-Host ""
Write-Host "Index:" -ForegroundColor Cyan
Write-Host "  Ref:        $($Index.source.ref)"
Write-Host "  Characters: $($Index.characters.Count)"
Write-Host "  Floors:     $($Index.floors.Count)"
Write-Host "  Walls:      $($Index.walls.Count)"
Write-Host "  Carpets:    $($Index.carpets.Count)"
Write-Host "  Pets:       $($Index.pets.Count)"
Write-Host "  Furniture:  $($Index.furniture.Count)"
Write-Host ""

$CoreChecks = @(
    @{
        Label = "char_0.png"
        Path = Join-Path $AssetRoot "characters\char_0.png"
    },
    @{
        Label = "floor_0.png"
        Path = Join-Path $AssetRoot "floors\floor_0.png"
    },
    @{
        Label = "wall_0.png"
        Path = Join-Path $AssetRoot "walls\wall_0.png"
    },
    @{
        Label = "Gitcat pet"
        Path = Join-Path $AssetRoot "pets\gitcat\pet.png"
    },
    @{
        Label = "DESK manifest"
        Path = Join-Path $AssetRoot "furniture\DESK\manifest.json"
    },
    @{
        Label = "PC manifest"
        Path = Join-Path $AssetRoot "furniture\PC\manifest.json"
    }
)

foreach ($Check in $CoreChecks) {
    Result $Check.Label (Test-Path $Check.Path) $Check.Path
}

Write-Host ""
Write-Host "Validating furniture manifest image references..." -ForegroundColor Cyan

$Broken = @()

Get-ChildItem `
    (Join-Path $AssetRoot "furniture") `
    -Directory |
ForEach-Object {
    $Folder = $_
    $ManifestPath =
        Join-Path $Folder.FullName "manifest.json"

    if (-not (Test-Path $ManifestPath)) {
        return
    }

    $Manifest =
        Get-Content $ManifestPath -Raw |
        ConvertFrom-Json

    function Walk-Node {
        param(
            $Node,
            [string]$RootFolder
        )

        if ($Node.type -eq "asset") {
            $File =
                if ($Node.file) {
                    [string]$Node.file
                }
                else {
                    "$($Node.id).png"
                }

            $FilePath =
                Join-Path $RootFolder $File

            if (-not (Test-Path $FilePath)) {
                $script:Broken +=
                    "$($Manifest.id) -> $File"
            }

            return
        }

        if ($Node.members) {
            foreach ($Member in $Node.members) {
                Walk-Node $Member $RootFolder
            }
        }
    }

    Walk-Node $Manifest $Folder.FullName
}

Result `
    "Furniture image references" `
    ($Broken.Count -eq 0) `
    (
        if ($Broken.Count -eq 0) {
            "all referenced PNGs exist"
        }
        else {
            "$($Broken.Count) missing"
        }
    )

if ($Broken.Count -gt 0) {
    $Broken |
        Select-Object -First 20 |
        ForEach-Object {
            Write-Host "  $_" -ForegroundColor Yellow
        }
}

Write-Host ""
Write-Host "Testing Vite/Tauri dev server..." -ForegroundColor Cyan

$Urls = @(
    "$DevUrl/pixel-agents-assets/_jace-asset-index.json",
    "$DevUrl/pixel-agents-assets/characters/char_0.png",
    "$DevUrl/pixel-agents-assets/floors/floor_0.png",
    "$DevUrl/pixel-agents-assets/pets/gitcat/pet.png"
)

$ServerOk = $true

foreach ($Url in $Urls) {
    try {
        $Response =
            Invoke-WebRequest `
                -Uri $Url `
                -UseBasicParsing `
                -TimeoutSec 5

        Result `
            $Url `
            ($Response.StatusCode -eq 200) `
            "HTTP $($Response.StatusCode)"
    }
    catch {
        $ServerOk = $false

        Result `
            $Url `
            $false `
            $_.Exception.Message
    }
}

Write-Host ""

if (-not $ServerOk) {
    Write-Host (
        "The files exist on disk but Vite is not serving them. " +
        "Run 'npm run tauri dev' from apps\desktop and rerun this test."
    ) -ForegroundColor Yellow
    exit 2
}

if ($Broken.Count -gt 0) {
    Write-Host (
        "Vite can serve the assets, but the upstream copy contains broken " +
        "furniture references. Re-run the sync with -Force."
    ) -ForegroundColor Yellow
    exit 3
}

Write-Host "Pixel Agents assets are present AND reachable by the Jace frontend." -ForegroundColor Green
exit 0

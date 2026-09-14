$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"

Write-Host ""
Write-Host "Jace Step 4A.4 runtime capability resolver test"
Write-Host "================================================"
Write-Host ""

function Resolve-Capability {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $body = @{
        message = $Message
    } | ConvertTo-Json

    return Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/capabilities/resolve" `
        -ContentType "application/json" `
        -Body $body
}

function Assert-Need {
    param(
        [Parameter(Mandatory = $true)]
        $Plan,

        [Parameter(Mandatory = $true)]
        [string]$CapabilityId,

        [string]$PreferredProvider = ""
    )

    $need = @(
        $Plan.needs |
            Where-Object {
                $_.capability_id -eq $CapabilityId
            }
    )

    if ($need.Count -ne 1) {
        throw "Expected exactly one '$CapabilityId' capability need."
    }

    if (
        $PreferredProvider -and
        $need[0].preferred_provider -ne $PreferredProvider
    ) {
        throw ("Expected '{0}' to prefer '{1}', got '{2}'." -f $CapabilityId, $PreferredProvider, $need[0].preferred_provider)
    }

    $resolution = @(
        $Plan.resolutions |
            Where-Object {
                $_.capability_id -eq $CapabilityId
            }
    )

    if ($resolution.Count -ne 1) {
        throw "Expected exactly one '$CapabilityId' resolution."
    }

    Write-Host ("{0,-24} -> {1,-24} provider={2}" -f $CapabilityId, $resolution[0].status, $resolution[0].provider_id)
}

try {
    Invoke-RestMethod `
        -Method Get `
        -Uri "$BaseUrl/health" |
        Out-Null
}
catch {
    Write-Error "The Jace backend is not reachable at $BaseUrl."
    throw
}

Write-Host "Backend reachable."
Write-Host ""

$gmail = Resolve-Capability `
    -Message "Search my Gmail for emails from Microsoft about Azure."

Assert-Need `
    -Plan $gmail `
    -CapabilityId "email.search" `
    -PreferredProvider "google"

$outlook = Resolve-Capability `
    -Message "Show me what is on my Outlook calendar tomorrow."

Assert-Need `
    -Plan $outlook `
    -CapabilityId "calendar.read" `
    -PreferredProvider "microsoft"

$github = Resolve-Capability `
    -Message "Read my GitHub repository and inspect it."

Assert-Need `
    -Plan $github `
    -CapabilityId "repositories.read" `
    -PreferredProvider "github"

$plain = Resolve-Capability `
    -Message "What is 2 + 2?"

if (@($plain.needs).Count -ne 0) {
    throw "A plain arithmetic request incorrectly routed an external capability."
}

Write-Host ""
Write-Host "Plain local request -> no external capability needs (correct)."

foreach ($plan in @($gmail, $outlook, $github)) {
    foreach ($resolution in @($plan.resolutions)) {
        if (
            $resolution.status -eq "ready" -and
            [string]::IsNullOrWhiteSpace(
                [string]$resolution.tool_name
            )
        ) {
            throw ("A capability was marked ready without an executable tool binding: {0}" -f $resolution.capability_id)
        }
    }
}

Write-Host ""
Write-Host "PASS - Step 4A.4 runtime capability resolution is working."
Write-Host ""

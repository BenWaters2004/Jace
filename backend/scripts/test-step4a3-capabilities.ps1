$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"

Write-Host ""
Write-Host "Jace Step 4A.3 capability registry test"
Write-Host "======================================"
Write-Host ""

try {
    $snapshot = Invoke-RestMethod `
        -Method Get `
        -Uri "$BaseUrl/capabilities"
}
catch {
    Write-Error "Could not reach $BaseUrl/capabilities. Make sure the Jace backend is running."
    throw
}

$bindings = @(
    $snapshot.capabilities |
        Where-Object { $_.source -eq "connection" }
)

Write-Host "Connections:" $snapshot.connection_count
Write-Host "Ready:" $snapshot.counts.ready
Write-Host "Configured:" $snapshot.counts.configured
Write-Host "Blocked:" $snapshot.counts.blocked
Write-Host "Needs provider access:" $snapshot.counts.needs_access
Write-Host ""

foreach ($provider in @("google", "microsoft", "github")) {
    $providerBindings = @(
        $bindings |
            Where-Object {
                $_.provider_id -eq $provider -and
                $null -ne $_.connection_id
            }
    )

    if ($providerBindings.Count -eq 0) {
        throw "No connected capability bindings were found for provider '$provider'."
    }

    Write-Host ("{0}: {1} bound capabilities" -f $provider, $providerBindings.Count)
}

$incorrect = @(
    $bindings |
        Where-Object {
            $_.state -eq "configured" -and
            @($_.missing_scopes).Count -gt 0
        }
)

if ($incorrect.Count -gt 0) {
    Write-Host ""
    Write-Host "Incorrect capability rows:"
    $incorrect |
        Select-Object provider_id, account_hint, provider_capability_id, state, missing_scopes |
        Format-Table -AutoSize

    throw "A capability was reported as configured even though its provider scopes are missing."
}

$duplicateIds = @(
    $bindings |
        Group-Object id |
        Where-Object { $_.Count -gt 1 }
)

if ($duplicateIds.Count -gt 0) {
    throw "Capability binding IDs are not unique."
}

Write-Host ""
Write-Host "Sample provider capability states:"
$bindings |
    Select-Object -First 20 provider_id, account_hint, provider_capability_id, state, availability_reason, permission |
    Format-Table -AutoSize

Write-Host ""
Write-Host "PASS - Step 4A.3 registry is scope-aware and connection-specific."
Write-Host ""

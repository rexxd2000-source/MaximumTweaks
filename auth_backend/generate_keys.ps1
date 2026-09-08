<#
.SYNOPSIS
  MAXIMUM TWEAKS license key generator.

.DESCRIPTION
  Interactive mini-app that generates license keys through the backend's
  POST /admin/generate endpoint. The server URL ships as a built-in default
  and can be overridden with -Server or LICENSE_API_URL= in auth_backend\.env.

  The admin token comes from -Token, auth_backend\.env, or a built-in default
  that is only present in copies the owner hands out. The public copy on
  GitHub carries no token, so only authorized copies can generate keys.

  Choose the license duration interactively (1 month / 6 months / lifetime)
  or pass -Duration when scripting.

.PARAMETER Server
  Public URL of the license backend (e.g. https://your-domain). If omitted,
  LICENSE_API_URL from auth_backend\.env is used; if that is empty too, you
  are prompted.

.PARAMETER Count
  Number of keys to generate (1..500). Prompted if not passed.

.PARAMETER Customer
  Customer name/email to attach to the keys.

.PARAMETER Duration
  License length: 1m, 6m, or lifetime. Prompted if not passed.

.PARAMETER Plan
  Override the plan label (lifetime|monthly|yearly|custom).

.PARAMETER Note
  Free-text note attached to the keys.

.PARAMETER Expires
  Explicit expiry "YYYY-MM-DD HH:MM:SS" (overrides Duration).

.PARAMETER Token
  ADMIN_TOKEN. Defaults to ADMIN_TOKEN= in auth_backend\.env, then the
  built-in default embedded by the owner (authorized copies only).

.PARAMETER NoPause
  Don't wait for a keypress before closing.

.EXAMPLE
  .\generate_keys.ps1 -Server "https://your-server" -Count 5 -Customer "Alice"

.EXAMPLE
  .\generate_keys.ps1 -Duration lifetime -Count 1 -Customer "Bob"
#>
[CmdletBinding()]
param(
    [string]$Server = "",
    [int]$Count = 0,
    [string]$Customer = "",
    [ValidateSet("1m", "6m", "lifetime")]
    [string]$Duration = "",
    [ValidateSet("lifetime", "monthly", "yearly", "custom")]
    [string]$Plan = "",
    [string]$Note = "",
    [string]$Expires = "",
    [string]$Token = "",
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

# Built-in defaults. The PUBLIC copy on GitHub ships with a blank token so
# only people who receive an owner-authorized copy can generate keys.
$DefaultServer = "https://maximumtweaks.onrender.com"
$DefaultAdminToken = ""

function Get-EnvValue {
    param([string]$EnvFile, [string]$Key)
    if (-not (Test-Path $EnvFile)) { return "" }
    $line = Get-Content $EnvFile |
        Where-Object { $_ -match "^$Key=(.+)$" } |
        Select-Object -First 1
    if ($line) { return ($line -replace "^$Key=", "").Trim() }
    return ""
}

function Get-AdminToken {
    if ($Token) { return $Token }
    $envFile = Join-Path $PSScriptRoot ".env"
    $val = Get-EnvValue $envFile "ADMIN_TOKEN"
    if ($val) { return $val }
    if ($DefaultAdminToken) { return $DefaultAdminToken }
    throw "No admin token configured. Ask the Maximum Tweaks owner for an authorized copy of this script."
}

function Resolve-Server {
    if ($Server) { return $Server.Trim().TrimEnd("/") }
    $val = Get-EnvValue (Join-Path $PSScriptRoot ".env") "LICENSE_API_URL"
    if ($val) { return $val.Trim().TrimEnd("/") }
    if ($DefaultServer) { return $DefaultServer.Trim().TrimEnd("/") }
    $resp = Read-Host "License server URL (e.g. https://your-domain)"
    $resp = $resp.Trim().TrimEnd("/")
    if (-not $resp) {
        throw "No license server URL. Pass -Server or set LICENSE_API_URL= in auth_backend\.env"
    }
    return $resp
}

function Resolve-Duration {
    if ($Duration) { return $Duration }
    Write-Host ""
    Write-Host "  Choose license duration:" -ForegroundColor Cyan
    Write-Host "    1) 1 month"
    Write-Host "    2) 6 months"
    Write-Host "    3) Lifetime"
    $choice = Read-Host "  Choice (1/2/3)"
    switch ($choice.Trim()) {
        "1" { return "1m" }
        "2" { return "6m" }
        "3" { return "lifetime" }
        default { throw "Invalid duration choice: '$choice'" }
    }
}

try {
    $server = Resolve-Server
    $dur = Resolve-Duration

    $count = $Count
    if ($count -eq 0) {
        $count = [int](Read-Host "  Number of keys (1-500)")
    }
    if ($count -lt 1 -or $count -gt 500) {
        throw "Count must be between 1 and 500."
    }

    if (-not $Customer) {
        $Customer = Read-Host "  Customer name (optional)"
    }

    $planName = $Plan
    if (-not $planName) {
        $planName = switch ($dur) {
            "1m"       { "monthly" }
            "6m"       { "custom" }
            "lifetime" { "lifetime" }
        }
    }

    $expiresAt = $Expires
    if (-not $expiresAt -and $dur -ne "lifetime") {
        $months = if ($dur -eq "1m") { 1 } else { 6 }
        $expiresAt = (Get-Date).AddMonths($months).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss")
    }

    $token = Get-AdminToken
    $body = @{
        count    = $count
        plan     = $planName
        customer = $Customer
        note     = $Note
    }
    if ($expiresAt) { $body.expires_at = $expiresAt }

    Write-Host ""
    Write-Host "  MAXIMUM TWEAKS - License Key Generator" -ForegroundColor Cyan
    Write-Host "  --------------------------------------" -ForegroundColor Cyan
    Write-Host "  Duration : $dur"
    Write-Host "  Plan     : $planName"
    if ($expiresAt) { Write-Host "  Expires  : $expiresAt (UTC)" }
    Write-Host "  Count    : $count"
    if ($Customer) { Write-Host "  Customer : $Customer" }
    if ($Note)     { Write-Host "  Note     : $Note" }
    Write-Host ""

    $resp = Invoke-RestMethod -Uri "$server/admin/generate" -Method Post `
        -Headers @{ Authorization = "Bearer $token" } `
        -ContentType "application/json" `
        -Body ($body | ConvertTo-Json)

    Write-Host "  Generated $($resp.keys.Count) key(s):" -ForegroundColor Green
    Write-Host ""
    foreach ($k in $resp.keys) {
        Write-Host "    $k" -ForegroundColor White
    }
    Write-Host ""
    Write-Host "  Enter one of these on the app's Activate License screen." -ForegroundColor Yellow
}
catch {
    $status = "unknown"
    $detail = ""
    try {
        $respObj = $_.Exception.Response
        if ($respObj) {
            $status = [int]$respObj.StatusCode
            $stream = $respObj.GetResponseStream()
            if ($stream) {
                $reader = New-Object System.IO.StreamReader($stream)
                $detail = $reader.ReadToEnd()
            }
        }
    }
    catch { }
    Write-Host ""
    Write-Host "  FAILED (HTTP $status)" -ForegroundColor Red
    if ($detail) {
        Write-Host "  $detail" -ForegroundColor Red
    }
    else {
        Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    }
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        Read-Host "Press Enter to close..."
    }
}

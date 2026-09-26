<#
.SYNOPSIS
  Broadcast the Ultra Mode launch email to every subscribed waitlist address.

.DESCRIPTION
  Calls POST /admin/waitlist/send-launch on the live backend so you don't
  need Render Shell (not available on the free plan). The server URL comes
  from -Server, then LICENSE_API_URL= in auth_backend\.env, then a built-in
  default. The admin token comes from -Token, then ADMIN_TOKEN= in
  auth_backend\.env, then a built-in default (owner-authorized copies only).

  Use -List to just view the current waitlist roster without sending.

.PARAMETER Server
  Public URL of the backend (e.g. https://your-domain).

.PARAMETER Token
  Admin token. Defaults to ADMIN_TOKEN= in auth_backend\.env.

.PARAMETER Subject
.PARAMETER Heading
.PARAMETER Message
  Optional content overrides. Empty values fall back to env overrides
  (WAITLIST_*) on the server, then built-in defaults.

.PARAMETER CtaButton
  Optional call-to-action button text override.

.PARAMETER CtaUrl
  Optional call-to-action button URL override.

.PARAMETER To
  Optional single waitlist address to email instead of the whole roster.

.PARAMETER List
  Show the waitlist roster (GET /admin/waitlist) and exit - no email sent.

.PARAMETER Yes
  Skip the interactive "type SEND to confirm" prompt.

.PARAMETER Clipboard
  Copy the resulting JSON to the clipboard.

.PARAMETER NoPause
  Don't wait for a keypress before closing.

.EXAMPLE
  .\send_launch.ps1 -List

.EXAMPLE
  .\send_launch.ps1 -Subject "Maximum Tweaks is out now" -CtaUrl "https://max-opti.co.za/download"
#>
[CmdletBinding()]
param(
    [string]$Server = "",
    [string]$Token = "",
    [string]$Subject = "",
    [string]$Heading = "",
    [string]$Message = "",
    [string]$CtaButton = "",
    [string]$CtaUrl = "",
    [string]$To = "",
    [switch]$List,
    [switch]$Yes,
    [switch]$Clipboard,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

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
    $val = Get-EnvValue (Join-Path $PSScriptRoot ".env") "ADMIN_TOKEN"
    if ($val) { return $val }
    if ($DefaultAdminToken) { return $DefaultAdminToken }
    throw "No admin token configured. Ask the Maximum Tweaks owner for an authorized copy of this script."
}

function Resolve-Server {
    if ($Server) { return $Server.Trim().TrimEnd("/") }
    $val = Get-EnvValue (Join-Path $PSScriptRoot ".env") "LICENSE_API_URL"
    if ($val) { return $val.Trim().TrimEnd("/") }
    if ($DefaultServer) { return $DefaultServer.Trim().TrimEnd("/") }
    throw "No server URL. Pass -Server or set LICENSE_API_URL= in auth_backend\.env"
}

try {
    $server = Resolve-Server
    $token = Get-AdminToken
    $headers = @{ Authorization = "Bearer $token" }

    if ($List) {
        $resp = Invoke-RestMethod -Uri "$server/admin/waitlist" -Method Get -Headers $headers
        Write-Host ""
        Write-Host "  MAXIMUM TWEAKS - Waitlist Roster" -ForegroundColor Cyan
        Write-Host "  ---------------------------------" -ForegroundColor Cyan
        Write-Host "  Server     : $server"
        Write-Host "  Total      : $($resp.total)"
        Write-Host "  Subscribed : $($resp.subscribed)"
        Write-Host ""
        foreach ($e in $resp.entries) {
            $mark = if ($e.subscribed) { "ok" } else { "unsubscribed" }
            $notif = if ($e.notified) { "notified" } else { "pending" }
            Write-Host ("    {0,-42} {1,-13} {2}" -f $e.email, $mark, $notif) -ForegroundColor White
        }
    }
    else {
        $body = @{ code = $token }
        if ($Subject)   { $body.subject   = $Subject }
        if ($Heading)   { $body.heading   = $Heading }
        if ($Message)   { $body.message   = $Message }
        if ($CtaButton) { $body.cta_button = $CtaButton }
        if ($CtaUrl)    { $body.cta_url   = $CtaUrl }
        if ($To)        { $body.to_email  = $To }

        Write-Host ""
        Write-Host "  MAXIMUM TWEAKS - Launch Email Broadcast" -ForegroundColor Cyan
        Write-Host "  --------------------------------------" -ForegroundColor Cyan
        Write-Host "  Server : $server"
        if ($Subject) { Write-Host "  Subject: $Subject" }
        if ($To) { Write-Host "  To     : $To" }
        Write-Host ""

        if (-not $Yes) {
            $target = if ($To) { "email $To" } else { "email the entire waitlist" }
            $answer = Read-Host "  Type SEND to $target, anything else to cancel"
            if ($answer.Trim() -ne "SEND") {
                Write-Host "  Cancelled - no emails sent." -ForegroundColor Yellow
                exit 0
            }
        }

        $resp = Invoke-RestMethod -Uri "$server/admin/waitlist/send-launch" -Method Post `
            -Headers $headers `
            -ContentType "application/json" `
            -Body ($body | ConvertTo-Json)

        Write-Host "  OK - provider: $($resp.provider)" -ForegroundColor Green
        $resp.PSObject.Properties |
            Where-Object { $_.Name -notin @("ok", "provider") } |
            ForEach-Object {
                if ($_.Name -eq "failures") {
                    foreach ($f in @($_.Value)) {
                        Write-Host ("    failed  {0,-40} {1}" -f $f.email, $f.error) -ForegroundColor Red
                    }
                }
                else {
                    Write-Host ("    {0,-14} {1}" -f $_.Name, $_.Value) -ForegroundColor Green
                }
            }
        if ($Clipboard) {
            ($resp | ConvertTo-Json) | Set-Clipboard
            Write-Host "  Result JSON copied to clipboard." -ForegroundColor Yellow
        }
    }
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
# Rex Tweaks — build + publish a live-updatable release.
#
# Usage:
#   .\release.ps1 -Version 1.1.0            # bump APP_VERSION, build, tag, release
#   .\release.ps1 -Version 1.1.0 -SkipBuild # only tag + publish the existing exe
#
# Requirements:
#   - Python 3.10+, pip install pyinstaller
#   - GITHUB_REPO set in config/app_config.py (e.g. "you/RexTweaks")
#   - A GitHub PAT with `repo` scope in $env:GITHUB_TOKEN
#
# What it does:
#   1. Bumps APP_VERSION in config/app_config.py
#   2. PyInstaller build -> dist\RexTweaks.exe (one-file)
#   3. Creates tag v<VERSION> + a GitHub Release
#   4. Uploads RexTweaks.exe to the release
#   5. Prints the update source the app will check when GITHUB_REPO matches.
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$exeName = "RexTweaks.exe"
$exePath = Join-Path $root "dist\$exeName"

function Set-Version {
    $cfg = Join-Path $root "config\app_config.py"
    $content = Get-Content $cfg -Raw
    $content = $content -replace 'APP_VERSION = "[^"]*"', "APP_VERSION = `"$Version`""
    Set-Content $cfg $content -Encoding UTF8
    Write-Host "[1/5] APP_VERSION -> $Version" -ForegroundColor Cyan
}

function Build-Exe {
    Write-Host "[2/5] Building one-file exe (PyInstaller)..." -ForegroundColor Cyan
    python -m PyInstaller "$root\RexTweaks.spec" --noconfirm
    if (-not (Test-Path $exePath)) {
        throw "Build failed: $exePath not found"
    }
    Write-Host "      built: $exePath" -ForegroundColor Green
}

function Get-Repo {
    $repo = ""
    $cfg = Join-Path $root "config\app_config.py"
    $content = Get-Content $cfg -Raw
    if ($content -match 'GITHUB_REPO\s*=\s*"([^"]*)"') {
        $repo = $Matches[1].Trim().Trim("/")
    }
    return $repo
}

function Publish-Release {
    param([string]$Repo)
    if (-not $Repo) {
        Write-Warning "GITHUB_REPO is empty — set it in config/app_config.py to enable update checks."
        return
    }
    if (-not $env:GITHUB_TOKEN) {
        throw "GITHUB_TOKEN not set. Create one at https://github.com/settings/tokens (scope: repo)."
    }
    $tag = "v$Version"
    $api = "https://api.github.com/repos/$Repo/releases"

    Write-Host "[3/5] Ensuring tag $tag exists..." -ForegroundColor Cyan
    # Lightweight tag if the full tag is missing (rare).
    git -C $root tag $tag 2>$null
    git -C $root push origin $tag 2>$null

    Write-Host "[4/5] Creating GitHub Release $tag ..." -ForegroundColor Cyan
    $body = @{ tag_name = $tag; name = "Rex Tweaks v$Version"; body = "Rex Tweaks v$Version — see the in-app changelog for details." } | ConvertTo-Json
    $release = curl.exe -s -X POST $api -H "Authorization: Bearer $env:GITHUB_TOKEN" -H "Accept: application/vnd.github+json" -d $body | ConvertFrom-Json
    if (-not $release.id) {
        # Release may already exist for the tag; fetch its id.
        $existing = curl.exe -s "$api/$tag" -H "Authorization: Bearer $env:GITHUB_TOKEN" | ConvertFrom-Json
        $release = $existing
    }
    if (-not $release.id) {
        throw "Could not create release for $tag"
    }

    Write-Host "[5/5] Uploading $exeName ..." -ForegroundColor Cyan
    $upload = "https://uploads.github.com/repos/$Repo/releases/$($release.id)/assets?name=$exeName"
    curl.exe -s -X POST $upload -H "Authorization: Bearer $env:GITHUB_TOKEN" -H "Content-Type: application/octet-stream" --data-binary "@$exePath" | Out-Null
    Write-Host "      uploaded: $exePath" -ForegroundColor Green
    Write-Host ""
    Write-Host "Update source (the app auto-checks this when GITHUB_REPO matches):" -ForegroundColor Yellow
    Write-Host "  https://github.com/$Repo/releases/latest"
}

# ---- run ----
Set-Version
if (-not $SkipBuild) { Build-Exe }
$repo = Get-Repo
Publish-Release -Repo $repo
Write-Host "Done. Users on v$Version can click 'Check for Updates' once the next tag is published." -ForegroundColor Green
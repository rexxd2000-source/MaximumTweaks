# Maximum Tweaks - build + publish a live-updatable release.
#
# Usage:
#   .\release.ps1 -Version 2.0.1            # bump APP_VERSION, build, tag, release
#   .\release.ps1 -Version 2.0.1 -SkipBuild # only tag + publish the existing exe
#
# Requirements:
#   - Python 3.10+, pip install pyinstaller
#   - GITHUB_REPO set in config/app_config.py (e.g. "you/MaximumTweaks")
#   - A GitHub PAT with `repo` scope in $env:GITHUB_TOKEN
#
# What it does:
#   1. Bumps APP_VERSION in config/app_config.py
#   2. PyInstaller build -> dist\MaximumTweaks.exe (one-file)
#   3. Creates tag v<VERSION> + a GitHub Release
#   4. Uploads MaximumTweaks.exe to the release
#   5. Prints the update source the app will check when GITHUB_REPO matches.
#
# SECURITY: the update token is used ONLY inside this script (env var) for the
# tag push / release / asset upload. It is NEVER written into any config file
# or bundled into the exe. The repo itself is public, so client update checks
# require no token at all.
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$exeName = "MaximumTweaks.exe"
$exePath = Join-Path $root "dist\$exeName"

# Git may not be on PATH inside this script's shell; find it explicitly.
function Get-Git {
    $cands = @(
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\bin\git.exe",
        (Get-Command git -ErrorAction SilentlyContinue).Source
    )
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return "git"
}
$git = Get-Git

function Set-Version {
    $cfg = Join-Path $root "config\app_config.py"
    $content = Get-Content $cfg -Raw
    $content = $content -replace 'APP_VERSION = "[^"]*"', "APP_VERSION = `"$Version`""
    Set-Content $cfg $content -Encoding UTF8
    Write-Host "[1/5] APP_VERSION -> $Version" -ForegroundColor Cyan
}

function Build-Exe {
    # SECURITY: no token/file is written into the project or the exe. Update
    # authentication (if any) is consumed at runtime via the environment only.
    Write-Host "[2/5] Building one-file exe (PyInstaller)..." -ForegroundColor Cyan
    # Spec imports config.app_config, so build from the project root.
    Push-Location $root
    try {
        python -m PyInstaller "$root\MaximumTweaks.spec" --noconfirm
    }
    finally {
        Pop-Location
    }
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
        Write-Warning "GITHUB_REPO is empty - set it in config/app_config.py to enable update checks."
        return
    }
    if (-not $env:GITHUB_TOKEN) {
        throw "GITHUB_TOKEN not set. Create one at https://github.com/settings/tokens (scope: repo)."
    }
    $tag = "v$Version"
    $api = "https://api.github.com/repos/$Repo/releases"
    # Authenticated push URL so git can push the tag using the token.
    $owner = ($Repo -split "/")[0]
    $authPush = "https://$owner`:$env:GITHUB_TOKEN@github.com/$Repo.git"

    Write-Host "[4/5] Ensuring tag $tag exists..." -ForegroundColor Cyan
    $tagExists = $false
    & $git -C $root ls-remote --tags origin $tag 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $tagExists = $true
    }
    $tagExists = (Test-Path "$root\.git\refs\tags\$tag") -or $tagExists
    if (-not $tagExists) {
        & $git -C $root tag $tag
        & $git -C $root push "$authPush" $tag
    }
    else {
        Write-Host "      tag $tag already present - skipping." -ForegroundColor DarkGray
    }

    Write-Host "[5/5] Creating GitHub Release $tag ..." -ForegroundColor Cyan
    $body = @{ tag_name = $tag; name = "Maximum Tweaks v$Version"; body = "Maximum Tweaks v$Version - see the in-app changelog for details." } | ConvertTo-Json -Compress
    $bodyFile = Join-Path $env:TEMP "rexrelease_$Version.json"
    [System.IO.File]::WriteAllText($bodyFile, $body, [System.Text.UTF8Encoding]::new($false))
    $release = curl.exe -s -X POST $api -H "Authorization: Bearer $env:GITHUB_TOKEN" -H "Accept: application/vnd.github+json" --data-binary "@$bodyFile" | ConvertFrom-Json
    if (-not $release.id) {
        # Release may already exist for the tag; fetch its id.
        $existing = curl.exe -s "$api/$tag" -H "Authorization: Bearer $env:GITHUB_TOKEN" | ConvertFrom-Json
        $release = $existing
    }
    Remove-Item $bodyFile -ErrorAction SilentlyContinue
    if (-not $release.id) {
        throw "Could not create release for $tag"
    }

    Write-Host "[6/5] Uploading $exeName ..." -ForegroundColor Cyan
    $upload = "https://uploads.github.com/repos/$Repo/releases/$($release.id)/assets?name=$exeName"
    curl.exe -s -X POST $upload -H "Authorization: Bearer $env:GITHUB_TOKEN" -H "Content-Type: application/octet-stream" --data-binary "@$exePath" | Out-Null
    Write-Host "      uploaded: $exePath" -ForegroundColor Green
    Write-Host ""
    Write-Host "Update source (the app auto-checks this when GITHUB_REPO matches):" -ForegroundColor Yellow
    if ($env:GITHUB_TOKEN) {
        Write-Host "  https://api.github.com/repos/$Repo/releases/latest  (token set in publish env ONLY - never bundled in the exe)" -ForegroundColor Yellow
    }
    else {
        Write-Host "  https://github.com/$Repo/releases/latest  (public repo - no auth needed)" -ForegroundColor Yellow
    }
}

# ---- run ----
Set-Version
if (-not $SkipBuild) { Build-Exe }
$repo = Get-Repo
Publish-Release -Repo $repo
Write-Host "Done. Users on v$Version can click 'Check for Updates' once the next tag is published." -ForegroundColor Green
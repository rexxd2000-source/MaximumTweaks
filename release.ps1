# Maximum Tweaks - build + publish a live-updatable release.
#
# Usage:
#   .\release.ps1 -Version 2.4.3            # bump APP_VERSION, build, tag, release
#   .\release.ps1 -Version 2.4.3 -SkipBuild # only tag + publish the existing exe
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

function Get-Checksum {
    # Hash the built exe and publish it next to it as <exe>.sha256 so the
    # in-app updater can verify downloads (returns the bare hex digest).
    if (-not (Test-Path $exePath)) {
        Write-Warning "No exe at $exePath - manifest will be published without a checksum."
        return ""
    }
    $hash = (Get-FileHash -Path $exePath -Algorithm SHA256).Hash.ToLower()
    Set-Content -Path "$exePath.sha256" -Value "$hash  $exeName" -Encoding ascii
    Write-Host "      sha256: $hash" -ForegroundColor DarkGray
    return $hash
}

function Update-Manifest {
    param([string]$Sha256 = "")
    # Regenerate the served /update.json (auth_backend\web\update.json) so the
    # desktop app's built-in UPDATE_MANIFEST_URL points at this new build.
    # NOTE: the canonical GitHub asset path is /releases/download/... - the
    # shorter /download/... form 404s.
    $dl = "https://github.com/$Repo/releases/download/v$Version/$exeName"
    $m = @{
        version = $Version
        notes   = "Maximum Tweaks v$Version - see the in-app changelog for details."
        url     = $dl
    }
    if ($Sha256) {
        $m["sha256"] = $Sha256
        $m["checksum_url"] = "$dl.sha256"
    }
    # NSIS-installed copies update by re-running the setup instead of the
    # in-place exe swap (Program Files is not writable unelevated). The
    # installer itself is built + checksummed by CI (release.yml) from the
    # same tag, so its asset URL is deterministic here.
    $setupName = "MaximumTweaks-Setup-$Version.exe"
    $setupDl = "https://github.com/$Repo/releases/download/v$Version/$setupName"
    $m["installer_url"] = $setupDl
    $m["installer_checksum_url"] = "$setupDl.sha256"
    $m = $m | ConvertTo-Json
    $manifest = Join-Path $root "auth_backend\web\update.json"
    Set-Content $manifest $m -Encoding UTF8
    Write-Host "      manifest -> auth_backend\web\update.json (version $Version)" -ForegroundColor DarkGray
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

    Write-Host "[4/5] Ensuring tag $tag exists..." -ForegroundColor Cyan
    $tagLines = & $git -C $root ls-remote --tags origin "refs/tags/$tag" 2>$null
    $tagExists = [bool]$tagLines
    if (-not $tagExists) {
        & $git -C $root tag $tag
        # Pass the token through environment-scoped git config so it never
        # shows up in the command line, shell history, or git's error output
        # (the previous https://user:token@... push URL did all three).
        $b64 = [Convert]::ToBase64String(
            [Text.Encoding]::UTF8.GetBytes("x-access-token:$env:GITHUB_TOKEN"))
        $env:GIT_CONFIG_COUNT = "1"
        $env:GIT_CONFIG_KEY_0 = "http.https://github.com/.extraheader"
        $env:GIT_CONFIG_VALUE_0 = "AUTHORIZATION: basic $b64"
        try {
            & $git -C $root push origin $tag
            if ($LASTEXITCODE -ne 0) {
                throw "git push of tag $tag failed (exit $LASTEXITCODE)"
            }
        }
        finally {
            Remove-Item Env:GIT_CONFIG_COUNT, Env:GIT_CONFIG_KEY_0, Env:GIT_CONFIG_VALUE_0 -ErrorAction SilentlyContinue
        }
    }
    else {
        Write-Host "      tag $tag already present - skipping." -ForegroundColor DarkGray
    }

    Write-Host "[5/5] Creating GitHub Release $tag ..." -ForegroundColor Cyan
    $body = @{ tag_name = $tag; name = "Maximum Tweaks v$Version"; body = "Maximum Tweaks v$Version - see the in-app changelog for details." } | ConvertTo-Json -Compress
    $bodyFile = Join-Path $env:TEMP "release_$Version.json"
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
    $shaPath = "$exePath.sha256"
    if (Test-Path $shaPath) {
        $uploadSha = "https://uploads.github.com/repos/$Repo/releases/$($release.id)/assets?name=$exeName.sha256"
        curl.exe -s -X POST $uploadSha -H "Authorization: Bearer $env:GITHUB_TOKEN" -H "Content-Type: application/octet-stream" --data-binary "@$shaPath" | Out-Null
        Write-Host "      uploaded: $shaPath" -ForegroundColor Green
    }
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
$sha256 = Get-Checksum
Update-Manifest -Sha256 $sha256
Publish-Release -Repo $repo
Write-Host "Done. Users on v$Version can click 'Check for Updates' once the next tag is published." -ForegroundColor Green
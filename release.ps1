# Maximum Tweaks - cut a release (CI does the build + publish).
#
# Usage:
#   .\release.ps1 -Version 2.5.3            # bump, manifest, commit, tag, push
#   .\release.ps1 -Version 2.5.3 -SkipBuild # skip the local PyInstaller build
#
# Requirements:
#   - Python 3.14 + pinned requirements (README "Build the .exe") unless -SkipBuild
#   - GITHUB_REPO set in config/app_config.py
#   - An authenticated `git push` to origin (your normal GitHub login).
#     NO PAT and no token are used anywhere in this script: pushing the tag
#     triggers .github/workflows/release.yml, which builds the exe + NSIS
#     installer, publishes sizes and SHA-256 hashes in the job summary,
#     validates the update manifest, and creates the GitHub Release with its
#     built-in GITHUB_TOKEN.
#
# What it does:
#   1. Bumps APP_VERSION in config/app_config.py
#   2. (unless -SkipBuild) PyInstaller build -> dist\MaximumTweaks.exe for a
#      local smoke test only - the published artifact is the CI-built one
#   3. Regenerates auth_backend\web\update.json. Prerelease versions
#      (containing "-") keep the stable manifest version and only ensure the
#      installer fields exist, so stable users are never offered an rc.
#   4. Commits steps 1+3, pushes main, creates tag v<VERSION>, pushes it
#   5. CI validates + publishes; watch the Actions tab
#
# SECURITY: the workflow's GITHUB_TOKEN is scoped to the workflow run and
# never leaves GitHub. Nothing is read from a local token file and nothing
# secret is bundled into the exe.
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

function Update-Manifest {
    param([string]$Repo)
    # Regenerate the served /update.json (auth_backend\web\update.json) so the
    # desktop app's built-in UPDATE_MANIFEST_URL points at this new build.
    # NOTE: the canonical GitHub asset path is /releases/download/... - the
    # shorter /download/... form 404s.
    $manifest = Join-Path $root "auth_backend\web\update.json"
    $dl = "https://github.com/$Repo/releases/download/v$Version/$exeName"
    $setupName = "MaximumTweaks-Setup-$Version.exe"
    $setupDl = "https://github.com/$Repo/releases/download/v$Version/$setupName"

    if ($Version -match '-') {
        # Prerelease: keep the manifest's version/url on the current stable
        # build so stable users are never offered an rc. Only make sure the
        # installer fields exist - the CI release gate requires them (they are
        # never fetched while the manifest version is unchanged).
        try {
            $m = Get-Content $manifest -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Could not parse ${manifest}: $_"
        }
        if (-not $m.installer_url) {
            $m | Add-Member -NotePropertyName installer_url -NotePropertyValue $setupDl
        }
        if (-not ($m.installer_checksum_url -or $m.installer_sha256)) {
            $m | Add-Member -NotePropertyName installer_checksum_url -NotePropertyValue "$setupDl.sha256"
        }
        $m | ConvertTo-Json | Set-Content $manifest -Encoding UTF8 -ErrorAction Stop
        Write-Host "      manifest: prerelease - stable version kept, installer fields ensured" -ForegroundColor DarkGray
        return
    }

    $m = @{
        version                = $Version
        notes                  = "Maximum Tweaks v$Version - see the in-app changelog for details."
        url                    = $dl
        # CI publishes the .sha256 files next to the artifacts it builds; a
        # hash of the local (dev-only) build would not match what users
        # download, so only the checksum URL is recorded.
        checksum_url           = "$dl.sha256"
        installer_url          = $setupDl
        installer_checksum_url = "$setupDl.sha256"
    }
    $m = $m | ConvertTo-Json
    Set-Content $manifest $m -Encoding UTF8 -ErrorAction Stop
    Write-Host "      manifest -> auth_backend\web\update.json (version $Version)" -ForegroundColor DarkGray
}

function Build-Exe {
    Write-Host "[2/5] Building one-file exe (PyInstaller, local smoke test only)..." -ForegroundColor Cyan
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

function Publish-Tag {
    param([string]$Repo)
    if (-not $Repo) {
        Write-Warning "GITHUB_REPO is empty - set it in config/app_config.py to enable update checks."
        return
    }
    $tag = "v$Version"

    # Commit the release edits before tagging, otherwise the tag (and the CI
    # build it triggers) would not contain the version bump or the manifest.
    Write-Host "[3/5] Committing release changes..." -ForegroundColor Cyan
    & $git -C $root add -- "config/app_config.py" "auth_backend/web/update.json"
    $dirty = & $git -C $root status --porcelain -- "config/app_config.py" "auth_backend/web/update.json"
    if ($dirty) {
        & $git -C $root commit -m "release: v$Version"
        if ($LASTEXITCODE -ne 0) { throw "git commit failed (exit $LASTEXITCODE)" }
    }

    Write-Host "[4/5] Pushing main..." -ForegroundColor Cyan
    & $git -C $root push origin HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed (exit $LASTEXITCODE). Push main yourself, then re-run."
    }

    Write-Host "[5/5] Tagging $tag and pushing..." -ForegroundColor Cyan
    $tagLines = & $git -C $root ls-remote --tags origin "refs/tags/$tag" 2>$null
    if ($tagLines) {
        Write-Host "      tag $tag already present - skipping." -ForegroundColor DarkGray
    }
    else {
        & $git -C $root tag $tag
        if ($LASTEXITCODE -ne 0) { throw "git tag failed (exit $LASTEXITCODE)" }
        # Plain push with your normal git credentials - no token in the
        # command line, no token in git config, no token anywhere.
        & $git -C $root push origin $tag
        if ($LASTEXITCODE -ne 0) { throw "git push of tag $tag failed (exit $LASTEXITCODE)" }
    }
    Write-Host ""
    Write-Host "Pushed. The Release workflow now builds the exe + installer," -ForegroundColor Yellow
    Write-Host "hashes them in the job summary, validates update.json, and" -ForegroundColor Yellow
    Write-Host "creates the GitHub Release. Watch the Actions tab." -ForegroundColor Yellow
}

# ---- run ----
Set-Version
if (-not $SkipBuild) { Build-Exe }
$repo = Get-Repo
Update-Manifest -Repo $repo
Publish-Tag -Repo $repo
Write-Host "Done. Users on the previous version see this update once the manifest version exceeds theirs." -ForegroundColor Green

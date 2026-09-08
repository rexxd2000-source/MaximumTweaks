# Maximum Tweaks - scheduled publish wrapper (runs at 11:00).
# Pushes the latest committed state to origin/main, then builds + tags and
# publishes the GitHub Release so clients can update.
#
# SECURITY: the publish token is read from a locked file OUTSIDE the repo
# (created by the operator). It is never stored in the repo or committed.
$ErrorActionPreference = "Stop"
$root = "C:\Users\Admin\Documents\Default Project\RexTweaks"
$log  = "C:\Users\Admin\Documents\Default Project\RexTweaks\publish_log.txt"
$tokenFile = "$env:USERPROFILE\.maximumtweaks\publish_token.txt"

# Scheduled tasks get a bare PATH - make sure the real Python (and its Scripts)
# resolve so release.ps1 can run the PyInstaller build.
$pyDir = "C:\Users\Admin\AppData\Local\Python\pythoncore-3.14-64"
if (Test-Path (Join-Path $pyDir "python.exe")) {
    $env:PATH = "$pyDir;$pyDir\Scripts;" + $env:PATH
}
$git = "C:\Program Files\Git\bin\git.exe"
& $git config --global --add safe.directory "$root" 2>$null | Out-Null

function Log([string]$msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Add-Content -Path $log -Value $line
    Write-Host $line
}

# Read the current APP_VERSION from config/app_config.py.
function Get-Version {
    $cfg = Join-Path $root "config\app_config.py"
    $m = (Get-Content $cfg -Raw) -match 'APP_VERSION\s*=\s*"([^"]*)"'
    if ($m) { return $Matches[1] }
    throw "APP_VERSION not found in $cfg"
}
$version = Get-Version

# Load the publish token from the locked file (env for release.ps1). SECURITY:
# the token is consumed at publish time only and never written into the repo.
if (-not (Test-Path $tokenFile)) {
    Log "FATAL: token file not found at $tokenFile"
    exit 1
}
$token = ([System.IO.File]::ReadAllText($tokenFile)).Trim()
if (-not $token) {
    Log "FATAL: publish token is empty"
    exit 1
}
$env:GITHUB_TOKEN = $token

Log "Publishing Maximum Tweaks v$version"

# 1. Push the committed changes to origin/main (token-authenticated so the
#    scheduled task works without an interactive credential prompt).
$repo = "rexxd2000-source/MaximumTweaks"
$owner = ($repo -split "/")[0]
$authPush = "https://$owner`:$token@github.com/$repo.git"

Push-Location $root
try {
    Log "git push origin main"
    & $git push "$authPush" main 2>&1 | ForEach-Object { Log $_ }
    if ($LASTEXITCODE -ne 0) {
        Log "FATAL: git push failed"
        exit 1
    }
}
finally {
    Pop-Location
}

# 2. Build + tag + release via release.ps1.
Log "running release.ps1 -Version $version"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "release.ps1") -Version "$version" 2>&1 | ForEach-Object { Log $_ }
if ($LASTEXITCODE -ne 0) {
    Log "FATAL: release.ps1 failed"
    exit 1
}

Log "Done - v$version published."
# Maximum Tweaks - scheduled publish wrapper (runs at 14:00).
# Pushes the latest commit to origin/main, then builds + tags v2.0.4 and
# publishes the GitHub Release so clients can update.
$ErrorActionPreference = "Stop"
$root = "C:\Users\Admin\Documents\Default Project\RexTweaks"
$log  = "C:\Users\Admin\Documents\Default Project\RexTweaks\publish_log.txt"

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

# Load the update token from config\_secrets.py (gitignored).
$secrets = Join-Path $root "config\_secrets.py"
$token = $null
if (Test-Path $secrets) {
    $content = Get-Content $secrets -Raw
    if ($content -match 'GITHUB_TOKEN\s*=\s*"([^"]+)"') {
        $token = $Matches[1]
    }
}
if (-not $token) {
    Log "FATAL: GITHUB_TOKEN not found in config\_secrets.py"
    exit 1
}

Log "Publishing Maximum Tweaks v2.0.4"
$env:GITHUB_TOKEN = $token

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
Log "running release.ps1 -Version 2.0.4"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "release.ps1") -Version "2.0.4" 2>&1 | ForEach-Object { Log $_ }
if ($LASTEXITCODE -ne 0) {
    Log "FATAL: release.ps1 failed"
    exit 1
}

Log "Done - v2.0.4 published."

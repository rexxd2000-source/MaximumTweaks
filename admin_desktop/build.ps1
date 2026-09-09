# Maximum Tweaks Admin - build the shareable desktop EXE.
#
#   .\build.ps1          # build a fresh MaximumTweaksAdmin.exe
#
# Output: dist\MaximumTweaksAdmin.exe  (one-file, no install needed)
# Give that single file to your staff - they sign in with the ADMIN_TOKEN.
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exePath = Join-Path $root "dist\MaximumTweaksAdmin.exe"

Write-Host "[1/2] Building MaximumTweaksAdmin.exe (PyInstaller)..." -ForegroundColor Cyan
Push-Location $root
try {
    python -m PyInstaller "$root\admin_desktop\Admin.spec" --noconfirm --log-level WARN
}
finally {
    Pop-Location
}

if (-not (Test-Path $exePath)) {
    throw "Build failed - expected $exePath"
}

$sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "[2/2] Done: $exePath ($sizeMB MB)" -ForegroundColor Green
Write-Host ""
Write-Host "Share this ONE file with anyone who should manage licenses."
Write-Host "They sign in with the ADMIN_TOKEN (server URL: https://maximumtweaks.onrender.com)."
Write-Host "No admin token is baked into the exe." -ForegroundColor Yellow
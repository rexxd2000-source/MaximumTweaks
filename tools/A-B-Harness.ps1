param(
    [string]$SnapshotDir = "",
    [string]$TweakId = "MANUAL (apply in the app)",
    [string]$BaselineLabel = "baseline"
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

Write-Host ""
Write-Host "================ A/B TEST HARNESS ================"
Write-Host "Tweak under test : $TweakId"
Write-Host ""

$baseline = $SnapshotDir
if (-not $baseline) {
    Write-Host "[1/4] Capturing baseline snapshot (clean Windows state)..."
    & (Join-Path $here "Baseline-Capture.ps1") -OutDir (Join-Path $here "snapshots\$BaselineLabel")
    $baseline = (Get-ChildItem (Join-Path $here "snapshots") -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
} else {
    if (-not (Test-Path $baseline)) { Write-Host "Snapshot dir not found: $baseline"; exit 1 }
    Write-Host "[1/4] Using existing baseline snapshot: $baseline"
}

Write-Host ""
Write-Host "[2/4] NOW APPLY the tweak being tested:"
Write-Host "      - In MaximumTweaks, toggle ONLY: $TweakId"
Write-Host "      - Reboot if the tweak requires it (HKLM / services / drivers)."
Write-Host "      - Run your Fortnite benchmark/replay at a fixed scene and record:"
Write-Host "          avg FPS, 1% low, 0.1% low, max frametime (RTSS/CapFrameX log)."
Read-Host "      Press ENTER when the with-tweak run is finished"

$applied = Join-Path $here "snapshots\applied-$TweakId-" + (Get-Date -Format "yyyyMMdd-HHmmss")
& (Join-Path $here "Baseline-Capture.ps1") -OutDir $applied

Write-Host ""
Write-Host "[3/4] NOW REVERT the tweak in the app (Apply clean / toggle off),"
Write-Host "      reboot if needed, and run the SAME benchmark again."
Write-Host "      Record the same metrics."
Read-Host "      Press ENTER when the reverted run is finished"

$reverted = Join-Path $here "snapshots\reverted-$TweakId-" + (Get-Date -Format "yyyyMMdd-HHmmss")
& (Join-Path $here "Baseline-Capture.ps1") -OutDir $reverted

Write-Host ""
Write-Host "[4/4] Diffing baseline -> applied (what the tweak changed)..."
$diff1 = Join-Path $here ("diff-$TweakId-applied-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
& (Join-Path $here "Register-Diff.ps1") -Before $baseline -After $applied -OutFile $diff1

Write-Host ""
Write-Host "[4/4] Diffing applied -> reverted (rollback verification)..."
$diff2 = Join-Path $here ("diff-$TweakId-reverted-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
& (Join-Path $here "Register-Diff.ps1") -Before $applied -After $reverted -OutFile $diff2

Write-Host ""
Write-Host "================ SUMMARY ================"
Write-Host "baseline : $baseline"
Write-Host "applied  : $applied"
Write-Host "reverted : $reverted"
Write-Host ""
Write-Host "diff baseline->applied : $diff1"
Write-Host "diff applied->reverted : $diff2"
Write-Host ""
Write-Host "For a clean investigation THIS is the goal:"
Write-Host "  diff2 (applied->reverted) should undo exactly what diff1 (baseline->applied) did."
Write-Host "  If values do not return to the baseline values, rollback is incomplete."
Write-Host ""
Write-Host "Record the benchmark numbers and feed them to:"
Write-Host "  python frametime_regression_test.py --baseline <capframex-baseline.csv> --compare <capframex-applied.csv>"
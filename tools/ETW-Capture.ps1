param(
    [string]$Output = "",
    [string]$Profiles = "CPU GPU Power"
)

$ErrorActionPreference = "Stop"

$wpr = Get-Command wpr.exe -ErrorAction SilentlyContinue
if (-not $wpr) {
    Write-Host "wpr.exe not found (Windows Performance Recorder is part of Windows)."
    exit 1
}

if (-not $Output) {
    $Output = Join-Path $PSScriptRoot ("trace-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".etl")
}

Write-Host ""
Write-Host "================ ETW CAPTURE ================"
Write-Host "Profiles : $Profiles"
Write-Host "Output   : $Output"
Write-Host ""

& wpr.exe -stop $Output 2>&1 | Out-Null

$wprStart = @("-start", "GeneralProfile")
$wprStart = @()
foreach ($p in $Profiles.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)) {
    $wprStart += @("-start", $p)
}

$proc = Start-Process -FilePath "wpr.exe" -ArgumentList ($wprStart + @("-filemode")) -Wait -PassThru -NoNewWindow
if ($proc.ExitCode -ne 0) {
    Write-Host "wpr -start failed (exit $($proc.ExitCode)). Verify profile names:"
    Write-Host "  wpr -profiles"
    exit 1
}
Write-Host "Tracing started. Reproduce the 500->60->500 collapse now in your game."
Read-Host "Press ENTER to stop tracing"

$proc = Start-Process -FilePath "wpr.exe" -ArgumentList @("-stop", $Output) -Wait -PassThru -NoNewWindow
if ($proc.ExitCode -ne 0) {
    Write-Host "wpr -stop failed (exit $($proc.ExitCode))."
    exit 1
}

Write-Host ""
Write-Host "Trace saved to: $Output"
Write-Host "Open it in Windows Performance Analyzer:"
Write-Host "  - Look for 'GPU Utilization', 'CPU Ready/Wait Time' and the"
Write-Host "    'DWM/GPU Process' + game process scheduler rows around the collapse."
Write-Host "  - Correlate the collapse window with a service/scheduled-task wake-up"
Write-Host "    (DiagTrack, NV display container) or a GPU clock drop."
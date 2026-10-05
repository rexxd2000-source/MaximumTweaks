$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$gpus = @(Get-PnpDevice -Class Display -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match 'VEN_10DE' })
if ($gpus.Count -eq 0) {
    Write-Host '[ERROR] No NVIDIA GPU - VEN_10DE not detected. Exiting.'
    exit 1
}

$folder = @(Get-ChildItem -Path (Join-Path $here 'nvidia-backups') -Directory -Filter 'msi-*' -ErrorAction SilentlyContinue | Where-Object { @(Get-ChildItem -Path $_.FullName -Filter '*.reg' -ErrorAction SilentlyContinue).Count -gt 0 } | Sort-Object Name -Descending | Select-Object -First 1)
if ($folder.Count -eq 0) {
    Write-Host ' [ERROR] No MSI backup folder found - expected nvidia-backups\msi-*.'
    Write-Host '         Without an exact-state backup MaximumTweaks will NOT guess how'
    Write-Host '         to restore. Reinstall the GPU driver or delete the'
    Write-Host '         MSISupported value manually in:'
    Write-Host '         HKLM\SYSTEM\CurrentControlSet\Enum\...\Device Parameters\'
    Write-Host '         Interrupt Management\MessageSignaledInterruptProperties'
    exit 1
}
$bk = $folder[0].FullName
Write-Host (" Restoring exact prior interrupt state from: {0}" -f $bk)

$imported = 0
foreach ($r in Get-ChildItem -Path $bk -Filter 'msi-*.reg') {
    reg.exe import $r.FullName 2>$null | Out-Null
    Write-Host ("   imported {0}" -f $r.Name)
    $imported++
}

$leaf = 'Device Parameters\Interrupt Management\MessageSignaledInterruptProperties'
foreach ($g in $gpus) {
    $inst = $g.InstanceId
    $key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$inst\$leaf"
    $cur = if (Test-Path $key) { (Get-ItemProperty -Path $key -Name MSISupported -ErrorAction SilentlyContinue).MSISupported } else { $null }
    if ($cur -eq 1) {
        Write-Host ("  [info] {0} still shows MSISupported=1 - backup may already have this value, or reboot pending" -f $inst)
    } else {
        Write-Host ("  [ok]   {0} MSISupported no longer set to 1" -f $inst)
    }
}

Write-Host ''
Write-Host ' Restore complete. A REBOOT may be required.'
exit 0
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$bk = Join-Path $here ("nvidia-backups\msi-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))

$gpus = @(Get-PnpDevice -Class Display -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match 'VEN_10DE' })
if ($gpus.Count -eq 0) {
    Write-Host '[ERROR] No NVIDIA GPU - VEN_10DE not detected. Exiting without changes.'
    exit 1
}
Write-Host (" Detected {0} NVIDIA device(s). Targeting only NVIDIA hardware." -f $gpus.Count)

$leaf = 'Device Parameters\Interrupt Management\MessageSignaledInterruptProperties'
$made = 0
$skipped = 0
foreach ($g in $gpus) {
    $inst = $g.InstanceId
    $key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$inst\$leaf"
    $rawKey = "HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Enum\$inst\$leaf"
    $exists = Test-Path $key
    $cur = $null
    if ($exists) { $cur = (Get-ItemProperty -Path $key -Name MSISupported -ErrorAction SilentlyContinue).MSISupported }
    if ($cur -eq 1) {
        Write-Host ("  [skip] {0} : MSI already enabled." -f $inst)
        $skipped++
        continue
    }
    if (-not (Test-Path $bk)) { New-Item -ItemType Directory -Path $bk -Force | Out-Null }
    $backFile = Join-Path $bk ('msi-' + ($inst -replace '[\\&#]', '_') + '.reg')
    $lines = @('Windows Registry Editor Version 5.00', '')
    if ($exists) {
        $item = Get-Item -Path $key
        $lines += "[$rawKey]"
        foreach ($vn in $item.GetValueNames()) {
            $val = $item.GetValue($vn)
            switch ($item.GetValueKind($vn)) {
                'DWord' { $lines += ('"{0}"=dword:{1:x8}' -f $vn, $val) }
                'String' { $lines += ('"{0}"="{1}"' -f $vn, ($val -replace '"', '\"')) }
                'ExpandString' { $lines += ('"{0}"=hex(2):{1}' -f $vn, (($val -replace '"', '\"') -as [string])) }
            }
        }
    } else {
        $lines += "[-$rawKey]"
    }
    $lines += ''
    Set-Content -Path $backFile -Value $lines -Encoding Ascii
    Write-Host ("  [backup] current interrupt state of {0} saved to {1}" -f $inst, $backFile)
    if (-not $exists) { New-Item -Path $key -Force | Out-Null }
    Set-ItemProperty -Path $key -Name MSISupported -Value 1 -Type DWord
    $now = (Get-ItemProperty -Path $key -Name MSISupported -ErrorAction SilentlyContinue).MSISupported
    if ($now -eq 1) {
        Write-Host ("  [ok]    {0} : MSISupported set to 1 - verified." -f $inst)
        $made++
    } else {
        Write-Host ("  [error] {0} : MSISupported did not verify. Restoring backup..." -f $inst)
        if (Test-Path $backFile) { reg.exe import $backFile 2>$null | Out-Null }
    }
}

Write-Host ''
if ($made -gt 0) {
    Write-Host " MSI enabled on $made NVIDIA devices."
    Write-Host ' A REBOOT is required for the change to take effect.'
    Write-Host " Verify with Device Manager: Details -> Interrupt Requested (IRQ)"
    Write-Host ' or GPU-Z, then A/B test with tools\A-B-Harness.ps1.'
} elseif ($skipped -gt 0) {
    Write-Host ' All detected NVIDIA devices were already using MSI. Nothing changed.'
} else {
    Write-Host ' [WARNING] No NVIDIA display device was changed.'
}
Write-Host ' Restore: NVIDIA-GPU-MSI-Restore.bat'
exit 0
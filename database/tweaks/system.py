"""Category: System — OS-level memory, crash and responsiveness settings."""
from __future__ import annotations

import base64 as _b64

from ._base import make_T, validate_module

T = make_T("System", win_default="7,8,10,11")
CATEGORY = "System"


def _PS(script: str, timeout: int = 30) -> tuple:
    """Build a ("cmd", ...) action that runs a PowerShell script via
    -EncodedCommand.  Base64 avoids the nested-quoting breakage that hits long
    P/Invoke scripts when they are passed through cmd.exe (shell=True).
    Keep the encoded line under the 8191-char cmd line limit."""
    enc = _b64.b64encode(script.encode("utf-16-le")).decode("ascii")
    cmd = "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand " + enc
    return ("cmd", cmd, timeout)


_PERF_ECOQOS = r'''$ProgressPreference='SilentlyContinue'

$ProgressPreference='SilentlyContinue'
$ErrorActionPreference='SilentlyContinue'
Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;
public static class E{[DllImport("user32.dll")]public static extern IntPtr GetForegroundWindow();[DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);[DllImport("kernel32.dll")]public static extern IntPtr CreateToolhelp32Snapshot(uint f,uint p);[DllImport("kernel32.dll")]public static extern bool Thread32First(IntPtr s,ref T t);[DllImport("kernel32.dll")]public static extern bool Thread32Next(IntPtr s,ref T t);[DllImport("kernel32.dll")]public static extern IntPtr OpenThread(uint a,bool i,uint t);[DllImport("kernel32.dll")]public static extern bool GetThreadInformation(IntPtr h,int c,IntPtr i,uint l);[DllImport("kernel32.dll")]public static extern bool SetThreadInformation(IntPtr h,int c,IntPtr i,uint l);[DllImport("kernel32.dll")]public static extern bool CloseHandle(IntPtr h);[StructLayout(LayoutKind.Sequential)]public struct T{public uint s,c,t,o;public int b,d;public uint f;}}
'@
$h=[E]::GetForegroundWindow();$p=[uint32]0;[void][E]::GetWindowThreadProcessId($h,[ref]$p)
if($p -eq 0){Write-Output "No foreground window found - focus the game, then Apply again.";exit 0}
$proc=Get-Process -Id $p -ErrorAction SilentlyContinue
if(-not $proc){Write-Output "Foreground process not accessible.";exit 1}
Write-Output ("Foreground game/process: {0} (PID {1})" -f $proc.ProcessName,$p)
$snap=[E]::CreateToolhelp32Snapshot(4,0)
if($snap -eq [IntPtr]::Zero){Write-Output "Thread snapshot failed.";exit 1}
$t=New-Object 'E+T';$t.s=[System.Runtime.InteropServices.Marshal]::SizeOf($t)
$cleared=0;$wasEco=0
if([E]::Thread32First($snap,[ref]$t)){do{if($t.o -eq $p){$hT=[E]::OpenThread(0x0820,$false,$t.c);if($hT -ne [IntPtr]::Zero){$b=[System.Runtime.InteropServices.Marshal]::AllocHGlobal(4);try{if([E]::GetThreadInformation($hT,2,$b,4)){$q=[uint32][System.Runtime.InteropServices.Marshal]::ReadInt32($b);if($q -ge 4 -and $q -le 6){$wasEco++;$z=[System.Runtime.InteropServices.Marshal]::AllocHGlobal(4);[System.Runtime.InteropServices.Marshal]::WriteInt32($z,1);if([E]::SetThreadInformation($hT,2,$z,4)){$cleared++};[System.Runtime.InteropServices.Marshal]::FreeHGlobal($z)}}}finally{[System.Runtime.InteropServices.Marshal]::FreeHGlobal($b);[void][E]::CloseHandle($hT)}}}}while([E]::Thread32Next($snap,[ref]$t))}
[void][E]::CloseHandle($snap)
Write-Output ("EcoQoS threads detected: {0}" -f $wasEco)
Write-Output ("Threads set to Normal QoS: {0}" -f $cleared)
Write-Output "Efficiency/EcoQoS cleared for the foreground process only. Windows-wide EcoQoS is untouched."
Write-Output "Re-Apply after the game launches to re-clear any new threads."
'''

_DIAG_PCIE = r'''$ProgressPreference='SilentlyContinue'

$ProgressPreference='SilentlyContinue'
$ErrorActionPreference = 'SilentlyContinue'
$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Microsoft' } | Select-Object -First 1
if (-not $gpu) { Write-Output "No GPU detected."; exit 0 }
Write-Output ("GPU: {0}" -f $gpu.Name)
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
  $line = & nvidia-smi --query-gpu=pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max --format=csv,noheader,nounits
  if ($LASTEXITCODE -eq 0 -and $line) {
    $parts = $line -split ',\s*'
    $genCur  = $parts[0].Trim(); $genMax = $parts[1].Trim()
    $wCur    = $parts[2].Trim(); $wMax   = $parts[3].Trim()
    Write-Output ("PCIe generation: {0} (max {1})" -f $genCur, $genMax)
    Write-Output ("PCIe link width: x{0} (max x{1})" -f $wCur, $wMax)
    $bad = ($wCur -ne $wMax) -or ($genCur -ne $genMax)
    if ($bad) { Write-Output "Status: WARNING - GPU is below its maximum PCIe link. Check slot seating, lane-sharing and BIOS settings." }
    else      { Write-Output "Status: OK - GPU is at full PCIe link." }
    Write-Output "Diagnostic only. Re-seat the card and verify in the BIOS if a drop is unexpected."
    exit 0
  }
}
Write-Output "PCIe link speed/width not exposed by vendor telemetry on this system."
Write-Output "Use the GPU vendor's tool (GPU-Z, nvidia-smi) to verify the link under load."
'''

_DIAG_THROTTLE = r'''$ProgressPreference='SilentlyContinue'

$ErrorActionPreference = 'SilentlyContinue'
Write-Output "GPU Performance Health"
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
  $line = & nvidia-smi --query-gpu=name,temperature.gpu,clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.sw_power_cap,clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.hw_power_brake_slowdown,clocks_throttle_reasons.sync_boost,clocks_throttle_reasons.applications_clocks_setting --format=csv,noheader,nounits
  if ($LASTEXITCODE -eq 0 -and $line) {
    $p = $line -split ',\s*'
    $name = $p[0].Trim(); $temp = $p[1].Trim()
    $thermal = $p[2].Trim(); $power = $p[3].Trim(); $swThermal = $p[4].Trim()
    $brake = $p[5].Trim(); $sync = $p[6].Trim(); $appClk = $p[7].Trim()
    Write-Output ("GPU: {0}" -f $name)
    Write-Output ("Temperature: {0} C" -f $temp)
    $active = @()
    if ($thermal -eq 'Active') { $active += 'Thermal (HW)' }
    if ($swThermal -eq 'Active') { $active += 'Thermal (SW)' }
    if ($power -eq 'Active') { $active += 'Power limit' }
    if ($brake -eq 'Active') { $active += 'Power brake' }
    if ($sync -eq 'Active') { $active += 'Sync boost' }
    if ($appClk -eq 'Active') { $active += 'App clock cap' }
    if ($active.Count -eq 0) {
      Write-Output "Thermal: OK | Power: OK | Voltage: n/a | Throttling: NONE"
      Write-Output "Status: HEALTHY"
    } else {
      Write-Output ("Throttling: {0}" -f ($active -join ' + '))
      Write-Output "Status: PERFORMANCE LIMITED - check cooling/airflow and power delivery."
    }
    Write-Output "Vendor: NVIDIA (nvidia-smi). Diagnostic only; no values were changed."
    exit 0
  }
}
Write-Output "Vendor telemetry not available for this GPU (no nvidia-smi)."
Write-Output "Use the GPU vendor's monitoring tool to observe thermal/power throttling under load."
'''

_DIAG_MEMORY = r'''$ProgressPreference='SilentlyContinue'

$ProgressPreference='SilentlyContinue'
$os = Get-CimInstance Win32_OperatingSystem
$totalKB = [double]$os.TotalVisibleMemorySize
$freeKB  = [double]$os.FreePhysicalMemory
$totalGB = [math]::Round($totalKB / 1MB, 1)
$freeGB  = [math]::Round($freeKB / 1MB, 1)
$usedGB  = [math]::Round(($totalKB - $freeKB) / 1MB, 1)
Write-Output ("RAM: {0:F1} / {1:F1} GB used ({2:F1} GB free)" -f $usedGB, $totalGB, $freeGB)
$commit = (Get-Counter '\Memory\Committed Bytes' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue
$commitLimit = $os.TotalVirtualMemorySize * 1024
if ($commit -and $commitLimit) {
  $commitPct = [math]::Round(100.0 * $commit / $commitLimit, 0)
  Write-Output ("Commit: {0:P0} of commit limit" -f ($commitPct / 100.0))
} else { $commitPct = 0 }
$hf = (Get-Counter '\Memory\Pages input/sec' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue
if ($null -ne $hf) { Write-Output ("Hard faults (pages input): {0:N0} /s" -f $hf) }
$pf = Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue
if ($pf) {
  $pfSum = ($pf | Measure-Object -Property CurrentUsage -Sum).Sum
  $pfMax = ($pf | Measure-Object -Property AllocatedBaseSize -Sum).Sum
  Write-Output ("Pagefile: {0:N0} / {1:N0} MB" -f $pfSum, $pfMax)
}
$stby = (Get-Counter '\Memory\Standby Cache Normal Priority Bytes' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue
if ($null -ne $stby) { Write-Output ("Standby cache: {0:F1} GB" -f ($stby / 1GB)) }
$pressure = $false
if ($commitPct -ge 90) { $pressure = $true }
if ($freeGB -lt 1.0)   { $pressure = $true }
if ($hf -and $hf -gt 500) { $pressure = $true }
if ($pressure) {
  Write-Output "Status: MEMORY PRESSURE DETECTED - close background apps or add RAM before heavy gaming."
} else {
  Write-Output "Status: OK - no immediate memory pressure."
}
Write-Output "Recommendation: this is diagnostic only; nothing was cleared or changed."
'''

_NET_JITTER = r'''$ProgressPreference='SilentlyContinue'

$ErrorActionPreference = 'SilentlyContinue'
$target = '1.1.1.1'
$count = 20
$times = [System.Collections.Generic.List[double]]::new()
$lost = 0
for ($i = 0; $i -lt $count; $i++) {
  $p = New-Object System.Net.NetworkInformation.Ping
  $r = $p.Send($target, 1000)
  if ($r.Status -eq 'Success') { $times.Add([double]$r.RoundtripTime) } else { $lost++ }
}
$sent = $count
$lossPct = [math]::Round(100.0 * $lost / $sent, 1)
if ($times.Count -gt 0) {
  $min = [math]::Round(($times | Measure-Object -Minimum).Minimum, 1)
  $max = [math]::Round(($times | Measure-Object -Maximum).Maximum, 1)
  $avg = [math]::Round(($times | Measure-Object -Average).Average, 1)
  $sumSq = 0.0
  foreach ($t in $times) { $sumSq += ($t - $avg) * ($t - $avg) }
  $jitter = [math]::Round([math]::Sqrt($sumSq / $times.Count), 2)
  Write-Output ("Host: {0}" -f $target)
  Write-Output ("Pings: {0} (lost {1}, {2}% loss)" -f $sent, $lost, $lossPct)
  Write-Output ("Min: {0} ms | Avg: {1} ms | Max: {2} ms" -f $min, $avg, $max)
  Write-Output ("Jitter (std dev): {0} ms" -f $jitter)
  if ($lossPct -eq 0 -and $jitter -lt 3)     { $grade = 'EXCELLENT' }
  elseif ($lossPct -lt 1 -and $jitter -lt 8) { $grade = 'GOOD - competitive ready' }
  elseif ($lossPct -lt 3)                    { $grade = 'FAIR - noticeable inconsistency' }
  else                                       { $grade = 'POOR - investigate ISP/hardware' }
  Write-Output ("Status: {0}" -f $grade)
} else {
  Write-Output "No replies received - check connectivity / firewall / ISP."
}
Write-Output "Diagnostic only. This test does not change any ping or network setting."
'''

_NET_BUFFERBLOAT = r'''$ProgressPreference='SilentlyContinue'

$ErrorActionPreference = 'SilentlyContinue'
$target = '1.1.1.1'
function Get-AvgPing([int]$n, [string]$t) {
  $tms = New-Object System.Collections.Generic.List[double]
  for ($i = 0; $i -lt $n; $i++) {
    $p = New-Object System.Net.NetworkInformation.Ping
    $r = $p.Send($t, 1000)
    if ($r.Status -eq 'Success') { $tms.Add([double]$r.RoundtripTime) }
  }
  if ($tms.Count -eq 0) { return $null }
  return [math]::Round(($tms | Measure-Object -Average).Average, 1)
}
$idle = Get-AvgPing 6 $target
if ($null -eq $idle) { Write-Output "No replies - cannot measure bufferbloat. Check connectivity."; exit 0 }
Write-Output ("Idle latency: {0} ms" -f $idle)
$dlJob = Start-Job -ScriptBlock { param($u); & curl.exe -s -o NUL -m 18 --limit-rate 3M $u } -ArgumentList "https://speed.cloudflare.com/__down?bytes=30000000"
Start-Sleep -Milliseconds 1200
$dlLatency = Get-AvgPing 6 $target
Wait-Job $dlJob -Timeout 20 | Out-Null
Stop-Job $dlJob -ErrorAction SilentlyContinue | Out-Null
Remove-Job $dlJob -Force -ErrorAction SilentlyContinue | Out-Null
if ($null -eq $dlLatency) { $dlLatency = $idle }
Write-Output ("Under download load: {0} ms" -f $dlLatency)
$upJob = Start-Job -ScriptBlock { param($u); $tmp = Join-Path $env:TEMP "bufbloat_test.bin"; [System.IO.File]::WriteAllBytes($tmp, (New-Object byte[] 6291456)); & curl.exe -s -o NUL -m 18 --limit-rate 2M -X POST --data-binary "@$tmp" $u; Remove-Item $tmp -ErrorAction SilentlyContinue } -ArgumentList "https://speed.cloudflare.com/__up"
Start-Sleep -Milliseconds 1200
$upLatency = Get-AvgPing 6 $target
Wait-Job $upJob -Timeout 20 | Out-Null
Stop-Job $upJob -ErrorAction SilentlyContinue | Out-Null
Remove-Job $upJob -Force -ErrorAction SilentlyContinue | Out-Null
if ($null -eq $upLatency) { $upLatency = $idle }
Write-Output ("Under upload load: {0} ms" -f $upLatency)
$worst = [math]::Max($dlLatency, $upLatency)
$delta = $worst - $idle
if ($delta -lt 5)      { $grade = 'LOW - no significant bufferbloat' }
elseif ($delta -lt 20) { $grade = 'MODERATE - slight latency increase under load' }
elseif ($delta -lt 50) { $grade = 'HIGH - latency spikes under load' }
else                   { $grade = 'SEVERE - heavy bufferbloat' }
Write-Output ("Worst-case latency rise: {0} ms" -f [math]::Round($delta,1))
Write-Output ("Bufferbloat: {0}" -f $grade)
Write-Output "Guidance: enable SQM/QoS on the router if supported. This is diagnostic only; no Windows setting was changed."
'''

_DIAG_DISPLAY = r'''$ProgressPreference='SilentlyContinue'

$ErrorActionPreference = 'SilentlyContinue'
$vc = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Microsoft' } | Select-Object -First 1
if (-not $vc) { Write-Output "No active GPU/display detected."; exit 0 }
$res = if ($vc.CurrentHorizontalResolution) { "{0}x{1}" -f $vc.CurrentHorizontalResolution, $vc.CurrentVerticalResolution } else { "unknown" }
$cur = $vc.CurrentRefreshRate
Write-Output ("GPU output: {0}" -f $vc.Name)
Write-Output ("Resolution: {0}" -f $res)
Write-Output ("Current refresh rate: {0} Hz" -f $cur)
$maxHz = $null
try {
  $modes = Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorListedSupportedSourceModes -ErrorAction Stop
  $hzList = New-Object System.Collections.Generic.List[double]
  foreach ($m in $modes) {
    foreach ($sm in @($m.MonitorSourceModes)) {
      if (-not $sm) { continue }
      $num = [double]$sm.VerticalRefreshRateNumerator
      $den = [double]$sm.VerticalRefreshRateDenominator
      if ($num -gt 0 -and $den -gt 0) {
        $hzList.Add([math]::Round(($num / $den), 1))
      }
    }
  }
  if ($hzList.Count -gt 0) { $maxHz = ($hzList | Measure-Object -Maximum).Maximum }
} catch { $maxHz = $null }
if ($maxHz -and $cur -and $maxHz -lt $cur) { $maxHz = $cur }
if ($maxHz) {
  Write-Output ("Highest reported refresh: {0} Hz" -f $maxHz)
  if ($cur -and $cur -lt $maxHz) {
    Write-Output "Status: NOT RUNNING AT MAXIMUM REFRESH - switch to a higher rate in Windows display settings."
  } else {
    Write-Output "Status: OK - display is at its maximum supported refresh."
  }
} else {
  Write-Output "Highest reported refresh: not exposed by WMI."
  Write-Output "Status: unable to verify maximum - check display settings manually."
}
Write-Output "HDR/VRR: check in Windows Settings > Display > Advanced (not exposed reliably via WMI)."
Write-Output "Diagnostic only. To change refresh: Settings > System > Display > Advanced display."
'''

_DIAG_CAPTURE = r'''$ProgressPreference='SilentlyContinue'

$ErrorActionPreference = 'SilentlyContinue'
Write-Output "Background Capture"
$targets = @(
  @{ Label = "OBS Studio";        Names = @("obs64", "obs", "obs-browser-page", "streamlabs") },
  @{ Label = "NVIDIA Recording";  Names = @("nvcontainer", "nvsphelper", "nvsphelper64", "nvbackend", "nvudisp") },
  @{ Label = "AMD Recording";     Names = @("amddvr", "amddvrserver", "amdows", "RadeonSoftware", "AtDVR") },
  @{ Label = "Xbox Game Bar/DVR"; Names = @("GameBar", "GameBarPresenceWriter", "bcastdvr", "XboxAppServices") },
  @{ Label = "Discord Capture";   Names = @("discord", "discordptb", "discordcanary", "discord_tokens") }
)
foreach ($t in $targets) {
  $hit = @($t.Names | Where-Object { Get-Process -Name $_ -ErrorAction SilentlyContinue })
  if ($hit.Count -gt 0) {
    $names = @()
    foreach ($h in $hit) {
      $p = Get-Process -Name $h -ErrorAction SilentlyContinue | Select-Object -First 1
      $names += ("{0}({1})" -f $h, $p.Id)
    }
    Write-Output ("{0}: RUNNING - {1}" -f $t.Label, ($names -join ', '))
  } else {
    Write-Output ("{0}: OFF" -f $t.Label)
  }
}
Write-Output "Note: nothing was stopped. Close any listed recorder before competitive play if you do not need clips."
'''

TWEAKS = validate_module("system", [

    T("sys-002", "Do Not Clear Pagefile at Shutdown",
      "Skips clearing the pagefile during shutdown.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management", "ClearPageFileAtShutdown", 0, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management", "ClearPageFileAtShutdown", 1, "DWORD")],
      why="Clearing the pagefile on shutdown can take a long time and wears SSDs.",
      changes="Disables pagefile clearing at shutdown.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["pagefile", "shutdown", "ssd"]),

    T("sys-004", "Disable Windows Error Reporting",
      "Turns off WER popups and background report submission.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled", 1, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "DontShowUI", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled"),
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "DontShowUI"),
      ],
      why="WER dialogs and report queueing add background CPU and disk work.",
      changes="Disables Windows Error Reporting.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["wer", "crash", "reporting"]),

    T("sys-006", "Disable Auto Reboot on Crash",
      "Prevents automatic restart after a system failure.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\CrashControl", "AutoReboot", 0, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\CrashControl", "AutoReboot", 1, "DWORD")],
      why="An unplanned restart loses all state; better to fail visibly than reboot mid-session.",
      changes="Disables automatic restart on system failure.",
      risk="low", impact="low", recommended="recommended", admin=True,
      tags=["crash", "reboot", "stability"]),
    T("sys-007", "Enable Long Paths",
      "Enables Win32 long path support (>260 chars).",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem", "LongPathsEnabled", 1, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem", "LongPathsEnabled", 0, "DWORD")],
      why="Mod tools and deep game directories frequently exceed the classic path limit.",
      changes="Enables long paths in Win32.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["paths", "ntfs", "filesystem"]),
    T("sys-008", "Create System Restore Point",
      "Creates a manual restore point before making changes.",
      actions=[("cmd", "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Checkpoint-Computer -Description 'Maximum Tweaks backup' -RestorePointType MODIFY_SETTINGS\"")],
      revert=[("guidance", "No automatic undo — System Restore is rolled back from System Protection if needed.")],
      why="A restore point is the safety net that makes every other tweak reversible.",
      changes="Creates a System Restore point.",
      risk="safe", impact="very low", recommended="recommended", admin=True,
      tags=["restore", "backup", "safety"]),
    T("sys-009", "Boot Manager Timeout 0",
      "Removes the boot manager selection delay.",
      actions=[("cmd", "bcdedit /timeout 0")],
      revert=[("cmd", "bcdedit /timeout 30")],
      why="Shaves seconds off every cold boot when no dual-boot selection is needed.",
      changes="Sets boot manager timeout to 0.",
      risk="low", impact="low", recommended="recommended", admin=True,
      tags=["boot", "startup", "timeout"]),
    T("sys-010", "Disable Automatic Driver Downloads",
      "Stops Windows Update from automatically installing drivers.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", "SearchOrderConfig", 0, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", "SearchOrderConfig", 1, "DWORD")],
      why="An auto-updated GPU driver mid-week can silently change performance behaviour.",
      changes="Disables driver search via Windows Update.",
      risk="moderate", impact="moderate", recommended="optional", admin=True, confirm=True,
      tags=["driver", "update", "gpu"]),
    T("sys-011", "Pagefile Sizing Guidance",
      "Explains and applies a sane pagefile policy.",
      actions=[("guidance", "Keep the pagefile on the fastest drive and let Windows manage its size for stability. A manually fixed size equal to your RAM amount on the OS drive is a good gaming default.")],
      revert=[("guidance", "Re-enable automatic pagefile management in System Properties if desired.")],
      why="A badly sized or misplaced pagefile causes random game hitches when memory pressure rises.",
      changes="Shows pagefile guidance (no destructive change).",
      risk="safe", impact="low", recommended="recommended",
      tags=["pagefile", "memory", "vram"]),
    T("sys-012", "Fast App Shutdown Timeouts",
      "Reduces how long Windows waits for hung applications at shutdown.",
      actions=[
          ("reg", "HKCU", r"Control Panel\Desktop", "WaitToKillAppTimeout", 2000, "STRING"),
          ("reg", "HKCU", r"Control Panel\Desktop", "HungAppTimeout", 1000, "STRING"),
      ],
      revert=[
          ("reg", "HKCU", r"Control Panel\Desktop", "WaitToKillAppTimeout", 5000, "STRING"),
          ("reg", "HKCU", r"Control Panel\Desktop", "HungAppTimeout", 5000, "STRING"),
      ],
      why="Speeds up shutdown and restart cycles; unsaved work may be lost if an app hangs.",
      changes="Lowers shutdown/hung app timeouts.",
      risk="moderate", impact="low", recommended="optional", confirm=True,
      tags=["shutdown", "timeout", "hang"]),
    T("sys-013", "Auto-End Tasks at Logoff",
      "Forces hung applications to close when you log off.",
      actions=[("reg", "HKCU", r"Control Panel\Desktop", "AutoEndTasks", 1, "STRING")],
      revert=[("reg", "HKCU", r"Control Panel\Desktop", "AutoEndTasks", 0, "STRING")],
      why="Prevents a stuck app from blocking logout.",
      changes="Enables AutoEndTasks.",
      risk="low", impact="low", recommended="recommended",
      tags=["logoff", "tasks", "shutdown"]),
    T("sys-014", "Disable Drive AutoRun",
      "Disables AutoRun for all drive types.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDriveTypeAutoRun", 255, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDriveTypeAutoRun", 0, "DWORD")],
      why="Prevents unexpected background processes from launching when media is inserted.",
      changes="Disables AutoRun for all drives.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["autorun", "security", "usb"]),
    T("sys-015", "Disable Aero Shake",
      "Turns off the Aero Shake minimize gesture.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "DisallowShaking", 1, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "DisallowShaking", 0, "DWORD")],
      why="Accidental shakes while dragging can minimize a game window.",
      changes="Disables window shake minimize.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["shake", "window", "minimize"]),
    T("sys-016", "Disable Minimize Animation",
      "Turns off window minimize/restore animations.",
      actions=[("reg", "HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", 0, "STRING")],
      revert=[("reg", "HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", 1, "STRING")],
      why="Skips animation work when alt-tabbing between the game and other windows.",
      changes="Disables minimize animation.",
      risk="safe", impact="low", recommended="recommended",
      tags=["animation", "window", "alt-tab"]),
    T("sys-017", "Disable Notification Center",
      "Turns off the notification center via policy.",
      actions=[("reg", "HKCU", r"Software\Policies\Microsoft\Windows\Explorer", "DisableNotificationCenter", 1, "DWORD")],
      revert=[("regdel", "HKCU", r"Software\Policies\Microsoft\Windows\Explorer", "DisableNotificationCenter")],
      why="Removes toast scheduling work and accidental notifications during play.",
      changes="Disables the notification center.",
      risk="safe", impact="low", recommended="recommended",
      tags=["notifications", "toast", "center"]),

    T("sys-019", "Disable 'Start Full-Screen Optimizations' Help",
      "Turns off the fullscreen optimization compatibility help overlay.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "EnableOverlays", 0, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "EnableOverlays", 1, "DWORD")],
      why="Removes overlay layers that can add latency in borderless games.",
      changes="Disables overlay content for fullscreen apps.",
      risk="safe", impact="low", recommended="recommended",
      tags=["overlay", "fullscreen", "latency"]),

    T("sys-021", "Reduce Hung App Timeout",
      "Lowers the threshold before Windows considers an app hung.",
      actions=[("reg", "HKCU", r"Control Panel\Desktop", "HungAppTimeout", "1000", "STRING")],
      revert=[("reg", "HKCU", r"Control Panel\Desktop", "HungAppTimeout", "5000", "STRING")],
      why="Windows detects and prompts to close hung apps sooner, reducing stalls.",
      changes="Sets HungAppTimeout to 1000 ms.",
      risk="low", impact="low", recommended="optional",
      tags=["hung", "timeout", "responsiveness"]),
    T("sys-023", "Optimize Active Hours",
      "Sets Windows Update active hours to reduce background disruption.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursStart", 8, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursEnd", 20, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursStart", 7, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursEnd", 17, "DWORD"),
      ],
      why="Prevents Windows Update from restarting or installing during typical gaming hours.",
      changes="Sets active hours to 08:00 - 20:00.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["update", "activehours", "restart"]),

    T("perf-new-001", "Disable Game Process Efficiency Mode",
      "Clears EcoQoS/Efficiency Mode from the focused game process.",
      actions=[_PS(_PERF_ECOQOS, 30)],
      revert=[("guidance", "Restart the game; Windows restores default process QoS/EcoQoS behavior on launch.")],
      why="Windows can mark game threads as EcoQoS, capping CPU performance during active gameplay.",
      changes="Removes EcoQoS from the foreground game process only (Windows-wide EcoQoS untouched).",
      risk="low", impact="low", recommended="optional", admin=True, confirm=True,
      warn="Targets the foreground (focused) game window. Focus the game, then Apply.",
      added="2026-08-31",
      tags=["ecoqos", "efficiency", "game", "process"]),
    T("diag-new-001", "GPU PCIe Link Width / Speed Diagnostic",
      "Shows the GPU PCIe generation and current vs max link width.",
      actions=[_PS(_DIAG_PCIE, 30)],
      revert=[("guidance", "No change to revert.")],
      why="A GPU running at x8/x4 instead of its intended x16 can silently bottleneck games.",
      changes="Reports GPU model, PCIe generation and link width.",
      risk="safe", impact="very low", recommended="recommended",
      added="2026-08-31",
      tags=["pcie", "gpu", "link", "diagnostic"]),
    T("diag-new-002", "GPU Throttling Reason Scanner",
      "Checks thermal, power and voltage throttle reasons.",
      actions=[_PS(_DIAG_THROTTLE, 30)],
      revert=[("guidance", "No change to revert.")],
      why="Thermal or power throttling explains GPU clock drops under sustained load.",
      changes="Reports active GPU throttle reasons.",
      risk="safe", impact="very low", recommended="recommended",
      added="2026-08-31",
      tags=["gpu", "thermal", "throttle", "diagnostic"]),
    T("diag-new-003", "Hard Fault / Memory Pressure Detector",
      "Reports RAM, commit, hard faults, pagefile and standby state.",
      actions=[_PS(_DIAG_MEMORY, 30)],
      revert=[("guidance", "No change to revert.")],
      why="Memory pressure causes stutters and hitches that look like network or GPU issues.",
      changes="Reports memory pressure (diagnostic only).",
      risk="safe", impact="very low", recommended="recommended",
      added="2026-08-31",
      tags=["ram", "memory", "hardfault", "diagnostic"]),
    T("net-new-001", "Network Jitter + Packet Loss Test",
      "Runs a repeated ICMP test and reports latency, jitter and loss.",
      actions=[_PS(_NET_JITTER, 60)],
      revert=[("guidance", "No change to revert.")],
      why="Stable latency matters more than raw ping for competitive play.",
      changes="Reports ping consistency (diagnostic only, no setting changes).",
      risk="safe", impact="very low", recommended="recommended",
      added="2026-08-31",
      tags=["network", "jitter", "packetloss", "diagnostic"]),
    T("net-new-002", "Bufferbloat Test",
      "Measures latency rise under download and upload load.",
      actions=[_PS(_NET_BUFFERBLOAT, 120)],
      revert=[("guidance", "No change to revert. Enable SQM/QoS on the router if the test shows bufferbloat.")],
      why="A router that buffers too much turns idle-fast connections into lag under load.",
      changes="Measures latency under load (diagnostic only, no setting changes).",
      risk="safe", impact="very low", recommended="recommended",
      added="2026-08-31",
      tags=["network", "bufferbloat", "qos", "diagnostic"]),
    T("diag-new-004", "Refresh Rate / Display Mode Verification",
      "Checks the display's current vs maximum supported refresh rate.",
      actions=[_PS(_DIAG_DISPLAY, 30)],
      revert=[("guidance", "No change to revert.")],
      why="A display left at 60 Hz while the monitor supports 144/240 Hz forfeits smoothness.",
      changes="Reports resolution and refresh rate (diagnostic only).",
      risk="safe", impact="very low", recommended="recommended",
      added="2026-08-31",
      tags=["display", "refresh", "monitor", "diagnostic"]),
    T("diag-new-005", "Background Game Recording Process Scanner",
      "Detects active capture/recording software during play.",
      actions=[_PS(_DIAG_CAPTURE, 30)],
      revert=[("guidance", "No change to revert. Close any listed recorder manually if you do not need clips.")],
      why="Hidden recorders (OBS, NV/AMD/Xbox capture, Discord) steal GPU and CPU during games.",
      changes="Scans for known capture processes (diagnostic only, nothing is stopped).",
      risk="safe", impact="very low", recommended="recommended",
      added="2026-08-31",
      tags=["capture", "obs", "recording", "diagnostic"]),

])

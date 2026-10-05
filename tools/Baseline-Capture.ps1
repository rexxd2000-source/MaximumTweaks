param(
    [string]$OutDir = "",
    [switch]$RegistryOnly
)

$ErrorActionPreference = "Stop"

$DrvMap = @{
    "HKLM" = "HKLM:"
    "HKCU" = "HKCU:"
    "HKU"  = "Registry::HKEY_USERS"
    "HKCR" = "Registry::HKEY_CLASSES_ROOT"
}

$RegTargets = @(
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\PriorityControl"; name = "Win32PrioritySeparation" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\PriorityControl"; name = "IRQ8Priority" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\PriorityControl"; name = "SchedulingProfilingType" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Print"; name = "PrintJobLogging" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "TdrDelay" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "TdrLimitCount" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "TdrLimitTime" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "GpuTimeoutValue" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "HwSchMode" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "OverlayTestMode" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "EnableMsHybrid" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\GraphicsDrivers"; name = "HardwareAccelerationMode" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\kernel"; name = "GlobalTimerResolutionRequests" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\kernel"; name = "GlobalTimerResolution" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\kernel"; name = "TimerResolution" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Power"; name = "HiberbootEnabled" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "LargeSystemCache" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "DisablePagingExecutive" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "DisablePageCombining" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "IoPageLockLimit" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "SystemPages" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "PagedPoolSize" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "NonPagedPoolSize" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "SharedSection" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "MoveImages" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "ClearPageFileAtShutdown" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters"; name = "EnablePrefetcher" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters"; name = "EnableSuperfetch" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters"; name = "EnableBootAndPrefetch" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "FeatureSettingsOverride" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"; name = "FeatureSettingsOverrideMask" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control"; name = "WaitToKillServiceTimeout" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\CrashControl"; name = "AutoReboot" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power"; name = "CsEnabled" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power"; name = "CsEnableConnectedStandby" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power"; name = "PlatformAoAcOverride" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power"; name = "AoAcOverride" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power"; name = "LazyMode" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power"; name = "EnhancedSleepEnabled" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power"; name = "IntelSpeedShiftEnabled" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power\PowerSettings\238C9FA8-0AAD-41ED-83F4-97BE242C8F20\94AC6D29-73CE-41A6-809F-6363BA21B47E"; name = "Attributes" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power\PowerThrottling"; name = "PowerThrottlingOff" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Power\SleepStudy"; name = "Enabled" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"; name = "PerfLevelSrc" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"; name = "PowerMizerLevel" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"; name = "PowerMizerLevelAC" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"; name = "PowerMizerEnable" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver"; name = "KMD_EnableVSync" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver"; name = "DsrFlags" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver"; name = "MaxPreRenderedFrames" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver"; name = "PowerMizerLevelAC" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e96b-e325-11ce-bfc1-08002be10318}\0000"; name = "DeviceSelectiveSuspended" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e96b-e325-11ce-bfc1-08002be10318}\0000"; name = "EnhancedPowerManagementEnabled" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{36fc9e60-c465-11cf-8056-444553540000}\*"; name = "PnPCapabilities" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"; name = "SystemResponsiveness" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"; name = "NetworkThrottlingIndex" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"; name = "AllTasksPriority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games"; name = "GPU Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games"; name = "Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games"; name = "Scheduling Category" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game"; name = "Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game"; name = "GPU Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game"; name = "Clock Rate" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game"; name = "SFIO Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\{e96051d2-4e84-4e3e-8403-e8ba6078e564}"; name = "GPU Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\{e96051d2-4e84-4e3e-8403-e8ba6078e564}"; name = "Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\{e96051d2-4e84-4e3e-8403-e8ba6078e564}"; name = "Scheduling Category" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio"; name = "Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio"; name = "GPU Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio"; name = "Scheduling Category" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio"; name = "Latency" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback"; name = "Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback"; name = "Scheduling Category" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback"; name = "Latency" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Keyboard"; name = "Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Keyboard"; name = "Scheduling Category" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Keyboard"; name = "Latency" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Keyboard"; name = "GPU Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Keyboard"; name = "SFIO Priority" }
    @{ hive = "HKLM"; path = "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Keyboard"; name = "Background Only" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"; name = "InitialRTO" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"; name = "Tcp1323Opts" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"; name = "TcpAckFrequency" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"; name = "TCPNoDelay" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"; name = "DefaultTTL" }
    @{ hive = "HKLM"; path = "SOFTWARE\Policies\Microsoft\Windows\Psched"; name = "NonBestEffortLimit" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\mouclass\Parameters"; name = "MouseDataQueueSize" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\kbdclass\Parameters"; name = "KeyboardDataQueueSize" }
    @{ hive = "HKCU"; path = "Control Panel\Mouse"; name = "MouseSensitivity" }
    @{ hive = "HKCU"; path = "Control Panel\Mouse"; name = "MouseSpeed" }
    @{ hive = "HKCU"; path = "Control Panel\Mouse"; name = "MouseThreshold1" }
    @{ hive = "HKCU"; path = "Control Panel\Mouse"; name = "MouseThreshold2" }
    @{ hive = "HKCU"; path = "Control Panel\Mouse"; name = "MouseTrails" }
    @{ hive = "HKCU"; path = "Control Panel\Desktop"; name = "LowLevelHooksTimeout" }
    @{ hive = "HKCU"; path = "Control Panel\Desktop"; name = "MenuShowDelay" }
    @{ hive = "HKCU"; path = "Control Panel\Desktop"; name = "ForegroundLockTimeout" }
    @{ hive = "HKCU"; path = "Control Panel\Desktop"; name = "AutoEndTasks" }
    @{ hive = "HKCU"; path = "Control Panel\Desktop"; name = "WaitToKillAppTimeout" }
    @{ hive = "HKCU"; path = "Control Panel\Desktop"; name = "HungAppTimeout" }
    @{ hive = "HKCU"; path = "Control Panel\Desktop"; name = "ActiveWindowTracking" }
    @{ hive = "HKCU"; path = "System\GameConfigStore"; name = "GameDVR_Enabled" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Windows\CurrentVersion\GameDVR"; name = "AppCaptureEnabled" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Windows\CurrentVersion\GameDVR"; name = "BackgroundRecordingEnabled" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Windows\CurrentVersion\GameDVR"; name = "VKMToggleGameBar" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Windows\CurrentVersion\GameBar"; name = "UseNexusForGameBarEnabled" }
    @{ hive = "HKCU"; path = "Software\Microsoft\GameBar"; name = "AutoGameModeEnabled" }
    @{ hive = "HKCU"; path = "Software\Microsoft\GameBar"; name = "AllowAutoGameMode" }
    @{ hive = "HKLM"; path = "SOFTWARE\Policies\Microsoft\Windows\GameDVR"; name = "AllowGameDVR" }
    @{ hive = "HKLM"; path = "SOFTWARE\Policies\Microsoft\Windows\GameBar"; name = "AllowGameBar" }
    @{ hive = "HKCU"; path = "Software\Microsoft\GameBar"; name = "ShowStartupPanel" }
    @{ hive = "HKCU"; path = "SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR"; name = "AppCaptureEnabled" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\USB"; name = "DisableSelectiveSuspend" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\USB"; name = "DefaultRwTimeout" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\USB"; name = "ErrorRecoveryTimeout" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\USB"; name = "USBSelectiveSuspendDelay" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Multimedia\Audio\DevicePreferences"; name = "ExclusiveMode" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Multimedia\Audio\DevicePreferences"; name = "AllowExclusiveMode" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Multimedia\Audio\DevicePreferences"; name = "LaunchAppsInExclusiveMode" }
    @{ hive = "HKCU"; path = "Software\Microsoft\Multimedia\Audio\DevicePreferences"; name = "MicExclusiveMode" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Device\*"; name = "AllowSleep" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}"; name = "InterruptModeration" }
    @{ hive = "HKCU"; path = "SOFTWARE\Microsoft\DirectX\UserGpuPreferences"; name = "DirectXUserGlobalSettings" }
    @{ hive = "HKLM"; path = "SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"; name = "NoAutoUpdate" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\Terminal Server"; name = "fDenyTSConnections" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\FileSystem"; name = "NtfsDisable8dot3NameCreation" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\FileSystem"; name = "NtfsMftZoneReservation" }
    @{ hive = "HKLM"; path = "SYSTEM\CurrentControlSet\Control\FileSystem"; name = "LongPathsEnabled" }
    @{ hive = "SYSTEM"; path = "CurrentControlSet\Services\stornvme"; name = "DIPM" }
    @{ hive = "SYSTEM"; path = "CurrentControlSet\Services\stornvme"; name = "HIPM" }
)

$Services = @(
    "nvtelemetrycontainer", "nvtmmon", "nvtmrep", "nvvapi", "nvdisplay.container",
    "vaultsvc", "fontcache", "audiosrv", "audioendpointbuilder", "diagtrack",
    "tabletinputservice", "bthserv", "sysmain", "wsearch", "mapsbroker",
    "wmpnetworksvc", "retaildemo", "dmwappushservice",
    "diagnosticshub.standardcollector.service", "fax", "wersvc", "memcompression",
    "dsmsvc", "wpnservice", "spooler", "remoteregistry", "xblauthmanager",
    "xblgamesave", "phonesvc", "irmon", "wisvc", "compattelrunner", "waasmedicsvc"
)

if (-not $OutDir) {
    $OutDir = Join-Path $PSScriptRoot ("snapshots\capture-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$RegDump = Join-Path $OutDir "reg_values.txt"
$ServicesFile = Join-Path $OutDir "services.txt"
$PowerFile = Join-Path $OutDir "powercfg-active.txt"
$BcdFile = Join-Path $OutDir "bcdedit.txt"
$TasksFile = Join-Path $OutDir "schtasks.csv"
$Manifest = Join-Path $OutDir "manifest.json"

"" | Set-Content -Path $RegDump -Encoding Unicode
$restoreLines = New-Object System.Collections.Generic.List[string]
$restoreLines.Add("# Generated by Baseline-Capture.ps1 - re-imports captured state.")
$regExports = New-Object System.Collections.Generic.List[string]

function Expand-RegPath([string]$hive, [string]$path) {
    $root = $DrvMap[$hive]
    if (-not $root) { return @() }
    $leaf = $path
    $parentDir = $root
    $parts = $leaf.Split("\")
    $items = @(Get-Item -Path $parentDir -ErrorAction SilentlyContinue)
    for ($i = 0; $i -lt $parts.Count; $i++) {
        $seg = $parts[$i]
        if ($i -eq $parts.Count - 1) { continue }
        if ($seg -eq "*") {
            $items = @()
            Get-ChildItem -Path $parentDir -ErrorAction SilentlyContinue | ForEach-Object { $items += $_ }
        } else {
            $parentDir = Join-Path $parentDir $seg
            $items = @(Get-Item -Path $parentDir -ErrorAction SilentlyContinue)
        }
    }
    $final = $parts[-1]
    $out = @()
    foreach ($it in $items) {
        if ($final -eq "*") {
            Get-ChildItem -Path $it.PSPath -ErrorAction SilentlyContinue | ForEach-Object {
                $regName = ($hive + "\" + $_.Name.Replace($root, "").TrimStart("\"))
                $full = $it.PSPath + "\" + $_.Name
                $out += ,@($full, $regName)
            }
        } else {
            $full = $it.PSPath + "\" + $final
            $regName = $hive + "\" + $path
            $out += ,@($full, $regName)
        }
    }
    return ,$out
}

function Export-Key([string]$regKeyPath, [string]$tag) {
    try {
        $safe = $tag -replace '[\\/:*?"<>|]', "_"
        $file = Join-Path $OutDir ("reg-" + $safe + ".reg")
        & reg.exe export $regKeyPath $file /y 2>$null | Out-Null
        if (Test-Path $file) {
            $script:regExports.Add($file)
            $script:restoreLines.Add('reg import "' + $file + '"')
            return $true
        }
    } catch { }
    return $false
}

foreach ($t in $RegTargets) {
    $hive = $t.hive; $path = $t.path; $name = $t.name
    try {
        $expanded = @(Expand-RegPath $hive $path)
        foreach ($ex in $expanded) {
            $full = $ex[0]; $regName = $ex[1]
            $key = Get-Item -Path $full -ErrorAction SilentlyContinue
            if (-not $key) { continue }
            $prop = $key.GetValue($name, $null)
            $type = $key.GetValueKind($name)
            if ($prop -is [byte[]]) { $prop = "0x" + (($prop | ForEach-Object { $_.ToString("X2") }) -join "") }
            "$regName :: $name = $type:$prop" | Add-Content -Path $RegDump -Encoding Unicode
            Export-Key $regName ($regName.Replace("\", "_"))
        }
    } catch { }
}

if (-not $RegistryOnly) {
    $line = "active scheme:"; $line | Add-Content -Path $PowerFile -Encoding Unicode
    & powercfg.exe /getactivescheme 2>$null | Add-Content -Path $PowerFile -Encoding Unicode
    "" | Add-Content -Path $PowerFile -Encoding Unicode
    "full active scheme dump:" | Add-Content -Path $PowerFile -Encoding Unicode
    & powercfg.exe /query SCHEME_CURRENT 2>$null | Add-Content -Path $PowerFile -Encoding Unicode

    "active scheme GUID:" | Add-Content -Path $BcdFile -Encoding Unicode
    $active = (& powercfg.exe /getactivescheme 2>$null) -join " "
    if ($active -match "\(([0-9a-fA-F-]{36})\)") {
        $schemeGuid = $Matches[1]
        $schemeFile = Join-Path $OutDir "active-power-scheme.pow"
        & powercfg.exe /export $schemeFile $schemeGuid 2>$null | Out-Null
        if (Test-Path $schemeFile) {
            $script:restoreLines.Add('powercfg /import "' + $schemeFile + '"')
            $script:restoreLines.Add('powercfg /setactive ' + $schemeGuid)
        }
    } else { $schemeGuid = "" }

    foreach ($s in $Services) {
        $out = (& sc.exe qc $s 2>&1)
        $state = (& sc.exe query $s 2>&1)
        "===== $s =====" | Add-Content -Path $ServicesFile -Encoding Unicode
        $out | Add-Content -Path $ServicesFile -Encoding Unicode
        $state | Add-Content -Path $ServicesFile -Encoding Unicode
        $startLine = $out | Where-Object { $_ -match "START_TYPE" }
        if ($startLine -match "START_TYPE\s+:\s+2") { $script:restoreLines.Add('sc config ' + $s + ' start= auto') }
        elseif ($startLine -match "START_TYPE\s+:\s+3") { $script:restoreLines.Add('sc config ' + $s + ' start= demand') }
        elseif ($startLine -match "START_TYPE\s+:\s+4") { $script:restoreLines.Add('sc config ' + $s + ' start= disabled') }
        elseif ($startLine -match "START_TYPE\s+:\s+1") { $script:restoreLines.Add('sc config ' + $s + ' start= boot') }
    }

    & bcdedit.exe /enum "{current}" 2>&1 | Add-Content -Path $BcdFile -Encoding Unicode
    & schtasks.exe /query /fo CSV 2>$null | Add-Content -Path $TasksFile -Encoding Unicode

    $restoreFile = Join-Path $OutDir "restore.ps1"
    $restoreLines | Set-Content -Path $restoreFile -Encoding Unicode
}

$manifestObj = @{
    created = (Get-Date -Format o)
    reg_targets = $RegTargets.Count
    services = $Services
    exports = @($regExports)
}
$manifestObj | ConvertTo-Json | Set-Content -Path $Manifest -Encoding Unicode

Write-Host ""
Write-Host "Baseline captured to: $OutDir"
Write-Host "  reg_values.txt     normalized registry state (for diffing)"
Write-Host "  services.txt       service configuration + state"
Write-Host "  powercfg-active.txt power scheme dump"
Write-Host "  bcdedit.txt        boot configuration"
Write-Host "  schtasks.csv       scheduled tasks"
Write-Host "  *.reg              exact registry backups (for restore)"
if (-not $RegistryOnly) {
    Write-Host "  restore.ps1        re-applies captured state (run elevated)"
    Write-Host "  active-power-scheme.pow full power plan export"
}
Write-Host ""
Write-Host "Run this at a clean baseline, AFTER applying your tweaks, and again after reverting."
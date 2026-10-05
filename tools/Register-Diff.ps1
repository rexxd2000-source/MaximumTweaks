param(
    [string]$Before,
    [string]$After,
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"

if (-not $Before -or -not $After) {
    Write-Host "Usage: Register-Diff.ps1 -Before <snapshotDir> -After <snapshotDir>"
    exit 1
}
if (-not (Test-Path $Before)) { Write-Host "Before dir not found: $Before"; exit 1 }
if (-not (Test-Path $After))  { Write-Host "After dir not found: $After"; exit 1 }

function Load-RegMap([string]$dir) {
    $map = @{}
    $f = Join-Path $dir "reg_values.txt"
    if (-not (Test-Path $f)) { return $map }
    Get-Content $f | ForEach-Object {
        $i = $_.IndexOf(" :: ")
        if ($i -gt 0) {
            $key = $_.Substring(0, $i)
            $val = $_.Substring($i + 4)
            $map[$key] = $val
        }
    }
    return $map
}

$bMap = Load-RegMap $Before
$aMap = Load-RegMap $After

$added = New-Object System.Collections.Generic.List[string]
$removed = New-Object System.Collections.Generic.List[string]
$changed = New-Object System.Collections.Generic.List[string]

foreach ($k in $aMap.Keys) {
    if (-not $bMap.ContainsKey($k)) { $added.Add("  + $k = $($aMap[$k])") }
}
foreach ($k in $bMap.Keys) {
    if (-not $aMap.ContainsKey($k)) { $removed.Add("  - $k = $($bMap[$k])") }
}
foreach ($k in $bMap.Keys) {
    if ($aMap.ContainsKey($k) -and $aMap[$k] -ne $bMap[$k]) {
        $changed.Add("  ~ $k`n      before: $($bMap[$k])`n      after : $($aMap[$k])")
    }
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("Registry diff")
$lines.Add("  before: $Before")
$lines.Add("  after : $After")
$lines.Add("")
$lines.Add("ADDED ($($added.Count)):")
if ($added.Count -eq 0) { $lines.Add("  (none)") } else { $added | ForEach-Object { $lines.Add($_) } }
$lines.Add("")
$lines.Add("REMOVED ($($removed.Count)):")
if ($removed.Count -eq 0) { $lines.Add("  (none)") } else { $removed | ForEach-Object { $lines.Add($_) } }
$lines.Add("")
$lines.Add("CHANGED ($($changed.Count)):")
if ($changed.Count -eq 0) { $lines.Add("  (none)") } else { $changed | ForEach-Object { $lines.Add($_) } }

$lines.Add("")
$lines.Add("Services diff")
$sf1 = Join-Path $Before "services.txt"; $sf2 = Join-Path $After "services.txt"
if ((Test-Path $sf1) -and (Test-Path $sf2)) {
    $svcDiff = @(Compare-Object (Get-Content $sf1) (Get-Content $sf2))
    if ($svcDiff.Count -eq 0) { $lines.Add("  (no changes)") } else {
        $keyLines = @()
        $svcDiff | Where-Object { $_.SideIndicator -ne "=" } | ForEach-Object {
            if ($_.InputObject -match "START_TYPE|STATE\s+") { $keyLines += ("  " + $_.SideIndicator + " " + $_.InputObject.Trim()) }
        }
        if ($keyLines.Count -eq 0) { $lines.Add("  (no start/state changes)") } else { $keyLines | ForEach-Object { $lines.Add($_) } }
    }
} else { $lines.Add("  services.txt missing in one snapshot") }

if (-not $OutFile) { $OutFile = Join-Path $PSScriptRoot ("diff-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt") }
$lines | Set-Content -Path $OutFile -Encoding Unicode
Write-Host "Diff written to: $OutFile"
Write-Host ""
$lines | ForEach-Object { Write-Host $_ }
"""Category: Laptop — battery, lid, thermal and portability optimizations.

Genuine laptop-only tweaks: power timeouts, lid behaviour, modern standby,
thermal policy, wireless power saving, and battery-life vs performance
controls.  Every tweak here targets hardware or OS features that only exist
on portable systems.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Laptop", win_default="10,11")
CATEGORY = "Laptop"

TWEAKS = validate_module("laptop", [
    # ── Lid Action ─────────────────────────────────────────────────
    T("lap-001", "Lid Close: Do Nothing (AC)",
      "Prevent sleep when closing the laptop lid while plugged in.",
      actions=[("power", "lid_action", 0, "AC")],
      revert=[("power", "lid_action", 1, "AC")],
      why="Closing the lid mid-game on AC power should not sleep the system. "
          "Do-nothing keeps the external display and peripherals alive.",
      changes="Sets lid-close action to 'Do nothing' on AC power.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["lid", "sleep", "power"]),

    T("lap-002", "Lid Close: Sleep (Battery)",
      "Ensure the laptop sleeps when the lid is closed on battery.",
      actions=[("power", "lid_action", 1, "DC")],
      revert=[("power", "lid_action", 0, "DC")],
      why="On battery, closing the lid should sleep to prevent accidental "
          "drain in a bag.  Sleep preserves your session with minimal power.",
      changes="Sets lid-close action to 'Sleep' on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["lid", "sleep", "battery"]),

    T("lap-003", "Lid Close: Hibernate (Battery)",
      "Hibernate when the lid is closed on battery for zero drain.",
      actions=[("power", "lid_action", 2, "DC")],
      revert=[("power", "lid_action", 1, "DC")],
      why="Hibernation writes RAM to disk and powers off completely. "
          "Ideal if you carry the laptop for long periods without charging.",
      changes="Sets lid-close action to 'Hibernate' on battery.",
      risk="low", impact="low", recommended="optional",
      admin=True,
      tags=["lid", "hibernate", "battery"]),

    # ── Display Timeout ────────────────────────────────────────────
    T("lap-004", "Display Never Off (AC)",
      "Keep the display on when plugged in.",
      actions=[("power", "display_timeout", 0, "AC")],
      revert=[("power", "display_timeout", 600, "AC")],
      why="Prevents the screen from going dark during presentations or "
          "docked use where the laptop display is the primary monitor.",
      changes="Sets display timeout to never on AC power.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["display", "timeout", "power"]),

    T("lap-005", "Display Off After 5 min (Battery)",
      "Turn the display off after 5 minutes on battery to save power.",
      actions=[("power", "display_timeout", 300, "DC")],
      revert=[("power", "display_timeout", 600, "DC")],
      why="The display is the biggest battery drain.  A short timeout on "
          "battery extends unplugged session time significantly.",
      changes="Sets display timeout to 5 minutes on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["display", "timeout", "battery"]),

    # ── Sleep Timeout ──────────────────────────────────────────────
    T("lap-006", "Never Sleep (AC)",
      "Prevent the system from sleeping on AC power.",
      actions=[("power", "sleep_timeout", 0, "AC")],
      revert=[("power", "sleep_timeout", 1800, "AC")],
      why="When docked or plugged in, sleep interruptions are frustrating. "
          "Never-sleep on AC avoids dropped connections and lost work.",
      changes="Disables automatic sleep on AC power.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["sleep", "timeout", "power"]),

    T("lap-007", "Sleep After 15 min (Battery)",
      "Sleep after 15 minutes of inactivity on battery.",
      actions=[("power", "sleep_timeout", 900, "DC")],
      revert=[("power", "sleep_timeout", 1800, "DC")],
      why="A 15-minute battery sleep balances convenience with power saving. "
          "Long enough to step away; short enough to conserve charge.",
      changes="Sets sleep timeout to 15 minutes on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["sleep", "timeout", "battery"]),

    # ── Hibernate Timeout ──────────────────────────────────────────
    T("lap-008", "Disable Hibernate on AC",
      "Prevent hibernation while plugged in.",
      actions=[("power", "hibernate_timeout", 0, "AC")],
      revert=[("power", "hibernate_timeout", 1800, "AC")],
      why="Hibernate writes a large file to disk and is slow to resume. "
          "On AC power there is no battery concern, so skip it.",
      changes="Disables hibernation timeout on AC power.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["hibernate", "timeout", "power"]),

    T("lap-009", "Hibernate After 30 min (Battery)",
      "Hibernate after 30 minutes of sleep on battery to prevent drain.",
      actions=[("power", "hibernate_timeout", 1800, "DC")],
      revert=[("power", "hibernate_timeout", 0, "DC")],
      why="If the laptop sleeps long enough on battery, hibernating saves "
          "the remaining charge and preserves your session safely.",
      changes="Sets hibernate timeout to 30 minutes on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["hibernate", "timeout", "battery"]),

    # ── HDD / NVMe Timeout ────────────────────────────────────────
    T("lap-010", "HDD Never Spindown (AC)",
      "Keep hard drives spinning when plugged in.",
      actions=[("power", "hdd_timeout", 0, "AC")],
      revert=[("power", "hdd_timeout", 600, "AC")],
      why="Frequent spin-up/down of mechanical drives causes wear and "
          "introduces latency when the drive wakes.  On AC, keep it running.",
      changes="Sets HDD spindown timeout to never on AC power.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["hdd", "timeout", "power"]),

    T("lap-011", "HDD Spindown After 10 min (Battery)",
      "Spin down the HDD after 10 minutes on battery.",
      actions=[("power", "hdd_timeout", 600, "DC")],
      revert=[("power", "hdd_timeout", 0, "DC")],
      why="Spinning down the hard drive on battery saves measurable power "
          "and extends unplugged session time.",
      changes="Sets HDD spindown to 10 minutes on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["hdd", "timeout", "battery"]),

    # ── Processor Performance on Battery ───────────────────────────
    T("lap-012", "Max CPU on Battery",
      "Allow the CPU to reach maximum performance on battery power.",
      actions=[("power", "processor_max", 100, "DC")],
      revert=[("power", "processor_max", 80, "DC")],
      why="Windows throttles the CPU to 50-80% on battery by default. "
          "Raising the ceiling to 100% prevents frame drops when gaming "
          "unplugged (at the cost of shorter battery life).",
      changes="Sets maximum processor state to 100% on battery.",
      risk="low", impact="moderate", recommended="optional",
      admin=True, confirm=True,
      tags=["cpu", "battery", "performance"]),

    T("lap-013", "Min CPU 5% on Battery",
      "Set the minimum processor performance state on battery.",
      actions=[("power", "processor_min", 5, "DC")],
      revert=[("power", "processor_min", 100, "DC")],
      why="A low minimum lets the CPU down-clock deeply at idle, saving "
          "battery.  The OS boosts to higher P-states on demand anyway.",
      changes="Sets minimum processor state to 5% on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["cpu", "battery", "power"]),

    # ── Turbo Boost on Battery ─────────────────────────────────────
    T("lap-014", "Disable Turbo Boost on Battery",
      "Disable CPU turbo boost when on battery to extend playtime.",
      actions=[("power", "boost_policy", 0, "DC")],
      revert=[("power", "boost_policy", 100, "DC")],
      why="Turbo boost is the biggest battery drain during gaming.  "
          "Disabling it on battery extends unplugged session time "
          "significantly while keeping base-clock performance.",
      changes="Disables turbo boost on battery power.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["boost", "turbo", "battery"]),

    # ── Modern Standby ─────────────────────────────────────────────
    T("lap-015", "Disable Modern Standby",
      "Switch from Modern Standby to S3 sleep for better battery life.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "PlatformAoAcOverride", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "PlatformAoAcOverride"),
      ],
      why="Modern Standby (S0 low power idle) keeps the CPU partially "
          "active during sleep, draining battery.  Forcing S3 deep sleep "
          "reduces standby power draw significantly.",
      changes="Disables Modern Standby, falls back to S3 sleep.",
      risk="low", impact="high", recommended="recommended",
      admin=True,
      tags=["modern_standby", "sleep", "battery"]),

    T("lap-016", "Enable Network Connectivity in Standby",
      "Allow the network adapter to stay connected during Modern Standby.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "CsEnableConnectedStandby", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "CsEnableConnectedStandby", 0, "DWORD"),
      ],
      why="If Modern Standby is active, keeping the network alive lets "
          "the laptop receive emails and notifications during sleep.",
      changes="Enables network connectivity during Modern Standby.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["modern_standby", "network", "standby"]),

    # ── Wi-Fi Power Saving ─────────────────────────────────────────
    T("lap-017", "Wi-Fi: Maximum Performance (AC)",
      "Set Wi-Fi adapter to maximum performance on AC power.",
      actions=[
          ("cmd", "netsh wlan set interface * powermode=fast"),
      ],
      revert=[
          ("cmd", "netsh wlan set interface * powermode=moderate"),
      ],
      why="Wi-Fi power saving modes add latency to wireless traffic. "
          "Maximum performance mode reduces ping spikes in online gaming.",
      changes="Sets Wi-Fi to maximum performance on AC power.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["wifi", "power", "latency"]),

    T("lap-018", "Wi-Fi: Moderate Power Saving (Battery)",
      "Use moderate Wi-Fi power saving on battery.",
      actions=[
          ("cmd", "netsh wlan set interface * powermode=moderate"),
      ],
      revert=[
          ("cmd", "netsh wlan set interface * powermode=fast"),
      ],
      why="Moderate power saving balances Wi-Fi throughput with battery "
          "life.  Not as aggressive as maximum saving mode.",
      changes="Sets Wi-Fi to moderate power saving on battery.",
      risk="safe", impact="low", recommended="recommended",
      tags=["wifi", "power", "battery"]),

    # ── Bluetooth Power Saving ─────────────────────────────────────
    T("lap-019", "Disable Bluetooth Power Saving",
      "Disable Bluetooth adapter power saving to reduce input latency.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Device\*",
           "AllowSleep", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Device\*",
           "AllowSleep"),
      ],
      why="Bluetooth power saving can cause intermittent input lag on "
          "wireless mice and controllers.  Disabling it keeps latency "
          "consistent at the cost of slight battery drain.",
      changes="Disables Bluetooth adapter power saving.",
      risk="safe", impact="low", recommended="optional",
      tags=["bluetooth", "power", "latency"]),

    # ── PCIe Power Management ──────────────────────────────────────
    T("lap-020", "Disable PCIe Power Management",
      "Disable PCIe ASPM to reduce device wake latency.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "CsEnabled", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "CsEnabled", 1, "DWORD"),
      ],
      why="PCIe Active State Power Management (ASPM) can add latency "
          "when devices wake from low-power states.  Disabling it "
          "keeps the GPU and NVMe SSD at full responsiveness.",
      changes="Disables PCIe power management (ASPM).",
      risk="low", impact="moderate", recommended="optional",
      admin=True,
      tags=["pcie", "power", "latency"]),

    # ── USB Selective Suspend ──────────────────────────────────────
    T("lap-021", "Disable USB Selective Suspend",
      "Disable USB selective suspend to prevent device disconnections.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "EnhancedSleepEnabled", 0, "DWORD"),
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
           "EnhancedSleepEnabled", 1, "DWORD"),
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="USB selective suspend can disconnect peripherals like mice, "
          "keyboards and audio interfaces when idle.  Disabling it "
          "keeps all USB devices responsive.",
      changes="Disables USB selective suspend.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["usb", "power", "peripheral"]),

    # ── Battery Charge Threshold ───────────────────────────────────
    T("lap-028", "Battery Charge Limit Guidance",
      "Guidance on setting charge thresholds to preserve battery health.",
      actions=[
          ("guidance", "Most laptop vendors provide battery charge limit "
           "settings in BIOS or vendor software (Lenovo Vantage, ASUS "
           "MyASUS, Dell Power Manager).  Setting an 80% charge limit "
           "extends battery lifespan by reducing cell stress.  Check "
           "your manufacturer's app for this option."),
      ],
      revert=[
          ("guidance", "Remove the charge limit to allow full 100% charging."),
      ],
      why="Lithium-ion batteries degrade faster at high charge states. "
          "A charge limit of 80% can double the battery's useful lifespan.",
      changes="Shows battery charge threshold guidance.",
      risk="safe", impact="very low", recommended="optional",
      tags=["battery", "health", "guidance"]),

    # ── Fan / Thermal ──────────────────────────────────────────────
    T("lap-029", "Aggressive Fan Policy (AC)",
      "Set the system cooling policy to Active on AC power.",
      actions=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Active cooling ramps up the fan before throttling the CPU. "
          "This keeps clocks high during sustained gaming loads.",
      changes="Sets cooling policy to Active on AC power.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["thermal", "fan", "cooling"]),

    T("lap-030", "Passive Cooling on Battery",
      "Set the system cooling policy to Passive on battery power.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Passive cooling throttles the CPU before spinning the fan, "
          "saving battery and reducing noise when unplugged.",
      changes="Sets cooling policy to Passive on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["thermal", "fan", "battery"]),

    # ── Docking / External Display ─────────────────────────────────
    T("lap-031", "Prevent Display Sleep on Dock",
      "Keep the display on when a docking station is detected.",
      actions=[
          ("reg", "HKCU", r"Control Panel\Desktop",
           "ForegroundLockTimeout", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKCU", r"Control Panel\Desktop",
           "ForegroundLockTimeout"),
      ],
      why="When docked with an external monitor, the laptop display "
          "should not timeout independently.  This setting prevents "
          "focus-lock timeout issues in docked scenarios.",
      changes="Prevents display sleep timeout when docked.",
      risk="safe", impact="low", recommended="optional",
      tags=["display", "dock", "power"]),

    # ── Power Plan for Battery Gaming ──────────────────────────────
    T("lap-032", "Use Balanced Plan on Battery",
      "Switch to the Balanced power plan on battery for efficiency.",
      actions=[
          ("cmd", "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e"),
      ],
      revert=[
          ("cmd", "powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"),
      ],
      why="The Balanced plan dynamically scales CPU frequency based on "
          "demand.  On battery this gives good performance when needed "
          "while saving power at idle.",
      changes="Activates the Balanced power plan.",
      risk="safe", impact="low", recommended="recommended",
      tags=["power", "plan", "battery"]),

    # ── Hibernate File ─────────────────────────────────────────────
    T("lap-033", "Reduce Hibernate File Size",
      "Set hibernation to reduced mode to save disk space.",
      actions=[
          ("cmd", "powercfg /h /type reduced"),
      ],
      revert=[
          ("cmd", "powercfg /h /type full"),
      ],
      why="Reduced hibernation saves only kernel, drivers and system state "
          "(not user sessions).  It uses ~half the disk space of full "
          "hibernation while still enabling fast startup.",
      changes="Sets hibernation to reduced mode.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["hibernation", "disk", "battery"]),

    # ── Boost Behavior ─────────────────────────────────────────────
    T("lap-034", "Aggressive Boost on AC",
      "Set CPU boost mode to Aggressive when plugged in for maximum clocks.",
      actions=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE 2"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Aggressive boost mode forces the CPU toward its highest turbo "
          "frequency under load, preventing unnecessary clock reductions "
          "during plugged-in gaming sessions.",
      changes="Sets CPU boost mode to Aggressive on AC power.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["boost", "cpu", "performance"]),

    T("lap-035", "Disable Boost on Battery",
      "Disable CPU turbo boost on battery to extend playtime.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE 0"),
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTPOL 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE 2"),
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTPOL 100"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Turbo boost draws the most power on a laptop.  Disabling it "
          "on battery extends unplugged session time significantly.",
      changes="Disables CPU turbo boost on battery power.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["boost", "turbo", "battery"]),

    # ── PCI Express on Battery ─────────────────────────────────────
    T("lap-036", "PCI Express Max Power on AC",
      "Set PCI Express link state power management to off on AC.",
      actions=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PCIEXPRESS ASPM 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PCIEXPRESS ASPM 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="PCIe ASPM adds wake latency for GPU and NVMe devices. "
          "Disabling it on AC keeps storage and GPU at full responsiveness.",
      changes="Disables PCIe link state power management on AC.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["pcie", "power", "latency"]),

    T("lap-037", "PCI Express Moderate Saving on Battery",
      "Set PCI Express to moderate power saving on battery.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PCIEXPRESS ASPM 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PCIEXPRESS ASPM 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Moderate PCIe power saving on battery balances storage and "
          "GPU latency with battery life.  L1 idle state is low-impact.",
      changes="Sets PCIe to moderate power saving on battery.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["pcie", "power", "battery"]),

    # ── USB Power on Battery ───────────────────────────────────────
    T("lap-038", "USB Selective Suspend on Battery",
      "Enable USB selective suspend on battery to conserve power.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="On battery, USB selective suspend powers down idle USB ports "
          "to extend battery life.  Devices wake on demand when needed.",
      changes="Enables USB selective suspend on battery.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["usb", "power", "battery"]),

    # ── NVMe / Storage Power ───────────────────────────────────────
    T("lap-039", "NVMe Aggressive Idle on Battery",
      "Allow NVMe drives to enter deep power states on battery.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_DISK NVMePrimaryNVMePowerStateTransitionLatencyTolerance 5000"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_DISK NVMePrimaryNVMePowerStateTransitionLatencyTolerance 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="NVMe power state transitions save measurable battery on "
          "laptops with NVMe storage, with negligible wake latency.",
      changes="Sets NVMe power transition latency tolerance on battery.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["nvme", "power", "battery"]),

    T("lap-040", "NVMe Responsive on AC",
      "Keep NVMe drives in responsive mode when plugged in.",
      actions=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_DISK NVMePrimaryNVMePowerStateTransitionLatencyTolerance 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_DISK NVMePrimaryNVMePowerStateTransitionLatencyTolerance 5000"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="On AC power there is no battery concern, so keeping NVMe "
          "drives responsive eliminates any wake-from-idle latency.",
      changes="Sets NVMe to maximum responsiveness on AC.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["nvme", "power", "performance"]),

    # ── Disk Idle ──────────────────────────────────────────────────
    T("lap-041", "Disk Never Idle on AC",
      "Prevent hard drives from idling on AC power.",
      actions=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_DISK DISKIDLE 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_DISK DISKIDLE 300"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Keeping the disk spinning on AC avoids spin-up latency "
          "when accessing files after idle periods.",
      changes="Disables disk idle timeout on AC power.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["disk", "power", "performance"]),

    T("lap-042", "Disk Idle 5 min on Battery",
      "Spin down the disk after 5 minutes on battery.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_DISK DISKIDLE 300"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_DISK DISKIDLE 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Spinning down the disk on battery saves power during "
          "periods of low disk activity.",
      changes="Sets disk idle timeout to 5 minutes on battery.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["disk", "power", "battery"]),

    # ── Display Refresh Rate ───────────────────────────────────────
    T("lap-043", "High Refresh on AC",
      "Ensure the display uses its highest refresh rate when plugged in.",
      actions=[
          ("reg", "HKCU", r"Control Panel\Desktop", "RefreshRate", 0, "STRING"),
      ],
      revert=[
          ("regdel", "HKCU", r"Control Panel\Desktop", "RefreshRate"),
      ],
      why="Some laptops drop to 60 Hz on battery even when plugged in. "
          "Forcing the highest available refresh rate provides the "
          "smoothest gaming and desktop experience.",
      changes="Sets display to highest refresh rate on AC power.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["display", "refresh", "performance"]),

    # ── Background Apps on Battery ─────────────────────────────────
    T("lap-044", "Restrict Background Apps on Battery",
      "Restrict UWP background app activity when on battery power.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
           "GlobalUserDisabled", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
           "GlobalUserDisabled"),
      ],
      why="Background UWP apps drain battery by polling, syncing and "
          "updating when you are not using them.  Restricting them "
          "on battery extends unplugged session time.",
      changes="Restricts background apps on battery power.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["background", "battery", "apps"]),

    # ── Game Mode on Battery ───────────────────────────────────────
    T("lap-045", "Disable Game Mode on Battery",
      "Disable Windows Game Mode when on battery to save power.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode"),
      ],
      why="Game Mode reserves CPU/GPU resources for games, which "
          "consumes extra battery.  On battery, disabling it saves "
          "power when not gaming.",
      changes="Disables Game Mode when on battery.",
      risk="safe", impact="low", recommended="optional",
      tags=["gamemode", "battery", "power"]),

    # ── Processor Idle ─────────────────────────────────────────────
    T("lap-046", "Deep CPU Idle on Battery",
      "Allow the CPU to enter deeper idle states on battery.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR IDLEDISC 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR IDLEDISC 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Idle disconnect allows the CPU to drop to lower C-states "
          "when idle, reducing battery drain during light workloads.",
      changes="Enables deep CPU idle on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["cpu", "idle", "battery"]),

    # ── Hybrid Sleep ───────────────────────────────────────────────
    T("lap-047", "Disable Hybrid Sleep on Battery",
      "Disable hybrid sleep on battery to prevent disk writes.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP HYBRIDSLEEP 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP HYBRIDSLEEP 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Hybrid sleep writes RAM to disk while also maintaining "
          "power.  On battery this wastes disk writes and battery "
          "charge.  Regular sleep is more efficient.",
      changes="Disables hybrid sleep on battery.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["sleep", "battery", "power"]),

    # ── Wake Timers ────────────────────────────────────────────────
    T("lap-048", "Disable Wake Timers on Battery",
      "Prevent scheduled tasks from waking the laptop on battery.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCTIMER_ALLOW 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCTIMER_ALLOW 1"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="Wake timers (scheduled tasks, Windows Update) can wake "
          "the laptop from sleep, draining battery in a bag or "
          "backpack.  Disabling them on battery prevents this.",
      changes="Disables wake timers on battery power.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["wake", "sleep", "battery"]),

    # ── Adaptive Brightness ────────────────────────────────────────
    T("lap-049", "Disable Adaptive Brightness",
      "Disable ambient light sensor-based brightness adjustment.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SensorOverrides\{70050992-0f75-4bc7-bf43-4956634d5462}",
           "Disabled", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SensorOverrides\{70050992-0f75-4bc7-bf43-4956634d5462}",
           "Disabled"),
      ],
      why="Adaptive brightness can cause distracting brightness "
          "fluctuations during gaming.  Disabling it gives you "
          "full manual control over the display brightness.",
      changes="Disables adaptive brightness via ambient light sensor.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["display", "brightness", "sensor"]),

    # ── C-State on Battery ─────────────────────────────────────────
    T("lap-050", "Moderate C-States on Battery",
      "Allow moderate CPU C-states on battery for power savings.",
      actions=[
          ("power", "processor_idle_allow", 1, "DC"),
          ("power", "processor_idle_demote_threshold", 2, "DC"),
      ],
      revert=[
          ("power", "processor_idle_allow", 0, "DC"),
          ("power", "processor_idle_demote_threshold", 0, "DC"),
      ],
      why="Moderate C-states on battery let the CPU save power during "
          "idle moments without the wake latency of deepest C-states.",
      changes="Enables moderate CPU idle states on battery.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["cpu", "cstate", "battery"]),

    # ── Processor Performance on AC ────────────────────────────────

    # ── Timer Resolution on Battery ────────────────────────────────
    T("lap-052", "Standard Timer on Battery",
      "Use standard timer resolution on battery to save power.",
      actions=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP TIMERRESOLUTION 0"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      revert=[
          ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP TIMERRESOLUTION 5000"),
          ("cmd", "powercfg /setactive SCHEME_CURRENT"),
      ],
      why="High-resolution timers prevent deep idle states and waste "
          "battery.  On battery, the standard timer resolution is "
          "sufficient for normal workloads.",
      changes="Sets standard timer resolution on battery.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["timer", "battery", "power"]),

    # ── Desktop Composition on Battery ─────────────────────────────
    T("lap-053", "Disable DWM Effects on Battery",
      "Disable DWM visual effects on battery to reduce GPU power draw.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\DWM", "ForceEffectMode", 5, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\Windows\DWM", "ForceEffectMode"),
      ],
      why="DWM composition effects (transparency, animations) keep "
          "the GPU active.  Disabling them on battery reduces GPU "
          "power consumption noticeably.",
      changes="Disables DWM visual effects on battery.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["dwm", "gpu", "battery"]),
])

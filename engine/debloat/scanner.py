"""Smart Debloater scanner — application-focused system scanning.

Scans the actual PC for:
- Microsoft Store / AppX consumer applications
- Third-party applications (focus on bloatware)
- OEM software
- Optional services (extremely conservative)
- Scheduled tasks (optional, consumer-facing)
- Startup entries

Does NOT scan:
- Windows features
- Core Windows services
- Networking components
- PowerShell / command-line tools
- NVIDIA / AMD / Intel driver components
"""

from __future__ import annotations

import json
import subprocess

from engine.debloat.types import (
    DebloatCategory, RiskLevel, OSInfo, DebloatItem,
)
from engine.debloat.protected import (
    PROTECTED_SERVICES, PROTECTED_OEM, PROTECTED_APPX,
    KNOWN_DEPENDENCIES, GAMING_SOFTWARE_PATTERNS,
    BLOATWARE_PATTERNS, INTENTIONAL_SOFTWARE,
    KNOWN_OEM_BLOAT, OEM_PUBLISHERS, RUNTIME_PATTERNS,
    EXCLUDED_SERVICES,
)


def _run_ps(command: str, timeout: int = 30) -> str:
    """Run a PowerShell command and return stdout."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _run_ps_json(command: str, timeout: int = 30) -> list[dict]:
    """Run PowerShell, parse JSON output."""
    raw = _run_ps(f"({command}) | ConvertTo-Json -Depth 3 -Compress", timeout)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
        return []
    except (json.JSONDecodeError, TypeError):
        return []


# ── OS Detection ───────────────────────────────────────────────────

def scan_os() -> OSInfo:
    """Detect Windows version, edition, build, architecture."""
    info = OSInfo()

    raw = _run_ps("(Get-CimInstance Win32_OperatingSystem).Caption")
    if raw:
        info.product_name = raw

    raw = _run_ps("[System.Environment]::OSVersion.Version.ToString()")
    if raw:
        info.version = raw
        parts = raw.split(".")
        if len(parts) >= 3:
            info.build = parts[2]

    raw = _run_ps("(Get-CimInstance Win32_OperatingSystem).OSArchitecture")
    if raw:
        info.architecture = raw

    raw = _run_ps("(Get-CimInstance Win32_OperatingSystem).DisplayVersion")
    if raw and raw.lower() != "null":
        info.display_version = raw

    if not info.build:
        reg = _run_ps(
            "(Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion' "
            "-Name CurrentBuild -ErrorAction SilentlyContinue).CurrentBuild"
        )
        if reg:
            info.build = reg

    if not info.product_name:
        reg = _run_ps(
            "(Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion' "
            "-Name ProductName -ErrorAction SilentlyContinue).ProductName"
        )
        if reg:
            info.product_name = reg

    p = info.product_name.lower()
    if "home" in p:
        info.edition = "Home"
    elif "pro for workstations" in p:
        info.edition = "Pro for Workstations"
    elif "pro" in p:
        info.edition = "Pro"
    elif "enterprise" in p:
        info.edition = "Enterprise"
    elif "education" in p:
        info.edition = "Education"
    elif "server" in p:
        info.edition = "Server"
    else:
        info.edition = info.product_name
    return info


# ── Microsoft Store / AppX Scan ────────────────────────────────────

# Known optional Microsoft Store consumer apps
_KNOWN_STORE_BLOAT: dict[str, tuple[str, str, str, int]] = {
    # name: (display_name, description, what_happens, confidence)
    "Microsoft.3DBuilder": ("3D Builder", "Legacy 3D modeling app", "Removes the app; no impact on modern Windows", 85),
    "Microsoft.BingFinance": ("Bing Finance", "Pre-installed financial news app", "Removes the app; no system impact", 90),
    "Microsoft.BingNews": ("Bing News", "Pre-installed news aggregator", "Removes the app; no system impact", 90),
    "Microsoft.BingSports": ("Bing Sports", "Pre-installed sports news app", "Removes the app; no system impact", 90),
    "Microsoft.BingWeather": ("Bing Weather", "Pre-installed weather app", "Removes the app; use a web browser for weather", 85),
    "Microsoft.GetHelp": ("Get Help", "Microsoft support/troubleshooting app", "Removes the app; no impact on system stability", 90),
    "Microsoft.Getstarted": ("Tips", "Windows tips app that shows suggestions", "Removes the app; no system impact", 90),
    "Microsoft.MicrosoftOfficeHub": ("Office Hub", "Microsoft Office launcher/upsell app", "Removes the app; Office apps installed separately are unaffected", 85),
    "Microsoft.MicrosoftSolitaireCollection": ("Solitaire Collection", "Pre-installed card games collection", "Removes the games; no system impact", 95),
    "Microsoft.MixedReality.Portal": ("Mixed Reality Portal", "Windows Mixed Reality headset setup app", "Removes the app; no impact without VR headsets", 90),
    "Microsoft.People": ("People", "Contacts management app", "Removes contacts app; Mail/Calendar lose contact integration", 70),
    "Microsoft.SkypeApp": ("Skype", "Pre-installed Skype communication app", "Removes Skype; use web version or reinstall from Store", 80),
    "Microsoft.Wallet": ("Wallet", "Microsoft Pay/Wallet digital payment app", "Removes the app; no impact if not used for payments", 90),
    "Microsoft.WindowsAlarms": ("Alarms & Clock", "Built-in alarm/timer/stopwatch/clock app", "Removes the app; no system impact", 75),
    "Microsoft.WindowsCommunicationsApps": ("Mail and Calendar", "Mail and Calendar bundled apps", "Removes Mail and Calendar; reinstall from Store if needed", 60),
    "Microsoft.WindowsFeedbackHub": ("Feedback Hub", "Microsoft feedback and bug reporting app", "Removes the app; no impact on system stability", 90),
    "Microsoft.WindowsMaps": ("Windows Maps", "Pre-installed offline/online maps app", "Removes the app; no system impact", 90),
    "Microsoft.YourPhone": ("Phone Link", "Connects Android/iPhone to Windows", "Removes phone integration; no impact on other functionality", 85),
    "Microsoft.ZuneMusic": ("Media Player", "Modern Media Player app", "Removes the media player; use another player", 80),
    "Microsoft.ZuneVideo": ("Movies & TV", "Video playback app", "Removes the video player; use another player", 80),
    "Microsoft.549981C3F5F10": ("Cortana", "Microsoft voice assistant", "Removes Cortana; no impact on system functionality", 90),
    "Microsoft.MicrosoftStickyNotes": ("Sticky Notes", "Digital sticky notes app", "Removes the app; no system impact", 85),
    "Microsoft.Todos": ("Microsoft To Do", "Task management app", "Removes the app; no system impact", 85),
    "Microsoft.PowerAutomateDesktop": ("Power Automate Desktop", "Robotic process automation tool", "Removes the automation tool; no impact if not used", 85),
    "Microsoft.Clipchamp": ("Clipchamp", "Microsoft video editor", "Removes the video editor; reinstall from Store if needed", 80),
    "Microsoft.WindowsCopilot": ("Windows Copilot", "AI assistant integrated into Windows", "Removes Copilot; no impact on core Windows", 75),
}

# System/framework packages that must never be shown
_SYSTEM_PACKAGES: set[str] = {
    "Microsoft.AAD.BrokerPlugin", "Microsoft.AccountsControl",
    "Microsoft.AsyncTextService", "Microsoft.BioEnrollment",
    "Microsoft.CredDialogHost", "Microsoft.CapturePicker",
    "Microsoft.CloudExperienceHost", "Microsoft.DesktopAppInstaller",
    "Microsoft.HEIFImageExtension", "Microsoft.InputApp",
    "Microsoft.LockApp", "Microsoft.MathInputEditor",
    "Microsoft.Net.CompiledManaged", "Microsoft.Net.Host",
    "Microsoft.PPIProjection", "Microsoft.RawImageExtension",
    "Microsoft.SecHealthUI", "Microsoft.Services.Store.Engagement",
    "Microsoft.Search", "Microsoft.Windows.AppRep.ChxApp",
    "Microsoft.Windows.AssignedAccess", "Microsoft.Windows.CloudExperienceHost",
    "Microsoft.Windows.ContentDelivery", "Microsoft.Windows.ParentalControls",
    "Microsoft.Windows.PinningConfirmationDialog", "Microsoft.Windows.SecHealthUI",
    "Microsoft.Windows.ShellExperienceHost", "Microsoft.Windows.StartMenuExperienceHost",
    "Microsoft.Windows.StartScreenExperience", "Microsoft.Windows.UI.CachedInput",
    "Microsoft.Windows.UI.Xaml", "Microsoft.Windows.Voice",
    "Microsoft.WindowsApp", "Microsoft.WindowsCalculator",
    "Microsoft.WindowsStore", "Microsoft.Xbox.TCUI",
    "Microsoft.XboxGameCallableUI", "Microsoft.XboxIdentityProvider",
    "Microsoft.XboxSpeechToText", "Microsoft.YourPhone",
    "Microsoft.Windows.Photos", "Microsoft.WindowsTerminal",
    "Microsoft.WindowsTerminalPreview", "Microsoft.WinJS",
    "Microsoft.UI.Xaml", "Microsoft.WebpImageExtension",
    "Microsoft.WebMediaExtensions", "Microsoft.Xbox",
    "Microsoft.XboxGamingOverlay", "Microsoft.XboxGameOverlay",
    "Microsoft.XboxApp", "Microsoft.549981C3F5F10",
    "Microsoft.WindowsFeedbackHub", "Microsoft.WindowsMaps",
    "Microsoft.ZuneMusic", "Microsoft.ZuneVideo",
    "Microsoft.People", "Microsoft.MicrosoftStickyNotes",
    "Microsoft.Todos", "Microsoft.PowerAutomateDesktop",
    "Microsoft.WindowsAlarms", "Microsoft.WindowsCommunicationsApps",
    "Microsoft.BingWeather", "Microsoft.BingNews",
    "Microsoft.BingFinance", "Microsoft.BingSports",
    "Microsoft.GetHelp", "Microsoft.Getstarted",
    "Microsoft.MicrosoftSolitaireCollection", "Microsoft.MixedReality.Portal",
    "Microsoft.SkypeApp", "Microsoft.Wallet",
    "Microsoft.WindowsClipEditor", "Microsoft.ScreenSketch",
    "Microsoft.WindowsTerminal", "Microsoft.WindowsTerminalPreview",
    "Microsoft.MicrosoftOfficeHub", "Microsoft.Clipchamp",
    "Microsoft.WindowsCopilot",
}


def scan_appx_packages() -> list[DebloatItem]:
    """Scan installed AppX/MSIX packages for optional consumer apps."""
    items: list[DebloatItem] = []
    pkgs = _run_ps_json(
        "Get-AppxPackage -AllUsers | "
        "Select-Object Name,PackageFullName,Version,Status | "
        "ConvertTo-Json -Depth 3 -Compress"
    )

    for pkg in pkgs:
        name = pkg.get("Name", "")
        if not name:
            continue
        # Skip GUID-like names
        if len(name) > 8 and all(c in "0123456789abcdef-" for c in name.lower().replace("-", "")):
            continue
        # Skip system/framework packages
        if name in _SYSTEM_PACKAGES:
            continue
        # Skip Windows.* and MicrosoftWindows.* system components
        if name.startswith("MicrosoftWindows.") or name.startswith("Windows."):
            continue
        # Skip Microsoft.* that we can't identify (likely system)
        if name.startswith("Microsoft.") and name not in _KNOWN_STORE_BLOAT:
            continue
        # Skip runtime frameworks
        if name.startswith("MicrosoftCorporationII.") or name.startswith("MicrosoftCorporation."):
            continue
        if name.startswith("PythonSoftwareFoundation."):
            continue

        full_name = pkg.get("PackageFullName", "")
        version = pkg.get("Version", "")

        if name in _KNOWN_STORE_BLOAT:
            display, desc, what, conf = _KNOWN_STORE_BLOAT[name]
            items.append(DebloatItem(
                id=f"appx_{name}",
                name=display,
                description=desc,
                what_happens=what,
                category=DebloatCategory.MICROSOFT_STORE,
                risk=RiskLevel.SAFE if conf >= 80 else RiskLevel.OPTIONAL,
                confidence=conf,
                reversible=True,
                detected=True,
                remove_command=f"Get-AppxPackage -AllUsers -Name '{name}' | Remove-AppxPackage",
                restore_command=f"Add-AppxPackage -Register '{full_name}'" if full_name else "",
                verify_command=f"Get-AppxPackage -Name '{name}'",
                source="Microsoft Store App",
                version_found=version,
            ))

    return items


# ── Third-Party App Scan ───────────────────────────────────────────

def scan_third_party_apps() -> list[DebloatItem]:
    """Scan installed third-party applications from registry."""
    items: list[DebloatItem] = []
    all_sw: list[dict] = []

    paths = [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        r"HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    ]

    for reg_path in paths:
        progs = _run_ps_json(
            f"Get-ItemProperty '{reg_path}' -ErrorAction SilentlyContinue | "
            f"Where-Object {{$_.DisplayName -and $_.Publisher}} | "
            f"Select-Object DisplayName,Publisher,DisplayVersion,InstallLocation,UninstallString | "
            f"ConvertTo-Json -Depth 3 -Compress"
        )
        all_sw.extend(progs)

    seen_names: set[str] = set()
    for prog in all_sw:
        name = prog.get("DisplayName", "")
        publisher = prog.get("Publisher", "")
        version = prog.get("DisplayVersion", "")
        uninstall = prog.get("UninstallString", "")
        install_loc = prog.get("InstallLocation", "")

        if not name or name in seen_names:
            continue
        seen_names.add(name)

        # Skip Microsoft software (handled by AppX scanner)
        if "microsoft" in publisher.lower() and "microsoft corporation" in publisher.lower():
            continue

        # Skip runtimes/frameworks/drivers
        if any(rp.lower() in name.lower() for rp in RUNTIME_PATTERNS):
            continue
        if any(rp.lower() in publisher.lower() for rp in RUNTIME_PATTERNS):
            continue

        # Skip NVIDIA/AMD/Intel — completely excluded
        if any(x in publisher.lower() for x in ("nvidia", "amd", "intel")):
            continue
        if any(x in name.lower() for x in ("nvidia", "geforce", "amd radeon", "intel graphics")):
            continue

        # Skip OEM publishers (handled by OEM scanner)
        if any(oem.lower() in publisher.lower() for oem in OEM_PUBLISHERS):
            continue

        # Skip intentionally installed software
        is_intentional = False
        for pattern in INTENTIONAL_SOFTWARE:
            if pattern.lower() in name.lower():
                is_intentional = True
                break
        if is_intentional:
            continue

        # Check if this is known bloatware
        is_bloat = False
        for pattern, (display, desc, bloat_conf) in BLOATWARE_PATTERNS.items():
            if pattern.lower() in name.lower():
                items.append(DebloatItem(
                    id=f"3p_{name.replace(' ', '_').lower()[:50]}",
                    name=display,
                    description=desc,
                    what_happens="Uninstalls this application from the system.",
                    category=DebloatCategory.THIRD_PARTY,
                    risk=RiskLevel.SAFE if bloat_conf >= 80 else RiskLevel.OPTIONAL,
                    confidence=bloat_conf,
                    reversible=False,
                    detected=True,
                    remove_command=uninstall if uninstall else "",
                    verify_command=f"Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' | Where-Object {{$_.DisplayName -eq '{name}'}}",
                    source="Third-Party Application",
                    version_found=f"{publisher} v{version}" if version else publisher,
                ))
                is_bloat = True
                break

        if is_bloat:
            continue

        # Check gaming software — protect it
        is_gaming = False
        for pattern, label in GAMING_SOFTWARE_PATTERNS:
            if pattern.lower() in name.lower():
                is_gaming = True
                break
        if is_gaming:
            continue

        # Check known dependencies
        is_dep = False
        for dep_pattern in KNOWN_DEPENDENCIES:
            if dep_pattern.lower() in name.lower():
                is_dep = True
                break
        if is_dep:
            continue

        # Unknown third-party app — show with MODERATE risk and low confidence
        # Only show if it looks like a consumer app (not a driver/utility)
        if _looks_like_bloat(name, publisher):
            items.append(DebloatItem(
                id=f"3p_{name.replace(' ', '_').lower()[:50]}",
                name=name,
                description=f"Installed application by {publisher}.",
                what_happens="Uninstalls this application from the system.",
                category=DebloatCategory.THIRD_PARTY,
                risk=RiskLevel.CAUTION,
                confidence=30,
                reversible=False,
                detected=True,
                remove_command=uninstall if uninstall else "",
                verify_command=f"Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' | Where-Object {{$_.DisplayName -eq '{name}'}}",
                source="Third-Party Application",
                version_found=f"{publisher} v{version}" if version else publisher,
            ))

    return items


def _looks_like_bloat(name: str, publisher: str) -> bool:
    """Heuristic: does this app look like it could be bloatware?"""
    name_lower = name.lower()
    pub_lower = publisher.lower()

    # Skip system utilities, drivers, runtimes
    skip_words = [
        "driver", "runtime", "framework", "update", "service",
        "tool", "helper", "manager", "monitor", "controller",
        "adapter", "bridge", "protocol", "stack",
    ]
    if any(w in name_lower for w in skip_words):
        return False

    # Skip well-known publishers
    known_publishers = [
        "microsoft", "google", "mozilla", "adobe", "oracle",
        "vmware", "docker", "github", "jetbrains", "Notepad++",
    ]
    if any(p in pub_lower for p in known_publishers):
        return False

    # If it has a generic/bundled-sounding name, it might be bloat
    bloat_signals = [
        "assistant", "toolbar", "bar", "search", "offer",
        "deal", "coupon", "saver", "optimizer", "cleaner",
        "booster", "tune", "enhancer", "manager pro",
        "trial", "free", "lite", "premium",
    ]
    if any(s in name_lower for s in bloat_signals):
        return True

    return False


# ── OEM Software Scan ──────────────────────────────────────────────

def scan_oem_apps() -> list[DebloatItem]:
    """Scan for OEM pre-installed software."""
    items: list[DebloatItem] = []
    all_sw: list[dict] = []

    paths = [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        r"HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    ]

    for reg_path in paths:
        progs = _run_ps_json(
            f"Get-ItemProperty '{reg_path}' -ErrorAction SilentlyContinue | "
            f"Where-Object {{$_.DisplayName -and $_.Publisher}} | "
            f"Select-Object DisplayName,Publisher,DisplayVersion,UninstallString | "
            f"ConvertTo-Json -Depth 3 -Compress"
        )
        all_sw.extend(progs)

    seen_names: set[str] = set()
    for prog in all_sw:
        name = prog.get("DisplayName", "")
        publisher = prog.get("Publisher", "")
        version = prog.get("DisplayVersion", "")
        uninstall = prog.get("UninstallString", "")

        if not name or name in seen_names:
            continue
        seen_names.add(name)

        # Must be from an OEM publisher
        is_oem = any(oem.lower() in publisher.lower() for oem in OEM_PUBLISHERS)
        if not is_oem:
            continue

        # Skip NVIDIA/AMD/Intel — completely excluded
        if any(x in publisher.lower() for x in ("nvidia", "amd", "intel")):
            continue
        if any(x in name.lower() for x in ("nvidia", "geforce", "amd radeon", "intel")):
            continue

        # Skip runtimes/frameworks/drivers
        if any(rp.lower() in name.lower() for rp in RUNTIME_PATTERNS):
            continue

        # Check if this is known OEM bloat
        for pattern, (display, desc, conf) in KNOWN_OEM_BLOAT.items():
            if pattern.lower() in name.lower():
                items.append(DebloatItem(
                    id=f"oem_{name.replace(' ', '_').lower()[:50]}",
                    name=display,
                    description=desc,
                    what_happens="Removes this OEM application from the system.",
                    category=DebloatCategory.OEM,
                    risk=RiskLevel.SAFE if conf >= 75 else RiskLevel.OPTIONAL,
                    confidence=conf,
                    reversible=False,
                    detected=True,
                    remove_command=uninstall if uninstall else "",
                    verify_command=f"Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' | Where-Object {{$_.DisplayName -eq '{name}'}}",
                    source="OEM Software",
                    version_found=f"{publisher} v{version}" if version else publisher,
                ))
                break
        else:
            # Unknown OEM app — show with low confidence
            items.append(DebloatItem(
                id=f"oem_{name.replace(' ', '_').lower()[:50]}",
                name=name,
                description=f"OEM software from {publisher}.",
                what_happens="Removes this OEM application from the system.",
                category=DebloatCategory.OEM,
                risk=RiskLevel.CAUTION,
                confidence=25,
                reversible=False,
                detected=True,
                remove_command=uninstall if uninstall else "",
                verify_command=f"Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' | Where-Object {{$_.DisplayName -eq '{name}'}}",
                source="OEM Software",
                version_found=f"{publisher} v{version}" if version else publisher,
            ))

    return items


# ── Optional Services Scan ─────────────────────────────────────────

# Extremely conservative list of optional services.
# Each entry: (service_name, display_name, description, what_happens, default_risk, confidence)
_OPTIONAL_SERVICES: list[tuple[str, str, str, str, RiskLevel, int]] = [
    ("MapsBroker", "Downloaded Maps Manager",
     "Manages downloaded offline maps",
     "Disables automatic map updates; Maps app may not work offline",
     RiskLevel.SAFE, 85),
    ("RetailDemo", "Retail Demo Service",
     "Runs retail demo mode content for store displays",
     "Disables retail demo; no impact on personal use",
     RiskLevel.SAFE, 90),
    ("PhoneSvc", "Phone Service",
     "Manages telephony and phone connectivity",
     "Disables phone features; no impact on desktop use",
     RiskLevel.OPTIONAL, 70),
    ("SEMgrSvc", "NFC and Payment",
     "Manages secure element for NFC payments",
     "Disables NFC payments; no impact without NFC hardware",
     RiskLevel.OPTIONAL, 75),
    ("wisvc", "Windows Insider Service",
     "Manages Windows Insider Preview builds",
     "Disables Insider builds; no impact on stable releases",
     RiskLevel.OPTIONAL, 80),
    ("lfsvc", "Geolocation Service",
     "Manages geolocation and location services",
     "Disables location tracking; apps cannot access location",
     RiskLevel.OPTIONAL, 70),
    ("dmwappushservice", "WAP Push Message Routing",
     "Routes WAP push messages for device management",
     "Disables WAP push routing; no impact on desktop systems",
     RiskLevel.SAFE, 80),
    ("RemoteRegistry", "Remote Registry",
     "Allows remote users to modify registry settings",
     "Disables remote registry access; improves security",
     RiskLevel.SAFE, 85),
    ("Fax", "Fax Service",
     "Sends and receives faxes",
     "Disables fax functionality",
     RiskLevel.SAFE, 90),
    ("TapiSrv", "Telephony API",
     "Telephony and modem support",
     "Disables telephony; no impact on modern systems",
     RiskLevel.SAFE, 80),
]


def scan_optional_services() -> list[DebloatItem]:
    """Scan for optional services that can be safely disabled."""
    items: list[DebloatItem] = []

    svc_names = [s[0] for s in _OPTIONAL_SERVICES]
    svc_map = {s[0]: s for s in _OPTIONAL_SERVICES}

    # Get current state of all target services in one batch
    svc_list = "','".join(svc_names)
    raw = _run_ps(
        f"Get-Service -Name '{svc_list}' -ErrorAction SilentlyContinue | "
        f"Select-Object Name,DisplayName,Status,StartType | "
        f"ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        svcs = json.loads(raw) if raw else []
        if isinstance(svcs, dict):
            svcs = [svcs]
    except Exception:
        svcs = []

    for svc in svcs:
        name = svc.get("Name", "")
        status = svc.get("Status", "")
        start = svc.get("StartType", "")

        if name not in svc_map:
            continue

        _, display, desc, what, risk, conf = svc_map[name]

        # Check if this service is protected by dependencies
        is_protected = name in PROTECTED_SERVICES or name in EXCLUDED_SERVICES

        items.append(DebloatItem(
            id=f"svc_{name}",
            name=display,
            description=desc,
            what_happens=what,
            category=DebloatCategory.OPTIONAL_SERVICES,
            risk=risk,
            confidence=conf,
            reversible=True,
            detected=status == "Running" or start != "Disabled",
            remove_command=f"Stop-Service -Name '{name}' -Force; Set-Service -Name '{name}' -StartupType Disabled",
            restore_command=f"Set-Service -Name '{name}' -StartupType Manual",
            verify_command=f"(Get-Service -Name '{name}').StartType",
            source="Service",
            version_found=f"Status: {status}, Startup: {start}",
            is_protected=is_protected,
            detail_service=name,
            detail_state=f"Status: {status}",
            detail_startup=f"Startup Type: {start}",
        ))

    # Also scan Xbox services if gaming PC
    _scan_xbox_services(items)

    return items


def _scan_xbox_services(items: list[DebloatItem]):
    """Scan Xbox services — optional unless gaming software depends on them."""
    xbox_svcs = [
        ("XboxGipSvc", "Xbox Accessory Management",
         "Manages Xbox accessories and controllers",
         "Disables Xbox accessory management; controllers may still work"),
        ("XblAuthManager", "Xbox Live Auth Manager",
         "Manages Xbox Live authentication",
         "Disables Xbox Live sign-in; games may not connect to Live"),
        ("XblGameSave", "Xbox Live Game Save",
         "Syncs Xbox game saves to the cloud",
         "Disables cloud save sync for Xbox games"),
        ("XboxNetApiSvc", "Xbox Live Networking",
         "Manages Xbox Live network connectivity",
         "Disables Xbox Live networking features"),
    ]

    svc_names = [s[0] for s in xbox_svcs]
    svc_list = "','".join(svc_names)
    raw = _run_ps(
        f"Get-Service -Name '{svc_list}' -ErrorAction SilentlyContinue | "
        f"Select-Object Name,DisplayName,Status,StartType | "
        f"ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        svcs = json.loads(raw) if raw else []
        if isinstance(svcs, dict):
            svcs = [svcs]
    except Exception:
        svcs = []

    svc_map = {s[0]: s for s in xbox_svcs}

    for svc in svcs:
        name = svc.get("Name", "")
        status = svc.get("Status", "")
        start = svc.get("StartType", "")

        if name not in svc_map:
            continue

        _, display, desc, what = svc_map[name]

        items.append(DebloatItem(
            id=f"svc_{name}",
            name=display,
            description=desc,
            what_happens=what,
            category=DebloatCategory.OPTIONAL_SERVICES,
            risk=RiskLevel.OPTIONAL,
            confidence=60,
            reversible=True,
            detected=status == "Running" or start != "Disabled",
            remove_command=f"Stop-Service -Name '{name}' -Force; Set-Service -Name '{name}' -StartupType Disabled",
            restore_command=f"Set-Service -Name '{name}' -StartupType Manual",
            verify_command=f"(Get-Service -Name '{name}').StartType",
            source="Xbox Service",
            version_found=f"Status: {status}, Startup: {start}",
            detail_service=name,
            detail_state=f"Status: {status}",
            detail_startup=f"Startup Type: {start}",
        ))


# ── Scheduled Tasks Scan ───────────────────────────────────────────

_OPTIONAL_TASKS: list[tuple[str, str, str, str, int]] = [
    ("Consolidator", "Customer Experience Improvement",
     "Collects usage data for Microsoft improvement programs",
     "Stops CEIP data collection; no system impact", 85),
    ("UsbCeip", "USB CEIP",
     "Collects USB device usage data for Microsoft",
     "Stops USB telemetry; no system impact", 85),
    ("MapsToastTask", "Maps Notifications",
     "Shows toast notifications for Maps app",
     "Stops Maps notifications; no system impact", 85),
    ("MapsUpdateTask", "Maps Update",
     "Automatically updates offline maps",
     "Stops automatic map updates; no system impact", 85),
    ("XblGameSaveTask", "Xbox Game Save Sync",
     "Syncs Xbox game saves to cloud",
     "Stops cloud save sync; no system impact", 75),
    ("XblGameSaveTaskLogon", "Xbox Game Save (Logon)",
     "Syncs Xbox game saves on logon",
     "Stops cloud save sync on logon; no system impact", 75),
    ("FamilySafetyMonitorToastTask", "Family Safety Notifications",
     "Shows Family Safety notifications",
     "Stops Family Safety notifications; no impact if not used", 85),
    ("FamilySafetyRefreshTask", "Family Safety Refresh",
     "Refreshes Family Safety settings",
     "Stops Family Safety refresh; no impact if not used", 85),
    ("VerifyEmailTask", "Email Verification",
     "Verifies email address for Microsoft account",
     "Stops email verification checks; no impact", 85),
]


def scan_scheduled_tasks() -> list[DebloatItem]:
    """Scan for optional scheduled tasks."""
    items: list[DebloatItem] = []

    task_map = {t[0]: t for t in _OPTIONAL_TASKS}

    raw = _run_ps(
        "Get-ScheduledTask | Where-Object {$_.TaskPath -like '\\Microsoft\\*'} | "
        "Select-Object TaskName,TaskPath,State | ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        tasks = json.loads(raw) if raw else []
        if isinstance(tasks, dict):
            tasks = [tasks]
    except Exception:
        tasks = []

    for task in tasks:
        tname = task.get("TaskName", "")
        tpath = task.get("TaskPath", "")
        state = task.get("State", "")

        if tname not in task_map:
            continue

        _, display, desc, what, conf = task_map[tname]

        items.append(DebloatItem(
            id=f"task_{tname}",
            name=display,
            description=desc,
            what_happens=what,
            category=DebloatCategory.SCHEDULED_TASKS,
            risk=RiskLevel.SAFE if conf >= 80 else RiskLevel.OPTIONAL,
            confidence=conf,
            reversible=True,
            detected=state in ("Ready", "Running"),
            remove_command=f"Disable-ScheduledTask -TaskName '{tname}' -TaskPath '{tpath}'",
            restore_command=f"Enable-ScheduledTask -TaskName '{tname}' -TaskPath '{tpath}'",
            verify_command=f"(Get-ScheduledTask -TaskName '{tname}' -TaskPath '{tpath}').State",
            source="Scheduled Task",
            version_found=f"State: {state}",
        ))

    return items


# ── Startup Scan ───────────────────────────────────────────────────

def scan_startup_entries() -> list[DebloatItem]:
    """Scan startup entries — only OEM and bloatware launchers."""
    items: list[DebloatItem] = []

    raw = _run_ps(
        "Get-CimInstance Win32_StartupCommand | "
        "Select-Object Name,Command,Location,User | "
        "ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        entries = json.loads(raw) if raw else []
        if isinstance(entries, dict):
            entries = [entries]
    except Exception:
        entries = []

    oem_keywords = ["hp", "dell", "lenovo", "asus", "acer", "samsung", "sony", "realtek", "synaptics"]
    bloat_keywords = ["mcafee", "norton", "avast", "avg", "wildtangent", "cyberlink", "booking", "amazon"]
    gaming_keywords = ["steam", "epic", "discord", "obs", "razer", "logitech", "corsair", "steelseries"]

    for entry in entries:
        name = entry.get("Name", "")
        cmd = entry.get("Command", "")
        loc = entry.get("Location", "")
        user = entry.get("User", "")

        if not name:
            continue

        name_lower = name.lower()
        cmd_lower = cmd.lower()

        # Skip gaming software startup entries
        if any(g in name_lower for g in gaming_keywords) or any(g in cmd_lower for g in gaming_keywords):
            continue

        # Skip known essential startup
        if any(x in cmd_lower for x in ["security", "defender", "onedrive", "teams"]):
            continue

        # Determine if this is OEM bloat
        is_oem = any(o in name_lower for o in oem_keywords)
        is_bloat = any(b in name_lower for b in bloat_keywords) or any(b in cmd_lower for b in bloat_keywords)

        if is_oem or is_bloat:
            conf = 80 if is_bloat else 60
            risk = RiskLevel.SAFE if is_bloat else RiskLevel.OPTIONAL
            items.append(DebloatItem(
                id=f"startup_{name.replace(' ', '_').lower()[:50]}",
                name=f"{name} (Startup)",
                description=f"Starts automatically at login: {cmd[:80]}",
                what_happens="Removes this program from starting automatically at login.",
                category=DebloatCategory.STARTUP,
                risk=risk,
                confidence=conf,
                reversible=True,
                detected=True,
                remove_command=f"Remove-ItemProperty -Path '{loc}' -Name '{name}' -ErrorAction SilentlyContinue",
                verify_command=f"Get-CimInstance Win32_StartupCommand | Where-Object {{$_.Name -eq '{name}'}}",
                source="Startup Entry",
                version_found=f"User: {user}",
            ))

    return items

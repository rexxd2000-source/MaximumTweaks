"""Protected Components — application-focused protection database.

Everything here is either:
- A core Windows component that must never be disabled
- A driver-related component that hardware requires
- Gaming infrastructure that games and launchers depend on
- Security software that protects the system

The debloater will NEVER recommend removing protected items.
"""

from __future__ import annotations


# ── Core Windows Services ──────────────────────────────────────────
# Services that must NEVER be disabled. These are required by Windows,
# drivers, security, networking, or authentication.

PROTECTED_SERVICES: set[str] = {
    # Windows Core
    "WinDefend", "wuauserv", "BITS", "CryptSvc", "Dhcp", "Dnscache",
    "EventLog", "LSASS", "RpcSs", "SamSs", "PlugPlay", "Power",
    "Schedule", "Spooler", "Themes", "AudioSrv", "Audiosrv",
    # Security
    "SecurityHealthService", "Sense", "mpssvc", "BFE", "WdNisSvc", "WdFilter",
    "wscsvc", "WerSvc",
    # Networking
    "LanmanWorkstation", "LanmanServer", "Netman", "NlaSvc", "Wcmsvc",
    "WlanSvc", "WwanSvc", "Dot3svc", "iphlpsvc", "nsi", "netprofm",
    "WinHttpAutoProxySvc",
    # System
    "DcomLaunch", "RpcEptMapper", "TrkWks", "ProfSvc", "gpsvc", "AppInfo",
    "SysMain", "WSearch", "DPS", "WdiServiceHost", "WdiSystemHost", "DusmSvc",
    "BrokerInfrastructure", "SystemEventsBroker", "TimeBrokerSvc",
    # Storage/Devices
    "StorSvc", "CDPSvc", "CDPUserSvc", "DevicesFlowUserSvc",
    # Notifications
    "MessagingService", "WpnService", "WpnUserService",
    "PimIndexMaintenanceSvc", "UnistoreSvc", "UserDataSvc",
    # Update
    "UsoSvc", "WaaSMedicSvc", "InstallService", "TokenBroker",
    # Biometric
    "WbioSrvc",
    # Bluetooth
    "BthSvc", "bthserv", "BTAGService", "BthAvctpSvc",
    # Input
    "TabletInputService",
    # Diagnostics
    "PcaSvc", "ResourceBroker", "DsSvc", "Wecsvc",
    # Parental
    "WpcMonSvc",
}


# ── Services That Must Never Appear ────────────────────────────────
# These should never show up in ANY section of the debloater,
# not even as protected. They are completely excluded.

EXCLUDED_SERVICES: set[str] = {
    "WinDefend", "wuauserv", "BITS", "CryptSvc", "Dhcp", "Dnscache",
    "EventLog", "LSASS", "RpcSs", "SamSs", "PlugPlay", "Power",
    "Schedule", "Spooler", "AudioSrv", "Audiosrv",
    "SecurityHealthService", "mpssvc", "BFE", "WdNisSvc", "WdFilter",
    "wscsvc", "WerSvc", "DcomLaunch", "RpcEptMapper",
    "LanmanWorkstation", "LanmanServer", "Netman", "NlaSvc", "Wcmsvc",
    "WlanSvc", "WwanSvc", "Dot3svc", "iphlpsvc", "nsi", "netprofm",
    "WinHttpAutoProxySvc", "SysMain", "WSearch", "DPS",
    "BrokerInfrastructure", "SystemEventsBroker", "TimeBrokerSvc",
    "StorSvc", "CDPSvc", "CDPUserSvc", "DevicesFlowUserSvc",
    "WpnService", "WpnUserService", "ProfSvc", "gpsvc", "AppInfo",
    "UsoSvc", "WaaSMedicSvc", "InstallService", "TokenBroker",
    "WbioSrvc", "BthSvc", "bthserv", "BTAGService", "BthAvctpSvc",
    "PcaSvc", "Wecsvc", "TrkWks", "MessagingService",
    "PimIndexMaintenanceSvc", "UnistoreSvc", "UserDataSvc",
    "DusmSvc", "WpcMonSvc", "WdiServiceHost", "WdiSystemHost",
    "ResourceBroker", "DsSvc", "TabletInputService",
    # GPU driver services
    "NvContainerLocalSystem", "NvContainerNetworkService",
    "NvContainerSession", "NvTelemetryContainer",
    "AMD External Events Utility", "amdgpu", "amdfendr",
    # Audio driver services
    "Realtek Audio Service", "audiosrv",
    # Anti-cheat services
    "EasyAntiCheat", "BattlEye", "vgc", "vgk",
    # Game services
    "XblAuthManager", "XblGameSave", "XboxNetApiSvc", "XboxGipSvc",
}


# ── OEM Software Protection ────────────────────────────────────────
# OEM components that should NEVER be removed. These are driver-related
# or hardware control software.

PROTECTED_OEM: set[str] = {
    # NVIDIA — COMPLETELY EXCLUDED from debloater
    "NVIDIA", "GeForce", "NVENC", "NvContainer", "NVIDIA App",
    "NVIDIA Control Panel", "NVIDIA PhysX", "NVIDIA HD Audio",
    "NVIDIA ShadowPlay", "NVIDIA FrameView", "NVIDIA Telemetry",
    "NVIDIA Backend", "NVIDIA MessageBus", "NVIDIA Watchdog",
    "NVIDIA NvDLISR", "NVIDIA Virtual Audio", "NVIDIA Install",
    # AMD
    "AMD Radeon", "AMD Ryzen Master", "AMD Chipset", "AMD GPIO",
    "AMD PSP", "AMD PCI", "AMD Settings",
    # Intel
    "Intel Graphics", "Intel Management Engine", "Intel Rapid Storage",
    "Intel WiFi", "Intel Bluetooth", "Intel Chipset",
    # Audio/Input drivers
    "Realtek Audio", "Realtek Ethernet", "Realtek High Definition",
    "Synaptics", "ELAN Pointing",
    # Hardware control software
    "Logitech Gaming", "Razer", "Corsair", "SteelSeries",
    "HyperX", "Kingston",
}


# ── Gaming Software Detection ──────────────────────────────────────
# Patterns to detect gaming-related software. Gaming PCs should have
# their gaming infrastructure fully protected.

GAMING_SOFTWARE_PATTERNS: list[tuple[str, str]] = [
    ("Fortnite", "Fortnite"),
    ("Steam", "Steam"),
    ("Epic Games", "Epic Games Launcher"),
    ("Riot Client", "Riot Client"),
    ("Ubisoft Connect", "Ubisoft Connect"),
    ("EA App", "Electronic Arts"),
    ("Battle.net", "Blizzard"),
    ("Xbox", "Xbox"),
    ("Discord", "Discord"),
    ("OBS Studio", "OBS Studio"),
    ("GeForce Experience", "NVIDIA GeForce Experience"),
    ("NVIDIA App", "NVIDIA App"),
    ("AMD Software", "AMD Radeon Software"),
    ("EasyAntiCheat", "EasyAntiCheat"),
    ("BattlEye", "BattlEye"),
    ("Vanguard", "Vanguard"),
    ("Roblox", "Roblox"),
    ("Minecraft", "Minecraft"),
    ("GOG Galaxy", "GOG Galaxy"),
    ("itch.io", "itch.io"),
    ("Origin", "Origin"),
    ("Rockstar Games", "Rockstar Games Launcher"),
    ("Blizzard", "Blizzard"),
    ("Razer Cortex", "Razer Cortex"),
    ("Razer Synapse", "Razer Synapse"),
    ("Logitech G Hub", "Logitech G Hub"),
    ("SteelSeries GG", "SteelSeries GG"),
    ("Corsair iCUE", "Corsair iCUE"),
]


# ── Software Dependencies ──────────────────────────────────────────
# Maps installed software to the services/features they require.
# If software A needs service B, then service B is protected.

KNOWN_DEPENDENCIES: dict[str, dict] = {
    "Fortnite": {
        "required_services": {"XblAuthManager", "XblGameSave", "XboxNetApiSvc", "XboxGipSvc"},
        "description": "Epic Games' battle royale game",
    },
    "Steam": {
        "required_services": {"Steam Client Service"},
        "description": "Valve's game distribution platform",
    },
    "Epic Games Launcher": {
        "required_services": set(),
        "description": "Epic Games store and launcher",
    },
    "Riot Client": {
        "required_services": set(),
        "description": "Riot Games launcher (Valorant, League of Legends)",
    },
    "Ubisoft Connect": {
        "required_services": set(),
        "description": "Ubisoft game launcher",
    },
    "EA App": {
        "required_services": set(),
        "description": "Electronic Arts game launcher",
    },
    "Battle.net": {
        "required_services": set(),
        "description": "Blizzard game launcher",
    },
    "Xbox": {
        "required_services": {"XblAuthManager", "XblGameSave", "XboxNetApiSvc", "XboxGipSvc"},
        "description": "Xbox app and gaming services",
    },
    "Discord": {
        "required_services": set(),
        "description": "Voice and text communication",
    },
    "Zoom": {
        "required_services": set(),
        "description": "Video conferencing",
    },
    "Microsoft Teams": {
        "required_services": set(),
        "description": "Team collaboration",
    },
    "OBS Studio": {
        "required_services": set(),
        "description": "Screen recording and streaming",
    },
    "Adobe": {
        "required_services": set(),
        "description": "Adobe creative applications",
    },
    "Visual Studio": {
        "required_services": set(),
        "description": "Microsoft development environment",
    },
    "Docker": {
        "required_services": set(),
        "description": "Containerization platform",
    },
    "VMware": {
        "required_services": set(),
        "description": "Virtualization software",
    },
    "VirtualBox": {
        "required_services": set(),
        "description": "Virtualization software",
    },
    "NordVPN": {
        "required_services": set(),
        "description": "VPN client",
    },
    "ExpressVPN": {
        "required_services": set(),
        "description": "VPN client",
    },
    "Microsoft Office": {
        "required_services": set(),
        "description": "Office productivity suite",
    },
    "OneDrive": {
        "required_services": set(),
        "description": "Cloud storage",
    },
    "EasyAntiCheat": {
        "required_services": set(),
        "description": "Epic's anti-cheat system",
    },
    "BattlEye": {
        "required_services": set(),
        "description": "Anti-cheat system",
    },
    "Vanguard": {
        "required_services": set(),
        "description": "Riot's anti-cheat system (Valorant)",
    },
}


# ── Third-Party Bloatware Patterns ─────────────────────────────────
# Known bloatware patterns to flag during third-party app detection.

BLOATWARE_PATTERNS: dict[str, tuple[str, str, int]] = {
    # name_pattern: (display_name, description, confidence)
    "McAfee": ("McAfee Antivirus", "Pre-installed trial antivirus — often bundled with new PCs", 85),
    "Norton": ("Norton Antivirus", "Pre-installed trial antivirus — often bundled with new PCs", 85),
    "Avast": ("Avast Antivirus", "Free antivirus with optional trial", 70),
    "AVG": ("AVG Antivirus", "Free antivirus with optional trial", 70),
    "CyberLink": ("CyberLink Media Suite", "Bundled media software — rarely needed", 80),
    "WildTangent": ("WildTangent Games", "Bundled game launcher — often preinstalled on OEM PCs", 90),
    "Booking.com": ("Booking.com", "Pre-installed travel booking app", 90),
    "Amazon": ("Amazon App", "Pre-installed shopping app", 85),
    "Candy Crush": ("Candy Crush Saga", "Pre-installed game", 95),
    "Disney Magic": ("Disney Magic Kingdoms", "Pre-installed game", 95),
    "FarmVille": ("FarmVille", "Pre-installed game", 95),
    "Spotify": ("Spotify", "Music streaming app", 0),
    "tunein": ("TuneIn Radio", "Pre-installed radio app", 80),
    "Roblox": ("Roblox", "Game platform", 0),
    "Clipchamp": ("Clipchamp", "Microsoft video editor — can be reinstalled from Store", 75),
}


# ── Intentionally Installed Software ───────────────────────────────
# Software that is normally intentionally installed and should NOT
# be classified as bloat.

INTENTIONAL_SOFTWARE: set[str] = {
    "Discord", "OBS Studio", "Steam", "Epic Games", "Riot Client",
    "Ubisoft Connect", "EA App", "Battle.net", "Blizzard",
    "Visual Studio", "Visual Studio Code", "VS Code",
    "Docker", "VMware", "VirtualBox",
    "NordVPN", "ExpressVPN", "Mullvad VPN",
    "Microsoft Office", "OneDrive", "Teams",
    "Spotify", "VLC", "foobar2000", "Audacity",
    "Photoshop", "Illustrator", "Premiere", "After Effects",
    "Blender", "GIMP", "Inkscape",
    "Chrome", "Firefox", "Brave", "Opera", "Vivaldi",
    "7-Zip", "WinRAR", "Notepad++",
    "Git", "GitHub Desktop", "SourceTree",
    "Node.js", "Python", "Java", "Ruby",
    "PuTTY", "WinSCP", "FileZilla",
    "ShareX", "Greenshot", "LightShot",
    "MSI Afterburner", "HWiNFO", "HWMonitor",
    "RivaTuner", "CPU-Z", "GPU-Z",
    "Logitech G Hub", "Razer Synapse", "Corsair iCUE",
    "SteelSeries GG", "HyperX NGENUITY",
    "BlueStacks", "LDPlayer", "NoxPlayer",
}


# ── Protected AppX Packages ────────────────────────────────────────
# AppX packages that should NEVER be removed. These are core Windows
# components required by the system.

PROTECTED_APPX: set[str] = {
    # Core Windows
    "Microsoft.WindowsStore", "Microsoft.WindowsTerminal",
    "Microsoft.Windows.Photos", "Microsoft.WindowsClipEditor",
    "Microsoft.ScreenSketch", "Microsoft.WindowsCalculator",
    "Microsoft.WindowsCamera", "Microsoft.WindowsNotepad",
    "Microsoft.WindowsAlarms", "Microsoft.WindowsSoundRecorder",
    "Microsoft.WindowsFaxAndScan",
    # System infrastructure
    "Microsoft.WindowsShellExperienceHost",
    "Microsoft.Windows.StartMenuExperienceHost",
    "Microsoft.Windows.CloudExperienceHost",
    "Microsoft.Windows.ContentDeliveryManager",
    "Microsoft.Windows.SecHealthUI",
    "Microsoft.WindowsSecurity",
    "Microsoft.WindowsOOBE",
    "Microsoft.WindowsSubsystemForLinux",
    "Microsoft.DesktopAppInstaller",
    # Xbox core (protected — games depend on these)
    "Microsoft.Xbox.TCUI",
    "Microsoft.XboxIdentityProvider",
    "Microsoft.XboxGameCallableUI",
    # UI/Framework
    "Microsoft.UI.Xaml", "Microsoft.Windows.UI.Xaml",
    "Microsoft.AsyncTextService", "Microsoft.InputApp",
    # Media codecs
    "Microsoft.HEIFImageExtension", "Microsoft.RawImageExtension",
    "Microsoft.WebpImageExtension", "Microsoft.WebMediaExtensions",
    # Identity
    "Microsoft.AAD.BrokerPlugin", "Microsoft.AccountsControl",
    "Microsoft.CredDialogHost", "Microsoft.CapturePicker",
    "Microsoft.BioEnrollment", "Microsoft.LockApp",
    # Search
    "Microsoft.Search",
}


# ── OEM Software Patterns ──────────────────────────────────────────
# Known OEM bloat patterns for detection.

KNOWN_OEM_BLOAT: dict[str, tuple[str, str, int]] = {
    "HP Support Assistant": ("HP Support Assistant", "HP system management and update tool", 75),
    "HP Sure Click": ("HP Sure Click", "HP security isolation browser", 80),
    "HP Smart": ("HP Smart", "HP printer management app", 0),
    "My HP": ("My HP", "HP system dashboard", 75),
    "HP Privacy Settings": ("HP Privacy Settings", "HP privacy and data collection settings", 85),
    "Dell Digital Delivery": ("Dell Digital Delivery", "Delivers Dell digital purchases", 85),
    "Dell SupportAssist": ("Dell SupportAssist", "Dell system diagnostics", 75),
    "Dell Power Manager": ("Dell Power Manager", "Dell battery and power management", 50),
    "Lenovo Vantage": ("Lenovo Vantage", "Lenovo system settings and updates", 70),
    "Lenovo System Update": ("Lenovo System Update", "Lenovo driver updater", 60),
    "Lenovo Commercial Vantage": ("Lenovo Commercial Vantage", "Enterprise Lenovo management", 70),
}


# ── OEM Publishers ─────────────────────────────────────────────────
# Publishers that are considered OEM for detection purposes.
# NVIDIA, AMD, Intel are EXCLUDED — they are protected, not debloatable.

OEM_PUBLISHERS: set[str] = {
    "HP Inc.", "Hewlett-Packard", "HP",
    "Dell Inc.", "Dell",
    "Lenovo",
    "ASUSTeK Computer", "ASUS",
    "Acer Incorporated", "Acer",
    "Samsung Electronics", "Samsung",
    "Sony Corporation", "Sony",
    "Toshiba",
    "Realtek Semiconductor",
    "Synaptics Incorporated", "Synaptics",
    "Broadcom", "Qualcomm",
}


# ── Runtime/Framework Packages ─────────────────────────────────────
# These are never debloatable — they are runtimes, frameworks, or
# driver components that applications depend on.

RUNTIME_PATTERNS: set[str] = {
    "Microsoft Visual C++", "Microsoft .NET", "Microsoft VC++",
    "Microsoft Windows Desktop Runtime", "Microsoft ASP.NET",
    "Microsoft DirectX", "Microsoft Edge", "Microsoft OneDrive",
    "Microsoft Teams", "Microsoft Office", "Microsoft SQL",
    "Microsoft Silverlight", "Microsoft WSE", "Microsoft WCF",
    "Microsoft .NET Framework", "Microsoft .NET Runtime",
    "Redistributable", "Runtime", "Framework",
    "Qualcomm", "Realtek", "Synaptics",
}

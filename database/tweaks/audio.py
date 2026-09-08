"""Category: Audio — deep Windows audio stack optimizations.

Covers: Audio Engine, WASAPI, MMCSS audio scheduling, audio endpoint
configuration, USB/Bluetooth/HDMI audio power management, device-specific
settings (Realtek, DACs), microphone configuration, spatial audio,
communication ducking, audio enhancements, and gaming audio presets.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Audio", win_default="7,8,10,11")
CATEGORY = "Audio"

TWEAKS = validate_module("audio", [
    # =====================================================================
    #  SECTION 1 — AUDIO SERVICES & CORE ENGINE
    # =====================================================================

    T("audio-001", "Mute System Startup Sound",
      "Disables the Windows startup chime.",
      actions=[("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemStart\.Default", "", "", "STRING")],
      revert=[("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemStart\.Default", "", "startup", "STRING")],
      why="Removes the chime and its audio initialization burst on every boot.",
      changes="Mutes the startup sound.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["sound", "startup", "chime"]),

    T("audio-002", "Mute Notification Sounds",
      "Silences default notification sounds.",
      actions=[("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\Notification.Default\.Default", "", "", "STRING")],
      revert=[("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\Notification.Default\.Default", "", r"%SystemRoot%\Media\Windows Notify System Generic.wav", "EXPAND_STRING")],
      why="Removes audio pipeline work and distractions from background notifications.",
      changes="Clears the default notification sound file.",
      risk="safe", impact="low", recommended="recommended",
      tags=["sound", "notifications", "mute"]),

    T("audio-003", "High Priority Audio MMCSS Task",
      "Raises the MMCSS 'Audio' class scheduling priority.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "Priority", 4, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "Priority", 2, "DWORD")],
      why="Higher audio thread priority reduces audio processing jitter.",
      changes="Sets Audio task priority to 4.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["mmcss", "audio", "priority"]),

    T("audio-004", "High Priority Playback MMCSS Task",
      "Raises the MMCSS 'Playback' class scheduling priority.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback", "Priority", 4, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback", "Priority", 2, "DWORD")],
      why="Keeps audio playback threads responsive under CPU load.",
      changes="Sets Playback task priority to 4.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["mmcss", "playback", "priority"]),

    T("audio-005", "Audio Services Automatic",
      "Sets the Windows Audio and AudioEndpointBuilder services to automatic.",
      actions=[
          ("svc", "AudioSrv", "auto"),
          ("svc", "AudioEndpointBuilder", "auto"),
      ],
      revert=[
          ("svc", "AudioSrv", "manual"),
          ("svc", "AudioEndpointBuilder", "manual"),
      ],
      why="Ensures the audio stack is fully initialized before games launch.",
      changes="Sets audio services to automatic startup.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["audio", "service", "startup"]),

    T("audio-013", "Disable System Sounds",
      "Turns off the default Windows system sound scheme.",
      actions=[("reg", "HKCU", r"AppEvents\Schemes\.Default\.None", "", ".None", "STRING")],
      revert=[("reg", "HKCU", r"AppEvents\Schemes\.Default\.None", "", "(Default)", "STRING")],
      why="Prevents unexpected audio interruptions during gameplay from system notifications.",
      changes="Sets the default system sound to .None (silent).",
      risk="safe", impact="very low", recommended="optional",
      tags=["sound", "audio", "notifications"]),

    T("audio-014", "Disable Windows Error Sounds",
      "Silences Windows error, critical stop and default beep sounds.",
      actions=[
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\.Default\.Default", "", "", "STRING"),
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemHand\.Default", "", "", "STRING"),
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemExclamation\.Default", "", "", "STRING"),
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemAsterisk\.Default", "", "", "STRING"),
      ],
      revert=[
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\.Default\.Default", "", r"%SystemRoot%\Media\Windows Ding.wav", "EXPAND_STRING"),
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemHand\.Default", "", r"%SystemRoot%\Media\Windows Critical Stop.wav", "EXPAND_STRING"),
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemExclamation\.Default", "", r"%SystemRoot%\Media\Windows Exclamation.wav", "EXPAND_STRING"),
          ("reg", "HKCU", r"AppEvents\Schemes\Apps\.Default\SystemAsterisk\.Default", "", r"%SystemRoot%\Media\Windows Background.wav", "EXPAND_STRING"),
      ],
      why="Error sounds cause unexpected audio focus switches that can interrupt game audio or voice chat.",
      changes="Mutes all Windows error and default beep sounds.",
      risk="safe", impact="low", recommended="optional",
      tags=["sound", "error", "beep", "mute"]),

    T("audio-015", "Audio Service Recovery on Failure",
      "Configures the Windows Audio service to auto-restart on failure.",
      actions=[
          ("cmd", 'powershell -NoProfile -Command "sc.exe failure AudioSrv reset= 86400 actions= restart/5000/restart/10000/restart/20000"'),
          ("cmd", 'powershell -NoProfile -Command "sc.exe failure AudioEndpointBuilder reset= 86400 actions= restart/5000/restart/10000/restart/20000"'),
      ],
      revert=[
          ("cmd", 'powershell -NoProfile -Command "sc.exe failure AudioSrv reset= 0 actions= ""'),
          ("cmd", 'powershell -NoProfile -Command "sc.exe failure AudioEndpointBuilder reset= 0 actions= ""'),
      ],
      why="If the audio service crashes (e.g. from a bad driver), auto-recovery prevents permanent audio loss until reboot.",
      changes="Sets audio services to restart automatically on failure.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["audio", "service", "recovery"]),

    # =====================================================================
    #  SECTION 2 — SPATIAL AUDIO & ENHANCEMENTS
    # =====================================================================

    T("audio-006", "Disable Spatial Audio",
      "Disables Windows Sonic spatial audio via registry.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Audio", "SpatialDisable", 1, "DWORD")],
      revert=[("regdel", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Audio", "SpatialDisable")],
      why="Spatial audio processing adds overhead; most competitive players prefer raw stereo.",
      changes="Disables spatial sound processing.",
      risk="safe", impact="low", recommended="recommended",
      tags=["spatial", "sonic", "audio"]),

    T("audio-008", "Disable Audio Enhancements",
      "Disables all audio DSP enhancements via registry.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Audio", "DisableEnhancements", 1, "DWORD")],
      revert=[("regdel", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Audio", "DisableEnhancements")],
      why="DSP effects add buffering between the game and your ears.",
      changes="Disables audio enhancements system-wide.",
      risk="safe", impact="low", recommended="recommended",
      tags=["enhancements", "dsp", "audio"]),

    T("audio-016", "Disable Audio Processing Objects (APO)",
      "Disables per-device Audio Processing Objects (APO) for the default render endpoint.",
      actions=[
          ("cmd", 'powershell -NoProfile -Command "$dev = Get-AudioDevice -List | Where-Object {$_.Default} | Select-Object -First 1; if ($dev) { Set-ItemProperty -Path \'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\Render\' -Name \'DisableAPO\' -Value 1 -ErrorAction SilentlyContinue }"'),
      ],
      revert=[
          ("cmd", 'powershell -NoProfile -Command "Remove-ItemProperty -Path \'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\Render\' -Name \'DisableAPO\' -ErrorAction SilentlyContinue"'),
      ],
      why="APO drivers (equalizers, virtualizers, bass boost) add latency to the audio pipeline. Disabling them gives a cleaner path from game to speakers.",
      changes="Disables audio processing objects on the default render device.",
      risk="low", impact="low", recommended="optional", admin=True,
      tags=["apo", "dsp", "enhancements", "audio"]),

    # =====================================================================
    #  SECTION 3 — EXCLUSIVE MODE & WASAPI
    # =====================================================================

    T("audio-007", "Enable Exclusive Mode",
      "Enables audio exclusive mode for lower latency via registry.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "ExclusiveMode", 1, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "AllowExclusiveMode", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "ExclusiveMode", 0, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "AllowExclusiveMode", 0, "DWORD"),
      ],
      why="Exclusive mode skips the shared-mode mixer, cutting audio latency.",
      changes="Enables exclusive mode and exclusive mode priority for audio devices.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["exclusive", "latency", "audio"]),

    T("audio-017", "Disable Exclusive Mode Application Launch",
      "Prevents applications from hijacking the audio device in exclusive mode.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "LaunchAppsInExclusiveMode", 0, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "LaunchAppsInExclusiveMode", 1, "DWORD")],
      why="Some applications take exclusive control of the audio device, preventing other apps from playing sound. Disabling this keeps audio sharing reliable.",
      changes="Prevents apps from launching in exclusive mode.",
      risk="safe", impact="low", recommended="optional",
      tags=["exclusive", "wasapi", "audio"]),

    # =====================================================================
    #  SECTION 4 — DEFAULT AUDIO FORMAT
    # =====================================================================

    T("audio-009", "Set 48 kHz Default Format",
      "Guidance to set the audio format to 48 kHz.",
      actions=[("guidance", "In Sound > device Properties > Advanced set the default format to 48 kHz (or your headset's native rate). Avoid higher rates that force unnecessary resampling.")],
      revert=[("guidance", "Restore the previous format.")],
      why="48 kHz matches most game audio content, avoiding resampling work.",
      changes="Shows default-format guidance.",
      risk="safe", impact="low", recommended="recommended",
      tags=["format", "khz", "resample"]),

    T("audio-018", "Disable Audio Resampling Quality Boost",
      "Sets the Windows audio resampler to basic quality to reduce latency.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Audio", "ResamplerQuality", 1, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Audio", "ResamplerQuality", 4, "DWORD")],
      why="Higher resampler quality uses more CPU and adds latency; basic quality is sufficient for game audio.",
      changes="Sets audio resampler quality to basic.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["resampler", "quality", "latency", "audio"]),

    # =====================================================================
    #  SECTION 5 — COMMUNICATION / DUCKING
    # =====================================================================

    T("audio-019", "Disable Communication Ducking",
      "Prevents Windows from automatically reducing volume when it detects communications activity.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\Communications", "AutoMode", 0, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\Communications", "AutoMode", 2, "DWORD")],
      why="Windows defaults to reducing other sounds by 80% during voice calls. Gamers and streamers need consistent audio levels regardless of communication activity.",
      changes="Sets communication activity handling to 'Do nothing'.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["ducking", "communications", "volume", "audio"]),

    T("audio-020", "Disable Volume Auto-Limiting",
      "Prevents Windows from automatically capping peak volume.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "AutoVolumeLeveling", 0, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "AutoVolumeLeveling", 1, "DWORD")],
      why="Auto volume leveling compresses dynamic range; disabling it preserves the original audio dynamics from games.",
      changes="Disables automatic volume leveling.",
      risk="safe", impact="low", recommended="optional",
      tags=["volume", "leveling", "dynamics", "audio"]),

    # =====================================================================
    #  SECTION 6 — USB AUDIO
    # =====================================================================

    T("audio-010", "Disable Audio Device Power Savings",
      "Prevents audio devices from entering power-saving mode via registry.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Enum\USB\*\*\Device Parameters\WDF", "DeviceSelectiveSuspended", 0, "DWORD")],
      revert=[("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Enum\USB\*\*\Device Parameters\WDF", "DeviceSelectiveSuspended")],
      why="Audio devices that sleep cause the first-sound-after-idle crackle.",
      changes="Disables selective suspend on USB audio devices.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["power", "sleep", "audio"]),

    T("audio-021", "Disable USB Enhanced Power Management",
      "Disables Enhanced Power Management on USB audio endpoints.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Enum\USB\*\*\Device Parameters", "EnhancedPowerManagementEnabled", 0, "DWORD")],
      revert=[("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Enum\USB\*\*\Device Parameters", "EnhancedPowerManagementEnabled")],
      why="Enhanced Power Management allows USB audio devices to enter deep sleep states, causing pop/click artifacts when waking.",
      changes="Disables enhanced power management on USB audio endpoints.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["usb", "power", "sleep", "audio"]),

    T("audio-022", "Disable USB Audio Remote Wakeup",
      "Prevents USB audio devices from waking the system.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Enum\USB\*\*\Device Parameters\WDF", "SystemWakeEnabled", 0, "DWORD")],
      revert=[("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Enum\USB\*\*\Device Parameters\WDF", "SystemWakeEnabled")],
      why="USB audio devices can trigger spurious wakeups, disrupting sleep/hibernate and causing audio stack re-initialization.",
      changes="Disables remote wakeup on USB audio devices.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["usb", "wake", "power", "audio"]),

    # =====================================================================
    #  SECTION 7 — MMCSS AUDIO SCHEDULING (DEEP)
    # =====================================================================

    T("audio-023", "Audio MMCSS Scheduling Category",
      "Sets the Audio MMCSS task to High scheduling category.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "Scheduling Category", "High", "STRING"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "Latency", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "Scheduling Category", "Medium", "STRING"),
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "Latency"),
      ],
      why="The MMCSS scheduling category determines how aggressively the thread scheduler services audio deadlines. High ensures audio threads get scheduled ahead of background work.",
      changes="Sets Audio MMCSS to High scheduling category with latency flag.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["mmcss", "audio", "scheduling", "priority"]),

    T("audio-024", "Playback MMCSS Scheduling Category",
      "Sets the Playback MMCSS task to High scheduling category.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback", "Scheduling Category", "High", "STRING"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback", "Latency", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback", "Scheduling Category", "Medium", "STRING"),
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Playback", "Latency"),
      ],
      why="The Playback MMCSS class handles audio output threads. High scheduling category keeps them responsive under CPU load.",
      changes="Sets Playback MMCSS to High scheduling category with latency flag.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["mmcss", "playback", "scheduling", "priority"]),

    T("audio-025", "Audio MMCSS GPU Priority",
      "Raises the GPU priority for the Audio MMCSS task.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "GPU Priority", 8, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Audio", "GPU Priority", 0, "DWORD")],
      why="Audio processing threads that involve GPU-accelerated DSP (e.g. spatial audio, game mixers) benefit from higher GPU scheduling priority.",
      changes="Sets Audio MMCSS GPU Priority to 8.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["mmcss", "audio", "gpu", "priority"]),

    # =====================================================================
    #  SECTION 8 — DEVICE-SPECIFIC
    # =====================================================================

    T("audio-026", "Disable Realtek Audio DSP",
      "Disables Realtek audio processing effects.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Realtek\Audio\APO", "DisableAPO", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SOFTWARE\Realtek\Audio\APO", "DisableAPO", 0, "DWORD"),
      ],
      why="Realtek audio drivers install their own DSP effects (equalizer, virtualizer, bass boost) that add latency to the audio pipeline.",
      changes="Disables Realtek audio processing objects.",
      risk="low", impact="low", recommended="optional", admin=True,
      tags=["realtek", "dsp", "apo", "audio"],
      when={"audio_realtek": True}),

    T("audio-027", "Disable Realtek Signal Enhancement",
      "Disables the Realtek signal enhancement feature.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Realtek\Audio\APO", "DisableSignalEnhance", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SOFTWARE\Realtek\Audio\APO", "DisableSignalEnhance", 0, "DWORD"),
      ],
      why="Signal enhancement applies additional processing to the audio output; disabling it gives a cleaner audio path.",
      changes="Disables Realtek signal enhancement.",
      risk="low", impact="low", recommended="optional", admin=True,
      tags=["realtek", "signal", "enhancement", "audio"],
      when={"audio_realtek": True}),

    # =====================================================================
    #  SECTION 9 — BLUETOOTH AUDIO
    # =====================================================================

    T("audio-028", "Disable Bluetooth Hands-Free Profile",
      "Disables the Bluetooth HFP (hands-free) audio profile to prefer A2DP.",
      actions=[
          ("cmd", 'powershell -NoProfile -Command "Get-ItemProperty -Path \'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\bluetooth\' -ErrorAction SilentlyContinue | Out-Null; Set-ItemProperty -Path \'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\BthHFEnum\' -Name \'Start\' -Value 4 -Type DWord -ErrorAction SilentlyContinue"'),
      ],
      revert=[
          ("cmd", 'powershell -NoProfile -Command "Set-ItemProperty -Path \'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\BthHFEnum\' -Name \'Start\' -Value 3 -Type DWord -ErrorAction SilentlyContinue"'),
      ],
      why="Bluetooth HFP switches audio to a lower-quality voice codec when the mic is active. Disabling HFP keeps high-quality A2DP streaming even during voice chat.",
      changes="Disables Bluetooth hands-free audio profile.",
      risk="low", impact="moderate", recommended="optional", admin=True,
      tags=["bluetooth", "hfp", "a2dp", "codec", "audio"],
      when={"audio_bluetooth": True}),

    # =====================================================================
    #  SECTION 10 — MICROPHONE
    # =====================================================================

    T("audio-030", "Disable Microphone Exclusive Mode",
      "Prevents applications from taking exclusive control of the microphone.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "MicExclusiveMode", 0, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\DevicePreferences", "MicExclusiveMode", 1, "DWORD")],
      why="Exclusive microphone access prevents other apps (Discord, game chat) from sharing the mic simultaneously.",
      changes="Disables microphone exclusive mode.",
      risk="safe", impact="low", recommended="recommended",
      tags=["microphone", "exclusive", "sharing", "audio"]),

    T("audio-031", "Disable Microphone Boost",
      "Guidance to disable the +20dB microphone boost level.",
      actions=[("guidance", "Open Sound Settings > Input > Device Properties > Levels. If Microphone Boost is enabled (+10dB, +20dB, +30dB), reduce it to 0dB or the lowest setting. Boost amplifies background noise along with your voice.")],
      revert=[("guidance", "Restore the previous boost level.")],
      why="Microphone boost amplifies background noise along with the voice signal. A clean signal with proper gain staging produces clearer voice chat.",
      changes="Shows microphone boost guidance.",
      risk="safe", impact="low", recommended="optional",
      tags=["microphone", "boost", "noise", "voice"]),

    T("audio-032", "Disable Microphone Processing",
      "Disables Windows automatic microphone processing (noise suppression, echo cancellation).",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\MicProcessing", "NoiseSuppression", 0, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\MicProcessing", "AEC", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\MicProcessing", "NoiseSuppression", 1, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Multimedia\Audio\MicProcessing", "AEC", 1, "DWORD"),
      ],
      why="Windows audio processing adds latency to the microphone input. Games and Discord have their own processing, so double-processing degrades voice quality.",
      changes="Disables Windows microphone noise suppression and echo cancellation.",
      risk="safe", impact="low", recommended="recommended",
      tags=["microphone", "processing", "aec", "noise", "audio"]),

    # =====================================================================
    #  SECTION 11 — AUDIO DEVICE MANAGEMENT
    # =====================================================================

    T("audio-033", "Audio Device Report",
      "Lists all audio devices and their current status.",
      actions=[("cmd", "powershell -NoProfile -Command \"Get-CimInstance Win32_SoundDevice | Format-Table Name,Status,Manufacturer -AutoSize\"")],
      revert=[("guidance", "Read-only report.")],
      why="Confirms your intended device is the default and error-free.",
      changes="Shows the audio device report.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["report", "device", "audio"]),

    T("audio-034", "Audio Endpoint Report",
      "Lists all audio render and capture endpoints with their formats.",
      actions=[("cmd", 'powershell -NoProfile -Command "Get-PnpDevice -Class Media | Select-Object FriendlyName,Status,Class | Format-Table -AutoSize"')],
      revert=[("guidance", "Read-only report.")],
      why="Shows all available audio endpoints, their connection type, and driver status to identify issues.",
      changes="Shows the audio endpoint report.",
      risk="safe", impact="very low", recommended="optional",
      tags=["report", "endpoint", "pnp", "audio"]),

    # =====================================================================
    #  SECTION 12 — LAPTOP AUDIO
    # =====================================================================

    T("audio-035", "Disable Audio Power Management (Laptop)",
      "Prevents Windows from powering down audio devices to save battery on laptops.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power\PowerSettings\238C9FA8-0AAD-41ED-83F4-97BE242C8F20\94AC6D29-73CE-41A6-809F-6363BA21B47E", "Attributes", 2, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power\PowerSettings\238C9FA8-0AAD-41ED-83F4-97BE242C8F20\94AC6D29-73CE-41A6-809F-6363BA21B47E", "Attributes", 1, "DWORD"),
      ],
      why="Laptop power management aggressively suspends audio devices to save battery, causing crackle and pops when audio resumes.",
      changes="Exposes the audio power management setting in Power Options.",
      risk="low", impact="low", recommended="optional", admin=True,
      tags=["laptop", "power", "battery", "audio"],
      when={"laptop": True}),

    T("audio-036", "Disable Audio Endpoint Auto-Scaling",
      "Prevents Windows from dynamically adjusting audio buffer sizes on laptops.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio", "EnableBufferManagement", 0, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio", "EnableBufferManagement", 1, "DWORD")],
      why="Dynamic buffer scaling can cause audio glitches when switching between battery and AC power.",
      changes="Disables audio endpoint auto-scaling.",
      risk="low", impact="low", recommended="optional", admin=True,
      tags=["laptop", "buffer", "scaling", "audio"],
      when={"laptop": True}),

    # =====================================================================
    #  SECTION 13 — LATENCY MONITORING
    # =====================================================================

    T("audio-037", "LatencyMon DPC Guidance",
      "Guidance on measuring DPC latency that affects audio.",
      actions=[("guidance", "Install LatencyMon, let it run 5 minutes while a game is open, and check the 'Interrupt to process latency' values. Green = drivers healthy.")],
      revert=[("guidance", "Close LatencyMon.")],
      why="DPC spikes from bad drivers manifest as audio crackle and stutter. LatencyMon identifies the offending driver.",
      changes="Shows LatencyMon guidance.",
      risk="safe", impact="low", recommended="recommended",
      tags=["latencymon", "dpc", "audio"]),

    # =====================================================================
    #  SECTION 14 — AUDIO PRESETS (GUIDANCE)
    # =====================================================================

    T("audio-038", "Gaming Audio Preset",
      "Optimizes audio for competitive gaming: disable ducking, enhancements, spatial audio, and set high MMCSS priority.",
      actions=[("guidance", "Apply these tweaks for gaming: Enable Exclusive Mode, Disable Audio Enhancements, Disable Spatial Audio, Disable Communication Ducking, High MMCSS Audio Priority, Audio Services Automatic. These prevent audio interruptions, reduce latency, and keep game audio consistent.")],
      revert=[("guidance", "Revert individual tweaks as needed.")],
      why="Gaming audio needs low latency, no ducking interruptions, and consistent delivery.",
      changes="Shows gaming audio preset guidance.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["gaming", "preset", "competitive", "audio"]),

    T("audio-039", "Voice Chat Preset",
      "Optimizes audio for voice chat: disable mic processing, mic exclusive mode, and communication ducking.",
      actions=[("guidance", "For voice chat: Disable Microphone Exclusive Mode, Disable Microphone Processing, Disable Communication Ducking, keep Audio Services Automatic. These let Discord/game chat share the mic cleanly without Windows interference.")],
      revert=[("guidance", "Revert individual tweaks as needed.")],
      why="Voice chat needs reliable microphone sharing and no ducking.",
      changes="Shows voice chat preset guidance.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["voice", "chat", "discord", "preset", "audio"]),

    T("audio-040", "USB Headset Preset",
      "Optimizes audio for USB headsets: disable USB power savings, disable enhancements, set exclusive mode.",
      actions=[("guidance", "For USB headsets: Disable Audio Device Power Savings, Disable USB Enhanced Power Management, Disable Audio Enhancements, Enable Exclusive Mode, Disable Spatial Audio. These prevent USB sleep issues and reduce latency.")],
      revert=[("guidance", "Revert individual tweaks as needed.")],
      why="USB headsets are prone to power-management issues that cause pops and disconnects.",
      changes="Shows USB headset preset guidance.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["usb", "headset", "preset", "audio"]),

    T("audio-041", "DAC / Audio Interface Preset",
      "Optimizes audio for external DACs and audio interfaces.",
      actions=[("guidance", "For external DACs/audio interfaces: Disable Audio Enhancements, Disable APO, Disable Spatial Audio, Enable Exclusive Mode, Set 48kHz Format. External DACs handle their own DSP — Windows processing is redundant and adds latency.")],
      revert=[("guidance", "Revert individual tweaks as needed.")],
      why="External DACs and audio interfaces have their own processing; Windows DSP is redundant.",
      changes="Shows DAC/audio interface preset guidance.",
      risk="safe", impact="moderate", recommended="optional",
      tags=["dac", "interface", "pro-audio", "preset", "audio"]),
])

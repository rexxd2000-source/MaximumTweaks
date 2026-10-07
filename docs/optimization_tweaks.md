# Optimization tweaks (applyable only)

Total: 515 entries. Diagnostics and System Tools are excluded.

| # | ID | Name | Category | Tier | Class | Description |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `adv-003` | Disable Insecure Guest Fallback | Advanced | performance | FOUNDATION | Disables SMB guest fallback. |
| 2 | `adv-006` | Set Processor Scheduling to Programs | Advanced | foundation | FREE | Prioritizes programs over background services. |
| 3 | `adv-007` | Disable Credential Manager | Advanced | maximum | MAXIMUM | Disables the credential manager service. |
| 4 | `adv-008` | Disable Print Job History | Advanced | foundation | FREE | Disables print job history tracking via registry. |
| 5 | `adv-009` | Disable Font Cache Service | Advanced | performance | FOUNDATION | Disables the font cache service. |
| 6 | `adv-015` | Optimize BCD Boot Settings | Advanced | performance | FOUNDATION | Sets the boot menu policy to standard for faster boots. |
| 7 | `aim-002` | Remove QoS Bandwidth Reservation | Aim | performance | FOUNDATION | Sets the QoS NonBestEffortLimit to 0 so Windows stops reserving ~20% of network bandwidth. |
| 8 | `audio-001` | Mute System Startup Sound | Audio | foundation | FREE | Disables the Windows startup chime. |
| 9 | `audio-002` | Mute Notification Sounds | Audio | foundation | FREE | Silences default notification sounds. |
| 10 | `audio-003` | High Priority Audio MMCSS Task | Audio | performance | FOUNDATION | Raises the MMCSS 'Audio' class scheduling priority. |
| 11 | `audio-004` | High Priority Playback MMCSS Task | Audio | performance | FOUNDATION | Raises the MMCSS 'Playback' class scheduling priority. |
| 12 | `audio-005` | Audio Services Automatic | Audio | foundation | FREE | Sets the Windows Audio and AudioEndpointBuilder services to automatic. |
| 13 | `audio-006` | Disable Spatial Audio | Audio | foundation | FREE | Disables Windows Sonic spatial audio via registry. |
| 14 | `audio-007` | Enable Exclusive Mode | Audio | foundation | FREE | Enables audio exclusive mode for lower latency via registry. |
| 15 | `audio-008` | Disable Audio Enhancements | Audio | foundation | FREE | Disables all audio DSP enhancements via registry. |
| 16 | `audio-013` | Disable System Sounds | Audio | foundation | FREE | Turns off the default Windows system sound scheme. |
| 17 | `audio-014` | Disable Windows Error Sounds | Audio | foundation | FREE | Silences Windows error, critical stop and default beep sounds. |
| 18 | `audio-015` | Audio Service Recovery on Failure | Audio | foundation | FREE | Configures the Windows Audio service to auto-restart on failure. |
| 19 | `audio-017` | Disable Exclusive Mode Application Launch | Audio | foundation | FREE | Prevents applications from hijacking the audio device in exclusive mode. |
| 20 | `audio-018` | Disable Audio Resampling Quality Boost | Audio | performance | FOUNDATION | Sets the Windows audio resampler to basic quality to reduce latency. |
| 21 | `audio-019` | Disable Communication Ducking | Audio | foundation | FREE | Prevents Windows from automatically reducing volume when it detects communications activity. |
| 22 | `audio-020` | Disable Volume Auto-Limiting | Audio | foundation | FREE | Prevents Windows from automatically capping peak volume. |
| 23 | `audio-023` | Audio MMCSS Scheduling Category | Audio | performance | FOUNDATION | Sets the Audio MMCSS task to High scheduling category. |
| 24 | `audio-024` | Playback MMCSS Scheduling Category | Audio | performance | FOUNDATION | Sets the Playback MMCSS task to High scheduling category. |
| 25 | `audio-025` | Audio MMCSS GPU Priority | Audio | performance | FOUNDATION | Raises the GPU priority for the Audio MMCSS task. |
| 26 | `audio-026` | Disable Realtek Audio DSP | Audio | performance | FOUNDATION | Disables Realtek audio processing effects. |
| 27 | `audio-027` | Disable Realtek Signal Enhancement | Audio | performance | FOUNDATION | Disables the Realtek signal enhancement feature. |
| 28 | `audio-028` | Disable Bluetooth Hands-Free Profile | Audio | performance | FOUNDATION | Disables the Bluetooth HFP (hands-free) audio profile to prefer A2DP. |
| 29 | `audio-030` | Disable Microphone Exclusive Mode | Audio | foundation | FREE | Prevents applications from taking exclusive control of the microphone. |
| 30 | `audio-032` | Disable Microphone Processing | Audio | foundation | FREE | Disables Windows automatic microphone processing (noise suppression, echo cancellation). |
| 31 | `bg-005` | Exclude Game Folders from Defender | Background | performance | FOUNDATION | Adds common game folders to the Defender exclusion list. |
| 32 | `bg-008` | Disable Settings Sync | Background | foundation | FREE | Disables settings sync via Group Policy. |
| 33 | `bg-009` | Disable Tips and Suggestions | Background | foundation | FREE | Disables Windows tips background suggestions. |
| 34 | `bg-010` | Set Active Hours | Background | foundation | FREE | Sets Windows Update active hours to cover a typical gaming session. |
| 35 | `cpu_amd_decrease_policy` | Performance Decrease Policy (AMD) | CPU | maximum | MAXIMUM | Chooses which signal is allowed to drop the clock back down, which changes how quickly the chip settles after a burst. |
| 36 | `cpu_amd_decrease_threshold` | Performance Decrease Threshold (AMD) | CPU | maximum | MAXIMUM | How far utilisation must rise before the clock steps up.  A low value makes the boost policy respond sooner. |
| 37 | `cpu_amd_increase_policy` | Performance Increase Policy (AMD) | CPU | maximum | MAXIMUM | Chooses which hardware performance boost signal is allowed to raise the clock, instead of letting the CPU decide. |
| 38 | `cpu_amd_increase_threshold` | Performance Increase Threshold (AMD) | CPU | maximum | MAXIMUM | How far utilisation must fall before the clock steps down.  A low value makes the boost policy respond sooner. |
| 39 | `cpu_amd_unpark_all` | Minimum Unparked Cores (100%) | CPU | performance | FOUNDATION | Asks the scheduler to keep every core out of the parked state, so spreading work does not stall on a waking core. |
| 40 | `cpu_boost_mode_aggressive` | Processor Boost Mode | CPU | performance | FOUNDATION | Sets the hardware turbo behaviour to aggressive, letting the chip exceed its sustained base clock for short bursts. |
| 41 | `cpu_epp_performance` | Energy Performance Preference | CPU | performance | FOUNDATION | Biases the hardware scheduler toward performance over energy saving when it picks between equally valid cores. |
| 42 | `cpu_hybrid_sched_performant` | Heterogeneous Scheduling (Performance) | CPU | maximum | MAXIMUM | Tells Windows to place long-running threads on the performance cores rather than letting it choose between P-cores and E-cores. |
| 43 | `cpu_hybrid_short_sched_performant` | Short-Thread Scheduling (Performance) | CPU | maximum | MAXIMUM | Applies the same performance-core preference to short-running threads, which the long-thread policy deliberately leaves alone. |
| 44 | `cpu_idle_disable` | Disable Processor Idle States | CPU | maximum | MAXIMUM | Stops the processor dropping into its low-power C-states, keeping cores clocked up at the cost of idle power and heat. |
| 45 | `cpu_intel_decrease_policy` | Performance Decrease Policy (Intel) | CPU | maximum | MAXIMUM | Chooses which signal is allowed to drop the clock back down, which changes how quickly the chip settles after a burst. |
| 46 | `cpu_intel_decrease_threshold` | Performance Decrease Threshold (Intel) | CPU | maximum | MAXIMUM | How far utilisation must rise before the clock steps up.  A low value makes the boost policy respond sooner. |
| 47 | `cpu_intel_increase_policy` | Performance Increase Policy (Intel) | CPU | maximum | MAXIMUM | Chooses which hardware performance boost signal is allowed to raise the clock, instead of letting the CPU decide. |
| 48 | `cpu_intel_increase_threshold` | Performance Increase Threshold (Intel) | CPU | maximum | MAXIMUM | How far utilisation must fall before the clock steps down.  A low value makes the boost policy respond sooner. |
| 49 | `cpu_max_state_100` | Maximum Processor State | CPU | foundation | FREE | Lets the processor use its full advertised frequency instead of being held below the maximum by the power plan. |
| 50 | `cpu_min_state_100` | Minimum Processor State | CPU | performance | FOUNDATION | Holds cores at full clock while the system is busy, trading idle power and heat for a floor under clock speed. |
| 51 | `mmcss_game_priority` | MMCSS Game Priority | CPU | performance | FOUNDATION | Marks the game as a high-priority Multimedia Class Scheduler task so audio and video threads get dedicated CPU time. |
| 52 | `process_priority` | Foreground Priority Boost | CPU | performance | FOUNDATION | Gives the foreground app more CPU share than background services when both want the processor. |
| 53 | `db-001` | Remove Default UWP Apps | Debloat | performance | FOUNDATION | Uninstalls common pre-installed UWP apps. |
| 54 | `db-002` | Remove Xbox App | Debloat | performance | FOUNDATION | Removes the Xbox app. |
| 55 | `db-003` | Remove Windows Mixed Reality | Debloat | performance | FOUNDATION | Removes Windows Mixed Reality apps. |
| 56 | `db-004` | Remove News & Weather | Debloat | performance | FOUNDATION | Removes the MSN News & Weather apps. |
| 57 | `db-005` | Stop OneDrive Process | Debloat | foundation | FREE | Stops the running OneDrive sync process (it stays installed). |
| 58 | `db-006` | Disable Pre-Installed Store Auto-Install | Debloat | foundation | FREE | Prevents auto re-install of removed apps. |
| 59 | `db-015` | Disable OneDrive | Debloat | performance | FOUNDATION | Disables OneDrive file synchronization via Group Policy. |
| 60 | `db-016` | Uninstall Cortana | Debloat | performance | FOUNDATION | Removes the Cortana app package from all user accounts. |
| 61 | `db-017` | Disable Widgets | Debloat | foundation | FREE | Disables the Widgets board via Group Policy. |
| 62 | `db-018` | Disable Windows Copilot | Debloat | foundation | FREE | Disables the Windows Copilot sidebar via Group Policy. |
| 63 | `db-019` | Disable Chat Icon | Debloat | foundation | FREE | Hides the Chat icon from the taskbar. |
| 64 | `db-020` | Disable Windows Spotlight | Debloat | foundation | FREE | Disables Windows Spotlight lock screen and desktop features. |
| 65 | `db-021` | Disable Widgets News & Interests | Debloat | foundation | FREE | Disables the Widgets news feed via the Dsh policy (AllowNewsAndInterests). |
| 66 | `dd-001` | Reduce Mouse Input Buffer | Delay Destroyer | maximum | MAXIMUM | Shrinks the OS mouse input queue so cursor updates reach applications faster. |
| 67 | `dd-002` | Reduce Keyboard Input Buffer | Delay Destroyer | maximum | MAXIMUM | Shrinks the OS keyboard input queue so key events reach applications faster. |
| 68 | `dd-003` | Disable Mouse Ballistics | Delay Destroyer | foundation | FREE | Disables the OS-level mouse sensitivity scaling for raw 1:1 pointer movement. |
| 69 | `dd-004` | Optimize HID Button Response | Delay Destroyer | maximum | MAXIMUM | Reduces the low-level hook timeout so HID button presses are processed faster. |
| 70 | `dd-005` | Disable USB Hub Power Management | Delay Destroyer | performance | FOUNDATION | Prevents USB hubs from entering power-saving states that add wake latency. |
| 71 | `dd-010` | Disable Game Bar Tips | Delay Destroyer | foundation | FREE | Disables Game Bar tip notifications that appear during gameplay. |
| 72 | `dd-011` | Disable Game Bar Keyboard Shortcuts | Delay Destroyer | foundation | FREE | Disables Game Bar keyboard shortcuts that can trigger during gameplay. |
| 73 | `dd-012` | Optimize Fullscreen Game Priority | Delay Destroyer | performance | FOUNDATION | Boosts the CPU priority of fullscreen exclusive games. |
| 74 | `dd-013` | Optimize TCP ACK Frequency | Delay Destroyer | performance | FOUNDATION | Disables delayed ACKs so TCP acknowledgments are sent immediately. |
| 75 | `dd-014` | Disable TCP Nagle Algorithm | Delay Destroyer | performance | FOUNDATION | Disables Nagle's algorithm so small packets are sent immediately. |
| 76 | `dd-015` | Optimize Network Interrupt Moderation | Delay Destroyer | maximum | MAXIMUM | Disables Interrupt Moderation on each active physical network adapter that exposes the setting (detect-first, revert-safe). |
| 77 | `dd-016` | Optimize DNS Cache Timeout | Delay Destroyer | performance | FOUNDATION | Reduces DNS cache timeout to refresh DNS entries more frequently. |
| 78 | `dd-017` | Optimize USB Transfer Timeout | Delay Destroyer | maximum | MAXIMUM | Reduces the USB transfer timeout for faster error recovery. |
| 79 | `dd-018` | Optimize USB Endpoint Response | Delay Destroyer | maximum | MAXIMUM | Reduces USB endpoint error recovery time for faster device responsiveness. |
| 80 | `dd-019` | Optimize USB Selective Suspend Delay | Delay Destroyer | maximum | MAXIMUM | Reduces the delay before USB devices enter selective suspend. |
| 81 | `disp-002` | Outline-Only Window Dragging | Display | foundation | FREE | Shows only the window outline while dragging. |
| 82 | `disp-004` | Solid Color Wallpaper | Display | foundation | FREE | Replaces the wallpaper with a solid color to reduce desktop redraws. |
| 83 | `disp-005` | Disable Translucent Selection | Display | foundation | FREE | Turns off the translucent rectangle used for file selection. |
| 84 | `disp-009` | Compact Icon Spacing | Display | foundation | FREE | Tightens desktop icon spacing. |
| 85 | `disp-012` | Disable Overlays | Display | foundation | FREE | Disables Game DVR overlay capture via registry. |
| 86 | `disp-014` | Disable Hardware Overlay | Display | performance | FOUNDATION | Turns off the hardware overlay plane to force GPU compositing. |
| 87 | `disp-016` | Disable Night Light | Display | foundation | FREE | Turns off the Windows Night Light blue-light filter. |
| 88 | `eth-001` | Disable Adapter Power Management | Ethernet | foundation | FREE | Turns off all power-saving on the wired adapter. |
| 89 | `eth-004` | Disable Large Send Offload IPv4 | Ethernet | performance | FOUNDATION | Turns off LSOv4 segmentation offload. |
| 90 | `eth-005` | Enable RSS on Adapter | Ethernet | foundation | FREE | Enables receive-side scaling on the wired adapter. |
| 91 | `eth-006` | Disable Flow Control | Ethernet | performance | FOUNDATION | Turns off Ethernet flow control. |
| 92 | `eth-008` | Disable Energy Efficient Ethernet | Ethernet | performance | FOUNDATION | Turns off EEE/Green Ethernet power saving. |
| 93 | `eth-009` | Disable Wake on Magic Packet | Ethernet | foundation | FREE | Turns off Wake-on-LAN wake on magic packet. |
| 94 | `eth-010` | Raise Receive Buffers | Ethernet | performance | FOUNDATION | Increases the adapter receive ring buffer size. |
| 95 | `eth-011` | Raise Transmit Buffers | Ethernet | performance | FOUNDATION | Increases the adapter transmit ring buffer size. |
| 96 | `eth-014` | Disable IPv6 Large Send Offload | Ethernet | performance | FOUNDATION | Turns off IPv6 LSO independently of IPv4. |
| 97 | `eth-015` | Disable Adapter Power-Off (Allow Computer to Turn Off) | Ethernet | foundation | FREE | Disables 'Allow the computer to turn off this device' on the wired adapter. |
| 98 | `exp-001` | Enable Dev Mode | Experimental | foundation | FREE | Enables Developer Mode features. |
| 99 | `exp-002` | Enable Windows Subsystem for Linux | Experimental | performance | FOUNDATION | Enables WSL support. |
| 100 | `exp-003` | Disable Hypervisor via BCDEdit | Experimental | maximum | MAXIMUM | Disables the hypervisor at boot. |
| 101 | `exp-004` | Enable Test Mode | Experimental | maximum | MAXIMUM | Enables test signing mode. |
| 102 | `exp-005` | Disable Core Isolation | Experimental | maximum | MAXIMUM | Disables memory integrity. |
| 103 | `fpsb-001` | Disable Virtualization-Based Security (VBS) | FPS Boost | maximum | MAXIMUM | Disables VBS and HVCI to recover 2-15% FPS lost to virtualization overhead. |
| 104 | `fpsb-005` | Disable Nagle's Algorithm (Network Latency) | FPS Boost | foundation | FREE | Disables TCP packet batching for lower network latency in online games. |
| 105 | `fpsb-008` | Disable Windows Spotlight | FPS Boost | foundation | FREE | Turns off the Windows lock screen Spotlight feature that downloads images. |
| 106 | `fpsb-009` | Disable Windows Tips and Suggestions | FPS Boost | foundation | FREE | Turns off Windows promotional tips and suggestion notifications. |
| 107 | `fpsb-010` | Disable Activity History | FPS Boost | foundation | FREE | Turns off Windows activity tracking to free background CPU and disk I/O. |
| 108 | `fpsb-012` | Disable Spectre/Meltdown Mitigations | FPS Boost | maximum | MAXIMUM | Disables CPU vulnerability mitigations for 1-8% FPS improvement. |
| 109 | `fpsb-021` | Disable PCIe ASPM | FPS Boost | performance | FOUNDATION | Disables PCI Express Active State Power Management for maximum GPU/SSD bandwidth. |
| 110 | `fpsb-025` | Disable NTFS Last Access Timestamps | FPS Boost | foundation | FREE | Stops NTFS from updating file access timestamps to reduce disk I/O. |
| 111 | `fn-011` | Disable Dynamic Shadows | Fortnite | performance | FOUNDATION | Turns off dynamic character/building shadows in Fortnite's config. |
| 112 | `fn-012` | Lowest Shadow Quality | Fortnite | performance | FOUNDATION | Forces Fortnite shadow quality to Low. |
| 113 | `fn-013` | Disable Post-Processing | Fortnite | performance | FOUNDATION | Drops Fortnite post-processing (bloom, DOF, color grading). |
| 114 | `fn-014` | Lowest Effects Quality | Fortnite | performance | FOUNDATION | Lowers Fortnite effects (smoke, explosions, particles) quality. |
| 115 | `fn-015` | Disable Motion Blur | Fortnite | foundation | FREE | Turns off Fortnite motion blur for clearer tracking. |
| 116 | `fn-016` | Disable Grass | Fortnite | performance | FOUNDATION | Removes Fortnite grass rendering entirely. |
| 117 | `fn-017` | Disable Anti-Aliasing | Fortnite | performance | FOUNDATION | Forces Fortnite to render with anti-aliasing disabled. |
| 118 | `fn-018` | Disable Global Illumination | Fortnite | performance | FOUNDATION | Drops Fortnite global illumination quality to off. |
| 119 | `fn-019` | Disable Reflections | Fortnite | performance | FOUNDATION | Drops Fortnite reflection quality to off. |
| 120 | `fn-020` | Lowest Shading Quality | Fortnite | performance | FOUNDATION | Forces the cheapest shading mode for maximum FPS. |
| 121 | `fn-021` | Lowest Texture Quality | Fortnite | performance | FOUNDATION | Frees VRAM by forcing lowest texture streaming quality. |
| 122 | `fn-022` | Foliage Off | Fortnite | performance | FOUNDATION | Removes Fortnite foliage quality. |
| 123 | `fn-023` | Competitive View Distance | Fortnite | performance | FOUNDATION | Sets Fortnite view distance to Medium for visibility with FPS saved. |
| 124 | `fn-024` | Disable Ray Tracing | Fortnite | performance | FOUNDATION | Turns off Fortnite ray tracing entirely. |
| 125 | `fn-025` | Disable Nanite | Fortnite | performance | FOUNDATION | Turns off Nanite geometry for faster CPU-side culling. |
| 126 | `fn-026` | Disable DLSS Frame Generation | Fortnite | performance | FOUNDATION | Turns off DLSS Frame Generation for lower render latency. |
| 127 | `fn-027` | Reflex Low Latency | Fortnite | foundation | FREE | Enables Fortnite's low-latency input mode. |
| 128 | `fn-028` | Disable VSync | Fortnite | foundation | FREE | Turns off VSync to remove added input latency. |
| 129 | `fn-029` | Disable Dynamic Resolution | Fortnite | foundation | FREE | Turns off Fortnite's dynamic resolution scaling. |
| 130 | `fn-030` | Multithreaded Rendering | Fortnite | foundation | FREE | Enables Fortnite multithreaded rendering. |
| 131 | `fn-031` | Keep Rendering in Background | Fortnite | foundation | FREE | Prevents Fortnite dropping to the fake-frame hitch when unfocused. |
| 132 | `fn-032` | Disable Energy Saving | Fortnite | foundation | FREE | Turns off Fortnite energy-saving throttling. |
| 133 | `fn-033` | Disable Mouse Acceleration | Fortnite | foundation | FREE | Turns off Fortnite mouse acceleration for 1:1 pointer input. |
| 134 | `fn-034` | Show FPS Counter | Fortnite | foundation | FREE | Enables Fortnite's in-game FPS counter. |
| 135 | `fn-035` | Lowest Textures (Scalability) | Fortnite | performance | FOUNDATION | Forces lowest texture quality in Fortnite scalability. |
| 136 | `fn-036` | Foliage Off (Scalability) | Fortnite | performance | FOUNDATION | Disables foliage quality in Fortnite scalability. |
| 137 | `fn-037` | Lowest Shading (Scalability) | Fortnite | performance | FOUNDATION | Forces lowest shading quality in Fortnite scalability. |
| 138 | `fn-038` | View Distance (Scalability) | Fortnite | performance | FOUNDATION | Sets Fortnite scalability view distance to Medium. |
| 139 | `gpu-001` | Enable Hardware Accelerated GPU Scheduling | GPU | performance | FOUNDATION | Lets the GPU driver schedule work without CPU help. |
| 140 | `gpu-002` | Disable Multiplane Overlay | GPU | performance | FOUNDATION | Turns off MPO to avoid composition glitches. |
| 141 | `gpu-003` | Increase TDR Delay | GPU | performance | FOUNDATION | Lets the driver recover instead of resetting on long renders. |
| 142 | `gpu-018` | Raise TDR Recovery Attempts | GPU | maximum | MAXIMUM | Allows more driver recoveries before Windows gives up on a hung display adapter. |
| 143 | `gpu-019` | Extend TDR Detection Window | GPU | maximum | MAXIMUM | Widens the time window in which TDR recoveries are counted, avoiding unnecessary full resets. |
| 144 | `gpu-020` | Extend GPU Hung Timeout | GPU | maximum | MAXIMUM | Raises how long Windows waits before declaring the GPU hung, protecting long shader compiles. |
| 145 | `gpu-021` | Disable Multi-GPU Switching | GPU | maximum | MAXIMUM | Stops Microsoft's hybrid graphics stack from hot-swapping between integrated and discrete adapters. |
| 146 | `gpu-022` | Prefer Hardware Render Path | GPU | performance | FOUNDATION | Forces the desktop composition stack onto the hardware renderer instead of software fallbacks. |
| 147 | `gpu-024` | Disable DWM Visual Effects | GPU | foundation | FREE | Cuts DWM visual effects (animations, shadows) for snappier UI redraws on weaker GPUs. |
| 148 | `gpu-025` | Disable Aero Peek | GPU | foundation | FREE | Turns off the Aero Peek taskbar preview animations to save a little composition work. |
| 149 | `gpu-060` | Enable MSI Mode for GPU | GPU | maximum | MAXIMUM | Enables Message Signaled Interrupts on the display adapter for lower interrupt latency. |
| 150 | `gproc-001` | Disable Game Efficiency Mode | Game Process | performance | FOUNDATION | Removes EcoQoS execution-speed throttling from the running game process (High QoS). Windows-only for Efficiency Mode behavior. |
| 151 | `gproc-002` | Restore Game CPU Sets | Game Process | performance | FOUNDATION | Detects an explicit per-game CPU Set restriction and clears it so Windows scheduling becomes unrestricted again. |
| 152 | `gproc-003` | Normalize Game Memory Priority | Game Process | performance | FOUNDATION | Restores a game that another optimizer set to a low memory priority back to Windows Normal (5). |
| 153 | `gproc-004` | Game CPU Priority | Game Process | performance | FOUNDATION | Lets a running supported game use the Windows 'Above Normal' CPU scheduling priority class. |
| 154 | `game-001` | Enable Game Mode | Gaming | foundation | FREE | Turns on Windows Game Mode. |
| 155 | `game-003` | Disable Game DVR / Game Bar / Background Capture | Gaming | performance | FOUNDATION | Single owner for the Game DVR and Game Bar capture pipeline: disables background recording, the Game Bar widget/overlay hook, and the policy-level capture switches. |
| 156 | `il-006` | Disable Pointer Trails | Input Latency | foundation | FREE | Turns off mouse pointer trails via registry. |
| 157 | `il-007` | Disable Enhanced Pointer Precision | Input Latency | foundation | FREE | Disables enhanced pointer precision (mouse acceleration) via registry. |
| 158 | `int-003` | Disable Intel VSync | Intel | performance | FOUNDATION | Disables driver-enforced VSync via the Intel graphics registry. |
| 159 | `int-009` | Opt Out of Intel Telemetry | Intel | performance | FOUNDATION | Disables Intel driver telemetry via registry keys. |
| 160 | `int-013` | Enable Intel Speed Shift | Intel | performance | FOUNDATION | Enables Intel Speed Shift Technology for faster CPU frequency transitions. |
| 161 | `int-014` | Enable Intel Turbo Boost Max 3.0 | Intel | performance | FOUNDATION | Ensures Intel Turbo Boost Max 3.0 is active for best single-core performance. |
| 162 | `kbd-001` | Zero Key Repeat Delay | Keyboard | foundation | FREE | Sets the key repeat delay to its minimum. |
| 163 | `kbd-003` | Disable Filter Keys | Keyboard | foundation | FREE | Turns off the Filter Keys accessibility feature. |
| 164 | `kbd-004` | Disable Sticky Keys | Keyboard | foundation | FREE | Turns off the Sticky Keys accessibility feature. |
| 165 | `kbd-005` | Disable Toggle Keys | Keyboard | foundation | FREE | Turns off the Toggle Keys beep indicator. |
| 166 | `kbd-006` | NumLock On at Logon | Keyboard | foundation | FREE | Turns NumLock on at the sign-in screen. |
| 167 | `kbd-014` | Instant Key Acceptance | Keyboard | foundation | FREE | Zeroes the Filter Keys delay before a press is accepted, so no keystroke is swallowed. |
| 168 | `kbd-015` | Zero FilterKeys Bounce Time | Keyboard | foundation | FREE | Sets Filter Keys bounce time to zero so a key can be re-pressed immediately. |
| 169 | `kbd-016` | Fast FilterKeys Auto-Repeat | Keyboard | foundation | FREE | Speeds up Filter Keys' internal auto-repeat delay and rate for held keys. |
| 170 | `kbd-017` | No FilterKeys Auto-Disable Timeout | Keyboard | foundation | FREE | Disables the timeout that auto-turns off Filter Keys while you step away. |
| 171 | `kbd-018` | Turn Off Filter Keys Switch | Keyboard | foundation | FREE | Flips the Filter Keys on/off switch value to fully off. |
| 172 | `kbd-019` | Silence Sticky Keys Feedback | Keyboard | foundation | FREE | Disables the audible and visual feedback Sticky Keys plays when a modifier activates. |
| 173 | `kbd-020` | Disable Sticky Keys Hotkey | Keyboard | foundation | FREE | Disables the Shift x5 hotkey that turns Sticky Keys on mid-game. |
| 174 | `kbd-021` | Turn Off Sticky Keys Switch | Keyboard | foundation | FREE | Sets the Sticky Keys main on/off value to disabled. |
| 175 | `kbd-022` | Sticky Keys Off at Logon | Keyboard | foundation | FREE | Disables Sticky Keys for the logon session before any profile loads. |
| 176 | `kbd-023` | Silence Toggle Keys Beep | Keyboard | foundation | FREE | Disables the Toggle Keys beep audio feedback. |
| 177 | `kbd-024` | Disable Toggle Keys Hotkey | Keyboard | foundation | FREE | Disables the Num Lock x5 hotkey that turns Toggle Keys on by accident. |
| 178 | `kbd-025` | Turn Off Toggle Keys Switch | Keyboard | foundation | FREE | Sets the Toggle Keys main on/off value to disabled. |
| 179 | `kbd-026` | Toggle Keys Off at Logon | Keyboard | foundation | FREE | Disables Toggle Keys for the logon session. |
| 180 | `kbd-027` | Disable High Contrast Mode | Keyboard | foundation | FREE | Turns off the High Contrast theme renderer. |
| 181 | `kbd-028` | Disable Mouse Keys Hotkey | Keyboard | foundation | FREE | Disables the hotkey that turns Mouse Keys on from the numeric keypad. |
| 182 | `kbd-029` | Keep Mouse Keys Active | Keyboard | foundation | FREE | Sets the Mouse Keys auto-off delay to never, so the feature stays active. |
| 183 | `kbd-030` | Disable Sound Sentry | Keyboard | foundation | FREE | Turns off Sound Sentry's flash-based sound alerts. |
| 184 | `kbd-031` | Disable Show Sounds Captions | Keyboard | foundation | FREE | Disables Show Sounds so no accessibility caption overlay is drawn. |
| 185 | `kbd-032` | Disable Ignore Repeated Keystrokes | Keyboard | foundation | FREE | Turns off the accessibility option that deliberately ignores repeated keystrokes. |
| 186 | `kbd-033` | Filter Keys Off at Logon | Keyboard | foundation | FREE | Disables Filter Keys for the logon session. |
| 187 | `kbd-034` | Hide Touch Keyboard Taskbar Button | Keyboard | foundation | FREE | Hides the touch keyboard taskbar button from the tray. |
| 188 | `kbd-035` | Caps Lock to Control Remap | Keyboard | performance | FOUNDATION | Remaps Caps Lock to the left Control key using a scancode map. |
| 189 | `kbd-046` | Disable Firmware PCI Settings | Keyboard | maximum | MAXIMUM | Stops firmware PCI settings overriding MSI-capable interrupt routing. |
| 190 | `kbd-047` | Block Keyboard Wake from Sleep | Keyboard | foundation | FREE | Stops the HID keyboard from waking the PC from sleep. |
| 191 | `kbd-048` | NumLock On at Logon Screen | Keyboard | foundation | FREE | Turns NumLock on for the sign-in screen itself. |
| 192 | `kbd-049` | Fast Key Repeat at Logon Screen | Keyboard | foundation | FREE | Applies the zero key repeat delay to the logon session. |
| 193 | `kbd-050` | Mouse Keys Off at Logon | Keyboard | foundation | FREE | Disables Mouse Keys for the logon session. |
| 194 | `kbd-051` | High Contrast Off at Logon | Keyboard | foundation | FREE | Disables High Contrast mode for the logon session. |
| 195 | `kbd-052` | Sound Sentry Off at Logon | Keyboard | foundation | FREE | Disables Sound Sentry for the logon session. |
| 196 | `kbd-053` | Silence Toggle Keys Beep at Logon | Keyboard | foundation | FREE | Disables Toggle Keys beep feedback at the logon session. |
| 197 | `kbd-054` | Silent Sticky Keys at Logon | Keyboard | foundation | FREE | Disables Sticky Keys feedback sounds at the logon session. |
| 198 | `kbd-055` | Mouse Keys Off Switch | Keyboard | foundation | FREE | Sets the Mouse Keys main on/off value to disabled. |
| 199 | `kbd-056` | High Contrast Off Switch | Keyboard | foundation | FREE | Sets the High Contrast main on/off value to disabled. |
| 200 | `kbd-057` | Sound Sentry Off Switch | Keyboard | foundation | FREE | Sets the Sound Sentry main on/off value to disabled. |
| 201 | `audio-036` | Disable Audio Endpoint Auto-Scaling | Laptop | performance | FOUNDATION | Prevents Windows from dynamically adjusting audio buffer sizes on laptops. |
| 202 | `lap-001` | Lid Close: Do Nothing (AC) | Laptop | foundation | FREE | Prevent sleep when closing the laptop lid while plugged in. |
| 203 | `lap-002` | Lid Close: Sleep (Battery) | Laptop | foundation | FREE | Ensure the laptop sleeps when the lid is closed on battery. |
| 204 | `lap-003` | Lid Close: Hibernate (Battery) | Laptop | foundation | FREE | Hibernate when the lid is closed on battery for zero drain. |
| 205 | `lap-004` | Display Never Off (AC) | Laptop | foundation | FREE | Keep the display on when plugged in. |
| 206 | `lap-005` | Display Off After 5 min (Battery) | Laptop | foundation | FREE | Turn the display off after 5 minutes on battery to save power. |
| 207 | `lap-006` | Never Sleep (AC) | Laptop | foundation | FREE | Prevent the system from sleeping on AC power. |
| 208 | `lap-007` | Sleep After 15 min (Battery) | Laptop | foundation | FREE | Sleep after 15 minutes of inactivity on battery. |
| 209 | `lap-008` | Disable Hibernate on AC | Laptop | foundation | FREE | Prevent hibernation while plugged in. |
| 210 | `lap-009` | Hibernate After 30 min (Battery) | Laptop | foundation | FREE | Hibernate after 30 minutes of sleep on battery to prevent drain. |
| 211 | `lap-010` | HDD Never Spindown (AC) | Laptop | foundation | FREE | Keep hard drives spinning when plugged in. |
| 212 | `lap-011` | HDD Spindown After 10 min (Battery) | Laptop | foundation | FREE | Spin down the HDD after 10 minutes on battery. |
| 213 | `lap-012` | Max CPU on Battery | Laptop | performance | FOUNDATION | Allow the CPU to reach maximum performance on battery power. |
| 214 | `lap-013` | Min CPU 5% on Battery | Laptop | performance | FOUNDATION | Set the minimum processor performance state on battery. |
| 215 | `lap-014` | Disable Turbo Boost on Battery | Laptop | performance | FOUNDATION | Disable CPU turbo boost when on battery to extend playtime. |
| 216 | `lap-016` | Enable Network Connectivity in Standby | Laptop | foundation | FREE | Allow the network adapter to stay connected during Modern Standby. |
| 217 | `lap-017` | Wi-Fi: Maximum Performance (AC) | Laptop | foundation | FREE | Set Wi-Fi adapter to maximum performance on AC power. |
| 218 | `lap-018` | Wi-Fi: Moderate Power Saving (Battery) | Laptop | foundation | FREE | Use moderate Wi-Fi power saving on battery. |
| 219 | `lap-019` | Disable Bluetooth Power Saving | Laptop | foundation | FREE | Disable Bluetooth adapter power saving to reduce input latency. |
| 220 | `lap-020` | Disable PCIe Power Management | Laptop | performance | FOUNDATION | Disable PCIe ASPM to reduce device wake latency. |
| 221 | `lap-021` | Disable USB Selective Suspend | Laptop | foundation | FREE | Disable USB selective suspend to prevent device disconnections. |
| 222 | `lap-029` | Aggressive Fan Policy (AC) | Laptop | performance | FOUNDATION | Set the system cooling policy to Active on AC power. |
| 223 | `lap-030` | Passive Cooling on Battery | Laptop | performance | FOUNDATION | Set the system cooling policy to Passive on battery power. |
| 224 | `lap-032` | Use Balanced Plan on Battery | Laptop | foundation | FREE | Switch to the Balanced power plan on battery for efficiency. |
| 225 | `lap-033` | Reduce Hibernate File Size | Laptop | foundation | FREE | Set hibernation to reduced mode to save disk space. |
| 226 | `lap-034` | Aggressive Boost on AC | Laptop | performance | FOUNDATION | Set CPU boost mode to Aggressive when plugged in for maximum clocks. |
| 227 | `lap-035` | Disable Boost on Battery | Laptop | performance | FOUNDATION | Disable CPU turbo boost on battery to extend playtime. |
| 228 | `lap-036` | PCI Express Max Power on AC | Laptop | performance | FOUNDATION | Set PCI Express link state power management to off on AC. |
| 229 | `lap-037` | PCI Express Moderate Saving on Battery | Laptop | performance | FOUNDATION | Set PCI Express to moderate power saving on battery. |
| 230 | `lap-038` | USB Selective Suspend on Battery | Laptop | foundation | FREE | Enable USB selective suspend on battery to conserve power. |
| 231 | `lap-039` | NVMe Aggressive Idle on Battery | Laptop | performance | FOUNDATION | Allow NVMe drives to enter deep power states on battery. |
| 232 | `lap-040` | NVMe Responsive on AC | Laptop | performance | FOUNDATION | Keep NVMe drives in responsive mode when plugged in. |
| 233 | `lap-041` | Disk Never Idle on AC | Laptop | foundation | FREE | Prevent hard drives from idling on AC power. |
| 234 | `lap-042` | Disk Idle 5 min on Battery | Laptop | foundation | FREE | Spin down the disk after 5 minutes on battery. |
| 235 | `lap-043` | High Refresh on AC | Laptop | foundation | FREE | Ensure the display uses its highest refresh rate when plugged in. |
| 236 | `lap-044` | Restrict Background Apps on Battery | Laptop | foundation | FREE | Restrict UWP background app activity when on battery power. |
| 237 | `lap-045` | Disable Game Mode on Battery | Laptop | foundation | FREE | Disable Windows Game Mode when on battery to save power. |
| 238 | `lap-047` | Disable Hybrid Sleep on Battery | Laptop | foundation | FREE | Disable hybrid sleep on battery to prevent disk writes. |
| 239 | `lap-048` | Disable Wake Timers on Battery | Laptop | foundation | FREE | Prevent scheduled tasks from waking the laptop on battery. |
| 240 | `lap-049` | Disable Adaptive Brightness | Laptop | foundation | FREE | Disable ambient light sensor-based brightness adjustment. |
| 241 | `lap-050` | Moderate C-States on Battery | Laptop | performance | FOUNDATION | Allow moderate CPU C-states on battery for power savings. |
| 242 | `lap-052` | Standard Timer on Battery | Laptop | performance | FOUNDATION | Use standard timer resolution on battery to save power. |
| 243 | `lap-053` | Disable DWM Effects on Battery | Laptop | foundation | FREE | Disable DWM visual effects on battery to reduce GPU power draw. |
| 244 | `mon-001` | Disable Monitor Auto-Detect Sleep | Monitor | foundation | FREE | Prevents the display from entering power save during long play sessions. |
| 245 | `mon-006` | Disable Adaptive Brightness | Monitor | foundation | FREE | Turns off display adaptive brightness in the power plan. |
| 246 | `mouse-002` | Disable Cursor Suppression | Mouse | foundation | FREE | Stops Windows from hiding the cursor during typing in games. |
| 247 | `mouse-004` | Instant Hover Time | Mouse | foundation | FREE | Sets the pointer hover activation time to its minimum. |
| 248 | `mouse-014` | Fast Double-Click | Mouse | foundation | FREE | Lowers the double-click speed threshold so rapid clicks register faster. |
| 249 | `mouse-015` | Compact Double-Click Zone | Mouse | foundation | FREE | Shrinks the vertical double-click hit zone for precise rapid clicking. |
| 250 | `mouse-016` | Compact Double-Click Zone Width | Mouse | foundation | FREE | Shrinks the horizontal double-click hit zone for rapid clicking. |
| 251 | `mouse-017` | Disable Pointer Trails | Mouse | foundation | FREE | Turns off cursor motion trails for a clean, precise pointer. |
| 252 | `mouse-018` | Disable Snap-To | Mouse | foundation | FREE | Prevents the pointer from jumping to the default button in dialogs. |
| 253 | `mouse-019` | Linear Pointer Curve | Mouse | foundation | FREE | Replaces the Windows acceleration curves with a flat 1:1 pointer response. |
| 254 | `mouse-020` | Tight Hover Zone | Mouse | foundation | FREE | Narrows the horizontal pointer hover zone for faster hover activation. |
| 255 | `mouse-021` | Tight Hover Zone Height | Mouse | foundation | FREE | Narrows the vertical pointer hover zone for faster hover activation. |
| 256 | `mouse-022` | Disable Click Lock | Mouse | foundation | FREE | Turns off Click Lock so dragging never sticks after a long press. |
| 257 | `mouse-023` | Faster Click Lock Engage | Mouse | foundation | FREE | Shortens the hold time before Click Lock engages when it is enabled. |
| 258 | `mouse-024` | Disable Cursor Blink | Mouse | foundation | FREE | Stops the text cursor from blinking. |
| 259 | `mouse-027` | Horizontal Wheel Chars | Mouse | foundation | FREE | Sets how many characters a horizontal wheel tilt scrolls. |
| 260 | `mouse-028` | Snappy Window Drag | Mouse | foundation | FREE | Lowers the vertical threshold before a window switches to full-window drag. |
| 261 | `mouse-029` | Snappy Window Drag Width | Mouse | foundation | FREE | Lowers the horizontal threshold before a window switches to full-window drag. |
| 262 | `mouse-030` | Activate Window on Hover | Mouse | performance | FOUNDATION | Makes windows activate as soon as the pointer passes over them. |
| 263 | `mouse-031` | Disable Snap Layouts | Mouse | foundation | FREE | Turns off the Win11 Snap Layouts popup when dragging a window to an edge. |
| 264 | `mouse-032` | Minimize Flash Count | Mouse | foundation | FREE | Sets the number of flashes a background window makes when it steals attention. |
| 265 | `mouse-047` | Scroll Inactive Windows on Hover | Mouse | foundation | FREE | Lets the wheel scroll windows under the pointer without activating them. |
| 266 | `mouse-048` | Disable Snap Assist | Mouse | foundation | FREE | Disables the Snap Assist layout buttons shown when dragging a window to an edge. |
| 267 | `mouse-049` | Disable Snap Fill | Mouse | foundation | FREE | Prevents windows from auto-filling available space when snapped. |
| 268 | `mouse-050` | Drag Maximized Windows | Mouse | foundation | FREE | Allows dragging a maximized window off the top edge to restore and move it. |
| 269 | `mouse-051` | Disable MouseKeys | Mouse | foundation | FREE | Turns off the numpad-based MouseKeys pointer control. |
| 270 | `mouse-052` | Faster MouseKeys Speed | Mouse | foundation | FREE | Raises the top pointer speed for the numpad MouseKeys control. |
| 271 | `mouse-053` | Faster MouseKeys Acceleration | Mouse | foundation | FREE | Shortens the time MouseKeys takes to reach its top pointer speed. |
| 272 | `nv-001` | Enable Persistence Mode | NVIDIA | performance | FOUNDATION | Keeps the NVIDIA driver resident to lower launch stalls. |
| 273 | `nv-002` | Reset Auto Boost Defaults | NVIDIA | performance | FOUNDATION | Returns GPU boost clocks to driver defaults. |
| 274 | `nv-018` | Disable NVIDIA Logging Services | NVIDIA | maximum | MAXIMUM | Stops and disables the NVIDIA logging and monitoring services. |
| 275 | `net-002` | TCP Congestion Provider CTCP | Network | performance | FOUNDATION | Switches the TCP congestion provider to Compound TCP (modern Win11 + legacy fallback). |
| 276 | `net-003` | Enable Receive-Side Scaling | Network | performance | FOUNDATION | Turns on RSS so network processing spreads across CPU cores. |
| 277 | `net-004` | Enable ECN Capability | Network | performance | FOUNDATION | Enables Explicit Congestion Notification on TCP. |
| 278 | `net-005` | Disable TCP Timestamps | Network | performance | FOUNDATION | Turns off TCP timestamp options. |
| 279 | `net-006` | Initial RTO 2000 ms | Network | performance | FOUNDATION | Sets the TCP initial retransmission timeout to 2000 ms. |
| 280 | `net-007` | Max Connections Per Server (IE/Apps) | Network | foundation | FREE | Raises simultaneous connections per HTTP server to 8. |
| 281 | `net-008` | Max Connections Per 1.0 Server | Network | foundation | FREE | Raises parallel connections for HTTP/1.0 servers to 8. |
| 282 | `net-009` | Disable Network Throttling | Network | performance | FOUNDATION | Raises the MMCSS network throttling index to maximum. |
| 283 | `net-010` | Default TTL 64 | Network | foundation | FREE | Sets the default IPv4 time-to-live to 64. |
| 284 | `net-012` | Set DNS to Cloudflare | Network | foundation | FREE | Switches DNS to Cloudflare's fast public resolvers. |
| 285 | `net-013` | Disable Delivery Optimization P2P | Network | foundation | FREE | Disables peer-to-peer Windows Update sharing. |
| 286 | `net-017` | Disable Nagle Algorithm | Network | performance | FOUNDATION | Disables Nagle's algorithm on all network interfaces for lower latency. |
| 287 | `net-019` | Disable RSS on Low RAM | Network | maximum | MAXIMUM | Disables Receive-Side Scaling on systems with limited RAM to free memory for games. |
| 288 | `net-020` | Disable NIC Interrupt Moderation | Network | maximum | MAXIMUM | Turns off the active adapter's Interrupt Moderation so every packet is raised to the CPU immediately instead of being batched. |
| 289 | `net-021` | Restore Receive-Side Scaling (Adapter) | Network | performance | FOUNDATION | Re-enables RSS on the TCP stack and on the adapter when it is supported but was switched off. |
| 290 | `net-022` | Network Adapter Performance Mode | Network | performance | FOUNDATION | Disables the NIC's low-power link features (EEE, Green Ethernet, Power Saving Mode, Gigabit Lite, Ultra Low Power Mode) for lower jitter. |
| 291 | `gpu-027` | Suppress Animations While Shifting | Performance | foundation | FREE | Lets you hold Shift to instantly disable window animations, useful for remote sessions. |
| 292 | `gpu-028` | Disable DWM Telemetry | Performance | foundation | FREE | Stops the DWM Customer Experience Improvement Program from collecting UI rendering data. |
| 293 | `gpu-029` | Disable DWM Machine Check Redraw | Performance | maximum | MAXIMUM | Stops DWM's full-surface redraw when the desktop changes, cutting jank on low-end GPUs. |
| 294 | `gpu-030` | Skip DWM Machine Check Fast Path | Performance | maximum | MAXIMUM | Prevents the DWM machine-check fast-path shortcut that can degrade presentation cadence. |
| 295 | `gpu-032` | Disable Window Blur | Performance | foundation | FREE | Turns off the blur-behind-windows effect that costs extra GPU fill passes. |
| 296 | `gpu-035` | Enable WPF Hardware Acceleration | Performance | foundation | FREE | Ensures WPF (.NET) apps render on the GPU instead of the software rasterizer. |
| 297 | `gpu-042` | Disable DirectX Update Checks | Performance | foundation | FREE | Stops the DirectX runtime from checking for optional updates during installs. |
| 298 | `gpu-046` | Clear DirectX Shader Cache | Performance | foundation | FREE | Wipes the DirectX shader cache so stale or corrupt shader blobs recompile cleanly. |
| 299 | `gpu-058` | Enable GPU MMCSS Scheduling | Performance | performance | FOUNDATION | Tunes the Multimedia Class Scheduler Service profile for GPU-priority tasks. |
| 300 | `perf-001` | Timer Resolution Diagnostic | Performance | performance | FOUNDATION | One optional timer card. Permits applications to request a higher timer resolution; it does not force 0.5 ms. Games already request the resolution they need, so this rarely changes anything. |
| 301 | `perf-002` | Enable Game Mode | Performance | foundation | FREE | Enable Windows Game Mode for better gaming performance. |
| 302 | `perf-003` | Disable Game Mode | Performance | foundation | FREE | Disable Windows Game Mode if it causes issues with your system. |
| 303 | `perf-004` | Disable Memory Compression | Performance | performance | FOUNDATION | Disable Windows Memory Compression which can add CPU overhead. |
| 304 | `perf-005` | Disable Superfetch (SysMain) | Performance | foundation | FREE | Disable Superfetch/SysMain service which can cause disk thrashing. |
| 305 | `perf-008` | Disable Hibernation | Performance | foundation | FREE | Disable hibernation to free disk space and reduce overhead. |
| 306 | `perf-009` | Throttle Windows Update During Gaming | Performance | foundation | FREE | Configure Windows Update to avoid downloading during active gaming. |
| 307 | `perf-012` | Disable Toast Notifications | Performance | foundation | FREE | Disable Windows toast notifications to avoid interruptions. |
| 308 | `perf-013` | Disable NIC Interrupt Moderation | Performance | maximum | MAXIMUM | Disables Interrupt Moderation on each active physical network adapter that exposes the setting (detect-first, revert-safe). |
| 309 | `perf-019` | Optimize Interrupt Affinity | Performance | maximum | MAXIMUM | Configure interrupt affinity for better CPU load distribution. |
| 310 | `perf-029` | Set MMCSS Gaming Priority | Performance | performance | FOUNDATION | Configure MMCSS to give game processes highest scheduling priority. |
| 311 | `perf-034` | Set Processor Performance Decrease Policy | Performance | maximum | MAXIMUM | Configure aggressive processor performance decrease for faster frequency scaling under gaming loads. |
| 312 | `perf-035` | Disable USB Selective Suspend | Performance | foundation | FREE | Disable USB selective suspend to prevent USB device disconnections. |
| 313 | `perf-037` | Force TRIM | Performance | foundation | FREE | Ensure TRIM is always enabled for optimal SSD performance. |
| 314 | `perf-038` | Disable I/O Coalescing | Performance | performance | FOUNDATION | Disable I/O coalescing in the LAN server driver for lower latency. |
| 315 | `perf-042` | Disable Memory Compression (Cmd) | Performance | performance | FOUNDATION | Disable Windows Memory Compression via PowerShell to reduce CPU overhead on systems with ample RAM. |
| 316 | `perf-043` | Disable Page Combining (Registry) | Performance | performance | FOUNDATION | Disable Windows page combining through registry to reduce memory management overhead. |
| 317 | `perf-046` | Disable Background Maintenance | Performance | performance | FOUNDATION | Disable scheduled maintenance tasks that consume disk and CPU resources during gaming sessions. |
| 318 | `perf-049` | Set IRPStackSize | Performance | maximum | MAXIMUM | Increase the I/O Request Packet stack size for better network throughput in LAN gaming scenarios. |
| 319 | `perf-053` | Optimize Non-Paged Pool Size | Performance | foundation | FREE | Let Windows auto-manage non-paged pool size for optimal memory allocation on gaming systems. |
| 320 | `perf-054` | Disable Game DVR Recording (Policy) | Performance | foundation | FREE | Disable Game DVR background recording via Group Policy to free up system resources. |
| 321 | `perf-055` | Optimize Thread Scheduling | Performance | performance | FOUNDATION | Disable scheduler profiling overhead for lower context switch latency in gaming workloads. |
| 322 | `power-002` | Disable USB Selective Suspend | Power | foundation | FREE | Prevents USB ports from suspending. |
| 323 | `power-003` | Disable PCI Express ASPM | Power | performance | FOUNDATION | Prevents PCIe link power saving. |
| 324 | `power-004` | Set Sleep to Never | Power | foundation | FREE | Prevents the system from sleeping. |
| 325 | `power-005` | Set Display Off Timeout | Power | foundation | FREE | Sets display-off timeout to 15 minutes. |
| 326 | `power-006` | Disable Hibernation | Power | foundation | FREE | Turns off hibernation and deletes the hibernation file. |
| 327 | `power-009` | Set Minimum Processor State | Power | performance | FOUNDATION | Keeps the CPU at a high clock floor on AC. |
| 328 | `power-010` | Disable Adaptive Brightness | Power | foundation | FREE | Turns off display adaptive brightness. |
| 329 | `power-011` | Disable Hard Disk Sleep | Power | foundation | FREE | Prevents the disk from idling down. |
| 330 | `power-016` | Disable Fast Startup | Power | foundation | FREE | Turns off Windows Fast Startup so the system performs a full cold boot every time. |
| 331 | `power-018` | Disable Power Telemetry | Power | foundation | FREE | Turns off Windows power telemetry collection to reduce background CPU and disk activity. |
| 332 | `power-019` | Disable Power Estimation | Power | foundation | FREE | Turns off the Windows power estimation engine to stop periodic CPU wake-ups for power tracking. |
| 333 | `power-021` | Disable Power Throttling | Power | performance | FOUNDATION | Turns off Windows Power Throttling globally so background processes are not duty-cycled to save energy. |
| 334 | `power-022` | Disable Lazy Mode | Power | performance | FOUNDATION | Turns off CPU lazy idle mode so cores transition out of idle states immediately instead of waiting. |
| 335 | `power-023` | Disable DIPM | Power | maximum | MAXIMUM | Disables Device Initiated Power Management on NVMe drives to prevent aggressive low-power transitions. |
| 336 | `power-024` | Disable HIPM | Power | maximum | MAXIMUM | Disables Host Initiated Power Management on NVMe drives to prevent the OS from putting drives into low-power states. |
| 337 | `power-025` | Disable Hidden Power Saving | Power | performance | FOUNDATION | Turns off the AoAcOverride that enables Always On Always Connected hidden power-saving states. |
| 338 | `power-026` | Disable Sleep Study | Power | foundation | FREE | Turns off the Windows Sleep Study diagnostic logger to reduce background disk and CPU activity. |
| 339 | `power-027` | Disable Connected Standby | Power | maximum | MAXIMUM | Disables Connected Standby (Modern Standby) via the platform override to force classic S3 sleep behavior. |
| 340 | `pp-013` | Maximum Power Plan | Power Plans | maximum | MAXIMUM | Create and activate the Maximum Power Plan — a maximum-performance gaming power plan that lets the CPU boost to 100% under load while idling down at rest, minimizing throttling for consistent frame times. |
| 341 | `pre-001` | Trajectory Timing | Precision Tweaks | maximum | MAXIMUM | Tweaks frame timing & send intervals. |
| 342 | `pre-003` | Packet Flow | Precision Tweaks | maximum | MAXIMUM | Packet flow optimization for stable network timing. |
| 343 | `pre-004` | Tick Sync | Precision Tweaks | maximum | MAXIMUM | Server timing tick alignment. |
| 344 | `pre-005` | Latency Consistency | Precision Tweaks | maximum | MAXIMUM | Latency spike reduction & response consistency. |
| 345 | `pre-006` | Click Timing | Precision Tweaks | maximum | MAXIMUM | Click-to-shot timing tightness. |
| 346 | `pre-007` | Packet Timing | Precision Tweaks | maximum | MAXIMUM | Network jitter & micro-loss mitigation. |
| 347 | `pre-009` | Taste Tester | Precision Tweaks | foundation | FREE | Preset mix of lighter tweaks across all categories. |
| 348 | `priv-001` | Disable Suggested Content | Privacy | foundation | FREE | Turns off suggested app content in Start. |
| 349 | `priv-002` | Disable Tailored Experiences | Privacy | foundation | FREE | Turns off tailored ad experiences. |
| 350 | `priv-003` | Disable Online Speech | Privacy | foundation | FREE | Turns off online speech recognition. |
| 351 | `priv-004` | Disable Handwriting Data | Privacy | foundation | FREE | Turns off handwriting data collection. |
| 352 | `priv-005` | Disable Advertiser Tracking | Privacy | foundation | FREE | Turns off the ad tracking ID. |
| 353 | `priv-006` | Disable Camera Access | Privacy | performance | FOUNDATION | Denies camera access to apps. |
| 354 | `priv-008` | Disable Contacts Access | Privacy | foundation | FREE | Denies contacts access. |
| 355 | `priv-009` | Disable Email Access | Privacy | foundation | FREE | Denies email access to apps. |
| 356 | `priv-010` | Disable Notifications | Privacy | performance | FOUNDATION | Disables app notification access. |
| 357 | `priv-011` | Disable Call History Access | Privacy | foundation | FREE | Denies call history access. |
| 358 | `ram-001` | Enable Prefetch | RAM | performance | FOUNDATION | Turns on boot and application prefetching. |
| 359 | `ram-002` | Enable SysMain Service | RAM | performance | FOUNDATION | Sets the SysMain (Superfetch) service to automatic. |
| 360 | `ram-003` | Disable SysMain on SSD | RAM | performance | FOUNDATION | Disables Superfetch on SSD-only systems. |
| 361 | `ram-004` | Disable Superfetch Registry (SSD) | RAM | performance | FOUNDATION | Turns off the Superfetch prefetcher at the registry level. |
| 362 | `ram-005` | Enable Superfetch on HDD | RAM | performance | FOUNDATION | Turns on the Superfetch prefetcher for HDD systems. |
| 363 | `ram-008` | Disable Hibernation Reserve | RAM | foundation | FREE | Frees the RAM-space reserved for the hibernation file. |
| 364 | `ram-009` | 32-bit Large Address Space | RAM | maximum | MAXIMUM | Raises the user address space for 32-bit games. |
| 365 | `ram-014` | Disable Memory Diagnostics at Boot | RAM | foundation | FREE | Prevents the scheduled memory check at boot. |
| 366 | `ram-021` | Cache Memory-Mapped Images | RAM | performance | FOUNDATION | Lets Windows keep loaded DLL and executable pages in the standby cache. |
| 367 | `ram-022` | Physical Address Extension (32-bit) | RAM | maximum | MAXIMUM | Enables PAE so 32-bit Windows can address more physical RAM. |
| 368 | `ram-023` | Enable Hibernation for Fast Startup | RAM | foundation | FREE | Turns hibernation back on so Fast Startup can preload the kernel. |
| 369 | `ram-024` | System-Managed Pagefile | RAM | foundation | FREE | Lets Windows automatically size the pagefile on all drives. |
| 370 | `ram-028` | Restore Automatic Pagefile Size | RAM | foundation | FREE | Returns the system-drive pagefile to Windows-managed sizing. |
| 371 | `ram-030` | Disable Telemetry Service | RAM | performance | FOUNDATION | Stops the Connected User Experiences and Telemetry service. |
| 372 | `ram-031` | Disable Maps Broker | RAM | foundation | FREE | Stops the downloaded-maps manager service. |
| 373 | `ram-032` | Disable WMP Network Sharing | RAM | foundation | FREE | Stops the Windows Media Player network sharing service. |
| 374 | `ram-033` | Disable Retail Demo Service | RAM | foundation | FREE | Stops the retail demo mode service. |
| 375 | `ram-035` | Disable Device WAP Push | RAM | foundation | FREE | Stops the Device Management WAP Push service. |
| 376 | `ram-036` | Disable Diagnostics Hub | RAM | performance | FOUNDATION | Stops the Diagnostics Hub Standard Collector service. |
| 377 | `ram-038` | Disable Windows Error Reporting | RAM | performance | FOUNDATION | Stops the WerSvc error reporting service. |
| 378 | `ram-039` | Disable Windows Error Reporting (WER) | RAM | foundation | FREE | Stops Windows Error Reporting from collecting crash dumps. |
| 379 | `ram-040` | Disable Memory Compression | RAM | performance | FOUNDATION | Turns off Windows 10/11 memory compression. |
| 380 | `ram-042` | Shorten Service Shutdown Timeout | RAM | performance | FOUNDATION | Cuts how long Windows waits for services to stop at shutdown. |
| 381 | `ram-043` | Disable Boot Memory Diagnostic | RAM | foundation | FREE | Prevents the scheduled Windows Memory Diagnostic run. |
| 382 | `ram-044` | Disable Data Sharing Service | RAM | performance | FOUNDATION | Stops the DsmSvc data sharing service. |
| 383 | `ram-046` | Disable Push Notifications | RAM | performance | FOUNDATION | Stops the Windows Push Notifications System service. |
| 384 | `ram-047` | Disable Full Memory Diagnostic Task | RAM | foundation | FREE | Disables the scheduled full memory check task. |
| 385 | `ram-048` | Disable Memory Diagnostic Events | RAM | foundation | FREE | Disables the memory-diagnostic event processing task. |
| 386 | `ram-049` | Disable Compatibility Appraiser | RAM | foundation | FREE | Disables the Microsoft Compatibility Appraiser task. |
| 387 | `ram-050` | Disable Program Data Updater | RAM | foundation | FREE | Disables the Application Experience ProgramDataUpdater task. |
| 388 | `ram-051` | Disable CEIP Consolidator | RAM | foundation | FREE | Disables the Customer Experience Improvement Program task. |
| 389 | `ram-052` | Disable WER Queue Reporting | RAM | foundation | FREE | Disables the error-reporting queue task. |
| 390 | `ram-053` | Remove Solitaire and Casual Games | RAM | performance | FOUNDATION | Uninstalls the built-in Solitaire Collection and casual games. |
| 391 | `ram-054` | Remove Xbox Gaming Overlay | RAM | performance | FOUNDATION | Uninstalls the Xbox Game Bar overlay app. |
| 392 | `ram-056` | Remove Pagefile From Second Drive | RAM | performance | FOUNDATION | Deletes a pagefile that was placed on D:. |
| 393 | `ram-057` | Enable Large System Cache | RAM | maximum | MAXIMUM | Sets the LargeSystemCache registry value to optimize file system caching. |
| 394 | `ram-058` | Increase Io Page Lock Limit | RAM | performance | FOUNDATION | Lets Windows auto-manage the I/O page lock limit. |
| 395 | `ram-059` | Disable Paging Executive | RAM | performance | FOUNDATION | Keeps the kernel and drivers in physical RAM instead of paging them to disk. |
| 396 | `ram-060` | Set System Pages | RAM | performance | FOUNDATION | Lets Windows manage the number of system page table entries. |
| 397 | `ram-061` | Optimize Paged Pool Size | RAM | performance | FOUNDATION | Lets Windows auto-manage the paged pool size. |
| 398 | `ram-062` | Enable Memory Compression | RAM | foundation | FREE | Enables Windows memory compression to fit more data in RAM. |
| 399 | `ram-063` | Set Process Count Limit | RAM | maximum | MAXIMUM | Optimizes the shared section size for desktop heap. |
| 400 | `ram-064` | Disable Prefetch (SSD) | RAM | performance | FOUNDATION | Turns off boot and application prefetching at the registry level. |
| 401 | `reg-001` | Foreground Lock Timeout 0 | Registry | foundation | FREE | Removes the delay before a clicked window receives focus. |
| 402 | `reg-002` | Active Window Tracking Timeout 0 | Registry | foundation | FREE | Removes the hover delay for focus-follows-mouse tracking. |
| 403 | `reg-003` | Suppress Low Disk Space Warnings | Registry | foundation | FREE | Stops the low-disk-space balloon warnings. |
| 404 | `reg-004` | Disable Recent Documents History | Registry | foundation | FREE | Stops tracking of recently opened documents. |
| 405 | `reg-005` | Disable Screen Saver | Registry | foundation | FREE | Turns the screen saver off. |
| 406 | `reg-006` | Disable Taskbar Animations | Registry | foundation | FREE | Turns off taskbar animation effects. |
| 407 | `reg-007` | Disable ListView Shadows | Registry | foundation | FREE | Turns off drop shadows behind list views. |
| 408 | `reg-008` | Never Combine Taskbar Buttons | Registry | foundation | FREE | Shows every window as a separate taskbar button. |
| 409 | `reg-009` | Explorer Separate Processes | Registry | foundation | FREE | Runs each Explorer folder in its own process. |
| 410 | `reg-010` | Hide Sync Provider Notifications | Registry | foundation | FREE | Removes cloud sync badges and banners in Explorer. |
| 411 | `reg-011` | Disable Desktop Peek Preview | Registry | foundation | FREE | Turns off the Aero Peek hover preview. |
| 412 | `reg-012` | Disable Icons Only Thumbnails | Registry | foundation | FREE | Shows only file icons instead of embedded thumbnail previews in lists. |
| 413 | `reg-013` | Hide Frequent Folders in Quick Access | Registry | foundation | FREE | Removes the frequent folders section from Quick Access. |
| 414 | `reg-014` | Disable AutoPlay Handlers | Registry | foundation | FREE | Disables AutoPlay for removable media. |
| 415 | `reg-015` | Disable Widgets Button | Registry | foundation | FREE | Removes the Widgets button from the taskbar. |
| 416 | `reg-016` | Disable Copilot Button | Registry | foundation | FREE | Removes the Copilot icon from the taskbar. |
| 417 | `rep-005` | Reset Windows Update Components | Repair | performance | FOUNDATION | Stops the update service, renames the SoftwareDistribution cache, and restarts it. |
| 418 | `rep-015` | CPU Optimization Repair | Repair | performance | FOUNDATION | Detect-first cleaner for bad scheduling values left behind by old MaximumTweaks builds, REG packs, BAT packs or other optimizers. |
| 419 | `sec-001` | Add Game Folder to Defender Exclusions | Security & Performance | performance | FOUNDATION | Excludes game folders from real-time scanning. |
| 420 | `sec-002` | Exclude Game Processes | Security & Performance | performance | FOUNDATION | Excludes game executables from scanning. |
| 421 | `sec-008` | Disable Remote Desktop | Security & Performance | foundation | FREE | Disables RDP if unused. |
| 422 | `sec-010` | Disable PowerShell Script Logging | Security & Performance | performance | FOUNDATION | Disables PowerShell ScriptBlock Logging via Group Policy. |
| 423 | `sec-011` | Disable Network Discovery | Security & Performance | foundation | FREE | Disables network discovery. |
| 424 | `svc-001` | Disable SysMain | Services | performance | FOUNDATION | Disables the SysMain (Superfetch) service. |
| 425 | `svc-002` | Disable Windows Search | Services | performance | FOUNDATION | Disables the Windows Search indexer. |
| 426 | `svc-005` | Disable Remote Registry | Services | foundation | FREE | Disables remote registry access. |
| 427 | `svc-006` | Disable Print Spooler | Services | performance | FOUNDATION | Disables the print spooler if you have no printers. |
| 428 | `svc-007` | Disable Xbox Services | Services | performance | FOUNDATION | Disables the Xbox Live services. |
| 429 | `svc-010` | Disable Bluetooth Support | Services | performance | FOUNDATION | Disables the Bluetooth service if unused. |
| 430 | `svc-011` | Disable Fax Service | Services | foundation | FREE | Disables the Fax service. |
| 431 | `svc-012` | Disable Touch Keyboard Service | Services | performance | FOUNDATION | Disables the touch keyboard if not needed. |
| 432 | `svc-013` | Disable Phone Service | Services | performance | FOUNDATION | Disables the Phone Link service. |
| 433 | `svc-016` | Disable Infrared Service | Services | foundation | FREE | Disables the infrared device service. |
| 434 | `svc-019` | Disable Windows Insider Service | Services | foundation | FREE | Disables the Windows Insider Preview service. |
| 435 | `start-005` | Enable Multi-Core Boot | Startup | performance | FOUNDATION | Uses all CPU cores while booting Windows. |
| 436 | `start-012` | Disable Automatic Sign-in Animations | Startup | foundation | FREE | Disables the Windows logon background image and sign-in animation. |
| 437 | `start-016` | Disable Maintenance Tasks | Startup | performance | FOUNDATION | Disables the automatic Windows Maintenance scheduler. |
| 438 | `stor-001` | Enable SSD TRIM | Storage | foundation | FREE | Turns on the TRIM command for SSD/NVMe drives. |
| 439 | `stor-002` | Disable 8.3 Short Names | Storage | performance | FOUNDATION | Stops NTFS from generating legacy 8.3 filenames. |
| 440 | `stor-004` | MFT Zone Reservation | Storage | performance | FOUNDATION | Reserves extra space for the NTFS Master File Table. |
| 441 | `stor-005` | Disable HDD Idle Spin-Down | Storage | foundation | FREE | Prevents the hard drive from spinning down during long sessions. |
| 442 | `stor-006` | Disable Scheduled Defragmentation | Storage | performance | FOUNDATION | Disables the automatic disk defrag task. |
| 443 | `stor-007` | Disable Storage Sense | Storage | foundation | FREE | Turns off automatic storage cleanup. |
| 444 | `stor-016` | Optimize NTFS Last Access | Storage | foundation | FREE | Disables NTFS last-access timestamp updates to reduce metadata writes on every file read. |
| 445 | `sys-002` | Do Not Clear Pagefile at Shutdown | System | foundation | FREE | Skips clearing the pagefile during shutdown. |
| 446 | `sys-004` | Disable Windows Error Reporting | System | foundation | FREE | Turns off WER popups and background report submission. |
| 447 | `sys-006` | Disable Auto Reboot on Crash | System | foundation | FREE | Prevents automatic restart after a system failure. |
| 448 | `sys-007` | Enable Long Paths | System | foundation | FREE | Enables Win32 long path support (>260 chars). |
| 449 | `sys-009` | Boot Manager Timeout 0 | System | performance | FOUNDATION | Removes the boot manager selection delay. |
| 450 | `sys-010` | Disable Automatic Driver Downloads | System | maximum | MAXIMUM | Stops Windows Update from automatically installing drivers. |
| 451 | `sys-012` | Fast App Shutdown Timeouts | System | maximum | MAXIMUM | Reduces how long Windows waits for hung applications at shutdown. |
| 452 | `sys-013` | Auto-End Tasks at Logoff | System | performance | FOUNDATION | Forces hung applications to close when you log off. |
| 453 | `sys-014` | Disable Drive AutoRun | System | foundation | FREE | Disables AutoRun for all drive types. |
| 454 | `sys-015` | Disable Aero Shake | System | foundation | FREE | Turns off the Aero Shake minimize gesture. |
| 455 | `sys-016` | Disable Minimize Animation | System | foundation | FREE | Turns off window minimize/restore animations. |
| 456 | `sys-017` | Disable Notification Center | System | performance | FOUNDATION | Turns off the notification center via policy. |
| 457 | `sys-019` | Disable 'Start Full-Screen Optimizations' Help | System | foundation | FREE | Turns off the fullscreen optimization compatibility help overlay. |
| 458 | `sys-021` | Reduce Hung App Timeout | System | performance | FOUNDATION | Lowers the threshold before Windows considers an app hung. |
| 459 | `tel-002` | Disable Compatibility Telemetry | Telemetry | foundation | FREE | Turns off the compatibility appraiser telemetry. |
| 460 | `tel-003` | Disable Inventory Collector | Telemetry | foundation | FREE | Disables the Device Inventory Collector. |
| 461 | `tel-004` | Disable Activity History | Telemetry | foundation | FREE | Turns off activity history tracking. |
| 462 | `tel-005` | Disable Advertising ID | Telemetry | foundation | FREE | Turns off the advertising ID. |
| 463 | `tel-009` | Disable Windows Update Telemetry | Telemetry | foundation | FREE | Sets Windows Data Collection telemetry level to minimum. |
| 464 | `tel-010` | Disable Feedback Requests | Telemetry | foundation | FREE | Turns off Windows feedback prompts. |
| 465 | `tel-012` | Disable Location Service | Telemetry | foundation | FREE | Turns off location access. |
| 466 | `tel-013` | Disable Find My Device | Telemetry | foundation | FREE | Turns off device-finder telemetry. |
| 467 | `tel-016` | Disable App Diagnostics | Telemetry | foundation | FREE | Turns off per-app diagnostic data access. |
| 468 | `tel-017` | Disable Customer Experience | Telemetry | foundation | FREE | Disables the Customer Experience Improvement Program. |
| 469 | `tel-019` | Disable Diagnostic Data Viewer | Telemetry | foundation | FREE | Disables the Diagnostic Data Viewer plugin. |
| 470 | `usb-001` | Disable USB Selective Suspend | USB | foundation | FREE | Turns off USB selective suspend in the active power scheme. |
| 471 | `usb-006` | Disable USB Host Controller Power Management | USB | performance | FOUNDATION | Disables power management on all USB host controllers to prevent input device sleep. |
| 472 | `usb-014` | Set USB Data Queue Size | USB | performance | FOUNDATION | Sets the minimum USB transfer bytes to zero for lower latency. |
| 473 | `usb-015` | Disable USB Hub Power Management | USB | foundation | FREE | Disables 'Allow the computer to turn off this device' on selected USB hubs. |
| 474 | `usb-016` | Disable HID Keyboard/Mouse Power Management | USB | foundation | FREE | Disables 'Allow the computer to turn off this device' for detected HID keyboard and mouse instances. |
| 475 | `usb-017` | Disable Bluetooth HID Power Saving | USB | performance | FOUNDATION | Disables power-saving on the Bluetooth HID adapter that serves BT keyboards and mice. |
| 476 | `wifi-001` | Disable Wi-Fi Power Saving | Wi-Fi | foundation | FREE | Turns off power management on the wireless adapter. |
| 477 | `wifi-002` | Highest Roaming Aggressiveness | Wi-Fi | performance | FOUNDATION | Sets roaming aggressiveness to its highest value. |
| 478 | `wifi-003` | Disable LSO on Wi-Fi | Wi-Fi | performance | FOUNDATION | Turns off Large Send Offload on the wireless adapter. |
| 479 | `wifi-005` | Prefer 5 GHz / 6 GHz Band | Wi-Fi | foundation | FREE | Sets the wireless adapter preferred band to 5 GHz / 6 GHz. |
| 480 | `wifi-007` | Disable Auto-Connect to Hotspots | Wi-Fi | foundation | FREE | Stops automatic connections to suggested open hotspots via registry. |
| 481 | `wifi-009` | Disable Wake on Magic Packet (Wi-Fi) | Wi-Fi | foundation | FREE | Turns off wireless Wake-on-LAN. |
| 482 | `wifi-010` | Disable LSO IPv6 (Wi-Fi) | Wi-Fi | performance | FOUNDATION | Turns off IPv6 large send offload on Wi-Fi. |
| 483 | `wifi-011` | Disable Background Scanning | Wi-Fi | foundation | FREE | Reduces frequent wireless background scans via registry. |
| 484 | `win-005` | Disable Balloon Tip Notifications | Windows | foundation | FREE | Turns off Explorer balloon tips and toasts. |
| 485 | `win-006` | Visual Effects: Best Performance | Windows | foundation | FREE | Sets the system visual effects preset to 'best performance'. |
| 486 | `win-007` | Menu Show Delay 0 | Windows | foundation | FREE | Removes the delay before submenus open. |
| 487 | `win-008` | Disable Transparency Effects | Windows | foundation | FREE | Turns off acrylic/blur transparency in the UI. |
| 488 | `win-009` | Disable Windows Tips and Suggestions | Windows | foundation | FREE | Disables the Start/tips content delivered by Windows. |
| 489 | `win-012` | Disable Web Search in Start | Windows | foundation | FREE | Stops Start menu web search results. |
| 490 | `win-013` | Disable Cortana | Windows | foundation | FREE | Turns off Cortana via policy. |
| 491 | `win-014` | Disable Bing Search in Start | Windows | foundation | FREE | Disables Bing results in Windows Search. |
| 492 | `win-015` | Legacy Windows 10 Context Menu | Windows | foundation | FREE | Restores the classic full context menu in Windows 11. |
| 493 | `win-017` | Disable First Sign-in Animation | Windows | foundation | FREE | Skips the Windows welcome/first-sign-in animation. |
| 494 | `win-018` | Disable Start Menu App Suggestions | Windows | foundation | FREE | Removes promoted app suggestions from the Start menu. |
| 495 | `win-019` | Disable Timeline | Windows | foundation | FREE | Turns off Windows Timeline activity history tracking. |
| 496 | `win-021` | Disable Search Cloud | Windows | foundation | FREE | Stops Windows Search from fetching cloud/web results. |
| 497 | `win-022` | Disable Search Box Suggestions | Windows | foundation | FREE | Turns off predictive suggestions in the Windows Search box. |
| 498 | `win-023` | Disable News and Interests | Windows | foundation | FREE | Turns off the News and Interests widget on the taskbar. |
| 499 | `expl-001` | Show Hidden Files | Windows Explorer | foundation | FREE | Displays hidden files and folders in Explorer. |
| 500 | `expl-002` | Show Protected Operating System Files | Windows Explorer | foundation | FREE | Reveals protected system files in Explorer. |
| 501 | `expl-003` | Show File Name Extensions | Windows Explorer | foundation | FREE | Displays full file name extensions. |
| 502 | `expl-004` | Disable Thumbnail Cache | Windows Explorer | foundation | FREE | Stops Explorer from generating thumbnail previews. |
| 503 | `expl-005` | Disable Network Thumbnail Cache | Windows Explorer | foundation | FREE | Turns off thumbnail caching for network folders. |
| 504 | `expl-006` | Disable thumbs.db Creation | Windows Explorer | foundation | FREE | Stops creation of thumbs.db database files on network folders. |
| 505 | `expl-007` | Enlarge Icon Cache | Windows Explorer | foundation | FREE | Raises the shell icon cache size to 8192 entries. |
| 506 | `expl-008` | Explorer Opens to This PC | Windows Explorer | foundation | FREE | Changes File Explorer's default landing page to This PC. |
| 507 | `expl-009` | Disable Recent Item Tracking | Windows Explorer | foundation | FREE | Stops Start menu and jump list from tracking opened items. |
| 508 | `expl-010` | Full Path in Explorer Title Bar | Windows Explorer | foundation | FREE | Shows the complete folder path in the window title bar. |
| 509 | `expl-011` | Hide Taskbar Search Box | Windows Explorer | foundation | FREE | Reduces the taskbar search box to an icon (or removes it). |
| 510 | `expl-012` | Disable Search Highlights | Windows Explorer | foundation | FREE | Turns off the search box highlights content. |
| 511 | `expl-013` | Explorer Compact Mode | Windows Explorer | foundation | FREE | Enables compact spacing in Windows 11 Explorer. |
| 512 | `wgr-003` | Disable Auto HDR | Windows Graphics | foundation | FREE | Disables Windows Auto HDR via policy registry key. |
| 513 | `wgr-006` | Restore MPO Composition | Windows Graphics | performance | FOUNDATION | Re-enables Multiplane Overlay (undo of the MPO disable tweak). |
| 514 | `wgr-012` | Reset Graphics Settings | Windows Graphics | performance | FOUNDATION | Deletes Windows' per-app DirectX GPU preference blob (stale per-app assignments and performance flags are removed at once). |
| 515 | `wgr-013` | DirectX Graphics Flags | Windows Graphics | performance | FOUNDATION | Sets all four DirectXUserGlobalSettings performance flags in one write (replaces the old four separate cards that fought over one value). |

# 🖼️ Windows Wallpaper Slideshow (Native Win32 / C++ Edition)

A high-performance, battery-friendly background wallpaper slideshow tool for **Windows 10 & 11**, designed specifically for Ultrabooks (Galaxy Book, Intel Core Ultra). It integrates natively with Windows Desktop Slideshow via the COM `IDesktopWallpaper` interface, providing smooth, hardware-accelerated desktop crossfades, tray control, custom intervals, and near-zero power consumption (< 100 KB RAM).

---

## ⚡ Key Highlights & Maximum Energy Efficiency

1. **Native Win32 / C++ Architecture (< 100 KB RAM):**
   - Pure machine-code binary compiled with Clang. Zero runtime dependency, no Python interpreter, no garbage collection wakeups.
2. **Native Windows Slideshow with Hardware-Accelerated Smooth Fade (Crossfade):**
   - Seamlessly uses the Windows COM `IDesktopWallpaper` interface (`SetSlideshow` & `AdvanceSlideshow`).
   - Keeps Windows in native **Slideshow** mode. Every transition is an ultra-fluid DWM crossfade.
3. **0.0% CPU in Idle (Pure Kernel Wait):**
   - No polling loops. The thread waits directly in the blocking Windows message pump (`GetMessageW`).
   - Deepest **Package C-States (C8–C10)** remain completely undisturbed between intervals.
4. **Windows 11 EcoQoS (Efficiency Mode):**
   - Automatically activates `PROCESS_POWER_THROTTLING_EXECUTION_SPEED` and `IDLE_PRIORITY_CLASS`.
   - Windows schedules execution exclusively on energy-efficient **E-Cores** and suppresses CPU clock boost spikes (Turbo Boost).
5. **Event-Driven Power Management (Ultrabook Optimized):**
   - **`GUID_ACDC_POWER_SOURCE`**: Immediate notification when AC power is disconnected/connected.
   - **`PauseOnBattery`**: Optional setting to automatically pause slideshow rotation when on battery power.
   - **`GUID_CONSOLE_DISPLAY_STATE`**: Automatically pauses when the screen turns off (standby / idle timeout).
   - **`WTSRegisterSessionNotification`**: Pauses immediately upon workstation lock (<kbd>Win</kbd> + <kbd>L</kbd>).
   - **`SHQueryUserNotificationState`**: Suppresses transitions during D3D fullscreen games and presentations.
6. **Timer Coalescing (`SetCoalescableTimer`):**
   - Batches wakeups with other pending operating system tasks to avoid isolated CPU wake events.
7. **Windows 11 Virtual-Desktop Bug Auto-Fix:**
   - Automatically cleans up orphaned per-desktop wallpaper registry entries that could otherwise lock Windows 11 into single-picture mode.
8. **Automatic Config Live-Reload:**
   - Re-reads `config.txt` on the fly when the file changes, without restarting.

---

## ⚙️ Configuration (`config.txt`)

```ini
# Pfad zum Bilderordner (Standard: Ordner "Wallpapers" im Programmverzeichnis):
PicturesPath=Wallpapers

# Anzeigedauer pro Bild in Sekunden (z. B. 15):
IntervalSeconds=15

# Bilder zufaellig mischen (true/false):
Shuffle=true

# Diashow automatisch pausieren, wenn ein Spiel/Praesentation im Vollbild laeuft (true/false):
PauseOnFullscreen=true

# Diashow automatisch pausieren, wenn Windows im Akku-Stromsparmodus ist (true/false):
PauseOnBatterySaver=false

# Ultrabook-Power: Automatisch pausieren, sobald das Laptop auf reinem Akkubetrieb laeuft (true/false):
PauseOnBattery=false
```

---

## 🚀 Usage

- **Start:** Double-click `WallpaperSlideshow.exe`.
- **Stop:** Right-click the tray icon and choose **Beenden**, or run `WallpaperSlideshow.exe --stop`.
- **Autostart:** Toggle **Mit Windows starten** directly via the tray icon menu.

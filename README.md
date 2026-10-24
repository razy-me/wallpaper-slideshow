# 🖼️ Windows Wallpaper Slideshow (Ultra-Energy-Efficient & Native)

A lightweight, battery-friendly background wallpaper slideshow tool for **Windows 10 & 11**. It cycles through pictures in your configured folder with native, smooth, flicker-free Windows desktop crossfades, tray control, and near-zero power consumption.

---

## ⚡ Key Highlights & Maximum Energy Efficiency

1. **0.0% CPU in Idle (Pure Kernel Wait):**
   - No polling loops (`while True: sleep(...)`). The background thread sleeps in the blocking Windows message pump (`GetMessage` / `PumpMessages`).
   - 0 interrupts and 0 context switches while waiting. Modern laptop CPUs stay undisturbed in deep **Package C-States (C8–C10)**.
2. **Windows 11 EcoQoS (Efficiency Mode):**
   - Automatically activates `PROCESS_POWER_THROTTLING_EXECUTION_SPEED` and `IDLE_PRIORITY_CLASS`.
   - Windows schedules execution exclusively on energy-efficient **E-Cores** and suppresses CPU clock boost spikes (Turbo Boost) on picture changes.
   - Shows the green efficiency leaf in Windows 11 Task Manager.
3. **Timer Coalescing (`SetCoalescableTimer`):**
   - Batches wakeups with other pending operating system tasks to avoid isolated CPU wake events.
4. **Display-Off Standby (`GUID_CONSOLE_DISPLAY_STATE`):**
   - When your monitor turns off (e.g. after Windows idle timeout), the timer pauses immediately. Zero wakeups and zero wallpaper transitions while the screen is black.
5. **Lock-Screen Auto-Pause (`WTSRegisterSessionNotification`):**
   - Pauses slideshow immediately when workstation is locked (<kbd>Win</kbd> + <kbd>L</kbd>) and resumes upon unlock.
6. **Fullscreen & Gaming Detection (`SHQueryUserNotificationState`):**
   - Suppresses transitions during D3D fullscreen games and presentations (`QUNS_RUNNING_D3D_FULL_SCREEN` / `QUNS_PRESENTATION_MODE`).
7. **Battery Saver Mode Awareness (`GetSystemPowerStatus`):**
   - Detects Windows battery saver mode and can automatically pause rotation to save battery.
8. **Smart Random Shuffle with Cooldown:**
   - Shuffles images randomly while ensuring each picture has a configurable cooldown (e.g. at least 9 other pictures must be shown before repeat).
9. **Automatic Config Live-Reload:**
   - Automatically re-reads `config.txt` in the background every 3 intervals. Changes to interval time, pictures directory, or shuffle settings apply on the fly without restarting.
10. **Ultra-Low Memory Footprint (~12–18 MB):**
    - Direct DWM hardware-accelerated crossfades without external image manipulation dependencies.
    - Aggressive working set trimming (`EmptyWorkingSet`) returns unused heap memory to the OS.

---

## ⚙️ Configuration (`config.txt`)

On first launch, `config.txt` is created automatically (based on `config.default.txt`):

```ini
# Path to your pictures folder (default: %USERPROFILE%\Pictures):
PicturesPath=C:\Users\YourUsername\Pictures

# Display duration per picture in seconds:
IntervalSeconds=30

# Shuffle images randomly (true/false):
Shuffle=true

# Cooldown: Minimum number of other pictures before repeat (e.g. 9):
Cooldown=9

# Automatically pause when Windows Battery Saver is active (true/false):
PauseOnBatterySaver=false
```

---

## 🚀 Quick Start

### Prerequisites
- Windows 10 or Windows 11 (64-bit recommended)
- Python 3.8+ with `pywin32`:
  ```cmd
  pip install -r requirements.txt
  ```

### Controls
- **Start:** Double-click `start.bat` (runs silently in background using `pythonw.exe`).
- **Stop:** Double-click `stop.bat` or choose **Beenden / Exit** in the system tray menu.
- **Autostart:** Double-click `install_autostart.bat` or toggle **Mit Windows starten** in the tray menu.

### System Tray Menu (bottom right next to system clock)
- **Left click / Double click:** Skip to next picture immediately.
- **Right-click menu:**
  - ⏭ **Nächstes Bild** (Next picture)
  - ⏮ **Vorheriges Bild** (Previous picture from history)
  - ⏸ **Diashow pausieren** / ▶ **Diashow fortsetzen** (Pause / Resume)
  - 📁 **Bilderordner öffnen** (Open pictures folder)
  - 🔄 **Bilder neu einlesen** (Reload images and config immediately)
  - ⚙ **Einstellungen** (Open `config.txt`)
  - 🔋 **Bei Windows-Stromsparmodus pausieren** (Toggle battery saver auto-pause)
  - 🚀 **Mit Windows starten** (Toggle Windows autostart)
  - ❌ **Beenden** (Exit)

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

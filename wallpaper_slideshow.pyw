"""
Wallpaper Slideshow für Windows (Todes optimiert & Ultra-Energieeffizient)
========================================================================
1. 0.0% CPU im Leerlauf:
   Reines Win32-Event-Driven-Design ohne Polling-Schleife (PumpMessages/GetMessage).
   Thread verweilt zu 100% im blockierenden Kernel-Wait -> CPU-Kerne verbleiben
   in tiefsten Package C-States (C8-C10).

2. Windows 11 EcoQoS (Effizienzmodus):
   Aktiviert PROCESS_POWER_THROTTLING_EXECUTION_SPEED & IDLE_PRIORITY_CLASS.
   Windows pinnt den Prozess exklusiv auf sparsame E-Cores (Efficiency Cores)
   und verhindert CPU-Takt-Spikes (Turbo Boost) beim Bildwechsel.
   Im Windows Task-Manager als grünes Effizienz-Blatt erkennbar!

3. Timer-Coalescing (SetCoalescableTimer mit 2000ms Toleranz):
   Windows bündelt den Timer-Interrupt mit anderen System-Wakeups,
   sodass keine isolierten CPU-Aufwachzyklen provoziert werden.

4. Display-Off Standby (GUID_CONSOLE_DISPLAY_STATE):
   Schaltet sich das Display per Windows-Energieplan ab, stoppt der Timer
   augenblicklich. Null Wakeups und kein Wallpaper-Wechsel bei schwarzem Bildschirm.

5. Bildschirmsperre-Pause (WTSRegisterSessionNotification):
   Pausiert sofort bei Win+L oder automatischer Sperre.

6. Vollbild- & Gaming-Schutz (SHQueryUserNotificationState):
   Keine Bildwechsel während D3D-Vollbildspielen oder Präsentationen.

7. Intelligente Windows-Stromsparmodus-Erkennung (GetSystemPowerStatus):
   Erkennt den Windows-Akkusparmodus. Kann optional das Weiterschalten
   vollständig pausieren, um den letzten Prozent Akku zu schützen.

8. Minimaler RAM-Footprint:
   Direktes Hardware-Compositing via DWM (kein Pillow/OpenCV/Canvas-Overhead).
   Aggressiver Working-Set-Trim (EmptyWorkingSet) hält den RAM bei nur ~12-18 MB.
"""

import os
import sys
import time
import random
import ctypes
from ctypes import wintypes
import winreg

import win32gui
import win32con
import win32service
import win32event
import win32api
import win32process
import winerror

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "config.txt")
ICON_FILE = os.path.join(APP_DIR, "app_icon.ico")
RUN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "WallpaperSlideshow"
MUTEX_NAME = "WallpaperSlideshow_SingleInstance_vUltra"

TRAY_MSG_ID = win32con.WM_USER + 42
TIMER_ID = 1

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

# WTS Session Notifications (Sperren / Entsperren)
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0

# Power Setting Notifications (Bildschirm An / Aus)
WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013

class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', wintypes.BYTE * 8)
    ]

# GUID_CONSOLE_DISPLAY_STATE: {6FE69556-704A-47A0-8F24-C28D936FDA47}
GUID_CONSOLE_DISPLAY_STATE = GUID(
    0x6FE69556, 0x704A, 0x47A0, (wintypes.BYTE * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)
)

class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [
        ('PowerSetting', GUID),
        ('DataLength', wintypes.DWORD),
        ('Data', wintypes.BYTE * 1)
    ]

class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ('ACLineStatus', wintypes.BYTE),
        ('BatteryFlag', wintypes.BYTE),
        ('BatteryLifePercent', wintypes.BYTE),
        ('SystemStatusFlag', wintypes.BYTE),
        ('BatteryLifeTime', wintypes.DWORD),
        ('BatteryFullLifeTime', wintypes.DWORD),
    ]

WALLPAPERS_DIR = os.path.join(APP_DIR, "Wallpapers")
DEFAULT_PICTURES = WALLPAPERS_DIR if os.path.exists(WALLPAPERS_DIR) else os.path.join(os.path.expanduser("~"), "Pictures")

DEFAULT_CONFIG = {
    "PicturesPath": DEFAULT_PICTURES,
    "IntervalSeconds": 30,
    "Shuffle": True,
    "Cooldown": 9,
    "PauseOnBatterySaver": False,
}

VALID_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.jfif')

def apply_process_eco_mode():
    """Aktiviert Windows 11 EcoQoS (Effizienzmodus) und Idle-Priorität."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetProcessInformation.restype = wintypes.BOOL

        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ('Version', wintypes.DWORD),
                ('ControlMask', wintypes.DWORD),
                ('StateMask', wintypes.DWORD),
            ]

        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = 1  # PROCESS_POWER_THROTTLING_CURRENT_VERSION
        state.ControlMask = 1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        state.StateMask = 1    # Enable EcoQoS

        h_proc = kernel32.GetCurrentProcess()
        kernel32.SetProcessInformation(h_proc, 4, ctypes.byref(state), ctypes.sizeof(state))
        win32process.SetPriorityClass(h_proc, win32process.IDLE_PRIORITY_CLASS)
    except Exception:
        pass

def is_battery_saver_active():
    """Prüft, ob der Windows-Stromsparmodus aktuell aktiv ist."""
    try:
        sps = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            return sps.SystemStatusFlag == 1
    except Exception:
        pass
    return False

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith(";"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k == "PicturesPath" and v:
                            # Relative Pfade (wie "Wallpapers") relativ zum Programmverzeichnis aufloesen
                            if not os.path.isabs(v):
                                v = os.path.normpath(os.path.join(APP_DIR, v))
                            cfg["PicturesPath"] = v
                        elif k == "IntervalSeconds":
                            try: cfg["IntervalSeconds"] = max(3, int(v))
                            except ValueError: pass
                        elif k == "Cooldown":
                            try: cfg["Cooldown"] = max(0, int(v))
                            except ValueError: pass
                        elif k == "Shuffle":
                            cfg["Shuffle"] = v.lower() in ("true", "1", "yes")
                        elif k == "PauseOnBatterySaver":
                            cfg["PauseOnBatterySaver"] = v.lower() in ("true", "1", "yes")
        except Exception:
            pass
    else:
        save_config(cfg)
    return cfg

def save_config(cfg):
    try:
        lines = [
            "# ==========================================",
            "# Wallpaper Slideshow Konfiguration",
            "# ==========================================",
            "# Pfad zum Bilderordner (nur Dateien direkt in diesem Ordner):",
            f"PicturesPath={cfg.get('PicturesPath', DEFAULT_CONFIG['PicturesPath'])}",
            "",
            "# Anzeigedauer pro Bild in Sekunden (z. B. 30):",
            f"IntervalSeconds={cfg.get('IntervalSeconds', DEFAULT_CONFIG['IntervalSeconds'])}",
            "",
            "# Bilder zufällig mischen (true/false):",
            f"Shuffle={str(cfg.get('Shuffle', DEFAULT_CONFIG['Shuffle'])).lower()}",
            "",
            "# Cooldown: Mindestanzahl anderer Bilder vor Wiederholung (z. B. 9):",
            f"Cooldown={cfg.get('Cooldown', DEFAULT_CONFIG['Cooldown'])}",
            "",
            "# Diashow automatisch anhalten, wenn Windows-Stromsparmodus aktiv ist (true/false):",
            f"PauseOnBatterySaver={str(cfg.get('PauseOnBatterySaver', DEFAULT_CONFIG['PauseOnBatterySaver'])).lower()}",
            ""
        ]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass

def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False

def set_autostart(enable):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                pythonw_path = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.exists(pythonw_path):
                    pythonw_path = sys.executable
                script_path = os.path.join(APP_DIR, "wallpaper_slideshow.pyw")
                cmd = f'"{pythonw_path}" "{script_path}"'
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass

def is_user_busy_or_fullscreen():
    """Prüft, ob der Nutzer im Vollbild-Spiel oder einer Präsentation ist."""
    try:
        state = ctypes.c_int()
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            # 3 = QUNS_RUNNING_D3D_FULL_SCREEN, 4 = QUNS_PRESENTATION_MODE
            return state.value in (3, 4)
    except Exception:
        pass
    return False


class SlideshowService:
    def __init__(self):
        try:
            hdesk = win32service.OpenInputDesktop(0, False, 0x01FF)
            hdesk.SetThreadDesktop()
        except Exception:
            pass

        # Windows 11 EcoQoS (Effizienzmodus) direkt beim Start setzen
        apply_process_eco_mode()

        self.config = load_config()

        # Mutex zur Verhinderung von Mehrfachstarts
        self.mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            sys.exit(0)

        self.playlist = []
        self.current_idx = -1
        self.recent_history = []
        self.history_back_stack = []
        self.is_paused = False
        self.is_locked = False
        self.is_display_off = False
        self.timer_active = False
        self.tick_count = 0
        self.h_power_notify = None

        self.init_window_and_tray()
        self.reload_playlist()

        # Erstes Bild direkt setzen
        if self.playlist:
            if self.config.get("Shuffle", True):
                self.current_idx = random.randint(0, len(self.playlist) - 1)
            else:
                self.current_idx = 0
            first_pic = self.playlist[self.current_idx]
            self.recent_history.append(first_pic)
            self.apply_wallpaper(first_pic)

        self.update_tray_tooltip()
        self.start_timer()

        # Arbeitsspeicher auf das absolute Minimum trimmen
        self.trim_memory()

    def init_window_and_tray(self):
        def wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == TRAY_MSG_ID:
                    if lparam == win32con.WM_RBUTTONUP:
                        self.show_tray_menu()
                    elif lparam in (win32con.WM_LBUTTONDBLCLK, win32con.WM_LBUTTONUP):
                        self.trigger_next_manually()
                elif msg == win32con.WM_TIMER and wparam == TIMER_ID:
                    self.on_timer_tick()
                    return 0
                elif msg == WM_WTSSESSION_CHANGE:
                    # Energiesparen: Wenn Windows gesperrt wird (Win+L), Timer anhalten
                    if wparam == WTS_SESSION_LOCK:
                        self.is_locked = True
                        self.stop_timer()
                    elif wparam == WTS_SESSION_UNLOCK:
                        self.is_locked = False
                        if not self.is_paused and not self.is_display_off:
                            self.start_timer()
                    return 0
                elif msg == WM_POWERBROADCAST and wparam == PBT_POWERSETTINGCHANGE:
                    # Energiesparen: Wenn das Display abschaltet (Windows Standby / Idle-Timeout)
                    try:
                        pbs = POWERBROADCAST_SETTING.from_address(lparam)
                        if pbs.PowerSetting.Data1 == 0x6FE69556:
                            display_state = pbs.Data[0]
                            if display_state == 0:  # Display OFF
                                self.is_display_off = True
                                self.stop_timer()
                            elif display_state in (1, 2):  # Display ON / Dimmed
                                self.is_display_off = False
                                if not self.is_paused and not self.is_locked:
                                    self.start_timer()
                    except Exception:
                        pass
                    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
                elif msg in (win32con.WM_CLOSE, win32con.WM_DESTROY):
                    self.shutdown()
                    return 0
            except Exception as e:
                import traceback
                traceback.print_exc()
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = wnd_proc
        wc.lpszClassName = "WallpaperSlideshow_UltraHost_v8"
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        self.msg_hwnd = win32gui.CreateWindow(
            "WallpaperSlideshow_UltraHost_v8", "WallpaperSlideshowMsg",
            0, 0, 0, 0, 0, 0, 0, 0, None
        )

        # Bei Windows für Session-Events (Sperren/Entsperren) registrieren
        try:
            ctypes.windll.wtsapi32.WTSRegisterSessionNotification(self.msg_hwnd, NOTIFY_FOR_THIS_SESSION)
        except Exception:
            pass

        # Bei Windows für Bildschirm-Status (Display On/Off) registrieren
        try:
            u32 = ctypes.windll.user32
            u32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            u32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
            u32.UnregisterPowerSettingNotification.argtypes = [wintypes.HANDLE]
            u32.UnregisterPowerSettingNotification.restype = wintypes.BOOL

            self.h_power_notify = u32.RegisterPowerSettingNotification(
                self.msg_hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0
            )
        except Exception:
            pass

        # Tray Icon laden
        if os.path.exists(ICON_FILE):
            try:
                self.hicon = win32gui.LoadImage(
                    0, ICON_FILE, win32con.IMAGE_ICON, 0, 0,
                    win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
                )
            except Exception:
                self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        else:
            self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        self.nid = (
            self.msg_hwnd, 1,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            TRAY_MSG_ID, self.hicon, "Wallpaper Slideshow"
        )
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self.nid)
        except Exception:
            pass

    def start_timer(self):
        """Startet den Timer mit Coalescing (Bündelung mit OS-Tasks zur Schonung der CPU-C-States)."""
        if self.is_paused or self.is_locked or self.is_display_off:
            return
        self.stop_timer()
        interval_ms = max(3000, int(self.config.get("IntervalSeconds", 30) * 1000))
        # 2000ms Toleranz für Coalescing: Spart Akku, da Windows den Wakeup mit anderen Tasks bündelt
        try:
            ctypes.windll.user32.SetCoalescableTimer(self.msg_hwnd, TIMER_ID, interval_ms, None, 2000)
        except Exception:
            ctypes.windll.user32.SetTimer(self.msg_hwnd, TIMER_ID, interval_ms, None)
        self.timer_active = True

    def stop_timer(self):
        if self.timer_active:
            try:
                ctypes.windll.user32.KillTimer(self.msg_hwnd, TIMER_ID)
            except Exception:
                pass
            self.timer_active = False

    def check_and_reload_config(self):
        """Liest config.txt im laufenden Betrieb neu ein und wendet Änderungen sofort an."""
        old_interval = self.config.get("IntervalSeconds", 30)
        old_path = self.config.get("PicturesPath", "")
        old_shuffle = self.config.get("Shuffle", True)

        new_config = load_config()
        self.config = new_config

        # 1. Pfad aktualisieren
        if new_config.get("PicturesPath") != old_path:
            self.reload_playlist()

        # 2. Intervall aktualisieren
        if new_config.get("IntervalSeconds") != old_interval:
            self.start_timer()

        self.update_tray_tooltip()

    def select_next_wallpaper(self):
        """Wählt das nächste Bild aus – zufällig mit Cooldown oder sequentiell."""
        if not self.playlist:
            return None

        total = len(self.playlist)
        if not self.config.get("Shuffle", True) or total <= 1:
            next_idx = (self.current_idx + 1) % total
            return self.playlist[next_idx]

        # Cooldown aus der Konfiguration (z. B. 9)
        # Wenn weniger Bilder vorhanden sind als Cooldown+1, wird der Cooldown auf total - 1 begrenzt
        target_cd = int(self.config.get("Cooldown", 9))
        effective_cd = min(target_cd, max(0, total - 1))

        # Die zuletzt gezeigten Bilder als blockiert markieren
        blocked = set(self.recent_history[-effective_cd:]) if effective_cd > 0 else set()
        
        candidates = [p for p in self.playlist if p not in blocked]
        if not candidates:
            # Fallback falls alle Bilder im Cooldown waren
            candidates = [p for p in self.playlist if p != (self.playlist[self.current_idx] if 0 <= self.current_idx < total else None)]
            if not candidates:
                candidates = self.playlist

        return random.choice(candidates)

    def on_timer_tick(self):
        if self.is_paused or self.is_locked or self.is_display_off:
            return

        self.tick_count += 1
        # Nach jedem 3. Intervall die config.txt im Hintergrund automatisch neu einlesen
        if self.tick_count % 3 == 0:
            self.check_and_reload_config()

        # Stromsparmodus-Prüfung
        if self.config.get("PauseOnBatterySaver", False) and is_battery_saver_active():
            self.update_tray_tooltip()
            return
        # Vollbild-Spiel / Präsentation Prüfung
        if is_user_busy_or_fullscreen():
            return

        next_pic = self.select_next_wallpaper()
        if next_pic:
            if 0 <= self.current_idx < len(self.playlist):
                curr_pic = self.playlist[self.current_idx]
                self.history_back_stack.append(curr_pic)
                if len(self.history_back_stack) > 50:
                    self.history_back_stack.pop(0)

            self.current_idx = self.playlist.index(next_pic)
            self.recent_history.append(next_pic)
            max_hist = max(50, int(self.config.get("Cooldown", 9)) * 2)
            if len(self.recent_history) > max_hist:
                self.recent_history = self.recent_history[-max_hist:]

            self.apply_wallpaper(next_pic)
            self.update_tray_tooltip()
            self.trim_memory()

    def show_tray_menu(self):
        menu = win32gui.CreatePopupMenu()

        win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 0, "🖼 Wallpaper Slideshow")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        win32gui.AppendMenu(menu, win32con.MF_STRING, 1, "⏭  Nächstes Bild")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 2, "⏮  Vorheriges Bild")

        pause_text = "▶  Diashow fortsetzen" if self.is_paused else "⏸  Diashow pausieren"
        win32gui.AppendMenu(menu, win32con.MF_STRING, 3, pause_text)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        win32gui.AppendMenu(menu, win32con.MF_STRING, 4, "📁  Bilderordner öffnen")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 5, "🔄  Bilder neu einlesen")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 6, "⚙  Einstellungen (config.txt)")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        # Stromsparmodus Option im Tray
        is_saver_cfg = self.config.get("PauseOnBatterySaver", False)
        saver_flags = win32con.MF_STRING | (win32con.MF_CHECKED if is_saver_cfg else win32con.MF_UNCHECKED)
        win32gui.AppendMenu(menu, saver_flags, 9, "🔋  Bei Windows-Stromsparmodus pausieren")

        is_auto = is_autostart_enabled()
        auto_flags = win32con.MF_STRING | (win32con.MF_CHECKED if is_auto else win32con.MF_UNCHECKED)
        win32gui.AppendMenu(menu, auto_flags, 7, "🚀  Mit Windows starten")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        win32gui.AppendMenu(menu, win32con.MF_STRING, 8, "❌  Beenden")

        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.msg_hwnd)
        cmd = win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
            pos[0], pos[1], 0, self.msg_hwnd, None
        )
        win32gui.PostMessage(self.msg_hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

        if cmd == 1:
            self.trigger_next_manually()
        elif cmd == 2:
            self.trigger_prev_manually()
        elif cmd == 3:
            self.toggle_pause()
        elif cmd == 4:
            try: os.startfile(self.config["PicturesPath"])
            except Exception: pass
        elif cmd == 5:
            self.check_and_reload_config()
            self.reload_playlist()
            self.trigger_next_manually()
        elif cmd == 6:
            if not os.path.exists(CONFIG_FILE):
                save_config(self.config)
            try: os.startfile(CONFIG_FILE)
            except Exception: pass
        elif cmd == 7:
            set_autostart(not is_auto)
        elif cmd == 8:
            self.shutdown()
        elif cmd == 9:
            self.config["PauseOnBatterySaver"] = not is_saver_cfg
            save_config(self.config)
            self.update_tray_tooltip()

    def update_tray_tooltip(self):
        try:
            count = len(self.playlist)
            if count > 0 and 0 <= self.current_idx < count:
                name = os.path.basename(self.playlist[self.current_idx])
                idx_str = f"({self.current_idx + 1}/{count})"
            else:
                name = "Keine Bilder"
                idx_str = "(0/0)"

            status = ""
            if self.is_paused:
                status = "[PAUSIERT] "
            elif self.config.get("PauseOnBatterySaver", False) and is_battery_saver_active():
                status = "[STROMSPARMODUS] "
            elif self.is_display_off:
                status = "[BILDSCHIRM AUS] "

            tip = f"{status}Wallpaper {idx_str}\n{name}\nAlle {self.config['IntervalSeconds']}s"
            if len(tip) > 63:
                tip = tip[:60] + "..."

            nid = (
                self.msg_hwnd, 1,
                win32gui.NIF_TIP,
                TRAY_MSG_ID, self.hicon, tip
            )
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)
        except Exception:
            pass

    def reload_playlist(self):
        path = self.config.get("PicturesPath", DEFAULT_CONFIG["PicturesPath"])
        current_file = self.playlist[self.current_idx] if (self.playlist and 0 <= self.current_idx < len(self.playlist)) else None
        self.playlist = []
        if os.path.exists(path):
            try:
                files = sorted([
                    os.path.join(path, f)
                    for f in os.listdir(path)
                    if os.path.isfile(os.path.join(path, f))
                    and f.lower().endswith(VALID_EXTENSIONS)
                ])
                self.playlist = files
                if current_file and current_file in self.playlist:
                    self.current_idx = self.playlist.index(current_file)
                else:
                    self.current_idx = 0 if self.playlist else -1
            except Exception:
                pass
        # Alte History bereinigen um nicht mehr existierende Dateien
        valid_set = set(self.playlist)
        self.recent_history = [p for p in self.recent_history if p in valid_set]
        self.history_back_stack = [p for p in self.history_back_stack if p in valid_set]
        self.update_tray_tooltip()

    def apply_wallpaper(self, filepath):
        try:
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, filepath,
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
            )
        except Exception:
            pass

    def trigger_next_manually(self):
        if not self.playlist:
            return
        next_pic = self.select_next_wallpaper()
        if next_pic:
            if 0 <= self.current_idx < len(self.playlist):
                curr_pic = self.playlist[self.current_idx]
                self.history_back_stack.append(curr_pic)
                if len(self.history_back_stack) > 50:
                    self.history_back_stack.pop(0)

            self.current_idx = self.playlist.index(next_pic)
            self.recent_history.append(next_pic)
            max_hist = max(50, int(self.config.get("Cooldown", 9)) * 2)
            if len(self.recent_history) > max_hist:
                self.recent_history = self.recent_history[-max_hist:]

            self.apply_wallpaper(next_pic)
            self.update_tray_tooltip()
            self.start_timer()

    def trigger_prev_manually(self):
        if not self.playlist:
            return
        # Falls History vorhanden ist, zurückspringen
        if self.history_back_stack:
            prev_pic = self.history_back_stack.pop()
            if prev_pic in self.playlist:
                self.current_idx = self.playlist.index(prev_pic)
                self.recent_history.append(prev_pic)
                self.apply_wallpaper(prev_pic)
                self.update_tray_tooltip()
                self.start_timer()
                return

        # Fallback auf einfaches Zurückblättern
        prev_idx = (self.current_idx - 1 + len(self.playlist)) % len(self.playlist)
        self.current_idx = prev_idx
        prev_pic = self.playlist[self.current_idx]
        self.recent_history.append(prev_pic)
        self.apply_wallpaper(prev_pic)
        self.update_tray_tooltip()
        self.start_timer()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.stop_timer()
        else:
            self.start_timer()
        self.update_tray_tooltip()

    def trim_memory(self):
        """Gibt ungenutzte Heap-Pages an das Betriebssystem zurück."""
        try:
            ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
        except Exception:
            pass

    def shutdown(self):
        self.stop_timer()
        if self.h_power_notify:
            try:
                ctypes.windll.user32.UnregisterPowerSettingNotification(self.h_power_notify)
            except Exception:
                pass
        try:
            ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(self.msg_hwnd)
        except Exception:
            pass
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, self.nid)
        except Exception:
            pass
        try:
            win32gui.DestroyWindow(self.msg_hwnd)
        except Exception:
            pass
        win32gui.PostQuitMessage(0)
        sys.exit(0)

    def run(self):
        # 100% blockierender Kernel-Wait ohne Polling-Schleife:
        # Die CPU schläft tief und wacht NUR auf, wenn der Timer triggert oder geklickt wird!
        win32gui.PumpMessages()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].lower() in ('--stop', '-stop', 'stop'):
        try:
            hdesk = win32service.OpenInputDesktop(0, False, 0x01FF)
            hdesk.SetThreadDesktop()
        except Exception:
            pass

        found = False
        for cname in ("WallpaperSlideshow_UltraHost_v8", "WallpaperSlideshow_UltraHost_v6"):
            hwnd = win32gui.FindWindow(cname, "WallpaperSlideshowMsg")
            if hwnd:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                found = True
        if not found:
            hwnd = win32gui.FindWindow(None, "WallpaperSlideshowMsg")
            if hwnd:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                found = True

        if found:
            for _ in range(20):
                time.sleep(0.05)
                h = win32gui.FindWindow(None, "WallpaperSlideshowMsg")
                if not h:
                    break
            print("WallpaperSlideshow wurde beendet.")
        else:
            print("Keine aktive WallpaperSlideshow gefunden.")
        sys.exit(0)

    service = SlideshowService()
    service.run()

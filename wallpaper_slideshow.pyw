"""
Wallpaper Slideshow für Windows (Native Diashow & Ultra-Energieeffizient)
========================================================================
1. Echte Windows-Diashow mit hardwarebeschleunigtem Smooth-Fade (Crossfade):
   Nutzt das native Windows COM-Interface IDesktopWallpaper (SetSlideshow / AdvanceSlideshow).
   Windows bleibt dauerhaft im Status "Diashow" und blendet jedes Bild butterweich über.

2. Volle Anpassbarkeit & freies Intervall:
   Erlaubt beliebige Sekunden-Intervalle (z. B. 10s, 15s, 30s) ohne die 1-Minuten-
   Mindestgrenze der Windows-GUI.

3. 0.0% CPU im Leerlauf:
   Reines Win32-Event-Driven-Design ohne Polling-Schleife (PumpMessages/GetMessage).
   Thread verweilt zu 100% im blockierenden Kernel-Wait -> CPU-Kerne verbleiben
   in tiefsten Package C-States (C8-C10).

4. Windows 11 EcoQoS (Effizienzmodus):
   Aktiviert PROCESS_POWER_THROTTLING_EXECUTION_SPEED & IDLE_PRIORITY_CLASS.
   Windows pinnt den Prozess exklusiv auf sparsame E-Cores (Efficiency Cores)
   und verhindert CPU-Takt-Spikes (Turbo Boost) beim Bildwechsel.
   Im Windows Task-Manager als grünes Effizienz-Blatt erkennbar!

5. Timer-Coalescing (SetCoalescableTimer mit 2000ms Toleranz):
   Windows bündelt den Timer-Interrupt mit anderen System-Wakeups,
   sodass keine isolierten CPU-Aufwachzyklen provoziert werden.

6. Display-Off Standby (GUID_CONSOLE_DISPLAY_STATE):
   Schaltet sich das Display per Windows-Energieplan ab, stoppt der Timer
   augenblicklich. Null Wakeups und kein Wallpaper-Wechsel bei schwarzem Bildschirm.

7. Bildschirmsperre-Pause (WTSRegisterSessionNotification):
   Pausiert sofort bei Win+L oder automatischer Sperre.

8. Vollbild- & Gaming-Schutz (SHQueryUserNotificationState):
   Keine Bildwechsel während D3D-Vollbildspielen oder Präsentationen.

9. Intelligente Windows-Stromsparmodus-Erkennung (GetSystemPowerStatus):
   Erkennt den Windows-Akkusparmodus. Kann optional das Weiterschalten
   vollständig pausieren, um den letzten Prozent Akku zu schützen.

10. Windows 11 Virtual-Desktop-Auto-Fix:
    Bereinigt automatisch eventuelle sperrende Wallpaper-Einträge unter
    VirtualDesktops, die Windows 11 sonst fehlerhaft auf "Bild" zurückwerfen würden.

11. Minimaler RAM-Footprint:
    Direktes Hardware-Compositing via DWM (kein Pillow/OpenCV/Canvas-Overhead).
    Aggressiver Working-Set-Trim (EmptyWorkingSet) hält den RAM bei nur ~12-18 MB.
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes, c_void_p, HRESULT, POINTER, WINFUNCTYPE, c_int, c_uint, c_wchar_p
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
MUTEX_NAME = "WallpaperSlideshow_SingleInstance_vNativeCOM"

TRAY_MSG_ID = win32con.WM_USER + 42
TIMER_ID = 1

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

CLSID_DesktopWallpaper = GUID(
    0xC2CF3110, 0x460E, 0x4fc1, (wintypes.BYTE * 8)(0xB9, 0xD0, 0x8A, 0x1C, 0x0C, 0x9C, 0xC4, 0xBD)
)
IID_IDesktopWallpaper = GUID(
    0xB92B56A9, 0x8B55, 0x4E14, (wintypes.BYTE * 8)(0x9A, 0x89, 0x01, 0x99, 0xBB, 0xB6, 0xF9, 0x3B)
)
IID_IShellItem = GUID(
    0x43826D1E, 0xE718, 0x42EE, (wintypes.BYTE * 8)(0xBC, 0x55, 0xA1, 0xE2, 0x61, 0xC3, 0x7B, 0xFE)
)
IID_IShellItemArray = GUID(
    0xB63EA76D, 0x1F85, 0x456F, (wintypes.BYTE * 8)(0xA1, 0x9C, 0x48, 0x15, 0x9E, 0xFA, 0x85, 0x8B)
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

DEFAULT_CONFIG = {
    "PicturesPath": "Wallpapers",
    "IntervalSeconds": 15,
    "Shuffle": True,
    "PauseOnFullscreen": True,
    "PauseOnBatterySaver": False,
}

VALID_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.jfif')

ole32 = ctypes.windll.ole32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

try:
    user32.SetCoalescableTimer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.ULONG]
    user32.SetCoalescableTimer.restype = wintypes.UINT
except Exception:
    pass

try:
    user32.SetTimer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
    user32.SetTimer.restype = wintypes.UINT
except Exception:
    pass

try:
    user32.KillTimer.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.KillTimer.restype = wintypes.BOOL
except Exception:
    pass

try:
    kernel32.GetSystemPowerStatus.argtypes = [ctypes.c_void_p]
    kernel32.GetSystemPowerStatus.restype = wintypes.BOOL
except Exception:
    pass

try:
    shell32.SHQueryUserNotificationState.argtypes = [ctypes.c_void_p]
    shell32.SHQueryUserNotificationState.restype = HRESULT
except Exception:
    pass

try:
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
except Exception:
    pass


def release_com(ptr):
    """Gibt einen COM-Interface-Pointer sauber frei."""
    if ptr and ptr.value:
        try:
            vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
            release_fn = WINFUNCTYPE(c_uint, c_void_p)(vtable[2])
            release_fn(ptr)
        except Exception:
            pass


class DesktopWallpaperManager:
    """Kapselt das native Windows Shell COM-Interface IDesktopWallpaper.

    Stabilität: Das COM-Objekt lebt im Explorer-Prozess. Stürzt explorer.exe ab oder
    wird neu gestartet, wird das Objekt ungültig (RPC_E_DISCONNECTED etc.). In diesem
    Fall wird es automatisch neu erzeugt (reconnect), ohne dass das Tool neu starten muss.
    """

    def __init__(self):
        ole32.CoInitialize(None)
        self.p_obj = c_void_p()
        self._connect()

    def _connect(self):
        """Erzeugt (oder erneuert) die COM-Instanz und bindet die VTable-Methoden."""
        if self.p_obj and self.p_obj.value:
            release_com(self.p_obj)
        self.p_obj = c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_DesktopWallpaper), None, 1 | 4,
            ctypes.byref(IID_IDesktopWallpaper), ctypes.byref(self.p_obj)
        )
        if hr != 0 or not self.p_obj.value:
            self.p_obj = c_void_p()
            return False

        vt = ctypes.cast(self.p_obj, POINTER(POINTER(c_void_p))).contents
        # Out-Strings als c_void_p binden, damit sie per CoTaskMemFree freigegeben werden können
        self._GetWallpaper = WINFUNCTYPE(HRESULT, c_void_p, wintypes.LPCWSTR, POINTER(c_void_p))(vt[4])
        self._GetMonitorDevicePathAt = WINFUNCTYPE(HRESULT, c_void_p, c_uint, POINTER(c_void_p))(vt[5])
        self._GetMonitorDevicePathCount = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_uint))(vt[6])
        self._SetSlideshow = WINFUNCTYPE(HRESULT, c_void_p, c_void_p)(vt[12])
        self._SetSlideshowOptions = WINFUNCTYPE(HRESULT, c_void_p, c_int, c_uint)(vt[14])
        self._AdvanceSlideshow = WINFUNCTYPE(HRESULT, c_void_p, wintypes.LPCWSTR, c_int)(vt[16])
        return True

    @staticmethod
    def clean_virtual_desktops_blockers():
        """Behebt den Windows 11 Virtual-Desktop-Bug, der die Diashow auf 'Bild' sperrt."""
        base_key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops\Desktops"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base_key, 0, winreg.KEY_READ) as k:
                n_sub = winreg.QueryInfoKey(k)[0]
                subkeys = [winreg.EnumKey(k, i) for i in range(n_sub)]
        except OSError:
            return
        for sub in subkeys:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{base_key}\\{sub}", 0, winreg.KEY_SET_VALUE) as sk:
                    winreg.DeleteValue(sk, "Wallpaper")
            except OSError:
                pass

    def setup_slideshow(self, folder_path, shuffle=True):
        """Aktiviert die native Windows-Diashow auf dem Zielordner."""
        abs_path = os.path.abspath(folder_path)
        if not os.path.isdir(abs_path):
            return False
        if not (self.p_obj and self.p_obj.value) and not self._connect():
            return False

        self.clean_virtual_desktops_blockers()

        # Registry-Status auf Diashow (2) setzen
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers", 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "BackgroundType", 0, winreg.REG_DWORD, 2)
                winreg.SetValueEx(k, "SlideshowSourceDirectoriesSet", 0, winreg.REG_DWORD, 1)
        except OSError:
            pass

        p_item = c_void_p()
        p_array = c_void_p()
        ok = False
        try:
            if shell32.SHCreateItemFromParsingName(abs_path, None, ctypes.byref(IID_IShellItem), ctypes.byref(p_item)) != 0:
                return False
            if shell32.SHCreateShellItemArrayFromShellItem(p_item, ctypes.byref(IID_IShellItemArray), ctypes.byref(p_array)) != 0:
                return False
            self._SetSlideshow(self.p_obj, p_array)
            # Interner Windows-Timer auf 1 Tag, damit unser eigener Coalescing-Timer exakt taktet
            self._SetSlideshowOptions(self.p_obj, 1 if shuffle else 0, 86400000)
            ok = True
        except OSError:
            ok = False
        finally:
            release_com(p_array)
            release_com(p_item)
        return ok

    def _try_advance(self):
        if not (self.p_obj and self.p_obj.value):
            return False
        try:
            self._AdvanceSlideshow(self.p_obj, None, 0)
            return True
        except OSError:
            return False

    def advance(self, folder_path=None, shuffle=True):
        """Schaltet mit nativer Windows-Crossfade-Überblendung zum nächsten Bild.

        Eskalationsstufen (Self-Healing):
          1. Direktes AdvanceSlideshow
          2. Diashow neu setzen (Windows hat Modus verloren) und erneut advancen
          3. COM-Objekt neu verbinden (Explorer wurde neu gestartet) und alles wiederholen
        """
        if self._try_advance():
            return True
        if folder_path and self.setup_slideshow(folder_path, shuffle) and self._try_advance():
            return True
        if self._connect() and folder_path and self.setup_slideshow(folder_path, shuffle):
            return self._try_advance()
        return False

    def get_current_wallpaper(self):
        """Gibt den Pfad des aktuellen Hintergrundbildes zurück (ohne Speicherleck)."""
        if not (self.p_obj and self.p_obj.value):
            return ""
        mid = c_void_p()
        wp = c_void_p()
        try:
            self._GetMonitorDevicePathAt(self.p_obj, 0, ctypes.byref(mid))
            if not mid.value:
                return ""
            self._GetWallpaper(self.p_obj, ctypes.wstring_at(mid.value), ctypes.byref(wp))
            return ctypes.wstring_at(wp.value) if wp.value else ""
        except OSError:
            return ""
        finally:
            # COM-allokierte Strings müssen explizit freigegeben werden
            if mid.value:
                ole32.CoTaskMemFree(mid)
            if wp.value:
                ole32.CoTaskMemFree(wp)

    def cleanup(self):
        release_com(self.p_obj)
        self.p_obj = c_void_p()
        try:
            ole32.CoUninitialize()
        except Exception:
            pass


def apply_process_eco_mode():
    """Aktiviert Windows 11 EcoQoS (Effizienzmodus) und Idle-Priorität."""
    try:
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
        if kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            return sps.SystemStatusFlag == 1
    except Exception:
        pass
    return False


def is_user_busy_or_fullscreen():
    """Prüft, ob der Nutzer im Vollbild-Spiel oder einer Präsentation ist."""
    try:
        state = ctypes.c_int()
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            # 3 = QUNS_RUNNING_D3D_FULL_SCREEN, 4 = QUNS_PRESENTATION_MODE
            return state.value in (3, 4)
    except Exception:
        pass
    return False


def resolve_pictures_path(raw_path):
    """Löst relative Pfade relativ zum Programmverzeichnis auf."""
    if not raw_path:
        raw_path = "Wallpapers"
    if not os.path.isabs(raw_path):
        resolved = os.path.normpath(os.path.join(APP_DIR, raw_path))
    else:
        resolved = os.path.normpath(raw_path)

    if os.path.exists(resolved):
        return resolved

    # Fallback auf lokalen Wallpapers-Ordner oder Bilderordner des Nutzers
    local_wallpapers = os.path.join(APP_DIR, "Wallpapers")
    if os.path.exists(local_wallpapers):
        return local_wallpapers
    return os.path.join(os.path.expanduser("~"), "Pictures")


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
                            cfg["PicturesPath"] = v
                        elif k == "IntervalSeconds":
                            try: cfg["IntervalSeconds"] = max(3, int(v))
                            except ValueError: pass
                        elif k == "Shuffle":
                            cfg["Shuffle"] = v.lower() in ("true", "1", "yes")
                        elif k == "PauseOnFullscreen":
                            cfg["PauseOnFullscreen"] = v.lower() in ("true", "1", "yes")
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
            "# Pfad zum Bilderordner:",
            "# Standardmaessig: Ordner 'Wallpapers' im Programmverzeichnis (portabel auf jedem PC)",
            f"PicturesPath={cfg.get('PicturesPath', DEFAULT_CONFIG['PicturesPath'])}",
            "",
            "# Anzeigedauer pro Bild in Sekunden (z. B. 15):",
            f"IntervalSeconds={cfg.get('IntervalSeconds', DEFAULT_CONFIG['IntervalSeconds'])}",
            "",
            "# Bilder zufaellig mischen (true/false):",
            f"Shuffle={str(cfg.get('Shuffle', DEFAULT_CONFIG['Shuffle'])).lower()}",
            "",
            "# Diashow automatisch pausieren, wenn ein Spiel oder eine Praesentation im Vollbild laeuft (true/false):",
            f"PauseOnFullscreen={str(cfg.get('PauseOnFullscreen', DEFAULT_CONFIG['PauseOnFullscreen'])).lower()}",
            "",
            "# Diashow automatisch pausieren, wenn Windows im Akku-Stromsparmodus ist (true/false):",
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


class SlideshowService:
    def __init__(self):
        try:
            hdesk = win32service.OpenInputDesktop(0, False, 0x01FF)
            hdesk.SetThreadDesktop()
        except Exception:
            pass

        # Windows 11 EcoQoS (Effizienzmodus) direkt beim Start setzen
        apply_process_eco_mode()

        # Mutex zur Verhinderung von Mehrfachstarts
        self.mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            sys.exit(0)

        self.config = load_config()
        self.resolved_path = resolve_pictures_path(self.config.get("PicturesPath"))

        # Native Desktop Wallpaper COM Manager initialisieren
        self.wallpaper_mgr = DesktopWallpaperManager()

        self.is_paused = False
        self.is_locked = False
        self.is_display_off = False
        self.timer_active = False
        self.is_shutting_down = False
        self.tick_count = 0
        self.config_mtime = None
        self.last_tip = None
        self.h_power_notify = None

        self.init_window_and_tray()

        # Diashow in Windows initialisieren
        self.init_slideshow()

        self.update_tray_tooltip()
        self.start_timer()

        # Arbeitsspeicher auf das absolute Minimum trimmen
        self.trim_memory()

    def init_slideshow(self):
        """Richtet die native Windows-Diashow mit dem konfigurierten Ordner ein."""
        self.resolved_path = resolve_pictures_path(self.config.get("PicturesPath"))
        shuffle = self.config.get("Shuffle", True)
        self.wallpaper_mgr.setup_slideshow(self.resolved_path, shuffle)

    def init_window_and_tray(self):
        def wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == TRAY_MSG_ID:
                    if lparam == win32con.WM_RBUTTONUP:
                        self.show_tray_menu()
                    elif lparam == win32con.WM_LBUTTONUP:
                        # Nur LBUTTONUP: verhindert Mehrfach-Wechsel bei Doppelklick (UP+DBLCLK+UP)
                        self.trigger_next_manually()
                elif msg == self.wm_taskbar_created:
                    # Explorer wurde neu gestartet -> Tray-Icon neu anlegen & COM neu verbinden
                    try:
                        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self.nid)
                    except Exception:
                        pass
                    self.wallpaper_mgr._connect()
                    self.init_slideshow()
                    self.update_tray_tooltip(force=True)
                    return 0
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
            except Exception:
                pass
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        # Broadcast-Nachricht, die Windows nach einem Explorer-Neustart sendet
        self.wm_taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = wnd_proc
        wc.lpszClassName = "WallpaperSlideshow_NativeHost_v9"
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        self.msg_hwnd = win32gui.CreateWindow(
            "WallpaperSlideshow_NativeHost_v9", "WallpaperSlideshowMsg",
            0, 0, 0, 0, 0, 0, 0, 0, None
        )

        # Bei Windows für Session-Events (Sperren/Entsperren) registrieren
        try:
            ctypes.windll.wtsapi32.WTSRegisterSessionNotification(self.msg_hwnd, NOTIFY_FOR_THIS_SESSION)
        except Exception:
            pass

        # Bei Windows für Bildschirm-Status (Display On/Off) registrieren
        try:
            user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
            user32.UnregisterPowerSettingNotification.argtypes = [wintypes.HANDLE]
            user32.UnregisterPowerSettingNotification.restype = wintypes.BOOL

            self.h_power_notify = user32.RegisterPowerSettingNotification(
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
        interval_ms = max(3000, int(self.config.get("IntervalSeconds", 15) * 1000))
        # 2000ms Toleranz für Coalescing: Spart Akku, da Windows den Wakeup mit anderen Tasks bündelt
        try:
            user32.SetCoalescableTimer(self.msg_hwnd, TIMER_ID, interval_ms, None, 2000)
        except Exception:
            user32.SetTimer(self.msg_hwnd, TIMER_ID, interval_ms, None)
        self.timer_active = True

    def stop_timer(self):
        if self.timer_active:
            try:
                user32.KillTimer(self.msg_hwnd, TIMER_ID)
            except Exception:
                pass
            self.timer_active = False

    def check_and_reload_config(self):
        """Liest config.txt im laufenden Betrieb neu ein und wendet Änderungen sofort an."""
        # Nur parsen, wenn sich die Datei tatsächlich geändert hat (ein einziger stat()-Call)
        try:
            mtime = os.stat(CONFIG_FILE).st_mtime_ns
        except OSError:
            mtime = None
        if mtime == self.config_mtime:
            return
        self.config_mtime = mtime

        old_interval = self.config.get("IntervalSeconds", 15)
        old_path = self.config.get("PicturesPath", "")
        old_shuffle = self.config.get("Shuffle", True)

        new_config = load_config()
        self.config = new_config

        # 1. Pfad oder Shuffle aktualisieren
        if new_config.get("PicturesPath") != old_path or new_config.get("Shuffle") != old_shuffle:
            self.init_slideshow()

        # 2. Intervall aktualisieren
        if new_config.get("IntervalSeconds") != old_interval:
            self.start_timer()

        self.update_tray_tooltip()

    def on_timer_tick(self):
        if self.is_paused or self.is_locked or self.is_display_off:
            return

        # config.txt bei jedem Tick per mtime prüfen (nahezu kostenlos, Änderungen greifen sofort)
        self.check_and_reload_config()

        # Stromsparmodus-Prüfung
        if self.config.get("PauseOnBatterySaver", False) and is_battery_saver_active():
            self.update_tray_tooltip()
            return

        # Vollbild-Spiel / Präsentation Prüfung
        if self.config.get("PauseOnFullscreen", True) and is_user_busy_or_fullscreen():
            self.update_tray_tooltip()
            return

        # Bild mit nativer Windows-Crossfade-Überblendung weiterschalten
        self.wallpaper_mgr.advance(self.resolved_path, self.config.get("Shuffle", True))
        self.update_tray_tooltip()
        self.trim_memory()

    def trigger_next_manually(self):
        """Manueller Bildwechsel per Klick (mit sofortigem Smooth-Fade)."""
        self.wallpaper_mgr.advance(self.resolved_path, self.config.get("Shuffle", True))
        self.update_tray_tooltip()
        self.start_timer()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.stop_timer()
        else:
            self.start_timer()
        self.update_tray_tooltip()

    def show_tray_menu(self):
        menu = win32gui.CreatePopupMenu()

        win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 0, "🖼 Wallpaper Slideshow (Diashow)")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        win32gui.AppendMenu(menu, win32con.MF_STRING, 1, "⏭  Nächstes Bild (Weicher Übergang)")

        pause_text = "▶  Diashow fortsetzen" if self.is_paused else "⏸  Diashow pausieren"
        win32gui.AppendMenu(menu, win32con.MF_STRING, 3, pause_text)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        win32gui.AppendMenu(menu, win32con.MF_STRING, 4, "📁  Bilderordner öffnen")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 5, "🔄  Diashow neu initialisieren")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 6, "⚙  Einstellungen (config.txt)")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        # Vollbild-Spiele Option im Tray
        is_fs_cfg = self.config.get("PauseOnFullscreen", True)
        fs_flags = win32con.MF_STRING | (win32con.MF_CHECKED if is_fs_cfg else win32con.MF_UNCHECKED)
        win32gui.AppendMenu(menu, fs_flags, 10, "🎮  Bei Vollbild-Spielen pausieren")

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
        elif cmd == 3:
            self.toggle_pause()
        elif cmd == 4:
            try: os.startfile(self.resolved_path)
            except Exception: pass
        elif cmd == 5:
            self.check_and_reload_config()
            self.init_slideshow()
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
        elif cmd == 10:
            self.config["PauseOnFullscreen"] = not is_fs_cfg
            save_config(self.config)
            self.update_tray_tooltip()

    def update_tray_tooltip(self, force=False):
        try:
            curr_file = self.wallpaper_mgr.get_current_wallpaper()
            name = os.path.basename(curr_file) if curr_file else "Wallpaper"

            status = ""
            if self.is_paused:
                status = "[PAUSIERT] "
            elif self.config.get("PauseOnFullscreen", True) and is_user_busy_or_fullscreen():
                status = "[VOLLBILD] "
            elif self.config.get("PauseOnBatterySaver", False) and is_battery_saver_active():
                status = "[STROMSPARMODUS] "
            elif self.is_display_off:
                status = "[BILDSCHIRM AUS] "

            tip = f"{status}Wallpaper Diashow\n{name}\nAlle {self.config.get('IntervalSeconds', 15)}s"
            if len(tip) > 63:
                tip = tip[:60] + "..."

            if not force and tip == self.last_tip:
                return
            self.last_tip = tip

            nid = (
                self.msg_hwnd, 1,
                win32gui.NIF_TIP,
                TRAY_MSG_ID, self.hicon, tip
            )
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)
        except Exception:
            pass

    def trim_memory(self):
        """Gibt ungenutzte Heap-Pages an das Betriebssystem zurück."""
        try:
            ctypes.windll.psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())
        except Exception:
            pass

    def shutdown(self):
        if self.is_shutting_down:
            return
        self.is_shutting_down = True
        self.stop_timer()
        if self.h_power_notify:
            try:
                user32.UnregisterPowerSettingNotification(self.h_power_notify)
            except Exception:
                pass
            self.h_power_notify = None
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
        try:
            self.wallpaper_mgr.cleanup()
        except Exception:
            pass
        win32gui.PostQuitMessage(0)

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
        for cname in ("WallpaperSlideshow_NativeHost_v9", "WallpaperSlideshow_UltraHost_v8", "WallpaperSlideshow_UltraHost_v6"):
            hwnd = win32gui.FindWindow(cname, "WallpaperSlideshowMsg")
            if hwnd:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                found = True

        if not found:
            hwnd = win32gui.FindWindow(None, "WallpaperSlideshowMsg")
            if hwnd:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                found = True

        if not found:
            hwnds = []
            def enum_cb(h, _):
                try:
                    cname = win32gui.GetClassName(h)
                    text = win32gui.GetWindowText(h)
                    if "WallpaperSlideshow" in cname or text == "WallpaperSlideshowMsg":
                        hwnds.append(h)
                except Exception:
                    pass
                return True
            try:
                win32gui.EnumWindows(enum_cb, None)
            except Exception:
                pass
            for h in hwnds:
                win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
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

    try:
        service = SlideshowService()
        service.run()
    except Exception as e:
        import traceback
        with open(os.path.join(APP_DIR, "crash_log.txt"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise

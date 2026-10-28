// ============================================================================
// Wallpaper Slideshow - Native Win32 / C++ Edition (Ultra Energy Efficient)
// Designed for Ultrabooks (Samsung Galaxy Book, Intel Core Ultra)
// ============================================================================
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#define NTDDI_VERSION NTDDI_WIN10_RS1
#include <windows.h>
#include <initguid.h>
#include <shobjidl.h>
#include <shellapi.h>
#include <wtsapi32.h>
#include <psapi.h>
#include <shlobj.h>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <cwchar>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "wtsapi32.lib")
#pragma comment(lib, "psapi.lib")

// --- Constants & Messages ---
#define TRAY_MSG_ID (WM_USER + 42)
#define TIMER_ID 1
#define MUTEX_NAME L"WallpaperSlideshow_SingleInstance_vNativeCOM"
#define WINDOW_CLASS_NAME L"WallpaperSlideshow_NativeHost_v9"
#define WINDOW_TITLE L"WallpaperSlideshowMsg"
#define RUN_REG_KEY L"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
#define APP_REG_NAME L"WallpaperSlideshow"

// GUIDs
static const GUID GUID_CONSOLE_DISPLAY_STATE_VAL = 
    { 0x6FE69556, 0x704A, 0x47A0, { 0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47 } };

static const GUID GUID_ACDC_POWER_SOURCE_VAL = 
    { 0x5D3E4A00, 0xE986, 0x4A72, { 0xAA, 0x1E, 0x3F, 0x98, 0x4C, 0x60, 0x9A, 0x53 } };

// EcoQoS Structs
typedef struct _PROCESS_POWER_THROTTLING_STATE_CUSTOM {
    ULONG Version;
    ULONG ControlMask;
    ULONG StateMask;
} PROCESS_POWER_THROTTLING_STATE_CUSTOM;

#ifndef ProcessPowerThrottling
#define ProcessPowerThrottling ((PROCESS_INFORMATION_CLASS)4)
#endif
#define PROCESS_POWER_THROTTLING_CURRENT_VERSION 1
#define PROCESS_POWER_THROTTLING_EXECUTION_SPEED 0x1

// --- Config Structure ---
struct AppConfig {
    std::wstring picturesPath = L"Wallpapers";
    int intervalSeconds = 15;
    bool shuffle = true;
    bool pauseOnFullscreen = true;
    bool pauseOnBatterySaver = false;
    bool pauseOnBattery = false; // New Ultrabook feature: pause on pure battery
};

// Global Application State
class SlideshowApp {
public:
    HWND m_hwnd = nullptr;
    NOTIFYICONDATAW m_nid = { 0 };
    HICON m_hIcon = nullptr;
    HPOWERNOTIFY m_hPowerDisplayNotify = nullptr;
    HPOWERNOTIFY m_hPowerAcDcNotify = nullptr;
    HANDLE m_hMutex = nullptr;
    UINT m_wmTaskbarCreated = 0;

    IDesktopWallpaper* m_pWallpaper = nullptr;

    std::wstring m_appDir;
    std::wstring m_configFile;
    std::wstring m_resolvedPicturesPath;
    FILETIME m_configLastWriteTime = { 0 };

    AppConfig m_config;

    bool m_isPaused = false;
    bool m_isLocked = false;
    bool m_isDisplayOff = false;
    bool m_isOnBattery = false;
    bool m_timerActive = false;
    bool m_isShuttingDown = false;
    std::wstring m_lastTip;

    SlideshowApp() {
        // App directory setup
        WCHAR path[MAX_PATH];
        GetModuleFileNameW(nullptr, path, MAX_PATH);
        WCHAR* lastSlash = wcsrchr(path, L'\\');
        if (lastSlash) *lastSlash = L'\0';
        m_appDir = path;
        m_configFile = m_appDir + L"\\config.txt";
    }

    ~SlideshowApp() {
        cleanup();
    }

    void applyEcoMode() {
        HMODULE hKernel = GetModuleHandleW(L"kernel32.dll");
        if (hKernel) {
            typedef BOOL (WINAPI *SetProcessInfoFn)(HANDLE, PROCESS_INFORMATION_CLASS, PVOID, DWORD);
            SetProcessInfoFn fnSetProcessInformation = (SetProcessInfoFn)GetProcAddress(hKernel, "SetProcessInformation");
            if (fnSetProcessInformation) {
                PROCESS_POWER_THROTTLING_STATE_CUSTOM state;
                ZeroMemory(&state, sizeof(state));
                state.Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION;
                state.ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED;
                state.StateMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED;
                fnSetProcessInformation(GetCurrentProcess(), ProcessPowerThrottling, &state, sizeof(state));
            }
        }
        SetPriorityClass(GetCurrentProcess(), IDLE_PRIORITY_CLASS);
    }

    void trimMemory() {
        EmptyWorkingSet(GetCurrentProcess());
    }

    // --- COM / DesktopWallpaper ---
    bool connectCOM() {
        if (m_pWallpaper) {
            m_pWallpaper->Release();
            m_pWallpaper = nullptr;
        }
        HRESULT hr = CoCreateInstance(
            CLSID_DesktopWallpaper, nullptr, CLSCTX_LOCAL_SERVER | CLSCTX_INPROC_SERVER,
            IID_IDesktopWallpaper, (void**)&m_pWallpaper
        );
        return SUCCEEDED(hr) && (m_pWallpaper != nullptr);
    }

    void cleanVirtualDesktopsBlockers() {
        const WCHAR* baseKey = L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\VirtualDesktops\\Desktops";
        HKEY hKey = nullptr;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, baseKey, 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            DWORD subKeysCount = 0;
            DWORD maxSubKeyLen = 0;
            if (RegQueryInfoKeyW(hKey, nullptr, nullptr, nullptr, &subKeysCount, &maxSubKeyLen, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr) == ERROR_SUCCESS) {
                std::vector<WCHAR> buffer(maxSubKeyLen + 2);
                for (DWORD i = 0; i < subKeysCount; ++i) {
                    DWORD len = (DWORD)buffer.size();
                    if (RegEnumKeyExW(hKey, i, buffer.data(), &len, nullptr, nullptr, nullptr, nullptr) == ERROR_SUCCESS) {
                        std::wstring subPath = std::wstring(baseKey) + L"\\" + buffer.data();
                        HKEY hSub = nullptr;
                        if (RegOpenKeyExW(HKEY_CURRENT_USER, subPath.c_str(), 0, KEY_SET_VALUE, &hSub) == ERROR_SUCCESS) {
                            RegDeleteValueW(hSub, L"Wallpaper");
                            RegCloseKey(hSub);
                        }
                    }
                }
            }
            RegCloseKey(hKey);
        }
    }

    std::wstring resolvePicturesPath(const std::wstring& raw) {
        if (raw.empty()) return m_appDir + L"\\Wallpapers";

        std::wstring candidate;
        if (raw.size() >= 2 && (raw[1] == L':' || (raw[0] == L'\\' && raw[1] == L'\\'))) {
            candidate = raw;
        } else {
            candidate = m_appDir + L"\\" + raw;
        }

        DWORD attr = GetFileAttributesW(candidate.c_str());
        if (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY)) {
            return candidate;
        }

        std::wstring localWallpapers = m_appDir + L"\\Wallpapers";
        attr = GetFileAttributesW(localWallpapers.c_str());
        if (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY)) {
            return localWallpapers;
        }

        WCHAR picPath[MAX_PATH];
        if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_MYPICTURES, nullptr, 0, picPath))) {
            return picPath;
        }
        return m_appDir;
    }

    bool setupSlideshow(const std::wstring& folderPath, bool shuffle) {
        DWORD attr = GetFileAttributesW(folderPath.c_str());
        if (attr == INVALID_FILE_ATTRIBUTES || !(attr & FILE_ATTRIBUTE_DIRECTORY)) {
            return false;
        }

        if (!m_pWallpaper && !connectCOM()) {
            return false;
        }

        cleanVirtualDesktopsBlockers();

        // BackgroundType = 2 (Slideshow)
        HKEY hKey = nullptr;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Wallpapers", 0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {
            DWORD bgType = 2;
            DWORD srcSet = 1;
            RegSetValueExW(hKey, L"BackgroundType", 0, REG_DWORD, (const BYTE*)&bgType, sizeof(bgType));
            RegSetValueExW(hKey, L"SlideshowSourceDirectoriesSet", 0, REG_DWORD, (const BYTE*)&srcSet, sizeof(srcSet));
            RegCloseKey(hKey);
        }

        IShellItem* pItem = nullptr;
        HRESULT hr = SHCreateItemFromParsingName(folderPath.c_str(), nullptr, IID_IShellItem, (void**)&pItem);
        if (FAILED(hr) || !pItem) return false;

        IShellItemArray* pArray = nullptr;
        hr = SHCreateShellItemArrayFromShellItem(pItem, IID_IShellItemArray, (void**)&pArray);
        pItem->Release();
        if (FAILED(hr) || !pArray) return false;

        hr = m_pWallpaper->SetSlideshow(pArray);
        pArray->Release();
        if (FAILED(hr)) return false;

        // Shuffle = DSO_SHUFFLEIMAGES, Interval = 86400000 (1 day) so our timer controls it
        m_pWallpaper->SetSlideshowOptions(shuffle ? DSO_SHUFFLEIMAGES : (DESKTOP_SLIDESHOW_OPTIONS)0, 86400000);
        return true;
    }

    bool advanceSlideshow() {
        if (!m_pWallpaper && !connectCOM()) return false;

        HRESULT hr = m_pWallpaper->AdvanceSlideshow(nullptr, DSD_FORWARD);
        if (SUCCEEDED(hr)) return true;

        // Escalation 1: Re-setup slideshow
        if (setupSlideshow(m_resolvedPicturesPath, m_config.shuffle)) {
            hr = m_pWallpaper->AdvanceSlideshow(nullptr, DSD_FORWARD);
            if (SUCCEEDED(hr)) return true;
        }

        // Escalation 2: Re-connect COM
        if (connectCOM() && setupSlideshow(m_resolvedPicturesPath, m_config.shuffle)) {
            hr = m_pWallpaper->AdvanceSlideshow(nullptr, DSD_FORWARD);
            if (SUCCEEDED(hr)) return true;
        }

        return false;
    }

    std::wstring getCurrentWallpaper() {
        if (!m_pWallpaper && !connectCOM()) return L"";

        LPWSTR monitorID = nullptr;
        HRESULT hr = m_pWallpaper->GetMonitorDevicePathAt(0, &monitorID);
        if (FAILED(hr) || !monitorID) return L"";

        LPWSTR wallpaperPath = nullptr;
        hr = m_pWallpaper->GetWallpaper(monitorID, &wallpaperPath);
        CoTaskMemFree(monitorID);

        std::wstring result = L"";
        if (SUCCEEDED(hr) && wallpaperPath) {
            result = wallpaperPath;
            CoTaskMemFree(wallpaperPath);
        }
        return result;
    }

    // --- Power & State Helpers ---
    void checkAcDcState() {
        SYSTEM_POWER_STATUS sps;
        if (GetSystemPowerStatus(&sps)) {
            m_isOnBattery = (sps.ACLineStatus == 0);
        }
    }

    bool isBatterySaverActive() {
        SYSTEM_POWER_STATUS sps;
        if (GetSystemPowerStatus(&sps)) {
            return sps.SystemStatusFlag == 1;
        }
        return false;
    }

    bool isUserBusyOrFullscreen() {
        QUERY_USER_NOTIFICATION_STATE state;
        if (SHQueryUserNotificationState(&state) == S_OK) {
            return (state == QUNS_RUNNING_D3D_FULL_SCREEN || state == QUNS_PRESENTATION_MODE);
        }
        return false;
    }

    // --- Configuration IO ---
    static std::wstring trim(const std::wstring& str) {
        size_t first = str.find_first_not_of(L" \t\r\n");
        if (first == std::wstring::npos) return L"";
        size_t last = str.find_last_not_of(L" \t\r\n");
        return str.substr(first, (last - first + 1));
    }

    static bool parseBool(const std::wstring& val) {
        std::wstring lower = val;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::towlower);
        return (lower == L"true" || lower == L"1" || lower == L"yes");
    }

    void loadConfig() {
        HANDLE hFile = CreateFileW(m_configFile.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (hFile != INVALID_HANDLE_VALUE) {
            GetFileTime(hFile, nullptr, nullptr, &m_configLastWriteTime);
            DWORD size = GetFileSize(hFile, nullptr);
            if (size > 0 && size < 100000) {
                std::vector<char> buf(size + 1, 0);
                DWORD read = 0;
                ReadFile(hFile, buf.data(), size, &read, nullptr);
                CloseHandle(hFile);

                std::istringstream stream(buf.data());
                std::string line;
                while (std::getline(stream, line)) {
                    if (line.empty() || line[0] == '#' || line[0] == ';') continue;
                    size_t eq = line.find('=');
                    if (eq != std::string::npos) {
                        std::string k_str = line.substr(0, eq);
                        std::string v_str = line.substr(eq + 1);

                        // Convert to wstring
                        int k_len = MultiByteToWideChar(CP_UTF8, 0, k_str.c_str(), -1, nullptr, 0);
                        int v_len = MultiByteToWideChar(CP_UTF8, 0, v_str.c_str(), -1, nullptr, 0);
                        std::vector<WCHAR> kW(k_len), vW(v_len);
                        MultiByteToWideChar(CP_UTF8, 0, k_str.c_str(), -1, kW.data(), k_len);
                        MultiByteToWideChar(CP_UTF8, 0, v_str.c_str(), -1, vW.data(), v_len);

                        std::wstring k = trim(kW.data());
                        std::wstring v = trim(vW.data());

                        if (k == L"PicturesPath" && !v.empty()) m_config.picturesPath = v;
                        else if (k == L"IntervalSeconds") {
                            try { m_config.intervalSeconds = (std::max)(3, std::stoi(v)); } catch (...) {}
                        }
                        else if (k == L"Shuffle") m_config.shuffle = parseBool(v);
                        else if (k == L"PauseOnFullscreen") m_config.pauseOnFullscreen = parseBool(v);
                        else if (k == L"PauseOnBatterySaver") m_config.pauseOnBatterySaver = parseBool(v);
                        else if (k == L"PauseOnBattery") m_config.pauseOnBattery = parseBool(v);
                    }
                }
                return;
            }
            CloseHandle(hFile);
        }
        // If not found or empty, save default
        saveConfig();
    }

    void saveConfig() {
        std::wostringstream ss;
        ss << L"# ==========================================\n"
           << L"# Wallpaper Slideshow Konfiguration\n"
           << L"# ==========================================\n\n"
           << L"# Pfad zum Bilderordner (Standard: 'Wallpapers'):\n"
           << L"PicturesPath=" << m_config.picturesPath << L"\n\n"
           << L"# Anzeigedauer pro Bild in Sekunden (z. B. 15):\n"
           << L"IntervalSeconds=" << m_config.intervalSeconds << L"\n\n"
           << L"# Bilder zufaellig mischen (true/false):\n"
           << L"Shuffle=" << (m_config.shuffle ? L"true" : L"false") << L"\n\n"
           << L"# Diashow automatisch pausieren, wenn ein Spiel/Praesentation im Vollbild laeuft (true/false):\n"
           << L"PauseOnFullscreen=" << (m_config.pauseOnFullscreen ? L"true" : L"false") << L"\n\n"
           << L"# Diashow automatisch pausieren, wenn Windows im Akku-Stromsparmodus ist (true/false):\n"
           << L"PauseOnBatterySaver=" << (m_config.pauseOnBatterySaver ? L"true" : L"false") << L"\n\n"
           << L"# Ultrabook-Power: Automatisch pausieren, sobald das Laptop auf reinem Akkubetrieb laeuft (true/false):\n"
           << L"PauseOnBattery=" << (m_config.pauseOnBattery ? L"true" : L"false") << L"\n";

        std::wstring outW = ss.str();
        int len = WideCharToMultiByte(CP_UTF8, 0, outW.c_str(), -1, nullptr, 0, nullptr, nullptr);
        std::vector<char> outUtf8(len);
        WideCharToMultiByte(CP_UTF8, 0, outW.c_str(), -1, outUtf8.data(), len, nullptr, nullptr);

        HANDLE hFile = CreateFileW(m_configFile.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (hFile != INVALID_HANDLE_VALUE) {
            DWORD written = 0;
            WriteFile(hFile, outUtf8.data(), (DWORD)strlen(outUtf8.data()), &written, nullptr);
            GetFileTime(hFile, nullptr, nullptr, &m_configLastWriteTime);
            CloseHandle(hFile);
        }
    }

    void checkAndReloadConfig() {
        WIN32_FILE_ATTRIBUTE_DATA fad;
        if (GetFileAttributesExW(m_configFile.c_str(), GetFileExInfoStandard, &fad)) {
            if (CompareFileTime(&fad.ftLastWriteTime, &m_configLastWriteTime) != 0) {
                int oldInterval = m_config.intervalSeconds;
                std::wstring oldPath = m_config.picturesPath;
                bool oldShuffle = m_config.shuffle;

                loadConfig();

                if (m_config.picturesPath != oldPath || m_config.shuffle != oldShuffle) {
                    m_resolvedPicturesPath = resolvePicturesPath(m_config.picturesPath);
                    setupSlideshow(m_resolvedPicturesPath, m_config.shuffle);
                }
                if (m_config.intervalSeconds != oldInterval) {
                    startTimer();
                }
                updateTrayTooltip();
            }
        }
    }

    // --- Autostart Helpers ---
    bool isAutostartEnabled() {
        HKEY hKey = nullptr;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, RUN_REG_KEY, 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            WCHAR buffer[MAX_PATH * 2];
            DWORD size = sizeof(buffer);
            DWORD type = 0;
            LONG res = RegQueryValueExW(hKey, APP_REG_NAME, nullptr, &type, (LPBYTE)buffer, &size);
            RegCloseKey(hKey);
            return (res == ERROR_SUCCESS);
        }
        return false;
    }

    void setAutostart(bool enable) {
        HKEY hKey = nullptr;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, RUN_REG_KEY, 0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {
            if (enable) {
                WCHAR exePath[MAX_PATH];
                GetModuleFileNameW(nullptr, exePath, MAX_PATH);
                std::wstring cmd = L"\"" + std::wstring(exePath) + L"\"";
                RegSetValueExW(hKey, APP_REG_NAME, 0, REG_SZ, (const BYTE*)cmd.c_str(), (DWORD)((cmd.size() + 1) * sizeof(WCHAR)));
            } else {
                RegDeleteValueW(hKey, APP_REG_NAME);
            }
            RegCloseKey(hKey);
        }
    }

    // --- Timer Management ---
    void startTimer() {
        if (m_isPaused || m_isLocked || m_isDisplayOff) return;
        stopTimer();

        UINT intervalMs = (UINT)(std::max)(3000, m_config.intervalSeconds * 1000);

        // SetCoalescableTimer batches wakeups with OS tasks, preserving deep CPU C-States
        typedef UINT_PTR (WINAPI *SetCoalescableTimerFn)(HWND, UINT_PTR, UINT, TIMERPROC, ULONG);
        static SetCoalescableTimerFn fnSetCoalescableTimer = 
            (SetCoalescableTimerFn)GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetCoalescableTimer");

        if (fnSetCoalescableTimer) {
            fnSetCoalescableTimer(m_hwnd, TIMER_ID, intervalMs, nullptr, 2000);
        } else {
            SetTimer(m_hwnd, TIMER_ID, intervalMs, nullptr);
        }
        m_timerActive = true;
    }

    void stopTimer() {
        if (m_timerActive) {
            KillTimer(m_hwnd, TIMER_ID);
            m_timerActive = false;
        }
    }

    void onTimerTick() {
        if (m_isPaused || m_isLocked || m_isDisplayOff) return;

        checkAndReloadConfig();

        // Ultrabook Power Check: Pure battery mode
        if (m_config.pauseOnBattery && m_isOnBattery) {
            updateTrayTooltip();
            return;
        }

        // Battery Saver Check
        if (m_config.pauseOnBatterySaver && isBatterySaverActive()) {
            updateTrayTooltip();
            return;
        }

        // Fullscreen / Gaming Check
        if (m_config.pauseOnFullscreen && isUserBusyOrFullscreen()) {
            updateTrayTooltip();
            return;
        }

        advanceSlideshow();
        updateTrayTooltip();
        trimMemory();
    }

    void triggerNextManually() {
        advanceSlideshow();
        updateTrayTooltip();
        startTimer();
    }

    void togglePause() {
        m_isPaused = !m_isPaused;
        if (m_isPaused) {
            stopTimer();
        } else {
            startTimer();
        }
        updateTrayTooltip();
    }

    // --- Tray UI ---
    void updateTrayTooltip(bool force = false) {
        std::wstring curr = getCurrentWallpaper();
        std::wstring name = L"Wallpaper";
        if (!curr.empty()) {
            size_t slash = curr.find_last_of(L"\\/");
            if (slash != std::wstring::npos) {
                name = curr.substr(slash + 1);
            } else {
                name = curr;
            }
        }

        std::wstring status = L"";
        if (m_isPaused) {
            status = L"[PAUSIERT] ";
        } else if (m_config.pauseOnBattery && m_isOnBattery) {
            status = L"[AKKUBETRIEB] ";
        } else if (m_config.pauseOnFullscreen && isUserBusyOrFullscreen()) {
            status = L"[VOLLBILD] ";
        } else if (m_config.pauseOnBatterySaver && isBatterySaverActive()) {
            status = L"[STROMSPARMODUS] ";
        } else if (m_isDisplayOff) {
            status = L"[BILDSCHIRM AUS] ";
        }

        WCHAR tipBuf[128];
        swprintf_s(tipBuf, L"%sWallpaper Diashow\n%s\nAlle %ds", status.c_str(), name.c_str(), m_config.intervalSeconds);
        std::wstring tip = tipBuf;
        if (tip.size() > 127) tip = tip.substr(0, 124) + L"...";

        if (!force && tip == m_lastTip) return;
        m_lastTip = tip;

        NOTIFYICONDATAW nid = { 0 };
        nid.cbSize = sizeof(nid);
        nid.hWnd = m_hwnd;
        nid.uID = 1;
        nid.uFlags = NIF_TIP;
        wcsncpy_s(nid.szTip, tip.c_str(), _TRUNCATE);
        Shell_NotifyIconW(NIM_MODIFY, &nid);
    }

    void showTrayMenu() {
        HMENU hMenu = CreatePopupMenu();
        AppendMenuW(hMenu, MF_STRING | MF_GRAYED, 0, L"🖼 Wallpaper Slideshow (Native Diashow)");
        AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);

        AppendMenuW(hMenu, MF_STRING, 1, L"⏭  Nächstes Bild (Weicher Übergang)");

        std::wstring pauseText = m_isPaused ? L"▶  Diashow fortsetzen" : L"⏸  Diashow pausieren";
        AppendMenuW(hMenu, MF_STRING, 3, pauseText.c_str());
        AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);

        AppendMenuW(hMenu, MF_STRING, 4, L"📁  Bilderordner öffnen");
        AppendMenuW(hMenu, MF_STRING, 5, L"🔄  Diashow neu initialisieren");
        AppendMenuW(hMenu, MF_STRING, 6, L"⚙  Einstellungen (config.txt)");
        AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);

        // Power & Efficiency submenu or options
        UINT fsFlags = MF_STRING | (m_config.pauseOnFullscreen ? MF_CHECKED : MF_UNCHECKED);
        AppendMenuW(hMenu, fsFlags, 10, L"🎮  Bei Vollbild-Spielen pausieren");

        UINT saverFlags = MF_STRING | (m_config.pauseOnBatterySaver ? MF_CHECKED : MF_UNCHECKED);
        AppendMenuW(hMenu, saverFlags, 9, L"🔋  Bei Windows-Stromsparmodus pausieren");

        UINT batFlags = MF_STRING | (m_config.pauseOnBattery ? MF_CHECKED : MF_UNCHECKED);
        AppendMenuW(hMenu, batFlags, 11, L"⚡  Bei reinem Akkubetrieb pausieren (Ultrabook)");

        bool isAuto = isAutostartEnabled();
        UINT autoFlags = MF_STRING | (isAuto ? MF_CHECKED : MF_UNCHECKED);
        AppendMenuW(hMenu, autoFlags, 7, L"🚀  Mit Windows starten");
        AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);

        AppendMenuW(hMenu, MF_STRING, 8, L"❌  Beenden");

        POINT pt;
        GetCursorPos(&pt);
        SetForegroundWindow(m_hwnd);
        int cmd = TrackPopupMenu(hMenu, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, m_hwnd, nullptr);
        PostMessageW(m_hwnd, WM_NULL, 0, 0);
        DestroyMenu(hMenu);

        if (cmd == 1) {
            triggerNextManually();
        } else if (cmd == 3) {
            togglePause();
        } else if (cmd == 4) {
            ShellExecuteW(nullptr, L"open", m_resolvedPicturesPath.c_str(), nullptr, nullptr, SW_SHOW);
        } else if (cmd == 5) {
            checkAndReloadConfig();
            setupSlideshow(m_resolvedPicturesPath, m_config.shuffle);
            triggerNextManually();
        } else if (cmd == 6) {
            ShellExecuteW(nullptr, L"open", m_configFile.c_str(), nullptr, nullptr, SW_SHOW);
        } else if (cmd == 7) {
            setAutostart(!isAuto);
        } else if (cmd == 8) {
            shutdown();
        } else if (cmd == 9) {
            m_config.pauseOnBatterySaver = !m_config.pauseOnBatterySaver;
            saveConfig();
            updateTrayTooltip();
        } else if (cmd == 10) {
            m_config.pauseOnFullscreen = !m_config.pauseOnFullscreen;
            saveConfig();
            updateTrayTooltip();
        } else if (cmd == 11) {
            m_config.pauseOnBattery = !m_config.pauseOnBattery;
            saveConfig();
            updateTrayTooltip();
        }
    }

    // --- Message Procedure ---
    static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
        SlideshowApp* pApp = (SlideshowApp*)GetWindowLongPtrW(hwnd, GWLP_USERDATA);

        if (msg == TRAY_MSG_ID) {
            if (lParam == WM_RBUTTONUP) {
                if (pApp) pApp->showTrayMenu();
            } else if (lParam == WM_LBUTTONUP) {
                if (pApp) pApp->triggerNextManually();
            }
            return 0;
        }

        if (pApp && msg == pApp->m_wmTaskbarCreated) {
            // Explorer restarted: re-add icon and reconnect COM
            Shell_NotifyIconW(NIM_ADD, &pApp->m_nid);
            pApp->connectCOM();
            pApp->setupSlideshow(pApp->m_resolvedPicturesPath, pApp->m_config.shuffle);
            pApp->updateTrayTooltip(true);
            return 0;
        }

        switch (msg) {
        case WM_TIMER:
            if (wParam == TIMER_ID && pApp) {
                pApp->onTimerTick();
            }
            return 0;

        case WM_WTSSESSION_CHANGE:
            if (pApp) {
                if (wParam == WTS_SESSION_LOCK) {
                    pApp->m_isLocked = true;
                    pApp->stopTimer();
                } else if (wParam == WTS_SESSION_UNLOCK) {
                    pApp->m_isLocked = false;
                    if (!pApp->m_isPaused && !pApp->m_isDisplayOff) {
                        pApp->startTimer();
                    }
                }
            }
            return 0;

        case WM_POWERBROADCAST:
            if (wParam == PBT_POWERSETTINGCHANGE && lParam && pApp) {
                POWERBROADCAST_SETTING* pbs = (POWERBROADCAST_SETTING*)lParam;
                if (IsEqualGUID(pbs->PowerSetting, GUID_CONSOLE_DISPLAY_STATE_VAL)) {
                    DWORD displayState = pbs->Data[0];
                    if (displayState == 0) { // Display OFF
                        pApp->m_isDisplayOff = true;
                        pApp->stopTimer();
                    } else if (displayState == 1 || displayState == 2) { // Display ON / Dimmed
                        pApp->m_isDisplayOff = false;
                        if (!pApp->m_isPaused && !pApp->m_isLocked) {
                            pApp->startTimer();
                        }
                    }
                } else if (IsEqualGUID(pbs->PowerSetting, GUID_ACDC_POWER_SOURCE_VAL)) {
                    DWORD acState = pbs->Data[0];
                    // 0 = AC power, 1 = Battery, 2 = Short term battery
                    pApp->m_isOnBattery = (acState != 0);
                    pApp->updateTrayTooltip();
                }
            }
            return DefWindowProcW(hwnd, msg, wParam, lParam);

        case WM_CLOSE:
            if (pApp) pApp->shutdown();
            return 0;

        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
        }

        return DefWindowProcW(hwnd, msg, wParam, lParam);
    }

    bool init() {
        HDESK hDesk = OpenInputDesktop(0, FALSE, MAXIMUM_ALLOWED);
        if (hDesk) {
            SetThreadDesktop(hDesk);
            CloseDesktop(hDesk);
        }

        // 1. EcoQoS / Effizienzmodus
        applyEcoMode();

        // 2. Single-Instance Mutex
        m_hMutex = CreateMutexW(nullptr, FALSE, MUTEX_NAME);
        if (GetLastError() == ERROR_ALREADY_EXISTS) {
            return false;
        }

        // 3. COM Initialisierung
        CoInitialize(nullptr);

        // 4. Config & Paths
        loadConfig();
        m_resolvedPicturesPath = resolvePicturesPath(m_config.picturesPath);
        checkAcDcState();

        // 5. Window Registration
        WNDCLASSW wc = { 0 };
        wc.lpfnWndProc = WndProc;
        wc.hInstance = GetModuleHandleW(nullptr);
        wc.lpszClassName = WINDOW_CLASS_NAME;
        RegisterClassW(&wc);

        m_hwnd = CreateWindowExW(
            0, WINDOW_CLASS_NAME, WINDOW_TITLE,
            0, 0, 0, 0, 0, 0, 0, wc.hInstance, nullptr
        );
        if (!m_hwnd) return false;

        SetWindowLongPtrW(m_hwnd, GWLP_USERDATA, (LONG_PTR)this);
        m_wmTaskbarCreated = RegisterWindowMessageW(L"TaskbarCreated");

        // 6. Power Notifications (Display State + AC/DC Source)
        typedef HPOWERNOTIFY (WINAPI *RegPowerFn)(HANDLE, LPCGUID, DWORD);
        RegPowerFn fnRegisterPowerSettingNotification = 
            (RegPowerFn)GetProcAddress(GetModuleHandleW(L"user32.dll"), "RegisterPowerSettingNotification");

        if (fnRegisterPowerSettingNotification) {
            m_hPowerDisplayNotify = fnRegisterPowerSettingNotification(m_hwnd, &GUID_CONSOLE_DISPLAY_STATE_VAL, DEVICE_NOTIFY_WINDOW_HANDLE);
            m_hPowerAcDcNotify = fnRegisterPowerSettingNotification(m_hwnd, &GUID_ACDC_POWER_SOURCE_VAL, DEVICE_NOTIFY_WINDOW_HANDLE);
        }

        WTSRegisterSessionNotification(m_hwnd, NOTIFY_FOR_THIS_SESSION);

        // 7. Tray Icon
        std::wstring iconPath = m_appDir + L"\\app_icon.ico";
        m_hIcon = (HICON)LoadImageW(nullptr, iconPath.c_str(), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE);
        if (!m_hIcon) {
            m_hIcon = LoadIconW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(1));
        }
        if (!m_hIcon) {
            m_hIcon = LoadIconW(nullptr, (LPCWSTR)IDI_APPLICATION);
        }

        m_nid.cbSize = sizeof(m_nid);
        m_nid.hWnd = m_hwnd;
        m_nid.uID = 1;
        m_nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
        m_nid.uCallbackMessage = TRAY_MSG_ID;
        m_nid.hIcon = m_hIcon;
        wcsncpy_s(m_nid.szTip, L"Wallpaper Slideshow", _TRUNCATE);
        Shell_NotifyIconW(NIM_ADD, &m_nid);

        // 8. Slideshow Initialisierung
        connectCOM();
        setupSlideshow(m_resolvedPicturesPath, m_config.shuffle);

        updateTrayTooltip();
        startTimer();
        trimMemory();

        return true;
    }

    void shutdown() {
        if (m_isShuttingDown) return;
        m_isShuttingDown = true;

        stopTimer();

        typedef BOOL (WINAPI *UnregPowerFn)(HPOWERNOTIFY);
        UnregPowerFn fnUnregisterPowerSettingNotification = 
            (UnregPowerFn)GetProcAddress(GetModuleHandleW(L"user32.dll"), "UnregisterPowerSettingNotification");

        if (fnUnregisterPowerSettingNotification) {
            if (m_hPowerDisplayNotify) {
                fnUnregisterPowerSettingNotification(m_hPowerDisplayNotify);
                m_hPowerDisplayNotify = nullptr;
            }
            if (m_hPowerAcDcNotify) {
                fnUnregisterPowerSettingNotification(m_hPowerAcDcNotify);
                m_hPowerAcDcNotify = nullptr;
            }
        }

        if (m_hwnd) {
            WTSUnRegisterSessionNotification(m_hwnd);
            Shell_NotifyIconW(NIM_DELETE, &m_nid);
            DestroyWindow(m_hwnd);
            m_hwnd = nullptr;
        }

        cleanup();
        PostQuitMessage(0);
    }

    void cleanup() {
        if (m_pWallpaper) {
            m_pWallpaper->Release();
            m_pWallpaper = nullptr;
        }
        if (m_hMutex) {
            CloseHandle(m_hMutex);
            m_hMutex = nullptr;
        }
        CoUninitialize();
    }

    void run() {
        MSG msg;
        while (GetMessageW(&msg, nullptr, 0, 0)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
};

// --- Entry Point ---
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    // Attach to current user input desktop (essential for tray icon & session messages)
    HDESK hDesk = OpenInputDesktop(0, FALSE, 0x01FF);
    if (hDesk) {
        SetThreadDesktop(hDesk);
        CloseDesktop(hDesk);
    }

    // Check for "--stop" command line argument
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv) {
        if (argc > 1 && (_wcsicmp(argv[1], L"--stop") == 0 || _wcsicmp(argv[1], L"-stop") == 0 || _wcsicmp(argv[1], L"stop") == 0)) {
            LocalFree(argv);
            HWND existing = FindWindowW(WINDOW_CLASS_NAME, WINDOW_TITLE);
            if (existing) {
                PostMessageW(existing, WM_CLOSE, 0, 0);
                return 0;
            }
            return 1;
        }
        LocalFree(argv);
    }

    SlideshowApp app;
    if (!app.init()) {
        return 0;
    }
    app.run();
    return 0;
}

# Review Findings

## Review: WallpaperSlideshow C++ Port Audit
**Date**: 2026-10-28 | **Tier**: 1 (Diff/Feature, single-pass audit)
**Files**: 1 (`main.cpp`) | **Agents Used**: 0

| CRITICAL | MAJOR | MINOR | ENHANCEMENT |
|---|---|---|---|
| 0 | 1 | 3 | 2 |

### Fix First (top items)
1. [MAJOR] [FIXED] R-01 Redundant desktop handle creation in `init()` fails with `ERROR_ACCESS_DENIED` and causes silent degradation -- `main.cpp:709-713`

---

### Findings

### [MAJOR] [FIXED] R-01 Redundant desktop handle creation in `init()` fails with `ERROR_ACCESS_DENIED` and causes silent degradation
- **Status**: FIXED
- **Where**: `main.cpp:709-713`
- **Source**: `r-review` (Tier 1) (2026-10-28)
- **Confidence**: HIGH
- **Category**: robustness
- **Scenario**: `WinMain()` already opens the input desktop with `0x01FF` and calls `SetThreadDesktop()` at lines 846-850. Then inside `app.init()` at line 709, `OpenInputDesktop(0, FALSE, MAXIMUM_ALLOWED)` was called again. In non-elevated user contexts, requesting `MAXIMUM_ALLOWED` (0x02000000) on an interactive input desktop object frequently fails with `ERROR_ACCESS_DENIED` (error code 5), or unnecessarily switches thread desktop contexts twice on every launch.
- **Why**: Double-desktop binding with inconsistent access masks (`0x01FF` vs `MAXIMUM_ALLOWED`). The second call in `init()` is redundant and fragile.
- **Fix**: Removed redundant second call in `init()`.

---

### [MINOR] [FIXED] R-02 Trailing slash or dot in relative path resolution causes `resolvePicturesPath` fallback failure
- **Status**: FIXED
- **Where**: `main.cpp:171-182`
- **Source**: `r-review` (Tier 1) (2026-10-28)
- **Confidence**: HIGH
- **Category**: bug
- **Scenario**: User configures `PicturesPath=.\Wallpapers\` or `PicturesPath=Wallpapers/`. In Windows, `m_appDir + L"\\" + raw` creates paths with duplicate or mixed slashes `C:\Path\\.\Wallpapers\`. If `GetFileAttributesW` fails due to unnormalized trailing slashes or relative segments, it prematurely triggers fallback to the default folder or user Pictures.
- **Why**: `candidate` is not normalized via `GetFullPathNameW` before checking directory attributes and passing to `SHCreateItemFromParsingName`.
- **Fix**: Added `GetFullPathNameW` canonicalization before directory attribute inspection.

---

### [MINOR] [FIXED] R-03 File handle leak in `loadConfig()` when read size check fails
- **Status**: FIXED
- **Where**: `main.cpp:319-357`
- **Source**: `r-review` (Tier 1) (2026-10-28)
- **Confidence**: HIGH
- **Category**: robustness
- **Scenario**: If `config.txt` is corrupted or empty (`size == 0`), or abnormally large (`size >= 100000`), the `if (size > 0 && size < 100000)` branch evaluates to `false`. Execution jumps past the inner `CloseHandle(hFile)` to line 359 `saveConfig();`, while `hFile` remains open with read/write sharing. `saveConfig()` then attempts `CreateFileW(..., CREATE_ALWAYS, ...)`, which fails with sharing violation `ERROR_SHARING_VIOLATION`.
- **Why**: `CloseHandle(hFile)` is inside the `if` body rather than executed before leaving the enclosing scope.
- **Fix**: Added explicit `CloseHandle(hFile)` in the else branch before fallback saving.

---

### [MINOR] [FIXED] R-04 `TrackPopupMenu` missing keyboard focus and dismiss handling
- **Status**: FIXED
- **Where**: `main.cpp:594-597`
- **Source**: `r-review` (Tier 1) (2026-10-28)
- **Confidence**: MEDIUM
- **Category**: robustness
- **Scenario**: When right-clicking the tray icon, `SetForegroundWindow(m_hwnd)` is called, but `m_hwnd` is a 0x0 message-only hidden window without a visible taskbar presence. Under certain Windows 11 focus states, clicking away outside the popup menu does not dismiss the menu promptly, or keystrokes (like Escape) can be dropped.
- **Why**: Verified and confirmed: `PostMessageW(m_hwnd, WM_NULL, 0, 0)` is strictly dispatched directly after `TrackPopupMenu` to ensure reliable menu dismissal.

---

### [ENHANCEMENT] [FIXED] R-05 Remove unused MSVC-specific `#pragma comment(lib, ...)` warnings under Clang/MinGW
- **Status**: FIXED
- **Where**: `main.cpp:22-27`
- **Source**: `r-review` (Tier 1) (2026-10-28)
- **Confidence**: HIGH
- **Category**: maintainability
- **Scenario**: Clang/MinGW emits 6 warnings (`-Wunknown-pragmas`) on compilation because GCC/MinGW linkers consume library arguments via CLI (`-luser32` etc.) rather than `#pragma comment`.
- **Why**: Dead pragmas producing harmless but noisy compiler warnings.
- **Fix**: Wrapped `#pragma comment(lib, ...)` blocks inside `#if defined(_MSC_VER)`.

---

### [ENHANCEMENT] [DEFERRED] R-06 Replace timer polling for `checkAndReloadConfig()` with Win32 Directory Change Notification
- **Status**: DEFERRED
- **Where**: `main.cpp:475`
- **Source**: `r-review` (Tier 1) (2026-10-28)
- **Confidence**: MEDIUM
- **Category**: performance
- **Scenario**: Every timer tick (default 15 seconds) executes `checkAndReloadConfig()` which calls `GetFileAttributesExW` to query filesystem metadata. While very cheap, on battery-constrained laptops this produces unnecessary I/O query cycles on every wakeup.
- **Why**: Deferred to avoid introducing background worker threads or file watcher handles that would bloat the binary or memory footprint above the current ~80 KB working set.

---

### Coverage / Not Reviewed
- **Reviewed**: `main.cpp`, `resources.rc`, `config.default.txt`, `.gitignore`, `README.md`.
- **Excluded**: Binary asset files (`app_icon.ico`, `Wallpapers/*.png`).

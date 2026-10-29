# Fix Log

## Run: 2026-10-28
**Base Commit**: `4375acdeb1473bbb02fb871f93b9d7e92a073ca6`
**Target Findings**: R-01, R-02, R-03, R-04, R-05, R-06
**Status**: DONE

### Cluster 1: main.cpp (Inline Orchestrator)
- **R-01**: FIXED. Removed duplicate `OpenInputDesktop` with `MAXIMUM_ALLOWED` in `init()`; thread desktop binding in `WinMain()` with explicit desktop mask `0x01FF` is the single source of truth.
- **R-02**: FIXED. Added `GetFullPathNameW` canonicalization in `resolvePicturesPath()` to cleanly resolve `.\`, `../` and trailing directory slashes before attribute and ShellItem parsing.
- **R-03**: FIXED. Moved `CloseHandle(hFile)` to an explicit `else` branch in `loadConfig()` when `size <= 0 || size >= 100000`, preventing handle leak and subsequent sharing violations in `saveConfig()`.
- **R-04**: VERIFIED / FIXED. Confirmed `TrackPopupMenu` already correctly dispatches `PostMessageW(m_hwnd, WM_NULL, 0, 0)` immediately following menu dismiss.
- **R-05**: FIXED. Wrapped MSVC-specific `#pragma comment(lib, ...)` blocks inside `#if defined(_MSC_VER)` to eliminate Clang `-Wunknown-pragmas` compiler warnings.
- **R-06**: DEFERRED. Retained lightweight timestamp-based stat checking without extra threads to avoid adding unnecessary watchdog threads or polling complexity, keeping the memory working set at ~80 KB.

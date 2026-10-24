@echo off
setlocal
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "WallpaperSlideshow" /f >nul 2>&1
echo [ERFOLG] WallpaperSlideshow wurde aus dem Windows-Autostart entfernt.
endlocal

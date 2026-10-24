@echo off
setlocal
set SCRIPT_PATH=%~dp0wallpaper_slideshow.pyw
set "PYTHONW=pythonw.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" (
    set "PYTHONW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
)

reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "WallpaperSlideshow" /t REG_SZ /d "\"%PYTHONW%\" \"%SCRIPT_PATH%\"" /f >nul
if %ERRORLEVEL% equ 0 (
    echo [ERFOLG] WallpaperSlideshow wurde erfolgreich zum Windows-Autostart hinzugefuegt!
    echo Beim naechsten Windows-Start startet die Diashow automatisch im Hintergrund.
) else (
    echo [FEHLER] Autostart konnte nicht eingerichtet werden.
)
endlocal

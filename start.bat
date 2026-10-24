@echo off
setlocal
cd /d "%~dp0"
set "PYTHONW=pythonw.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" (
    set "PYTHONW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
)
"%PYTHONW%" "wallpaper_slideshow.pyw" --stop >nul 2>&1
start "" "%PYTHONW%" "wallpaper_slideshow.pyw"
echo [OK] Wallpaper Slideshow wurde im Hintergrund gestartet!
endlocal

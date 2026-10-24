@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW=pythonw.exe"
where.exe pythonw.exe >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYTHONW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" set "PYTHONW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
    if exist "%ProgramFiles%\Python312\pythonw.exe" set "PYTHONW=%ProgramFiles%\Python312\pythonw.exe"
    if exist "%ProgramFiles%\Python311\pythonw.exe" set "PYTHONW=%ProgramFiles%\Python311\pythonw.exe"
)

"%PYTHONW%" "%~dp0wallpaper_slideshow.pyw" --stop >nul 2>&1
ping 127.0.0.1 -n 2 >nul 2>&1
start "" "%PYTHONW%" "%~dp0wallpaper_slideshow.pyw"
echo [OK] Wallpaper Slideshow wurde im Hintergrund gestartet!
endlocal

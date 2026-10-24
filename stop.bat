@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=python.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
"%PYTHON%" "wallpaper_slideshow.pyw" --stop
endlocal

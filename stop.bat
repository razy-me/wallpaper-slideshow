@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=python.exe"
where.exe python.exe >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON=%ProgramFiles%\Python312\python.exe"
    if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON=%ProgramFiles%\Python311\python.exe"
)

"%PYTHON%" "wallpaper_slideshow.pyw" --stop
endlocal

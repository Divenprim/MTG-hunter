@echo off
setlocal
cd /d "%~dp0"

rem  https for the tablet: without it the browser refuses the camera, which
rem  means no scanner.  ASCII only here -- cmd reads this file in the OEM code
rem  page, so every Russian letter in it would turn into garbage.  The
rem  readable part is printed by start.py.

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Run run.bat first: it installs the environment.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "%~dp0start.py" 0.0.0.0 8765 ssl
if errorlevel 1 pause

@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem  https for the tablet: without it the browser refuses the camera, which
rem  means no scanner.  ASCII only here -- cmd reads this file in the OEM code
rem  page, so every Russian letter in it would turn into garbage.  Everything
rem  a person reads is printed by start.py.
rem
rem  This file used to refuse to work on a fresh copy ("run run.bat first").
rem  A person who wants the tablet should not have to run something else
rem  first: the same bootstrap lives here, and start.py sets up whatever is
rem  missing, certificate included.

chcp 65001 >nul 2>nul

rem  The system Python, not the one inside .venv: a broken environment must
rem  be rebuildable, and start.py does that with whatever started it.
set "PYEXE="
for %%P in ("py -3.12" "py -3" "python" "python3") do (
    if not defined PYEXE (
        %%~P -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYEXE=%%~P"
    )
)

if not defined PYEXE (
    echo.
    echo   Python 3.10+ not found / Python 3.10+ ne naiden
    echo.
    echo   Install it from  https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH".
    echo.
    echo   Already installed? Then Windows intercepts the name "python":
    echo   Settings ^> Apps ^> Advanced app settings ^> App execution aliases,
    echo   turn off python.exe and python3.exe, then run this file again.
    echo.
    pause
    exit /b 1
)

%PYEXE% "%~dp0start.py" 0.0.0.0 8765 ssl
if errorlevel 1 pause

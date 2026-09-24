@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem  run.bat        -- this computer only (default)
rem  run.bat lan    -- visible to the local network: tablet, phone
rem
rem  Everything a person reads is printed by start.py, not from here.
rem  A .bat file is read by cmd in the OEM code page, so Russian text in it
rem  turns into garbage on most machines.  ASCII only below.

rem  The console must expect UTF-8 before a single Russian letter is
rem  printed.  Safe here: this file is pure ASCII, so switching the code
rem  page cannot confuse the parser reading it.
chcp 65001 >nul 2>nul

set "MTGH_HOST=127.0.0.1"
set "MTGH_PORT=8765"
if /i "%~1"=="lan" set "MTGH_HOST=0.0.0.0"

rem  Finding Python is a task, not a command.  On Windows 11 the name
rem  "python" leads to a Microsoft Store stub that prints its own text and
rem  exits with an error, so the py launcher is asked first.
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

%PYEXE% "%~dp0start.py" %MTGH_HOST% %MTGH_PORT%
if errorlevel 1 pause

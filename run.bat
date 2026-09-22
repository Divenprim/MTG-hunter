@echo off
setlocal
cd /d "%~dp0"

rem  run.bat        -- только этот компьютер (по умолчанию)
rem  run.bat lan    -- видно всей локальной сети: с планшета, с телефона
rem
rem  В сетевом режиме пароля нет: кто в этой сети, тот и видит вашу коллекцию.
rem  Windows при первом запуске спросит про брандмауэр -- разрешать надо для
rem  частной сети.
set "MTGH_HOST=127.0.0.1"
set "MTGH_PORT=8765"
if /i "%~1"=="lan" set "MTGH_HOST=0.0.0.0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating virtual environment...
    python -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    echo [setup] installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

if not exist "data\sets.json" (
    echo [setup] fetching the set list from Scryfall...
    ".venv\Scripts\python.exe" fetch_sets.py || goto :fail
)

if not exist "data\cards.sqlite" goto :build_cards

rem A failed or interrupted build can leave cards.sqlite behind.  Validate all
rem indexes and completion metadata instead of trusting the file's existence.
".venv\Scripts\python.exe" build_db.py --check >nul 2>nul
if errorlevel 1 (
    echo [setup] card database is incomplete; rebuilding it...
    goto :build_cards
)
goto :cards_ready

:build_cards
echo [setup] building the card database ^(this takes a few minutes^)...
".venv\Scripts\python.exe" build_db.py || goto :fail

:cards_ready

echo [run] starting on http://127.0.0.1:%MTGH_PORT%
start "" http://127.0.0.1:%MTGH_PORT%
".venv\Scripts\python.exe" -m uvicorn app.main:app --host %MTGH_HOST% --port %MTGH_PORT%
goto :eof

:fail
echo.
echo [error] setup failed. See the messages above.
pause

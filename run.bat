@echo off
setlocal
cd /d "%~dp0"

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

if not exist "data\cards.sqlite" (
    echo [setup] card database not found, building it once ^(this takes a few minutes^)...
    ".venv\Scripts\python.exe" build_db.py || goto :fail
)

echo [run] starting on http://127.0.0.1:8765
start "" http://127.0.0.1:8765
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8765
goto :eof

:fail
echo.
echo [error] setup failed. See the messages above.
pause

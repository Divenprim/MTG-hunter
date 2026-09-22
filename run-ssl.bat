@echo off
setlocal
cd /d "%~dp0"

rem  Сервер по https для планшета: без этого браузер не даёт камеру, а
rem  значит не работает сканер. Сертификат свой, локальный; на планшет он
rem  ставится один раз -- как именно, напечатает make_cert.py.

if not exist ".venv\Scripts\python.exe" (
    echo [error] сначала запустите run.bat -- он поставит окружение.
    pause & goto :eof
)

".venv\Scripts\python.exe" -c "import cryptography" 2>nul
if errorlevel 1 (
    echo [setup] ставлю cryptography...
    ".venv\Scripts\python.exe" -m pip install cryptography || goto :fail
)

if not exist "data\cert\cert.pem" (
    echo [setup] делаю сертификат...
    ".venv\Scripts\python.exe" make_cert.py || goto :fail
)

set "MTGH_HOST=0.0.0.0"
set "MTGH_PORT=8765"
set "MTGH_CA_PORT=8766"
echo [run] https://127.0.0.1:8765
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --ssl-keyfile data\cert\key.pem --ssl-certfile data\cert\cert.pem
goto :eof

:fail
echo.
echo [error] не получилось. Смотрите сообщения выше.
pause

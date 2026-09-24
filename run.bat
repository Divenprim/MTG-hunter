@echo off
setlocal enabledelayedexpansion
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

rem ------------------------------------------------------------------ python
rem  Найти питон -- отдельная задача, а не одна команда. В Windows 11 «python»
rem  из коробки ведёт не в питон, а в заглушку магазина: она печатает своё и
rem  выходит с ошибкой. Поэтому сперва спрашиваем лаунчер «py», который ставит
rem  сам установщик с python.org, и только потом «python» из PATH.
set "PYEXE="
for %%P in ("py -3.12" "py -3" "python" "python3") do (
    if not defined PYEXE (
        %%~P -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYEXE=%%~P"
    )
)

if not defined PYEXE (
    echo.
    echo [ошибка] не нашёлся Python 3.10 или новее.
    echo.
    echo   Скачайте его с https://www.python.org/downloads/ и при установке
    echo   обязательно отметьте галочку «Add python.exe to PATH».
    echo.
    echo   Если Python вы уже ставили, а эта надпись всё равно появилась --
    echo   скорее всего сработала заглушка из Microsoft Store. Откройте
    echo   «Параметры» ^> «Приложения» ^> «Дополнительные параметры приложения»
    echo   ^> «Псевдонимы выполнения приложения» и выключите там python.exe.
    echo.
    pause
    goto :eof
)

rem ------------------------------------------------------------- окружение
if exist ".venv\Scripts\python.exe" (
    rem  Окружение может остаться от переноса папки или от оборванной
    rem  установки: файл на месте, а внутри пусто. Проверяем делом.
    ".venv\Scripts\python.exe" -c "import fastapi, uvicorn" >nul 2>nul
    if errorlevel 1 (
        echo [setup] окружение неисправно -- собираю заново...
        rmdir /s /q ".venv" 2>nul
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [setup] создаю окружение...
    %PYEXE% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    echo [setup] ставлю зависимости ^(несколько минут, качается ~150 МБ^)...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
    copy /y requirements.txt ".venv\requirements.stamp" >nul
)

rem  Зависимости могли появиться после обновления программы: окружение уже
rem  есть, а нового в нём нет. Сверяем requirements.txt с тем, чем ставили в
rem  прошлый раз, -- и доставляем, только если список изменился.
fc /b requirements.txt ".venv\requirements.stamp" >nul 2>nul
if errorlevel 1 (
    echo [setup] обновляю зависимости...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
    copy /y requirements.txt ".venv\requirements.stamp" >nul
)

rem ------------------------------------------------------------------ данные
if not exist "data\sets.json" (
    echo [setup] качаю список сетов со Scryfall...
    ".venv\Scripts\python.exe" fetch_sets.py || goto :fail
)

if not exist "data\cards.sqlite" goto :build_cards

rem  Оборванная сборка оставляет после себя cards.sqlite, который выглядит
rem  готовым. Проверяем индексы и отметку о завершении, а не наличие файла.
".venv\Scripts\python.exe" build_db.py --check >nul 2>nul
if errorlevel 1 (
    echo [setup] база карт неполная -- пересобираю...
    goto :build_cards
)
goto :cards_ready

:build_cards
echo [setup] собираю базу карт ^(несколько минут, качается ~100 МБ^)...
".venv\Scripts\python.exe" build_db.py || goto :fail

:cards_ready

rem ------------------------------------------------------------------ запуск
rem  Браузер открывается не сразу, а когда сервер начал отвечать: раньше он
rem  успевал показать «не удаётся подключиться», и это выглядело как будто
rem  программа не запустилась.
start "" /b ".venv\Scripts\python.exe" open_browser.py %MTGH_PORT%

echo [run] http://127.0.0.1:%MTGH_PORT%  ^(остановить -- Ctrl+C^)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host %MTGH_HOST% --port %MTGH_PORT%
if errorlevel 1 goto :fail
goto :eof

:fail
echo.
echo [ошибка] не получилось. Что произошло -- написано выше.
echo.
echo   Чаще всего это одно из двух: нет интернета, либо порт %MTGH_PORT% уже
echo   занят другой копией программы.
echo.
pause

"""Первый запуск: окружение, зависимости, база карт -- и сам запуск.

Почему это не .bat. Батник печатает байты как есть, а консоль читает их в
кодировке OEM (866 в русской Windows). Файл в UTF-8 -- и вместо «создаю
окружение» пользователь видит «СЃРѕР·РґР°СЋ». Python в консоль Windows пишет
юникодом, поэтому русский текст отсюда читается при любой кодовой странице.
В run.bat остался только ASCII: найти питон и передать управление сюда.

Запускается **системным** питоном, поэтому здесь нельзя ничего, кроме
стандартной библиотеки.

Всё, что печатается, дублируется в data/setup.log (UTF-8): если запуск
оборвался, этот файл отвечает на вопрос «что случилось» лучше, чем память о
промелькнувшем окне.

    python start.py [хост] [порт]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, ".venv")
VENV_PY = os.path.join(VENV, "Scripts", "python.exe")
STAMP = os.path.join(VENV, "requirements.stamp")
REQS = os.path.join(ROOT, "requirements.txt")
DATA = os.path.join(ROOT, "data")
LOG = os.path.join(DATA, "setup.log")
CARDS = os.path.join(DATA, "cards.sqlite")
SETS = os.path.join(DATA, "sets.json")

MIN_PYTHON = (3, 10)
PORTABLE = os.environ.get("MTGH_PORTABLE") == "1"
RUNTIME_PY = sys.executable if PORTABLE else VENV_PY

# Ctrl+C и закрытие окна -- это не поломка. Windows возвращает при этом свои
# коды, и пугать ими человека, который сам остановил программу, незачем.
STOPPED_BY_HAND = (0xC000013A, 0xC000013A - (1 << 32), -1, 0xFFFFFFFF, 2)


def console_speaks_utf8() -> None:
    """Договориться с консолью о кодировке -- до первой напечатанной буквы.

    Русская Windows показывает консоль в кодовой странице 866, а питон пишет
    UTF-8. Пока эти двое не договорились, вместо «создаю окружение» на экране
    «СЃРѕР·РґР°СЋ». Поэтому: консоли говорим «жди UTF-8», себе и всем
    запускаемым отсюда программам (pip, uvicorn) -- «пиши UTF-8».

    Всё делается мягко: на системе без этих вызовов программа просто
    продолжит работу.
    """
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"


def say(text: str = "") -> None:
    """Напечатать и запомнить. Печать -- юникодом, лог -- в UTF-8."""
    print(text, flush=True)
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def run(args: list[str], what: str) -> None:
    """Выполнить и объяснить, если не вышло."""
    say("[setup] %s" % what)
    try:
        done = subprocess.run(args, cwd=ROOT)
    except OSError as exc:
        raise Setback("не удалось запустить: %s" % exc)
    if done.returncode != 0:
        raise Setback("шаг «%s» закончился ошибкой (код %d)"
                      % (what, done.returncode))


class Setback(Exception):
    """Понятная остановка: причина уже сформулирована по-русски."""


def venv_is_alive() -> bool:
    """Окружение есть -- но работает ли оно.

    Папку .venv переносят вместе с программой, а внутри лежат абсолютные пути;
    установка обрывается и оставляет полупустую папку. Наличие файла ничего не
    доказывает, поэтому спрашиваем делом.
    """
    if not os.path.exists(VENV_PY):
        return False
    try:
        done = subprocess.run([VENV_PY, "-c", "import fastapi, uvicorn"],
                              cwd=ROOT, capture_output=True)
    except OSError:
        return False
    return done.returncode == 0


def requirements_changed() -> bool:
    """Список зависимостей не тот, которым ставили в прошлый раз."""
    if not os.path.exists(STAMP):
        return True
    try:
        with open(REQS, "rb") as a, open(STAMP, "rb") as b:
            return a.read() != b.read()
    except OSError:
        return True


def remember_requirements() -> None:
    try:
        shutil.copyfile(REQS, STAMP)
    except OSError:
        pass


def _portable_runtime_is_alive() -> bool:
    """The release carries its own Python and runtime dependencies."""
    try:
        done = subprocess.run(
            [RUNTIME_PY, "-c",
             "import fastapi, uvicorn, requests, pydantic, PIL, numpy, cv2"],
            cwd=ROOT, capture_output=True)
    except OSError:
        return False
    return done.returncode == 0


def prepare() -> None:
    if PORTABLE:
        if not _portable_runtime_is_alive():
            raise Setback(
                "встроенная среда релиза повреждена — скачайте архив релиза заново")
    elif not venv_is_alive():
        if os.path.exists(VENV):
            say("[setup] окружение неисправно — собираю заново")
            shutil.rmtree(VENV, ignore_errors=True)
        run([sys.executable, "-m", "venv", VENV], "создаю окружение")
        subprocess.run([VENV_PY, "-m", "pip", "install", "--upgrade", "pip"],
                       cwd=ROOT, capture_output=True)
        run([VENV_PY, "-m", "pip", "install", "-r", REQS],
            "ставлю зависимости (несколько минут, качается ~150 МБ)")
        remember_requirements()
    elif requirements_changed():
        run([VENV_PY, "-m", "pip", "install", "-r", REQS],
            "обновляю зависимости")
        remember_requirements()

    if not os.path.exists(SETS):
        run([RUNTIME_PY, "fetch_sets.py"], "качаю список сетов со Scryfall")

    whole = False
    if os.path.exists(CARDS):
        done = subprocess.run([RUNTIME_PY, "build_db.py", "--check"], cwd=ROOT,
                              capture_output=True)
        whole = done.returncode == 0
        if not whole:
            say("[setup] база карт неполная — пересобираю")
    if not whole:
        run([RUNTIME_PY, "build_db.py"],
            "собираю базу карт (несколько минут, качается ~100 МБ)")


def prepare_ssl() -> list[str]:
    """Свой сертификат для планшета: без https браузер не даёт камеру."""
    done = subprocess.run([RUNTIME_PY, "-c", "import cryptography"], cwd=ROOT,
                          capture_output=True)
    if done.returncode != 0:
        if PORTABLE:
            raise Setback(
                "встроенная поддержка HTTPS повреждена — скачайте архив релиза заново")
        run([VENV_PY, "-m", "pip", "install", "cryptography"],
            "ставлю cryptography")
    cert = os.path.join(DATA, "cert", "cert.pem")
    key = os.path.join(DATA, "cert", "key.pem")
    if not os.path.exists(cert):
        run([VENV_PY, "make_cert.py"], "делаю сертификат")
    return ["--ssl-keyfile", key, "--ssl-certfile", cert]


def serve(host: str, port: str, ssl: bool = False) -> int:
    """Запустить сервер и открыть браузер, когда он начнёт отвечать."""
    extra = prepare_ssl() if ssl else []
    # Сервер печатает адреса для планшета, только если знает, что открыт в
    # сеть; а корневой сертификат надо чем-то отдать -- по https планшет за
    # ним не придёт, он этого сертификата ещё не знает.
    os.environ["MTGH_HOST"] = host
    os.environ["MTGH_PORT"] = port
    if ssl:
        os.environ.setdefault("MTGH_CA_PORT", "8766")
        os.environ["MTGH_SCHEME"] = "https"
    opener = None
    if not ssl:
        opener = subprocess.Popen(
            [RUNTIME_PY, os.path.join(ROOT, "open_browser.py"), port], cwd=ROOT)
    say("[run] %s://127.0.0.1:%s   (остановить — Ctrl+C)"
        % ("https" if ssl else "http", port))
    if host == "0.0.0.0":
        say("      с планшета и телефона — по адресу этого компьютера в сети")
    try:
        done = subprocess.run(
            [RUNTIME_PY, "-m", "uvicorn", "app.main:app", "--host", host,
             "--port", port] + extra, cwd=ROOT)
    except KeyboardInterrupt:
        return 0
    finally:
        if opener is not None and opener.poll() is None:
            opener.terminate()
    return done.returncode


def main(argv: list[str]) -> int:
    console_speaks_utf8()
    host = argv[0] if argv else "127.0.0.1"
    port = argv[1] if len(argv) > 1 else "8765"
    ssl = "ssl" in argv[2:]

    if sys.version_info < MIN_PYTHON:
        say("Нужен Python %d.%d или новее, а этот — %s"
            % (MIN_PYTHON[0], MIN_PYTHON[1], sys.version.split()[0]))
        return 1

    say("")
    say("--- %s ---" % time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        prepare()
    except Setback as stop:
        say("")
        say("[не получилось] %s" % stop)
        say("")
        say("Что обычно помогает:")
        say("  * проверить интернет: и зависимости, и база карт качаются;")
        if PORTABLE:
            say("  * скачать portable-архив релиза заново и распаковать целиком;")
            say("    папку data сохраните — в ней ваши колоды и коллекция.")
        else:
            say("  * удалить папку .venv и запустить run.bat заново — окружение")
            say("    соберётся с нуля (папку data не трогайте, в ней ваши колоды);")
        say("  * если ругается антивирус или прокси — они любят обрывать pip.")
        say("")
        say("Подробности записаны в %s" % LOG)
        return 1
    except KeyboardInterrupt:
        say("[setup] прервано")
        return 1

    try:
        code = serve(host, port, ssl)
    except Setback as stop:
        say("")
        say("[не получилось] %s" % stop)
        say("Подробности записаны в %s" % LOG)
        return 1
    if code and code not in STOPPED_BY_HAND:
        say("")
        say("[не получилось] сервер остановился с ошибкой (код %d)." % code)
        say("Чаще всего порт %s уже занят другой копией программы." % port)
        say("Подробности записаны в %s" % LOG)
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

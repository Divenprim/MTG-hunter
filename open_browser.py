"""Открыть программу в браузере, когда сервер начнёт отвечать.

Раньше run.bat открывал браузер сразу же, а сервер к этому моменту ещё
поднимался: пользователь видел «не удаётся подключиться» и решал, что
программа не запустилась. Здесь браузер ждёт ответа -- и открывается один
раз, когда открывать уже есть что.

Ждём не вечно: если за минуту сервер не ответил, значит дело не в скорости
запуска, и незачем открывать вкладку с ошибкой -- в окне run.bat к этому
времени уже написано, что случилось.

    python open_browser.py [порт]
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
import webbrowser

WAIT_SECONDS = 60.0
STEP = 0.4


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8765"
    url = "http://127.0.0.1:%s/" % port
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as answer:
                if answer.status < 500:
                    webbrowser.open(url)
                    return 0
        except urllib.error.HTTPError:
            # Ответ есть, пусть и не двухсотый: сервер поднялся.
            webbrowser.open(url)
            return 0
        except Exception:
            pass
        time.sleep(STEP)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

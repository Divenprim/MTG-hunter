"""Собрать базу отпечатков артов -- то, чем сканер узнаёт карту по камере.

    .venv/Scripts/python.exe build_art.py            # по одной печати на карту
    .venv/Scripts/python.exe build_art.py --all      # все печати
    .venv/Scripts/python.exe build_art.py --check    # что уже собрано

Первый вариант -- около 36 тысяч картинок, примерно час: узнаёт карту, но не
обязательно её конкретную печать. Второй -- 108 тысяч, около трёх часов: тогда
узнаётся и печать, а значит и цена берётся от той же версии.

Прерывать можно в любой момент: следующий запуск продолжит с того же места.
Картинки не хранятся -- только два числа на печать.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import artscan  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


if __name__ == "__main__":
    if "--check" in sys.argv:
        state = artscan.status()
        print("отпечатков: %d, не вышло: %d, объём: %s" % (
            state["hashed"], state["failed"], state["scope"] or "—"))
        raise SystemExit(0 if state["built"] else 1)

    scope = "all" if "--all" in sys.argv else "representative"
    result = artscan.build(scope=scope, progress=log)
    print("ИТОГ:", result)

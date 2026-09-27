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

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from app import artscan  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="hash every printing instead of one representative per card")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("MTGH_ART_WORKERS", "12")))
    parser.add_argument("--rate", type=float, default=float(os.environ.get("MTGH_ART_RATE", "20")))
    args = parser.parse_args()

    if args.check:
        state = artscan.status()
        print("отпечатков: %d, не вышло: %d, объём: %s" % (
            state["hashed"], state["failed"], state["scope"] or "—"))
        raise SystemExit(0 if state["built"] else 1)

    scope = "all" if args.all else "representative"
    result = artscan.build(
        scope=scope,
        workers=max(1, args.workers),
        per_second=max(0.1, args.rate),
        progress=log,
    )
    print("ИТОГ:", result)

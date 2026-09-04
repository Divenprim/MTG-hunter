"""Build the local card database. Run once, then re-run to refresh."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import build_database  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


if __name__ == "__main__":
    include_ru = "--no-russian" not in sys.argv
    result = build_database(include_russian=include_ru, progress=log)
    print("RESULT:", result)

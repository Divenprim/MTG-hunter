"""Build the local card database. Run once, then re-run to refresh."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import build_database, database_is_complete  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


if __name__ == "__main__":
    if "--check" in sys.argv:
        complete = database_is_complete()
        print("Card database is complete." if complete else "Card database is incomplete.")
        raise SystemExit(0 if complete else 1)
    include_ru = "--no-russian" not in sys.argv
    result = build_database(include_russian=include_ru, progress=log)
    print("RESULT:", result)

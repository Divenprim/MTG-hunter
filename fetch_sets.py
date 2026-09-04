"""Download the list of Magic sets into data/sets.json.

The line parser needs it: seller lines say "M10", "c18-143", "Commander 2019",
and turning those into a real set is what makes an offer identifiable. Nothing
else in the project creates this file, so a fresh clone has to fetch it before
the first run -- run.bat does it automatically when the file is missing.

One request to Scryfall, about 600 KB, no key required. Re-run it after a new
set comes out.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

URL = "https://api.scryfall.com/sets"
USER_AGENT = "mtg-hunter/1.0 (local deckbuilding tool)"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TARGET = os.path.join(DATA_DIR, "sets.json")


def fetch(target: str = TARGET) -> dict[str, int]:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    request = urllib.request.Request(
        URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)

    sets = payload.get("data") or []
    if not sets:
        raise SystemExit("Scryfall вернул пустой список сетов — файл не тронут")

    # Written whole, then moved into place: a half-written sets.json would break
    # every line parse until someone noticed.
    tmp = target + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"data": sets}, fh, ensure_ascii=False)
    os.replace(tmp, target)
    return {"sets": len(sets), "bytes": os.path.getsize(target)}


if __name__ == "__main__":
    result = fetch()
    print("сетов: %d, файл: %s (%.0f КБ)" % (
        result["sets"], TARGET, result["bytes"] / 1024))
    sys.exit(0)

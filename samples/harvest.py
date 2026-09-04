"""Harvest a diverse real sample of topdeck listing lines for parser development."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.topdeck import TopdeckClient  # noqa: E402

# Spread across eras, formats, rarities and languages so we see many writing styles.
CARDS = [
    "Lightning Bolt",
    "Force of Will",
    "Ragavan, Nimble Pilferer",
    "Sol Ring",
    "Brainstorm",
    "Thoughtseize",
    "Snapcaster Mage",
    "Mana Crypt",
    "Cyclonic Rift",
    "Underground Sea",
    "Wrenn and Six",
    "Ancient Tomb",
    "Birds of Paradise",
    "Counterspell",
    "Swords to Plowshares",
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offers.json")


def main() -> None:
    client = TopdeckClient(delay=2.0)
    all_offers = []
    # Batch them a few at a time; one giant query risks a slow/huge response.
    batch_size = 5
    for i in range(0, len(CARDS), batch_size):
        batch = CARDS[i : i + batch_size]
        print("searching:", ", ".join(batch), flush=True)
        try:
            offers = client.search(batch)
        except Exception as exc:  # noqa: BLE001
            print("  FAILED:", exc, flush=True)
            continue
        print("  ->", len(offers), "offers", flush=True)
        all_offers.extend(o.as_dict() for o in offers)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(all_offers, fh, ensure_ascii=False, indent=1)
    print("total", len(all_offers), "offers ->", OUT)


if __name__ == "__main__":
    main()

"""Goldfishing: opening hands and draw simulation.

What people actually use goldfishing for is answering "does this deck function
on turns 1-4" -- do I hit my land drops, is my hand keepable, can I cast
anything. That is a shuffling question, and it is answered far better by
simulating a thousand games than by dealing one hand by hand.

The assumptions are stated openly, both here and in the UI, because a
simulation that hides them is worse than no simulation:

  * one land per turn, played from hand as soon as one is there;
  * ramp, fetchlands, cantrips and card selection are NOT modelled -- a deck
    full of them will do better in reality than these numbers suggest;
  * no mulligan decisions: the opening-hand figures describe the raw seven.
"""

from __future__ import annotations

import random
import statistics
from typing import Any

HAND_SIZE = 7
KEEPABLE_LANDS = (2, 3, 4, 5)


def build_library(deck: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the deck into a shuffleable list.

    Commanders are excluded: they start in the command zone, not the library.
    """
    library: list[dict[str, Any]] = []
    for row in deck.get("cards", []):
        if row.get("section") != "main":
            continue
        card = row.get("card") or {}
        type_line = (card.get("type_line") or "").lower()
        entry = {
            "name": (card.get("name") or row["name"]),
            "cmc": float(card.get("cmc") or 0),
            "is_land": "land" in type_line,
            "image_small": card.get("image_small"),
            "mana_cost": card.get("mana_cost"),
            "type_line": card.get("type_line"),
        }
        library.extend([dict(entry) for _ in range(int(row.get("quantity") or 1))])
    return library


def simulate(
    deck: dict[str, Any],
    games: int = 1000,
    hand_size: int = HAND_SIZE,
    turns: int = 5,
    seed: int | None = None,
) -> dict[str, Any]:
    library = build_library(deck)
    if len(library) < hand_size:
        return {
            "error": "В основной колоде %d карт — для раздачи нужно хотя бы %d"
                     % (len(library), hand_size),
        }

    rng = random.Random(seed)
    games = max(1, min(int(games), 20000))

    land_counts: list[int] = []
    keepable = 0
    hand_mvs: list[float] = []
    # turn on which the Nth land was played, per game (None if never)
    reach_turn: dict[int, list[int]] = {3: [], 4: []}
    playable_by_turn = {t: 0 for t in range(1, turns + 1)}

    for _ in range(games):
        deck_copy = library[:]
        rng.shuffle(deck_copy)
        hand = deck_copy[:hand_size]
        rest = deck_copy[hand_size:]

        lands_in_hand = sum(1 for c in hand if c["is_land"])
        land_counts.append(lands_in_hand)
        if lands_in_hand in KEEPABLE_LANDS:
            keepable += 1
        nonland_mvs = [c["cmc"] for c in hand if not c["is_land"]]
        if nonland_mvs:
            hand_mvs.append(sum(nonland_mvs) / len(nonland_mvs))

        # Play out the first `turns` turns: one land drop a turn if available,
        # one card drawn a turn.
        current_hand = hand[:]
        lands_played = 0
        seen_targets = {3: None, 4: None}
        for turn in range(1, turns + 1):
            if turn > 1 and rest:
                current_hand.append(rest.pop(0))

            land_in_hand = next((c for c in current_hand if c["is_land"]), None)
            if land_in_hand is not None:
                current_hand.remove(land_in_hand)
                lands_played += 1
                for target in seen_targets:
                    if seen_targets[target] is None and lands_played >= target:
                        seen_targets[target] = turn

            # Something castable this turn with the mana we have on the table.
            if any(not c["is_land"] and c["cmc"] <= lands_played for c in current_hand):
                playable_by_turn[turn] += 1

        for target, turn in seen_targets.items():
            if turn is not None:
                reach_turn[target].append(turn)

    distribution = {n: land_counts.count(n) for n in range(0, hand_size + 1)}
    return {
        "games": games,
        "hand_size": hand_size,
        "library": len(library),
        "lands_in_library": sum(1 for c in library if c["is_land"]),
        "avg_lands_in_hand": round(statistics.mean(land_counts), 2),
        "land_distribution": distribution,
        "keepable_pct": round(100.0 * keepable / games, 1),
        "avg_hand_mv": round(statistics.mean(hand_mvs), 2) if hand_mvs else None,
        "reach_3_lands": {
            "pct": round(100.0 * len(reach_turn[3]) / games, 1),
            "avg_turn": round(statistics.mean(reach_turn[3]), 2) if reach_turn[3] else None,
        },
        "reach_4_lands": {
            "pct": round(100.0 * len(reach_turn[4]) / games, 1),
            "avg_turn": round(statistics.mean(reach_turn[4]), 2) if reach_turn[4] else None,
        },
        "playable_by_turn": {
            t: round(100.0 * n / games, 1) for t, n in playable_by_turn.items()
        },
        "assumptions": [
            "одна земля за ход, как только появилась в руке",
            "рампа, фетчи и кантрипы НЕ учитываются — с ними в реальности будет лучше",
            "муллиганы не моделируются: цифры описывают сырые семь карт",
        ],
    }


def deal(deck: dict[str, Any], hand_size: int = HAND_SIZE, seed: int | None = None) -> dict[str, Any]:
    """One shuffled hand, for playing by hand in the UI."""
    library = build_library(deck)
    if len(library) < hand_size:
        return {"error": "В основной колоде всего %d карт" % len(library)}
    rng = random.Random(seed)
    rng.shuffle(library)
    return {
        "hand": library[:hand_size],
        "library": library[hand_size:],
        "library_size": len(library) - hand_size,
    }

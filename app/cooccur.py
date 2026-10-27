"""What the decks that look like yours play, and you do not.

This is the one question the aggregated numbers cannot answer. EDHREC says
"Sol Ring is in 78% of decks with this commander" -- true, and the same for
everyone playing that commander. It cannot say "of the decks that already run
your seven cards, most also run this one", because that depends on your deck.

So: a sample of real decklists (app/archidekt.py), and four statistics over it.

**Neighbours.** Every sampled deck is scored by how many cards it shares with
yours, basics excluded because everybody plays Mountains. The closest few dozen
are the neighbourhood, and a card is suggested by how much of that
neighbourhood runs it. Beside that number is the same card's share of the whole
sample, and the ratio between them: a card at 80% among neighbours and 30%
overall is a card your build wants in particular, not a staple.

Nearest neighbours rather than pairwise conditional probability on purpose. A
sample of a couple of hundred decks gives solid counts for a neighbourhood of
thirty; conditioning card-by-card on a dozen of your cards at once would divide
the same sample into slices too thin to mean anything.

**Pairs.** For one card you already play, what tends to travel with it, again
against its own base rate. This is the "package" question -- these three cards
turn up together -- in the form that a sample this size can actually support.

**Копии.** Вопрос не «что добавить», а «по сколько». В 60-карточном формате
между одной копией и четырьмя лежит половина разницы между колодами: карта по
одной копии -- это карта, которую вы увидите в трети игр. Считается медиана по
соседям, которые эту карту играют, и сравнивается с вашим числом. В
командирской колоде вопроса нет -- там всё по одной, -- поэтому и ответ пуст.

**Сайдборд.** Пятнадцать карт, которых в списке «чего не хватает» не было
никогда: добор, подсказки и покупки смотрели только в мейн. У соседей он
скачан вместе с колодой, и вопрос тот же самый -- что держат против вас те,
кто играет то же, что вы.

Names are compared through normalize_name, so a Russian name in your deck and
Archidekt's English one are the same card.
"""

from __future__ import annotations

from typing import Any, Iterable

from .archidekt import BASICS, deck_main, deck_meta, deck_side
from .cards import CardDB, normalize_name

# A deck with almost nothing in it has no meaningful neighbours: below this
# much overlap the "closest" decks are just the first ones in the list.
MIN_OVERLAP = 5

# How many neighbours to average over, and the fewest that still count as a
# neighbourhood rather than an accident.
NEAR_DECKS = 30
MIN_NEIGHBOURS = 8

# Above this share of the sample a card is in nearly every deck, and asking
# what travels with it is a degenerate question: everything does, and every
# lift collapses to the same ratio (1 / share). Worth saying out loud rather
# than presenting the arithmetic as a discovery.
UBIQUITOUS = 0.7


def _keys(names: Iterable[str]) -> set[str]:
    """Comparable card names, without the basics everyone plays."""
    out = set()
    for name in names:
        key = normalize_name(name or "")
        if not key or key in BASICS:
            continue
        out.add(key)
    return out


def _counts(cards: dict[str, int]) -> dict[str, int]:
    """Копии по сравнимым именам, без базовых земель."""
    out: dict[str, int] = {}
    for name, qty in (cards or {}).items():
        key = normalize_name(name or "")
        if not key or key in BASICS:
            continue
        out[key] = out.get(key, 0) + int(qty or 1)
    return out


def sample_rows(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """Каждая колода выборки в удобном для счёта виде.

    Колоды в кеше лежат двух видов -- старые списком имён, новые разбором с
    копиями и сайдом, -- и разбирать это здесь не нужно: читают их
    `archidekt.deck_main` и соседи.
    """
    rows = []
    for deck_id, entry in (sample.get("decks") or {}).items():
        main = deck_main(entry)
        if not main:
            continue
        side = deck_side(entry)
        rows.append({
            "id": deck_id,
            "names": list(main.keys()),
            "keys": _keys(main.keys()),
            "main": _counts(main),
            "side": _counts(side),
            "side_names": list(side.keys()),
            "side_keys": _keys(side.keys()),
            "meta": deck_meta(entry),
        })
    return rows


def sample_decks(sample: dict[str, Any]) -> list[tuple[str, list[str], set[str]]]:
    """(deck id, names as given, comparable keys) for every sampled deck."""
    return [(row["id"], row["names"], row["keys"]) for row in sample_rows(sample)]


def neighbourhood(
    mine: set[str],
    decks: list[tuple[str, list[str], set[str]]],
    near: int = NEAR_DECKS,
) -> tuple[list[tuple[int, str, set[str]]], bool]:
    """The most similar decks, and whether we had to fall back to all of them."""
    scored = sorted(
        ((len(mine & keys), deck_id, keys) for deck_id, _names, keys in decks),
        key=lambda row: -row[0],
    )
    close = [row for row in scored if row[0] >= MIN_OVERLAP][:max(1, near)]
    if len(close) >= MIN_NEIGHBOURS:
        return close, False
    # Not enough of the sample resembles this deck -- an empty or very unusual
    # list. Then the honest answer is the whole sample, said out loud.
    return scored[:max(1, near)], True


def _display_names(decks: list[tuple[str, list[str], set[str]]]) -> dict[str, str]:
    """Key -> the name to show, taken from the sample itself."""
    names: dict[str, str] = {}
    for _deck_id, raw, _keys_ in decks:
        for name in raw:
            key = normalize_name(name or "")
            if key and key not in names:
                names[key] = name
    return names


def suggest(
    deck_names: Iterable[str],
    sample: dict[str, Any],
    near: int = NEAR_DECKS,
    limit: int = 60,
    min_share: float = 0.2,
    exclude: Iterable[str] = (),
) -> dict[str, Any]:
    """Cards the decks closest to yours run and yours does not.

    `exclude` is for cards that are yours by definition rather than by being
    in the list -- the commander above all: suggesting someone their own
    commander is the kind of answer that makes the rest look untrustworthy.
    """
    decks = sample_decks(sample)
    mine = _keys(deck_names)
    skip = _keys(exclude)
    if not decks:
        # `overlap` здесь тоже нужен. Без него пустая выборка роняла
        # ответ целиком: вызывающий читает поле всегда, а не только когда
        # колоды нашлись, -- и спрашивать выборку, которой ещё нет, это
        # обычный случай, а не ошибка.
        return {"decks": 0, "near": 0, "overlap": 0, "fallback": False,
                "cards": []}

    close, fallback = neighbourhood(mine, decks, near)
    close_keys = [keys for _score, _deck_id, keys in close]

    near_count: dict[str, int] = {}
    for keys in close_keys:
        for key in keys - mine - skip:
            near_count[key] = near_count.get(key, 0) + 1

    all_count: dict[str, int] = {}
    for _deck_id, _raw, keys in decks:
        for key in keys:
            all_count[key] = all_count.get(key, 0) + 1

    shown = _display_names(decks)
    total_near = len(close_keys) or 1
    total_all = len(decks)

    rows = []
    for key, count in near_count.items():
        near_share = count / total_near
        if near_share < min_share:
            continue
        all_share = all_count.get(key, 0) / total_all if total_all else 0.0
        rows.append({
            "name": shown.get(key, key),
            "near_decks": count,
            "near_of": total_near,
            "near_share": round(near_share, 4),
            "all_decks": all_count.get(key, 0),
            "all_share": round(all_share, 4),
            # How much more usual this card is among decks like yours than in
            # the sample at large. 1.0 means "just as usual" -- a staple.
            "lift": round(near_share / all_share, 3) if all_share else None,
        })

    rows.sort(key=lambda r: (-r["near_share"], -(r["lift"] or 0)))
    return {
        "decks": total_all,
        "near": total_near,
        "overlap": close[0][0] if close else 0,
        "fallback": fallback,
        "cards": rows[:max(1, limit)],
    }


def pairs_for(
    card: str,
    sample: dict[str, Any],
    limit: int = 20,
    min_together: int = 3,
) -> dict[str, Any]:
    """What travels with this card in the sample, against its own base rate."""
    decks = sample_decks(sample)
    key = normalize_name(card or "")
    withit = [keys for _deck_id, _raw, keys in decks if key in keys]
    if not withit:
        return {"card": card, "decks": len(decks), "with_card": 0, "cards": []}

    together: dict[str, int] = {}
    for keys in withit:
        for other in keys:
            if other == key:
                continue
            together[other] = together.get(other, 0) + 1

    all_count: dict[str, int] = {}
    for _deck_id, _raw, keys in decks:
        for name_key in keys:
            all_count[name_key] = all_count.get(name_key, 0) + 1

    shown = _display_names(decks)
    rows = []
    for other, count in together.items():
        if count < min_together:
            continue
        share = count / len(withit)
        base = all_count.get(other, 0) / len(decks) if decks else 0.0
        rows.append({
            "name": shown.get(other, other),
            "together": count,
            "of": len(withit),
            "share": round(share, 4),
            "base_share": round(base, 4),
            "lift": round(share / base, 3) if base else None,
        })
    rows.sort(key=lambda r: (-(r["lift"] or 0), -r["share"]))
    return {
        "card": card,
        "decks": len(decks),
        "with_card": len(withit),
        "ubiquitous": len(withit) / len(decks) >= UBIQUITOUS if decks else False,
        "cards": rows[:max(1, limit)],
    }


def _rows_near(
    mine: set[str],
    rows: list[dict[str, Any]],
    near: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Соседи колоды -- те же, что у `suggest`, но строками целиком."""
    decks = [(row["id"], row["names"], row["keys"]) for row in rows]
    close, fallback = neighbourhood(mine, decks, near)
    by_id = {row["id"]: row for row in rows}
    return [by_id[deck_id] for _score, deck_id, _keys_ in close if deck_id in by_id], fallback


def _shown_names(rows: list[dict[str, Any]], where: str = "main") -> dict[str, str]:
    """Ключ -> имя, как его пишут в выборке."""
    names: dict[str, str] = {}
    for row in rows:
        source = row["names"] if where == "main" else (row.get("side_names") or [])
        for name in source:
            key = normalize_name(name or "")
            if key and key not in names:
                names[key] = name
    return names


def _median(values: list[int]) -> int:
    values = sorted(values)
    return values[len(values) // 2] if values else 0


# Сколько соседей должны играть карту, чтобы про число её копий вообще
# стоило говорить. Три колоды -- это не «обычно играют по четыре», это три
# колоды.
MIN_FOR_COPIES = 5


def copies(
    deck_counts: dict[str, int],
    sample: dict[str, Any],
    near: int = NEAR_DECKS,
    limit: int = 30,
    min_decks: int = MIN_FOR_COPIES,
) -> dict[str, Any]:
    """По сколько копий соседи играют то, что уже стоит у вас.

    Отвечает на вопрос, которого в программе не было: не «чего нет», а
    «чего мало». Карта по одной копии в 60-карточной колоде попадается
    примерно в трети игр -- если у соседей она стоит по четыре, это не
    мелочь, а другой расчёт колоды.

    Счёт идёт только по тем соседям, которые карту вообще играют: медиана
    по всей округе провалилась бы в ноль на любой карте, которая не стоит
    в каждой второй колоде.
    """
    rows = sample_rows(sample)
    mine = _counts(deck_counts)
    if not rows or not mine:
        return {"decks": len(rows), "near": 0, "cards": [], "flat": True}

    close, fallback = _rows_near(set(mine), rows, near)
    if not close:
        return {"decks": len(rows), "near": 0, "cards": [], "flat": True}

    shown = _shown_names(rows)
    # Выборка, где у всех всё по одной -- это командирская выборка, и
    # разговор о копиях в ней бессмысленный. Говорим это прямо, а не
    # показываем таблицу нулей.
    flat = all(qty <= 1 for row in close for qty in row["main"].values())

    out = []
    for key, qty in mine.items():
        counts = [row["main"][key] for row in close if key in row["main"]]
        if len(counts) < max(1, min_decks):
            continue
        usual = _median(counts)
        if usual == qty:
            continue
        out.append({
            "name": shown.get(key, key),
            "mine": qty,
            "usual": usual,
            "decks": len(counts),
            "of": len(close),
            "diff": usual - qty,
        })
    out.sort(key=lambda r: (-abs(r["diff"]), -r["decks"]))
    return {
        "decks": len(rows),
        "near": len(close),
        "fallback": fallback,
        "flat": flat,
        "cards": out[:max(1, limit)],
    }


def neighbours(
    deck_names: Iterable[str],
    sample: dict[str, Any],
    near: int = NEAR_DECKS,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Сами колоды, на которых стоят числа, -- с именами и ссылками.

    Проценты без этого списка нечем проверить: «71% соседей» звучит
    одинаково и когда соседи настоящие, и когда это первые попавшиеся
    колоды формата. Ссылка ведёт на Archidekt, где список видно целиком.
    """
    rows = sample_rows(sample)
    mine = _keys(deck_names)
    if not rows:
        return []
    close, _fallback = _rows_near(mine, rows, near)
    out = []
    for row in close[:max(1, limit)]:
        meta = row.get("meta") or {}
        out.append({
            "id": row["id"],
            "name": meta.get("name") or "",
            "url": "https://archidekt.com/decks/%s" % row["id"],
            "shared": len(mine & row["keys"]),
            "cards": len(row["keys"]),
            "updated": (meta.get("updated") or "")[:10],
        })
    return out


def sideboard(
    main_names: Iterable[str],
    side_names: Iterable[str],
    sample: dict[str, Any],
    near: int = NEAR_DECKS,
    limit: int = 30,
    min_share: float = 0.2,
) -> dict[str, Any]:
    """Что соседи держат в сайде -- и чего из этого нет у вас.

    Сайдборд до сих пор не участвовал ни в чём: ни в подсказках, ни в
    «чего не хватает», ни в покупках. А это пятнадцать карт из семидесяти
    пяти, и в турнирной колоде они решают половину матчей.

    Считается по тем соседям, у кого сайд вообще известен: в старых
    выборках его не скачивали, и делать вид, что у колоды пустой сайд,
    нельзя -- это разные вещи.
    """
    rows = sample_rows(sample)
    mine = _keys(main_names)
    yours = _keys(side_names)
    if not rows:
        return {"decks": 0, "near": 0, "known": 0, "cards": [], "yours": len(yours)}

    close, fallback = _rows_near(mine, rows, near)
    withside = [row for row in close if row["side"]]
    if not withside:
        return {"decks": len(rows), "near": len(close), "known": 0,
                "cards": [], "yours": len(yours), "fallback": fallback}

    count: dict[str, int] = {}
    qty: dict[str, list[int]] = {}
    for row in withside:
        for key, number in row["side"].items():
            count[key] = count.get(key, 0) + 1
            qty.setdefault(key, []).append(number)

    # Имя для показа берём и из мейнов, и из сайдов: карта, которая у
    # соседей в сайде, у кого-то стоит в мейне, и наоборот.
    shown = dict(_shown_names(rows))
    shown.update(_shown_names(rows, "side"))
    out = []
    for key, decks in count.items():
        share = decks / len(withside)
        if share < min_share:
            continue
        out.append({
            "name": shown.get(key, key),
            "decks": decks,
            "of": len(withside),
            "share": round(share, 4),
            "usual": _median(qty.get(key) or []),
            "mine": key in yours,
            # Карта из чужого сайда может стоять у вас в мейне -- это не
            # «у вас её нет», и путать эти два случая нельзя.
            "in_main": key in mine,
        })
    out.sort(key=lambda r: (r["mine"], -r["share"]))
    return {
        "decks": len(rows),
        "near": len(close),
        "known": len(withside),
        "yours": len(yours),
        "fallback": fallback,
        "cards": out[:max(1, limit)],
    }


def as_sections(result: dict[str, Any], db: CardDB) -> list[dict[str, Any]]:
    """Shape the rows the way the suggestion panel already renders them.

    `decks`/`pool`/`share` are the fields every suggestion row uses, so the
    neighbourhood numbers slot into the existing renderer, and `lift` rides
    along beside them for the column that is new here.
    """
    cards = []
    for row in result.get("cards", []):
        card = db.by_name(row["name"])
        cards.append(dict(
            row,
            name=(card or {}).get("name") or row["name"],
            decks=row["near_decks"],
            pool=row["near_of"],
            share=row["near_share"],
            synergy=None,
        ))
    return [{
        "tag": "cooccur",
        "title": "У похожих колод есть, у вас нет",
        "cards": cards,
    }]


__all__ = ["MIN_FOR_COPIES", "MIN_OVERLAP", "NEAR_DECKS", "UBIQUITOUS",
           "as_sections", "copies", "neighbourhood", "neighbours", "pairs_for",
           "sample_decks", "sample_rows", "sideboard", "suggest"]

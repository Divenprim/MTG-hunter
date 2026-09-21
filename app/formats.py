"""Подходит ли колода под формат -- и что сделать, чтобы подошла.

Колода живёт дольше одного формата. Собранная под модерн, она почти целиком
проходит в легаси и почти наверняка не проходит в пионер -- но «не проходит»
обычно значит три карты, а не сорок. Поэтому ответ здесь не «да/нет», а разбор:
сколько копий вне пула, что именно забанено, какие правила формата нарушены и
чем эти карты заменить, не меняя колоду по смыслу.

Наружу ничего не спрашивается. Легальность лежит в базе Scryfall, которую
программа и так собирает, а замены ищутся по функциональным тегам того же
Scryfall Tagger: «чем заменить Lightning Bolt» -- это не «что похоже по
тексту», а «что ещё делает то же самое и стоит в пуле нужного формата».

Чего здесь нет: метагейма. Программа не знает, что играют на турнирах, и не
притворяется, что знает. Замена предлагается по назначению карты и по тому,
насколько карта на слуху (сколько раз её переиздавали), -- этого хватает, чтобы
не собирать колоду с нуля, и не хватает, чтобы называть это деклистом.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

# Форматы, про которые имеет смысл спрашивать: бумажные, с разным пулом карт.
# Порядок -- от узкого пула к широкому, как их обычно и сравнивают.
FORMATS: list[tuple[str, str, int]] = [
    ("standard", "Стандарт", 60),
    ("pioneer", "Пионер", 60),
    ("modern", "Модерн", 60),
    ("legacy", "Легаси", 60),
    ("vintage", "Винтаж", 60),
    ("pauper", "Паупер", 60),
    ("commander", "Командир", 100),
]
FORMAT_TITLES = {slug: title for slug, title, _size in FORMATS}
FORMAT_SIZE = {slug: size for slug, _title, size in FORMATS}
SINGLETON_FORMATS = {"commander", "brawl", "oathbreaker"}
BASIC_LANDS = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest",
}
# Карты, которых можно любое количество: так написано на них самих.
ANY_NUMBER = re.compile(
    r"a deck can have any number of cards named|"
    r"колода может содержать любое количество карт с именем", re.IGNORECASE)


def _is_basic(card: dict[str, Any] | None, name: str) -> bool:
    if (name or "").strip().lower() in BASIC_LANDS:
        return True
    type_line = ((card or {}).get("type_line") or "").lower()
    return "basic" in type_line and "land" in type_line


def _any_number(card: dict[str, Any] | None) -> bool:
    return bool(ANY_NUMBER.search(((card or {}).get("oracle_text") or "")))


def _legality(card: dict[str, Any] | None, fmt: str) -> str:
    legal = (card or {}).get("legalities") or {}
    if isinstance(legal, str):
        try:
            legal = json.loads(legal)
        except ValueError:
            legal = {}
    return legal.get(fmt) or "not_legal"


# --------------------------------------------------------------------------- #
# Проверка колоды против одного формата
# --------------------------------------------------------------------------- #

def check(deck: dict[str, Any], fmt: str) -> dict[str, Any]:
    """Разбор колоды по одному формату.

    Возвращает не приговор, а три разные вещи, потому что чинятся они
    по-разному: blockers -- карты вне пула, их надо менять; rules -- форма
    колоды (число карт, копии, командир), это правится без похода в магазин;
    и счёт копий, по которому видно, насколько всё близко.
    """
    size = FORMAT_SIZE.get(fmt, 60)
    singleton = fmt in SINGLETON_FORMATS

    rows = deck.get("cards") or []
    main = [r for r in rows if r.get("section") == "main"]
    side = [r for r in rows if r.get("section") == "side"]
    commanders = [r for r in rows if r.get("section") == "commander"]
    playable = main + commanders

    blockers: list[dict[str, Any]] = []
    rules: list[dict[str, str]] = []
    copies = 0
    legal_copies = 0

    for row in playable + side:
        card = row.get("card")
        qty = int(row.get("quantity") or 0)
        copies += qty
        if not card:
            blockers.append({
                "name": row.get("name"),
                "quantity": qty,
                "why": "unknown",
                "text": "такой карты нет в базе — проверьте написание",
            })
            continue
        status = _legality(card, fmt)
        if status == "legal":
            legal_copies += qty
        elif status == "restricted":
            legal_copies += qty
            if qty > 1:
                blockers.append({
                    "name": row.get("name"), "quantity": qty, "why": "restricted",
                    "text": "ограничена: в колоде можно только одну",
                    "card": card,
                })
        else:
            blockers.append({
                "name": row.get("name"),
                "quantity": qty,
                "why": "banned" if status == "banned" else "not_legal",
                "text": ("забанена в формате" if status == "banned"
                         else "не входит в пул формата"),
                "card": card,
            })

    # --- форма колоды ------------------------------------------------------ #
    playable_copies = sum(int(r.get("quantity") or 0) for r in playable)
    if singleton:
        if playable_copies != size:
            rules.append({
                "kind": "size",
                "text": "карт в колоде %d, нужно ровно %d" % (playable_copies, size),
            })
        if not commanders:
            rules.append({"kind": "commander", "text": "не выбран командир"})
    else:
        if playable_copies < size:
            rules.append({
                "kind": "size",
                "text": "карт в колоде %d, минимум %d" % (playable_copies, size),
            })
        if sum(int(r.get("quantity") or 0) for r in side) > 15:
            rules.append({"kind": "side", "text": "в сайдборде больше 15 карт"})
        if commanders:
            rules.append({
                "kind": "commander",
                "text": "командир назначен, а в этом формате его не бывает — "
                        "карта пойдёт в основную колоду",
            })

    seen: dict[str, int] = {}
    for row in playable:
        card = row.get("card")
        name = row.get("name") or ""
        if _is_basic(card, name) or _any_number(card):
            continue
        key = (card or {}).get("name") or name
        seen[key] = seen.get(key, 0) + int(row.get("quantity") or 0)
    limit = 1 if singleton else 4
    for name, count in sorted(seen.items()):
        if count > limit:
            rules.append({
                "kind": "copies",
                "text": "«%s» — %d копий, разрешено %d" % (name, count, limit),
            })

    # --- цветовая идентичность командира ----------------------------------- #
    if singleton and commanders:
        identity: set[str] = set()
        for row in commanders:
            identity.update(((row.get("card") or {}).get("color_identity") or ""))
        for row in main:
            card = row.get("card")
            if not card:
                continue
            extra = set(card.get("color_identity") or "") - identity
            if extra:
                blockers.append({
                    "name": row.get("name"),
                    "quantity": int(row.get("quantity") or 0),
                    "why": "identity",
                    "text": "вне цветовой идентичности командира (лишнее: %s)"
                            % "".join(sorted(extra)),
                    "card": card,
                })

    pool_ok = not blockers
    verdict = "fits" if pool_ok and not rules else ("shape" if pool_ok else "no")
    return {
        "format": fmt,
        "title": FORMAT_TITLES.get(fmt, fmt),
        "verdict": verdict,
        "blockers": blockers,
        "blocked_copies": sum(b["quantity"] for b in blockers),
        "rules": rules,
        "copies": copies,
        "legal_copies": legal_copies,
        "share": round(legal_copies / copies, 3) if copies else 0.0,
    }


def survey(deck: dict[str, Any]) -> dict[str, Any]:
    """Все форматы разом: где колода играет как есть, а где почти.

    Отсортировано по близости, а не по алфавиту: сверху то, чем можно сесть
    играть, следом то, где мешают две карты, и только потом безнадёжное.
    """
    reports = [check(deck, slug) for slug, _t, _s in FORMATS]
    order = {"fits": 0, "shape": 1, "no": 2}
    reports.sort(key=lambda r: (order[r["verdict"]], r["blocked_copies"],
                                len(r["rules"]), r["format"]))
    return {
        "declared": (deck.get("format") or "").lower(),
        "formats": reports,
        "playable": [r["format"] for r in reports if r["verdict"] == "fits"],
        "nearly": [r["format"] for r in reports
                   if r["verdict"] != "fits" and r["blocked_copies"] <= 4],
    }


# --------------------------------------------------------------------------- #
# Чем заменить карту, которая не проходит
# --------------------------------------------------------------------------- #

# Теги, которые ничего не говорят о назначении карты: либо про оформление
# («аллитерация», «имя из одного слова»), либо про строение правил
# («активируемая способность»). И того и другого — тысячи карт.
NOISE_TAGS = ("cycle", "french-vanilla", "vanilla", "reprint", "art-",
              "signpost", "flavor", "typal-", "gold-", "hybrid-",
              "single-english-word-name", "alliteration", "unique-type-line",
              "intervening-if-clause", "activated-ability", "triggered-ability")
# Тег, под который попадает каждая шестая карта, тоже ничего не выделяет.
# Порог для замен мягче: «точечное удаление» — общий тег, но заменять по нему
# осмысленно. Для тематики он строже: тема должна выделять колоду.
GENERIC_TAG_CARDS = 6000
THEME_TAG_CARDS = 4000

# Во что превращается каждая часть сходства. Теги -- главное: они и есть «что
# карта делает». Остальное отсеивает несуразицу вроде замены однокруговой карты
# семикруговой.
W_TAGS = 6.0
W_TYPE = 2.0
W_CMC = 2.0
W_COLOR = 2.0
W_FAME = 1.0


def _tags_of(conn: sqlite3.Connection, oracle_id: str,
             max_cards: int = GENERIC_TAG_CARDS) -> list[str]:
    """Функциональные теги карты -- без тех, что есть у всего подряд."""
    if not oracle_id:
        return []
    rows = conn.execute(
        "SELECT t.slug AS slug FROM card_tags t "
        "LEFT JOIN tags g ON g.slug = t.slug "
        "WHERE t.oracle_id = ? AND COALESCE(g.card_count, 0) <= ?",
        (oracle_id, max_cards),
    ).fetchall()
    return [r["slug"] for r in rows
            if not any(v in (r["slug"] or "") for v in NOISE_TAGS)]


def _primary_type(type_line: str) -> str:
    line = (type_line or "").split("//")[0].lower()
    for kind in ("land", "creature", "planeswalker", "battle", "artifact",
                 "enchantment", "instant", "sorcery"):
        if kind in line:
            return kind
    return ""


def _deck_palette(deck: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    """Цвета колоды и её состав по именам -- рамка для любого предложения."""
    palette: set[str] = set()
    names: set[str] = set()
    for row in (deck or {}).get("cards") or []:
        card = row.get("card") or {}
        # И как записано в колоде, и как карта называется на самом деле: иначе
        # «Search for Azcanta» предлагается колоде, в которой она уже стоит.
        names.add((row.get("name") or "").lower())
        if card.get("name"):
            names.add(card["name"].lower())
        if row.get("section") in ("main", "commander"):
            palette.update(card.get("color_identity") or "")
    return palette, names


def _brief(cand: dict[str, Any], **extra: Any) -> dict[str, Any]:
    out = {
        "name": cand.get("name"),
        "ru_name": cand.get("ru_name"),
        "type_line": cand.get("type_line"),
        "mana_cost": cand.get("mana_cost"),
        "cmc": cand.get("cmc"),
        "rarity": cand.get("rarity"),
        "image_small": cand.get("image_small"),
        "image_normal": cand.get("image_normal"),
        "prices": cand.get("prices"),
    }
    out.update(extra)
    return out


def _fame(conn: sqlite3.Connection, ids: list[str]) -> dict[str, int]:
    """Сколько раз карту переиздавали. Грубый, но честный признак известности:
    метагейма программа не знает и знать не делает вид."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {
        r["oracle_id"]: r["n"] for r in conn.execute(
            "SELECT oracle_id, COUNT(*) AS n FROM cards "
            "WHERE oracle_id IN (%s) GROUP BY oracle_id" % marks, ids)
    }


def replacements(db: Any, name: str, fmt: str, deck: dict[str, Any] | None = None,
                 limit: int = 6) -> dict[str, Any]:
    """Чем заменить эту карту в этом формате.

    Ищем по функциональным тегам: у Lightning Bolt это «direct damage» и
    «burn», и под них в пионере попадают карты, которые в колоде займут то же
    место. Дальше сходство уточняется типом, маной и цветом, а порядок среди
    равных решает известность карты.
    """
    card = db.by_name(name)
    if not card:
        return {"name": name, "format": fmt, "cards": [],
                "note": "такой карты нет в базе"}

    conn = db.conn
    tags = _tags_of(conn, card.get("oracle_id") or "")
    if not tags:
        return {"name": card.get("name"), "format": fmt, "cards": [], "tags": [],
                "note": "у карты нет функциональных тегов — заменять не по чему"}

    want_type = _primary_type(card.get("type_line") or "")
    want_cmc = float(card.get("cmc") or 0)
    want_colors = set(card.get("colors") or "")

    palette, in_deck = _deck_palette(deck)
    if not palette:
        palette = set(card.get("color_identity") or "")

    marks = ",".join("?" * len(tags))
    rows = conn.execute(
        "SELECT c.oracle_id AS oracle_id, COUNT(*) AS hits "
        "FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id "
        "WHERE t.slug IN (%s) AND c.representative = 1 "
        "  AND c.oracle_id != ? "
        "  AND json_extract(c.legalities, '$.' || ?) = 'legal' "
        "GROUP BY c.oracle_id ORDER BY hits DESC LIMIT 300" % marks,
        tags + [card.get("oracle_id") or "", fmt],
    ).fetchall()
    if not rows:
        return {"name": card.get("name"), "format": fmt, "cards": [], "tags": tags[:8],
                "note": "в пуле формата нет карт с тем же назначением"}

    hits = {r["oracle_id"]: r["hits"] for r in rows}
    ids = list(hits)
    marks = ",".join("?" * len(ids))
    fame = _fame(conn, ids)

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in conn.execute(
            "SELECT * FROM cards WHERE representative = 1 "
            "AND oracle_id IN (%s)" % marks, ids):
        cand = db.card_dict(row)
        if (cand.get("name") or "").lower() in in_deck:
            continue
        identity = set(cand.get("color_identity") or "")
        if palette and identity - palette:
            continue

        shared = hits.get(cand["oracle_id"], 0)
        score = W_TAGS * (shared / max(1, len(tags)))
        if _primary_type(cand.get("type_line") or "") == want_type:
            score += W_TYPE
        gap = abs(float(cand.get("cmc") or 0) - want_cmc)
        score += W_CMC * max(0.0, 1.0 - gap / 3.0)
        colors = set(cand.get("colors") or "")
        if colors == want_colors:
            score += W_COLOR
        elif colors and want_colors and colors <= want_colors:
            score += W_COLOR / 2
        printings = fame.get(cand["oracle_id"], 1)
        score += W_FAME * min(1.0, printings / 12.0)

        scored.append((score, _brief(cand, shared_tags=shared,
                                     printings=printings, score=round(score, 2))))

    scored.sort(key=lambda p: (-p[0], p[1]["name"] or ""))
    return {
        "name": card.get("name"),
        "format": fmt,
        "title": FORMAT_TITLES.get(fmt, fmt),
        "tags": tags[:8],
        "cards": [c for _s, c in scored[:limit]],
    }


# --------------------------------------------------------------------------- #
# Тематика колоды и что к ней добавить
# --------------------------------------------------------------------------- #

def theme(db: Any, deck: dict[str, Any], fmt: str | None = None,
          limit: int = 10) -> dict[str, Any]:
    """О чём эта колода и чего в ней не хватает.

    Тема -- это то, что повторяется: не «зелёная колода», а «двенадцать карт
    разгона маны и семь способов добрать карту». Считается по тем же
    функциональным тегам, и по ним же подбирается, что добавить: карты того же
    назначения, легальные в формате, в цвете колоды и ещё не в ней.
    """
    conn = db.conn
    fmt = (fmt or deck.get("format") or "commander").lower()

    counts: dict[str, int] = {}
    palette, in_deck = _deck_palette(deck)
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander"):
            continue
        card = row.get("card") or {}
        qty = int(row.get("quantity") or 0)
        for slug in _tags_of(conn, card.get("oracle_id") or "", THEME_TAG_CARDS):
            counts[slug] = counts.get(slug, 0) + qty

    top = sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:8]
    labels: dict[str, str] = {}
    if top:
        marks = ",".join("?" * len(top))
        for r in conn.execute(
                "SELECT slug, label FROM tags WHERE slug IN (%s)" % marks,
                [s for s, _n in top]):
            labels[r["slug"]] = r["label"]
    themes = [{"slug": slug, "label": labels.get(slug, slug), "cards": n}
              for slug, n in top]

    # Что добавить: карты двух-трёх главных тем -- то, чем колода и занимается.
    picks: list[dict[str, Any]] = []
    lead = [slug for slug, _n in top[:3]]
    if lead:
        marks = ",".join("?" * len(lead))
        rows = conn.execute(
            "SELECT c.oracle_id AS oracle_id, COUNT(*) AS hits "
            "FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id "
            "WHERE t.slug IN (%s) AND c.representative = 1 "
            "  AND json_extract(c.legalities, '$.' || ?) = 'legal' "
            "GROUP BY c.oracle_id ORDER BY hits DESC LIMIT 400" % marks,
            lead + [fmt],
        ).fetchall()
        hits = {r["oracle_id"]: r["hits"] for r in rows}
        ids = list(hits)
        if ids:
            marks = ",".join("?" * len(ids))
            fame = _fame(conn, ids)
            scored: list[tuple[float, dict[str, Any]]] = []
            for row in conn.execute(
                    "SELECT * FROM cards WHERE representative = 1 "
                    "AND oracle_id IN (%s)" % marks, ids):
                cand = db.card_dict(row)
                if (cand.get("name") or "").lower() in in_deck:
                    continue
                identity = set(cand.get("color_identity") or "")
                if palette and identity - palette:
                    continue
                printings = fame.get(cand["oracle_id"], 1)
                score = hits.get(cand["oracle_id"], 0) + min(1.0, printings / 12.0)
                scored.append((score, _brief(cand, shared_tags=hits.get(
                    cand["oracle_id"], 0), printings=printings)))
            scored.sort(key=lambda p: (-p[0], p[1]["name"] or ""))
            picks = [c for _s, c in scored[:limit]]

    return {
        "format": fmt,
        "title": FORMAT_TITLES.get(fmt, fmt),
        "themes": themes,
        "add": picks,
    }


__all__ = ["FORMATS", "FORMAT_TITLES", "check", "replacements", "survey", "theme"]

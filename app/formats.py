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
import math
import re
import sqlite3
import threading
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


def legality(card: dict[str, Any] | None, fmt: str) -> str:
    """Легальность одной карты в формате: legal / banned / restricted / not_legal.

    Публичный вход: то же самое спрашивает подборщик комбо, и незачем ему
    разбирать JSON легальностей заново.
    """
    return _legality(card, (fmt or "").lower())


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
NOISE_TAGS = ("french-vanilla", "vanilla", "reprint", "art-",
              "signpost", "typal-", "gold-", "hybrid-",
              "single-english-word-name", "alliteration", "unique-type-line",
              "intervening-if-clause", "activated-ability", "triggered-ability")

# У тегов Scryfall есть дерево, и целые его ветки к назначению карты отношения
# не имеют: «имя из трёх букв» — это ветка card-names, «цикл редких земель» —
# ветка cycle. Отсекать их по подстроке в слаге бессмысленно (под «cycle»
# попадёт и «recycle»), а по корню дерева — надёжно.
COSMETIC_ROOTS = {
    "card-names", "cycle", "draft-signpost", "un-design", "meme",
    "type-errata", "flavors-of-vanilla", "vanilla", "digital-only-mechanics",
    "art", "flavor", "securities-fraud",
}

# Тег, под который попадает каждая шестая карта, тоже ничего не выделяет.
# Порог для замен мягче: «точечное удаление» — общий тег, но заменять по нему
# осмысленно. Для тематики он строже: тема должна выделять колоду.
GENERIC_TAG_CARDS = 6000
THEME_TAG_CARDS = 4000
# Чем вообще выигрывают. Тегов победы в таксономии Scryfall ровно два рода:
# карта, которая прямо говорит «вы выигрываете» (84 карты во всей Magic), и
# карты, которые мелют библиотеку соперника. Всё остальное -- бой и урон, и
# отдельного тега у них нет: это видно по самой колоде.
WIN_TAGS = ("alternate-win-condition",)
MILL_TAGS = ("mill-opponent", "mill-each")
# Сколько копий тега должно быть в колоде, чтобы считать его её темой: одна
# карта с тегом -- случайность, три -- замысел.
THEME_REPEATS = 3

# Тег, который стоит на каждой сороковой карте, в счёте участвует (с малым
# весом), но называть его назначением карты не стоит: «заклинание в одну цель»
# в строке «не делает» -- шум, из-за которого не видно строчки про кладбище.
DEFINING_TAG_CARDS = 2000

# Во что превращается каждая часть сходства.
#
# Теги -- это и есть «что карта делает», поэтому они весят больше всего
# остального вместе взятого. Так было не всегда: пока тег весил шесть, а тип,
# мана и цвет -- по два, «Isochron Scepter» в пионере заменялся на случайный
# двухманный артефакт, потому что совпадение по редкому тегу imprint ценилось
# ровно так же, как совпадение по тегу, который есть у четырёхсот карт. Теперь
# редкий тег весит больше частого (см. _tag_weight), а сходство считается как
# доля назначения карты, которую замена покрывает.
W_TAGS = 20.0
W_TYPE = 2.0
W_CMC = 2.0
W_COLOR = 2.0
W_FAME = 0.5


_TREE: dict[str, Any] | None = None
_TREE_LOCK = threading.Lock()


def _tree(conn: sqlite3.Connection) -> dict[str, Any]:
    """Дерево тегов целиком: родители, сколько карт, как называется.

    Четыре с половиной тысячи строк, которые после сборки базы не меняются, --
    читаются один раз на весь запуск. Без этого каждый подбор замены упирался
    бы в десяток мелких запросов на карту.
    """
    global _TREE
    with _TREE_LOCK:
        if _TREE is None:
            parents: dict[str, list[str]] = {}
            count: dict[str, int] = {}
            label: dict[str, str] = {}
            note: dict[str, str] = {}
            for r in conn.execute(
                    "SELECT slug, parents, card_count, label, description FROM tags"):
                parents[r["slug"]] = [
                    x for x in (r["parents"] or "").split(",") if x]
                count[r["slug"]] = int(r["card_count"] or 0)
                label[r["slug"]] = r["label"] or r["slug"]
                note[r["slug"]] = r["description"] or ""
            total = conn.execute(
                "SELECT COUNT(DISTINCT oracle_id) AS n FROM card_tags"
            ).fetchone()["n"] or 1
            _TREE = {"parents": parents, "count": count, "label": label,
                     "note": note, "total": int(total)}
        return _TREE


def _roots(tree: dict[str, Any], slug: str,
           seen: set[str] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if slug in seen:
        return set()
    seen.add(slug)
    parents = tree["parents"].get(slug) or []
    if not parents:
        return {slug}
    out: set[str] = set()
    for parent in parents:
        out |= _roots(tree, parent, seen)
    return out or {slug}


def _is_functional(tree: dict[str, Any], slug: str, max_cards: int) -> bool:
    if tree["count"].get(slug, 0) > max_cards:
        return False
    if any(v in (slug or "") for v in NOISE_TAGS):
        return False
    return not (_roots(tree, slug) & COSMETIC_ROOTS)


def _tag_weight(tree: dict[str, Any], slug: str) -> float:
    """Чем реже тег, тем больше он говорит о карте.

    imprint стоит на 96 картах, а «заклинание в одну цель» -- на четырёх с
    половиной тысячах. Пока оба весили одинаково, вторая карта выигрывала
    просто потому, что таких много.
    """
    count = max(1, tree["count"].get(slug, 1))
    return max(0.4, math.log(tree["total"] / count))


def _tags_of(conn: sqlite3.Connection, oracle_id: str,
             max_cards: int = GENERIC_TAG_CARDS) -> list[str]:
    """Функциональные теги карты -- без тех, что есть у всего подряд."""
    if not oracle_id:
        return []
    tree = _tree(conn)
    rows = conn.execute(
        "SELECT slug FROM card_tags WHERE oracle_id = ?", (oracle_id,)).fetchall()
    slugs = [r["slug"] for r in rows if _is_functional(tree, r["slug"], max_cards)]
    return sorted(slugs, key=lambda s: (-_tag_weight(tree, s), s))


def _job(tree: dict[str, Any], slug: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "label": tree["label"].get(slug, slug),
        "note": tree["note"].get(slug, ""),
        "weight": round(_tag_weight(tree, slug), 2),
        "cards": tree["count"].get(slug, 0),
    }


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
        # Нужен тем, кто потом спрашивает у карты её теги: без него замена
        # выглядит картой без единого свойства, и «что она роняет» отвечает
        # «всё сразу».
        "oracle_id": cand.get("oracle_id"),
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


def _covered(conn: sqlite3.Connection, oracle_ids: list[str],
             tags: list[str]) -> dict[str, set[str]]:
    """Какие из нужных тегов есть у каждого кандидата."""
    if not oracle_ids or not tags:
        return {}
    marks = ",".join("?" * len(oracle_ids))
    slots = ",".join("?" * len(tags))
    out: dict[str, set[str]] = {}
    for row in conn.execute(
            "SELECT oracle_id, slug FROM card_tags "
            "WHERE oracle_id IN (%s) AND slug IN (%s)" % (marks, slots),
            oracle_ids + tags):
        out.setdefault(row["oracle_id"], set()).add(row["slug"])
    return out


def _pool_size(conn: sqlite3.Connection, slug: str, fmt: str) -> int:
    """Сколько карт с таким назначением вообще есть в пуле формата.

    Нужно, чтобы отвечать на «не верю, что в пионере нет ни одной карты с
    imprint»: либо их сорок пять, и тогда замена обязана быть одной из них,
    либо их правда нет, и это надо сказать прямо.
    """
    return conn.execute(
        "SELECT COUNT(DISTINCT c.oracle_id) AS n FROM card_tags t "
        "JOIN cards c ON c.oracle_id = t.oracle_id "
        "WHERE t.slug = ? AND c.representative = 1 "
        "  AND json_extract(c.legalities, '$.' || ?) = 'legal'",
        (slug, fmt)).fetchone()["n"]


def replacements(db: Any, name: str, fmt: str, deck: dict[str, Any] | None = None,
                 limit: int = 6, require: list[str] | None = None) -> dict[str, Any]:
    """Чем заменить эту карту в этом формате.

    Карта -- это набор дел, которые она делает, и замена тем лучше, чем
    большую часть этих дел она берёт на себя. Дела берутся из функциональных
    тегов Scryfall, и считаются они не поштучно, а по весу: редкий тег
    (imprint -- 96 карт) весит вчетверо больше частого («заклинание в одну
    цель» -- 4677 карт). Поэтому Isochron Scepter в пионере меняется на Elite
    Arcanist, а не на первый попавшийся двухманный артефакт, который случайно
    совпал по трём общим тегам.

    Что карта делает не одно дело, а два-три, -- обычное дело, и заменить их
    все удаётся не всегда. Поэтому у каждого предложения сказано, что из
    назначения оно **не** покрывает: «Blessed Respite» -- это туман И возврат
    кладбища в библиотеку, и если замена только туман, это должно быть видно,
    а не замалчиваться.

    require -- назначения, без которых предложение не годится. Шесть лучших по
    общему счёту это одно, а «покажи только те, что умеют imprint» -- другое:
    когда человек уже понял, ради чего карта стоит в колоде, выбирать ему, а не
    счёту. Порядок внутри отобранных прежний.

    Чего здесь по-прежнему нет: метагейма. Порядок среди равных решает
    известность карты (сколько раз её переиздавали), и это честнее, чем
    притворяться, будто программа знает турнирные списки.
    """
    card = db.by_name(name)
    if not card:
        return {"name": name, "format": fmt, "cards": [], "jobs": [],
                "note": "такой карты нет в базе"}

    conn = db.conn
    tree = _tree(conn)
    tags = _tags_of(conn, card.get("oracle_id") or "")
    if not tags:
        return {"name": card.get("name"), "format": fmt, "cards": [], "tags": [],
                "jobs": [],
                "note": "у карты нет функциональных тегов — заменять не по чему"}

    weights = {slug: _tag_weight(tree, slug) for slug in tags}
    total_weight = sum(weights.values()) or 1.0
    # Требовать можно только то, что карта и правда делает: кнопки в панели --
    # это её же назначения.
    needed = [slug for slug in (require or []) if slug in weights]

    want_type = _primary_type(card.get("type_line") or "")
    want_cmc = float(card.get("cmc") or 0)
    want_colors = set(card.get("colors") or "")

    palette, in_deck = _deck_palette(deck)
    if not palette:
        palette = set(card.get("color_identity") or "")

    # Кандидаты отбираются по сумме весов общих тегов, а не по их количеству:
    # иначе три общих тега «ни о чём» вытесняют из отбора единственную карту,
    # которая делает то же самое.
    values = ",".join("(?,?)" for _ in tags)
    params: list[Any] = []
    for slug in tags:
        params += [slug, weights[slug]]
    params += [card.get("oracle_id") or "", fmt]
    # Отбор требуемых назначений делает сама база: иначе при «только imprint»
    # три сотни кандидатов -- это три сотни карт без imprint, из которых
    # останется пусто.
    having = ""
    if needed:
        having = (" HAVING COUNT(DISTINCT CASE WHEN want.slug IN (%s) "
                  "THEN want.slug END) = %d"
                  % (",".join("?" * len(needed)), len(needed)))
        params += needed
    rows = conn.execute(
        "WITH want(slug, weight) AS (VALUES %s) "
        "SELECT c.oracle_id AS oracle_id, SUM(want.weight) AS hit "
        "FROM card_tags t JOIN want ON want.slug = t.slug "
        "JOIN cards c ON c.oracle_id = t.oracle_id "
        "WHERE c.representative = 1 AND c.oracle_id != ? "
        "  AND json_extract(c.legalities, '$.' || ?) = 'legal' "
        "GROUP BY c.oracle_id%s ORDER BY hit DESC LIMIT 400" % (values, having),
        params,
    ).fetchall()

    jobs = [dict(_job(tree, slug), in_pool=_pool_size(conn, slug, fmt),
                 defining=tree["count"].get(slug, 0) <= DEFINING_TAG_CARDS)
            for slug in tags]
    missing_pool = [j for j in jobs if not j["in_pool"]]

    if not rows:
        return {"name": card.get("name"), "format": fmt, "cards": [],
                "tags": tags[:8], "jobs": jobs, "require": needed, "total": 0,
                "note": ("в пуле формата нет карт, которые делают всё выбранное"
                         if needed
                         else "в пуле формата нет карт с тем же назначением")}

    hits = {r["oracle_id"]: float(r["hit"] or 0) for r in rows}
    ids = list(hits)
    marks = ",".join("?" * len(ids))
    fame = _fame(conn, ids)
    covered = _covered(conn, ids, tags)

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

        mine = covered.get(cand["oracle_id"], set())
        coverage = hits.get(cand["oracle_id"], 0.0) / total_weight
        score = W_TAGS * coverage
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

        # В отчёт идут только определяющие теги: счёт считается по всем, но
        # читать «не делает: заклинание в одну цель» бессмысленно.
        defining = [slug for slug in tags
                    if tree["count"].get(slug, 0) <= DEFINING_TAG_CARDS]
        misses = [slug for slug in defining if slug not in mine]
        scored.append((score, _brief(
            cand,
            shared_tags=len(mine),
            covers=[_job(tree, slug) for slug in defining if slug in mine],
            misses=[_job(tree, slug) for slug in misses],
            coverage=round(coverage, 3),
            full=not misses,
            printings=printings,
            score=round(score, 2),
        )))

    scored.sort(key=lambda p: (-p[0], p[1]["name"] or ""))
    return {
        "name": card.get("name"),
        "format": fmt,
        "title": FORMAT_TITLES.get(fmt, fmt),
        "tags": tags[:8],
        "jobs": jobs,
        "missing_pool": missing_pool,
        "require": needed,
        "total": len(scored),
        # Кандидатов берём четыреста -- если упёрлись в потолок, честнее
        # сказать «больше четырёхсот», чем выдать потолок за точное число.
        "capped": len(rows) >= 400,
        "cards": [c for _s, c in scored[:max(1, limit)]],
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


# --------------------------------------------------------------------------- #
# Чем колода выигрывает
# --------------------------------------------------------------------------- #

# Способов выиграть немного, и почти все видны по самой колоде. Тегом в
# таксономии Scryfall помечен ровно один -- «карта прямо говорит, что вы
# выигрываете»; остальные считаются по картам, и каждый -- числом, а не
# признаком. Число важнее признака: «урон существами 34» и «урон существами 4»
# -- разные колоды, хотя признак у них один.
WIN_TAGS = ("alternate-win-condition",)
MILL_TAGS = ("mill-opponent", "mill-each")
BURN_TAGS = ("burn-player", "drain-life")
POISON_TAGS = ("poisonous", "poison-opponents")
# Сколько копий тега должно быть в колоде, чтобы считать его её темой: одна
# карта с тегом -- случайность, три -- замысел.
THEME_REPEATS = 3

# Главный способ выбирается не порядком в списке, а тем, насколько способ
# перерос свой минимум: одно случайное комбо в колоде, бьющей на девяносто
# семь силы, -- совпадение, а двенадцать собранных связок -- замысел. Порядок
# ниже решает только ничьи.
ROUTE_ORDER = ("alt", "combo", "mill", "poison", "burn", "combat")
# Название способа и то, в чём он меряется -- тремя формами, чтобы «4 копии»
# и «5 копий» писались по-русски, а не одинаково.
ROUTE_WORDS = {
    "alt": ("карта-победитель", ("копия", "копии", "копий")),
    "combo": ("комбо", ("связка", "связки", "связок")),
    "mill": ("перемалывание библиотеки", ("копия", "копии", "копий")),
    "poison": ("яд", ("копия", "копии", "копий")),
    "burn": ("урон заклинаниями", ("копия", "копии", "копий")),
    "combat": ("урон существами", ("силы", "силы", "силы")),
}
# Ниже этого способ не считается способом: одна мельница и два существа
# выигрывают только у того, кто согласился ждать.
ROUTE_FLOOR = {"alt": 1, "combo": 1, "mill": 3, "poison": 3, "burn": 6,
               "combat": 8}


def _plural(n: int, one: str, few: str, many: str) -> str:
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _deck_tag_counts(conn: sqlite3.Connection,
                     deck: dict[str, Any]) -> dict[str, int]:
    """Сколько копий в колоде несут каждый тег.

    Это и есть «о чём колода»: тег, встречающийся в двенадцати копиях, -- её
    тема, а встречающийся в одной -- свойство одной карты. Разница важна при
    переделке: замена, теряющая тему, ломает колоду, а замена, теряющая
    случайное свойство, -- нет.
    """
    counts: dict[str, int] = {}
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander", "side"):
            continue
        card = row.get("card") or {}
        qty = int(row.get("quantity") or 0)
        for slug in _tags_of(conn, card.get("oracle_id") or ""):
            counts[slug] = counts.get(slug, 0) + qty
    return counts


def _card_of(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Карта строки колоды -- со всем, что нужно для счёта.

    В колоде хранится то, что когда-то ввели, и часть полей (сила, ключевые
    слова) может не доехать. Тогда спрашиваем базу: считать существо
    неатакующим потому, что поле пустое, нечестно.
    """
    card = row.get("card") or {}
    if card.get("power") is None and db is not None:
        full = db.by_name(card.get("name") or row.get("name") or "")
        if full:
            return full
    return card


def _combat_power(db: Any, deck: dict[str, Any]) -> tuple[int, int]:
    """Сколько силы в колоде умеет атаковать: (сумма силы, число существ).

    Стены не в счёт: подсказка «дайте ему +X/+X» победой не станет, пока бить
    нечем. Существо с силой «*» считаем за единицу -- меньше, чем оно обычно
    стоит, зато не выдумываем.
    """
    power = 0
    bodies = 0
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander"):
            continue
        card = _card_of(db, row)
        line = (card.get("type_line") or "").split("//")[0].lower()
        if "creature" not in line:
            continue
        if "defender" in str(card.get("keywords") or "").lower():
            continue
        try:
            value = float(str(card.get("power") or "0"))
        except ValueError:
            value = 1.0
        if value <= 0:
            continue
        qty = int(row.get("quantity") or 0)
        power += int(value * qty)
        bodies += qty
    return power, bodies


def _tagged_copies(conn: sqlite3.Connection, deck: dict[str, Any],
                   tags: tuple[str, ...]) -> tuple[int, list[str]]:
    """Сколько копий в колоде несут любой из этих тегов -- и что это за карты."""
    copies = 0
    names: list[str] = []
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander"):
            continue
        card = row.get("card") or {}
        mine = set(_tags_of(conn, card.get("oracle_id") or ""))
        if mine & set(tags):
            copies += int(row.get("quantity") or 0)
            names.append(card.get("name") or row.get("name") or "")
    return copies, names


def _deck_combos(combo_db: Any, deck: dict[str, Any]) -> list[dict[str, Any]]:
    """Комбо, которые в колоде уже собраны.

    База комбо -- сто десять тысяч связок Commander Spellbook -- лежит
    локально, и не спросить её было бы странно: колода с дюжиной собранных
    связок на бесконечные срабатывания выигрывает ими, а не «боем», как
    считает подсчёт существ.
    """
    if combo_db is None:
        return []
    names = [row.get("name") or "" for row in deck.get("cards") or []
             if row.get("section") in ("main", "commander")]
    try:
        if not combo_db.ready:
            return []
        found = combo_db.for_deck(names, max_missing=0, commander_only=False)
    except Exception:  # noqa: BLE001 -- база комбо не обязана быть собрана
        return []
    return list(found.get("complete") or [])


def win_routes(db: Any, deck: dict[str, Any],
               combo_db: Any = None) -> list[dict[str, Any]]:
    """Все способы, которыми эта колода может выиграть, каждый -- числом.

    Не «есть победа / нет победы», а сколько её. Так видно и то, чем колода
    выигрывает сейчас, и то, что с этим станет после переделки: способ,
    упавший с тридцати четырёх до нуля, -- потерянный замысел, а упавший до
    двадцати одного -- та же колода, только слабее.
    """
    conn = db.conn
    routes: list[dict[str, Any]] = []

    alt_copies, alt_names = _tagged_copies(conn, deck, WIN_TAGS)
    if alt_copies:
        routes.append({"kind": "alt", "strength": alt_copies,
                       "cards": sorted(set(alt_names))})

    combos = _deck_combos(combo_db, deck)
    if combos:
        pieces: set[str] = set()
        for combo in combos[:20]:
            pieces.update(combo.get("cards") or [])
        routes.append({"kind": "combo", "strength": len(combos),
                       "cards": sorted(pieces)[:12],
                       "results": [c.get("results") for c in combos[:3]]})

    for kind, tags in (("mill", MILL_TAGS), ("poison", POISON_TAGS),
                       ("burn", BURN_TAGS)):
        copies, names = _tagged_copies(conn, deck, tags)
        if copies:
            routes.append({"kind": kind, "strength": copies,
                           "cards": sorted(set(names))[:12]})

    power, bodies = _combat_power(db, deck)
    if power:
        routes.append({"kind": "combat", "strength": power, "bodies": bodies,
                       "cards": []})

    for route in routes:
        label, forms = ROUTE_WORDS.get(route["kind"], (route["kind"], ("", "", "")))
        floor = ROUTE_FLOOR.get(route["kind"], 1)
        route["label"] = label
        route["forms"] = list(forms)
        route["unit"] = _plural(route["strength"], *forms)
        route["floor"] = floor
        route["real"] = route["strength"] >= floor
        # Во сколько раз способ перерос свой минимум -- этим и меряется, чем
        # колода занята на самом деле.
        route["score"] = round(route["strength"] / float(floor), 2)
    routes.sort(key=lambda r: (-r["score"],
                               ROUTE_ORDER.index(r["kind"])
                               if r["kind"] in ROUTE_ORDER else 99))
    return routes


def win_plan(db: Any, deck: dict[str, Any],
             combo_db: Any = None) -> dict[str, Any]:
    """Чем эта колода выигрывает: главный способ и все остальные.

    Ответ нужен не сам по себе, а для переделки под другой формат: пока
    известно, чем колода выигрывает, видно и то, переживёт ли это переделку.
    Турбофог с Maze's End выигрывает не туманами -- туманы только не дают
    проиграть, -- и потеря одной этой карты превращает колоду в ничью на
    шестьдесят карт.
    """
    routes = win_routes(db, deck, combo_db)
    real = [r for r in routes if r["real"]]
    primary = real[0] if real else None
    power, bodies = _combat_power(db, deck)

    if primary is None:
        text = "чем колода выигрывает — не видно"
        if routes:
            text += " (есть намётки: " + ", ".join(
                "%s %d" % (r["label"], r["strength"]) for r in routes[:3]) + ")"
    elif primary["kind"] == "alt":
        text = "колода выигрывает картой: " + ", ".join(primary["cards"])
    elif primary["kind"] == "combo":
        text = "колода выигрывает комбо: собранных связок %d" % primary["strength"]
    elif primary["kind"] == "combat":
        text = "колода выигрывает боем: сила атакующих %d в %d существах" % (
            primary["strength"], primary.get("bodies") or 0)
    else:
        text = "колода выигрывает: %s (%s %d)" % (
            primary["label"], primary["unit"], primary["strength"])

    return {
        "kind": primary["kind"] if primary else "none",
        "routes": routes,
        "primary": primary,
        "cards": primary["cards"] if primary and primary["kind"] == "alt" else [],
        "mill": next((r["strength"] for r in routes if r["kind"] == "mill"), 0),
        "attackers": bodies,
        "power": power,
        "text": text,
    }


def win_pool(db: Any, fmt: str, deck: dict[str, Any] | None = None,
             limit: int = 6) -> list[dict[str, Any]]:
    """Какими картами в этом формате вообще выигрывают -- в цвете колоды.

    Если таких карт нет вовсе (в паупере их ноль), это и есть ответ: колоду с
    такой победой в этом формате не собрать, и переделывать нечего.
    """
    conn = db.conn
    palette, _in_deck = _deck_palette(deck)
    marks = ",".join("?" * len(WIN_TAGS))
    rows = conn.execute(
        "SELECT DISTINCT c.* FROM card_tags t "
        "JOIN cards c ON c.oracle_id = t.oracle_id "
        "WHERE t.slug IN (%s) AND c.representative = 1 "
        "  AND json_extract(c.legalities, '$.' || ?) = 'legal'" % marks,
        list(WIN_TAGS) + [fmt]).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        cand = db.card_dict(row)
        identity = set(cand.get("color_identity") or "")
        if palette and identity - palette:
            continue
        out.append(_brief(cand))
    out.sort(key=lambda c: (c.get("name") or ""))
    return out[:limit]


def after_deck(db: Any, deck: dict[str, Any],
               plan: dict[str, Any]) -> dict[str, Any]:
    """Колода, какой она станет, если применить план.

    Считать её приходится по-настоящему: вердикт «замысел теряется» должен
    следовать из того, что от колоды осталось, а не из признака одной карты.
    Отложенное выброшено, замены поставлены, лишние копии срезаны -- и уже к
    этому задаётся тот же вопрос: чем оно выигрывает.
    """
    swapped = {(x.get("name") or "").lower(): x for x in plan.get("swaps") or []}
    shelved = {(x.get("name") or "").lower() for x in plan.get("shelve") or []}
    trims = {(t.get("name") or "").lower(): int(t.get("keep") or 1)
             for t in plan.get("trims") or []}

    rows: list[dict[str, Any]] = []
    for row in deck.get("cards") or []:
        key = (row.get("name") or "").lower()
        real = ((row.get("card") or {}).get("name") or "").lower()
        if key in shelved or real in shelved:
            continue
        qty = int(row.get("quantity") or 0)
        if key in trims or real in trims:
            qty = min(qty, trims.get(key, trims.get(real, qty)))
        swap = swapped.get(key) or swapped.get(real)
        if swap:
            name = (swap.get("to") or {}).get("name") or ""
            card = db.by_name(name) if name else None
            if not card:
                continue
            rows.append({"name": name, "quantity": qty,
                         "section": row.get("section"), "card": card})
        else:
            rows.append(dict(row, quantity=qty))
    return {"format": plan.get("format") or deck.get("format"), "cards": rows}


def _units(route: dict[str, Any], n: int) -> str:
    """«4 копии», «12 связок», «20 силы» -- по-русски, а не по-словарному."""
    forms = route.get("forms") or ROUTE_WORDS.get(
        route.get("kind"), ("", ("", "", "")))[1]
    return "%d %s" % (n, _plural(n, *forms))


def _verdict(before: list[dict[str, Any]], after: list[dict[str, Any]],
             fmt_title: str, pool: list[dict[str, Any]],
             power_after: int) -> tuple[str, str]:
    """Что стало с тем, чем колода выигрывала.

    Сравниваются не признаки, а числа, поэтому один и тот же разбор одинаково
    работает и для карты-победителя, и для комбо, и для урона существами.
    """
    was = {r["kind"]: r for r in before if r["real"]}
    now = {r["kind"]: r for r in after if r["real"]}
    if not was:
        return "unknown", ("Чем эта колода выигрывает, программа не увидела — "
                           "значит, и терять переделке нечего.")

    main = before[0] if before else {}
    lines: list[str] = []
    for kind, route in was.items():
        left = now.get(kind, {}).get("strength", 0)
        if left == 0:
            lines.append("%s — было %s, не остаётся ничего" % (
                route["label"], _units(route, route["strength"])))
        elif left < route["strength"]:
            lines.append("%s — %d → %s" % (
                route["label"], route["strength"], _units(route, left)))

    gone = [k for k in was if now.get(k, {}).get("strength", 0) == 0]
    kept = [k for k in was if now.get(k, {}).get("strength", 0) > 0]
    fresh = [k for k in now if k not in was]

    if not gone and not lines:
        return "keeps", "Замысел сохраняется: %s, и в «%s» это остаётся." % (
            main.get("label", "то, чем колода выигрывает"), fmt_title)

    said = "; ".join(lines) + "."
    if not kept and not fresh:
        text = ("Колода теряет все способы выиграть: " + said +
                " Этим форматом это уже другая колода: собрать её с нуля "
                "честнее и проще, чем переделывать эту.")
        text += ((" Выигрывают в этом формате, например, так: " +
                  ", ".join(c["name"] for c in pool[:4]) + ".") if pool else
                 " Карт, которыми можно выиграть так же, в пуле формата нет вовсе.")
        if power_after < ROUTE_FLOOR["combat"]:
            text += (" Бой тоже не выход: силы у атакующих %d — подсказки "
                     "вроде «возьмите карту, дающую +X/+X» победой не станут, "
                     "пока бить нечем." % power_after)
        return "lost", text

    if gone and not kept:
        # Старый способ не пережил переделку, но появился новый: карты, которые
        # подставились вместо выбывших, умеют что-то своё. Это честный ответ --
        # и одновременно предупреждение: колода стала другой.
        new_words = ", ".join(
            "%s %s" % (now[k]["label"], _units(now[k], now[k]["strength"]))
            for k in fresh)
        was_words = ", ".join(
            "%s %d" % (r["label"], r["strength"])
            for r in before if r["kind"] in fresh) or "ничего такого не было"
        return "changes", (
            "То, чем колода выигрывала, переделку не переживает: " + said +
            " Взамен появляется другое: " + new_words + " (было: " + was_words +
            "). Колода останется играбельной, но выигрывать будет иначе — "
            "и строить её дальше придётся вокруг этого, а не вокруг прежнего "
            "замысла.")

    if gone:
        return "changes", ("Часть того, чем колода выигрывала, не переживает "
                           "переделку: " + said + " Остаётся: " +
                           ", ".join(now[k]["label"] for k in kept) +
                           ". Проверьте, хватит ли этого.")
    return "weakens", ("Замысел остаётся, но слабеет: " + said +
                       " Это та же колода, только тише.")


# --------------------------------------------------------------------------- #
# Вариант колоды под другой формат
# --------------------------------------------------------------------------- #

def _section_of(deck: dict[str, Any], name: str) -> str:
    for row in deck.get("cards") or []:
        if (row.get("name") or "").lower() == (name or "").lower():
            return row.get("section") or "main"
    return "main"


def _copy_trims(deck: dict[str, Any], fmt: str) -> list[dict[str, Any]]:
    """Сколько копий придётся срезать: в командире всего по одной.

    Это не подбор карт, а арифметика правил, и потому делается молча: вариант
    -- отдельная колода, исходная не трогается.
    """
    limit = 1 if fmt in SINGLETON_FORMATS else 4
    counts: dict[str, dict[str, Any]] = {}
    for row in deck.get("cards") or []:
        if row.get("section") not in ("main", "commander"):
            continue
        card = row.get("card")
        name = row.get("name") or ""
        if _is_basic(card, name) or _any_number(card):
            continue
        key = (card or {}).get("name") or name
        slot = counts.setdefault(key, {"name": key, "quantity": 0})
        slot["quantity"] += int(row.get("quantity") or 0)
    return [
        {"name": v["name"], "quantity": v["quantity"], "keep": limit,
         "text": "%d копий, в формате можно %d" % (v["quantity"], limit)}
        for v in sorted(counts.values(), key=lambda x: x["name"])
        if v["quantity"] > limit
    ]


def adapt(db: Any, deck: dict[str, Any], fmt: str, limit: int = 8,
          combo_db: Any = None) -> dict[str, Any]:
    """Что сделать с колодой, чтобы она играла в этом формате.

    Ответ на «а можно то же самое, но в пионере»: колода почти всегда проходит
    процентов на девяносто, и вопрос только в том, чем заменить оставшееся.
    План состоит из трёх разных вещей, потому что и делаются они по-разному:

      swaps  -- карта вне пула, но ей есть равнозначная замена в пуле;
      trims  -- копий больше, чем разрешено: лишние просто убираются;
      shelve -- заменить нечем; карта уходит в «возможно», а не в мусор.

    Ничего не меняется: это план. Применяет его тот, кто заводит вариант.
    """
    fmt = (fmt or "").lower()
    report = check(deck, fmt)
    conn = db.conn
    # Чем колода выигрывает и что она повторяет: по этим двум вещам и видно,
    # переживёт ли замысел переделку. Без них план -- просто список подмен.
    tree = _tree(conn)
    win = win_plan(db, deck, combo_db)
    theme = _deck_tag_counts(conn, deck)
    # win["cards"] -- имена карт, которыми колода выигрывает (строки).
    win_names = {str(c).lower() for c in win.get("cards") or []}

    # Одну и ту же замену нельзя поставить дважды -- и нельзя предложить то,
    # что в колоде уже стоит.
    taken = {(row.get("name") or "").lower() for row in deck.get("cards") or []}
    for row in deck.get("cards") or []:
        real = ((row.get("card") or {}).get("name") or "").lower()
        if real:
            taken.add(real)

    swaps: list[dict[str, Any]] = []
    shelve: list[dict[str, Any]] = []

    for b in report["blockers"]:
        name = b.get("name") or ""
        base = {
            "name": name,
            "quantity": int(b.get("quantity") or 0),
            "section": _section_of(deck, name),
            "why": b.get("why"),
            "text": b.get("text"),
        }
        if b.get("why") in ("unknown", "restricted"):
            # Неизвестную карту подбирать не по чему, а ограниченная остаётся
            # в колоде -- ей хватит среза копий.
            if b.get("why") == "unknown":
                shelve.append(dict(base, note="такой карты нет в базе"))
            continue

        # Карту, которой колода выигрывает, менять на «что-то похожее» нельзя:
        # похожесть тут не поможет, нужна такая же победа. Поэтому у неё
        # замена ищется с требованием того же тега победы -- и если такой
        # карты в пуле формата нет, это не «не нашлось замены», а «в этом
        # формате так не выигрывают».
        card_tags = _tags_of(conn, (db.by_name(name) or {}).get("oracle_id") or "")
        wins_here = [t for t in card_tags if t in WIN_TAGS]
        is_win = bool(wins_here) or name.lower() in win_names

        found = replacements(db, name, fmt, deck, limit=limit,
                             require=wins_here if wins_here else None)
        pick = None
        for cand in found.get("cards") or []:
            if (cand.get("name") or "").lower() not in taken:
                pick = cand
                break
        if pick:
            taken.add((pick.get("name") or "").lower())
            # Что замена роняет из того, что колода повторяет. Потерять тег,
            # который есть у одной карты, -- пустяк; потерять тот, на котором
            # держится дюжина копий, -- сломать колоду.
            mine = set(_tags_of(conn, pick.get("oracle_id") or ""))
            drops = [_job(tree, t) for t in card_tags
                     if t not in mine
                     and (theme.get(t, 0) >= THEME_REPEATS or t in WIN_TAGS)]
            swaps.append(dict(base, to=pick, tags=(found.get("tags") or [])[:4],
                              drops=drops, weak=bool(drops), win=is_win))
        else:
            shelve.append(dict(base, win=is_win,
                               note=("в пуле формата нет карты, которой можно "
                                     "выиграть так же") if wins_here else
                               (found.get("note") or
                                "в пуле формата нет карты того же назначения")))

    trims = _copy_trims(deck, fmt)
    # Форма колоды -- число карт и командир -- правится руками: дописать
    # двадцать карт за пользователя программа не должна.
    shape = [r for r in report["rules"] if r.get("kind") in ("size", "commander", "side")]

    # --- переживёт ли замысел -------------------------------------------- #
    #
    # Раньше здесь стоял признак: «потерялась карта с тегом победы -- значит,
    # всё пропало». Это работало ровно на колодах с такой картой и молчало на
    # колодах, выигрывающих боем или комбо. Теперь считается честно: строится
    # колода, какой она станет после плана, и у неё спрашивается то же самое --
    # чем она выигрывает. Разница двух ответов и есть вердикт, и он одинаково
    # работает для любой колоды.
    plan_so_far = {"format": fmt, "swaps": swaps, "shelve": shelve,
                   "trims": trims}
    routes_before = win_routes(db, deck, combo_db)
    changed = after_deck(db, deck, plan_so_far)
    routes_after = win_routes(db, changed, combo_db)
    power_after, _bodies = _combat_power(db, changed)

    lost_kinds = [r for r in routes_before if r["real"] and
                  not any(a["kind"] == r["kind"] and a["strength"] > 0
                          for a in routes_after)]
    pool = win_pool(db, fmt, deck) if any(
        r["kind"] == "alt" for r in lost_kinds) else []
    intent, said = _verdict(routes_before, routes_after,
                            FORMAT_TITLES.get(fmt, fmt), pool, power_after)

    lost = [{"name": row.get("name"), "quantity": row.get("quantity"),
             "to": (row.get("to") or {}).get("name")}
            for row in swaps + shelve if row.get("win")]

    return {
        "format": fmt,
        "title": FORMAT_TITLES.get(fmt, fmt),
        "verdict": report["verdict"],
        "swaps": swaps,
        "trims": trims,
        "shelve": shelve,
        "shape": shape,
        "copies": report["copies"],
        "blocked_copies": report["blocked_copies"],
        "ready": not swaps and not trims and not shelve,
        # Чем колода выигрывает -- и что с этим станет.
        "win": win,
        "routes": routes_before,
        "win_after": {"routes": routes_after, "power": power_after},
        "intent": intent,
        "said": said,
        "lost": lost,
        "win_pool": pool,
    }


__all__ = ["FORMATS", "FORMAT_TITLES", "adapt", "check", "legality",
           "replacements", "survey", "theme"]

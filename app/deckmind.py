"""О чём эта колода — и что ей предложить.

Предложка до сих пор умела один вопрос: «что обычно играют с этим
командиром». Для модерна, пионера и всего остального она спрашивала имя
командира, которого там нет, и на том заканчивалась. А человек хочет не
«что играют с Аткой», а «я собираю милл — покажи ещё милл», «у меня синий —
где контрмагия подешевле», «есть манадорки — какие бывают лучше».

Здесь это делается без интернета, по локальной базе.

**Чем виден смысл.** У карт Scryfall есть теги: `fog`, `mill-self`,
`mana-dork`, `counterspell`, `reanimate-permanent` — четыре с половиной
тысячи штук, 235 тысяч связей. Тема колоды — тег, который в ней встречается
заметно чаще, чем вообще бывает. «Fog» в базе у 36 карт из 37854; три такие
карты в колоде из двадцати пяти — это не совпадение, а замысел.

Мера — **выраженность**: во сколько раз доля тега в колоде больше его доли в
базе. Она же отсеивает то, что есть у всех: `triggered-ability` в колоде у
каждой пятой карты, но и в базе у каждой пятой — выраженность ×1, и говорить
тут не о чем.

**Что предлагается.** По каждой теме — карты с тем же тегом, которых в колоде
нет: в её цветах, легальные в её формате. Порядок задаёт человек:

* «подешевле» — сперва то, что дешевле в рублях (по уже известным ценам);
* «посильнее» — сперва то, что переиздавали чаще: карта, которую печатали в
  десяти наборах, играется повсеместно, и это единственная мера силы,
  которую можно взять из локальной базы честно. Выдавать её за оценку
  силы нельзя — так и написано в ответе.

Наружу здесь не уходит ни одного запроса.
"""

from __future__ import annotations

import collections
import json
from typing import Any, Iterable

from .cards import CardDB, normalize_name

# Теги про оформление, имена и курьёзы: они описывают не то, что карта
# делает, а то, как она выглядит или называется. «Три буквы в названии» --
# настоящий тег Scryfall, и в теме колоды ему делать нечего.
JUNK_PARTS = (
    "-name", "art-", "artist", "flavor", "watermark", "borderless",
    "showcase", "promo", "alternate", "reprint", "frame", "full-art",
    "secret-lair", "misprint", "funny", "alliteration", "rhyme",
    "single-english", "three-letter", "double-letter", "palindrome",
)

# У тегов Scryfall есть дерево, и мусор в нём растёт из своих корней:
# «eponymous» и «virtual-legendary» -- это `card-names`, а полторы тысячи
# тегов вида «цикл редких земель такого-то набора» -- `cycle`. Отсев по
# корню надёжнее списка слов: он ловит и то, чего мы не видели.
JUNK_ROOTS = {
    "card-names", "cycle", "vertical-cycle", "draft-signpost",
    "un-set-mechanics", "face-commander", "art", "flavor", "booster",
    "watermark", "frame-effect", "promo", "acorn",
}

# Теги, которые есть почти у всего: они верны и бесполезны.
TOO_COMMON = {
    "triggered-ability", "activated-ability", "etb", "creature-type-matters",
    "single-target-instant-sorcery", "permanent", "spell",
    # Про устройство самой карточки, а не про то, что она делает в игре.
    # «Уникальная типовая строка» верна для пяти базовых земель подряд -- и
    # ровно поэтому выглядела замыслом у колоды, где замысла нет.
    "unique-type-line", "vanilla", "french-vanilla", "basic-land",
    "flavors-of-vanilla", "historic", "modal", "split-card", "double-faced",
}

# Сколько карт колоды должно нести тег, чтобы считать его темой, и во
# сколько раз он должен быть гуще, чем в базе.
MIN_CARDS = 3
MIN_LIFT = 4.0
# Тег, которым помечены три карты из четырёх тысяч, -- это не тема, а
# редкость: предлагать по нему нечего.
MIN_TAG_SIZE = 12

# Сколько тем показывать и сколько карт в каждой.
MAX_THEMES = 6
MAX_PICKS = 12

# Русские имена частых тем. Остальным достаётся собственный slug и
# английское описание из самой базы -- это честнее, чем выдумывать перевод
# для четырёх с половиной тысяч тегов.
RU_THEMES = {
    "fog": "Туманы: бой не наносит урона",
    "mill-self": "Самомилл: сброс своей библиотеки",
    "mill-opponent": "Милл: сброс чужой библиотеки",
    "mill": "Милл",
    "counterspell": "Контрмагия",
    "counter-spell": "Контрмагия",
    "mana-dork": "Манадорки: существа, дающие ману",
    "mana-rock": "Мана-артефакты",
    "land-ramp": "Рампа землями",
    "ramp": "Рампа",
    "lifegain": "Набор жизней",
    "lifegain-matters": "Жизни имеют значение",
    "sacrifice-outlet": "Куда жертвовать",
    "sacrifice-matters": "Жертвоприношение",
    "reanimate-permanent": "Реанимация перманентов",
    "reanimate-creature": "Реанимация существ",
    "reanimate-aura": "Реанимация аурами",
    "cheat-death": "Возвращение с кладбища",
    "graveyard-fuel-self": "Своё кладбище как ресурс",
    "token-creation": "Фишки",
    "tokens-matter": "Фишки имеют значение",
    "landfall": "Лэндфолл",
    "play-additional-land": "Больше земель за ход",
    "sneak-land": "Земли из библиотеки в игру",
    "card-draw": "Добор карт",
    "pure-draw": "Чистый добор",
    "cantrip": "Кантрипы",
    "spot-removal": "Точечное удаление",
    "board-wipe": "Массовое удаление",
    "burn": "Бёрн: прямой урон",
    "direct-damage": "Прямой урон",
    "lifeloss": "Потеря жизней",
    "discard-opponent": "Сброс карт противника",
    "tutor": "Поиск карт в библиотеке",
    "protects-planeswalker": "Защита планесвокеров",
    "equipment": "Снаряжение",
    "aura": "Ауры",
    "flying-matters": "Полёт",
    "artifacts-matter": "Артефакты имеют значение",
    "enchantments-matter": "Чары имеют значение",
    "infect": "Инфект",
    "storm": "Шторм",
    "cascade": "Каскад",
    "flashback": "Воспоминание",
    "energy": "Энергия",
    "proliferate": "Распространение жетонов",
    "untapper": "Разворот перманентов",
    "stax": "Стакс: связывание противника",
    "symmetrical": "Симметричные эффекты",
    "extra-turn": "Лишние ходы",
    "extra-combat": "Лишние бои",
    "blink": "Мигание: уход и возвращение",
    "clone": "Копии существ",
    "steal-permanent": "Захват чужого",
    "wheel": "Колесо: сброс и перебор рук",
    "group-hug": "Общая польза",
    "voltron": "Вольтрон: одно существо",
    "removal": "Удаление",
    "removal-creature": "Удаление существ",
    "repeatable-removal": "Повторяемое удаление",
    "mass-removal": "Массовое удаление",
    "mana-producer": "Источники маны",
    "mana-filter": "Фильтрация маны",
    "filterland": "Земли-фильтры",
    "regrowth": "Возврат из кладбища в руку",
    "reanimate": "Реанимация",
    "hate-graveyard": "Против кладбища",
    "hate": "Помехи противнику",
    "damage-prevention": "Предотвращение урона",
    "mill": "Милл",
    "evasion": "Непробиваемость в бою",
    "tapper": "Тапперы",
    "untap": "Разворот перманентов",
    "copy": "Копирование",
    "tutor-creature": "Поиск существ",
    "land-destruction": "Разрушение земель",
    "lifelink-matters": "Цепь жизни",
    "counters-matter": "Жетоны имеют значение",
    "sacrifice": "Жертвоприношение",
    "treasure": "Сокровища",
    "adds-multiple-mana": "Много маны разом",
    "card-advantage": "Преимущество по картам",
    "discard": "Сброс карт",
    "recursion": "Возврат своего",
    "protection": "Защита своего",
    "pump": "Усиление существ",
    "haste-granting": "Выдача ускорения",
    "blink-self": "Мигание своих",
    "flicker": "Мигание",
    "commander-matters": "Про командира",
}


def _junky(slug: str) -> bool:
    if slug in TOO_COMMON:
        return True
    return any(part in slug for part in JUNK_PARTS)


def _tag_parents(db: CardDB) -> dict[str, str]:
    """slug -> непосредственный родитель. Читается один раз на запрос."""
    out = {}
    for row in db.conn.execute("SELECT slug, parents FROM tags"):
        parent = (row["parents"] or "").split(",")[0].strip()
        if parent:
            out[row["slug"]] = parent
    return out


def tag_root(slug: str, parents: dict[str, str]) -> str:
    """Корень дерева для тега. Цикл в данных не должен вешать разбор."""
    seen = set()
    cur = slug
    while cur in parents and cur not in seen:
        seen.add(cur)
        cur = parents[cur]
    return cur


def theme_label(slug: str, description: str = "") -> str:
    """Как назвать тему человеку."""
    if slug in RU_THEMES:
        return RU_THEMES[slug]
    pretty = slug.replace("-", " ")
    return pretty[:1].upper() + pretty[1:]


def _card_rows(db: CardDB, names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Имя -> представительная печать. По одному запросу на имя: имён в
    колоде сотня, а не сто тысяч."""
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        key = normalize_name(name)
        if key in out:
            continue
        row = db.conn.execute(
            "SELECT oracle_id, name, ru_name, color_identity, cmc, type_line,"
            "       legalities, prices, image_small, rarity "
            "FROM cards WHERE LOWER(name) = ? "
            "ORDER BY representative DESC LIMIT 1",
            (str(name or "").strip().lower(),)).fetchone()
        if row:
            out[key] = dict(row)
    return out


def _total_cards(db: CardDB) -> int:
    row = db.conn.execute(
        "SELECT COUNT(DISTINCT oracle_id) AS n FROM cards").fetchone()
    return int(row["n"] or 1)


def _legal_in(legalities: Any, fmt: str) -> bool:
    """Легальна ли карта в формате колоды. Нет формата -- не ограничиваем."""
    if not fmt:
        return True
    data = legalities
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return True
    if not isinstance(data, dict):
        return True
    verdict = data.get(fmt.lower())
    return verdict in (None, "legal", "restricted")


def _within(colours: str, identity: set[str]) -> bool:
    """Карта в цветах колоды: бесцветная подходит всегда."""
    own = set(colours or "")
    return own.issubset(identity) if own else True


def deck_identity(rows: Iterable[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for row in rows:
        for ch in (row.get("color_identity") or ""):
            out.add(ch)
    return out


def themes(deck_cards: list[dict[str, Any]], db: CardDB) -> dict[str, Any]:
    """Чем занята колода: темы по убыванию выраженности."""
    names = [c.get("name") or "" for c in deck_cards if c.get("name")]
    rows = _card_rows(db, names)
    if not rows:
        return {"themes": [], "colors": "", "read": 0, "of": len(names)}

    total = _total_cards(db)
    parents = _tag_parents(db)
    by_tag: dict[str, list[str]] = collections.defaultdict(list)
    for key, row in rows.items():
        oracle = row.get("oracle_id")
        if not oracle:
            continue
        for tag in db.conn.execute(
                "SELECT slug FROM card_tags WHERE oracle_id = ?", (oracle,)):
            slug = tag["slug"]
            if _junky(slug) or tag_root(slug, parents) in JUNK_ROOTS:
                continue
            # Тег и его родитель -- оба. Теги Scryfall дробные:
            # «counterspell-with-set-mechanic», «mill-self-small». Называть
            # тему этим словом нельзя, и выбирать по нему тоже: под узким
            # тегом лежит десяток карт, под родительским -- сотня, и это
            # ровно та сотня, из которой человек и хочет выбирать.
            # Слишком общий родитель отсеется сам: у него низкая
            # выраженность.
            for name in (slug, parents.get(slug, "")):
                if not name or _junky(name):
                    continue
                if tag_root(name, parents) in JUNK_ROOTS:
                    continue
                if row["name"] not in by_tag[name]:
                    by_tag[name].append(row["name"])

    sizes = {}
    for slug in by_tag:
        row = db.conn.execute(
            "SELECT card_count, description FROM tags WHERE slug = ?",
            (slug,)).fetchone()
        sizes[slug] = (int(row["card_count"] or 0) if row else 0,
                       (row["description"] if row else "") or "")

    found = len(rows)
    out = []
    for slug, cards in by_tag.items():
        size, description = sizes.get(slug, (0, ""))
        if len(cards) < MIN_CARDS or size < MIN_TAG_SIZE:
            continue
        share = len(cards) / found
        rate = size / total
        lift = share / rate if rate else 0.0
        if lift < MIN_LIFT:
            continue
        out.append({
            "slug": slug,
            "label": theme_label(slug, description),
            "description": description,
            "cards": sorted(cards)[:8],
            "in_deck": len(cards),
            "tag_size": size,
            "lift": round(lift, 1),
        })

    out.sort(key=lambda t: (-t["lift"], -t["in_deck"]))

    # Тема и её же подтема -- одно и то же дважды: «Контрмагия» и
    # «Counterspell with set mechanic» описывают те же карты, занимают два
    # места из шести и выглядят как две разные мысли. Оставляем ту, что
    # выше в списке: она либо выразительнее, либо шире.
    kept: list[dict[str, Any]] = []
    taken: set[str] = set()
    for theme in out:
        slug = theme["slug"]
        chain = set()
        cur = slug
        seen = set()
        while cur in parents and cur not in seen:
            seen.add(cur)
            cur = parents[cur]
            chain.add(cur)
        if slug in taken or chain & taken:
            continue
        kept.append(theme)
        taken.add(slug)
    out = kept

    return {
        "themes": out[:MAX_THEMES],
        "colors": "".join(sorted(deck_identity(rows.values()))),
        "read": found,
        "of": len(names),
    }


def _printings_of(db: CardDB, oracle: str) -> int:
    """Сколько раз карту печатали -- мера того, насколько она в ходу."""
    row = db.conn.execute(
        "SELECT COUNT(*) AS n FROM cards WHERE oracle_id = ?",
        (oracle,)).fetchone()
    return int(row["n"] or 0)


def picks_for_theme(
    slug: str,
    db: CardDB,
    identity: set[str],
    fmt: str,
    already: set[str],
    prices: dict[str, dict[str, Any]] | None = None,
    order: str = "fit",
    limit: int = MAX_PICKS,
) -> list[dict[str, Any]]:
    """Карты этой темы, которых в колоде нет."""
    prices = prices or {}
    rows = db.conn.execute(
        "SELECT c.oracle_id, c.name, c.ru_name, c.color_identity, c.cmc,"
        "       c.type_line, c.legalities, c.prices, c.image_small, c.rarity "
        "FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id "
        "WHERE t.slug = ? AND c.representative = 1 "
        "GROUP BY c.oracle_id", (slug,)).fetchall()

    picks = []
    for row in rows:
        card = dict(row)
        key = normalize_name(card["name"])
        if key in already:
            continue
        if not _within(card.get("color_identity"), identity):
            continue
        if not _legal_in(card.get("legalities"), fmt):
            continue
        usd = None
        raw = card.get("prices")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = None
        if isinstance(raw, dict):
            try:
                usd = float(raw.get("usd") or raw.get("usd_foil") or 0) or None
            except (TypeError, ValueError):
                usd = None
        known = prices.get(key) or {}
        rub = known.get("rub_min")
        picks.append({
            "name": card["name"],
            "ru_name": card.get("ru_name"),
            "type_line": card.get("type_line"),
            "cmc": card.get("cmc"),
            "rarity": card.get("rarity"),
            "image_small": card.get("image_small"),
            "usd": usd,
            "rub": rub,
            "printings": _printings_of(db, card["oracle_id"]),
        })

    # Сперва ходовые -- в любом порядке. Без этого «подешевле» давало свалку:
    # самые дешёвые карты темы -- это карты, которые никто не играет, и на
    # запрос «где контрмагия дешевле» приезжал мусор ценой в рубль. Сначала
    # отбираем то, что вообще в ходу, и уже внутри этого ищем дешёвое.
    picks.sort(key=lambda p: (-p["printings"], p["cmc"] or 0, p["name"]))
    shortlist = picks[:max(limit * 5, 40)]

    if order == "cheap":
        # Неизвестная цена -- не повод считать карту дешёвой: такие в конец.
        shortlist.sort(key=lambda p: (
            p["rub"] is None and p["usd"] is None,
            p["rub"] if p["rub"] is not None else (p["usd"] or 0) * 100,
            -p["printings"]))
    return shortlist[:limit]


def ideas(
    deck: dict[str, Any],
    db: CardDB,
    prices: dict[str, dict[str, Any]] | None = None,
    order: str = "fit",
    sections: int = MAX_THEMES,
) -> dict[str, Any]:
    """Полный ответ: о чём колода и что ей предложить по каждой теме."""
    cards = [c for c in (deck.get("cards") or [])
             if (c.get("section") or "main") in ("main", "commander")]
    read = themes(cards, db)
    already = {normalize_name(c.get("name") or "")
               for c in (deck.get("cards") or [])}
    identity = set(read["colors"])
    fmt = (deck.get("format") or "").strip().lower()

    out = []
    for theme in read["themes"][:sections]:
        picks = picks_for_theme(
            theme["slug"], db, identity, fmt, already,
            prices=prices, order=order)
        if not picks:
            continue
        out.append({
            "slug": theme["slug"],
            "label": theme["label"],
            "description": theme["description"],
            "why": "в колоде %d %s этой темы — чаще обычного в %g раз"
                   % (theme["in_deck"],
                      "карта" if theme["in_deck"] == 1 else "карт",
                      theme["lift"]),
            "in_deck": theme["in_deck"],
            "lift": theme["lift"],
            "examples": theme["cards"][:4],
            "picks": picks,
        })

    return {
        "themes": read["themes"],
        "colors": read["colors"],
        "format": fmt,
        "read": read["read"],
        "of": read["of"],
        "order": order,
        "sections": out,
    }


__all__ = ["ideas", "themes", "picks_for_theme", "theme_label", "deck_identity"]

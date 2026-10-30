"""Сцена: программа с данными, которая никуда не ходит.

Браузерные сценарии (`tests/ui_*.py`) проверяют не разметку, а то, что
человек читает с экрана: «подешевело на 25%», «дешевле всего виденного: 3»,
«собранные колоды претендуют на карты, которых столько нет». Ничего из этого
на пустой программе не появляется -- и в сборке релиза, где копия свежая,
двенадцать сценариев из пятидесяти семи падали не потому, что интерфейс
разъехался, а потому, что им нечего было показывать.

Жить с этим было нельзя в обе стороны: падающая сборка не выпускает релиз
(архива не было с 1.33.0), а сделать шаг необязательным значило бы выключить
единственную проверку того, что видит человек.

Поэтому здесь -- сцена. Она заводит свою папку данных, наполняет её
выдуманной, но правдоподобной жизнью (коллекция, колоды, избранное, цены с
историей и разбором по версиям) и поднимает программу на ней. Наружу сцена не
ходит: клиент topdeck подменён выдумкой, и все продавцы в ней зовутся
«ПРОВЕРКА-...», чтобы ни один снимок экрана нельзя было спутать с настоящими
данными.

    python tests/stage.py --port 8799
    python tests/stage.py --port 8799 --data C:/temp/stage   # своя папка
    python tests/stage.py --seed-only --data C:/temp/stage   # только наполнить

Чего здесь нет и не будет: чьих-либо настоящих данных. Всё, что сцена кладёт
в базу, написано в этом файле -- имена карт public domain, продавцы выдуманы,
цены взяты с потолка.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Папка данных ставится ДО импорта программы: модули запоминают её при
# первом обращении. Та же причина, по которой это условие живёт здесь, а не
# в команде запуска: один запуск без переменной -- и сцена пишет в настоящую
# коллекцию. Так уже было, данные уцелели по удаче.
MARKER = "stage.id"


def data_dir(where: str | None) -> str:
    """Папка сцены -- своя и только своя.

    Отказ работать в чужой папке важнее удобства: в `data` рядом с
    программой лежит `user.sqlite` живого человека, и сцена, наполняющая
    его выдуманными колодами, -- это потеря данных, а не неудобство.
    """
    path = os.path.abspath(where or os.path.join(ROOT, "data", "stage"))
    os.makedirs(path, exist_ok=True)
    mark = os.path.join(path, MARKER)
    if not os.path.exists(mark):
        strangers = [n for n in os.listdir(path) if n != MARKER]
        if strangers:
            raise SystemExit(
                "В %s уже что-то лежит (%s). Сцена заводит свою папку и "
                "чужую не трогает: укажите пустую через --data."
                % (path, ", ".join(sorted(strangers)[:4])))
        with open(mark, "w", encoding="utf-8") as fh:
            fh.write("Папка сцены для tests/stage.py. Данные выдуманы.\n")
    return path


def share_databases(path: str) -> None:
    """Общие базы -- ссылкой, а не копией.

    `cards.sqlite` программа ищет рядом с собой, а `combos.sqlite`,
    `art_hashes.sqlite` и `sets.json` -- в папке данных. В своей папке их
    нет, и сценарии честно показывали «комбо в колоде: 0», то есть падали
    из-за оснастки, а не из-за программы. Ссылка не занимает места и не
    плодит вторую базу, которую надо помнить обновлять.
    """
    for shared in ("combos.sqlite", "art_hashes.sqlite", "sets.json"):
        there = os.path.join(path, shared)
        here = os.path.join(ROOT, "data", shared)
        if os.path.exists(there) or not os.path.exists(here):
            continue
        try:
            os.link(here, there)
        except OSError:
            # Разные тома -- ссылку не сделать; копия тоже годится.
            import shutil

            shutil.copy2(here, there)


# --------------------------------------------------------------- наполнение

# Карты настоящие -- их знает офлайн-база, и без этого половина экранов
# показывала бы «карта неизвестна». Всё остальное выдумано.
STAPLES = [
    "Lightning Bolt", "Counterspell", "Sol Ring", "Arcane Signet",
    "Swords to Plowshares", "Path to Exile", "Brainstorm", "Ponder",
    "Birds of Paradise", "Llanowar Elves", "Cultivate", "Rampant Growth",
    "Dark Ritual", "Demonic Tutor", "Beast Within", "Krosan Grip",
    "Wrath of God", "Fog", "Opt", "Preordain", "Serum Visions",
    "Thoughtseize", "Fatal Push", "Command Tower", "Rhystic Study",
    "Cyclonic Rift", "Smothering Tithe", "Mystic Remora", "Sakura-Tribe Elder",
    "Eternal Witness", "Solemn Simulacrum", "Burnished Hart",
    "Austere Command", "Blasphemous Act", "Heroic Intervention",
    # Второй десяток нужен не для красоты: окно коллекции показывает
    # карты порциями, и проверка «показано не всё» на три десятка имён
    # не срабатывает вовсе -- всё помещается сразу.
    "Negate", "Dispel", "Mana Leak", "Remand", "Condescend",
    "Thought Scour", "Faithless Looting", "Lava Spike", "Chain Lightning",
    "Seal of Fire", "Galvanic Blast", "Abrade", "Shock",
    "Duress", "Inquisition of Kozilek", "Agony Warp", "Doom Blade",
    "Go for the Throat", "Victim of Night", "Reanimate", "Unearth",
    "Giant Growth", "Harrow", "Explore", "Farseek", "Kodama's Reach",
    "Nature's Lore", "Wall of Blossoms", "Elvish Mystic", "Fyndhorn Elves",
    "Disenchant", "Naturalize", "Dawn Charm", "Holy Day", "Ethereal Haze",
    "Pacifism", "Oblivion Ring", "Journey to Nowhere", "Banishing Light",
    "Mind Stone", "Fellwar Stone", "Star Compass", "Wayfarer's Bauble",
    "Force of Will",
]

LANDS = ["Island", "Mountain", "Forest", "Swamp", "Plains"]

# Карты, которых у сцены нет на руках, хотя колоды их просят.
SHORT = ("Force of Will",)

# Сайдборды чужих колод берутся из этого небольшого набора, а не из общего
# списка. Причина не в экономии: сайдборд -- это ответ на чужую колоду, и в
# жизни полтора десятка карт отвечают за весь формат. Если тянуть сайд из
# восьми десятков имён поровну, «что держат в сайде» выродится в список
# случайностей, где каждая карта встречается у одной колоды из сорока, --
# то есть в статистику, по которой нельзя ничего сказать.
SIDE_POOL = [
    "Negate", "Dispel", "Duress", "Abrade", "Disenchant", "Naturalize",
    "Veil of Summer", "Pithing Needle", "Rest in Peace", "Mystical Dispute",
]

# Колоды сцены. Формат, состав и «собрана» подобраны так, чтобы на экранах
# было что показывать: собранная колода спорит с коллекцией за карты, у
# модерновой есть сайдборд, у командирской -- командир.
DECKS = [
    {
        "name": "Сцена · разбег",
        "format": "modern",
        # Собранных колод у сцены нет, и это правило, а не случайность.
        # «Собрана» значит «эти копии заняты», то есть претензия на
        # коллекцию: любой сценарий, который считает свободные карты,
        # начинает видеть чужие занятые копии и падать. Собранную колоду
        # сценарий заводит себе сам -- и только себе.
        "assembled": False,
        "family": "Сцена · разбег",
        "main": [("Lightning Bolt", 4), ("Counterspell", 4), ("Brainstorm", 4),
                 ("Ponder", 4), ("Opt", 3), ("Preordain", 3),
                 ("Serum Visions", 2), ("Fatal Push", 4), ("Thoughtseize", 4),
                 ("Island", 12), ("Mountain", 8)],
        "side": [("Krosan Grip", 2), ("Fog", 2), ("Beast Within", 1)],
    },
    {
        "name": "Сцена · разбег, вторая редакция",
        "format": "modern",
        "assembled": False,
        "family": "Сцена · разбег",
        "main": [("Lightning Bolt", 4), ("Counterspell", 4), ("Brainstorm", 4),
                 ("Ponder", 2), ("Opt", 2), ("Remand", 3), ("Mana Leak", 2),
                 ("Fatal Push", 3), ("Thoughtseize", 3), ("Force of Will", 2),
                 ("Island", 12), ("Mountain", 8)],
        "side": [("Negate", 2), ("Dispel", 2), ("Abrade", 2)],
    },
    {
        "name": "Сцена · зелёный разгон",
        "format": "pioneer",
        "assembled": False,
        "main": [("Birds of Paradise", 4), ("Llanowar Elves", 4),
                 ("Cultivate", 3), ("Rampant Growth", 3),
                 ("Eternal Witness", 3), ("Sakura-Tribe Elder", 4),
                 ("Beast Within", 2), ("Heroic Intervention", 2),
                 ("Forest", 14)],
        "side": [("Krosan Grip", 3)],
    },
    {
        "name": "Сцена · стол на четверых",
        "format": "commander",
        "assembled": False,
        "commander": "Atraxa, Praetors' Voice",
        "main": [("Sol Ring", 1), ("Arcane Signet", 1), ("Command Tower", 1),
                 ("Rhystic Study", 1), ("Cyclonic Rift", 1),
                 ("Smothering Tithe", 1), ("Mystic Remora", 1),
                 ("Demonic Tutor", 1), ("Austere Command", 1),
                 ("Solemn Simulacrum", 1), ("Burnished Hart", 1),
                 ("Swords to Plowshares", 1), ("Island", 8), ("Swamp", 7),
                 ("Forest", 7), ("Plains", 7)],
        "side": [],
    },
]

# Избранное: две папки, и у одной карты названа цена, по которой человек
# готов её взять, -- без неё «Дождались» проверять не на чем.
FAVOURITES = [
    ("Сцена · хотелки", [("Rhystic Study", 1, 3000),
                         ("Cyclonic Rift", 1, 0),
                         ("Smothering Tithe", 2, 0)]),
    ("Сцена · на потом", [("Mystic Remora", 1, 0),
                          ("Austere Command", 1, 500)]),
]


def seed(path: str) -> dict[str, int]:
    """Наполнить папку сцены. Повторный запуск ничего не портит."""
    os.environ["MTGH_DATA_DIR"] = path

    from app import collection as collection_store
    from app import favourites
    from app.decks import DeckStore

    collection_store.reset_connection()
    favourites.reset_connection()
    store = DeckStore()

    # ---- коллекция.
    #
    # Правило, которое важнее состава: **сцена не создаёт нехватки**. Всё,
    # что просят её колоды, на руках есть. Иначе карты сцены лезут в охоту
    # и в список покупок каждого сценария, который заводит свою колоду, --
    # и сценарий проверяет уже не себя, а оснастку. Нехватку сценарии
    # устраивают сами, своими колодами.
    owned: dict[str, int] = {}
    for spec in DECKS:
        for name, qty in (list(spec["main"]) + list(spec.get("side", []))):
            owned[name] = owned.get(name, 0) + qty
        if spec.get("commander"):
            owned[spec["commander"]] = owned.get(spec["commander"], 0) + 1
    for i, name in enumerate(STAPLES):
        owned[name] = max(owned.get(name, 0), 2 + (i % 3))
    for land in LANDS:
        owned[land] = max(owned.get(land, 0), 30)
    # Одно исключение из правила -- и оно названо.
    #
    # Коллекция без единой нехватки -- это тоже неправда: списку покупок,
    # разбору семейства и «чего не хватает» нечего показывать, и проверки
    # этих экранов упираются в пустые таблицы. Поэтому ровно одна карта
    # одной колоды остаётся ненайденной -- столько, чтобы экраны ожили, и
    # так мало, чтобы её легко было не считать.
    for name in SHORT:
        owned.pop(name, None)
    collection_store.replace(owned)

    # ---- колоды
    made = 0
    known = {d["name"] for d in store.list_decks()}
    for spec in DECKS:
        if spec["name"] in known:
            continue
        deck_id = store.create_deck(spec["name"], spec["format"])
        for name, qty in spec["main"]:
            store.add_card(deck_id, name, qty, "main")
        for name, qty in spec.get("side", []):
            store.add_card(deck_id, name, qty, "side")
        if spec.get("commander"):
            store.add_card(deck_id, spec["commander"], 1, "commander")
        if spec.get("assembled"):
            store.rename_deck(deck_id, None, None, assembled=True)
        if spec.get("family"):
            store.rename_deck(deck_id, None, None, family=spec["family"])
        made += 1

    # ---- избранное
    doc = favourites.load()
    folders = {f["name"]: f["id"] for f in doc["folders"]}
    for name, cards in FAVOURITES:
        folder_id = folders.get(name)
        if folder_id is None:
            folder_id = favourites.create_folder(name)["folders"][0]["id"]
            folder_id = [f["id"] for f in favourites.load()["folders"]
                         if f["name"] == name][0]
        have = {c["name"] for f in favourites.load()["folders"]
                if f["id"] == folder_id for c in f["cards"]}
        for card, qty, target in cards:
            if card in have:
                continue
            added = favourites.add_card(folder_id, card, qty)
            if target:
                card_id = [c["id"] for f in added["folders"]
                           if f["id"] == folder_id
                           for c in f["cards"] if c["name"] == card]
                if card_id:
                    favourites.update_card(folder_id, card_id[0], target=target)

    prices = seed_prices(store)
    seed_worth(collection_store)
    samples = seed_samples()
    return {"decks": made, "cards": len(owned), "prices": prices,
            "samples": samples}


# Выборки чужих колод, которые сцена рисует сама.
#
# «Под ваш состав», «что держат в сайде», «сравнить с соседом», «смысл
# колоды» -- всё это считается по выборке чужих колод с Archidekt. В свежей
# копии её нет, и четыре сценария честно упирались в «выборка не собрана».
# Качать её в сборке нельзя: это чужой сайт и сотни запросов за каждую
# сборку.
#
# Поэтому колоды здесь выдуманы, но устроены как настоящие: общее ядро,
# разный хвост, сайдборды, даты. Статистика по ним получается осмысленная --
# «эту карту держат девять из десяти», -- а наружу не уходит ничего.
SAMPLE_FORMATS = ("modern", "pioneer", "legacy", "standard", "pauper")
SAMPLE_COMMANDERS = ("Tiamat", "Atraxa, Praetors' Voice")
SAMPLE_SIZE = 60


def _sample_deck(pool, rnd, wide, commander=None):
    """Одна чужая колода: ядро формата плюс свой хвост."""
    core, rest = pool[:8], pool[8:]
    picked = list(core) + rnd.sample(rest, wide)
    main: dict[str, int] = {}
    for name in picked:
        main[name] = 1 if commander else (4 if name in core
                                          else rnd.choice((1, 2, 3, 4)))
    if commander:
        main[commander] = 1
        for land in LANDS[:3]:
            main[land] = rnd.choice((6, 7, 8))
    else:
        for land in LANDS[:2]:
            main[land] = rnd.choice((8, 10, 12))
    side = ({} if commander
            else {name: rnd.choice((1, 2, 3))
                  for name in rnd.sample(SIDE_POOL, 5)})
    return {"main": main, "side": side}


def seed_samples() -> int:
    """Положить выборки на диск, если их там ещё нет."""
    from app import archidekt

    pool = [n for n in dict.fromkeys(STAPLES) if n not in LANDS]
    written = 0
    keys = ([archidekt.format_key(f) for f in SAMPLE_FORMATS]
            + [archidekt.commander_key(c) for c in SAMPLE_COMMANDERS])
    for key in keys:
        if archidekt.load(key).get("decks"):
            continue
        rnd = random.Random("сцена:" + key)
        edh = key.startswith("cmd:")
        decks, meta, ids = {}, {}, []
        for i in range(SAMPLE_SIZE):
            deck_id = "%d%03d" % (abs(hash(key)) % 900 + 100, i)
            decks[deck_id] = _sample_deck(
                pool, rnd, 54 if edh else 14,
                key.split(":", 1)[1] if edh else None)
            meta[deck_id] = {
                "name": "Колода сцены №%d" % (i + 1),
                # Дата нужна «свежести выборки»: без неё программа пишет,
                # что про возраст колод ничего не известно.
                "updated": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(time.time() - (i % 30) * 86400)),
                "views": 100 + i * 7,
                "size": sum(decks[deck_id]["main"].values()),
            }
            ids.append(deck_id)
        skipped = {"%s-skip-%d" % (deck_id[:3], n): reason
                   for n, reason in enumerate(
                       ["private", "small", "old", "small", "private"])}
        archidekt._save(key, {"key": key, "ids": ids, "decks": decks,
                              "failed": [], "skipped": skipped, "meta": meta,
                              "pages_done": 3})
        written += 1
    return written


def seed_prices(store) -> int:
    """Цены с прошлым: история, разбор по версиям и «было -- стало».

    Это самая важная часть наполнения. Три экрана из новых -- коридор цены,
    список изменений и «ваша цена» -- не показывают ничего, пока цену
    спросили один раз, и проверять их на свежей копии значит проверять
    пустое место. Числа выдуманы, но устроены как настоящие: у части карт
    цена менялась, у части -- стояла, у части её не знают вовсе.
    """
    from app.cards import normalize_name

    rnd = random.Random(20261029)
    names = STAPLES + LANDS + ["Atraxa, Praetors' Voice"]
    written = 0
    for i, name in enumerate(names):
        if i % 9 == 0:
            continue                       # про эти цену не спрашивали
        base = 40 + (i * 37) % 900
        # Разбор по версиям -- у двух третей: остальные остаются «одним
        # числом на имя», и докуп честно скажет, что сравнивает грубо.
        variants = None
        if i % 3:
            variants = [
                {"set_code": "m10", "foil": 0, "condition": "NM",
                 "language": "EN", "rub_min": base, "rub_max": base + 30,
                 "offers": 3},
                {"set_code": "2x2", "foil": 1, "condition": "NM",
                 "language": "EN", "rub_min": base * 6, "rub_max": base * 8,
                 "offers": 2},
            ]
        # История: замеры за прошлые дни. Трёх хватает на коридор цены,
        # поэтому у большинства их три и больше.
        points = 3 + (i % 3) if i % 4 else 1
        for back in range(points, 0, -1):
            shift = rnd.choice((-12, -5, 0, 0, 7, 15))
            # Замеры кладутся прямо, с датой: обычная запись знает только
            # «сегодня», а сцене нужно прошлое. Повторный запуск такие
            # строки перепишет, а не удвоит.
            day = time.strftime("%Y-%m-%d",
                                time.localtime(time.time() - back * 86400))
            with store.conn:
                store.conn.execute(
                    "INSERT OR REPLACE INTO price_history "
                    "(name_norm, at, rub_min, rub_median, offers) "
                    "VALUES (?,?,?,?,?)",
                    (normalize_name(name), day,
                     max(10, base + shift * back), base + 40, 4))
        store.store_price(name, base, base + 40, 3 + i % 5,
                          cheapest_seller="ПРОВЕРКА-Один",
                          cheapest_line="1 %s (m10) NM %d" % (name, base),
                          variants=variants)
        # «Было -- стало»: у каждой третьей карты цена изменилась.
        if i % 3 == 1:
            store.store_price(name, max(10, base - 20), base + 30, 4 + i % 3,
                              variants=variants)
        written += 1
    return written


def seed_worth(collection_store) -> None:
    """Оценка коллекции за несколько дней -- иначе график рисовать не из чего."""
    history = collection_store.value_history()
    if len(history) > 2:
        return
    conn = collection_store._conn()
    with conn:
        for back in range(6, 0, -1):
            day = time.strftime("%Y-%m-%d",
                                time.localtime(time.time() - back * 86400))
            conn.execute(
                "INSERT OR REPLACE INTO collection_value "
                "(at, cards, copies, usd, rub, priced) VALUES (?,?,?,?,?,?)",
                (day, 33, 120, 180.0 + back * 4, 9000 + back * 120, 30))


class FakeSampler:
    """Сборщик чужих колод, который ничего не качает.

    Выборки под формат и командира сцена кладёт на диск заранее, но этого
    мало: половина экранов спрашивает выборку **по отмеченным картам** --
    «колоды модерна, где есть Fog и Arboreal Grazer», -- а какие карты
    программа отметит, заранее не знает никто. Кнопка «собрать выборку»
    при этом ходит на Archidekt, и в сборке ей ходить нельзя.

    Поэтому сборщик подменён: он выдумывает колоды на любой ключ, и в них
    обязательно есть те самые отмеченные карты -- иначе выборка «по
    картам» была бы выборкой без этих карт, то есть ложью.
    """

    PAGES = 6
    PER_PAGE = 25
    # Темп. Настоящий сборщик ждёт полторы секунды между запросами, и
    # половина обещаний экрана -- про это ожидание: кнопка «остановить»,
    # счётчик скачанного, «порция по двенадцать». Сборщик, который
    # отвечает мгновенно, проверяет их в условиях, которых не бывает:
    # сценарий жал «стоп», а к этому мигу выборка успевала вырасти на три
    # порции -- и падала проверка, а не программа. Полторы секунды здесь
    # ни к чему (ждать некого), но темп нужен осязаемый.
    PACE = 0.2

    def __init__(self) -> None:
        self.key = ""

    def more_ids(self, key, data):
        from app.archidekt import key_parts

        time.sleep(self.PACE)
        self.key = key
        page = int(data.get("pages_done") or 0) + 1
        data["pages_done"] = page
        if page > self.PAGES:
            data["exhausted"] = True
            return 0
        kind, head, _cards = key_parts(key)
        added = 0
        # Отсев до скачивания -- часть настоящей картины: закрытые колоды,
        # огрызки и списки, которых годами не трогали, стоят одного
        # запроса, и программа про них пишет отдельной строкой.
        for n, reason in enumerate(("private", "small", "old")):
            data.setdefault("skipped", {})["%s-%d-skip%d"
                                           % (kind, page, n)] = reason
        for i in range(self.PER_PAGE):
            deck_id = "%s-%d-%d" % (kind, page, i)
            if deck_id in {str(x) for x in data["ids"]}:
                continue
            data["ids"].append(deck_id)
            data.setdefault("meta", {})[deck_id] = {
                "name": "Колода сцены %s №%d" % (head, page * 100 + i),
                "updated": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(time.time() - ((page + i) % 40) * 86400)),
                "views": 50 + i * 3,
                "size": 60,
            }
            added += 1
        return added

    def one_deck(self, deck_id, min_cards=60):
        from app.archidekt import key_parts

        time.sleep(self.PACE)
        kind, head, cards = key_parts(self.key or "fmt:modern")
        pool = [n for n in dict.fromkeys(STAPLES) if n not in LANDS]
        rnd = random.Random("%s|%s" % (self.key, deck_id))
        edh = kind == "cmd"
        deck = _sample_deck(pool, rnd, 54 if edh else 14,
                            head if edh else None)
        # Выборка по картам обязана содержать эти карты -- за ними и шли.
        for name in cards:
            deck["main"].setdefault(name, 2)
        if len(deck["main"]) < max(1, min_cards):
            return None
        return deck


# ------------------------------------------------------------- без интернета

CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск"]
PEOPLE = ["ПРОВЕРКА-Один", "ПРОВЕРКА-Два", "ПРОВЕРКА-Три", "ПРОВЕРКА-Четыре"]
SETS = ["m10", "2x2", "mh2", "lea"]


class FakeTopdeck:
    """Выдуманные объявления на любой запрос, не выходя наружу.

    Поиск предложений -- единственное место, где программа дёргает чужой
    сайт. В проверках это недопустимо: чужие ресурсы, и сборка, которая
    стучится к продавцам на каждый толчок, -- это не проверка, а нагрузка
    на чужой сервер.
    """

    def search(self, names):
        from app.topdeck import Offer, Seller

        out = []
        # Объявлений на карту -- ровно четыре, и всегда.
        #
        # Было «от двух до четырёх, как повезёт», и это стоило двух
        # сценариев: проверка «полный список предложений открылся» ждёт
        # хотя бы трёх строк, а Lightning Bolt доставалось две. Проверка,
        # которая падает по жребию, не проверка -- и её падение ничего не
        # говорит о программе.
        for name in names:
            for i in range(4):
                who = PEOPLE[(len(out) + i) % len(PEOPLE)]
                seller = Seller(name=who, kind="user", id=who.lower(),
                                city=CITIES[i % len(CITIES)], refs=10 + i * 7)
                cost = 80 + i * 55
                qty = 1 + (i % 3)
                # Версии: фойл и состояние. Без них цены по версиям
                # проверить нечем -- все объявления были бы одной версией.
                mark = ["NM", "MP", "фойл NM", ""][i % 4]
                if mark.startswith("фойл"):
                    cost *= 6
                line = "%d %s (%s) %s %d" % (qty, name, SETS[i % len(SETS)],
                                             mark, cost)
                out.append(Offer(
                    name=name, eng_name=name, rus_name="", qty=qty, cost=cost,
                    seller=seller, source="topdeck",
                    # Добор отбирает только ссылки на topdeck: у частника все
                    # объявления ведут в одну тему, её и читают. С выдуманным
                    # адресом кнопка честно отвечала «в плане одни магазины»,
                    # и проверять было нечего.
                    url="https://topdeck.ru/forums/topic/99900%d/"
                        % (PEOPLE.index(who) + 1),
                    stamp="2026-10-12", line=line, city=seller.city))
        return out

    def fetch_page(self, url):
        """Тема продавца -- для добора «что ещё есть у этих продавцов».

        Отдаётся обезличенный образец из tests/data: настоящая по
        устройству страница форума, но без имён и ссылок.
        """
        path = os.path.join(ROOT, "tests", "data", "stock-topic.html")
        with open(path, encoding="utf-8") as fh:
            return fh.read()


def main() -> int:
    ap = argparse.ArgumentParser(description="Программа с данными, офлайн")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data", default=None,
                    help="папка данных сцены (по умолчанию data/stage)")
    ap.add_argument("--seed-only", action="store_true",
                    help="наполнить и выйти, не поднимая программу")
    args = ap.parse_args()

    path = data_dir(args.data)
    os.environ["MTGH_DATA_DIR"] = path
    share_databases(path)
    print("СЦЕНА: данные в %s (всё выдумано)" % path)
    counts = seed(path)
    print("СЦЕНА: колод заведено %d, имён в коллекции %d, цен записано %d, "
          "выборок чужих колод %d"
          % (counts["decks"], counts["cards"], counts["prices"],
             counts["samples"]))
    if args.seed_only:
        return 0

    import uvicorn

    import app.main as main_module

    main_module.TopdeckClient = lambda *a, **k: FakeTopdeck()
    # Сборщик выборок -- тоже подменён: кнопка «собрать выборку» работает,
    # и наружу при этом не уходит ни одного запроса.
    from app import archidekt

    archidekt.Sampler = FakeSampler
    print("СЦЕНА: предложения выдуманы, наружу не ходим")
    uvicorn.run(main_module.app, host=args.host, port=args.port,
                log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

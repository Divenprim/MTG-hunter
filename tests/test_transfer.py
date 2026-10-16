"""Перенос коллекции и колод между устройствами.

Программа локальная: данные лежат на том компьютере, где её запустили. Второй
компьютер, ноутбук в поездке, переезд на новую машину — и всё приходится
набирать заново.

Здесь проверяется то, ради чего перенос и делается:

* выгруженное читается обратно без потерь — **вместе с печатями**: карта в
  коллекции это «Sol Ring из C21 №263, нефойл», и выгрузка по именам теряет
  ровно то, ради чего коллекция ведётся по печатям;
* «добавить» не затирает то, что уже нажито на той стороне;
* «заменить» заменяет, но только то, что названо в файле;
* чужой или испорченный файл не применяется вовсе — ни наполовину, ни
  «как получится».

Свои данные: `MTGH_DATA_DIR` уводит тесты в отдельный каталог, настоящая
коллекция не трогается.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Каталог данных подменяется на свой -- и возвращается обратно после каждого
# теста. Первая версия этого не делала, и соседний набор (test_recommend)
# падал на проверке «кеш лежит под своим каталогом»: мой каталог оставался в
# окружении процесса после моих тестов. Набор, который портит окружение
# другим, хуже отсутствующего: он валит чужое и выглядит чужой ошибкой.
_PREV_DATA_DIR = os.environ.get("MTGH_DATA_DIR")
_TMP = tempfile.mkdtemp(prefix="mtgh-transfer-")
# Переменную здесь НЕ ставим. Половина наборов задаёт её прямо при импорте, а
# импортируются они все разом, до первого теста: кто импортировался последним,
# тот и победил. Поставив её тут, я отбирал каталог у test_recommend, и
# падал он -- чужой набор, чужой ошибкой. Свой каталог включается в setUp и
# выключается в tearDown, то есть ровно на время моих тестов.


def _restore_data_dir():
    if _PREV_DATA_DIR is None:
        os.environ.pop("MTGH_DATA_DIR", None)
    else:
        os.environ["MTGH_DATA_DIR"] = _PREV_DATA_DIR
    collection_store.reset_connection()
    fav_store.reset_connection()

from app import collection as collection_store  # noqa: E402
from app import favourites as fav_store  # noqa: E402
from app import transfer  # noqa: E402
from app.decks import DeckStore  # noqa: E402


_MADE: list[str] = []


def wipe():
    """Чистый лист — это новый каталог данных.

    Удалять файлы нельзя: на Windows открытый sqlite держит их, и второй тест
    спотыкается о «файл занят другим процессом». Новый каталог решает ту же
    задачу и ничего не ломает.
    """
    fresh = tempfile.mkdtemp(prefix="mtgh-transfer-", dir=_TMP)
    _MADE.append(fresh)
    os.environ["MTGH_DATA_DIR"] = fresh
    collection_store.reset_connection()
    fav_store.reset_connection()
    return DeckStore()


class TransferCase(unittest.TestCase):
    def setUp(self):
        self.store = wipe()

    def tearDown(self):
        # Возвращаем окружение как было: следующий тест -- хоть здешний, хоть
        # из соседнего файла -- должен видеть свой каталог, а не мой.
        _restore_data_dir()

    @classmethod
    def tearDownClass(cls):
        _restore_data_dir()
        shutil.rmtree(_TMP, ignore_errors=True)

    def fill(self):
        """То, что человек нажил на первом устройстве."""
        collection_store.add_items([
            {"name": "Sol Ring", "quantity": 2, "set_code": "c21",
             "collector_number": "263", "finish": "nonfoil"},
            {"name": "Lightning Bolt", "quantity": 1, "set_code": "m10",
             "collector_number": "146", "finish": "foil"},
        ])
        deck_id = self.store.create_deck("Туманы", "pioneer", notes="держать 4 фога")
        self.store.add_card(deck_id, "Fog", 4, section="main", category="туманы")
        self.store.add_card(deck_id, "Root Snare", 2, section="side")
        # «Хочу купить» программа заводит сама -- в пустой базе она уже есть.
        folder = fav_store.load()["folders"][0]
        fav_store.add_card(folder["id"], "Sol Ring", 1)
        # А эту на той стороне придётся создать: без неё перенос папок не
        # проверен -- только пополнение существующей.
        made = fav_store.create_folder("Апгрейды")["folders"]
        upgrade = [f for f in made if f["name"] == "Апгрейды"][0]
        fav_store.add_card(upgrade["id"], "Fog", 2)
        return deck_id


class TestExport(TransferCase):
    def test_everything_is_there(self):
        self.fill()
        out = transfer.export_all(self.store)
        self.assertEqual(out["kind"], transfer.KIND)
        self.assertEqual(len(out["collection"]), 2)
        self.assertEqual(len(out["decks"]), 1)
        self.assertEqual(len(out["favourites"]), 2)
        self.assertEqual(out["summary"]["collection_copies"], 3)

    def test_printings_survive(self):
        """Печать — это то, ради чего коллекция ведётся по печатям."""
        self.fill()
        out = transfer.export_all(self.store)
        bolt = [r for r in out["collection"] if r["name"] == "Lightning Bolt"][0]
        self.assertEqual(bolt["set_code"], "m10")
        self.assertEqual(bolt["collector_number"], "146")
        self.assertEqual(bolt["finish"], "foil")

    def test_deck_keeps_its_shape(self):
        self.fill()
        deck = transfer.export_all(self.store)["decks"][0]
        self.assertEqual(deck["format"], "pioneer")
        self.assertEqual(deck["notes"], "держать 4 фога")
        side = [c for c in deck["cards"] if c["section"] == "side"]
        main = [c for c in deck["cards"] if c["section"] == "main"]
        self.assertEqual(len(side), 1)
        self.assertEqual(main[0]["category"], "туманы")

    def test_file_is_json_a_human_can_read(self):
        self.fill()
        body = json.dumps(transfer.export_all(self.store), ensure_ascii=False)
        self.assertIn("Туманы", body)
        self.assertIn("Sol Ring", body)


class TestRoundTrip(TransferCase):
    def test_empty_machine_gets_everything(self):
        """Главное: выгрузили здесь — получили то же самое там."""
        self.fill()
        letter = json.dumps(transfer.export_all(self.store), ensure_ascii=False)

        other = wipe()                      # «второе устройство»
        data = transfer.read_file(letter)
        transfer.import_all(data, other, mode="merge")

        got = collection_store.items()
        bolt = [r for r in got if r["name"] == "Lightning Bolt"]
        self.assertTrue(bolt, [r["name"] for r in got])
        self.assertEqual(bolt[0]["set_code"], "m10")
        self.assertEqual(bolt[0]["finish"], "foil")

        decks = other.list_decks()
        self.assertEqual([d["name"] for d in decks], ["Туманы"])
        cards = other.get_deck(decks[0]["id"])["cards"]
        self.assertEqual(sorted(c["name"] for c in cards),
                         ["Fog", "Root Snare"])
        folders = {f["name"]: f for f in fav_store.load()["folders"]}
        self.assertIn("Апгрейды", folders, list(folders))
        self.assertEqual([c["name"] for c in folders["Апгрейды"]["cards"]],
                         ["Fog"])
        self.assertEqual([c["name"] for c in folders["Хочу купить"]["cards"]],
                         ["Sol Ring"])

    def test_second_import_does_not_double_the_decks(self):
        """Файл принесли дважды — колод не должно стать две."""
        self.fill()
        letter = json.dumps(transfer.export_all(self.store), ensure_ascii=False)
        other = wipe()
        transfer.import_all(transfer.read_file(letter), other, mode="merge")
        transfer.import_all(transfer.read_file(letter), other, mode="merge")
        self.assertEqual(len(other.list_decks()), 1)


class TestMergeKeepsWhatIsThere(TransferCase):
    def test_existing_deck_is_left_alone(self):
        """«Добавить» не трогает колоду с тем же именем: её могли развивать."""
        self.fill()
        letter = json.dumps(transfer.export_all(self.store), ensure_ascii=False)

        other = wipe()
        mine = other.create_deck("Туманы", "modern")
        other.add_card(mine, "Opt", 4)

        result = transfer.import_all(transfer.read_file(letter), other,
                                     mode="merge")
        self.assertEqual(result["decks"]["skipped"], 1)
        cards = other.get_deck(mine)["cards"]
        self.assertEqual([c["name"] for c in cards], ["Opt"])

    def test_collection_adds_up(self):
        self.fill()
        letter = json.dumps(transfer.export_all(self.store), ensure_ascii=False)
        other = wipe()
        collection_store.add_items([
            {"name": "Sol Ring", "quantity": 1, "set_code": "c21",
             "collector_number": "263", "finish": "nonfoil"}])
        transfer.import_all(transfer.read_file(letter), other, mode="merge")
        rings = [r for r in collection_store.items()
                 if r["name"] == "Sol Ring" and r["set_code"] == "c21"]
        self.assertEqual(sum(r["count"] for r in rings), 3, rings)


class TestReplace(TransferCase):
    def test_replace_overwrites_the_named_deck(self):
        self.fill()
        letter = json.dumps(transfer.export_all(self.store), ensure_ascii=False)

        other = wipe()
        mine = other.create_deck("Туманы", "modern")
        other.add_card(mine, "Opt", 4)
        transfer.import_all(transfer.read_file(letter), other, mode="replace")

        decks = other.list_decks()
        self.assertEqual(len(decks), 1)
        cards = other.get_deck(decks[0]["id"])["cards"]
        self.assertEqual(sorted(c["name"] for c in cards),
                         ["Fog", "Root Snare"])

    def test_replace_leaves_decks_the_file_does_not_mention(self):
        """Заменять — только названное: чужую колоду трогать не за что."""
        self.fill()
        letter = json.dumps(transfer.export_all(self.store), ensure_ascii=False)
        other = wipe()
        keep = other.create_deck("Своя колода", "modern")
        other.add_card(keep, "Opt", 4)
        transfer.import_all(transfer.read_file(letter), other, mode="replace")
        names = sorted(d["name"] for d in other.list_decks())
        self.assertEqual(names, ["Своя колода", "Туманы"])


class TestBadFiles(TransferCase):
    def test_not_json(self):
        with self.assertRaises(transfer.TransferError):
            transfer.read_file("это не файл переноса")

    def test_someone_elses_json(self):
        with self.assertRaises(transfer.TransferError):
            transfer.read_file(json.dumps({"hello": "world"}))

    def test_future_format_is_refused(self):
        """Файл из будущей версии не надо угадывать."""
        with self.assertRaises(transfer.TransferError):
            transfer.read_file(json.dumps(
                {"kind": transfer.KIND, "format": transfer.FORMAT + 1}))

    def test_rubbish_inside_is_skipped_not_fatal(self):
        """Строка без имени — просто пропускается: файл мог собрать кто угодно."""
        data = transfer.read_file(json.dumps({
            "kind": transfer.KIND, "format": transfer.FORMAT,
            "collection": [{"name": "", "count": 3},
                           {"name": "Fog", "count": 0},
                           {"name": "Opt", "count": 2}],
            "decks": [{"name": "", "cards": []},
                      {"name": "Нормальная", "cards": [{"name": "", "quantity": 1}]}],
        }))
        self.assertEqual([r["name"] for r in data["collection"]], ["Opt"])
        self.assertEqual([d["name"] for d in data["decks"]], ["Нормальная"])
        self.assertEqual(data["decks"][0]["cards"], [])

    def test_unknown_mode(self):
        with self.assertRaises(transfer.TransferError):
            transfer.import_all({"collection": []}, self.store, mode="как-нибудь")


if __name__ == "__main__":
    unittest.main()

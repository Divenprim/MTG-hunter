"""Чем опознаётся архетип колоды и где этот выбор живёт.

Выборка чужих колод для 60-карточного формата ценна ровно настолько,
насколько она про вашу колоду. «Весь модерн» -- это бёрн, трон, эльфы и
8-Rack в одной куче: соседей у вашей колоды там горсть, и подсказки идут от
чужих архетипов. Поэтому колоду опознают её собственные карты.

Проверяется:

  * что предлагается отметить. Земли не предлагаются вовсе -- по ним
    опознаются цвета, а не колода; вперёд идут карты, которых в колоде
    больше и которые реже печатали (стейпл формата стоит в половине колод
    и поиск не сужает);
  * что выбор запоминается и его читают все, кто считает по выборке:
    предложка, добор у продавцов, покупки. Иначе человек видел бы
    подсказки по своему архетипу, а добор -- по всему формату;
  * что отказаться от выбора можно, и это не то же самое, что его не
    делать.

Данных пользователя тест не касается: MTGH_DATA_DIR уводит и базу, и
настройки в свой каталог.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="mtgh-sign-")

# Папка данных подменяется на время импорта, а потом возвращается как была.
# Проверки запускаются все вместе, и каждый файл выставляет MTGH_DATA_DIR
# себе при импорте: оставив свою, этот файл увёл бы чужие кеши в свой
# каталог -- ровно это и случилось с проверкой кеша EDHREC.
_PREV = os.environ.get("MTGH_DATA_DIR")
os.environ["MTGH_DATA_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from app import archidekt, main  # noqa: E402
from app.cards import DB_PATH  # noqa: E402

if _PREV is None:
    os.environ.pop("MTGH_DATA_DIR", None)
else:
    os.environ["MTGH_DATA_DIR"] = _PREV

DECK = [
    ("Thoughtseize", 4, "main"),
    ("The Rack", 4, "main"),
    ("Shrieking Affliction", 3, "main"),
    ("Swamp", 20, "main"),
    ("Urborg, Tomb of Yawgmoth", 2, "main"),
    ("Leyline of the Void", 2, "side"),
]


@unittest.skipUnless(os.path.exists(DB_PATH), "нужна база карт")
class TestSignature(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # На время своих проверок -- своя папка данных и свои настройки:
        # выбор карт архетипа пишется в settings.json, и писать его в
        # рабочую копию программы проверка не вправе.
        cls._prev_dir = os.environ.get("MTGH_DATA_DIR")
        cls._prev_settings = main.SETTINGS_PATH
        os.environ["MTGH_DATA_DIR"] = _TMP
        main.SETTINGS_PATH = os.path.join(_TMP, "settings.json")
        cls.client = TestClient(main.app)
        made = cls.client.post("/api/decks",
                               json={"name": "ТЕСТ архетип", "format": "modern"})
        cls.deck_id = made.json()["deck"]["id"]
        cls.client.post(
            "/api/decks/%s/cards" % cls.deck_id,
            json={"cards": [{"name": n, "quantity": q, "section": s}
                            for n, q, s in DECK]})

    @classmethod
    def tearDownClass(cls):
        cls.client.delete("/api/decks/%s" % cls.deck_id)
        main.SETTINGS_PATH = cls._prev_settings
        if cls._prev_dir is None:
            os.environ.pop("MTGH_DATA_DIR", None)
        else:
            os.environ["MTGH_DATA_DIR"] = cls._prev_dir

    def setUp(self):
        self.client.post("/api/cooccur/cards",
                         json={"deck_id": self.deck_id, "cards": []})

    def test_lands_are_not_offered_as_signature_cards(self):
        got = self.client.get(
            "/api/cooccur/signature?deck_id=%s" % self.deck_id).json()
        names = [c["name"] for c in got["cards"]]
        self.assertIn("Thoughtseize", names)
        self.assertNotIn("Swamp", names)
        self.assertNotIn("Urborg, Tomb of Yawgmoth", names)

    def test_the_most_played_and_least_reprinted_come_first(self):
        got = self.client.get(
            "/api/cooccur/signature?deck_id=%s" % self.deck_id).json()
        rows = got["cards"]
        self.assertEqual(rows[0]["qty"], 4)
        # Карта с тремя копиями не может стоять выше карты с четырьмя.
        self.assertTrue(all(rows[i]["qty"] >= rows[i + 1]["qty"]
                            for i in range(len(rows) - 1)))
        fours = [r for r in rows if r["qty"] == 4]
        self.assertTrue(all(fours[i]["reprints"] <= fours[i + 1]["reprints"]
                            for i in range(len(fours) - 1)))

    def test_the_format_is_named_and_marked_as_supported(self):
        got = self.client.get(
            "/api/cooccur/signature?deck_id=%s" % self.deck_id).json()
        self.assertTrue(got["supported"])
        self.assertEqual(got["format"], "modern")
        self.assertEqual(got["max"], archidekt.CARDS_MAX)

    def test_the_choice_is_remembered_and_used_by_the_sample(self):
        saved = self.client.post("/api/cooccur/cards", json={
            "deck_id": self.deck_id,
            "cards": ["Thoughtseize", "The Rack"]}).json()
        self.assertEqual(saved["key"], "cards:modern|The Rack|Thoughtseize")

        # Запрос без слова о картах -- берёт запомненное.
        state = self.client.get(
            "/api/cooccur/status?deck_id=%s" % self.deck_id).json()
        self.assertEqual(state["kind"], "cards")
        self.assertEqual(sorted(state["cards"]), ["The Rack", "Thoughtseize"])

        # И тот же выбор читают те, кто считает по выборке молча.
        self.assertEqual(main._saved_sample_cards(self.deck_id),
                         ["Thoughtseize", "The Rack"])

    def test_more_than_three_cards_are_cut(self):
        saved = self.client.post("/api/cooccur/cards", json={
            "deck_id": self.deck_id,
            "cards": ["Thoughtseize", "The Rack", "Shrieking Affliction",
                      "Bitterblossom"]}).json()
        self.assertEqual(len(saved["cards"]), archidekt.CARDS_MAX)

    def test_refusing_to_choose_is_not_the_same_as_not_having_chosen(self):
        self.client.post("/api/cooccur/cards", json={
            "deck_id": self.deck_id, "cards": ["Thoughtseize"]})
        # Пустой список в запросе -- это «по всему формату», и запомненный
        # выбор его не подменяет.
        state = self.client.get(
            "/api/cooccur/status?deck_id=%s&cards=" % self.deck_id).json()
        self.assertEqual(state["kind"], "format")
        # А запрос без параметра по-прежнему берёт выбор.
        state = self.client.get(
            "/api/cooccur/status?deck_id=%s" % self.deck_id).json()
        self.assertEqual(state["kind"], "cards")

    def test_a_russian_name_becomes_the_english_one_archidekt_knows(self):
        self.client.post("/api/cooccur/cards", json={
            "deck_id": self.deck_id, "cards": ["Уловить Мысль"]})
        state = self.client.get(
            "/api/cooccur/status?deck_id=%s" % self.deck_id).json()
        self.assertEqual(state["cards"], ["Thoughtseize"])

    def test_an_unknown_deck_is_a_404_not_an_empty_answer(self):
        self.assertEqual(
            self.client.get("/api/cooccur/signature?deck_id=нет").status_code,
            404)


@unittest.skipUnless(os.path.exists(DB_PATH), "нужна база карт")
class TestIllegalSuggestions(unittest.TestCase):
    """Чужой список написан не вчера, и в нём попадается забаненное."""

    def sections(self, *names):
        return {"sections": [{"cards": [{"name": n} for n in names]}]}

    def test_a_card_outside_the_pool_is_marked(self):
        data = self.sections("Mox Jet", "Lightning Bolt")
        main._mark_illegal(data, "modern")
        rows = {r["name"]: r for r in data["sections"][0]["cards"]}
        self.assertIn("не в пуле", rows["Mox Jet"]["illegal_label"])
        # Карта не прячется -- она остаётся в списке с пометкой.
        self.assertEqual(len(data["sections"][0]["cards"]), 2)
        self.assertNotIn("illegal", rows["Lightning Bolt"])

    def test_the_format_is_named_in_the_mark(self):
        data = self.sections("Mox Jet")
        main._mark_illegal(data, "pauper")
        self.assertIn("паупер",
                      data["sections"][0]["cards"][0]["illegal_label"].lower())

    def test_a_deck_without_a_known_format_is_left_alone(self):
        data = self.sections("Mox Jet")
        main._mark_illegal(data, "")
        self.assertNotIn("illegal", data["sections"][0]["cards"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)

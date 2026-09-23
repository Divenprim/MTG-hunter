"""Вариант колоды под другой формат.

Вопрос, ради которого это написано: «а можно тот же турбофог, но в пионере».
Ответ -- не «нельзя», а план: шесть карт заменить, лишние копии срезать, чему
замены не нашлось -- отложить, а не выбросить. И применяется этот план не к
исходной колоде, а к её ответвлению: два формата одного замысла -- это два
исполнения, которые дальше сравниваются в «Версиях».

Здесь проверяется сам план (app/formats.adapt) и его применение
(app.main._apply_adapt) на колоде в своём каталоге данных.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import formats, main  # noqa: E402
from app.decks import DeckStore  # noqa: E402

LEGAL_EVERYWHERE = {f: "legal" for f, _t, _s in formats.FORMATS}


def card(name, legal=None, **extra):
    c = {
        "name": name,
        "legalities": legal if legal is not None else dict(LEGAL_EVERYWHERE),
        "type_line": extra.pop("type_line", "Instant"),
        "color_identity": extra.pop("color_identity", "G"),
        "oracle_text": extra.pop("oracle_text", ""),
        "oracle_id": extra.pop("oracle_id", "id-" + name),
    }
    c.update(extra)
    return c


def row(name, quantity=1, section="main", legal=None, **extra):
    return {"name": name, "quantity": quantity, "section": section,
            "card": card(name, legal, **extra)}


class FakeDB:
    """База, которая на любой вопрос о заменах отвечает заранее известным.

    Настоящий подбор проверяется в test_formats.py; здесь важно не то, какую
    карту выберет движок, а то, что план собран правильно: одна замена на одну
    карту, дважды одна и та же не предлагается, а когда предложить нечего --
    карта уходит в «возможно».
    """

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def by_name(self, name):
        return card(name)


def fake_replacements(answers):
    def call(db, name, fmt, deck=None, limit=6):
        db.asked.append((name, fmt))
        return {"name": name, "format": fmt, "tags": ["fog"],
                "cards": answers.get(name, []),
                "note": "" if answers.get(name) else "нечем заменить"}
    return call


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.real = formats.replacements

    def tearDown(self):
        formats.replacements = self.real

    def plan(self, deck, fmt, answers):
        db = FakeDB(answers)
        formats.replacements = fake_replacements(answers)
        return formats.adapt(db, deck, fmt), db

    def test_card_out_of_pool_gets_a_replacement(self):
        deck = {"format": "modern", "cards": [
            row("Ethereal Haze", 4, legal={"modern": "legal", "pioneer": "not_legal"}),
        ]}
        plan, _db = self.plan(deck, "pioneer", {
            "Ethereal Haze": [{"name": "Haze of Pollen"}]})
        self.assertEqual(len(plan["swaps"]), 1)
        self.assertEqual(plan["swaps"][0]["to"]["name"], "Haze of Pollen")
        self.assertEqual(plan["swaps"][0]["quantity"], 4)
        self.assertEqual(plan["shelve"], [])
        self.assertFalse(plan["ready"])

    def test_the_same_replacement_is_never_offered_twice(self):
        """Иначе в колоде окажется восемь копий одной карты вместо двух разных."""
        deck = {"format": "modern", "cards": [
            row("A", 4, legal={"pioneer": "not_legal"}),
            row("B", 4, legal={"pioneer": "not_legal"}),
        ]}
        plan, _db = self.plan(deck, "pioneer", {
            "A": [{"name": "Same"}, {"name": "Other"}],
            "B": [{"name": "Same"}, {"name": "Other"}],
        })
        picked = [s["to"]["name"] for s in plan["swaps"]]
        self.assertEqual(sorted(picked), ["Other", "Same"])

    def test_a_card_already_in_the_deck_is_not_offered(self):
        deck = {"format": "modern", "cards": [
            row("A", 4, legal={"pioneer": "not_legal"}),
            row("Already Here", 2),
        ]}
        plan, _db = self.plan(deck, "pioneer", {
            "A": [{"name": "Already Here"}, {"name": "Fresh"}]})
        self.assertEqual(plan["swaps"][0]["to"]["name"], "Fresh")

    def test_nothing_to_swap_means_shelved_not_deleted(self):
        deck = {"format": "modern", "cards": [
            row("Weird Card", 2, legal={"pioneer": "banned"}),
        ]}
        plan, _db = self.plan(deck, "pioneer", {})
        self.assertEqual(plan["swaps"], [])
        self.assertEqual(len(plan["shelve"]), 1)
        self.assertEqual(plan["shelve"][0]["name"], "Weird Card")

    def test_singleton_format_trims_copies(self):
        deck = {"format": "modern", "cards": [row("Fog", 4)]}
        plan, _db = self.plan(deck, "commander", {})
        self.assertEqual([(t["name"], t["keep"]) for t in plan["trims"]],
                         [("Fog", 1)])

    def test_basic_lands_are_never_trimmed(self):
        deck = {"format": "modern", "cards": [
            row("Forest", 20, type_line="Basic Land — Forest"),
        ]}
        plan, _db = self.plan(deck, "commander", {})
        self.assertEqual(plan["trims"], [])

    def test_deck_size_is_reported_but_not_fixed(self):
        """Дописать двадцать карт за пользователя программа не должна."""
        deck = {"format": "modern", "cards": [row("Fog", 4)]}
        plan, _db = self.plan(deck, "modern", {})
        kinds = [r["kind"] for r in plan["shape"]]
        self.assertIn("size", kinds)

    def test_a_deck_that_already_fits_needs_no_plan(self):
        deck = {"format": "modern", "cards": [
            row("Fog %d" % i, 1) for i in range(60)]}
        plan, _db = self.plan(deck, "modern", {})
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["swaps"], [])
        self.assertEqual(plan["trims"], [])
        self.assertEqual(plan["shelve"], [])

    def test_sideboard_cards_are_part_of_the_plan(self):
        deck = {"format": "modern", "cards": [
            row("Side Thing", 2, section="side", legal={"pioneer": "not_legal"}),
        ]}
        plan, _db = self.plan(deck, "pioneer", {
            "Side Thing": [{"name": "Other Thing"}]})
        self.assertEqual(plan["swaps"][0]["section"], "side")


class TestApply(unittest.TestCase):
    """План, применённый к настоящей колоде.

    Колода живёт в своём файле во временном каталоге: ни личных колод, ни
    личных данных тест не касается. app.main._apply_adapt ходит в колоды через
    store(), поэтому на время теста store() и подменяется -- это честнее, чем
    переучивать модуль через переменные окружения.
    """

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        os.unlink(self.path)
        self.store = DeckStore(self.path)
        self.real_store = main.store
        main.store = lambda: self.store

    def tearDown(self):
        main.store = self.real_store
        try:
            self.store.conn.close()
        except Exception:  # noqa: BLE001
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass

    def test_swap_shelve_and_trim_land_in_the_deck(self):
        deck_id = self.store.create_deck("План", "modern")
        self.store.add_many(deck_id, [
            {"name": "Ethereal Haze", "quantity": 4, "section": "main"},
            {"name": "Weird Card", "quantity": 2, "section": "main"},
            {"name": "Fog", "quantity": 4, "section": "main"},
        ])
        plan = {
            "swaps": [{"name": "Ethereal Haze", "quantity": 4,
                       "to": {"name": "Haze of Pollen"}}],
            "shelve": [{"name": "Weird Card", "quantity": 2}],
            "trims": [{"name": "Fog", "quantity": 4, "keep": 1}],
        }
        main._apply_adapt(deck_id, plan)

        cards = {c["name"]: c for c in self.store.get_deck(deck_id)["cards"]}
        self.assertNotIn("Ethereal Haze", cards)
        self.assertEqual(cards["Haze of Pollen"]["quantity"], 4)
        self.assertEqual(cards["Haze of Pollen"]["section"], "main")
        # Отложенное не исчезает: оно в «возможно», откуда его видно и можно
        # вернуть.
        self.assertEqual(cards["Weird Card"]["section"], "maybe")
        self.assertEqual(cards["Fog"]["quantity"], 1)

    def test_the_source_deck_is_not_touched(self):
        """Вариант -- отдельная колода; исходную он менять не имеет права."""
        src = self.store.create_deck("Исходная", "modern")
        self.store.add_many(src, [{"name": "Ethereal Haze", "quantity": 4,
                                   "section": "main"}])
        branch = self.store.branch_deck(src, "Исходная — Пионер")
        main._apply_adapt(branch, {
            "swaps": [{"name": "Ethereal Haze", "quantity": 4,
                       "to": {"name": "Haze of Pollen"}}],
            "shelve": [], "trims": [],
        })
        before = {c["name"] for c in self.store.get_deck(src)["cards"]}
        after = {c["name"] for c in self.store.get_deck(branch)["cards"]}
        self.assertEqual(before, {"Ethereal Haze"})
        self.assertEqual(after, {"Haze of Pollen"})

    def test_both_executions_stay_in_one_family(self):
        src = self.store.create_deck("turbo fog", "modern")
        branch = self.store.branch_deck(src, "turbo fog — Пионер")
        decks = {d["id"]: d for d in self.store.list_decks()}
        self.assertEqual(decks[src].get("family"), decks[branch].get("family"))
        self.assertTrue(decks[branch].get("family"))


if __name__ == "__main__":
    unittest.main()

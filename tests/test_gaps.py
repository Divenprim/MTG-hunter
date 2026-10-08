"""Чего колоде не хватает: советовать надо то, что можно сыграть.

Разница между полезным списком и шумом здесь ровно одна -- учитывает ли совет
саму колоду. Колода с четырьмя Bomat Courier формально красная, потому что их
способность стоит {R}; предложить ей Worldfire за {6}{R}{R}{R} формально
правильно и практически бессмысленно -- одной горой его не разыграть никогда.

Поэтому здесь проверяется не «нашлось ли что-нибудь», а три вещи: предложение
влезает в цвета, предложение разыгрывается имеющимися источниками, и число
«у тебя столько-то» разворачивается в карты, с которыми можно не согласиться.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import gaps  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402


def deck(name, fmt, rows):
    """Колода в том виде, в каком её отдаёт хранилище."""
    db = CardDB()
    cards = []
    for card_name, quantity in rows:
        cards.append({"name": card_name, "quantity": quantity,
                      "section": "main", "card": db.by_name(card_name)})
    return {"name": name, "format": fmt, "cards": cards}


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestGaps(unittest.TestCase):

    COLOURLESS = [("Bomat Courier", 4), ("Kaldra Compleat", 4),
                  ("Urza's Tower", 4), ("Urza's Mine", 4),
                  ("Urza's Power Plant", 4), ("Gilded Lotus", 2),
                  ("Mountain", 1), ("Wastes", 16), ("Ornithopter", 4)]
    MONO_RED = [("Lightning Bolt", 4), ("Mountain", 24),
                ("Goblin Guide", 4), ("Monastery Swiftspear", 4)]

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def look(self, rows, fmt="modern"):
        return gaps.report(deck("UI", fmt, rows), self.db)

    # ------------------------------------------------- цвета колоды

    def test_one_stray_card_does_not_recolour_the_deck(self):
        """Одна забытая гора не делает бесцветный Трон красной колодой."""
        got = self.look([("Kaldra Compleat", 4), ("Wastes", 20),
                         ("Mountain", 1), ("Ornithopter", 4)])
        self.assertEqual(got["colors"], "бесцветная")
        self.assertTrue(any(c["name"] == "Mountain" for c in got["stray"]))

    def test_a_real_colour_is_a_colour(self):
        got = self.look(self.MONO_RED)
        self.assertIn("R", got["colors"])

    # --------------------------------------- предложения по колоде

    def test_suggestions_fit_the_deck_colours(self):
        got = self.look(self.COLOURLESS)
        for block in got["short"]:
            for card in block["candidates"]:
                with self.subTest(card=card["name"]):
                    self.assertNotIn("{R}", card.get("mana_cost") or "")
                    self.assertNotIn("{U}", card.get("mana_cost") or "")

    def test_a_card_the_deck_cannot_cast_is_not_offered(self):
        """Идентичность -- это не «можно сыграть».

        Колода красная из-за способности Bomat Courier, но красных источников
        в ней одна земля: предлагать ей заклинания с красными значками
        формально правильно и практически бессмысленно.
        """
        got = self.look(self.COLOURLESS)
        offered = [c["name"] for b in got["short"] for c in b["candidates"]]
        heavy = [n for n in offered
                 if "{R}" in (self.db.by_name(n) or {}).get("mana_cost", "")]
        self.assertEqual(heavy, [], "предложено неразыгрываемое: %s" % heavy[:3])

    def test_cards_already_in_the_deck_are_not_offered(self):
        got = self.look(self.COLOURLESS)
        offered = {c["name"] for b in got["short"] for c in b["candidates"]}
        self.assertNotIn("Kaldra Compleat", offered)

    # ------------------------------------------------ счёт с картами

    def test_every_count_shows_its_cards(self):
        """«У тебя пять карт добора» неоспоримо, пока не видно каких."""
        got = self.look(self.MONO_RED)
        blocks = got["short"] + got["enough"]
        self.assertTrue(blocks)
        for block in blocks:
            self.assertIn("counted", block)

    def test_the_thresholds_are_declared(self):
        said = " ".join(self.look(self.MONO_RED)["basis"])
        self.assertIn("порог наш", said)
        self.assertIn("заменитель популярности", said)

    # ------------------------- цветная мана, спрятанная в способности

    def test_colour_needed_by_an_ability_is_found(self):
        """Манабаза считает значки в стоимости и такого не видит."""
        got = self.look(self.COLOURLESS)
        found = [h for h in got["hidden_pips"] if h["name"] == "Bomat Courier"]
        self.assertTrue(found, got["hidden_pips"])
        self.assertEqual(found[0]["needs"], "R")
        self.assertEqual(found[0]["copies"], 4)

    def test_it_says_how_many_sources_and_which(self):
        got = self.look(self.COLOURLESS)
        found = [h for h in got["hidden_pips"] if h["name"] == "Bomat Courier"][0]
        self.assertGreater(len(found["from"]), 0)
        self.assertEqual(found["lands"], 1, "красная земля в колоде одна")

    def test_a_land_is_not_a_card_with_a_hidden_cost(self):
        """У земли нет стоимости розыгрыша -- её идентичность всегда «шире»."""
        got = self.look(self.COLOURLESS)
        self.assertNotIn("Mountain", [h["name"] for h in got["hidden_pips"]])

    # ---------------------------------------------------- крайности

    def test_an_empty_deck_does_not_explode(self):
        got = self.look([])
        self.assertEqual(got["cards"], 0)
        self.assertIsInstance(got["short"], list)


if __name__ == "__main__":
    unittest.main()

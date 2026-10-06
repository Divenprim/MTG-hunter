"""Такт победы: на каком ходу колода добивает, если ей не мешать.

Это голдфишинг, доведённый до конца, и опасен он ровно тем же, чем полезен:
число «убивает на пятом ходу» выглядит одинаково убедительно и когда посчитано,
и когда модель не поняла половину колоды. Поэтому главная проверка здесь — не
«похож ли ход на правду», а **покрытие**: модель обязана говорить, сколько карт
она вообще сумела оценить, и не выдавать молчание за ноль.

Вторая по важности — односторонность. Жетоны, лорды, экипировка, рампа и туторы
не учитываются, а все они ускоряют. Значит из такого счёта следует «быстро» и
не следует «медленно», и это должно быть написано под цифрами, а не
подразумеваться.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import winclock  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestClock(unittest.TestCase):

    BURN = [("Lightning Bolt", 4), ("Lava Spike", 4), ("Goblin Guide", 4),
            ("Monastery Swiftspear", 4), ("Mountain", 20)]
    CONTROL = [("Counterspell", 4), ("Swords to Plowshares", 4),
               ("Wrath of God", 3), ("Island", 25)]
    INFECT = [("Glistener Elf", 4), ("Blight Mamba", 4), ("Forest", 24)]

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def run_clock(self, rows, fmt="modern", **kw):
        kw.setdefault("seed", 1)
        kw.setdefault("games", 400)
        return winclock.clock(rows, self.db, fmt, **kw)

    # ------------------------------------------------------- покрытие

    def test_it_says_how_much_of_the_deck_it_understood(self):
        got = self.run_clock(self.BURN)
        self.assertEqual(got["coverage"]["pct"], 100.0, got["coverage"])

    def test_a_deck_it_cannot_read_is_admitted_not_zeroed(self):
        """Контроль не «не выигрывает» — про него модель ничего не знает."""
        got = self.run_clock(self.CONTROL, fmt="legacy")
        self.assertEqual(got["routes"]["damage"]["pct"], 0.0)
        self.assertEqual(got["coverage"]["modelled"], 0)
        self.assertGreater(got["coverage"]["nonland"], 0)
        self.assertEqual(got["coverage"]["pct"], 0.0)

    def test_a_creature_without_a_number_is_counted_as_unread(self):
        """У Tarmogoyf сила «*»: это не ноль, это «не знаю»."""
        got = self.run_clock([("Tarmogoyf", 4), ("Forest", 20)])
        self.assertEqual(got["coverage"]["unknown_power"], 4)
        self.assertEqual(got["coverage"]["modelled"], 0)

    def test_cards_outside_the_base_are_counted_as_unread(self):
        got = self.run_clock(self.BURN + [("Такой Карты Нет", 3)])
        self.assertEqual(got["coverage"]["unknown_card"], 3)

    # --------------------------------------------------------- такт

    def test_burn_kills_and_says_when(self):
        got = self.run_clock(self.BURN)
        route = got["routes"]["damage"]
        self.assertGreater(route["pct"], 90)
        self.assertLess(route["avg_turn"], 9)
        self.assertGreaterEqual(route["soonest"], 1)

    def test_the_threshold_follows_the_format(self):
        self.assertEqual(self.run_clock(self.BURN, fmt="modern")["life"], 20)
        self.assertEqual(self.run_clock(self.BURN, fmt="commander")["life"], 40)

    def test_more_opponents_need_more_damage(self):
        one = self.run_clock(self.BURN, opponents=1)
        three = self.run_clock(self.BURN, opponents=3)
        self.assertEqual(three["routes"]["damage"]["need"],
                         one["routes"]["damage"]["need"] * 3)
        self.assertLessEqual(three["routes"]["damage"]["pct"],
                             one["routes"]["damage"]["pct"])

    def test_haste_attacks_the_turn_it_lands(self):
        """Вызывная болезнь -- не мелочь: без неё такт считается не тот."""
        hasty = self.run_clock([("Goblin Guide", 20), ("Mountain", 20)])
        slow = self.run_clock([("Savannah Lions", 20), ("Plains", 20)])
        self.assertLess(hasty["routes"]["damage"]["avg_turn"],
                        slow["routes"]["damage"]["avg_turn"])

    def test_infect_goes_by_poison_not_damage(self):
        got = self.run_clock(self.INFECT)
        self.assertEqual(got["routes"]["poison"]["need"], winclock.POISON)
        self.assertGreater(got["routes"]["poison"]["pct"], 80)

    def test_the_fastest_route_is_the_sooner_of_the_two(self):
        got = self.run_clock(self.INFECT)
        poison = got["routes"]["poison"]["avg_turn"]
        self.assertIsNotNone(got["fastest"]["avg_turn"])
        self.assertLessEqual(got["fastest"]["avg_turn"], poison + 0.01)

    def test_the_same_seed_gives_the_same_answer(self):
        a = self.run_clock(self.BURN)
        b = self.run_clock(self.BURN)
        self.assertEqual(a["routes"]["damage"]["avg_turn"],
                         b["routes"]["damage"]["avg_turn"])

    def test_a_tiny_deck_is_refused_politely(self):
        got = self.run_clock([("Mountain", 3)])
        self.assertFalse(got["known"])
        self.assertIn("мало", got["why"])

    # ---------------------------------------------------- оговорки

    def test_both_caveats_are_printed(self):
        said = " ".join(self.run_clock(self.BURN)["assumptions"])
        self.assertIn("бездействуют", said)
        self.assertIn("не позже", said, "односторонность обязана быть названа")
        self.assertIn("медленнее", said, "про живых противников тоже")
        self.assertIn("жетоны", said)
        self.assertIn("милл", said, "о том, чего не считаем вовсе, надо сказать")


if __name__ == "__main__":
    unittest.main()

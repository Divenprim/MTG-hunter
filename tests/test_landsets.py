"""Наборы земель: то, что покупают и играют вместе.

Каталог собирается из данных -- циклы размечены тегами Scryfall, -- и проверять
надо именно это: что в наборе действительно земли, что цена за плейсет вчетверо
больше цены за комплект, и что отбор по формату честный (набор попадает в
выдачу, только если легальны все его карты, а не половина).
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import landsets, manabase  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestCatalogue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()
        cls.cat = landsets.catalogue(cls.db, "modern", limit=40)

    def test_there_are_sets_at_all(self):
        self.assertGreater(self.cat["total"], 20)
        self.assertTrue(self.cat["sets"])

    def test_every_set_is_made_of_lands(self):
        for s in self.cat["sets"]:
            for card in s["cards"]:
                found = self.db.by_name(card["name"])
                self.assertTrue(manabase.is_land(found),
                                "%s в наборе %s" % (card["name"], s["label"]))

    def test_a_playset_costs_four_times_a_single(self):
        for s in self.cat["sets"]:
            if s["unpriced"]:
                continue
            self.assertAlmostEqual(s["usd_playset"], s["usd_one"] * 4, places=1,
                                   msg=s["label"])

    def test_sets_are_named_for_people_not_machines(self):
        """«cycle-rav-shockland» -- имя для машины; человеку нужен вид и сет."""
        raw = [s for s in self.cat["sets"] if s["label"].startswith("cycle-")]
        self.assertEqual(raw, [], "остались сырые слаги: %s" %
                         [s["label"] for s in raw][:3])

    def test_the_kind_of_land_is_named_in_russian(self):
        """«napland · Champions of Kamigawa» -- слаг с пробелами, не название.

        Проверяются только циклы: у комбо-наборов подпись -- это имена карт,
        и они по-английски по делу.
        """
        cyrillic = re.compile("[а-яё]", re.I)
        wide = landsets.catalogue(self.db, "", limit=400)
        dumb = [s["label"] for s in wide["sets"]
                if s["kind"] == "cycle"
                and not cyrillic.search(s["label"].split(" · ")[0])]
        self.assertEqual(dumb, [], "виды земель без названия: %s" % dumb[:5])

    def test_only_sets_legal_as_a_whole_are_shown(self):
        for s in self.cat["sets"]:
            for card in s["cards"]:
                found = self.db.by_name(card["name"])
                self.assertEqual((found.get("legalities") or {}).get("modern"),
                                 "legal", "%s из %s" % (card["name"], s["label"]))

    def test_budget_cuts_by_the_playset_price(self):
        cheap = landsets.catalogue(self.db, "modern", budget=5.0, limit=40)
        for s in cheap["sets"]:
            self.assertLessEqual(s["usd_playset"], 5.0, s["label"])

    def test_only_open_drops_sets_with_taplands(self):
        fast = landsets.catalogue(self.db, "modern", only_open=True, limit=40)
        for s in fast["sets"]:
            self.assertEqual(s["entry"].get("tapped", 0), 0, s["label"])

    def test_order_by_price_really_sorts_by_price(self):
        cheap = landsets.catalogue(self.db, "modern", order="price", limit=10)
        prices = [s["usd_playset"] for s in cheap["sets"]]
        self.assertEqual(prices, sorted(prices))

    def test_the_handmade_sets_are_there_when_legal(self):
        """Urza's tron тегами не связан, но набором является."""
        found = landsets.catalogue(self.db, "modern", limit=200)
        names = {s["key"] for s in found["sets"]}
        self.assertIn("urza-tron", names)

    def test_a_set_knows_what_colors_it_covers(self):
        for s in self.cat["sets"]:
            if not s["fetch"]:
                continue
            # Набор из одних фетчей цветов не даёт -- и не должен их обещать.
            self.assertTrue(isinstance(s["colors"], str))


if __name__ == "__main__":
    unittest.main()

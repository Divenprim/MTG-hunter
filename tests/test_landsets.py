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
class FakeBase:
    """База ровно в том объёме, в каком её трогает имя набора."""

    def __init__(self, set_name: str):
        self.conn = self
        self._name = set_name

    def execute(self, sql, params=()):
        return self

    def fetchone(self):
        return {"set_name": self._name}


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

    def test_new_land_cycles_are_named_before_they_reach_the_user(self):
        """Виды земель из новых сетов -- отдельно и по имени.

        Проверка выше смотрит на собранную базу, а база на машине разработчика
        отстаёт от той, с которой собирается релиз: новый сет появляется
        сначала там. Поэтому сборка релиза падала на землях, которых здесь
        ещё нет, -- и увидеть это заранее было негде.

        Здесь названия спрашиваются напрямую, без базы: так новый цикл
        проверяется в тот же день, когда его добавили в справочник.
        """
        for tail, want in (("annex", "аннексы"),
                           ("commons", "общины"),
                           ("turbulent-land", "бурные земли")):
            self.assertEqual(landsets._kind_word(tail), want, tail)

    def test_no_machine_name_reaches_the_screen(self):
        """«napland · Champions of Kamigawa» -- слаг с пробелами, не название.

        Ловится именно это: машинное имя, вылезшее на экран. Английская
        подпись самого Tagger («storage land») -- не ошибка, а запасной
        путь, и падать из-за неё нельзя: метки заводят чужие люди, каждый
        новый сет приносит вид, которого у нас ещё нет.

        Дважды на этом спотыкалась сборка релиза: база, с которой она
        собирается, свежее здешней, и там находились виды «modal land», а
        потом «anomaly». Теперь неизвестный вид зовётся набором земель
        такого-то сета -- и релиз из-за чужой новой метки не встаёт.

        Проверяются только циклы: у комбо-наборов подпись -- это имена
        карт, и они по-английски по делу.
        """
        wide = landsets.catalogue(self.db, "", limit=400)
        dumb = [s["label"] for s in wide["sets"]
                if s["kind"] == "cycle" and s.get("named") == "slug"]
        self.assertEqual(dumb, [], "машинные имена на экране: %s" % dumb[:5])

    def test_an_unknown_kind_is_named_by_its_set(self):
        """Вида не знаем -- говорим то, что знаем, а не слаг.

        Проверяется напрямую, с поддельной базой: новый вид появляется
        сперва в той базе, с которой собирается релиз, а здешняя о нём
        ещё не знает -- и поймать это после сборки уже поздно.
        """
        label, source = landsets._nice_label(FakeBase("Star Trek"),
                                             "cycle-ltr-anomaly", 5)
        self.assertEqual(source, "set")
        self.assertEqual(label, "набор земель · Star Trek")

    def test_a_tagger_label_is_used_when_we_have_no_word(self):
        """Английская подпись метки лучше, чем «набор земель»: она хоть
        что-то говорит о виде."""
        label, source = landsets._nice_label(FakeBase("Star Trek"),
                                             "cycle-ltr-anomaly", 5,
                                             fallback="storage land")
        self.assertEqual(source, "tag")
        self.assertEqual(label, "storage land · Star Trek")

    def test_the_kinds_we_know_are_named_in_russian(self):
        """А те виды, что мы знаем, зовутся по-русски -- на том и стоим."""
        cyrillic = re.compile("[а-яё]", re.I)
        wide = landsets.catalogue(self.db, "", limit=400)
        ours = [s for s in wide["sets"]
                if s["kind"] == "cycle" and s.get("named") == "ru"]
        self.assertTrue(ours, "ни один вид земель не опознан")
        dumb = [s["label"] for s in ours
                if not cyrillic.search(s["label"].split(" · ")[0])]
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
        prices = [s["usd_playset"] for s in cheap["sets"]
                  if s["unpriced"] < len(s["cards"])]
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


class TestASetWithNoPriceAtAll(unittest.TestCase):
    """Набор, цены которого не знает никто, стоит не ноль, а неизвестно.

    Сборка релиза собирает базу карт заново, и в ней есть печати, которым
    Scryfall ещё не проставил цену. Такой набор выходил бесплатным: в
    порядке «польза за деньги» он делил пользу на единицу и вставал
    первым, а под бюджет «до пяти долларов» попадал любой ценой. Наверху
    списка оказывалось то, про что программа знает меньше всего.
    """

    def set(self, label, price, unpriced, size, quality=10.0):
        return {"label": label, "usd_one": price, "usd_playset": price * 4,
                "quality": quality, "unpriced": unpriced,
                "cards": [{"name": "%s-%d" % (label, i)} for i in range(size)]}

    def test_a_set_with_no_price_is_not_free(self):
        blind = self.set("неизвестный", 0.0, 3, 3)
        self.assertTrue(landsets._nothing_known_about_price(blind))

    def test_a_partly_priced_set_still_counts_as_priced(self):
        """Цена по двум картам из трёх -- заниженная, но это цена."""
        part = self.set("частичный", 1.0, 1, 3)
        self.assertFalse(landsets._nothing_known_about_price(part))

    def test_the_unpriced_set_goes_last_in_every_order(self):
        blind = self.set("неизвестный", 0.0, 3, 3, quality=12.0)
        cheap = self.set("дешёвый", 0.5, 0, 3, quality=6.0)
        good = self.set("хороший", 4.0, 0, 3, quality=11.0)
        for order in ("value", "price", "quality"):
            out = landsets.order_sets([blind, cheap, good], order)
            self.assertEqual(out[-1]["label"], "неизвестный", order)

    def test_the_cheapest_known_price_still_wins_by_price(self):
        blind = self.set("неизвестный", 0.0, 2, 2)
        cheap = self.set("дешёвый", 0.5, 0, 3)
        dear = self.set("дорогой", 9.0, 0, 3)
        out = landsets.order_sets([dear, blind, cheap], "price")
        self.assertEqual([s["label"] for s in out],
                         ["дешёвый", "дорогой", "неизвестный"])


if __name__ == "__main__":
    unittest.main()

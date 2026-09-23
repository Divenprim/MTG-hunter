"""Тесты проверки колоды по форматам.

Вопрос, ради которого это написано: «подойдёт ли модерновая колода в пионер».
Ответ должен различать две совершенно разные беды -- карта вне пула (её надо
менять) и форма колоды (59 карт вместо 60, это правится бесплатно), -- иначе
«не подходит» ничего не говорит.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import formats  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402


def row(name, quantity=1, section="main", legal=None, **card):
    """Строка колоды: имя, сколько копий и что про карту знает база."""
    c = {
        "name": name,
        "legalities": legal if legal is not None else {},
        "type_line": card.pop("type_line", "Creature — Human"),
        "color_identity": card.pop("color_identity", ""),
        "oracle_text": card.pop("oracle_text", ""),
    }
    c.update(card)
    return {"name": name, "quantity": quantity, "section": section, "card": c}


def deck(cards, fmt="modern"):
    return {"format": fmt, "cards": cards}


LEGAL_EVERYWHERE = {f: "legal" for f, _t, _s in formats.FORMATS}


def filler(n, **kw):
    """n карт, легальных везде: чтобы правило о размере не мешало смотреть
    на то, ради чего написан тест."""
    return [row("Filler %d" % i, 1, legal=dict(LEGAL_EVERYWHERE), **kw)
            for i in range(n)]


class TestCardPool(unittest.TestCase):
    def test_a_deck_of_legal_cards_fits(self):
        report = formats.check(deck(filler(60)), "modern")
        self.assertEqual(report["verdict"], "fits")
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["legal_copies"], 60)

    def test_a_card_outside_the_pool_is_a_blocker(self):
        cards = filler(59) + [row("Explore", 1, legal={"modern": "legal",
                                                       "pioneer": "not_legal"})]
        report = formats.check(deck(cards), "pioneer")
        self.assertEqual(report["verdict"], "no")
        self.assertEqual([b["name"] for b in report["blockers"]], ["Explore"])
        self.assertEqual(report["blockers"][0]["why"], "not_legal")

    def test_a_banned_card_says_banned_and_not_merely_missing(self):
        cards = filler(59) + [row("Mox Sapphire", 1, legal={"vintage": "restricted",
                                                            "legacy": "banned"})]
        report = formats.check(deck(cards), "legacy")
        self.assertEqual(report["blockers"][0]["why"], "banned")

    def test_a_restricted_card_is_fine_alone_and_not_in_pairs(self):
        one = filler(59) + [row("Black Lotus", 1, legal={"vintage": "restricted"})]
        self.assertEqual(formats.check(deck(one), "vintage")["blockers"], [])
        two = filler(58) + [row("Black Lotus", 2, legal={"vintage": "restricted"})]
        report = formats.check(deck(two), "vintage")
        self.assertEqual(report["blockers"][0]["why"], "restricted")

    def test_a_name_the_base_does_not_know_is_reported_as_such(self):
        cards = filler(59) + [{"name": "Азканта", "quantity": 1, "section": "main"}]
        report = formats.check(deck(cards), "modern")
        self.assertEqual(report["blockers"][0]["why"], "unknown")


class TestDeckShape(unittest.TestCase):
    """Форма колоды -- отдельная беда: она чинится без похода в магазин."""

    def test_a_short_deck_of_legal_cards_is_not_the_same_as_an_illegal_one(self):
        report = formats.check(deck(filler(59)), "modern")
        self.assertEqual(report["verdict"], "shape")
        self.assertEqual(report["blockers"], [])
        self.assertEqual([r["kind"] for r in report["rules"]], ["size"])

    def test_five_copies_are_too_many(self):
        cards = filler(56) + [row("Fog", 5, legal=dict(LEGAL_EVERYWHERE))]
        report = formats.check(deck(cards), "modern")
        self.assertIn("copies", [r["kind"] for r in report["rules"]])

    def test_basic_lands_are_not_counted_by_that_rule(self):
        cards = filler(36) + [row("Forest", 24, legal=dict(LEGAL_EVERYWHERE),
                                  type_line="Basic Land — Forest")]
        report = formats.check(deck(cards), "modern")
        self.assertEqual(report["rules"], [])

    def test_a_card_that_says_any_number_is_not_counted_either(self):
        cards = filler(30) + [row(
            "Relentless Rats", 30, legal=dict(LEGAL_EVERYWHERE),
            oracle_text="A deck can have any number of cards named Relentless Rats.")]
        report = formats.check(deck(cards), "modern")
        self.assertEqual(report["rules"], [])

    def test_a_big_sideboard_is_a_problem(self):
        cards = filler(60) + [row("Fog", 16, section="side",
                                  legal=dict(LEGAL_EVERYWHERE))]
        report = formats.check(deck(cards), "modern")
        self.assertIn("side", [r["kind"] for r in report["rules"]])


class TestCommander(unittest.TestCase):
    def test_singleton_and_size_are_checked(self):
        cards = [row("Tiamat", 1, section="commander", legal=dict(LEGAL_EVERYWHERE),
                     type_line="Legendary Creature — Dragon", color_identity="WUBRG")]
        cards += [row("Sol Ring", 2, legal=dict(LEGAL_EVERYWHERE))]
        report = formats.check(deck(cards, "commander"), "commander")
        kinds = [r["kind"] for r in report["rules"]]
        self.assertIn("size", kinds)
        self.assertIn("copies", kinds)

    def test_a_card_outside_the_colour_identity_is_a_blocker(self):
        cards = [row("Krenko", 1, section="commander", legal=dict(LEGAL_EVERYWHERE),
                     type_line="Legendary Creature — Goblin", color_identity="R")]
        cards += [row("Counterspell", 1, legal=dict(LEGAL_EVERYWHERE),
                      color_identity="U")]
        report = formats.check(deck(cards, "commander"), "commander")
        self.assertEqual([b["why"] for b in report["blockers"]], ["identity"])

    def test_a_missing_commander_is_a_rule_and_not_a_card(self):
        report = formats.check(deck(filler(100), "commander"), "commander")
        self.assertEqual(report["blockers"], [])
        self.assertIn("commander", [r["kind"] for r in report["rules"]])

    def test_a_commander_in_a_sixty_card_format_is_only_a_note(self):
        cards = filler(60) + [row("Tiamat", 1, section="commander",
                                  legal=dict(LEGAL_EVERYWHERE))]
        report = formats.check(deck(cards), "modern")
        self.assertEqual(report["blockers"], [])
        self.assertIn("commander", [r["kind"] for r in report["rules"]])


class TestSurvey(unittest.TestCase):
    def test_the_formats_it_plays_come_first(self):
        # Легальна везде, кроме стандарта: значит, «играет» почти всюду.
        legal = dict(LEGAL_EVERYWHERE)
        legal["standard"] = "not_legal"
        cards = [row("Filler %d" % i, 1, legal=dict(legal)) for i in range(60)]
        out = formats.survey(deck(cards))
        self.assertEqual(out["formats"][0]["verdict"], "fits")
        self.assertIn("modern", out["playable"])
        self.assertNotIn("standard", out["playable"])
        self.assertEqual(out["formats"][-1]["format"], "standard")

    def test_two_cards_short_of_a_format_counts_as_nearly(self):
        legal = dict(LEGAL_EVERYWHERE)
        cards = [row("Filler %d" % i, 1, legal=dict(legal)) for i in range(58)]
        bad = dict(LEGAL_EVERYWHERE)
        bad["pioneer"] = "not_legal"
        cards += [row("Explore", 2, legal=bad)]
        out = formats.survey(deck(cards))
        self.assertIn("pioneer", out["nearly"])


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestReplacements(unittest.TestCase):
    """Замены и тематика считаются по базе Scryfall: без неё проверять нечего."""

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def test_a_fog_is_replaced_by_other_fogs(self):
        out = formats.replacements(self.db, "Fog", "pioneer")
        names = [c["name"] for c in out["cards"]]
        self.assertTrue(names, out.get("note"))
        self.assertIn("fog", out["tags"])
        # Каждая замена обязана быть легальной в запрошенном формате.
        for name in names:
            card = self.db.by_name(name)
            self.assertEqual((card.get("legalities") or {}).get("pioneer"), "legal",
                             "%s не легальна в пионере" % name)

    def test_a_card_already_in_the_deck_is_not_suggested(self):
        cards = [row("Fog", 4), {"name": "Haze of Pollen", "quantity": 4,
                                 "section": "main",
                                 "card": {"name": "Haze of Pollen",
                                          "color_identity": "G"}}]
        out = formats.replacements(self.db, "Fog", "pioneer", deck(cards))
        self.assertNotIn("Haze of Pollen", [c["name"] for c in out["cards"]])

    def test_the_theme_is_what_the_deck_repeats(self):
        cards = [{"name": "Fog", "quantity": 4, "section": "main",
                  "card": self.db.by_name("Fog")},
                 {"name": "Cultivate", "quantity": 4, "section": "main",
                  "card": self.db.by_name("Cultivate")}]
        out = formats.theme(self.db, deck(cards, "pioneer"), "pioneer")
        slugs = [t["slug"] for t in out["themes"]]
        self.assertIn("fog", slugs)
        self.assertTrue(out["add"])
        # Тематика не предлагает того, что уже стоит в колоде.
        self.assertNotIn("Cultivate", [c["name"] for c in out["add"]])

    def test_a_card_the_base_does_not_know_says_so(self):
        out = formats.replacements(self.db, "Азканта", "modern")
        self.assertEqual(out["cards"], [])
        self.assertTrue(out["note"])


class TestSingleCardLegality(unittest.TestCase):
    """Легальность одной карты: её спрашивает подборщик комбо.

    Комбо из четырёх карт, одна из которых вне пула формата колоды, собрать
    нельзя, и узнать об этом надо в окне комбо, а не в магазине.
    """

    def test_legal_banned_and_out_of_pool_are_told_apart(self):
        card = {"legalities": {"modern": "legal", "pioneer": "not_legal",
                               "legacy": "banned", "vintage": "restricted"}}
        self.assertEqual(formats.legality(card, "modern"), "legal")
        self.assertEqual(formats.legality(card, "pioneer"), "not_legal")
        self.assertEqual(formats.legality(card, "legacy"), "banned")
        self.assertEqual(formats.legality(card, "vintage"), "restricted")

    def test_unknown_card_is_not_called_legal(self):
        self.assertEqual(formats.legality(None, "modern"), "not_legal")

    def test_legalities_stored_as_json_text_still_work(self):
        """База отдаёт легальности строкой JSON, если карту не разбирали."""
        card = {"legalities": '{"modern": "legal"}'}
        self.assertEqual(formats.legality(card, "modern"), "legal")


if __name__ == "__main__":
    unittest.main()

"""Манабаза: что земля умеет, сколько источников нужно и чем добить.

Проверяется то, на чём эта часть программы может тихо соврать:

  * что земля производит. Читается из текста, и текст бывает разный:
    «Add {U} or {R}», «Add {W}, {U}, or {B}», «Add one mana of any color»;
  * как она входит. Шоковая земля входит развёрнутой за две жизни -- считать
    её тапландом неправда, обещать развёрнутость тоже;
  * настоящий ли это источник. «{1}, {T}: Add one mana of any color» -- не
    источник пяти цветов, а размен одной маны на другую, и в подсчёт он идти
    не должен: именно на этом список кандидатов однажды возглавили
    двадцатицентовые фильтры;
  * сколько источников нужно. Требование колоды -- по самой требовательной
    карте цвета, а не по средней.

Без собранной базы карт проверять нечего -- тогда тесты пропускаются.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import manabase as mb  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402


class TestPips(unittest.TestCase):
    def test_colored_pips_are_counted(self):
        self.assertEqual(mb.pips("{1}{U}{U}{U}"), {"U": 3})

    def test_generic_mana_is_not_a_pip(self):
        self.assertEqual(mb.pips("{5}"), {})

    def test_hybrid_counts_for_both_colors(self):
        """Гибрид можно заплатить любым из двух -- источником годится любой."""
        self.assertEqual(mb.pips("{W/U}"), {"W": 1, "U": 1})


class TestKarsten(unittest.TestCase):
    def test_one_pip_on_turn_one_needs_fourteen(self):
        self.assertEqual(mb.needed_sources(1, 1), 14)

    def test_two_pips_on_turn_two_need_more(self):
        self.assertGreater(mb.needed_sources(2, 2), mb.needed_sources(1, 2))

    def test_later_turns_need_fewer(self):
        self.assertLess(mb.needed_sources(1, 5), mb.needed_sources(1, 1))

    def test_a_bigger_library_needs_proportionally_more(self):
        self.assertGreater(mb.needed_sources(1, 1, 99), mb.needed_sources(1, 1, 60))


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestLandReading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def card(self, name):
        found = self.db.by_name(name)
        self.assertIsNotNone(found, name)
        return found

    def test_a_dual_gives_both_colors(self):
        self.assertEqual(mb.produces(self.card("Steam Vents")), "UR")

    def test_a_triome_gives_all_three(self):
        """Текст с запятыми -- «Add {W}, {U}, or {B}» -- читается целиком."""
        self.assertEqual(mb.produces(self.card("Raffine's Tower")), "WUB")

    def test_any_color_means_all_five(self):
        self.assertEqual(mb.produces(self.card("Gateway Plaza")), "WUBRG")

    def test_a_basic_gives_its_own_color(self):
        self.assertEqual(mb.produces(self.card("Forest")), "G")

    def test_a_shockland_enters_by_choice(self):
        self.assertEqual(mb.entry(self.card("Steam Vents")), "maybe")

    def test_a_triome_always_enters_tapped(self):
        self.assertEqual(mb.entry(self.card("Raffine's Tower")), "tapped")

    def test_a_basic_enters_untapped(self):
        self.assertEqual(mb.entry(self.card("Forest")), "open")

    def test_a_fetch_gives_no_mana_of_its_own(self):
        self.assertTrue(mb.fetches(self.card("Flooded Strand")))
        self.assertEqual(mb.produces(self.card("Flooded Strand")), "")

    def test_a_real_dual_is_a_real_source(self):
        for name in ("Steam Vents", "Breeding Pool", "Botanical Sanctum",
                     "Yavimaya Coast", "Azorius Guildgate"):
            self.assertEqual(mb.reliability(self.card(name), "modern"), "direct",
                             name)

    def test_a_land_that_charges_for_color_is_not_a_source(self):
        """«{1}, {T}: Add one mana of any color» -- это размен, а не источник."""
        for name in ("Shimmering Grotto", "Aether Hub", "Holdout Settlement"):
            self.assertEqual(mb.reliability(self.card(name), "modern"), "costly",
                             name)

    def test_color_that_depends_on_the_opponent_is_not_counted(self):
        self.assertEqual(mb.reliability(self.card("Exotic Orchard"), "modern"),
                         "theirs")

    def test_commander_only_land_is_limited_elsewhere(self):
        """Command Tower вне командирских форматов не даёт ничего."""
        card = self.card("Command Tower")
        self.assertEqual(mb.reliability(card, "modern"), "limited")
        self.assertEqual(mb.reliability(card, "commander"), "direct")

    def test_a_double_faced_card_whose_back_is_a_land_is_not_a_land(self):
        card = self.db.by_name("Treasure Map // Treasure Cove")
        if card:
            self.assertFalse(mb.is_land(card))


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def deck(self, names, fmt="modern"):
        rows = []
        for name, qty in names:
            rows.append({"name": name, "quantity": qty, "section": "main",
                         "card": self.db.by_name(name)})
        return {"format": fmt, "cards": rows}

    def test_sources_are_counted_per_color(self):
        deck = self.deck([("Island", 10), ("Steam Vents", 4),
                          ("Counterspell", 4)])
        rep = mb.report(self.db, deck)
        blue = [c for c in rep["colors"] if c["color"] == "U"][0]
        self.assertEqual(blue["have"], 14)

    def test_the_most_demanding_card_sets_the_need(self):
        """Одна карта с тремя значками требует больше, чем десять с одним."""
        deck = self.deck([("Island", 12), ("Opt", 10), ("Cryptic Command", 1)])
        rep = mb.report(self.db, deck)
        blue = [c for c in rep["colors"] if c["color"] == "U"][0]
        self.assertEqual(blue["worst"]["name"], "Cryptic Command")
        self.assertGreater(blue["need"], 20)

    def test_a_split_card_is_counted_by_its_front_half(self):
        """Иначе «{2}{W}{W} // {3}{W}{W}» требует четырёх значков вместо двух."""
        card = self.db.by_name("Dusk // Dawn")
        if not card:
            self.skipTest("нет такой карты в базе")
        deck = self.deck([("Plains", 20), ("Dusk // Dawn", 1)])
        rep = mb.report(self.db, deck)
        white = [c for c in rep["colors"] if c["color"] == "W"][0]
        self.assertEqual(white["worst"]["pips"], 2)

    def test_entry_is_summed_up(self):
        deck = self.deck([("Forest", 8), ("Raffine's Tower", 4),
                          ("Steam Vents", 4)])
        rep = mb.report(self.db, deck)
        self.assertEqual(rep["entry"]["open"], 8)
        self.assertEqual(rep["entry"]["tapped"], 4)
        self.assertEqual(rep["entry"]["maybe"], 4)


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestLandPlan(unittest.TestCase):
    """Колоды, где земли -- не обслуга, а замысел.

    Турбофог выигрывает десятью Вратами: советовать ему «поменяйте тапленды на
    удобные двойные» значит предлагать разобрать колоду. Поэтому сперва
    спрашивается, не держится ли на землях победа.
    """

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def deck(self, names, fmt="modern"):
        return {"format": fmt, "cards": [
            {"name": n, "quantity": q, "section": "main",
             "card": self.db.by_name(n)} for n, q in names]}

    def gates(self):
        names = [("Maze's End", 4), ("Fog", 4)]
        for gate in ("Azorius Guildgate", "Boros Guildgate", "Dimir Guildgate",
                     "Golgari Guildgate", "Gruul Guildgate", "Izzet Guildgate",
                     "Orzhov Guildgate", "Rakdos Guildgate", "Selesnya Guildgate",
                     "Simic Guildgate"):
            names.append((gate, 1))
        return self.deck(names)

    def test_a_deck_that_wins_with_lands_says_so(self):
        plan = mb.land_plan(self.db, self.gates())[0]
        self.assertEqual(plan["card"], "Maze's End")
        self.assertEqual(plan["what"], "Gate")
        self.assertEqual(plan["need"], 10)
        self.assertTrue(plan["distinct"])
        self.assertTrue(plan["wins"])

    def test_it_counts_names_not_copies_when_names_must_differ(self):
        """Одиннадцатая копия тех же Врат план не двигает."""
        doubled = self.gates()
        for row in doubled["cards"]:
            if "Guildgate" in row["name"]:
                row["quantity"] = 2
        plan = mb.land_plan(self.db, doubled)[0]
        self.assertEqual(plan["have"], 10)

    def test_an_unassembled_plan_is_not_called_assembled(self):
        few = self.deck([("Maze's End", 4), ("Azorius Guildgate", 4),
                         ("Boros Guildgate", 4)])
        plan = mb.land_plan(self.db, few)[0]
        self.assertEqual(plan["have"], 2)
        self.assertFalse(plan["ok"])

    def test_lands_with_different_names_is_a_plan_too(self):
        deck = self.deck([("Field of the Dead", 4), ("Island", 6),
                          ("Mountain", 6), ("Forest", 6)])
        plan = mb.land_plan(self.db, deck)[0]
        self.assertEqual(plan["what"], "land")
        self.assertEqual(plan["need"], 7)
        self.assertTrue(plan["distinct"])

    def test_a_subtype_counted_without_distinct_names_counts_copies(self):
        deck = self.deck([("Valakut, the Molten Pinnacle", 4), ("Mountain", 12)])
        plan = mb.land_plan(self.db, deck)[0]
        self.assertEqual(plan["what"], "Mountain")
        self.assertEqual(plan["need"], 5)
        self.assertFalse(plan["distinct"])
        self.assertEqual(plan["have"], 12)

    def test_lands_that_work_only_together_are_a_plan(self):
        deck = self.deck([("Urza's Mine", 4), ("Urza's Power Plant", 4),
                          ("Urza's Tower", 4)])
        kinds = [p["kind"] for p in mb.land_plan(self.db, deck)]
        self.assertIn("pair", kinds)

    def test_an_ordinary_deck_has_no_such_plan(self):
        deck = self.deck([("Island", 8), ("Mountain", 8),
                          ("Cryptic Command", 4), ("Lightning Bolt", 4)])
        self.assertEqual(mb.land_plan(self.db, deck), [])

    def test_the_payoff_land_takes_a_slot_too(self):
        """Четыре Maze's End играются ради плана, а не ради маны."""
        deck = self.gates()
        plans = mb.land_plan(self.db, deck)
        self.assertEqual(mb.plan_lands(plans, self.db, deck), 14)

    def test_the_report_says_how_many_slots_are_left_for_colors(self):
        rep = mb.report(self.db, self.gates())
        self.assertEqual(rep["plan_lands"], 14)
        self.assertEqual(rep["free_lands"], rep["lands"] - 14)

    def test_suggestions_that_do_not_break_the_plan_are_real_gates(self):
        """«Mystic Gate» -- не Врата: Maze's End её не считает."""
        out = mb.candidates(self.db, self.gates(), "modern", budget=5.0)
        self.assertEqual(out["plan_what"], "Gate")
        for land in out["plan"]:
            card = self.db.by_name(land["name"])
            self.assertIn("Gate", (card.get("type_line") or "").split("—")[-1],
                          land["name"])

    def test_a_gate_already_in_the_deck_is_not_suggested_again(self):
        out = mb.candidates(self.db, self.gates(), "modern", budget=5.0)
        names = {land["name"] for land in out["plan"]}
        self.assertNotIn("Azorius Guildgate", names)


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def deck(self):
        rows = [{"name": n, "quantity": q, "section": "main",
                 "card": self.db.by_name(n)}
                for n, q in (("Island", 8), ("Mountain", 8),
                             ("Cryptic Command", 4), ("Lightning Bolt", 4))]
        return {"format": "modern", "cards": rows}

    def test_duals_and_any_color_lands_are_kept_apart(self):
        """Пятицветная земля по числу источников бьёт любую двойную, а играют
        их по-разному: сравнивать их одним списком -- обманывать себя."""
        out = mb.candidates(self.db, self.deck(), "modern", budget=5.0)
        for land in out["duals"]:
            colored = [c for c in land["produces"] if c in mb.COLORS]
            self.assertLessEqual(len(colored), 3, land["name"])
        for land in out["anycolor"]:
            colored = [c for c in land["produces"] if c in mb.COLORS]
            self.assertGreaterEqual(len(colored), 4, land["name"])

    def test_budget_is_respected(self):
        out = mb.candidates(self.db, self.deck(), "modern", budget=0.5)
        for land in out["duals"]:
            if land["usd"] is not None:
                self.assertLessEqual(land["usd"], 0.5, land["name"])

    def test_only_open_drops_taplands(self):
        out = mb.candidates(self.db, self.deck(), "modern", budget=5.0,
                            only_open=True)
        for land in out["duals"]:
            self.assertEqual(land["entry"], "open", land["name"])

    def test_costly_lands_are_shown_but_not_counted(self):
        out = mb.candidates(self.db, self.deck(), "modern", budget=5.0)
        names = {land["name"] for land in out["duals"] + out["anycolor"]}
        self.assertNotIn("Shimmering Grotto", names)
        self.assertTrue(out["costly"])

    def test_fetches_go_to_their_own_group(self):
        out = mb.candidates(self.db, self.deck(), "modern", budget=5.0)
        for land in out["fetch"]:
            self.assertEqual(land["produces"], "", land["name"])


if __name__ == "__main__":
    unittest.main()

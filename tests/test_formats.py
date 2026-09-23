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

    # --- что именно карта делает, и кто это делает так же ------------------ #

    def test_a_rare_tag_beats_several_common_ones(self):
        """Isochron Scepter -- это imprint, а не «двухманный артефакт».

        Пока редкий тег весил столько же, сколько частый, в ответ приходили
        случайные двухманные артефакты, совпавшие по трём тегам «ни о чём»:
        карта, которая делает то же самое (Elite Arcanist), оказывалась
        седьмой. Она должна быть первой.
        """
        out = formats.replacements(self.db, "Isochron Scepter", "pioneer")
        names = [c["name"] for c in out["cards"]]
        self.assertTrue(names, out.get("note"))
        self.assertEqual(names[0], "Elite Arcanist", "; ".join(names))

    def test_the_defining_tag_is_first_among_the_jobs(self):
        out = formats.replacements(self.db, "Isochron Scepter", "pioneer")
        jobs = [j["slug"] for j in out["jobs"]]
        self.assertEqual(jobs[0], "imprint", "; ".join(jobs))
        # И сказано, сколько таких карт в пуле формата: «нет ни одной карты с
        # imprint в пионере» -- проверяемое утверждение, а не отговорка.
        imprint = [j for j in out["jobs"] if j["slug"] == "imprint"][0]
        self.assertGreater(imprint["in_pool"], 0)

    def test_a_replacement_says_what_it_does_not_do(self):
        """Blessed Respite -- это туман И возврат кладбища в библиотеку."""
        out = formats.replacements(self.db, "Blessed Respite", "pioneer")
        jobs = {j["slug"] for j in out["jobs"]}
        self.assertIn("fog", jobs)
        self.assertIn("restock-all", jobs)

        fogs = [c for c in out["cards"] if c["name"] in
                ("Fog", "Root Snare", "Haze of Pollen")]
        self.assertTrue(fogs, [c["name"] for c in out["cards"]])
        missed = {m["slug"] for m in fogs[0]["misses"]}
        self.assertIn("restock-all", missed)
        self.assertFalse(fogs[0]["full"])

    def test_a_full_match_is_marked_as_one(self):
        out = formats.replacements(self.db, "Fog", "pioneer")
        best = out["cards"][0]
        self.assertTrue(best["full"], best["name"])
        self.assertEqual(best["misses"], [])
        self.assertEqual(best["coverage"], 1.0)

    def test_cosmetic_tags_are_not_treated_as_purpose(self):
        """«Имя из трёх букв» -- это про имя, а не про то, что карта делает."""
        out = formats.replacements(self.db, "Fog", "pioneer")
        slugs = {j["slug"] for j in out["jobs"]}
        self.assertNotIn("three-letter-name", slugs)
        self.assertIn("fog", slugs)

    def test_a_meme_is_not_a_purpose_either(self):
        out = formats.replacements(self.db, "Lightning Bolt", "pioneer")
        self.assertNotIn("meme", {j["slug"] for j in out["jobs"]})

    # --- отбор по назначению и длина списка -------------------------------- #

    def test_asking_for_a_tag_keeps_only_cards_that_have_it(self):
        """«Покажи только те, что умеют imprint» -- 45 карт вместо шести лучших."""
        out = formats.replacements(self.db, "Isochron Scepter", "pioneer",
                                   limit=50, require=["imprint"])
        self.assertTrue(out["cards"])
        self.assertEqual(out["require"], ["imprint"])
        for card in out["cards"]:
            self.assertNotIn("imprint", [m["slug"] for m in card["misses"]],
                             card["name"])

    def test_two_tags_at_once_narrow_it_further(self):
        one = formats.replacements(self.db, "Isochron Scepter", "pioneer",
                                   limit=50, require=["imprint"])
        two = formats.replacements(self.db, "Isochron Scepter", "pioneer",
                                   limit=50, require=["imprint", "copy-instant"])
        self.assertLess(two["total"], one["total"])
        self.assertIn("Elite Arcanist", [c["name"] for c in two["cards"]])

    def test_an_impossible_pair_says_so_instead_of_lying(self):
        """Туман, который ещё и мешивает кладбище, в пионере один -- и он вне пула."""
        out = formats.replacements(self.db, "Blessed Respite", "pioneer",
                                   limit=20, require=["fog", "restock-all"])
        self.assertEqual(out["cards"], [])
        self.assertEqual(out["total"], 0)
        self.assertTrue(out["note"])

    def test_a_tag_the_card_does_not_have_is_ignored(self):
        """Кнопки -- это назначения самой карты; чужого требовать нечего."""
        out = formats.replacements(self.db, "Fog", "pioneer",
                                   require=["imprint"])
        self.assertEqual(out["require"], [])
        self.assertTrue(out["cards"])

    def test_the_list_grows_when_asked(self):
        six = formats.replacements(self.db, "Fog", "pioneer", limit=6)
        more = formats.replacements(self.db, "Fog", "pioneer", limit=20)
        self.assertEqual(len(six["cards"]), 6)
        self.assertGreater(len(more["cards"]), len(six["cards"]))
        # Сколько всего нашлось -- одно и то же число, сколько ни показывай.
        self.assertEqual(six["total"], more["total"])

    def test_generic_tags_stay_out_of_the_report(self):
        """В счёте они участвуют, в строке «не делает» -- нет: это шум."""
        out = formats.replacements(self.db, "Blessed Respite", "pioneer")
        for card in out["cards"]:
            for job in card["misses"] + card["covers"]:
                self.assertLessEqual(job["cards"], formats.DEFINING_TAG_CARDS,
                                     job["slug"])


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestWinCondition(unittest.TestCase):
    """Чем колода выигрывает -- и переживёт ли это переделку под другой формат.

    Турбофог выигрывает не туманами: туманы не дают проиграть, а выигрывает
    Maze's End. В пионере эта карта есть, и переделка осмысленна -- дороже, но
    та же колода. В паупере её нет, и нет ни одной карты, которой можно
    выиграть так же: там это уже другая колода, и сказать об этом надо прямо,
    а не молча подставить «похожие ворота».
    """

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def deck(self, names, fmt="modern"):
        rows = []
        for name, qty in names:
            rows.append({"name": name, "quantity": qty, "section": "main",
                         "card": self.db.by_name(name)})
        return {"format": fmt, "cards": rows}

    def gates(self):
        return self.deck([
            ("Maze's End", 4), ("Plaza of Harmony", 4), ("Azorius Guildgate", 4),
            ("Boros Guildgate", 4), ("Dimir Guildgate", 4), ("Fog", 4),
            ("Arboreal Grazer", 4), ("Growth Spiral", 4),
        ])

    def test_the_card_that_wins_is_named(self):
        win = formats.win_plan(self.db, self.gates())
        self.assertEqual(win["kind"], "alt")
        # win["cards"] -- имена карт-победителей, строками.
        self.assertIn("Maze's End", win["cards"])

    def test_a_deck_with_no_way_to_win_says_so(self):
        """И это само по себе ответ: такую колоду переделка не сломает."""
        win = formats.win_plan(self.db, self.deck([("Fog", 4), ("Island", 20)]))
        self.assertEqual(win["kind"], "none")

    def test_walls_are_not_attackers(self):
        """Arboreal Grazer -- 0/3: подсказка «дайте ему +X/+X» победой не станет."""
        win = formats.win_plan(self.db, self.deck([("Arboreal Grazer", 4)]))
        self.assertEqual(win["attackers"], 0)

    def test_creatures_that_can_attack_are_counted(self):
        win = formats.win_plan(self.db, self.deck([("Hugs, Grisly Guardian", 4)]))
        self.assertEqual(win["attackers"], 4)

    def test_a_format_that_keeps_the_win_is_called_that(self):
        plan = formats.adapt(self.db, self.gates(), "pioneer")
        self.assertEqual(plan["intent"], "keeps", plan["said"])

    def test_the_ways_to_win_are_counted_not_guessed(self):
        """Каждый способ -- числом: так видно, чем колода занята на самом деле."""
        routes = {r["kind"]: r for r in formats.win_routes(self.db, self.gates())}
        self.assertIn("alt", routes)
        self.assertEqual(routes["alt"]["strength"], 4)
        # Стены силы не дают, поэтому бой в турбофоге способом не считается.
        self.assertFalse(routes.get("combat", {"real": False})["real"])

    def test_a_beatdown_deck_is_read_as_combat(self):
        deck = self.deck([("Hugs, Grisly Guardian", 4), ("Forest", 20)])
        win = formats.win_plan(self.db, deck)
        self.assertEqual(win["kind"], "combat")
        self.assertEqual(win["power"], 20)

    def test_what_the_deck_becomes_is_really_computed(self):
        """Вердикт следует из колоды «после», а не из признака одной карты."""
        gates = self.gates()
        plan = formats.adapt(self.db, gates, "pauper")
        after = formats.after_deck(self.db, gates, plan)
        names = {row["name"] for row in after["cards"]}
        self.assertNotIn("Maze's End", names)
        # Замены встают в том же количестве, а отложенное уходит целиком:
        # значит, карт становится ровно на отложенное меньше.
        shelved = sum(r["quantity"] for r in plan["shelve"])
        self.assertEqual(
            sum(r["quantity"] for r in after["cards"]) + shelved,
            sum(r["quantity"] for r in gates["cards"]))

    def test_a_format_without_that_win_says_what_is_lost(self):
        plan = formats.adapt(self.db, self.gates(), "pauper")
        self.assertIn(plan["intent"], ("lost", "changes"), plan["said"])
        self.assertIn("карта-победитель", plan["said"])
        self.assertIn("не остаётся ничего", plan["said"])

    def test_a_deck_that_loses_everything_is_told_to_start_over(self):
        """Когда не остаётся ни одного способа -- переделывать нечего."""
        deck = self.deck([("Maze's End", 4), ("Azorius Guildgate", 20),
                          ("Fog", 8)])
        plan = formats.adapt(self.db, deck, "pauper")
        if plan["intent"] == "lost":
            self.assertIn("с нуля", plan["said"])
        else:
            # Либо взамен появился другой способ -- и тогда так и сказано.
            self.assertIn("Взамен появляется", plan["said"])

    def test_the_lost_card_is_shelved_with_the_reason(self):
        plan = formats.adapt(self.db, self.gates(), "pauper")
        maze = [r for r in plan["shelve"] if r["name"] == "Maze's End"]
        self.assertTrue(maze, [r["name"] for r in plan["shelve"]])
        self.assertIn("выиграть так же", maze[0]["note"])

    def test_a_replacement_that_drops_the_deck_theme_is_marked_weak(self):
        """Колода собрана на воротах: замена без ворот -- заплатка, а не замена."""
        plan = formats.adapt(self.db, self.gates(), "pauper")
        plaza = [s for s in plan["swaps"] if s["name"] == "Plaza of Harmony"]
        self.assertTrue(plaza, [s["name"] for s in plan["swaps"]])
        self.assertTrue(plaza[0]["weak"])
        self.assertIn("synergy-gate", [d["slug"] for d in plaza[0]["drops"]])

    def test_the_pool_of_wins_is_named_where_it_exists(self):
        pool = formats.win_pool(self.db, "pioneer", self.gates())
        self.assertTrue(pool)
        self.assertEqual(formats.win_pool(self.db, "pauper", self.gates()), [])


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

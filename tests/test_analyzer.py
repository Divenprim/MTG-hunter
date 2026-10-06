"""Разбор колоды на признаки: считаем то, что есть, и говорим, чем считали.

Здесь проверяется нижний слой анализа -- тот, на котором потом стоят баллы.
Если он ошибается тихо, ошибаются и они, и заметить это будет негде: балл
выглядит одинаково убедительно и когда он посчитан, и когда он выдуман.

Три вещи, ради которых этот файл написан:

  * **у каждого числа есть карты.** Признак без списка карт -- это мнение.
    Поэтому проверяется не только «сколько», но и «кто»;
  * **метки берутся по дереву, а не по подстроке.** «%ramp%» ловит
    `gives-trample`, «%counter%» -- полторы тысячи карт с жетонами +1/+1.
    Такая ошибка не падает, она просто даёт неправильный ответ;
  * **противоядие -- не яд.** `hate-discard` -- это защита от дискарда, и
    считать её дискардом значит перевернуть смысл на противоположный.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import analyzer  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestFeatures(unittest.TestCase):
    """Признаки считаются по настоящим картам: выдумать фикстуру тут нельзя.

    Смысл проверки как раз в том, совпадает ли наше представление о карте с
    тем, что про неё знает база. На поддельной карте это не проверяется.
    """

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def look(self, rows):
        return analyzer.features(rows, self.db)

    def feat(self, rows, key):
        return self.look(rows)["features"][key]

    # ------------------------------------------------------------ основное

    def test_it_counts_copies_not_names(self):
        got = self.look([("Lightning Bolt", 4), ("Island", 20)])
        self.assertEqual(got["cards"], 24)
        self.assertEqual(got["lands"], 20)

    def test_unknown_cards_are_named_not_dropped(self):
        got = self.look([("Такой Карты Нет", 2), ("Island", 1)])
        self.assertEqual(got["unknown"], [{"name": "Такой Карты Нет", "copies": 2}])
        self.assertEqual(got["cards"], 3, "неизвестная карта всё равно карта")

    def test_every_feature_says_which_cards_made_it(self):
        got = self.look([("Swords to Plowshares", 1), ("Wrath of God", 1)])
        removal = got["features"]["removal"]
        self.assertEqual(removal["copies"], 2)
        names = [c["name"] for c in removal["cards"]]
        self.assertIn("Swords to Plowshares", names)
        self.assertIn("Wrath of God", names)
        for card in removal["cards"]:
            self.assertTrue(card.get("why"), "должно быть видно, чем посчитали")

    def test_contributors_come_biggest_first(self):
        got = self.feat([("Lightning Bolt", 4), ("Swords to Plowshares", 1)],
                        "removal")
        self.assertEqual([c["copies"] for c in got["cards"]], [4, 1])

    # -------------------------------------------------- метки, а не подстроки

    def test_trample_is_not_ramp(self):
        """«%ramp%» ловит gives-trample -- проверяем, что мы так не считаем."""
        got = self.feat([("Rancor", 1)], "ramp")
        self.assertEqual(got["copies"], 0, got["cards"])

    def test_plus_one_counters_are_not_counterspells(self):
        """«%counter%» -- это полторы тысячи карт с жетонами, а не контрмагия."""
        got = self.feat([("Ajani's Pridemate", 1)], "counterspell")
        self.assertEqual(got["copies"], 0, got["cards"])

    def test_a_real_counterspell_is_one(self):
        got = self.feat([("Counterspell", 1)], "counterspell")
        self.assertEqual(got["copies"], 1)

    def test_protection_from_discard_is_not_discard(self):
        """hate-discard -- противоядие, а не яд."""
        got = self.feat([("Thoughtseize", 1), ("Leyline of Sanctity", 1)],
                        "discard")
        names = [c["name"] for c in got["cards"]]
        self.assertIn("Thoughtseize", names)
        self.assertNotIn("Leyline of Sanctity", names)

    # ------------------------------------------------------ спорные случаи

    def test_ramp_beats_tutor(self):
        """Cultivate ищет в библиотеке, но колода с ней -- не колода туторов."""
        got = self.look([("Cultivate", 1), ("Demonic Tutor", 1)])
        self.assertEqual(got["features"]["ramp"]["copies"], 1)
        tutors = [c["name"] for c in got["features"]["tutor"]["cards"]]
        self.assertEqual(tutors, ["Demonic Tutor"])

    def test_a_land_is_a_land_not_a_function(self):
        """Иначе девять фетчей -- это «девять туторов», чего никто не имеет в виду."""
        got = self.look([("Flooded Strand", 4)])
        self.assertEqual(got["features"]["tutor"]["copies"], 0)
        self.assertEqual(got["lands"], 4)

    def test_a_tax_is_not_a_lock(self):
        """«Не могут атаковать, если не заплатят» -- цена, а не запрет."""
        got = self.look([("Ghostly Prison", 1)])
        self.assertEqual(got["features"]["tax"]["copies"], 1)
        self.assertEqual(got["features"]["lock"]["copies"], 0,
                         "плати и играй -- это не замок")

    def test_a_lock_is_a_lock(self):
        got = self.look([("Winter Orb", 1)])
        self.assertEqual(got["features"]["lock"]["copies"], 1)

    def test_fast_mana_is_named_not_guessed(self):
        """«Add {C}{C}» есть и у Sol Ring, и у земли за четыре -- разница есть."""
        got = self.look([("Sol Ring", 1), ("Ur-Golem's Eye", 1)])
        names = [c["name"] for c in got["features"]["fast_mana"]["cards"]]
        self.assertEqual(names, ["Sol Ring"])

    def test_free_spells_are_found_by_what_they_say(self):
        got = self.feat([("Force of Will", 1), ("Counterspell", 1)],
                        "free_spell")
        self.assertEqual([c["name"] for c in got["cards"]], ["Force of Will"])

    def test_mass_land_denial_is_noticed(self):
        got = self.feat([("Armageddon", 1), ("Island", 1)], "mass_land_denial")
        self.assertEqual([c["name"] for c in got["cards"]], ["Armageddon"])

    def test_flexible_removal_is_not_armageddon(self):
        """Beast Within умеет убить землю -- но это не снос земель.

        Он помечен `removal-land`, и если считать это массовым сносом, то
        казуальная колода с одной универсальной картой получает командирский
        бракет B4 и «вы портите всем игру». Цена ошибки -- доверие ко всему
        ответу, поэтому признаки разведены.
        """
        got = self.look([("Beast Within", 1)])
        self.assertEqual(got["features"]["mass_land_denial"]["copies"], 0)
        self.assertEqual(got["features"]["land_removal"]["copies"], 1)

    # -------------------------------------------------------------- форма

    def test_lands_stay_out_of_the_curve(self):
        got = self.look([("Island", 20), ("Lightning Bolt", 4)])
        self.assertEqual(sum(got["curve"].values()), 4)

    def test_types_are_counted(self):
        got = self.look([("Lightning Bolt", 4), ("Sol Ring", 1), ("Island", 2)])
        self.assertEqual(got["types"].get("instant"), 4)
        self.assertEqual(got["types"].get("artifact"), 1)
        self.assertEqual(got["types"].get("land"), 2)

    def test_zero_and_negative_copies_are_ignored(self):
        got = self.look([("Island", 0), ("Lightning Bolt", -3), ("Sol Ring", 1)])
        self.assertEqual(got["cards"], 1)

    def test_an_empty_deck_does_not_explode(self):
        got = self.look([])
        self.assertEqual(got["cards"], 0)
        self.assertEqual(got["unknown"], [])
        self.assertTrue(all(f["copies"] == 0 for f in got["features"].values()))


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestScores(unittest.TestCase):
    """Сила и соль: требования спеки, проверенные на настоящих колодах.

    Главное требование -- не к числам, а к их проверяемости. Балл, который
    нельзя развернуть в слагаемые, нельзя и оспорить: он выглядит одинаково
    убедительно и когда посчитан, и когда выдуман. Поэтому первое, что здесь
    проверяется, -- сходятся ли слагаемые с итогом, а не «правильный» ли итог.

    Числа проверяются диапазонами и порядком, а не равенством: веса -- это
    суждение, и подгонять тест под сегодняшнее суждение значит закрепить его
    навсегда.
    """

    STAX = [("Winter Orb", 1), ("Armageddon", 1), ("Ghostly Prison", 1),
            ("Static Orb", 1), ("Smokestack", 1), ("Thalia, Guardian of Thraben", 1),
            ("Sol Ring", 1), ("Plains", 35)]
    BURN = [("Lightning Bolt", 4), ("Lava Spike", 4), ("Skewer the Critics", 4),
            ("Monastery Swiftspear", 4), ("Shock", 4), ("Mountain", 20)]
    CONTROL = [("Counterspell", 4), ("Swords to Plowshares", 4),
               ("Wrath of God", 3), ("Brainstorm", 4), ("Island", 12),
               ("Plains", 11)]

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def look(self, rows, fmt):
        vector = analyzer.features(rows, self.db)
        measured = analyzer.metrics(vector, fmt, self.db, rows)
        return vector, measured, analyzer.scores(measured, vector)

    def sums(self, block):
        return sum(p["adds"] for p in block["parts"])

    # ------------------------------------------- объяснение, а не декорация

    def test_every_score_equals_the_sum_of_its_named_parts(self):
        """Иначе объяснение -- украшение, и спорить с баллом не о чем."""
        for rows, fmt in ((self.STAX, "commander"), (self.BURN, "modern"),
                          (self.CONTROL, "legacy")):
            _vector, measured, got = self.look(rows, fmt)
            for key in ("power", "salt", "confidence"):
                with self.subTest(fmt=fmt, score=key):
                    self.assertEqual(self.sums(got[key]), got[key]["value"])
            for key, block in measured.items():
                with self.subTest(fmt=fmt, metric=key):
                    self.assertEqual(self.sums(block), block["value"])

    def test_the_weights_come_with_the_answer(self):
        """С числом 78 не поспоришь, с весами -- можно."""
        _v, _m, got = self.look(self.BURN, "modern")
        self.assertIn("power", got["weights"])
        self.assertIn("salt", got["weights"])
        self.assertAlmostEqual(sum(got["weights"]["power"].values()), 1.0, places=6)

    def test_parts_name_the_cards_behind_them(self):
        _v, _m, got = self.look(self.STAX, "commander")
        named = [p for p in got["salt"]["parts"] if p.get("cards")]
        self.assertTrue(named, "соль без карт -- это приговор без доказательств")

    # ------------------------------------------------ требования спеки

    def test_power_and_salt_do_not_move_together(self):
        """Слабая тюрьма солёная, быстрое комбо -- нет. Это разные вещи."""
        _v, _m, stax = self.look(self.STAX, "commander")
        _v, _m, burn = self.look(self.BURN, "modern")
        self.assertGreater(stax["salt"]["value"], burn["salt"]["value"])

    def test_removal_and_counterspells_are_not_salt(self):
        """Иначе солёной окажется любая играющая колода."""
        _v, _m, got = self.look(self.CONTROL, "legacy")
        self.assertEqual(got["salt"]["value"], 0, got["salt"]["parts"])

    def test_removal_does_raise_power(self):
        _v, measured, got = self.look(self.CONTROL, "legacy")
        self.assertGreater(measured["interaction"]["value"], 0)
        self.assertGreater(got["power"]["value"], 0)

    def test_stax_raises_salt_noticeably(self):
        _v, _m, got = self.look(self.STAX, "commander")
        self.assertGreater(got["salt"]["value"], 20, got["salt"]["parts"])

    def test_the_same_deck_reads_differently_in_another_format(self):
        """Одна и та же скорость обычна для легаси и высока для командира."""
        _v, fast, _s = self.look(self.BURN, "legacy")
        _v, slow, _s = self.look(self.BURN, "commander")
        self.assertNotEqual(fast["speed"]["value"], slow["speed"]["value"])

    def test_unknown_cards_lower_confidence_and_say_so(self):
        rows = self.BURN + [("Такой Карты Нет", 20)]
        _v, _m, got = self.look(rows, "modern")
        self.assertLess(got["confidence"]["value"], 100)
        said = " ".join(p["what"] for p in got["confidence"]["parts"])
        self.assertIn("не знаем", said)

    def test_a_deck_we_fully_know_is_fully_trusted(self):
        _v, _m, got = self.look(self.BURN, "modern")
        self.assertEqual(got["confidence"]["value"], 100)

    def test_an_empty_deck_does_not_explode(self):
        _v, _m, got = self.look([], "modern")
        self.assertEqual(got["power"]["value"], 0)
        self.assertEqual(got["salt"]["value"], 0)


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestPrice(unittest.TestCase):
    """Цена списка и «сколько мерзости на доллар».

    Две вещи делают такое сравнение честным или бессмысленным: одинаковая
    методика для обеих колод и покрытие. Цена, известная наполовину, выглядит
    точно так же, как известная целиком, -- и именно поэтому Salt/$ при низком
    покрытии не показывается вовсе.
    """

    CHEAP = [("Winter Orb", 1), ("Ghostly Prison", 1), ("Smokestack", 1),
             ("Plains", 20)]
    RICH = CHEAP[:3] + [("Mana Crypt", 1), ("Gaea's Cradle", 1), ("Plains", 18)]

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def salt_of(self, rows):
        vector = analyzer.features(rows, self.db)
        measured = analyzer.metrics(vector, "commander", self.db, rows)
        return analyzer.scores(measured, vector)["salt"]

    def test_it_says_how_it_counted(self):
        got = analyzer.price(self.CHEAP, self.db)
        self.assertIn("дешёвая печать", got["basis"])

    def test_a_known_deck_is_fully_covered(self):
        got = analyzer.price(self.CHEAP, self.db)
        self.assertEqual(got["coverage"], 1.0, got["unpriced"])
        self.assertGreater(got["usd"], 0)

    def test_unknown_cards_are_named_and_lower_coverage(self):
        got = analyzer.price(self.CHEAP + [("Такой Карты Нет", 10)], self.db)
        self.assertLess(got["coverage"], 1.0)
        self.assertIn("Такой Карты Нет", [u["name"] for u in got["unpriced"]])

    def test_the_cheap_deck_buys_more_salt_per_dollar(self):
        """Требование спеки: одинаковая соль, разная цена -- разный Salt/$."""
        cheap = analyzer.salt_per_dollar(self.salt_of(self.CHEAP),
                                         analyzer.price(self.CHEAP, self.db))
        rich = analyzer.salt_per_dollar(self.salt_of(self.RICH),
                                        analyzer.price(self.RICH, self.db))
        self.assertTrue(cheap["known"] and rich["known"])
        self.assertGreater(cheap["per_dollar"], rich["per_dollar"])

    def test_half_known_prices_give_no_false_precision(self):
        """Делить на цену, известную наполовину, нельзя -- и надо сказать, почему."""
        rows = self.CHEAP + [("Такой Карты Нет", 60)]
        got = analyzer.salt_per_dollar(self.salt_of(rows),
                                       analyzer.price(rows, self.db))
        self.assertFalse(got["known"])
        self.assertIn("мало", got["why"])

    def test_a_free_deck_is_not_divided_by_zero(self):
        got = analyzer.salt_per_dollar({"value": 50},
                                       {"usd": 0.0, "coverage": 1.0,
                                        "basis": "", "unpriced": []})
        self.assertFalse(got["known"])

    def test_an_empty_deck_does_not_explode(self):
        got = analyzer.price([], self.db)
        self.assertEqual(got["usd"], 0)
        self.assertEqual(got["cards"], 0)


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestBracket(unittest.TestCase):
    """Командирский бракет -- на чужих правилах, с датой и источником.

    Бракеты и список Game Changers придумали не мы. Главное требование к этой
    части -- не угадывать: что взято снаружи, то названо и датировано, а чего
    по списку карт не видно (пятый бракет -- это намерение и метагейм), то не
    назначается вовсе.
    """

    CASUAL = [("Llanowar Elves", 1), ("Cultivate", 1), ("Beast Within", 1),
              ("Craterhoof Behemoth", 1), ("Forest", 37)]
    UPGRADED = [("Demonic Tutor", 1), ("Cyclonic Rift", 1), ("Rhystic Study", 1),
                ("Island", 35)]
    ARMAGEDDON = [("Armageddon", 1), ("Winter Orb", 1), ("Plains", 38)]

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()
        try:
            from app.combos import ComboDB
            cls.combo_db = ComboDB()
        except Exception:
            cls.combo_db = None

    def bracket(self, rows, fmt="commander"):
        vector = analyzer.features(rows, self.db)
        combos = analyzer.combos_in(rows, self.db, self.combo_db, fmt)
        return analyzer.commander_bracket(vector, rows, self.db, combos, fmt)

    # --------------------------------------------- куда бракет не лезет

    def test_other_formats_get_no_bracket(self):
        """В модерне бракетов нет; выдать их туда -- выдумка, а не анализ."""
        for fmt in ("modern", "legacy", "standard", "pioneer", "pauper", None):
            with self.subTest(fmt=fmt):
                self.assertIsNone(self.bracket(self.CASUAL, fmt))

    def test_a_strong_deck_never_becomes_cedh_by_itself(self):
        """cEDH -- это намерение и метагейм, по списку карт его не видно."""
        got = self.bracket(self.UPGRADED + [("Mana Crypt", 1),
                                            ("Vampiric Tutor", 1),
                                            ("Ancient Tomb", 1)])
        self.assertLessEqual(got["bracket"], 4)
        self.assertTrue(any("cEDH" in w for w in got["warnings"]))

    # ------------------------------------------------------ сами правила

    def test_a_quiet_deck_sits_at_the_bottom(self):
        self.assertEqual(self.bracket(self.CASUAL)["bracket"], 1)

    def test_flexible_removal_does_not_count_as_armageddon(self):
        """Beast Within умеет убить землю -- и из-за этого казуальная колода
        получала B4 и «вы портите всем игру». Цена ошибки -- доверие."""
        got = self.bracket(self.CASUAL)
        said = " ".join(v["what"] for lv in got["levels"].values()
                        for v in lv["violations"])
        self.assertNotIn("уничтожение земель", said)

    def test_mass_land_denial_does(self):
        got = self.bracket(self.ARMAGEDDON)
        self.assertGreaterEqual(got["bracket"], 4)
        said = " ".join(v["what"] for v in got["levels"][3]["violations"])
        self.assertIn("уничтожение земель", said)

    def test_game_changers_are_counted_and_named(self):
        got = self.bracket(self.UPGRADED)
        names = [c["name"] for c in got["game_changers"]]
        self.assertIn("Demonic Tutor", names)
        self.assertIn("Cyclonic Rift", names)
        self.assertEqual(got["bracket"], 3, "три Game Changers -- это B3")

    def test_one_game_changer_already_bars_the_two_lowest(self):
        got = self.bracket(self.CASUAL + [("Demonic Tutor", 1)])
        self.assertFalse(got["levels"][1]["fits"])
        self.assertFalse(got["levels"][2]["fits"])
        self.assertTrue(got["levels"][3]["fits"])

    def test_every_violation_can_be_read(self):
        got = self.bracket(self.ARMAGEDDON)
        for level in got["levels"].values():
            for broken in level["violations"]:
                self.assertTrue(broken["what"].strip())

    def found(self, rows, tier, means, cards, compact=0):
        """Бракет при заранее известном наборе комбо.

        Настоящая база комбо в тестах изолирована -- и правило из-за этого
        не проверялось вовсе, тесты молча уходили в пропуск. А проверять надо
        именно правило: `commander_bracket` берёт комбо параметром, так что
        достаточно подать их прямо.
        """
        vector = analyzer.features(rows, self.db)
        combos = {"known": True, "count": 1, "compact": compact,
                  "complete": [], "near": 0,
                  "best": {"tier": tier, "means": means, "cards": cards}}
        return analyzer.commander_bracket(vector, rows, self.db, combos,
                                          "commander")

    def test_a_finished_combo_sets_the_floor(self):
        """Пометка Spellbook сама говорит, с какого бракета комбо уместно.

        Прежнее правило смотрело только на двойки -- и колода с двенадцатью
        собранными комбо из трёх карт объявлялась Exhibition, то есть самой
        безобидной, какая бывает. Пометки существуют ровно для этого.
        """
        got = self.found(self.CASUAL, 4, "Ruthless — быстрая двойка",
                         ["Thassa's Oracle", "Demonic Consultation"], compact=1)
        self.assertGreaterEqual(got["bracket"], 4,
                                "Ruthless-двойка не может быть казуальной")
        said = " ".join(v["what"] for v in got["levels"][3]["violations"])
        self.assertIn("комбо", said)

    def test_a_three_card_combo_still_lifts_the_floor(self):
        """Колода с собранным комбо из трёх карт -- не Exhibition."""
        got = self.found(self.CASUAL, 2, "Oddball — требует третьей карты",
                         ["A", "B", "C"], compact=0)
        self.assertEqual(got["bracket"], 2)
        self.assertFalse(got["levels"][1]["fits"])

    def test_a_casual_combo_does_not_lift_anything(self):
        """Exhibition-комбо уместно и в самой безобидной колоде."""
        got = self.found(self.CASUAL, 1, "Exhibition — казуальное",
                         ["A", "B"], compact=0)
        self.assertEqual(got["bracket"], 1)

    def test_a_deck_without_combos_is_not_pushed_up(self):
        if self.combo_db is None or not getattr(self.combo_db, "ready", False):
            got = self.bracket(self.CASUAL)   # без базы: комбо просто неизвестны
        else:
            got = self.bracket(self.CASUAL)
        said = " ".join(v["what"] for lv in got["levels"].values()
                        for v in lv["violations"])
        self.assertNotIn("собранное комбо", said)

    # ------------------------------------------- чужое названо и датировано

    def test_the_answer_says_whose_rules_these_are(self):
        got = self.bracket(self.CASUAL)
        self.assertIn("Scryfall", got["rules"]["game_changers"])
        self.assertIn(analyzer.GAME_CHANGERS_DATE, got["rules"]["game_changers"])
        self.assertIn("Spellbook", got["rules"]["combo_brackets"])

    def test_the_game_changer_list_is_real_cards(self):
        gone = [name for name in analyzer.GAME_CHANGERS
                if not self.db.by_name(name)]
        self.assertEqual(gone, [], "таких карт нет: %s" % gone[:5])

    def test_the_combo_marks_are_the_documented_ones(self):
        """«C» -- это Core, а не Casual: догадка здесь была бы неверной."""
        self.assertEqual(set(analyzer.SPELLBOOK_BRACKET),
                         set("BEOCSPR"))
        self.assertIn("Core", analyzer.SPELLBOOK_BRACKET["C"][1])
        self.assertIn("Exhibition", analyzer.SPELLBOOK_BRACKET["E"][1])

    # ------------------------------------------------ без базы комбо

    def test_without_the_combo_database_it_says_so(self):
        got = analyzer.combos_in(self.CASUAL, self.db, None, "commander")
        self.assertFalse(got["known"])
        self.assertIn("не собрана", got["why"])

    def test_the_bracket_still_answers_without_combos(self):
        """Анализ обязан пережить отсутствие чужих данных, а не развалиться."""
        vector = analyzer.features(self.ARMAGEDDON, self.db)
        combos = analyzer.combos_in(self.ARMAGEDDON, self.db, None, "commander")
        got = analyzer.commander_bracket(vector, self.ARMAGEDDON, self.db,
                                         combos, "commander")
        self.assertIsNotNone(got)
        self.assertTrue(any("комбо" in w for w in got["warnings"]))


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestVocabulary(unittest.TestCase):
    """Метка, которой нет, не ошибается -- она не срабатывает никогда.

    Ровно так в `family.py` годами жили четырнадцать выдуманных меток. Здесь
    проверяется, что каждый корень существует, что за ним стоят карты и что
    ветка разворачивается по дереву, а не остаётся одним словом.
    """

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()
        cls.known = {r["slug"]: (r["card_count"] or 0)
                     for r in cls.db.conn.execute(
                         "SELECT slug, card_count FROM tags")}

    def test_every_root_exists(self):
        missing = [root for roots in analyzer.TAG_FEATURES.values()
                   for root in roots if root not in self.known]
        self.assertEqual(missing, [], "таких меток в базе нет: %s" % missing)

    def test_every_branch_marks_cards(self):
        self.db.conn                      # дерево грузится на это соединение
        empty = {}
        for key, roots in analyzer.TAG_FEATURES.items():
            cards = sum(self.known.get(slug, 0)
                        for root in roots for slug in analyzer._branch(root))
            if not cards:
                empty[key] = roots
        self.assertEqual(empty, {}, "ветки без карт: %s" % empty)

    def test_inverted_tags_are_kept_out_of_branches(self):
        self.db.conn
        for key, roots in analyzer.TAG_FEATURES.items():
            for root in roots:
                bad = [s for s in analyzer._branch(root)
                       if s.startswith(analyzer.TAG_INVERTS)]
                self.assertEqual(bad, [], "%s: %s" % (key, bad))

    def test_fast_mana_names_are_real_cards(self):
        gone = [name for name in analyzer.FAST_MANA
                if not self.db.by_name(name)]
        self.assertEqual(gone, [], "таких карт нет: %s" % gone)


if __name__ == "__main__":
    unittest.main()

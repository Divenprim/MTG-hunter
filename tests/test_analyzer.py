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

    def test_land_denial_is_noticed(self):
        got = self.feat([("Armageddon", 1), ("Island", 1)], "land_denial")
        self.assertEqual([c["name"] for c in got["cards"]], ["Armageddon"])

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

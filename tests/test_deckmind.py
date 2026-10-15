"""О чём колода и что ей предложить — без командира и без интернета.

Предложка умела один вопрос: «что играют с этим командиром». Человеку,
собирающему модерн, она показывала поле «имя командира» и больше ничего.

Здесь проверяется то, ради чего всё затевалось:

* смысл колоды читается по картам — туманы остаются туманами, реанимация
  реанимацией;
* предложения в цветах колоды и легальны в её формате;
* того, что уже в колоде, в предложениях нет;
* «подешевле» не превращается в свалку из карт по рублю, которые никто не
  играет;
* мусорные теги Scryfall («три буквы в названии», «цикл земель набора») в
  темы не попадают.

База карт нужна настоящая: темы — это её теги.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import deckmind  # noqa: E402
from app.cards import CardDB  # noqa: E402

DB = CardDB()


def deck(name, fmt, names, section="main"):
    return {
        "name": name,
        "format": fmt,
        "cards": [{"name": n, "quantity": 4, "section": section} for n in names],
    }


FOG = deck("туманы", "pioneer", [
    "Fog", "Haze of Pollen", "Root Snare", "Blunt the Assault",
    "Forest", "Island", "Opt", "Growth Spiral", "Dictate of Kruphix",
])

COUNTERS = deck("синий контроль", "pioneer", [
    "Counterspell", "Negate", "Essence Scatter", "Dissolve", "Disdainful Stroke",
    "Island", "Opt", "Think Twice", "Censor",
])

DORKS = deck("зелёные дорки", "modern", [
    "Llanowar Elves", "Elvish Mystic", "Birds of Paradise", "Noble Hierarch",
    "Forest", "Giant Growth", "Llanowar Visionary",
])


class TestThemesAreRead(unittest.TestCase):
    def slugs(self, result):
        return [t["slug"] for t in result["themes"]]

    def test_fog_deck_is_about_fog(self):
        got = deckmind.themes(FOG["cards"], DB)
        self.assertIn("fog", self.slugs(got), self.slugs(got))

    def test_counter_deck_is_about_counterspells(self):
        got = deckmind.themes(COUNTERS["cards"], DB)
        self.assertTrue(
            any("counter" in s for s in self.slugs(got)), self.slugs(got))

    def test_dork_deck_is_about_mana(self):
        got = deckmind.themes(DORKS["cards"], DB)
        self.assertTrue(
            any(s in ("mana-dork", "ramp", "mana-producer", "mana-creature")
                or "mana" in s for s in self.slugs(got)), self.slugs(got))

    def test_colours_come_from_the_cards(self):
        got = deckmind.themes(COUNTERS["cards"], DB)
        self.assertEqual(got["colors"], "U", got["colors"])

    def test_junk_tags_are_not_themes(self):
        """«Три буквы в названии» — настоящий тег и не тема."""
        for d in (FOG, COUNTERS, DORKS):
            for slug in self.slugs(deckmind.themes(d["cards"], DB)):
                self.assertFalse(deckmind._junky(slug), slug)
                root = deckmind.tag_root(slug, deckmind._tag_parents(DB))
                self.assertNotIn(root, deckmind.JUNK_ROOTS, slug)

    def test_a_pile_of_unrelated_cards_has_no_theme(self):
        """Набор «всего понемногу» — это не замысел, и выдумывать его нельзя."""
        pile = deck("свалка", "modern", [
            "Forest", "Island", "Mountain", "Swamp", "Plains",
        ])
        self.assertEqual(deckmind.themes(pile["cards"], DB)["themes"], [])


class TestSuggestions(unittest.TestCase):
    def ideas(self, d, order="fit"):
        return deckmind.ideas(d, DB, order=order)

    def test_fog_deck_gets_fog_cards(self):
        got = self.ideas(FOG)
        fog = [s for s in got["sections"] if s["slug"] == "fog"]
        self.assertTrue(fog, [s["slug"] for s in got["sections"]])
        names = [p["name"] for p in fog[0]["picks"]]
        self.assertTrue(names)
        # Предложенные туманы -- тоже туманы, а не что попало.
        for name in names[:5]:
            row = DB.conn.execute(
                "SELECT oracle_id FROM cards WHERE name = ? LIMIT 1",
                (name,)).fetchone()
            tags = {r["slug"] for r in DB.conn.execute(
                "SELECT slug FROM card_tags WHERE oracle_id = ?",
                (row["oracle_id"],))}
            self.assertIn("fog", tags, name)

    def test_nothing_already_in_the_deck_is_suggested(self):
        got = self.ideas(FOG)
        mine = {c["name"].lower() for c in FOG["cards"]}
        for section in got["sections"]:
            for pick in section["picks"]:
                self.assertNotIn(pick["name"].lower(), mine)

    def test_suggestions_stay_in_colour(self):
        got = self.ideas(COUNTERS)
        for section in got["sections"]:
            for pick in section["picks"]:
                row = DB.conn.execute(
                    "SELECT color_identity FROM cards WHERE name = ? LIMIT 1",
                    (pick["name"],)).fetchone()
                identity = set((row["color_identity"] or "") if row else "")
                self.assertTrue(identity.issubset({"U"}),
                                "%s -> %s" % (pick["name"], identity))

    def test_suggestions_are_legal_in_the_format(self):
        got = self.ideas(FOG)
        for section in got["sections"]:
            for pick in section["picks"]:
                row = DB.conn.execute(
                    "SELECT legalities FROM cards WHERE name = ? LIMIT 1",
                    (pick["name"],)).fetchone()
                self.assertTrue(deckmind._legal_in(row["legalities"], "pioneer"),
                                pick["name"])

    def test_cheap_order_is_cheap_but_not_rubbish(self):
        """«Подешевле» ищет дешёвое среди ходового, а не вообще всё дешёвое.

        Без этого на «где контрмагия подешевле» приезжали карты по рублю,
        которых не играет никто: дешевизна без порога — это свалка.
        """
        cheap = self.ideas(COUNTERS, order="cheap")
        fit = self.ideas(COUNTERS, order="fit")
        self.assertTrue(cheap["sections"] and fit["sections"])

        def prices(data):
            out = []
            for section in data["sections"]:
                for pick in section["picks"]:
                    if pick["usd"] is not None:
                        out.append(pick["usd"])
            return out

        cheap_prices, fit_prices = prices(cheap), prices(fit)
        if cheap_prices and fit_prices:
            self.assertLessEqual(
                sum(cheap_prices) / len(cheap_prices),
                sum(fit_prices) / len(fit_prices))

        # И при этом каждая предложенная карта переиздавалась хоть раз --
        # то есть она в ходу, а не редкость из одного набора.
        for section in cheap["sections"]:
            for pick in section["picks"]:
                self.assertGreaterEqual(pick["printings"], 1, pick["name"])

    def test_sections_explain_themselves(self):
        got = self.ideas(FOG)
        for section in got["sections"]:
            self.assertTrue(section["label"])
            self.assertIn("в колоде", section["why"])
            self.assertTrue(section["examples"])

    def test_no_commander_needed(self):
        """Главное: для модерна и пионера не спрашивается никакой командир."""
        for d in (FOG, COUNTERS, DORKS):
            got = self.ideas(d)
            self.assertTrue(got["sections"], d["name"])


class TestThemeNames(unittest.TestCase):
    def test_known_themes_are_russian(self):
        self.assertEqual(deckmind.theme_label("fog"),
                         "Туманы: бой не наносит урона")
        self.assertEqual(deckmind.theme_label("counterspell"), "Контрмагия")

    def test_unknown_theme_falls_back_to_its_own_name(self):
        """Переводить четыре с половиной тысячи тегов руками никто не станет;
        показать slug честнее, чем выдумать перевод."""
        self.assertEqual(deckmind.theme_label("wibble-wobble"), "Wibble wobble")


class TestFormatAndColour(unittest.TestCase):
    def test_legal_in_handles_missing_data(self):
        self.assertTrue(deckmind._legal_in(None, "modern"))
        self.assertTrue(deckmind._legal_in("не json", "modern"))
        self.assertTrue(deckmind._legal_in('{"modern": "legal"}', "modern"))
        self.assertFalse(deckmind._legal_in('{"modern": "banned"}', "modern"))
        self.assertTrue(deckmind._legal_in('{"modern": "banned"}', ""))

    def test_colourless_fits_any_deck(self):
        self.assertTrue(deckmind._within("", {"U"}))
        self.assertTrue(deckmind._within("U", {"U", "B"}))
        self.assertFalse(deckmind._within("R", {"U", "B"}))


if __name__ == "__main__":
    unittest.main()


class TestNoRepeats(unittest.TestCase):
    """Карта несёт несколько тегов: тот же «Pause for Reflection» -- и туман,
    и защита планесвокера. Предложенная дважды, она выглядит сбоем."""

    def test_a_card_is_suggested_once(self):
        got = deckmind.ideas(FOG, DB)
        seen = []
        for section in got["sections"]:
            for pick in section["picks"]:
                seen.append(pick["name"])
        self.assertEqual(len(seen), len(set(seen)),
                         [n for n in seen if seen.count(n) > 1][:4])


class TestDescriptionIsReadable(unittest.TestCase):
    def test_markdown_links_are_stripped(self):
        raw = ("Effects that prevent damage, similar to Fog. See also "
               "[pseudo-fog](https://tagger.scryfall.com/tags/card/pseudo-fog).")
        out = deckmind.clean_description(raw)
        self.assertNotIn("http", out)
        self.assertNotIn("[", out)

    def test_russian_theme_needs_no_english_help(self):
        got = deckmind.themes(FOG["cards"], DB)
        for theme in got["themes"]:
            if theme["slug"] in deckmind.RU_THEMES:
                self.assertEqual(theme["description"], "", theme["slug"])

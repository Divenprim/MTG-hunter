"""Tests for the search query language and result ranking."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import CardDB, parse_query  # noqa: E402

DB = CardDB()


class TestColourModes(unittest.TestCase):
    """cards.colors is stored in Scryfall's order (alphabetical in practice,
    e.g. 'UW'), never WUBRG. Matching must not depend on the order."""

    def test_exactly_these_colours(self):
        rows = DB.search("c=wu t:creature", limit=20)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(set(r["colors"]), {"U", "W"})

    def test_includes_these_colours(self):
        rows = DB.search("c:wu t:creature", limit=20)
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue({"U", "W"}.issubset(set(r["colors"])))

    def test_at_most_these_colours(self):
        rows = DB.search("c<=wu t:creature", limit=30)
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(set(r["colors"]).issubset({"U", "W"}))

    def test_colourless(self):
        rows = DB.search("c:c t:artifact", limit=10)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["colors"], "")

    def test_identity_defaults_to_subset(self):
        rows = DB.search("id:abzan t:creature", limit=25)
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(set(r["color_identity"]).issubset({"W", "B", "G"}))

    def test_guild_name_expands(self):
        by_name = DB.count("id<=azorius")
        by_letters = DB.count("id<=wu")
        self.assertEqual(by_name, by_letters)


class TestCommaLists(unittest.TestCase):
    def test_rarity_list_is_or(self):
        rows = DB.search("r:rare,mythic", limit=25)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["rarity"], ("rare", "mythic"))

    def test_set_list_is_or(self):
        rows = DB.search("s:clb,m10", limit=25)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["set_code"], ("clb", "m10"))

    def test_type_list_is_or(self):
        total_both = DB.count("t:instant,sorcery")
        self.assertGreater(total_both, DB.count("t:instant"))
        self.assertGreater(total_both, DB.count("t:sorcery"))


class TestRanges(unittest.TestCase):
    def test_cmc_window(self):
        rows = DB.search("cmc>=3 cmc<=4 t:creature", limit=25)
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(3 <= (r["cmc"] or 0) <= 4)

    def test_power_floor(self):
        rows = DB.search("pow>=6 t:creature", limit=20)
        self.assertTrue(rows)
        for r in rows:
            try:
                self.assertGreaterEqual(float(r["power"]), 6)
            except (TypeError, ValueError):
                self.fail("non-numeric power slipped through: %r" % r["power"])


class TestSorting(unittest.TestCase):
    def test_rarity_sort_puts_mythics_first(self):
        """'special'/'bonus' must not outrank mythic."""
        rows = DB.search("t:creature", limit=6, sort="rarity")
        self.assertTrue(all(r["rarity"] == "mythic" for r in rows))

    def test_cmc_sort_ascends(self):
        rows = DB.search("t:creature", limit=8, sort="cmc")
        values = [r["cmc"] or 0 for r in rows]
        self.assertEqual(values, sorted(values))

    def test_price_asc_skips_cards_without_a_price(self):
        rows = DB.search("t:creature", limit=5, sort="price_asc")
        for r in rows:
            self.assertTrue((r["prices"] or {}).get("usd"))


class TestRanking(unittest.TestCase):
    def test_a_card_outranks_another_cards_face_with_the_same_name(self):
        """Regression: "Lightning Bolt" is a card AND the back face of
        "Emeritus of Conflict // Lightning Bolt". The real card comes first."""
        rows = DB.search("Lightning Bolt", limit=3)
        self.assertEqual(rows[0]["name"], "Lightning Bolt")

    def test_exact_name_beats_longer_names_containing_it(self):
        rows = DB.search("Tiamat", limit=4)
        self.assertEqual(rows[0]["name"], "Tiamat")
        self.assertIn("Tiamat's Fanatics", [r["name"] for r in rows])

    def test_russian_name_finds_the_card(self):
        rows = DB.search("Удар Молнии", limit=2)
        self.assertEqual(rows[0]["name"], "Lightning Bolt")


class TestCount(unittest.TestCase):
    def test_count_matches_paged_results(self):
        q = "s:clb r:mythic"
        total = DB.count(q)
        page1 = DB.search(q, limit=1000)
        self.assertEqual(total, len(page1))

    def test_unknown_key_is_treated_as_text_not_dropped(self):
        q = parse_query("bogus:thing")
        self.assertIsNotNone(q.fts)
        self.assertIn("bogus", q.fts)


class TestFinishes(unittest.TestCase):
    def test_is_foil_actually_narrows(self):
        """Regression: finishes is a list like "nonfoil,foil", and a bare
        LIKE '%foil%' also matches "nonfoil" -- so is:foil matched everything."""
        base = DB.count("c:c t:artifact cmc<=2")
        foil = DB.count("c:c t:artifact cmc<=2 is:foil")
        self.assertGreater(base, 0)
        self.assertLess(foil, base)

    def test_is_foil_rows_really_have_a_foil_finish(self):
        rows = DB.search("t:creature is:foil", limit=15)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn("foil", (r["finishes"] or "").split(","))


class TestExactMatchPinning(unittest.TestCase):
    """Choosing a sort order must not bury the card you searched for.

    Regression: "tiamat" sorted by ascending price listed
    "Livaan, Cultist of Tiamat" and "Tiamat's Fanatics" first, because Tiamat
    is the expensive one -- so the card being searched for never appeared at
    the top. The sort now orders everything EXCEPT the exact match.
    """

    SORTS = ["relevance", "name", "cmc", "cmc_desc", "released",
             "released_asc", "rarity", "price", "price_asc"]

    def test_tiamat_is_first_in_every_sort(self):
        for sort in self.SORTS:
            rows = DB.search("tiamat", limit=10, sort=sort)
            self.assertTrue(rows, "no results for sort=%s" % sort)
            self.assertEqual(
                rows[0]["name"], "Tiamat",
                "sort=%s put %r first" % (sort, rows[0]["name"]),
            )

    def test_full_name_still_beats_face_name_under_a_sort(self):
        for sort in ("price_asc", "released", "name"):
            rows = DB.search("Lightning Bolt", limit=5, sort=sort)
            self.assertEqual(rows[0]["name"], "Lightning Bolt", "sort=%s" % sort)

    def test_sort_still_orders_the_non_exact_results(self):
        rows = DB.search("t:creature c:g", limit=6, sort="cmc")
        values = [r["cmc"] or 0 for r in rows]
        self.assertEqual(values, sorted(values))


class TestSetGroupsAndTreatments(unittest.TestCase):
    """Secret Lair is five set codes, and its drops are only distinguishable by
    promo_types / frame_effects / border_color -- not by set."""

    SECRET_LAIR_CODES = {"sld", "slc", "slp", "slu", "pssc", "sls", "slx"}

    def test_set_group_expands(self):
        rows = DB.search("s:secretlair", limit=40)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["set_code"], self.SECRET_LAIR_CODES)

    def test_is_secretlair_matches_the_group(self):
        self.assertEqual(DB.count("is:secretlair"), DB.count("s:secretlair"))

    def test_group_mixes_with_plain_codes(self):
        both = DB.count("s:secretlair,clb")
        self.assertGreater(both, DB.count("s:clb"))
        self.assertGreater(both, DB.count("s:secretlair"))

    def test_borderless_reads_border_color_not_frame_effects(self):
        rows = DB.search("is:borderless", limit=25)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["border_color"], "borderless")

    def test_showcase_and_extendedart_read_frame_effects(self):
        for flag in ("showcase", "extendedart"):
            rows = DB.search("is:" + flag, limit=15)
            self.assertTrue(rows, flag)
            for r in rows:
                self.assertIn(flag, (r["frame_effects"] or "").split(","))

    def test_serialized_reads_promo_types(self):
        rows = DB.search("is:serialized", limit=15)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn("serialized", (r["promo_types"] or "").split(","))

    def test_treatment_narrows_the_group(self):
        whole = DB.count("s:secretlair")
        borderless = DB.count("s:secretlair is:borderless")
        self.assertGreater(whole, 0)
        self.assertLess(borderless, whole)

    def test_frame_and_promo_keys(self):
        self.assertGreater(DB.count("frame:etched"), 0)
        self.assertGreater(DB.count("promo:prerelease"), 0)
        self.assertGreater(DB.count("border:gold"), 0)

    def test_textless_and_fullart(self):
        for r in DB.search("is:textless", limit=8):
            self.assertEqual(r["textless"], 1)


class TestFlavourNamesAndDrops(unittest.TestCase):
    """Secret Lair reprints are PRINTED under a themed name: "Hammer of Nazahn"
    appears as "Piko Piko Hammer" in the Sonic drop. That is the name on the
    card, the name a user types, and the name topdeck sellers write."""

    def test_flavour_name_finds_the_card(self):
        rows = DB.search("Piko Piko Hammer", limit=2)
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "Hammer of Nazahn")

    def test_flavour_name_shows_the_printing_that_bears_it(self):
        rows = DB.search("Piko Piko Hammer", limit=1)
        self.assertEqual(rows[0]["set_code"], "sld")
        self.assertEqual(rows[0]["flavor_name"], "Piko Piko Hammer")

    def test_by_name_resolves_a_flavour_name(self):
        """So a seller listing "Piko Piko Hammer" can be matched at all."""
        card = DB.by_name("Piko Piko Hammer")
        self.assertIsNotNone(card)
        self.assertEqual(card["name"], "Hammer of Nazahn")

    def test_real_name_still_outranks_a_flavour_name(self):
        rows = DB.search("Hammer of Nazahn", limit=2)
        self.assertEqual(rows[0]["name"], "Hammer of Nazahn")

    def test_collector_number_range_expresses_a_drop(self):
        """The Sonic drop is sld #2081-2101 and nothing else identifies it."""
        rows = DB.search("s:sld cn>=2081 cn<=2087", limit=20)
        names = {r["name"] for r in rows}
        self.assertIn("Sonic the Hedgehog", names)
        self.assertIn("Amy Rose", names)
        self.assertIn("Knuckles the Echidna", names)
        self.assertEqual(len(rows), 7)

    def test_collector_number_exact(self):
        rows = DB.search("s:sld cn:2087", limit=3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Sonic the Hedgehog")

    def test_released_filter(self):
        self.assertGreater(DB.count("s:sld released:2025-07-14"), 0)


class TestFunctionalTags(unittest.TestCase):
    """Search by PURPOSE. "рампа" and "кража существ" are not phrases printed
    on cards, so oracle text cannot find them; Scryfall Tagger's curated tags
    can."""

    def test_ramp_returns_cards(self):
        self.assertGreater(DB.count("otag:ramp"), 500)

    def test_theft_creature_returns_cards(self):
        rows = DB.search("otag:theft-creature", limit=5)
        self.assertTrue(rows)

    def test_parent_tag_includes_its_children(self):
        """`control-changing-effects` has NO cards of its own -- they hang off
        its children -- so asking for the parent must expand the hierarchy."""
        direct = DB.conn.execute(
            "SELECT card_count FROM tags WHERE slug = 'control-changing-effects'"
        ).fetchone()
        self.assertEqual(direct["card_count"], 0, "fixture assumption changed")
        self.assertGreater(DB.count("otag:control-changing-effects"), 100)

    def test_expansion_includes_known_children(self):
        from app.cards import _expand_tag_slugs
        expanded = _expand_tag_slugs("control-changing-effects")
        self.assertIn("theft", expanded)
        self.assertIn("exchange-control", expanded)

    def test_tag_combines_with_other_filters(self):
        broad = DB.count("otag:ramp")
        narrow = DB.count("otag:ramp cmc<=2")
        self.assertGreater(broad, narrow)
        for r in DB.search("otag:ramp cmc<=2", limit=10):
            self.assertLessEqual(r["cmc"] or 0, 2)

    def test_two_tags_and_together(self):
        both = DB.count("otag:ramp otag:mana-rock")
        self.assertGreater(both, 0)
        self.assertLessEqual(both, DB.count("otag:mana-rock"))

    def test_comma_list_is_or(self):
        either = DB.count("otag:mana-rock,mana-dork")
        self.assertGreater(either, DB.count("otag:mana-rock"))

    def test_unknown_tag_matches_nothing_not_everything(self):
        """Silently ignoring an unknown tag would return the whole database and
        look like the filter worked."""
        self.assertEqual(DB.count("otag:definitely-not-a-real-tag"), 0)

    def test_aliases_resolve(self):
        from app.cards import _expand_tag_slugs
        self.assertTrue(_expand_tag_slugs("spot removal"))


class TestFullNameBeatsFaceName(unittest.TestCase):
    """A card's OWN name must outrank another card's face or flavour name --
    both for an exact match and for a prefix, which is where it was missed.

    Typing "burg" used to list "Bilbo, Luckwearer // Burglar's Bell" above
    "Burgeoning": both matched the prefix, and the tie-break was alphabetical.
    """

    def test_exact_full_name_wins(self):
        self.assertEqual(DB.search("Burgeoning", limit=3)[0]["name"], "Burgeoning")

    def test_prefix_prefers_the_cards_own_name(self):
        rows = DB.search("burg", limit=5)
        self.assertEqual(rows[0]["name"], "Burgeoning",
                         "got %s" % [r["name"] for r in rows])

    def test_prefix_does_not_surface_face_matches_first(self):
        for query in ("bu", "bur", "burg"):
            first = DB.search(query, limit=1)[0]["name"]
            self.assertNotIn(" // ", first,
                             "%r put a two-faced card first: %s" % (query, first))

    def test_partial_typing_keeps_the_obvious_card_on_top(self):
        """Every prefix of the name, from the point it is unambiguous."""
        for length in range(5, len("Burgeoning") + 1):
            query = "Burgeoning"[:length]
            first = DB.search(query, limit=1)[0]["name"]
            self.assertEqual(first, "Burgeoning", "%r -> %s" % (query, first))

    def test_exact_match_still_pinned_under_every_sort(self):
        for sort in ("relevance", "name", "cmc", "price_asc", "released", "rarity"):
            rows = DB.search("Burgeoning", limit=3, sort=sort)
            self.assertEqual(rows[0]["name"], "Burgeoning", "sort=%s" % sort)


if __name__ == "__main__":
    unittest.main(verbosity=2)

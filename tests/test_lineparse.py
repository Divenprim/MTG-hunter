"""Tests for the seller-line normalizer, built from real topdeck listings."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lineparse import SetIndex, parse_line  # noqa: E402

IDX = SetIndex.load()
BOLT = ("Lightning Bolt", "Удар Молнии")
RING = ("Sol Ring", "Солнечное Кольцо")


def p(line, names=BOLT):
    return parse_line(line, IDX, names[0], names[1])


class TestSetAndNumber(unittest.TestCase):
    def test_set_code_with_hash_number(self):
        r = p("\t1x Lightning Bolt (EN) (SP) (A25 #141) 160")
        self.assertEqual(r.set_code, "a25")
        self.assertEqual(r.collector_number, "141")
        self.assertEqual(r.language, "en")
        self.assertEqual(r.condition, "LP")

    def test_set_dash_number(self):
        r = p("1 <b>Lightning Bolt (JP)</b> (PL, m11-149)")
        self.assertEqual(r.set_code, "m11")
        self.assertEqual(r.collector_number, "149")
        self.assertEqual(r.language, "ja")
        self.assertEqual(r.condition, "MP")

    def test_full_set_name(self):
        r = p("1 <b>Lightning Bolt</b> (M/NM, Modern Masters 2015)")
        self.assertEqual(r.set_code, "mm2")
        self.assertEqual(r.set_confidence, "name")
        self.assertEqual(r.condition, "NM")

    def test_long_set_name_wins_over_prefix(self):
        r = p("1 <b>Lightning Bolt</b> (M/NM, Commander Legends: Battle for Baldur's Gate)")
        self.assertEqual(r.set_code, "clb")

    def test_cyrillic_set_code(self):
        """Sellers type set codes on a Russian keyboard: 'м11' with Cyrillic м."""
        r = p("\t3 Удар молнии (М11) sp 130")
        self.assertEqual(r.set_code, "m11")
        self.assertEqual(r.condition, "LP")

    def test_price_does_not_eat_the_set_code(self):
        """Regression: a greedy price regex turned 'm10 143р.' into the price
        '10 143' and destroyed the set code."""
        r = p("\t1x RU m10 Lightning Bolt 143р. SP")
        self.assertEqual(r.set_code, "m10")
        self.assertEqual(r.price_in_line, 143)
        self.assertEqual(r.language, "ru")
        self.assertEqual(r.condition, "LP")

    def test_ordinal_set_alias(self):
        r = p("\t4 Lightning Bolt (4E) - 270")
        self.assertEqual(r.set_code, "4ed")

    def test_number_only_is_flagged(self):
        r = p("\t   1 Lightning Bolt (#1) [eng]  фойл - 2000 руб.")
        self.assertIsNone(r.set_code)
        self.assertEqual(r.collector_number, "1")
        self.assertEqual(r.set_confidence, "number-only")
        self.assertTrue(r.foil)

    def test_no_information_is_not_invented(self):
        r = p("3 <b style='color:#777777'>Lightning Bolt</b> ")
        self.assertIsNone(r.set_code)
        self.assertIsNone(r.language)
        self.assertIsNone(r.condition)
        self.assertIn("no set identified", r.warnings)


class TestMixedLots(unittest.TestCase):
    def test_explicit_mixed_word(self):
        r = p("4 <b style='color:#777777'>Lightning Bolt</b>  (разные)")
        self.assertTrue(r.mixed)

    def test_two_languages_in_one_listing(self):
        r = p("\t   3 Удар Молнии (#146) [2 рус, 1 eng]  - 130 руб.")
        self.assertTrue(r.mixed)
        self.assertEqual(sorted(r.languages), ["en", "ru"])
        self.assertIsNone(r.language)  # ambiguous, so no single answer

    def test_rus_slash_eng(self):
        r = p("4 Sol Ring 120 rus/eng", RING)
        self.assertTrue(r.mixed)
        self.assertEqual(sorted(r.languages), ["en", "ru"])


class TestAttributes(unittest.TestCase):
    def test_foil_and_treatment(self):
        r = p("\t1x Lightning Bolt (showcase) (EN) (NM) (CLB #401) 190")
        self.assertIn("showcase", r.treatments)
        self.assertEqual(r.set_code, "clb")

    def test_foil_detected(self):
        r = p("\t1    Lightning Bolt M11  EN Foil     525")
        self.assertTrue(r.foil)
        self.assertEqual(r.set_code, "m11")

    def test_foil_unstated_stays_none(self):
        r = p("\t4x Lightning Bolt (EN) (NM) (CLB #187) 160")
        self.assertIsNone(r.foil)

    def test_condition_variants(self):
        for line, grade in [
            ("1 x Lightning Bolt (NM-) (M10 #146) 1", "NM"),
            ("1 x Lightning Bolt (M/NM) (M10 #146) 1", "NM"),
            ("1 x Lightning Bolt (SP+) (M10 #146) 1", "LP"),
            ("1 x Lightning Bolt (MP) (M10 #146) 1", "MP"),
            ("1 x Lightning Bolt (HP) (M10 #146) 1", "HP"),
        ]:
            self.assertEqual(p(line).condition, grade, msg=line)

    def test_promo_family_labelled_not_guessed(self):
        r = p("\t1 Lightning Bolt judge gift cards - 5000")
        self.assertEqual(r.promo_family, "judge-promo")
        self.assertIsNone(r.set_code)

    def test_html_is_stripped(self):
        r = p("4 <b style='color:#777777'>Lightning Bolt</b>  (CLB FOIL eng nm)")
        self.assertNotIn("<", r.residue)
        self.assertEqual(r.set_code, "clb")
        self.assertTrue(r.foil)
        self.assertEqual(r.language, "en")
        self.assertEqual(r.condition, "NM")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Tests for deciding which card a topdeck listing is really for.

The bug these guard against cost real money. topdeck's search matches seller
lines by substring and labels every result with the name you SEARCHED FOR, not
the card being sold. Asking for "Burgeoning" returned 69 offers all labelled
"Burgeoning" -- 45 of them were Urban Burgeoning, Blighted Burgeoning,
March of Burgeoning Life or Hulkling, Burgeoning Bruiser, and the cheap ones
were all the wrong card. The real Burgeoning starts around 2000 roubles, and
the app was about to show 10.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import CardDB  # noqa: E402
from app.offermatch import MATCH, OTHER, UNCLEAR, OfferMatcher, price_check  # noqa: E402

DB = CardDB()


class TestConfusableNames(unittest.TestCase):
    def setUp(self):
        self.m = OfferMatcher(DB)

    def test_longer_names_containing_the_wanted_one_are_known(self):
        names = {display for _, display in self.m.confusable("Burgeoning")}
        self.assertIn("Urban Burgeoning", names)
        self.assertIn("Blighted Burgeoning", names)
        self.assertIn("March of Burgeoning Life", names)

    def test_the_card_itself_is_not_listed_as_confusable(self):
        names = {display for _, display in self.m.confusable("Burgeoning")}
        self.assertNotIn("Burgeoning", names)

    def test_tiamat_traps_are_known(self):
        names = {display for _, display in self.m.confusable("Tiamat")}
        self.assertIn("Tiamat's Fanatics", names)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.m = OfferMatcher(DB)

    def verdict(self, want, line):
        return self.m.classify(want, line)["verdict"]

    def test_real_listing_matches(self):
        self.assertEqual(
            self.verdict("Burgeoning", "11 <b>Burgeoning</b> (NM, CN2)"), MATCH)

    def test_a_different_card_is_rejected_by_name(self):
        for line in (
            "Urban burgeoning 10",
            "2 RTR Urban Burgeoning 10 руб.",
            "2 <b>Blighted Burgeoning</b> (NM, March of the Machine)",
            "1 March of Burgeoning Life (#201) [eng]  - 21",
            "Hulkling, Burgeoning Bruiser 20",
        ):
            self.assertEqual(self.verdict("Burgeoning", line), OTHER, line)

    def test_the_rejection_names_the_actual_card(self):
        r = self.m.classify("Burgeoning", "Urban burgeoning 10")
        self.assertEqual(r["actual"], "Urban Burgeoning")
        self.assertIn("Urban Burgeoning", r["reason"])

    def test_russian_name_counts_as_a_match(self):
        self.assertEqual(
            self.verdict("Lightning Bolt", "2 <b>Удар Молнии</b> (NM, Magic 2011)"), MATCH)

    def test_a_face_name_counts_as_a_match(self):
        self.assertEqual(
            self.verdict("Brazen Borrower", "1x Petty Theft (EN) (NM) (ELD #39) 400"), MATCH)

    def test_flavour_name_counts_as_a_match(self):
        self.assertEqual(
            self.verdict("Hammer of Nazahn", "1 Piko Piko Hammer (SLD) 900"), MATCH)

    def test_line_without_the_name_is_unclear_not_a_match(self):
        """Silence is not consent: an unreadable line must not be bought."""
        self.assertEqual(self.verdict("Burgeoning", "4 карты по 100 руб"), UNCLEAR)

    def test_empty_line_is_unclear(self):
        self.assertEqual(self.verdict("Burgeoning", ""), UNCLEAR)

    def test_html_and_nbsp_do_not_hide_the_name(self):
        line = "2 <b style='color:#777'>Burgeoning</b> (NM, c16-143)"
        self.assertEqual(self.verdict("Burgeoning", line), MATCH)


class TestPriceCheck(unittest.TestCase):
    """topdeck also misreads prices out of seller lines."""

    def test_collector_number_read_as_a_price_is_caught(self):
        r = price_check(235, "1 Тиамат (Tiamat) #235/281 AFR RU     1300")
        self.assertTrue(r["disputed"])
        self.assertEqual(r["written"], 1300)
        self.assertIn("235", r["reason"])
        self.assertIn("1300", r["reason"])

    def test_agreeing_price_is_not_disputed(self):
        r = price_check(160, "4x Lightning Bolt (EN) (SP) (M10 #146) 160")
        self.assertFalse(r["disputed"])

    def test_no_price_in_line_is_not_a_dispute(self):
        """Most shop lines carry no price at all; that is not a disagreement."""
        r = price_check(2074, "11 <b>Burgeoning</b> (NM, CN2)")
        self.assertFalse(r["disputed"])

    def test_rouble_suffix_is_understood(self):
        r = price_check(145, "4 Lightning Bolt (NM EN CLB #187) - 145 руб")
        self.assertFalse(r["disputed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Tests for name resolution and offer->want matching.

Guards the bug class the user hit: one card's name being part of another's.
A listing for "Tiamat's Fanatics" must never be bought as "Tiamat", and a
listing written as a back face ("Petty Theft") must match its card.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import CardDB, normalize_name  # noqa: E402
from app.hunt import Filters, Hunter, Want  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402

DB = CardDB()


class FakeClient:
    """Returns a canned offer list, so no network and no load on topdeck."""

    def __init__(self, offers):
        self._offers = offers
        self.asked: list[str] = []

    def search(self, names):
        self.asked.extend(names)
        return list(self._offers)


def offer(eng_name, line, cost=100, qty=4, rus_name=""):
    return Offer(
        name=eng_name, eng_name=eng_name, rus_name=rus_name, qty=qty, cost=cost,
        seller=Seller(name="s", kind="user", id="1", refs=5), source="topdeck",
        url="", stamp="", line=line,
    )


class TestNormalize(unittest.TestCase):
    def test_typographic_apostrophe(self):
        self.assertEqual(normalize_name("Tiamat’s Fanatics"), normalize_name("Tiamat's Fanatics"))

    def test_case_and_space(self):
        self.assertEqual(normalize_name("  LIGHTNING   bolt "), "lightning bolt")

    def test_double_slash_spacing(self):
        self.assertEqual(
            normalize_name("Brazen Borrower//Petty Theft"), "brazen borrower // petty theft"
        )


class TestByName(unittest.TestCase):
    def test_substring_neighbour_is_not_confused(self):
        self.assertEqual(DB.by_name("Tiamat")["name"], "Tiamat")
        self.assertEqual(DB.by_name("Tiamat's Fanatics")["name"], "Tiamat's Fanatics")

    def test_back_face_resolves_to_its_card(self):
        self.assertEqual(DB.by_name("Petty Theft")["name"], "Brazen Borrower // Petty Theft")

    def test_russian_name_resolves(self):
        self.assertEqual(DB.by_name("Удар Молнии")["name"], "Lightning Bolt")

    def test_unknown_name_is_none(self):
        self.assertIsNone(DB.by_name("Not A Real Card Name At All"))


class TestFaceAwareSearch(unittest.TestCase):
    def test_search_labels_the_face_that_matched(self):
        rows = DB.search("Petty Theft", limit=3)
        self.assertTrue(rows)
        top = rows[0]
        self.assertEqual(top["display_name"], "Petty Theft")
        self.assertEqual(top["name"], "Brazen Borrower // Petty Theft")
        self.assertEqual(top["matched_face"], 1)

    def test_exact_name_ranks_first(self):
        rows = DB.search("Tiamat", limit=5)
        self.assertEqual(rows[0]["name"], "Tiamat")

    def test_faces_are_attached_with_images_for_transform(self):
        rows = DB.search("Fable of the Mirror-Breaker", limit=1)
        faces = rows[0]["faces"]
        self.assertEqual(len(faces), 2)
        # transform cards have a real image per side
        self.assertTrue(all(f["image_normal"] for f in faces))


class TestTwoFacedNames(unittest.TestCase):
    """Двусторонние карты ищутся по лицевой стороне.

    Полное имя карты -- «Search for Azcanta // Azcanta, the Sunken Ruin», и так
    её пишут единицы: на topdeck по полному имени находилось три объявления, а
    по лицевой стороне -- двадцать три. Поэтому спрашиваем оба имени; лишнего
    запроса это не стоит, потому что поиск принимает список имён разом.
    """

    def test_both_names_are_asked_for(self):
        h = Hunter(DB, FakeClient([]))
        names = h._query_names([
            Want(name="Search for Azcanta // Azcanta, the Sunken Ruin", quantity=1)])
        self.assertIn("Search for Azcanta // Azcanta, the Sunken Ruin", names)
        self.assertIn("Search for Azcanta", names)

    def test_a_plain_card_is_asked_for_once(self):
        h = Hunter(DB, FakeClient([]))
        self.assertEqual(h._query_names([Want(name="Fog", quantity=4)]), ["Fog"])

    def test_the_same_name_is_not_asked_twice(self):
        h = Hunter(DB, FakeClient([]))
        names = h._query_names([
            Want(name="Fog", quantity=4),
            Want(name="fog", quantity=1),
        ])
        self.assertEqual(names, ["Fog"])

    def test_the_search_really_gets_the_front_face(self):
        client = FakeClient([])
        h = Hunter(DB, client)
        h.gather([Want(name="Brazen Borrower // Petty Theft", quantity=1)])
        self.assertIn("Brazen Borrower", client.asked)
        self.assertIn("Brazen Borrower // Petty Theft", client.asked)

    def test_an_offer_for_the_front_face_still_counts_as_the_card(self):
        """Иначе искать по лицу было бы бессмысленно: нашли и не узнали."""
        client = FakeClient([
            offer("Brazen Borrower", "1 Brazen Borrower ELD 39", cost=150)])
        h = Hunter(DB, client)
        cands = h.gather([Want(name="Brazen Borrower // Petty Theft", quantity=1)])
        self.assertTrue(cands)
        self.assertEqual(cands[0].want, "Brazen Borrower // Petty Theft")


class TestOfferMatching(unittest.TestCase):
    def test_alias_map_covers_faces_and_russian(self):
        h = Hunter(DB, FakeClient([]))
        aliases = h._alias_map([Want(name="Brazen Borrower", quantity=1)])
        self.assertIn("petty theft", aliases)
        self.assertIn("brazen borrower // petty theft", aliases)

    def test_offer_for_a_different_card_is_rejected(self):
        """The exact failure: topdeck returns a neighbour, we must not buy it."""
        h = Hunter(DB, FakeClient([
            offer("Tiamat", "1x Tiamat (RU) (NM) (AFR #235) 1200", cost=1200),
            offer("Tiamat's Fanatics", "4 Tiamat's Fanatics (CLB #202) 60", cost=60),
        ]))
        wants = [Want(name="Tiamat", quantity=1)]
        cands = h.gather(wants)

        good = [c for c in cands if not c.unmatched]
        bad = [c for c in cands if c.unmatched]
        self.assertEqual([c.offer.eng_name for c in good], ["Tiamat"])
        self.assertEqual([c.offer.eng_name for c in bad], ["Tiamat's Fanatics"])
        # The reason is shown to the user, so it is written in Russian.
        self.assertIn("другая карта", bad[0].rejected)

    def test_filters_cannot_revive_a_different_card(self):
        h = Hunter(DB, FakeClient([
            offer("Tiamat's Fanatics", "4 Tiamat's Fanatics (CLB #202) 60", cost=60),
        ]))
        cands = h.gather([Want(name="Tiamat", quantity=1)])
        h.apply_filters(cands, Filters())
        self.assertTrue(all(c.rejected for c in cands))
        self.assertIn("другая карта", cands[0].rejected)

    def test_listing_written_as_back_face_matches(self):
        h = Hunter(DB, FakeClient([
            offer("Petty Theft", "1x Petty Theft (EN) (NM) (ELD #39) 400", cost=400),
        ]))
        cands = h.gather([Want(name="Brazen Borrower", quantity=1)])
        self.assertFalse(cands[0].unmatched)
        self.assertEqual(cands[0].want, "Brazen Borrower")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Русские имена склоняются, а поиск по подстроке — нет.

«Молния» не находила «Удар Молнии»: на карте напечатан родительный падеж, и
подстрока «молния» в него не входит. Хуже того, выдача была **не пустая** —
дюжина карт, у которых «Молния» стоит в именительном («Шаровая Молния»,
«Ветвистая Молния»), — поэтому ни одна подсказка про пустой поиск не
срабатывала, и выходило, что программа карту просто не знает.

Заодно здесь закреплено, почему основа ищется в `card_names`, а не по
`LOWER(ru_name)`: `LOWER()` в SQLite понижает только латиницу, и для него
«Удар Молнии» так и остаётся с заглавной «М».
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import CardDB, name_like_terms, ru_stem  # noqa: E402

DB = CardDB()


class TestStem(unittest.TestCase):
    def test_russian_ending_is_dropped(self):
        self.assertEqual(ru_stem("Молния"), "молни")
        self.assertEqual(ru_stem("рампа"), "рамп")

    def test_consonant_ending_is_left_alone(self):
        """«Остров» и так в именительном: резать нечего."""
        self.assertEqual(ru_stem("Остров"), "остров")

    def test_latin_is_untouched(self):
        self.assertEqual(ru_stem("Lightning"), "lightning")
        self.assertEqual(ru_stem("Bolt"), "bolt")

    def test_short_words_are_untouched(self):
        """«Лес» — целое имя карты, а не окончание."""
        self.assertEqual(ru_stem("Лес"), "лес")
        self.assertEqual(ru_stem("Гора"), "гора")

    def test_terms_keep_the_original_first(self):
        self.assertEqual(name_like_terms("молния"), ["молния", "молни"])
        self.assertEqual(name_like_terms("остров"), ["остров"])


class TestSearchFindsOtherCase(unittest.TestCase):
    def names(self, query, limit=60):
        return [r["name"] for r in DB.search(query, limit=limit)]

    def test_nominative_finds_genitive(self):
        self.assertIn("Lightning Bolt", self.names("Молния"))

    def test_official_name_still_first(self):
        rows = self.names("Удар Молнии", limit=5)
        self.assertEqual(rows[0], "Lightning Bolt")

    def test_latin_search_unchanged(self):
        rows = self.names("Lightning Bolt", limit=5)
        self.assertEqual(rows[0], "Lightning Bolt")

    def test_basic_land_unchanged(self):
        """«Остров» — проверка на то, что основа не растащила выдачу."""
        rows = self.names("Остров", limit=5)
        self.assertEqual(rows[0], "Island")

    def test_count_matches_search(self):
        """Счётчик «показано N из M» считает тем же условием, что и выдача.

        Иначе выйдет «показано 45 из 12»: условие живёт в трёх местах --
        выдача, счётчик и отбор печатей, -- и расходится оно молча.
        """
        for query in ("Молния", "Остров", "Удар Молнии"):
            found = len(self.names(query, limit=400))
            total = DB.count(query)
            self.assertEqual(found, total, query)
            self.assertLess(found, 400, query)


if __name__ == "__main__":
    unittest.main()

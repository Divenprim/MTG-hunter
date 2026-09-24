"""Теги, по которым программа судит о картах, должны существовать.

Правило, написанное по несуществующему тегу, не ошибается -- оно просто не
срабатывает никогда, и заметить это нельзя ни по логам, ни по экрану. Так в
`family.py` половина списка «ответных карт» (graveyard-hate, stax, prison,
land-destruction, hexproof-granting, artifact-removal, enchantment-removal,
anti-aggro) и почти весь список «чем выигрывают» (wincon, infinite-combo,
win-the-game, mill-wincon, combo-finisher, damage-wincon) жили годами, ничего
не помечая: в таксономии Scryfall таких тегов нет.

Здесь проверяется, что каждый тег из этих списков есть в собранной базе и
что за ним стоят карты. Без базы тестировать нечего -- тогда тест пропускается.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import family, formats  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402

# Списки, которые программа сверяет со слагами тегов один в один. NOISE_TAGS
# сюда не входит: там нарочно куски слагов, а не слаги («art-», «typal-»).
EXACT = {
    "family.REACTIVE_TAGS": family.REACTIVE_TAGS,
    "family.WINCON_TAGS": family.WINCON_TAGS,
    "formats.WIN_TAGS": formats.WIN_TAGS,
    "formats.MILL_TAGS": formats.MILL_TAGS,
    "formats.BURN_TAGS": formats.BURN_TAGS,
    "formats.POISON_TAGS": formats.POISON_TAGS,
    "formats.COSMETIC_ROOTS": tuple(formats.COSMETIC_ROOTS),
}


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestTagVocabulary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()
        cls.known = {r["slug"]: (r["card_count"] or 0)
                     for r in cls.db.conn.execute(
                         "SELECT slug, card_count FROM tags")}

    def test_every_tag_exists_in_the_base(self):
        missing = {}
        for where, tags in EXACT.items():
            if where.endswith("COSMETIC_ROOTS"):
                continue          # корни проверяются отдельно, по дереву
            gone = [t for t in tags if t not in self.known]
            if gone:
                missing[where] = gone
        self.assertEqual(missing, {},
                         "таких тегов в базе нет: %s" % missing)

    def test_cosmetic_roots_are_real_roots_of_the_tree(self):
        """Корень -- не обязательно тег с картами, но существовать он обязан.

        Иначе целая ветка «косметики» отсекается только на словах: «art» и
        «flavor» такими и были -- их в дереве нет.
        """
        tree = formats._tree(self.db.conn)
        roots = set()
        for slug in tree["parents"]:
            roots |= formats._roots(tree, slug)
        unknown = sorted(set(formats.COSMETIC_ROOTS) - roots)
        self.assertEqual(unknown, [], "таких корней в дереве нет: %s" % unknown)

    def test_every_tag_marks_at_least_some_cards(self):
        """Тег с нулём карт -- то же самое, что несуществующий."""
        empty = {}
        for where, tags in EXACT.items():
            # Корни косметики -- узлы дерева, у них своих карт может не быть:
            # они нужны как родители, а не как метки.
            if where.endswith("COSMETIC_ROOTS"):
                continue
            zero = [t for t in tags if self.known.get(t, 0) == 0]
            if zero:
                empty[where] = zero
        self.assertEqual(empty, {}, "теги без единой карты: %s" % empty)

    def test_the_win_tag_really_marks_cards_that_win(self):
        """Проверка смысла, а не только существования."""
        rows = self.db.conn.execute(
            "SELECT c.name FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id "
            "WHERE t.slug = 'alternate-win-condition' AND c.representative = 1 "
            "ORDER BY c.name").fetchall()
        names = {r["name"] for r in rows}
        self.assertIn("Maze's End", names)
        self.assertIn("Approach of the Second Sun", names)


if __name__ == "__main__":
    unittest.main()

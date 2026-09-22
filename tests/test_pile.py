"""Тесты разбора снимка пачки: прочитать имена и понять, какие это карты.

Снимок здесь рисуется на месте: полосы с именами, набранные системным
шрифтом. Это не подмена проверки, а её суть -- распознавателю всё равно, чем
напечатано имя, а нам нужно убедиться, что прочитанное находит свою карту
среди шестидесяти тысяч имён и что текст с карты не выдаёт себя за имя.
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ocr, pile                                # noqa: E402
from app.cards import DB_PATH, CardDB                    # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = pile.DEPS_OK
except ImportError:                                      # pragma: no cover
    HAVE_PIL = False

HAVE_OCR = ocr.available().get("ok", False)
HAVE_DB = os.path.exists(DB_PATH)

NAMES = ["Lightning Bolt", "Sol Ring", "Counterspell", "Cultivate",
         "Birds of Paradise", "Brainstorm"]


def _font(size: int):
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fake_pile(names, step=120, width=900) -> bytes:
    """Пачка внахлёст: у каждой карты видна только полоса с именем."""
    height = step * len(names) + 240
    img = Image.new("RGB", (width, height), (42, 40, 38))
    draw = ImageDraw.Draw(img)
    font = _font(46)
    for i, name in enumerate(names):
        top = 40 + i * step
        draw.rectangle([40, top, width - 40, top + step + 200], fill=(222, 214, 196),
                       outline=(28, 26, 24), width=3)
        draw.text((78, top + 26), name, fill=(18, 16, 14), font=font)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


class TestLattice(unittest.TestCase):
    """Ровный шаг -- это то, чем имя отличается от текста с карты."""

    def test_a_steady_run_is_kept_whole(self):
        rows = [100, 210, 320, 430, 540]
        self.assertEqual(pile.lattice(rows), [True] * 5)

    def test_text_below_the_run_falls_out(self):
        # Пять имён через 110, а дальше тип, правила и флейвор нижней карты.
        rows = [100, 210, 320, 430, 540, 843, 1022, 1070]
        keep = pile.lattice(rows)
        self.assertEqual(keep[:5], [True] * 5)
        self.assertEqual(keep[5:], [False] * 3)

    def test_a_missing_card_does_not_break_the_run(self):
        rows = [100, 210, 430, 540, 650]        # одну карту не прочитали
        self.assertEqual(pile.lattice(rows), [True] * 5)

    def test_too_few_rows_are_all_kept(self):
        self.assertEqual(pile.lattice([10, 120]), [True, True])


class TestCleanText(unittest.TestCase):
    def test_it_drops_what_the_reader_adds(self):
        self.assertEqual(pile.clean_text("  Lightning  Bolt. "), "Lightning Bolt")
        self.assertEqual(pile.clean_text("«Сол Ринг»"), "Сол Ринг")

    def test_it_keeps_the_apostrophe(self):
        self.assertIn("'", pile.clean_text("Gaea's Cradle"))


@unittest.skipUnless(HAVE_DB, "нет собранной базы карт")
class TestNameFinder(unittest.TestCase):
    """Поиск нестрогий: распознаватель ошибается, а имя всё равно узнаётся."""

    @classmethod
    def setUpClass(cls):
        cls.finder = pile.NameFinder(CardDB())

    def test_an_exact_name_is_found(self):
        hit = self.finder.find("Lightning Bolt")[0]
        self.assertEqual(hit["name"], "Lightning Bolt")
        self.assertGreater(hit["score"], 0.99)

    def test_a_misread_name_is_still_found(self):
        for misread in ("Lightnmg Bolt", "lightning boIt", "Ligh tning Bolt"):
            hit = self.finder.find(misread)[0]
            self.assertEqual(hit["name"], "Lightning Bolt", misread)
            self.assertGreater(hit["score"], 0.85, misread)

    def test_a_russian_name_is_found_too(self):
        hit = self.finder.find("Удар Молнии")[0]
        self.assertTrue(hit["name"], "русское имя не нашлось")
        self.assertGreater(hit["score"], 0.9)

    def test_nonsense_does_not_pretend_to_be_a_card(self):
        hits = self.finder.find("qwerty zxcvbn")
        self.assertTrue(not hits or hits[0]["score"] < pile.MIN_RATIO)


@unittest.skipUnless(HAVE_PIL and HAVE_OCR and HAVE_DB,
                     "нужны Pillow, распознаватель текста и база карт")
class TestReadingAPile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()
        cls.finder = pile.NameFinder(cls.db)

    def test_every_card_on_the_photo_is_read(self):
        out = pile.read_pile(fake_pile(NAMES), self.db, ocr, self.finder)
        self.assertTrue(out["ok"], out.get("detail"))
        sure = [c["name"] for c in out["cards"] if c["sure"]]
        for name in NAMES:
            self.assertIn(name, sure, "не прочиталась: %s" % name)

    def test_it_does_not_invent_cards(self):
        out = pile.read_pile(fake_pile(NAMES), self.db, ocr, self.finder)
        sure = [c["name"] for c in out["cards"] if c["sure"]]
        self.assertEqual(len(sure), len(NAMES),
                         "лишние уверенные: %s" % [n for n in sure if n not in NAMES])

    def test_an_empty_photo_says_so_instead_of_guessing(self):
        blank = Image.new("RGB", (800, 1000), (40, 40, 40))
        buf = io.BytesIO()
        blank.save(buf, "JPEG")
        out = pile.read_pile(buf.getvalue(), self.db, ocr, self.finder)
        self.assertTrue(out["ok"])
        self.assertEqual(out["cards"], [])


class TestWithoutAReader(unittest.TestCase):
    def test_it_says_what_is_missing(self):
        class NoReader:
            @staticmethod
            def available():
                return {"ok": False, "detail": "нечем читать"}

        out = pile.read_pile(b"", CardDB() if HAVE_DB else None, NoReader())
        self.assertFalse(out["ok"])
        self.assertIn("нечем читать", out["detail"])


if __name__ == "__main__":
    unittest.main()

"""Тесты поиска карты в кадре и её выпрямления.

Это тот шаг, который снимает с человека обязанность класть карту в рамку. Без
него отпечаток считается по неизменной доле кадра, и восемь градусов поворота
означают уже другую картинку; с ним карта находится как четырёхугольник и
приводится к прямоугольнику, и угол перестаёт значить что-либо.

Кадры здесь рисуются на месте: карта -- узнаваемый прямоугольник с
асимметричным рисунком (чтобы было видно, если выпрямление перевернуло или
отразило её), лежащий на фоне под разными углами.
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import carddetect  # noqa: E402

try:
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:                                      # pragma: no cover
    HAVE_PIL = False

HAVE_CV = carddetect.DEPS_OK


def a_card(w=420, h=586) -> "Image.Image":
    """Карта: светлая, с разными углами, чтобы ловить переворот и отражение."""
    card = Image.new("RGBA", (w, h), (232, 226, 210, 255))
    draw = ImageDraw.Draw(card)
    draw.rectangle([0, 0, w - 1, h - 1], outline=(30, 28, 26, 255), width=6)
    draw.rectangle([int(w * .08), int(h * .10), int(w * .92), int(h * .47)],
                   fill=(60, 90, 150, 255))                      # «арт»
    draw.ellipse([int(w * .12), int(h * .13), int(w * .34), int(h * .28)],
                 fill=(240, 190, 60, 255))                       # метка вверху слева
    draw.rectangle([int(w * .55), int(h * .60), int(w * .90), int(h * .90)],
                   fill=(150, 60, 60, 255))                      # метка внизу справа
    return card


def photo(card: "Image.Image", angle=0.0, shift=(0.0, 0.0), scale=1.0,
          bg=(70, 66, 60), size=(1280, 960)) -> bytes:
    """Кадр «карта лежит на столе»."""
    W, H = size
    ch = int(H * 0.62 * scale)
    cw = int(ch * card.width / card.height)
    small = card.resize((cw, ch), Image.LANCZOS)
    rotated = small.rotate(angle, resample=Image.BICUBIC, expand=True,
                           fillcolor=(0, 0, 0, 0))
    frame = Image.new("RGB", (W, H), bg)
    frame.paste(rotated,
                (int((W - rotated.width) / 2 + shift[0] * W),
                 int((H - rotated.height) / 2 + shift[1] * H)),
                rotated.split()[3])
    out = io.BytesIO()
    frame.save(out, "JPEG", quality=85)
    return out.getvalue()


@unittest.skipUnless(HAVE_PIL and HAVE_CV, "нет OpenCV — поиск карты не собран")
class TestFindingTheCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = a_card()

    def test_a_card_lying_straight_is_found(self):
        """Кандидатов бывает несколько -- и это нарочно.

        У карты находится и внешний край, и линия рамки, а на снимке
        нескольких карт -- ещё и контуры вокруг пар соседних. Разобрать, что
        из них карта, геометрия не может: у пары карт бок о бок пропорции
        ровно как у одной карты набок. Поэтому сюда возвращаются все
        правдоподобные, а отбирает отпечаток.
        """
        found = carddetect.find_cards(photo(self.card))
        self.assertTrue(found)
        self.assertGreater(found[0]["area"], 0.05)
        self.assertTrue(all(f["area"] > 0 for f in found))

    def test_the_angle_does_not_matter(self):
        for angle in (0, 7, 15, 30, 45, 60, 80):
            found = carddetect.find_cards(photo(self.card, angle=angle))
            self.assertTrue(found, "не нашлась при %d°" % angle)

    def test_the_place_in_the_frame_does_not_matter(self):
        found = carddetect.find_cards(photo(self.card, shift=(0.24, -0.2), angle=12))
        self.assertTrue(found)

    def test_the_straightened_card_has_card_proportions(self):
        found = carddetect.find_cards(photo(self.card, angle=23))
        with Image.open(io.BytesIO(found[0]["image"])) as img:
            self.assertEqual(img.size, (carddetect.CARD_W, carddetect.CARD_H))

    def test_the_straightened_card_is_not_turned_or_mirrored(self):
        """Метка была вверху слева -- там же должна и остаться.

        Перевёрнутая или отражённая карта для отпечатка -- это другая карта,
        и поймать это надо здесь, а не на живых снимках.
        """
        for angle in (0, 20, 40):
            found = carddetect.find_cards(photo(self.card, angle=angle))
            with Image.open(io.BytesIO(found[0]["image"])) as img:
                rgb = img.convert("RGB")
                w, h = rgb.size
                corner = rgb.getpixel((int(w * .22), int(h * .20)))
                self.assertGreater(corner[0], 150, "жёлтой метки нет при %d°" % angle)
                self.assertGreater(corner[0] - corner[2], 60,
                                   "цвет метки не жёлтый при %d°" % angle)

    def test_the_corners_come_back_as_fractions_of_the_frame(self):
        found = carddetect.find_cards(photo(self.card, angle=10))
        for x, y in found[0]["corners"]:
            self.assertTrue(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, (x, y))

    def test_an_empty_table_yields_nothing(self):
        blank = Image.new("RGB", (1280, 960), (70, 66, 60))
        out = io.BytesIO()
        blank.save(out, "JPEG")
        self.assertEqual(carddetect.find_cards(out.getvalue()), [])

    def test_rubbish_input_does_not_raise(self):
        self.assertEqual(carddetect.find_cards(b"not a picture"), [])


class TestWithoutOpenCV(unittest.TestCase):
    def test_it_answers_nothing_instead_of_failing(self):
        if carddetect.DEPS_OK:
            self.skipTest("OpenCV есть — проверять нечего")
        self.assertEqual(carddetect.find_cards(b""), [])


if __name__ == "__main__":
    unittest.main()

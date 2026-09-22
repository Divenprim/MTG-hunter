"""Тесты отпечатков артов -- того, чем сканер узнаёт карту.

Картинки здесь рисуются на месте, без сети: проверяется не Scryfall, а сама
механика. Снимок с камеры имитируется тем, чем он на самом деле отличается от
эталона: другой размер, поворот, размытие, тусклее, JPEG.
"""

import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import artscan  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    HAVE_PIL = artscan.DEPS_OK
except ImportError:                                        # pragma: no cover
    HAVE_PIL = False


def card_image(seed: int, size=(146, 204)) -> bytes:
    """Что-то похожее на карту: рамка и несколько разноцветных пятен в арте."""
    rng = __import__("random").Random(seed)
    img = Image.new("RGB", size, (20, 18, 16))
    draw = ImageDraw.Draw(img)
    w, h = size
    # Арт занимает ту же долю, которую вырезает сканер.
    draw.rectangle([int(w * .08), int(h * .10), int(w * .92), int(h * .47)],
                   fill=(rng.randint(0, 80), rng.randint(0, 80), rng.randint(0, 80)))
    for _ in range(14):
        x0 = rng.randint(int(w * .08), int(w * .85))
        y0 = rng.randint(int(h * .10), int(h * .42))
        draw.ellipse([x0, y0, x0 + rng.randint(6, 30), y0 + rng.randint(6, 30)],
                     fill=(rng.randint(40, 255), rng.randint(40, 255), rng.randint(40, 255)))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def as_camera(data: bytes, blur=1.3, bright=0.8, angle=2.0, quality=55) -> bytes:
    """Тот же арт, но снятый: мельче, криво, размыто, темнее и пережато."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    img = img.resize((int(w * 1.7), int(h * 1.7)), Image.LANCZOS)
    img = img.rotate(angle, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(blur))
    img = ImageEnhance.Brightness(img).enhance(bright)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)
    return out.getvalue()


@unittest.skipUnless(HAVE_PIL, "нет Pillow/numpy — сканер не собран")
class TestHashes(unittest.TestCase):
    def test_the_same_picture_gives_the_same_hash(self):
        data = card_image(1)
        self.assertEqual(artscan.hashes_for(data), artscan.hashes_for(data))

    def test_different_pictures_give_different_hashes(self):
        a = artscan.hashes_for(card_image(1))
        b = artscan.hashes_for(card_image(2))
        self.assertNotEqual(a, b)

    def test_a_photographed_card_stays_close_to_its_own_hash(self):
        """Снимок обязан быть ближе к своей карте, чем к чужой.

        Это и есть всё условие работоспособности: точного совпадения от камеры
        никто не ждёт, нужно только, чтобы своя карта была ближайшей.
        """
        mine = artscan.hashes_for(card_image(7))
        other = artscan.hashes_for(card_image(8))
        shot = artscan.hashes_for(as_camera(card_image(7)))

        def distance(a, b):
            return bin((a[0] ^ b[0]) & 0xFFFFFFFFFFFFFFFF).count("1") + \
                   bin((a[1] ^ b[1]) & 0xFFFFFFFFFFFFFFFF).count("1")

        near = distance(shot, mine)
        far = distance(shot, other)
        self.assertLess(near, far, "снимок ближе к чужой карте, чем к своей")
        self.assertLess(near, 40, "снимок слишком далёк даже от своей карты")

    def test_sixty_four_bits_survive_the_database(self):
        """Хеш со старшим битом -- обычное дело, и он обязан записаться."""
        value = 0xFFFFFFFFFFFFFFFF
        stored = artscan.signed64(value)
        self.assertLess(stored, 0)
        self.assertEqual(stored & 0xFFFFFFFFFFFFFFFF, value)
        self.assertEqual(artscan.signed64(1), 1)


@unittest.skipUnless(HAVE_PIL, "нет Pillow/numpy — сканер не собран")
class TestIndex(unittest.TestCase):
    """Поиск по собранным отпечаткам, на своей маленькой базе."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="mtgh-art-")
        cls.path = os.path.join(cls.dir, "art.sqlite")
        conn = artscan.connect(cls.path)
        cls.cards = {}
        for seed in range(1, 31):
            data = card_image(seed)
            ph, dh = artscan.hashes_for(data)
            card_id = "card-%02d" % seed
            cls.cards[card_id] = data
            conn.execute(
                "INSERT INTO art (card_id, oracle_id, name, set_code, "
                "collector_number, phash, dhash) VALUES (?,?,?,?,?,?,?)",
                (card_id, "o-%02d" % seed, "Карта %02d" % seed, "tst", str(seed),
                 artscan.signed64(ph), artscan.signed64(dh)))
        conn.commit()
        conn.close()
        cls.index = artscan.ArtIndex(cls.path)

    def test_the_index_loads_everything(self):
        self.assertTrue(self.index.ready)
        self.assertEqual(len(self.index.ids), 30)

    def test_an_exact_picture_finds_itself_at_zero(self):
        ph, dh = artscan.hashes_for(self.cards["card-05"])
        best = self.index.match(ph, dh, limit=3)[0]
        self.assertEqual(best["card_id"], "card-05")
        self.assertEqual(best["distance"], 0)

    def test_a_photographed_card_is_still_found_first(self):
        for card_id in ("card-03", "card-11", "card-22", "card-29"):
            ph, dh = artscan.hashes_for(as_camera(self.cards[card_id]))
            best = self.index.match(ph, dh, limit=3)[0]
            self.assertEqual(best["card_id"], card_id,
                             "%s узналась как %s" % (card_id, best["card_id"]))

    def test_matches_come_back_in_order(self):
        ph, dh = artscan.hashes_for(as_camera(self.cards["card-17"]))
        rows = self.index.match(ph, dh, limit=5)
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["distance"] for r in rows],
                         sorted(r["distance"] for r in rows))

    def test_an_empty_index_answers_nothing_instead_of_failing(self):
        empty = artscan.ArtIndex(os.path.join(self.dir, "nothing.sqlite"))
        self.assertFalse(empty.ready)
        self.assertEqual(empty.match(1, 2), [])


class TestStatusWithoutDatabase(unittest.TestCase):
    def test_it_says_what_is_missing_rather_than_failing(self):
        state = artscan.status(os.path.join(tempfile.gettempdir(), "нет-такого.sqlite"))
        self.assertFalse(state["built"])
        self.assertEqual(state["hashed"], 0)


if __name__ == "__main__":
    unittest.main()

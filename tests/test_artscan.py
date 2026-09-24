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


def in_sleeve(data: bytes, loose: bool = False) -> bytes:
    """Та же карта, но в протекторе -- то есть с полями плёнки вокруг.

    Протектор больше карты (66 x 91 мм против 63 x 88), и в кадре обводится
    он. Карта лежит в нём не по центру: у открытого края поле больше.
    """
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    grow = 1.06 if loose else 1.0
    pad_x = int(w * (66 / 63 - 1) / 2 * grow)
    pad_top = int(h * (91 / 88 - 1) * 0.65 * grow)
    pad_bottom = int(h * (91 / 88 - 1) * 0.35 * grow)
    holder = Image.new("RGB", (w + pad_x * 2, h + pad_top + pad_bottom),
                       (236, 236, 240))
    holder.paste(img, (pad_x, pad_top))
    out = io.BytesIO()
    holder.save(out, "PNG")
    return out.getvalue()


@unittest.skipUnless(HAVE_PIL, "нет Pillow/numpy — сканер не собран")
class TestSleeves(unittest.TestCase):
    """Карта в протекторе.

    Жалоба была прямая: «в протекторах не определяет, приходилось вынимать».
    Дело не в плёнке как таковой, а в рамке: протектор больше карты, контур
    обводит его, и арт внутри выпрямленного прямоугольника оказывается меньше
    и ниже, чем у эталона. Отпечаток считается по доле картинки -- и не
    сходится. Поэтому снимок читается в нескольких рамках сразу.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="mtgh-sleeve-")
        path = os.path.join(cls.dir, "art.sqlite")
        conn = artscan.connect(path)
        cls.cards = {}
        for seed in range(101, 141):
            data = card_image(seed, size=(488, 680))
            ph, dh = artscan.hashes_for(data)
            card_id = "card-%03d" % seed
            cls.cards[card_id] = data
            conn.execute(
                "INSERT INTO art (card_id, oracle_id, name, set_code, "
                "collector_number, phash, dhash) VALUES (?,?,?,?,?,?,?)",
                (card_id, "o-%03d" % seed, "Карта %03d" % seed, "tst",
                 str(seed), artscan.signed64(ph), artscan.signed64(dh)))
        conn.commit()
        conn.close()
        cls.index = artscan.ArtIndex(path)
        cls.saved_index = artscan._INDEX
        artscan._INDEX = cls.index

    @classmethod
    def tearDownClass(cls):
        artscan._INDEX = cls.saved_index

    def test_the_inset_takes_the_film_off(self):
        img = Image.new("RGB", (1000, 1000))
        cut = artscan.unsleeve(img, (0.02, 0.05, 0.02, 0.10))
        self.assertEqual(cut.size, (960, 850))

    def test_no_inset_changes_nothing(self):
        img = Image.new("RGB", (100, 100))
        self.assertIs(artscan.unsleeve(img, (0.0, 0.0, 0.0, 0.0)), img)

    def test_a_card_in_a_sleeve_is_recognised(self):
        for card_id, data in list(self.cards.items())[:12]:
            found = artscan.identify(in_sleeve(data), limit=3)
            self.assertTrue(found, card_id)
            self.assertEqual(found[0]["card_id"], card_id,
                             "%s узналась как %s" % (card_id, found[0]["card_id"]))

    def test_a_loose_sleeve_too(self):
        for card_id, data in list(self.cards.items())[:8]:
            found = artscan.identify(in_sleeve(data, loose=True), limit=3)
            self.assertEqual(found[0]["card_id"], card_id, card_id)

    def test_the_answer_says_which_framing_won(self):
        card_id, data = next(iter(self.cards.items()))
        self.assertEqual(artscan.identify(data, limit=3)[0]["framing"],
                         "без протектора")
        self.assertIn("протектор",
                      artscan.identify(in_sleeve(data), limit=3)[0]["framing"])

    def test_the_sleeve_framing_reads_much_closer_than_the_plain_one(self):
        """Ради чего всё это.

        «Узналась или нет» на сорока нарисованных картах ничего не показывает:
        в такой базе правильная карта находится и по сдвинутой рамке, за
        неимением других. А вот насколько прочтение ближе к эталону -- видно
        всегда, и на живой базе в сто тысяч именно эта разница решает, попадёт
        ли ответ в порог уверенности.
        """
        gains = []
        for card_id, data in list(self.cards.items())[:12]:
            with Image.open(io.BytesIO(in_sleeve(data))) as img:
                img.load()
                plain = artscan.crop_art(img)
                fitted = artscan.crop_art(
                    artscan.unsleeve(img, artscan.SLEEVE_INSETS[1][1]))
            far = self.index.match(artscan.phash(plain), artscan.dhash(plain),
                                   limit=1)[0]["distance"]
            near = self.index.match(artscan.phash(fitted), artscan.dhash(fitted),
                                    limit=1)[0]["distance"]
            gains.append(far - near)
        gains.sort()
        middle = gains[len(gains) // 2]
        self.assertGreater(middle, 5,
                           "рамка протектора перестала приближать к эталону: "
                           "выигрыши %s" % gains)

    def test_a_crowded_match_loses_to_one_that_stands_out(self):
        """Правило выбора: не «кто ближе», а «кто заметно ближе остальных».

        Если брать наименьшее расстояние, побеждает мимо снятая рамка: среди
        ста тысяч отпечатков ближайший сосед находится всегда.
        """
        crowded = [{"oracle_id": "a", "distance": 9},
                   {"oracle_id": "b", "distance": 11}]
        lonely = [{"oracle_id": "c", "distance": 14},
                  {"oracle_id": "d", "distance": 40}]
        self.assertGreater(artscan.quality(lonely), artscan.quality(crowded))

    def test_a_reprint_is_not_counted_as_a_rival(self):
        """Соседняя печать той же карты -- это она сама, а не соперник."""
        same = [{"oracle_id": "a", "distance": 4},
                {"oracle_id": "a", "distance": 4},
                {"oracle_id": "b", "distance": 30}]
        self.assertIsNotNone(artscan.rival_of(same))
        self.assertEqual(artscan.rival_of(same)["oracle_id"], "b")
        self.assertTrue(artscan.quality(same)[0])


class TestStatusWithoutDatabase(unittest.TestCase):
    def test_it_says_what_is_missing_rather_than_failing(self):
        state = artscan.status(os.path.join(tempfile.gettempdir(), "нет-такого.sqlite"))
        self.assertFalse(state["built"])
        self.assertEqual(state["hashed"], 0)


if __name__ == "__main__":
    unittest.main()

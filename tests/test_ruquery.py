"""Русская фраза -> запрос на языке программы.

Заведено после замера: «поиск по-русски ничего не находит» оказалось
неточностью -- по именам он ищет («Лес» даёт 60 карт), а вот «зелёная рампа»
не находится и не может: так не называется ни одна карта. Это описание, и
перевести его должна программа.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ruquery                                   # noqa: E402
from app.main import _RU_THEMES, KEYWORD_PRESETS, THEME_PRESETS  # noqa: E402


def say(q):
    return ruquery.translate(q, _RU_THEMES, KEYWORD_PRESETS)


class Translate(unittest.TestCase):

    def test_colour_and_theme(self):
        """Та самая фраза, на которой человек споткнулся."""
        got = say("зелёная рампа")
        self.assertEqual(got["query"], "c:g otag:ramp")
        self.assertEqual(got["unknown"], [])

    def test_declension(self):
        """Русский склоняется, а запрос печатают как придётся."""
        for q in ("зелёную рампу", "зеленая рампа", "рампа зелёная"):
            self.assertEqual(say(q)["query"], "c:g otag:ramp", q)

    def test_longer_label_wins(self):
        """«Масс-удаление» -- не «удаление»: это разные метки.

        Сказали точно -- получили точное. Сказали одним словом -- получили
        широкую метку, а не одну из двух узких наугад.
        """
        self.assertEqual(say("масс-удаление")["query"], "otag:sweeper")
        self.assertEqual(say("точечное удаление")["query"], "otag:spot-removal")
        self.assertEqual(say("удаление")["query"], "otag:removal")

    def test_two_word_label_needs_both_words(self):
        """«Кража» одна -- ещё не «кража существ»: есть и «смена контроля»."""
        self.assertEqual(say("кража существ")["query"], "otag:theft-creature")
        self.assertIsNone(say("кража"))

    def test_keyword(self):
        got = say("зелёные дефендеры")
        self.assertEqual(got["query"], "c:g kw:defender")

    def test_unknown_words_are_named(self):
        """Молча выкинуть слово -- значит ответить не на тот вопрос."""
        got = say("зелёная рампа подешевле для кухонного стола")
        self.assertEqual(got["query"], "c:g otag:ramp")
        self.assertIn("подешевле", got["unknown"])
        self.assertNotIn("для", got["unknown"])   # служебное слово -- не «не понял»

    def test_english_is_left_alone(self):
        """Английский запрос язык программы уже понимает сам."""
        self.assertIsNone(say("ramp"))
        self.assertIsNone(say("otag:ramp c:g"))

    def test_russian_name_is_not_translated(self):
        """«Лес» -- имя карты, а не назначение: переводить нечего."""
        self.assertIsNone(say("Лес"))
        self.assertIsNone(say("Погребальный"))

    def test_nothing_to_offer(self):
        self.assertIsNone(say(""))
        self.assertIsNone(say("   "))

    def test_vocabulary_is_the_panel_vocabulary(self):
        """Словарь не свой: он тот же, по которому нарисована панель.

        Если список меток в панели поправят, перевод поедет вместе с ним --
        и это нужное поведение, а не случайность.
        """
        labels = {label for label, _ in _RU_THEMES}
        self.assertIn("рампа", labels)
        for label, _slug in _RU_THEMES:
            got = say(label)
            self.assertIsNotNone(got, label)


if __name__ == "__main__":
    unittest.main()

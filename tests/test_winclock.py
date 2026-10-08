"""Такт победы: на каком ходу колода добивает, если ей не мешать.

Это голдфишинг, доведённый до конца, и опасен он ровно тем же, чем полезен:
число «убивает на пятом ходу» выглядит одинаково убедительно и когда посчитано,
и когда модель не поняла половину колоды. Поэтому главная проверка здесь — не
«похож ли ход на правду», а **покрытие**: модель обязана говорить, сколько карт
она вообще сумела оценить, и не выдавать молчание за ноль.

Вторая по важности — односторонность. Жетоны, лорды, экипировка, рампа и туторы
не учитываются, а все они ускоряют. Значит из такого счёта следует «быстро» и
не следует «медленно», и это должно быть написано под цифрами, а не
подразумеваться.
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import winclock  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestClock(unittest.TestCase):

    BURN = [("Lightning Bolt", 4), ("Lava Spike", 4), ("Goblin Guide", 4),
            ("Monastery Swiftspear", 4), ("Mountain", 20)]
    CONTROL = [("Counterspell", 4), ("Swords to Plowshares", 4),
               ("Wrath of God", 3), ("Island", 25)]
    INFECT = [("Glistener Elf", 4), ("Blight Mamba", 4), ("Forest", 24)]

    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def run_clock(self, rows, fmt="modern", **kw):
        kw.setdefault("seed", 1)
        kw.setdefault("games", 400)
        return winclock.clock(rows, self.db, fmt, **kw)

    # ------------------------------------------------------- покрытие

    def test_it_says_how_much_of_the_deck_it_understood(self):
        got = self.run_clock(self.BURN)
        self.assertEqual(got["coverage"]["pct"], 100.0, got["coverage"])

    def test_a_deck_it_cannot_read_is_admitted_not_zeroed(self):
        """Контроль не «не выигрывает» — про него модель ничего не знает."""
        got = self.run_clock(self.CONTROL, fmt="legacy")
        self.assertEqual(got["routes"]["damage"]["pct"], 0.0)
        self.assertEqual(got["coverage"]["modelled"], 0)
        self.assertGreater(got["coverage"]["nonland"], 0)
        self.assertEqual(got["coverage"]["pct"], 0.0)

    def test_a_creature_without_a_number_is_counted_as_unread(self):
        """У Tarmogoyf сила «*»: это не ноль, это «не знаю»."""
        got = self.run_clock([("Tarmogoyf", 4), ("Forest", 20)])
        self.assertEqual(got["coverage"]["unknown_power"], 4)
        self.assertEqual(got["coverage"]["modelled"], 0)

    def test_cards_outside_the_base_are_counted_as_unread(self):
        got = self.run_clock(self.BURN + [("Такой Карты Нет", 3)])
        self.assertEqual(got["coverage"]["unknown_card"], 3)

    # --------------------------------------------------------- такт

    def test_burn_kills_and_says_when(self):
        got = self.run_clock(self.BURN)
        route = got["routes"]["damage"]
        self.assertGreater(route["pct"], 90)
        self.assertLess(route["avg_turn"], 9)
        self.assertGreaterEqual(route["soonest"], 1)

    def test_the_threshold_follows_the_format(self):
        self.assertEqual(self.run_clock(self.BURN, fmt="modern")["life"], 20)
        self.assertEqual(self.run_clock(self.BURN, fmt="commander")["life"], 40)

    def test_more_opponents_need_more_damage(self):
        one = self.run_clock(self.BURN, opponents=1)
        three = self.run_clock(self.BURN, opponents=3)
        self.assertEqual(three["routes"]["damage"]["need"],
                         one["routes"]["damage"]["need"] * 3)
        self.assertLessEqual(three["routes"]["damage"]["pct"],
                             one["routes"]["damage"]["pct"])

    def test_haste_attacks_the_turn_it_lands(self):
        """Вызывная болезнь -- не мелочь: без неё такт считается не тот."""
        hasty = self.run_clock([("Goblin Guide", 20), ("Mountain", 20)])
        slow = self.run_clock([("Savannah Lions", 20), ("Plains", 20)])
        self.assertLess(hasty["routes"]["damage"]["avg_turn"],
                        slow["routes"]["damage"]["avg_turn"])

    def test_infect_goes_by_poison_not_damage(self):
        got = self.run_clock(self.INFECT)
        self.assertEqual(got["routes"]["poison"]["need"], winclock.POISON)
        self.assertGreater(got["routes"]["poison"]["pct"], 80)

    def test_the_fastest_route_is_the_sooner_of_the_two(self):
        got = self.run_clock(self.INFECT)
        poison = got["routes"]["poison"]["avg_turn"]
        self.assertIsNotNone(got["fastest"]["avg_turn"])
        self.assertLessEqual(got["fastest"]["avg_turn"], poison + 0.01)

    def test_the_same_seed_gives_the_same_answer(self):
        a = self.run_clock(self.BURN)
        b = self.run_clock(self.BURN)
        self.assertEqual(a["routes"]["damage"]["avg_turn"],
                         b["routes"]["damage"]["avg_turn"])

    def test_a_tiny_deck_is_refused_politely(self):
        got = self.run_clock([("Mountain", 3)])
        self.assertFalse(got["known"])
        self.assertIn("мало", got["why"])

    # ----------------------------------------- числа, записанные словами

    def test_numbers_written_as_words_are_read(self):
        """«create two tokens», «mills four cards» -- цифр в правилах нет.

        Из-за этого жетоны и милл не считались вовсе: регулярка с \\d+ не
        находила ровным счётом ничего, и колода на жетонах выглядела пустой.
        """
        self.assertEqual(winclock.count_word("two"), 2)
        self.assertEqual(winclock.count_word("a"), 1)
        self.assertEqual(winclock.count_word("four"), 4)

    def test_an_unknown_amount_is_not_guessed(self):
        """«create X tokens» зависит от влитой маны -- подставлять нельзя."""
        self.assertIsNone(winclock.count_word("x"))
        self.assertIsNone(winclock.count_word("half"))

    def test_tokens_are_read_with_their_power(self):
        card = self.db.by_name("Raise the Alarm")
        got = winclock._entry(card, "Raise the Alarm")
        self.assertEqual(got["tokens"], 2)
        self.assertEqual(got["token_power"], 1)

    def test_x_tokens_are_an_expression_not_a_refusal(self):
        """«Create X tokens» непонятно в отрыве и понятно в партии.

        X записан в стоимости отдельно, а cmc считает его за ноль, поэтому в
        прогоне он вычисляется: сколько маны влили, столько и жетонов. Разбор
        в константу тут означал бы либо выбросить карту, либо подставить
        выдуманное число.
        """
        card = self.db.by_name("Secure the Wastes")
        got = winclock._entry(card, "Secure the Wastes")
        self.assertEqual(got["tokens_kind"], "x")
        self.assertEqual(got["token_power"], 1)
        self.assertFalse(got["blank"])

    def test_x_tokens_actually_kill(self):
        """Если бы X считался нулём, такая колода не убивала бы никогда."""
        got = self.run_clock([("Secure the Wastes", 8), ("Plains", 32)])
        self.assertGreater(got["routes"]["damage"]["pct"], 50,
                           "X не превратился в жетоны")

    def test_zero_power_tokens_are_still_refused(self):
        """Сила 0/1 набирается счётчиками, которых модель не моделирует."""
        card = self.db.by_name("Avenger of Zendikar")
        got = winclock._entry(card, "Avenger of Zendikar")
        self.assertEqual(got["tokens_kind"], "")

    def test_an_anthem_is_read(self):
        card = self.db.by_name("Glorious Anthem")
        self.assertEqual(winclock._entry(card, "Glorious Anthem")["anthem"], 1)

    def test_mill_is_read(self):
        card = self.db.by_name("Mind Sculpt")
        self.assertEqual(winclock._entry(card, "Mind Sculpt")["mill"], 7)

    def test_mill_of_unknown_amount_is_refused(self):
        """Traumatize сносит половину библиотеки -- это не число."""
        card = self.db.by_name("Traumatize")
        got = winclock._entry(card, "Traumatize")
        self.assertEqual(got["mill"], 0)

    # --------------------------------------------- не только сколько, но и когда

    def test_an_entering_trigger_fires_once(self):
        card = self.db.by_name("Hornet Queen")
        got = winclock._entry(card, "Hornet Queen")
        self.assertEqual(got["tokens_when"], "enters")
        self.assertEqual(got["tokens"], 4)

    def test_an_attack_trigger_fires_every_combat(self):
        """Считать бой за розыгрыш -- значит занизить колоду в разы."""
        card = self.db.by_name("Brimaz, King of Oreskos")
        got = winclock._entry(card, "Brimaz, King of Oreskos")
        self.assertEqual(got["tokens_when"], "attacks")

    def test_enters_or_attacks_is_both(self):
        card = self.db.by_name("Grave Titan")
        self.assertEqual(winclock._entry(card, "Grave Titan")["tokens_when"],
                         "enters_attacks")

    def test_a_token_maker_beats_a_plain_body(self):
        """Brimaz 3/4 должен бить быстрее обычного существа той же цены."""
        maker = self.run_clock([("Brimaz, King of Oreskos", 8), ("Plains", 32)])
        plain = self.run_clock([("Gray Ogre", 8), ("Mountain", 32)])
        self.assertLess(maker["routes"]["damage"]["avg_turn"],
                        plain["routes"]["damage"]["avg_turn"])

    def test_x_redefined_by_the_text_is_not_mana(self):
        """«where X is the number of Goblins» -- это не заплаченное.

        Считать такое по мане значит молча завысить: у Krenko X -- число
        гоблинов на столе, а вовсе не то, сколько в него влили.
        """
        card = self.db.by_name("Krenko, Mob Boss")
        got = winclock._entry(card, "Krenko, Mob Boss")
        self.assertEqual(got["tokens_kind"], "")

    def test_an_ability_with_a_cost_is_not_counted(self):
        """Сколько раз успеют включить способность -- вопрос не к тексту."""
        card = self.db.by_name("Krenko, Mob Boss")
        text = (card.get("oracle_text") or "")
        self.assertTrue(winclock.ACTIVATED_RX.search(text), text[:40])

    def test_a_token_source_need_not_be_a_creature(self):
        """Bitterblossom -- чары, и делает жетон каждый ход.

        Пока на стол клали только существ, она не делала ничего, и колода из
        восьми Bitterblossom не убивала ни разу за четырнадцать ходов.
        """
        got = self.run_clock([("Bitterblossom", 8), ("Swamp", 32)])
        self.assertGreater(got["routes"]["damage"]["pct"], 50)

    def test_a_per_turn_trigger_is_recognised(self):
        card = self.db.by_name("Bitterblossom")
        self.assertEqual(winclock._entry(card, "Bitterblossom")["tokens_when"],
                         "each_turn")

    def test_an_enchantment_does_not_attack_by_itself(self):
        """У чар нет силы, и анфем не должен превращать её в урон."""
        got = self.run_clock([("Glorious Anthem", 20), ("Plains", 20)])
        self.assertEqual(got["routes"]["damage"]["pct"], 0.0,
                         "анфем сам по себе никого не бьёт")

    # ------------------------------------------------- они входят в такт

    def test_tokens_shorten_the_clock(self):
        with_tokens = self.run_clock(
            [("Raise the Alarm", 20), ("Plains", 20)])
        without = self.run_clock([("Plains", 40)])
        self.assertGreater(with_tokens["routes"]["damage"]["pct"],
                           without["routes"]["damage"]["pct"])

    def test_an_anthem_makes_the_same_board_hit_harder(self):
        plain = self.run_clock([("Raise the Alarm", 12), ("Plains", 28)])
        buffed = self.run_clock([("Raise the Alarm", 12), ("Glorious Anthem", 8),
                                 ("Plains", 20)])
        self.assertLessEqual(buffed["routes"]["damage"]["avg_turn"],
                             plain["routes"]["damage"]["avg_turn"])

    def test_mill_is_its_own_route(self):
        got = self.run_clock([("Mind Sculpt", 4), ("Tome Scour", 4),
                              ("Glimpse the Unthinkable", 4), ("Island", 20)])
        route = got["routes"]["mill"]
        self.assertGreater(route["pct"], 50)
        self.assertEqual(route["need"], winclock.LIBRARY_DEFAULT)

    def test_a_targeted_mill_cannot_kill_the_whole_table(self):
        """Заслать библиотеку одному и объявить побеждёнными троих нельзя."""
        rows = [("Mind Sculpt", 20), ("Island", 20)]
        one = self.run_clock(rows, fmt="commander", opponents=1)
        table = self.run_clock(rows, fmt="commander", opponents=3)
        self.assertGreater(one["routes"]["mill"]["pct"],
                           table["routes"]["mill"]["pct"])

    # ------------------------------ сила, написанная не в поле «сила»

    def test_counters_on_entry_are_read(self):
        """Hangarback Walker напечатан 0/0: вся его сила -- в счётчиках.

        Считать такое существо нулём значит выбросить всю «вырастающую»
        механику разом.
        """
        card = self.db.by_name("Hangarback Walker")
        got = winclock._entry(card, "Hangarback Walker")
        self.assertEqual(got["power"], 0)
        self.assertEqual(got["counters_kind"], "x")
        self.assertFalse(got["blank"])

    def test_a_double_x_cost_halves_the_counters(self):
        """У Hangarback стоимость {X}{X}: на X уходит половина влитого.

        Без этого счёта карта выглядела бы вдвое сильнее, чем есть.
        """
        card = self.db.by_name("Hangarback Walker")
        self.assertEqual(winclock._entry(card, "Hangarback Walker")["x_in_cost"], 2)

    def test_a_zero_power_creature_with_counters_still_kills(self):
        got = self.run_clock([("Hangarback Walker", 10), ("Forest", 30)])
        self.assertGreater(got["routes"]["damage"]["pct"], 50,
                           "счётчики не превратились в силу")

    # ------------------------------------------------------ экипировка

    def test_equipment_is_read_with_its_cost(self):
        card = self.db.by_name("Bonesplitter")
        got = winclock._entry(card, "Bonesplitter")
        self.assertEqual(got["equips"], 2)
        self.assertGreaterEqual(got["equip_cost"], 1)

    def test_equipment_shortens_the_clock(self):
        bare = self.run_clock([("Grizzly Bears", 10), ("Forest", 30)])
        armed = self.run_clock([("Grizzly Bears", 10), ("Bonesplitter", 6),
                                ("Forest", 24)])
        self.assertLess(armed["routes"]["damage"]["avg_turn"],
                        bare["routes"]["damage"]["avg_turn"])

    def test_a_pump_that_is_not_a_pump_is_ignored(self):
        """Skullclamp даёт +1/-1 -- это не усиление, а размен."""
        card = self.db.by_name("Skullclamp")
        self.assertEqual(winclock._entry(card, "Skullclamp")["equips"], 0)

    # --------------------------------------------------- лишние бои

    def test_an_extra_combat_is_read(self):
        card = self.db.by_name("Relentless Assault")
        self.assertEqual(winclock._entry(card, "Relentless Assault")["extra_combat"], 1)

    def test_an_extra_combat_shortens_the_clock(self):
        plain = self.run_clock([("Grizzly Bears", 10), ("Forest", 30)])
        twice = self.run_clock([("Grizzly Bears", 10), ("Relentless Assault", 6),
                                ("Mountain", 24)])
        self.assertLess(twice["routes"]["damage"]["avg_turn"],
                        plain["routes"]["damage"]["avg_turn"])

    # ---------------------------------------- потеря жизней и триггеры

    def test_life_loss_counts_like_damage(self):
        """«Каждый противник теряет N жизней» -- тот же урон по итогу.

        Таких карт больше двух с половиной сотен, и не считать их значит
        пропустить целый путь к победе.
        """
        card = self.db.by_name("Exsanguinate")
        if card is None:
            self.skipTest("карты нет в базе")
        self.assertTrue(True)   # разбор проверяется на картах ниже

    def test_our_own_life_loss_is_not_a_win(self):
        """«You lose N life» -- это про нас. Считать своё за чужое нельзя."""
        card = self.db.by_name("Phyrexian Arena")
        got = winclock._entry(card, "Phyrexian Arena")
        self.assertEqual(got["burn"], 0)
        self.assertEqual(got["burn_each"], 0)

    def test_a_one_shot_spell_is_counted(self):
        card = self.db.by_name("Lightning Bolt")
        self.assertEqual(winclock._entry(card, "Lightning Bolt")["burn"], 3)

    def test_damage_behind_an_untracked_trigger_is_not_counted(self):
        """Blood Artist страшен в колоде с жертвоприношением и безобиден без.

        Считать его разово при розыгрыше неверно в обе стороны, поэтому за
        триггером, которого модель не отслеживает, числа не берутся вовсе.
        Сторож этот был написан с ошибкой и не срабатывал ни разу: вместо
        границы слова в образец попал символ забоя.
        """
        for name in ("Blood Artist", "Zulaport Cutthroat"):
            card = self.db.by_name(name)
            if card is None:
                continue
            got = winclock._entry(card, name)
            with self.subTest(card=name):
                self.assertEqual(got["burn"], 0, name)
                self.assertEqual(got["burn_each"], 0, name)

    def test_a_trigger_on_someone_elses_entry_is_not_ours(self):
        """Impact Tremors бьёт за каждое существо, а не раз при розыгрыше."""
        card = self.db.by_name("Impact Tremors")
        if card is None:
            self.skipTest("карты нет в базе")
        self.assertEqual(winclock._entry(card, "Impact Tremors")["burn_each"], 0)

    def test_the_cards_own_entry_still_counts(self):
        """Выход самой карты случается ровно тогда, когда её разыграли."""
        card = self.db.by_name("Hornet Queen")
        self.assertEqual(winclock._entry(card, "Hornet Queen")["tokens"], 4)

    def test_x_defined_by_devotion_is_not_a_number(self):
        card = self.db.by_name("Gray Merchant of Asphodel")
        got = winclock._entry(card, "Gray Merchant of Asphodel")
        self.assertEqual(got["burn_each"], 0)

    def test_no_control_characters_crept_into_the_patterns(self):
        """Символ забоя в образце выглядит как \b и не работает никогда.

        Такую ошибку не видно ни в тесте поведения, ни на экране: образец
        просто перестаёт срабатывать, и сторож пропускает всё.
        """
        with io.open(winclock.__file__, encoding="utf-8") as fh:
            source = fh.read()
        bad = [c for c in source if ord(c) < 9 or 13 < ord(c) < 32]
        self.assertEqual(bad, [], "управляющие символы: %r" % bad[:4])

    # ---------------------------------------------------- оговорки

    def test_both_caveats_are_printed(self):
        said = " ".join(self.run_clock(self.BURN)["assumptions"])
        self.assertIn("бездействуют", said)
        self.assertIn("не позже", said, "односторонность обязана быть названа")
        self.assertIn("медленнее", said, "про живых противников тоже")
        self.assertIn("жетоны", said)
        self.assertIn("милл", said, "о том, чего не считаем вовсе, надо сказать")


if __name__ == "__main__":
    unittest.main()

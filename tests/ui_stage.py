"""Общее для браузерных сценариев: признак сцены и сбор выборки.

Половина экранов программы считается по выборке чужих колод, а собирается
выборка с Archidekt -- то есть по сети. Сценарию ходить наружу нельзя: это
чужой сайт, и проверка, которая стучится туда на каждый запуск сборки, --
нагрузка на чужой сервер, а не проверка.

Выход -- `tests/stage.py`: она поднимает программу с подменённым сборщиком,
который выдумывает колоды на месте. Но сценарий сам по себе не знает, против
чего он работает: против сцены, где собирать безопасно, или против настоящей
программы, где нажатие уйдёт в интернет.

Отсюда переменная окружения. Её ставит тот, кто запускает:

    MTGH_UI_STAGE=1 MTGH_UI_BASE=http://127.0.0.1:8799 python tests/ui_x.py

Без неё сценарий ничего не собирает и честно говорит, что проверять нечего.
Знание «здесь собирать безопасно» лежит у запускающего, а не внутри
программы: в самой программе никакого «режима проверки» нет и не будет.
"""

from __future__ import annotations

import os

STAGE = os.environ.get("MTGH_UI_STAGE") == "1"


def gather(page, deck_id: str = "", cards: list[str] | None = None,
           target: int = 60) -> dict:
    """Собрать выборку под колоду или под отмеченные карты.

    Возвращает ответ сервера; пустой словарь -- если собирать нельзя
    (не сцена) или сервер отказал.
    """
    if not STAGE:
        return {}
    return page.evaluate(
        """async ([id, cards, target]) => {
          try {
            return await fetch('/api/cooccur/collect', {method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({deck_id: id || null, cards: cards || [],
                                    target: target})
            }).then(r => r.json());
          } catch (e) { return {}; }
        }""", [deck_id, cards or [], target])


def have_sample(page, deck_id: str = "", cards: list[str] | None = None) -> int:
    """Сколько колод уже лежит в выборке для этой колоды и этих карт."""
    return page.evaluate(
        """async ([id, cards]) => {
          const q = '/api/cooccur/status?deck_id=' + encodeURIComponent(id) +
            (cards && cards.length
              ? '&cards=' + encodeURIComponent(cards.join('|')) : '');
          try {
            const s = await fetch(q).then(r => r.json());
            return s.decks || 0;
          } catch (e) { return 0; }
        }""", [deck_id, cards or []])


def ensure_sample(page, deck_id: str = "", cards: list[str] | None = None,
                  target: int = 60) -> int:
    """Выборка под эту колоду, собранная при надобности. Отдаёт число колод."""
    have = have_sample(page, deck_id, cards)
    if have:
        return have
    gather(page, deck_id, cards, target)
    return have_sample(page, deck_id, cards)

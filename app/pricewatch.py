"""Дополнять рублёвые цены понемногу.

Узнать цену одной карты -- это один запрос к topdeck и вежливые полторы
секунды. Для колоды на сто карт это двадцать секунд, и нажать кнопку не жалко.
Для коллекции в две тысячи это сорок минут сплошного стука в чужой сервер --
так не делают.

Поэтому здесь другое: медленное дополнение. Раз в полминуты уходит один
запрос на горстку карт, и цены набираются сами, пока программа открыта. За час
это около девятисот карт -- коллекция в две тысячи наберётся за вечер, и
никто этого не заметит.

Правила, которые не меняются:

  * **только по вашему согласию.** Выключатель на виду, состояние помнится, и
    пока он выключен, наружу не уходит ни одного запроса;
  * **очередь по делу.** Сначала карты, цены которых нет вовсе; потом те, у
    которых цена записана одним числом на имя, без разбора по версиям -- о
    таком числе неизвестно, фойл это, убитая копия или обычная карта; потом
    те, что давно не проверялись. Свежие и разобранные не трогаются: цена на
    topdeck не меняется ежечасно;
  * **пауза между запросами настоящая.** Клиент topdeck и сам держит полторы
    секунды между обращениями, а здесь сверх того пауза в полминуты: это не
    «сканирование», а фоновое дополнение;
  * **останавливается сразу.** Выключили -- поток дорабатывает текущую горстку
    и встаёт.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .cards import normalize_name

# Сколько карт в одном запросе и сколько ждать между запросами. Числа
# подобраны так, чтобы дополнение было незаметным: горстка карт раз в
# полминуты -- это около девятисот карт в час.
BATCH = 6
PAUSE_SECONDS = 30.0
# Цена старше этого срока считается устаревшей и обновляется заново.
STALE_DAYS = 21


class PriceWatch:
    """Фоновое дополнение цен. Один на программу."""

    def __init__(self, refresh: Callable[..., dict[str, Any]],
                 names: Callable[[], list[str]],
                 store: Callable[[], Any],
                 db: Callable[[], Any],
                 client: Callable[[], Any],
                 pause: float = PAUSE_SECONDS,
                 sets: Callable[[], Any] | None = None) -> None:
        self._refresh = refresh
        self._names = names
        self._store = store
        self._db = db
        self._client = client
        # Чтобы разложить цену по версиям, нужен указатель наборов. Его
        # может не быть (в проверках его и не передают) -- тогда цены
        # запоминаются как раньше, одним числом на имя.
        self._sets = sets
        self._pause = pause
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Про что разбор по версиям уже спрашивали в этот запуск. Нужно от
        # вечного круга: у продавца может не найтись ни одного объявления,
        # которое программа сумеет разобрать, -- и тогда карта так и
        # останется без версий, сколько её ни спрашивай. Спросили раз --
        # дальше она ждёт своей очереди по сроку, как все.
        self._split_tried: set[str] = set()
        self._state: dict[str, Any] = {
            "running": False, "done": 0, "left": 0, "updated": 0,
            "current": "", "started_at": "", "last_error": "", "last_at": "",
        }

    # ------------------------------------------------------------ очередь
    def queue(self) -> dict[str, list[str]]:
        """Очередь по ступеням: нет цены, нет разбора, цена устарела.

        Средняя ступень -- не выдумка, а то, что нашлось на живых данных: в
        базе лежали сто семьдесят цен, узнанных прежними версиями программы,
        одним числом на имя. Пока такую цену не спросят заново, непонятно,
        к чему она относится, -- а спросить её было некому: «цена есть» и
        «цена свежая» для старой очереди значило «трогать не надо». Теперь
        такие цены дополняются сами, вместе со всем остальным.
        """
        store = self._store()
        names = self._names()
        known = store.get_prices(names)
        # Разбор по версиям хранится отдельной таблицей, и в проверках
        # встречается store без неё -- тогда обходимся без средней ступени.
        splits: set[str] = set()
        reader = getattr(store, "names_with_variants", None)
        can_split = callable(reader)
        if can_split:
            try:
                splits = set(reader(names) or ())
            except Exception:  # noqa: BLE001
                can_split = False
        edge = time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(time.time() - STALE_DAYS * 86400))
        unknown: list[str] = []
        unsplit: list[tuple[str, str]] = []
        stale: list[tuple[str, str]] = []
        for name in names:
            key = normalize_name(name)
            row = known.get(key)
            if not row or row.get("rub_min") is None and not row.get("checked_at"):
                unknown.append(name)
                continue
            when = row.get("checked_at") or ""
            # Спрашивали и не нашлось -- это ответ, и разбирать там нечего:
            # такая карта ждёт своей очереди по сроку, как все.
            if (can_split and row.get("rub_min") is not None
                    and key not in splits and key not in self._split_tried):
                unsplit.append((when, name))
            elif when < edge:
                stale.append((when, name))
        unsplit.sort()
        stale.sort()
        return {
            "unknown": unknown,
            "unsplit": [name for _when, name in unsplit],
            "stale": [name for _when, name in stale],
        }

    def pending(self) -> list[str]:
        """Что стоит спросить -- одним списком, в порядке очереди."""
        queue = self.queue()
        return queue["unknown"] + queue["unsplit"] + queue["stale"]

    # -------------------------------------------------------------- работа
    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        state["pause"] = self._pause
        state["batch"] = BATCH
        if not state["running"]:
            queue = self.queue()
            state["left"] = sum(len(part) for part in queue.values())
            # По ступеням -- чтобы на экране было сказано, чего именно ждут:
            # «не спрошено 16» и «у 154 цена без разбора по версиям» это
            # разные новости, и вторая не должна выглядеть как первая.
            state["unknown"] = len(queue["unknown"])
            state["unsplit"] = len(queue["unsplit"])
            state["stale"] = len(queue["stale"])
        return state

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._state["running"]:
                return dict(self._state)
            self._stop.clear()
            self._state.update({
                "running": True, "done": 0, "updated": 0, "current": "",
                "last_error": "",
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        # Отвечаем свежим состоянием, а не тем, что лежало в памяти: число
        # оставшихся считается заново, иначе оно врёт сразу после нажатия.
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            self._state["running"] = False
        return self.status()

    def join(self, timeout: float = 5.0) -> None:
        """Дождаться, пока поток действительно встанет.

        Нужно не только тестам: остановка без ожидания оставляет за собой
        поток, который ещё держит базу, -- и следующая же запись упирается в
        «database is locked».
        """
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def _run(self) -> None:
        try:
            # Первая пауза -- до первого запроса, а не после. Программа
            # открылась -- наружу в эту же секунду никто не стучится.
            if self._stop.wait(self._pause):
                return
            while not self._stop.is_set():
                queue = self.pending()
                with self._lock:
                    self._state["left"] = len(queue)
                if not queue:
                    break
                batch = queue[:BATCH]
                with self._lock:
                    self._state["current"] = ", ".join(batch[:3])
                # Спросили -- значит про разбор версий этой карты вопрос
                # закрыт до следующего срока, нашёлся он или нет.
                self._split_tried.update(normalize_name(n) for n in batch)
                try:
                    report = self._refresh(batch, self._store(), self._db(),
                                           self._client(),
                                           set_index=self._sets() if self._sets
                                           else None)
                except Exception as exc:                     # noqa: BLE001
                    with self._lock:
                        self._state["last_error"] = str(exc)[:200]
                    # Чужой сервер мог просто икнуть -- ждём дольше обычного и
                    # пробуем снова, а не бросаем работу совсем.
                    if self._stop.wait(self._pause * 4):
                        break
                    continue
                with self._lock:
                    self._state["done"] += len(batch)
                    self._state["updated"] += int(report.get("updated") or 0)
                    self._state["last_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if self._stop.wait(self._pause):
                    break
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["current"] = ""


__all__ = ["BATCH", "PAUSE_SECONDS", "STALE_DAYS", "PriceWatch"]

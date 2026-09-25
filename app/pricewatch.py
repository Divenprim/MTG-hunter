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
  * **очередь по делу.** Сначала карты, цены которых нет вовсе, потом те, что
    давно не проверялись. Свежие не трогаются: цена на topdeck не меняется
    ежечасно;
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
                 pause: float = PAUSE_SECONDS) -> None:
        self._refresh = refresh
        self._names = names
        self._store = store
        self._db = db
        self._client = client
        self._pause = pause
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state: dict[str, Any] = {
            "running": False, "done": 0, "left": 0, "updated": 0,
            "current": "", "started_at": "", "last_error": "", "last_at": "",
        }

    # ------------------------------------------------------------ очередь
    def pending(self) -> list[str]:
        """Что стоит спросить: сперва неизвестное, потом давно не смотренное."""
        store = self._store()
        known = store.get_prices(self._names())
        edge = time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(time.time() - STALE_DAYS * 86400))
        unknown: list[str] = []
        stale: list[tuple[str, str]] = []
        for name in self._names():
            row = known.get((name or "").strip().lower())
            if not row or row.get("rub_min") is None and not row.get("checked_at"):
                unknown.append(name)
            elif (row.get("checked_at") or "") < edge:
                stale.append((row.get("checked_at") or "", name))
        stale.sort()
        return unknown + [name for _when, name in stale]

    # -------------------------------------------------------------- работа
    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        state["pause"] = self._pause
        state["batch"] = BATCH
        if not state["running"]:
            state["left"] = len(self.pending())
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
                try:
                    report = self._refresh(batch, self._store(), self._db(),
                                           self._client())
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

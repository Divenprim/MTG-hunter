"""Where user data lives, and how it survives.

Two rules, both learned the hard way:

1. **Tests must never touch real user data.** Set `MTGH_DATA_DIR` and every
   module writes somewhere else. The favourites file was destroyed once by a
   cleanup step that assumed everything in it was test data -- an assumption no
   code should ever be in a position to make.

2. **Every mutation leaves a snapshot behind.** Snapshots live in the same
   SQLite file as the data, are timestamped, and rotate. Losing work then
   requires deleting the database itself, and even that is one file to back up
   rather than several.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

SNAPSHOT_KEEP = 40
_USER_DB_INIT_LOCK = threading.Lock()


# Запись json-файлов идёт по одному писателю на процесс. Вкладок у программы
# бывает несколько, и две из них умеют писать один и тот же файл.
_JSON_WRITE_LOCK = threading.Lock()

# Маленький файл с настройками, последней охотой, отметками -- читается и
# пишется из нескольких мест. Лежало в main.py; здесь ему место, потому что
# запись атомарная через временный файл и os.replace, как и всё остальное
# хранение.
def load_json(path: str, default: Any) -> Any:
    """Прочитать json, не мешая записи.

    Замок тот же, что у записи, и это главное в этой функции. Запись
    подменяет файл, а Windows не даёт подменить файл, который держат открытым
    на чтение; в одном процессе это ровно наши же вкладки -- одна
    перечитывает прошлую охоту, вторая сохраняет новую. Пока чтение идёт под
    тем же замком, они физически не пересекаются, и повторы в `save_json`
    остаются страховкой от чужих процессов, а не повседневностью.

    Файлы здесь маленькие (последняя охота -- 18 КБ), так что замок на чтении
    ничего не стоит.
    """
    try:
        with _JSON_WRITE_LOCK:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


# Сколько раз повторить подмену файла и с какой паузой. Полсекунды суммарно:
# дольше ждать нечего -- чтение, которое держит файл, занимает миллисекунды,
# а если оно длится полсекунды, то дело не в гонке.
REPLACE_TRIES = 6
REPLACE_PAUSE = 0.05


def save_json(path: str, payload: Any) -> None:
    """Записать json так, чтобы запись либо случилась, либо сказала о себе.

    Было: временный файл с постоянным именем и `os.replace`. На Windows
    `os.replace` отказывается подменять файл, который кто-то держит открытым
    на чтение, -- а держит его `GET /api/hunt/last`, то есть ровно та пара,
    что встречается в жизни: одна вкладка перечитывает прошлую охоту, вторая
    сохраняет новую. Замер: 39 отказов из 40 попыток. Никто их не ловил, и
    результат охоты -- полторы секунды запроса на пачку имён -- просто не
    доезжал до диска.

    Три поправки, каждая от своей беды:

    * имя временного файла уникальное. Прежнее было общим, и два писателя
      затирали друг другу черновик, а между `unlink` и `replace` файла не
      существовало вовсе -- читатель в этот момент получал «ничего нет»;
    * `fsync` перед подменой: иначе при выключении питания на месте файла
      окажется пустышка нужной длины;
    * повтор на `PermissionError`. Чтение, которое держит файл, занимает
      миллисекунды, и второй попытки почти всегда хватает.

    Если не вышло и после повторов -- исключение летит наружу. Тихо потерять
    запись хуже, чем сказать о ней.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.%s.tmp" % (path, os.getpid(), threading.get_ident())
    with _JSON_WRITE_LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            last: OSError | None = None
            for attempt in range(REPLACE_TRIES):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError as exc:      # Windows: файл читают
                    last = exc
                    time.sleep(REPLACE_PAUSE * (attempt + 1))
            raise last if last else OSError("не удалось записать %s" % path)
        finally:
            # Черновик не должен оставаться: он наш и больше ничей.
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass


def data_dir() -> str:
    """The directory holding user data. `MTGH_DATA_DIR` overrides it."""
    path = os.environ.get("MTGH_DATA_DIR") or DEFAULT_DATA_DIR
    os.makedirs(path, exist_ok=True)
    return path


def user_db_path() -> str:
    return os.path.join(data_dir(), "user.sqlite")


def connect_user_db(schema: str, path: str | None = None) -> sqlite3.Connection:
    """Open the shared user database without racing another module's setup.

    The home page requests decks, favourites, backups, collection and orders in
    parallel.  On a fresh file those modules must not all switch journal mode
    and create tables at the same instant.
    """
    target = path or user_db_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with _USER_DB_INIT_LOCK:
        conn = sqlite3.connect(target, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(schema)
            return conn
        except Exception:
            conn.close()
            raise


SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT NOT NULL,
    created  TEXT NOT NULL,
    reason   TEXT DEFAULT '',
    payload  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_kind ON snapshots(kind, id DESC);
"""


def snapshot(conn: sqlite3.Connection, kind: str, payload: Any, reason: str = "") -> None:
    """Store a copy of `payload` before it is replaced, then rotate old ones."""
    conn.executescript(SNAPSHOT_SCHEMA)
    with conn:
        conn.execute(
            "INSERT INTO snapshots (kind, created, reason, payload) VALUES (?,?,?,?)",
            (kind, time.strftime("%Y-%m-%d %H:%M:%S"), reason,
             json.dumps(payload, ensure_ascii=False)),
        )
        conn.execute(
            """
            DELETE FROM snapshots
            WHERE kind = ? AND id NOT IN (
                SELECT id FROM snapshots WHERE kind = ? ORDER BY id DESC LIMIT ?
            )
            """,
            (kind, kind, SNAPSHOT_KEEP),
        )


def list_snapshots(conn: sqlite3.Connection, kind: str) -> list[dict[str, Any]]:
    conn.executescript(SNAPSHOT_SCHEMA)
    rows = conn.execute(
        "SELECT id, kind, created, reason, LENGTH(payload) AS size FROM snapshots "
        "WHERE kind = ? ORDER BY id DESC",
        (kind,),
    ).fetchall()
    return [dict(r) for r in rows]


def read_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> Any:
    conn.executescript(SNAPSHOT_SCHEMA)
    row = conn.execute(
        "SELECT payload FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload"])

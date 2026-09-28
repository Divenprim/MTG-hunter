"""Merge independently-built art fingerprint SQLite shards."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Запускается как `python release/merge_art_hashes.py`, и тогда в sys.path
# попадает папка самого скрипта, а не корень репозитория -- пакета `app` из
# неё не видно. Стоило это дорого: шесть шардов отпечатков считались часами и
# успешно, а слияние падало на первой же строке импорта, и готовой базы
# отпечатков не появлялось вовсе. А без неё не собирается ни один релиз:
# сборка требует её обязательным шагом.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import artscan  # noqa: E402


def merge(output: Path, shards: list[Path]) -> dict[str, int | float]:
    if output.exists():
        output.unlink()
    for suffix in ("-wal", "-shm"):
        side = Path(str(output) + suffix)
        if side.exists():
            side.unlink()

    conn = artscan.connect(str(output))
    try:
        for shard in shards:
            src = sqlite3.connect(shard)
            src.row_factory = sqlite3.Row
            try:
                art_rows = src.execute(
                    "SELECT card_id, oracle_id, name, set_code, collector_number, "
                    "phash, dhash FROM art"
                ).fetchall()
                conn.executemany(
                    "INSERT OR REPLACE INTO art "
                    "(card_id, oracle_id, name, set_code, collector_number, phash, dhash) "
                    "VALUES (?,?,?,?,?,?,?)",
                    [tuple(r) for r in art_rows],
                )
                failed_rows = src.execute(
                    "SELECT card_id, reason, at FROM failed"
                ).fetchall()
                conn.executemany(
                    "INSERT OR REPLACE INTO failed (card_id, reason, at) VALUES (?,?,?)",
                    [tuple(r) for r in failed_rows],
                )
                if art_rows:
                    conn.executemany(
                        "DELETE FROM failed WHERE card_id = ?",
                        [(r["card_id"],) for r in art_rows],
                    )
                conn.commit()
            finally:
                src.close()

        hashed = conn.execute("SELECT COUNT(*) FROM art").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM failed").fetchone()[0]
        target = len(artscan.printings_to_hash("all"))
        meta = {
            "scope": "all",
            "target": str(target),
            "hashed": str(hashed),
            "failed": str(failed),
        }
        conn.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            list(meta.items()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES "
            "('built_at', datetime('now'))"
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()

    return {
        "target": target,
        "hashed": hashed,
        "failed": failed,
        "coverage": (hashed / target) if target else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("shards", nargs="+")
    args = parser.parse_args()
    report = merge(Path(args.output), [Path(p) for p in args.shards])
    print(report, flush=True)
    if report["coverage"] < 0.995:
        raise SystemExit("merged art database coverage is below 99.5%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

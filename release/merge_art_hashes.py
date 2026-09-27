"""Merge independently-built art fingerprint SQLite shards."""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from app import artscan


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

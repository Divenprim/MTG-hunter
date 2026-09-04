"""The database must be usable from several threads at once.

FastAPI runs sync route handlers in a thread pool, so a browser loading the page
(several requests in flight) hits the database from different threads. sqlite3
connections are bound to the thread that created them, so one shared connection
raised "SQLite objects created in a thread can only be used in that same
thread" and every search returned HTTP 500.

Sequential single requests almost always reuse one pool thread, which is why
curl testing missed it entirely. Hence this test.
"""

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import CardDB  # noqa: E402

DB = CardDB()


class TestConcurrentAccess(unittest.TestCase):
    def _hammer(self, fn, threads=8):
        errors = []
        results = []
        lock = threading.Lock()

        def run(i):
            try:
                value = fn(i)
                with lock:
                    results.append(value)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append("%s: %s" % (type(exc).__name__, exc))

        workers = [threading.Thread(target=run, args=(i,)) for i in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(30)
        return results, errors

    def test_search_from_many_threads(self):
        queries = ["Lightning Bolt", "Sol Ring", "t:creature c:r", "Удар Молнии",
                   "Petty Theft", "s:clb r:mythic", "cmc>=5 t:dragon", "Tiamat"]
        results, errors = self._hammer(lambda i: len(DB.search(queries[i], limit=5)))
        self.assertEqual(errors, [], "concurrent search failed: %s" % errors)
        self.assertEqual(len(results), len(queries))

    def test_count_from_many_threads(self):
        results, errors = self._hammer(lambda i: DB.count("t:creature"))
        self.assertEqual(errors, [], "concurrent count failed: %s" % errors)
        self.assertTrue(all(r == results[0] for r in results), "counts disagreed: %s" % results)

    def test_by_name_from_many_threads(self):
        results, errors = self._hammer(lambda i: (DB.by_name("Lightning Bolt") or {}).get("name"))
        self.assertEqual(errors, [], "concurrent by_name failed: %s" % errors)
        self.assertTrue(all(r == "Lightning Bolt" for r in results), results)

    def test_each_thread_gets_its_own_connection(self):
        """Every thread gets its own connection, and keeps it.

        Comparing id() of connections from threads that have already finished
        does not work: a dead thread releases its connection and CPython hands
        the freed address to the next object, so two live-and-correct threads
        can report the same id. This test therefore keeps every connection
        referenced and holds all threads at a barrier, so all six exist at the
        same moment and their identities are comparable.
        """
        threads = 6
        barrier = threading.Barrier(threads, timeout=30)
        kept = []
        lock = threading.Lock()

        def grab(i):
            conn = DB.conn
            with lock:
                kept.append(conn)
            barrier.wait()
            # The same thread must be handed the same object every time.
            return conn is DB.conn

        results, errors = self._hammer(grab, threads=threads)
        self.assertEqual(errors, [], "per-thread connection failed: %s" % errors)
        self.assertEqual(len(kept), threads)
        self.assertTrue(all(results), "a thread was handed two different connections")
        self.assertEqual(
            len({id(c) for c in kept}), threads, "connection was shared across threads"
        )

    def test_worker_connection_is_not_the_main_one(self):
        got = []
        thread = threading.Thread(target=lambda: got.append(DB.conn))
        thread.start()
        thread.join(30)
        self.assertTrue(got and got[0] is not DB.conn)


if __name__ == "__main__":
    unittest.main(verbosity=2)

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from assembly_site import service as service_mod
from assembly_site.notes import Notes
from assembly_site.service import Service

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class NotesStorageTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.path = Path(self._t.name) / "a.jsonl"

    def tearDown(self):
        self._t.cleanup()

    def test_two_writers_on_one_file_never_lose_or_tear_lines(self):
        a, b = Notes(self.path), Notes(self.path)        # separate instances: separate in-process locks, like two processes

        def work(n, who):
            for i in range(40):
                n.comment("Q-0001", "%s says %d " % (who, i) + "x" * 300, who)

        ts = [threading.Thread(target=work, args=(a, "ann")), threading.Thread(target=work, args=(b, "bo")),
              threading.Thread(target=work, args=(a, "cy")), threading.Thread(target=work, args=(b, "di"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        lines = self.path.read_text().splitlines()
        self.assertEqual(len(lines), 160)
        self.assertTrue(all(json.loads(l)["op"] == "comment" for l in lines))
        self.assertEqual(len(Notes(self.path).view("Q-0001")["comments"]), 160)

    def test_index_is_one_pass_and_cached_until_the_file_changes(self):
        n = Notes(self.path)
        for t in range(200):
            for i in range(10):
                n._append({"op": "comment", "target": "Q-%04d" % (t + 1), "id": "c%d-%d" % (t, i), "actor": "ann", "text": "t", "parent": None})
        t0 = time.time()
        idx = n.index()
        first = time.time() - t0
        self.assertEqual(len(idx), 200)
        self.assertEqual(idx["Q-0007"]["comments"], 10)
        t0 = time.time()
        for _ in range(50):
            n.index()
            n.view("Q-0100")
        self.assertLess(time.time() - t0, max(0.5, first * 5))      # cached: 100 calls cost about as much as a few
        Notes(self.path).star("Q-0007", "bo", True)                  # another instance writes
        self.assertTrue(n.index()["Q-0007"]["starred"])              # the cache noticed


class RecordCacheTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")
        for i in range(5):
            self.s.capture("question", dict(Q, text="question number %d" % i))

    def tearDown(self):
        self._t.cleanup()

    def test_second_listing_reads_no_record_files(self):
        self.s.records()
        with mock.patch.object(service_mod.json, "loads", wraps=json.loads) as m:
            self.assertEqual(len(self.s.records()), 5)
            self.assertEqual(m.call_count, 0)

    def test_cache_sees_core_changes_and_is_not_poisoned_by_callers(self):
        self.s.records()
        self.s.set("Q-0001", {"region": "Erie"}, [])
        self.assertEqual(self.s.record("Q-0001")["record"]["fields"]["region"], "Erie")
        rec = self.s._load("Q-0002")
        rec["status"] = "failed"                                   # a caller mutating its copy ...
        self.assertEqual([r["status"] for r in self.s.records() if r["id"] == "Q-0002"], ["new"])   # ... must not leak into the cache

import tempfile
import unittest
from pathlib import Path

from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class BulkTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")
        self.out = b / "out"
        self.ids = [self.s.capture("question", dict(Q, text="q%d" % i))["record"]["id"] for i in range(3)]

    def tearDown(self):
        self._t.cleanup()

    def test_preview_writes_nothing_for_every_op(self):
        for op in ("star", "unstar", "hold", "release", "retire", "dispatch"):
            r = self.s.bulk(op, self.ids, reason="why", apply=False)
            self.assertEqual(len(r["results"]), 3)
        self.assertEqual([x["status"] for x in self.s.records()], ["new"] * 3)
        self.assertFalse(self.out.exists() and list(self.out.iterdir()))
        self.assertEqual(self.s.starred(), [])

    def test_star_and_hold_apply(self):
        self.s.bulk("star", self.ids[:2], actor="ann", apply=True)
        self.assertEqual({x["target"] for x in self.s.starred()}, set(self.ids[:2]))
        self.s.bulk("hold", self.ids[:1], reason="wait", actor="ann", apply=True)
        self.assertEqual(self.s.bundles(__import__("datetime").date(2026, 10, 25))["totals"]["held"], 1)
        self.s.bulk("release", self.ids[:1], actor="ann", apply=True)
        self.assertEqual(self.s.bundles(__import__("datetime").date(2026, 10, 25))["totals"]["held"], 0)

    def test_retire_needs_reason_and_reports_each_record(self):
        with self.assertRaises(SiteError):
            self.s.bulk("retire", self.ids, reason=" ", apply=True)
        self.s.retire(self.ids[0], "dup", True)
        r = self.s.bulk("retire", self.ids, reason="cleanup", apply=True)
        self.assertEqual([x["ok"] for x in r["results"]], [False, True, True])     # one failure does not stop the rest
        self.assertEqual((r["ok"], r["failed"]), (2, 1))
        self.assertEqual([x["status"] for x in self.s.records(status="retired")].count("retired"), 3)

    def test_stale_rev_per_record_is_reported_not_applied(self):
        self.s.set(self.ids[0], {"region": "A"}, [])
        r = self.s.bulk("retire", self.ids[:2], reason="x", apply=True, revs={self.ids[0]: 0, self.ids[1]: 0})
        self.assertFalse(r["results"][0]["ok"])
        self.assertIn("changed since", r["results"][0]["errors"][0])
        self.assertTrue(r["results"][1]["ok"])

    def test_dispatch_bulk(self):
        r = self.s.bulk("dispatch", self.ids, apply=False)
        self.assertTrue(all(x["ok"] for x in r["results"]))
        self.assertIn(".md", r["results"][0]["message"])
        r = self.s.bulk("dispatch", self.ids, apply=True)
        self.assertEqual(r["ok"], 3)
        self.assertEqual(len(list(self.out.glob("*.md"))), 3)

    def test_limits_and_validation(self):
        with self.assertRaises(SiteError):
            self.s.bulk("explode", self.ids, apply=False)
        with self.assertRaises(SiteError):
            self.s.bulk("star", [], apply=False)
        with self.assertRaises(SiteError):
            self.s.bulk("star", ["Q-%04d" % i for i in range(1, 52)], apply=False)
        r = self.s.bulk("star", ["Q-9999"], apply=True)
        self.assertFalse(r["results"][0]["ok"])

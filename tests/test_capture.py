import tempfile
import unittest
from pathlib import Path

from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies to 676 King St W?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")

    def tearDown(self):
        self._t.cleanup()

    def test_similar_finds_near_duplicates_and_ignores_retired_and_unrelated(self):
        a = self.s.capture("question", dict(Q))["record"]["id"]
        old = self.s.capture("question", dict(Q, text="Zoning for 676 King Street W, what applies"))["record"]["id"]
        self.s.retire(old, "dup", True)
        self.s.capture("question", dict(Q, text="Which councils changed short term rental bylaws?"))
        sim = self.s.similar("question", dict(Q, text="what zoning applies to 676 King St W"))
        self.assertEqual([x["id"] for x in sim], [a])
        self.assertGreaterEqual(sim[0]["score"], 0.6)

    def test_preview_carries_similar_but_never_blocks(self):
        self.s.capture("question", dict(Q))
        p = self.s.preview_new("question", dict(Q))
        self.assertEqual(len(p["similar"]), 1)
        self.s.capture("question", dict(Q))                      # still allowed

    def test_bulk_preview_and_apply(self):
        common = {k: v for k, v in Q.items() if k != "text"}
        texts = ["First question here", "Second question here", "Third one"]
        p = self.s.capture_bulk("question", common, texts, apply=False)
        self.assertEqual(len(p["items"]), 3)
        self.assertEqual(self.s.records(), [])
        r = self.s.capture_bulk("question", common, texts, apply=True)
        self.assertEqual([x["id"] for x in r["created"]], ["Q-0001", "Q-0002", "Q-0003"])
        self.assertTrue(all(x["state"] == "draft" for x in r["created"]))

    def test_bulk_is_all_or_nothing_and_reports_line_numbers(self):
        common = {k: v for k, v in Q.items() if k not in ("text", "lens")}
        with self.assertRaises(SiteError) as e:
            self.s.capture_bulk("question", common, ["ok"], apply=True)
        self.assertTrue(any("lens" in x for x in e.exception.errors))
        self.assertEqual(self.s.records(), [])
        common2 = {k: v for k, v in Q.items() if k != "text"}
        with self.assertRaises(SiteError) as e:
            self.s.capture_bulk("question", common2, ["fine", "  ", "also fine"], apply=True)
        self.assertIn("line 2", e.exception.errors[0])
        self.assertEqual(self.s.records(), [])
        with self.assertRaises(SiteError):
            self.s.capture_bulk("question", common2, ["x"] * 51, apply=True)

    def test_bulk_unsupported_kind(self):
        with self.assertRaises(SiteError):
            self.s.capture_bulk("nope", {}, ["x"], apply=False)

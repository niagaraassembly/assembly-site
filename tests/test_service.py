import tempfile
import unittest
from pathlib import Path

from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies to 676 King St W?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        base = Path(self._t.name)
        (base / "root").mkdir()
        self.s = Service(base / "root", outbox=base / "out", runs=base / "runs")
        self.out = base / "out"

    def tearDown(self):
        self._t.cleanup()

    def test_capture_is_a_draft_and_writes_no_task(self):
        r = self.s.capture("question", dict(Q))
        self.assertEqual(r["record"]["status"], "new")
        self.assertEqual(r["creation"]["state"], "draft")
        self.assertFalse(self.out.exists() and list(self.out.iterdir()))
        self.assertEqual(self.s.summary()["drafts"][0]["id"], r["record"]["id"])

    def test_invalid_capture_mints_nothing(self):
        with self.assertRaises(SiteError):
            self.s.capture("question", {"text": "x"})
        self.assertEqual(self.s.records(), [])

    def test_dispatch_preview_then_apply(self):
        id = self.s.capture("question", dict(Q))["record"]["id"]
        prev = self.s.dispatch_preview(id)
        self.assertEqual(prev["errors"], [])
        self.assertFalse(prev["tasks"][0]["written"])
        r = self.s.dispatch(id)
        self.assertEqual(r["record"]["status"], "dispatched")
        self.assertEqual(len(list(self.out.glob("*.md"))), 1)
        self.assertEqual(r["creation"]["state"], "complete")
        self.assertTrue(r["tasks"][0]["written"])

    def test_file_intake_has_nothing_to_dispatch(self):
        id = self.s.capture("question", dict(Q, intake="file"))["record"]["id"]
        with self.assertRaises(SiteError):
            self.s.dispatch_preview(id)

    def test_set_goes_through_core_and_bumps_rev(self):
        id = self.s.capture("question", dict(Q))["record"]["id"]
        self.assertEqual(self.s.set_preview(id, {"region": "Niagara"}, [])["diff"][0]["new"], "Niagara")
        r = self.s.set(id, {"region": "Niagara"}, [])
        self.assertEqual(r["record"]["rev"], 1)
        with self.assertRaises(SiteError):
            self.s.set(id, {"lens": "nonsense"}, [])
        with self.assertRaises(SiteError):
            self.s.set(id, {"supersedes": "Q-0001"}, [])

    def test_confirm_only_when_awaiting(self):
        id = self.s.capture("question", dict(Q))["record"]["id"]
        with self.assertRaises(SiteError):
            self.s.confirm(id)

    def test_retire_needs_reason_and_preview_does_not_write(self):
        id = self.s.capture("question", dict(Q))["record"]["id"]
        with self.assertRaises(SiteError):
            self.s.retire(id, " ", True)
        self.s.retire(id, "dup", False)
        self.assertEqual(self.s.record(id)["record"]["status"], "new")
        self.assertEqual(self.s.retire(id, "dup", True)["record"]["status"], "retired")

    def test_handback_absent_runs_is_not_progress(self):
        out = self.s.handback(False)
        self.assertFalse(out["runs_present"])
        self.assertEqual(out["log"], [])

    def test_unknown_record(self):
        with self.assertRaises(SiteError) as e:
            self.s.record("Q-9999")
        self.assertEqual(e.exception.code, 404)

    def test_kinds_expose_edit_policy(self):
        q = [k for k in self.s.kinds() if k["name"] == "question"][0]
        self.assertTrue(q["dispatchable"])
        self.assertFalse([f for f in q["fields"] if f["name"] == "supersedes"][0]["editable"])


if __name__ == "__main__":
    unittest.main()

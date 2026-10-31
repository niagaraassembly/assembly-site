import datetime
import json
import tempfile
import unittest
from pathlib import Path

from assembly_site.core import records
from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class OpsTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.b = Path(self._t.name)
        (self.b / "root").mkdir()
        self.s = Service(self.b / "root", outbox=self.b / "out", runs=self.b / "runs")

    def tearDown(self):
        self._t.cleanup()

    def mk(self, **o):
        return self.s.capture("question", dict(Q, **o))["record"]["id"]

    def set_status(self, id, status, at=None):
        rec = self.s._load(id)
        rec["status"] = status
        if at:
            rec["history"][-1]["at"] = at
        records.save(self.s.root, rec)

    def mkrun(self, id, status="done", text="Found 3 permits"):
        d = self.b / "runs" / "2026" / "10" / "r1"
        d.mkdir(parents=True)
        (d / "run.md").write_text('---\nid: r1\ncreated: "2026-10-27 10:00:00"\nupdated: "2026-10-27 10:05:00"\nmachine: deb\ntool: auto\nstatus: %s\nactual_tool: claude\n---\n' % status)
        (d / "input.md").write_text('---\nmach: 1\ntags: [assembly, as:%s]\n---\n' % id)
        (d / "output.md").write_text(text)

    # ---- result before confirming
    def test_result_shows_run_output_or_says_none(self):
        id = self.mk()
        self.assertIsNone(self.s.result(id)["result"])
        self.mkrun(id)
        r = self.s.result(id)["result"]
        self.assertEqual(r["files"]["output.md"], "Found 3 permits")
        self.assertEqual(r["status"], "done")

    # ---- inbox
    def test_inbox_collects_review_failed_flagged_aging_and_partial(self):
        a, b, c, d = self.mk(), self.mk(), self.mk(), self.mk()
        self.set_status(a, "awaiting-confirmation")
        self.set_status(b, "failed")
        self.s.post_note(c, {"op": "flag", "on": True, "reason": "check lens", "actor": "ann"})
        self.s.dispatch(d)
        old = (datetime.datetime.now().astimezone() - datetime.timedelta(days=5)).isoformat(timespec="seconds")
        self.set_status(d, "dispatched", at=old)
        kinds = {i["kind"] for i in self.s.inbox()["items"]}
        self.assertEqual(kinds, {"review", "failed", "flagged", "aging"})
        self.assertEqual(self.s.inbox()["count"], 4)
        self.assertEqual(self.s.inbox()["items"][0]["kind"], "review")      # most pressing first

    def test_recently_dispatched_is_not_aging(self):
        self.s.dispatch(self.mk())
        self.assertEqual([i for i in self.s.inbox()["items"] if i["kind"] == "aging"], [])

    # ---- resume / supersede / health
    def test_resume_finishes_a_partial_creation(self):
        id = self.mk()
        good = self.s.outbox
        blocker = self.b / "blocked"
        blocker.write_text("file")
        self.s.outbox = blocker
        self.s.dispatch_preview(id)            # preview is fine
        with self.assertRaises(SiteError):
            self.s.dispatch(id)                # the outbox is a file, so the write fails and the creation stays partial
        self.assertEqual(self.s.record(id)["creation"]["state"], "partial")
        self.assertTrue(any(i["kind"] == "partial" for i in self.s.inbox()["items"]))
        self.s.outbox = good
        r = self.s.resume(id)
        self.assertEqual(r["creation"]["state"], "complete")
        self.assertEqual(r["record"]["status"], "dispatched")

    def test_resume_refuses_when_nothing_partial(self):
        id = self.mk()
        with self.assertRaises(SiteError):
            self.s.resume(id)

    def test_supersede_preview_then_apply(self):
        old, new = self.mk(), self.mk(text="Replacement")
        self.assertEqual(self.s.supersede(old, new, apply=False)["would"], "supersede")
        self.assertEqual(self.s.record(old)["record"]["status"], "new")
        r = self.s.supersede(old, new, apply=True)
        self.assertEqual(r["record"]["status"], "retired")
        self.assertEqual(self.s.record(new)["record"]["fields"]["supersedes"], old)
        with self.assertRaises(SiteError):
            self.s.supersede(old, "Q-9999", apply=False)

    def test_health_reports_lint(self):
        self.mk()
        h = self.s.health()
        self.assertEqual(h["errors"], [])
        self.assertIn("backups", h)

    # ---- backups
    def test_backup_copies_checksums_and_verifies(self):
        id = self.mk()
        self.s.post_note(id, {"op": "comment", "text": "n", "actor": "ann"})
        bk = self.s.backup()
        self.assertTrue(bk["name"])
        self.assertGreaterEqual(bk["files"], 3)               # profile, creation, annotations (+ registry)
        self.assertTrue(self.s.verify_backup(bk["name"])["ok"])
        self.assertEqual(self.s.backups()[0]["name"], bk["name"])
        # tamper with the copy: verification must fail
        f = next((self.s.data / "backups" / bk["name"]).rglob("Q-0001.json"))
        f.write_text("{}")
        v = self.s.verify_backup(bk["name"])
        self.assertFalse(v["ok"])
        self.assertTrue(v["bad"])

    def test_backup_name_validation(self):
        with self.assertRaises(SiteError):
            self.s.verify_backup("../etc")
        with self.assertRaises(SiteError):
            self.s.verify_backup("20200101-000000")


if __name__ == "__main__":
    unittest.main()

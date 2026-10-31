import tempfile
import unittest
from datetime import date
from pathlib import Path

from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan",
     "region": "Niagara", "cadence": "weekly", "origin": "internal"}
SUN, MON = date(2026, 10, 25), date(2026, 10, 26)


class ExtrasTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")

    def tearDown(self):
        self._t.cleanup()

    def mk(self, **o):
        return self.s.capture("question", dict(Q, **o))["record"]["id"]

    # ---- diff of a revised task document
    def test_first_dispatch_has_no_diff_revision_shows_what_changed(self):
        id = self.mk()
        self.assertIsNone(self.s.dispatch_preview(id)["tasks"][0]["diff"])
        self.s.dispatch(id)
        self.s.set(id, {"region": "Erie"}, [])
        t = self.s.dispatch_preview(id)["tasks"][0]
        self.assertIn("-r1", t["file"])
        self.assertIn("region: Niagara", t["diff"])
        self.assertIn("region: Erie", t["diff"])
        self.assertTrue(any(l.startswith("-") and "Niagara" in l for l in t["diff"].splitlines()))
        self.assertTrue(any(l.startswith("+") and "Erie" in l for l in t["diff"].splitlines()))

    def test_unchanged_redispatch_is_identical_not_a_diff(self):
        id = self.mk()
        self.s.dispatch(id)
        t = self.s.dispatch_preview(id)["tasks"][0]
        self.assertEqual(t["diff"], "")

    # ---- hold
    def test_hold_removes_from_ready_blocks_direct_dispatch_and_release_restores(self):
        a, b = self.mk(), self.mk()
        self.s.post_note(a, {"op": "hold", "on": True, "reason": "wait for owner", "actor": "ann"})
        m = {x["id"]: x for x in self.s.bundles(SUN)["bundles"][0]["members"]}
        self.assertEqual(m[a]["readiness"], "held")
        self.assertIn("wait for owner", m[a]["why"])
        self.assertEqual(self.s.bundles(SUN)["bundles"][0]["counts"]["held"], 1)
        with self.assertRaises(SiteError):
            self.s.dispatch(a)
        done = self.s.bundle_dispatch(self.s.bundles(SUN)["bundles"][0]["key_id"], SUN, apply=True)
        self.assertEqual([r["id"] for r in done["results"]], [b])
        self.s.post_note(a, {"op": "hold", "on": False, "actor": "ann"})
        self.assertEqual({x["id"]: x for x in self.s.bundles(SUN)["bundles"][0]["members"]}[a]["readiness"], "ready")

    def test_hold_only_on_records(self):
        with self.assertRaises(SiteError):
            self.s.post_note("stage:dispatch", {"op": "hold", "on": True})

    # ---- schedule
    def test_schedule_lists_due_bundles_per_day(self):
        self.mk(cadence="weekly")
        self.mk(cadence="daily", region="Erie")
        sch = self.s.schedule(SUN, 7)
        self.assertEqual([d["on"] for d in sch["days"]][:2], ["2026-10-25", "2026-10-26"])
        self.assertEqual(len(sch["days"][0]["bundles"]), 2)       # Sunday: weekly + daily
        self.assertEqual(len(sch["days"][1]["bundles"]), 1)       # Monday: daily only
        self.assertEqual(sch["days"][0]["weekday"], "Sun")
        with self.assertRaises(SiteError):
            self.s.schedule(SUN, 99)

    # ---- bundle history
    def test_bundle_history_lists_member_events_newest_first(self):
        a = self.mk()
        self.s.dispatch(a)
        h = self.s.bundles(SUN)["bundles"][0]["history"]
        self.assertEqual(h[0]["id"], a)
        self.assertIn(h[0]["event"], ("handoff-written", "dispatched"))

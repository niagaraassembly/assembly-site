import tempfile
import unittest
from datetime import date
from pathlib import Path

from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan",
     "region": "Niagara", "cadence": "daily", "origin": "internal"}
D = date(2026, 10, 28)


class BundlesTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")
        self.out = b / "out"

    def tearDown(self):
        self._t.cleanup()

    def mk(self, **over):
        return self.s.capture("question", dict(Q, **over))["record"]["id"]

    def test_bundle_view_has_labelled_key_members_and_readiness(self):
        a, b = self.mk(), self.mk(intake="file")
        v = self.s.bundles(D)
        self.assertEqual(len(v["bundles"]), 2)
        scan = [x for x in v["bundles"] if x["key"]["intake"] == "scan"][0]
        self.assertEqual(scan["members"][0]["id"], a)
        self.assertEqual(scan["members"][0]["readiness"], "ready")
        self.assertEqual(scan["counts"]["ready"], 1)
        filing = [x for x in v["bundles"] if x["key"]["intake"] == "file"][0]
        self.assertEqual(filing["members"][0]["readiness"], "manual")
        self.assertEqual(filing["counts"]["ready"], 0)
        self.assertEqual(v["totals"]["ready"], 1)

    def test_external_trust_shows_approval_needed(self):
        self.mk(trust="external", origin="external")
        m = self.s.bundles(D)["bundles"][0]["members"][0]
        self.assertEqual(m["readiness"], "ready")
        self.assertTrue(m["needs_approval"])

    def test_dispatch_preview_writes_nothing_then_apply_dispatches_only_ready(self):
        a, b = self.mk(), self.mk()
        self.s.dispatch(b)                                # b already in flight
        bk = self.s.bundles(D)["bundles"][0]
        prev = self.s.bundle_dispatch(bk["key_id"], D, apply=False)
        self.assertEqual([t["id"] for t in prev["members"]], [a])
        self.assertEqual(len(list(self.out.glob("*.md"))), 1)    # only b's, from before
        done = self.s.bundle_dispatch(bk["key_id"], D, apply=True)
        self.assertEqual([r["id"] for r in done["results"] if r["ok"]], [a])
        self.assertEqual(len(list(self.out.glob("*.md"))), 2)
        self.assertEqual(self.s.record(a)["record"]["status"], "dispatched")
        self.assertEqual(self.s.bundles(D)["bundles"][0]["counts"]["ready"], 0)

    def test_subset_and_unknown_bundle(self):
        a, b = self.mk(), self.mk()
        bk = self.s.bundles(D)["bundles"][0]
        self.s.bundle_dispatch(bk["key_id"], D, apply=True, ids=[a])
        self.assertEqual(self.s.record(b)["record"]["status"], "new")
        with self.assertRaises(SiteError) as e:
            self.s.bundle_dispatch("bk-00000000", D, apply=True)
        self.assertEqual(e.exception.code, 404)
        with self.assertRaises(SiteError):
            self.s.bundle_dispatch(bk["key_id"], D, apply=True, ids=["Q-9999"])

    def test_workbench_next_actions_follow_priority(self):
        self.assertEqual(self.s.workbench(D)["next"][0]["kind"], "capture")
        a = self.mk()
        self.assertEqual(self.s.workbench(D)["next"][0]["kind"], "dispatch-ready")
        self.assertEqual(self.s.workbench(D)["next"][0]["cta"], "Open bundles")
        self.assertEqual(self.s.workbench(D)["steps"][1]["count"], 1)      # bundles
        self.s.dispatch(a)
        w = self.s.workbench(D)
        self.assertEqual(w["next"][0]["kind"], "track")
        self.assertEqual(w["in_flight"][0]["id"], a)
        rec = self.s._load(a)
        rec["status"] = "awaiting-confirmation"
        from assembly_site.core import records
        records.save(self.s.root, rec)
        self.assertEqual(self.s.workbench(D)["next"][0]["kind"], "review")

    def test_excluded_listed_with_reason(self):
        a = self.mk()
        self.s.retire(a, "dup", True)
        self.assertEqual(self.s.bundles(D)["excluded"][0]["reason"], "retired")

    def test_bundle_stage_is_now_built_in_the_map(self):
        st = [x for x in self.s.stages() if x["key"] == "dispatch"][0]
        bundle = [x for x in st["substages"] if x["key"] == "bundle"][0]
        self.assertEqual(bundle["state"], "built")
        self.assertEqual(bundle["actions"][0]["route"], "#/bundles")

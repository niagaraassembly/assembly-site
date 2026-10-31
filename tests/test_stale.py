import tempfile
import unittest
from pathlib import Path

from assembly_site.core import records
from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class StaleTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")

    def tearDown(self):
        self._t.cleanup()

    def mk(self):
        return self.s.capture("question", dict(Q))["record"]["id"]

    def test_stale_set_is_a_409_and_changes_nothing(self):
        id = self.mk()
        self.s.set(id, {"region": "A"}, [], expected_rev=0)
        with self.assertRaises(SiteError) as e:
            self.s.set(id, {"region": "B"}, [], expected_rev=0)
        self.assertEqual(e.exception.code, 409)
        self.assertEqual(self.s.record(id)["record"]["fields"]["region"], "A")
        with self.assertRaises(SiteError) as e:
            self.s.set_preview(id, {"region": "B"}, [], expected_rev=0)       # the preview already warns
        self.assertEqual(e.exception.code, 409)

    def test_stale_retire_supersede_dispatch_are_409(self):
        id, other = self.mk(), self.mk()
        self.s.set(id, {"region": "A"}, [])
        for fn in (lambda: self.s.retire(id, "x", True, expected_rev=0),
                   lambda: self.s.supersede(id, other, True, expected_rev=0),
                   lambda: self.s.dispatch(id, expected_rev=0)):
            with self.assertRaises(SiteError) as e:
                fn()
            self.assertEqual(e.exception.code, 409)
        self.assertEqual(self.s.record(id)["record"]["status"], "new")

    def test_confirm_goes_through_core_and_a_second_confirm_is_refused(self):
        id = self.mk()
        rec = self.s._load(id)
        rec["status"] = "awaiting-confirmation"
        records.save(self.s.root, rec)
        r = self.s.confirm(id)
        self.assertEqual(r["record"]["status"], "answered")
        self.assertEqual(r["record"]["history"][-1]["detail"], "owner (site)")
        with self.assertRaises(SiteError):
            self.s.confirm(id)

    def test_dispatch_event_is_written_by_the_core_with_the_site_as_actor(self):
        id = self.mk()
        self.s.dispatch(id)
        ev = [e for e in self.s.record(id)["record"]["history"] if e["event"] in ("handoff-written", "dispatched")]
        self.assertTrue(ev)
        # second dispatch of unchanged record must not add history
        n = len(self.s.record(id)["record"]["history"])
        self.s.dispatch(id)
        self.assertEqual(len(self.s.record(id)["record"]["history"]), n)

    def test_site_service_does_not_save_records_itself(self):
        src = (Path(__file__).resolve().parent.parent / "assembly_site" / "service.py").read_text()
        self.assertNotIn("records.save(", src)
        self.assertNotIn("records.add_event(", src)

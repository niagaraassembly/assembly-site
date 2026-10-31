import csv
import io
import tempfile
import unittest
from pathlib import Path

from assembly_site.notes import NoteError, Notes
from assembly_site.service import Service, SiteError

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class ThreadsTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.n = Notes(Path(self._t.name) / "a.jsonl")

    def tearDown(self):
        self._t.cleanup()

    def test_resolve_and_reopen_a_thread_root_only(self):
        a = self.n.comment("Q-0001", "root", "ann")
        r = self.n.comment("Q-0001", "reply", "bo", parent=a["id"])
        self.n.resolve(a["id"], "bo", True)
        v = {c["id"]: c for c in self.n.view("Q-0001")["comments"]}
        self.assertTrue(v[a["id"]]["resolved"])
        self.assertEqual(v[a["id"]]["resolved_by"], "bo")
        self.assertFalse(v[r["id"]]["resolved"])
        with self.assertRaises(NoteError):
            self.n.resolve(r["id"], "bo", True)              # replies cannot be resolved on their own
        self.n.resolve(a["id"], "ann", False)
        self.assertFalse({c["id"]: c for c in self.n.view("Q-0001")["comments"]}[a["id"]]["resolved"])

    def test_mentions_found_case_insensitively_never_for_self_and_unread_by_seen(self):
        self.n.comment("Q-0001", "ping @Ann please look", "bo")
        self.n.comment("Q-0001", "talking to myself @ann", "ann")
        self.n.comment("Q-0002", "no mention here", "bo")
        m = self.n.mentions_for("ann")
        self.assertEqual([x["target"] for x in m], ["Q-0001"])
        self.assertEqual(len(self.n.unread_mentions("ann")), 1)
        self.n.seen("ann")
        self.assertEqual(self.n.unread_mentions("ann"), [])
        self.n.comment("Q-0003", "again @ann", "bo")
        self.assertEqual([x["target"] for x in self.n.unread_mentions("ann")], ["Q-0003"])

    def test_retracted_mention_is_not_listed(self):
        c = self.n.comment("Q-0001", "hey @ann", "bo")
        self.n.retract(c["id"], "bo")
        self.assertEqual(self.n.mentions_for("ann"), [])


class RecordsViewTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")
        self.ids = [self.s.capture("question", dict(Q, text=t, region=r))["record"]["id"]
                    for t, r in (("Zoning in Welland", "Welland"), ("Permits in Niagara Falls", "Niagara"), ("Bylaws in St Catharines", "Niagara"))]

    def tearDown(self):
        self._t.cleanup()

    def test_search_matches_id_title_and_any_field(self):
        self.assertEqual([r["id"] for r in self.s.records_page(q="welland")["rows"]], [self.ids[0]])
        self.assertEqual(len(self.s.records_page(q="niagara")["rows"]), 2)        # matches a field value, not just the title
        self.assertEqual([r["id"] for r in self.s.records_page(q="q-0003")["rows"]], [self.ids[2]])
        self.assertEqual(self.s.records_page(q="zzz")["total"], 0)

    def test_sort_and_paging(self):
        asc = self.s.records_page(sort="id", order="asc")
        self.assertEqual([r["id"] for r in asc["rows"]], self.ids)
        desc = self.s.records_page(sort="title", order="desc")
        self.assertEqual(desc["rows"][0]["title"], "Zoning in Welland")
        p = self.s.records_page(sort="id", order="asc", per=2, page=2)
        self.assertEqual([r["id"] for r in p["rows"]], [self.ids[2]])
        self.assertEqual((p["page"], p["pages"], p["total"]), (2, 2, 3))
        self.assertEqual(self.s.records_page(per=2, page=99)["page"], 2)           # clamped
        with self.assertRaises(SiteError):
            self.s.records_page(sort="password")

    def test_csv_export_neutralises_formulas(self):
        self.s.capture("question", dict(Q, text="=HYPERLINK(\"http://x\",\"y\")"))
        rows = list(csv.reader(io.StringIO(self.s.records_csv())))
        self.assertEqual(rows[0][:3], ["id", "kind", "status"])
        self.assertEqual(len(rows), 5)
        evil = [r for r in rows if r[0] == "Q-0004"][0]
        self.assertTrue(evil[rows[0].index("title")].startswith("'="))

    def test_timeline_merges_history_newest_first_with_paging(self):
        import time
        time.sleep(1.1)                       # history timestamps have one-second resolution
        self.s.set(self.ids[0], {"region": "Erie"}, [])
        t = self.s.timeline(limit=3)
        self.assertEqual(t["events"][0]["event"], "changed")
        self.assertEqual(len(t["events"]), 3)
        self.assertEqual(t["total"], 4)
        self.assertEqual(len(self.s.timeline(limit=3, offset=3)["events"]), 1)


class MentionInboxTest(RecordsViewTest):
    def test_inbox_mentions_for_actor_and_mark_seen(self):
        self.s.post_note(self.ids[0], {"op": "comment", "text": "@ann can you check?", "actor": "bo"})
        self.assertEqual([i["kind"] for i in self.s.inbox("ann")["items"]], ["mention"])
        self.assertEqual(self.s.inbox("bo")["count"], 0)
        self.assertEqual(self.s.inbox()["count"], 0)                 # no actor: no personal items
        self.s.mark_seen("ann")
        self.assertEqual(self.s.inbox("ann")["count"], 0)

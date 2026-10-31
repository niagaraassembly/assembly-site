import tempfile
import unittest
from pathlib import Path

from assembly_site.notes import NoteError, Notes


class NotesTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.path = Path(self._t.name) / "data" / "annotations.jsonl"
        self.n = Notes(self.path)

    def tearDown(self):
        self._t.cleanup()

    def test_comment_thread_preserves_text_and_order(self):
        a = self.n.comment("Q-0001", "first\n**bold** <b>x</b>", "ann")
        b = self.n.comment("Q-0001", "reply", "bo", parent=a["id"])
        v = self.n.view("Q-0001")
        self.assertEqual([c["id"] for c in v["comments"]], [a["id"], b["id"]])
        self.assertEqual(v["comments"][0]["text"], "first\n**bold** <b>x</b>")
        self.assertEqual(v["comments"][1]["parent"], a["id"])

    def test_empty_overlong_and_foreign_parent_refused(self):
        with self.assertRaises(NoteError):
            self.n.comment("Q-0001", "  ", "ann")
        with self.assertRaises(NoteError):
            self.n.comment("Q-0001", "x" * 4001, "ann")
        c = self.n.comment("Q-0001", "ok", "ann")
        with self.assertRaises(NoteError):
            self.n.comment("Q-0002", "reply elsewhere", "ann", parent=c["id"])
        with self.assertRaises(NoteError):
            self.n.comment("Q-0001", "reply", "ann", parent="nope")

    def test_star_is_per_actor_and_idempotent(self):
        self.n.star("Q-0001", "ann", True)
        self.n.star("Q-0001", "ann", True)
        self.n.star("Q-0001", "bo", True)
        self.assertEqual(sorted(self.n.view("Q-0001")["starred_by"]), ["ann", "bo"])
        self.n.star("Q-0001", "ann", False)
        self.assertEqual(self.n.view("Q-0001")["starred_by"], ["bo"])

    def test_flag_latest_wins_and_keeps_reason(self):
        self.n.flag("stage:dispatch.digest", "ann", True, "needs owner")
        self.assertEqual(self.n.view("stage:dispatch.digest")["flag"]["reason"], "needs owner")
        self.n.flag("stage:dispatch.digest", "bo", False, "")
        self.assertIsNone(self.n.view("stage:dispatch.digest")["flag"])

    def test_retract_hides_text_in_view_but_not_in_file(self):
        c = self.n.comment("Q-0001", "secret-ish", "ann")
        with self.assertRaises(NoteError):
            self.n.retract(c["id"], "bo")           # only the author
        self.n.retract(c["id"], "ann")
        v = self.n.view("Q-0001")["comments"][0]
        self.assertTrue(v["retracted"])
        self.assertIsNone(v["text"])
        self.assertIn("secret-ish", self.path.read_text())   # provenance kept

    def test_survives_restart_and_skips_corrupt_lines(self):
        self.n.comment("Q-0001", "kept", "ann")
        with open(self.path, "a") as f:
            f.write("{not json\n")
        again = Notes(self.path)
        self.assertEqual(len(again.view("Q-0001")["comments"]), 1)
        again.comment("Q-0001", "after", "ann")
        self.assertEqual(len(Notes(self.path).view("Q-0001")["comments"]), 2)

    def test_actor_sanitised_and_activity_newest_first(self):
        c = self.n.comment("Q-0001", "hi", "  An\nn\t" + "z" * 80)
        self.assertNotIn("\n", c["actor"])
        self.assertLessEqual(len(c["actor"]), 40)
        self.n.star("Q-0002", "ann", True)
        act = self.n.activity(10)
        self.assertEqual(act[0]["op"], "star")
        self.assertEqual(act[1]["op"], "comment")

    def test_index_summarises_targets(self):
        self.n.comment("Q-0001", "a", "ann")
        self.n.star("Q-0001", "ann", True)
        self.n.flag("Q-0002", "ann", True, "r")
        idx = self.n.index()
        self.assertEqual(idx["Q-0001"], {"comments": 1, "starred": True, "flagged": False})
        self.assertTrue(idx["Q-0002"]["flagged"])

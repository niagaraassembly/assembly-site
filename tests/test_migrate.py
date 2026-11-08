import tempfile
import unittest
from pathlib import Path

from assembly_site.migrate import migrate, plan


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.target, self.backup = (self.base / name for name in ("source", "records", "snapshot"))
        for path, body in (("profiles/question/Q-0001.json", b'{"text":"original\\ntext"}\n'),
                           ("registry/counters.json", b'{"Q":1}\n'), ("creations/Q-0001.json", b'{"state":"complete"}\n')):
            dest = self.source / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)

    def test_preview_writes_nothing_and_apply_preserves_every_byte(self):
        preview = plan(self.source, self.target, self.backup)
        self.assertEqual(len(preview["files"]), 3)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.backup.exists())
        result = migrate(self.source, self.target, self.backup, expected=preview["files"])
        self.assertEqual(result["files"], preview["files"])
        for name in result["files"]:
            self.assertEqual((self.target / name).read_bytes(), (self.source / name).read_bytes())
            self.assertEqual((self.backup / name).read_bytes(), (self.source / name).read_bytes())

    def test_existing_target_and_changed_source_fail_without_overwriting(self):
        preview = plan(self.source, self.target, self.backup)
        (self.source / "registry/counters.json").write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, "changed"):
            migrate(self.source, self.target, self.backup, expected=preview["files"])
        self.assertFalse(self.target.exists())
        self.target.mkdir()
        sentinel = self.target / "keep"
        sentinel.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            migrate(self.source, self.target, self.backup)
        self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_busy_root_and_symlinks_are_refused(self):
        lock = self.source / "registry/.lock"
        lock.touch()
        with self.assertRaisesRegex(ValueError, "lock"):
            plan(self.source, self.target, self.backup)
        lock.unlink()
        (self.source / "profiles/question/link.json").symlink_to(self.source / "registry/counters.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            plan(self.source, self.target, self.backup)

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assembly_site.runtime import metadata_fields, record_root, settings


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "local.json"

    def test_record_root_is_external_and_configuration_is_optional(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(record_root(config=self.config), Path("~/na/local-data/assembly").expanduser().resolve())
        self.config.write_text(json.dumps({"record_root": str(self.root / "configured")}))
        self.assertEqual(settings(self.config)["record_root"], str(self.root / "configured"))
        with patch.dict(os.environ, {"ASSEMBLY_ROOT": str(self.root / "environment")}):
            self.assertEqual(record_root(config=self.config), self.root / "environment")
            self.assertEqual(record_root(self.root / "explicit", self.config), self.root / "explicit")

    def test_metadata_policy_is_read_from_core_schema(self):
        schema = self.root / "kinds/question.json"
        schema.parent.mkdir()
        schema.write_text(json.dumps({"capture": {"metadata": ["region", "new_field"]}}))
        self.assertEqual(metadata_fields(self.root), ("region", "new_field"))
        schema.write_text(json.dumps({"capture": {"metadata": "unsafe"}}))
        with self.assertRaises(ValueError):
            metadata_fields(self.root)

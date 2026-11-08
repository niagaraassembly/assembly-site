import http.client
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from assembly_site.runtime import configure_core, metadata_fields

CORE = configure_core()
from assembly.kinds import Field, load_kinds
from assembly.records import load
from assembly_site.server import MAX_REQUEST_BYTES, make_server

REPO = Path(__file__).resolve().parent.parent
KINDS = load_kinds(CORE / "kinds")


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.start()

    def start(self):
        self.server = make_server(self.root, KINDS, port=0, metadata_fields=metadata_fields(CORE))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        h = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:%s" % self.server.server_port,
             "X-Assembly-CSRF": self.server.csrf_token}
        h.update(headers or {})
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        connection.request(method, path, body=data, headers=h)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        content_type = response.getheader("Content-Type", "")
        connection.close()
        return status, json.loads(raw) if "application/json" in content_type else raw.decode()

    def test_schema_and_get_do_not_write(self):
        status, body = self.request("GET", "/api/questions")
        self.assertEqual((status, body), (200, {"questions": []}))
        status, body = self.request("GET", "/api/schema")
        self.assertEqual(status, 200)
        self.assertTrue(any(f["name"] == "lens" for f in body["question_fields"]))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_new_schema_metadata_is_exposed_and_validated_without_site_field_lists(self):
        self.server.kinds = copy.deepcopy(KINDS)
        self.server.kinds["question"].fields.append(Field(name="sector", type="text"))
        self.server.metadata_fields += ("sector",)
        _, schema = self.request("GET", "/api/schema")
        self.assertIn("sector", [field["name"] for field in schema["question_fields"]])
        _, created = self.request("POST", "/api/questions", {"text": "Test schema growth"})
        id = created["question"]["id"]
        status, saved = self.request("PATCH", "/api/questions/" + id, {"fields": {"sector": "Manufacturing"}, "rev": 0})
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["question"]["fields"]["sector"], "Manufacturing")
        self.assertEqual(self.request("PATCH", "/api/questions/" + id,
                                      {"fields": {"sector": ["bad type"]}, "rev": 1})[0], 400)

    def test_capture_policy_cannot_expose_execution_or_original_fields(self):
        for name in ("text", "source_question", "supersedes", "procedure", "writes", "machine", "path", "intake", "unknown"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                make_server(self.root, KINDS, port=0, metadata_fields=(name,))

    def test_long_text_survives_create_read_and_server_restart(self):
        text = "\n\n  Pasted <script>window.injected=true</script>\r\n" + ("π e\u0301 🦊\n" * 20000) + "  \n"
        status, body = self.request("POST", "/api/questions", {"text": text, "title": "Long submission"})
        self.assertEqual(status, 201, body)
        id = body["question"]["id"]
        self.assertEqual(body["question"]["fields"]["text"], text)
        self.stop()
        self.start()
        status, body = self.request("GET", "/api/questions/" + id)
        self.assertEqual(status, 200)
        self.assertEqual(body["question"]["fields"]["text"], text)
        self.assertEqual(body["question"]["status"], "draft")
        self.assertFalse((self.root / "outbox").exists())

    def test_linked_capture_preserves_source_and_exposes_lineage(self):
        _, first = self.request("POST", "/api/questions", {"text": "Long original"})
        source = first["question"]["id"]
        status, child = self.request("POST", "/api/questions", {"text": "Discrete question", "source_question": source})
        self.assertEqual(status, 201)
        _, original = self.request("GET", "/api/questions/" + source)
        self.assertEqual(original["question"]["derived_questions"], [child["question"]["id"]])
        self.assertEqual(original["question"]["fields"]["text"], "Long original")

    def test_manual_metadata_is_versioned_and_backs_up_original(self):
        _, created = self.request("POST", "/api/questions", {"text": "Original"})
        id = created["question"]["id"]
        status, changed = self.request("PATCH", "/api/questions/" + id,
                                       {"fields": {"lens": "companies", "region": "Niagara"}, "rev": 0})
        self.assertEqual(status, 200, changed)
        self.assertEqual(changed["question"]["rev"], 1)
        self.assertEqual(changed["question"]["fields"]["text"], "Original")
        backups = list((self.root / "backups" / "profiles" / "question" / id).glob("*.json"))
        self.assertEqual(len(backups), 1)
        self.assertNotIn("region", json.loads(backups[0].read_text())["fields"])
        self.assertEqual(self.request("PATCH", "/api/questions/" + id, {"fields": {"region": "Other"}, "rev": 0})[0], 409)
        self.assertEqual(load(self.root, id, KINDS)["fields"]["region"], "Niagara")
        self.assertEqual(self.request("PATCH", "/api/questions/" + id, {"fields": {"text": "Replace"}, "rev": 1})[0], 400)

    def test_invalid_capture_and_cross_origin_never_write(self):
        for body in ({"text": " \n "}, {"text": "x", "intake": "scan"}, {"text": "x", "source_question": "Q-9999"}):
            self.assertEqual(self.request("POST", "/api/questions", body)[0], 400)
        self.assertEqual(self.request("POST", "/api/questions", {"text": "x"}, {"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("POST", "/api/questions", {"text": "x"}, {"X-Assembly-CSRF": "wrong"})[0], 403)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_save_receipts_do_not_use_the_full_question_listing(self):
        _, original = self.request("POST", "/api/questions", {"text": "Original"})
        source = original["question"]["id"]
        _, derived = self.request("POST", "/api/questions", {"text": "Derived", "source_question": source})
        child = derived["question"]["id"]
        with patch.object(self.server, "questions", side_effect=OSError("unrelated listing unavailable")):
            status, created = self.request("POST", "/api/questions", {"text": "Independent capture"})
            self.assertEqual(status, 201, created)
            self.assertEqual(created["question"]["derived_questions"], [])
            self.assertEqual(created["question"]["superseded_by"], [])
            status, changed = self.request("PATCH", "/api/questions/" + source,
                                           {"fields": {"region": "Niagara"}, "rev": 0})
            self.assertEqual(status, 200, changed)
            self.assertEqual(changed["question"]["derived_questions"], [child])
            self.assertEqual(changed["question"]["superseded_by"], [])
            self.assertEqual(changed["question"]["fields"]["region"], "Niagara")

    def test_single_question_read_skips_unreadable_unrelated_profiles(self):
        _, original = self.request("POST", "/api/questions", {"text": "Original"})
        source = original["question"]["id"]
        _, child = self.request("POST", "/api/questions", {"text": "Derived", "source_question": source})
        _, unrelated = self.request("POST", "/api/questions", {"text": "Unrelated"})
        blocked = unrelated["question"]["id"]

        def read(root, id, kinds):
            if id == blocked:
                raise OSError("unrelated profile unavailable")
            return load(root, id, kinds)

        with patch("assembly_site.server.load", side_effect=read):
            status, body = self.request("GET", "/api/questions/" + source)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["question"]["fields"]["text"], "Original")
        self.assertEqual(body["question"]["derived_questions"], [child["question"]["id"]])
        self.assertEqual(self.request("GET", "/api/questions/Q-9999")[0], 404)

    def test_metadata_receipt_does_not_read_unrelated_profiles_after_save(self):
        _, original = self.request("POST", "/api/questions", {"text": "Original"})
        source = original["question"]["id"]
        _, child = self.request("POST", "/api/questions", {"text": "Derived", "source_question": source})
        from assembly.change import apply_set as real_apply_set
        committed = []

        def save(*args, **kwargs):
            result = real_apply_set(*args, **kwargs)
            committed.append(True)
            return result

        def read(root, id, kinds):
            if committed and id != source:
                raise AssertionError("success receipt read an unrelated profile")
            return load(root, id, kinds)

        with patch("assembly_site.server.apply_set", side_effect=save), patch("assembly_site.server.load", side_effect=read):
            status, changed = self.request("PATCH", "/api/questions/" + source,
                                           {"fields": {"region": "Niagara"}, "rev": 0})
        self.assertEqual(status, 200, changed)
        self.assertEqual(changed["question"]["derived_questions"], [child["question"]["id"]])
        self.assertEqual(changed["question"]["rev"], 1)

    def test_id_lock_timeout_is_a_structured_retryable_error(self):
        with patch("assembly.create.mint", side_effect=RuntimeError("could not take the ID lock: private-path")):
            status, body = self.request("POST", "/api/questions", {"text": "Preserve this entry"})
        self.assertEqual(status, 503, body)
        self.assertIn("retry", body["error"].lower())
        self.assertNotIn("private-path", body["error"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_non_ascii_csrf_header_is_rejected_without_a_write(self):
        status, body = self.request("POST", "/api/questions", {"text": "x"}, {"X-Assembly-CSRF": "café"})
        self.assertEqual(status, 403, body)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_oversized_body_is_explicitly_rejected(self):
        status, body = self.request("POST", "/api/questions", {}, {"Content-Length": str(MAX_REQUEST_BYTES + 1)})
        self.assertEqual(status, 413)
        self.assertIn("8 MiB", body["error"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_server_is_loopback_only_and_does_not_expose_files(self):
        with self.assertRaises(ValueError):
            make_server(self.root, KINDS, host="0.0.0.0", port=0)
        self.assertEqual(self.request("GET", "/AGENTS.md")[0], 404)
        self.assertEqual(self.request("GET", "/api/questions/../registry")[0], 404)


if __name__ == "__main__":
    unittest.main()

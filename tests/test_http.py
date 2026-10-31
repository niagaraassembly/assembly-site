import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from assembly_site.server import serve
from assembly_site.service import Service

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class HttpTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.out = b / "out"
        self.srv = serve(Service(b / "root", outbox=self.out, runs=b / "runs"), port=0)
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self._t.cleanup()

    def call(self, path, body=None, headers=None):
        h = {"Content-Type": "application/json", "X-Assembly-Site": "1"} if body is not None else {}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null") if r.headers["Content-Type"].startswith("application/json") else r.read()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_static_index_served(self):
        code, body = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Dispatch", body)

    def test_capture_preview_apply_dispatch_flow(self):
        code, prev = self.call("/api/captures", {"kind": "question", "fields": Q})
        self.assertEqual(code, 200)
        self.assertEqual(self.call("/api/records")[1], [])           # preview mints nothing
        code, made = self.call("/api/captures", {"kind": "question", "fields": Q, "apply": True})
        self.assertEqual(code, 201)
        id = made["record"]["id"]
        self.assertFalse(self.out.exists())                           # a draft is never dispatched
        code, d = self.call("/api/records/%s/dispatch" % id)
        self.assertEqual(d["tasks"][0]["written"], False)
        self.assertFalse(self.out.exists())                           # GET preview writes nothing
        code, r = self.call("/api/records/%s/dispatch" % id, {"apply": True})
        self.assertEqual(r["record"]["status"], "dispatched")
        self.assertEqual(len(list(self.out.glob("*.md"))), 1)
        self.assertEqual(self.call("/api/summary")[1]["in_flight"][0]["id"], id)

    def test_validation_error_is_400_with_field_names(self):
        code, e = self.call("/api/captures", {"kind": "question", "fields": {"text": "x"}, "apply": True})
        self.assertEqual(code, 400)
        self.assertTrue(any("lens" in x for x in e["errors"]))

    def test_post_requires_site_headers_and_local_host(self):
        req = urllib.request.Request(self.base + "/api/handback", data=b"{}", headers={"Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(req)
        self.assertEqual(c.exception.code, 403)
        code, e = self.call("/api/summary", headers={"Host": "evil.example"})
        self.assertEqual(code, 403)

    def test_unknown_record_404_and_path_traversal_contained(self):
        self.assertEqual(self.call("/api/records/Q-0099")[0], 404)
        code, body = self.call("/..%2f..%2fetc/passwd")
        self.assertEqual(code, 200)
        self.assertIn(b"<html", body)  # falls back to the app, never the file


if __name__ == "__main__":
    unittest.main()

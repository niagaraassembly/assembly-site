import tempfile
import unittest
from pathlib import Path

from assembly_site import __version__
from assembly_site.server import make_handler, serve
from assembly_site.service import Service

from httpbase import HttpBase


class HealthDetailsTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        b = Path(self._t.name)
        (b / "root").mkdir()
        self.s = Service(b / "root", outbox=b / "out", runs=b / "runs")

    def tearDown(self):
        self._t.cleanup()

    def test_health_reports_versions_paths_and_probes(self):
        h = self.s.health()
        self.assertEqual(h["site"]["version"], __version__)
        self.assertTrue(h["core"]["path"].endswith("assembly-system") or h["core"]["path"])
        self.assertIn("commit", h["core"])
        for k in ("root", "data", "outbox", "runs", "core"):
            self.assertIn(k, h["paths"])
        keys = {(p["stage"], p["sub"]) for p in h["probes"]}
        self.assertIn(("dispatch", "bundle"), keys)
        bundle = [p for p in h["probes"] if (p["stage"], p["sub"]) == ("dispatch", "bundle")][0]
        self.assertEqual(bundle["state"], "built")
        self.assertTrue(all(n["found"] for n in bundle["needs"]))
        resolve = [p for p in h["probes"] if (p["stage"], p["sub"]) == ("dispatch", "resolve")][0]
        self.assertFalse(resolve["needs"][0]["found"])
        self.assertTrue(resolve["needs"][0]["spec"].startswith("module:"))


class HttpTransparencyTest(HttpBase, unittest.TestCase):
    def test_healthz(self):
        code, body = self.call("/healthz")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["core"])
        self.assertEqual(body["version"], __version__)
        self.assertEqual(self.call("/healthz", headers={"Host": "evil.example"})[0], 403)

    def test_requests_are_logged_only_when_asked(self):
        lines = []
        import threading
        srv = serve(self.svc, port=0, log=lines.append)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:%d/api/summary" % srv.server_address[1]).read()
        srv.shutdown()
        srv.server_close()
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^GET /api/summary 200 \d+ms$")
        quiet = []
        self.call("/api/summary")                               # the default server has no log callback
        self.assertEqual(quiet, [])

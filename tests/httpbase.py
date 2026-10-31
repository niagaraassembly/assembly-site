import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from assembly_site.server import serve
from assembly_site.service import Service

Q = {"text": "What zoning applies?", "lens": "law", "trust": "owner", "sensitivity": "private", "intake": "scan"}


class HttpBase:
    """Mixin: a live server on a temp root. Not a TestCase, so it adds no tests by itself."""
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.b = Path(self._t.name)
        (self.b / "root").mkdir()
        self.svc = Service(self.b / "root", outbox=self.b / "out", runs=self.b / "runs")
        self.srv = serve(self.svc, port=0)
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
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers["Content-Type"].startswith("application/json") else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

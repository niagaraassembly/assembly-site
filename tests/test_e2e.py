import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from assembly_site.server import serve
from assembly_site.service import Service

SCRIPT = Path(__file__).resolve().parent / "e2e" / "e2e.js"


def _playwright_available() -> bool:
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, cwd="/tmp").returncode == 0


@unittest.skipUnless(_playwright_available(), "node + playwright not installed")
class BrowserE2E(unittest.TestCase):
    def test_site_flows_in_a_real_browser(self):
        with tempfile.TemporaryDirectory() as t:
            b = Path(t)
            (b / "root").mkdir()
            srv = serve(Service(b / "root", outbox=b / "out", runs=b / "runs"), port=0)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                url = "http://127.0.0.1:%d/" % srv.server_address[1]
                r = subprocess.run(["node", str(SCRIPT), url], capture_output=True, text=True, cwd="/tmp", timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("e2e ok", r.stdout)
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main()

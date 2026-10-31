"""Localhost HTTP adapter: JSON API plus buildless static assets. Binds to 127.0.0.1 only.

Writes need `Content-Type: application/json` and `X-Assembly-Site: 1` (a plain cross-site form cannot send
either), and every request must carry a localhost Host header (blocks DNS rebinding).
"""
import argparse
import json
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .service import Service, SiteError

STATIC = Path(__file__).resolve().parent / "static"
_ID = r"([A-Z]+-\d{4,})"
_HOST_OK = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")


def _day(s):
    import datetime
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s))
    except ValueError:
        raise SiteError(["on: must be a date like 2026-10-28"])


def make_handler(svc: Service):
    class H(BaseHTTPRequestHandler):
        server_version = "AssemblySite/0"

        def log_message(self, fmt, *args):
            if os.environ.get("ASSEMBLY_SITE_LOG"):
                sys.stderr.write("%s\n" % (fmt % args))

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _err(self, code: int, errors):
            self._json(code, {"errors": errors if isinstance(errors, list) else [errors]})

        def _host_ok(self) -> bool:
            return bool(_HOST_OK.match(self.headers.get("Host", "")))

        def do_GET(self):
            if not self._host_ok():
                return self._err(403, "bad host")
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/summary":
                    return self._json(200, svc.summary())
                if u.path == "/api/kinds":
                    return self._json(200, svc.kinds())
                if u.path == "/api/records":
                    return self._json(200, svc.records(q.get("kind"), q.get("status"), q.get("starred") == "1"))
                if u.path == "/api/inbox":
                    return self._json(200, svc.inbox())
                if u.path == "/api/health":
                    return self._json(200, svc.health())
                m = re.fullmatch(r"/api/records/" + _ID + r"/result", u.path)
                if m:
                    return self._json(200, svc.result(m.group(1)))
                if u.path == "/api/bundles":
                    return self._json(200, svc.bundles(_day(q.get("on"))))
                if u.path == "/api/workbench":
                    return self._json(200, svc.workbench(_day(q.get("on"))))
                if u.path == "/api/stages":
                    return self._json(200, {"stages": svc.stages(), "gates": svc.gates()})
                m = re.fullmatch(r"/api/stages/([a-z0-9]+)", u.path)
                if m:
                    return self._json(200, svc.stage(m.group(1)))
                if u.path == "/api/notes":
                    return self._json(200, svc.notes(q.get("target", "")))
                if u.path == "/api/activity":
                    return self._json(200, {"activity": svc.activity(min(int(q.get("limit", "50") or 50), 200)), "starred": svc.starred()})
                m = re.fullmatch(r"/api/records/" + _ID, u.path)
                if m:
                    return self._json(200, svc.record(m.group(1)))
                m = re.fullmatch(r"/api/records/" + _ID + r"/dispatch", u.path)
                if m:
                    return self._json(200, svc.dispatch_preview(m.group(1)))
                if u.path == "/api/handback":
                    return self._json(200, svc.handback(False))
            except SiteError as e:
                return self._err(e.code, e.errors)
            if u.path.startswith("/api/"):
                return self._err(404, "not found")
            return self._static(u.path)

        def _static(self, path: str):
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (STATIC / name).resolve()
            if STATIC.resolve() not in f.parents or not f.is_file():
                f = STATIC / "index.html"  # single-page app: unknown paths show the app
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") or "javascript" in ctype else ""))

        def do_POST(self):
            if not self._host_ok():
                return self._err(403, "bad host")
            if self.headers.get("X-Assembly-Site") != "1" or not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._err(403, "missing site headers")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 1_000_000:
                    return self._err(413, "too large")
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._err(400, "body must be a JSON object")
            p = urlparse(self.path).path
            try:
                if p == "/api/captures":
                    kind, values = body.get("kind", ""), body.get("fields") or {}
                    if body.get("apply"):
                        return self._json(201, svc.capture(kind, values))
                    return self._json(200, svc.preview_new(kind, values))
                if p == "/api/handback":
                    return self._json(200, svc.handback(bool(body.get("apply"))))
                if p == "/api/backups":
                    return self._json(201, svc.backup())
                m = re.fullmatch(r"/api/backups/([0-9-]+)/verify", p)
                if m:
                    return self._json(200, svc.verify_backup(m.group(1)))
                m = re.fullmatch(r"/api/bundles/(bk-[0-9a-f]{8})/dispatch", p)
                if m:
                    return self._json(200, svc.bundle_dispatch(m.group(1), _day(body.get("on")), bool(body.get("apply")), body.get("ids")))
                if p == "/api/notes":
                    return self._json(200, svc.post_note(str(body.get("target", "")), body))
                m = re.fullmatch(r"/api/records/" + _ID + r"/(dispatch|set|retire|confirm|resume|supersede)", p)
                if m:
                    id, act = m.groups()
                    if act == "dispatch":
                        return self._json(200, svc.dispatch(id) if body.get("apply") else svc.dispatch_preview(id))
                    if act == "set":
                        ch, un = body.get("set") or {}, body.get("unset") or []
                        return self._json(200, svc.set(id, ch, un) if body.get("apply") else svc.set_preview(id, ch, un))
                    if act == "retire":
                        return self._json(200, svc.retire(id, str(body.get("reason", "")), bool(body.get("apply"))))
                    if act == "resume":
                        return self._json(200, svc.resume(id))
                    if act == "supersede":
                        return self._json(200, svc.supersede(id, str(body.get("by", "")), bool(body.get("apply"))))
                    return self._json(200, svc.confirm(id))
            except SiteError as e:
                return self._err(e.code, e.errors)
            return self._err(404, "not found")

    return H


def serve(svc: Service, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(svc))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="assembly-site", description="Local website for the Assembly System, centred on Dispatch.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ASSEMBLY_SITE_PORT", "8765")))
    ap.add_argument("--root", help="record store (default: $ASSEMBLY_ROOT or ~/.local/share/assembly-site/root); never inside this repo")
    a = ap.parse_args(argv)
    root = Path(a.root or os.environ.get("ASSEMBLY_ROOT") or "~/.local/share/assembly-site/root").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    svc = Service(root)
    srv = serve(svc, port=a.port)
    print("Assembly Site on http://127.0.0.1:%d  (records: %s)" % (a.port, root))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

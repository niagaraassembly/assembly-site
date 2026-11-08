"""Local question capture using Assembly's existing creation and change actions."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict
from urllib.parse import unquote, urlsplit

from assembly.change import ChangeError, apply_set, plan_set
from assembly.create import CreationError, apply_create
from assembly.ids import parse_id
from assembly.kinds import Kind
from assembly.records import list_ids, load

MAX_REQUEST_BYTES = 8 * 1024 * 1024
PROTECTED_FIELDS = {"text", "title", "source_question", "supersedes", "procedure", "writes", "machine", "path", "intake"}
ASSETS = Path(__file__).resolve().parent.parent / "web"


class RequestError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class AssemblyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, kinds, address, assets, metadata_fields):
        self.root, self.kinds, self.assets = Path(root), kinds, Path(assets)
        self.metadata_fields = tuple(metadata_fields)
        if len(set(self.metadata_fields)) != len(self.metadata_fields):
            raise ValueError("Duplicate field in the capture metadata policy.")
        for name in self.metadata_fields:
            if name in PROTECTED_FIELDS or kinds["question"].field(name) is None:
                raise ValueError("Unsupported capture metadata field: %s" % name)
        self.csrf_token = secrets.token_urlsafe(32)
        self.record_lock = threading.RLock()
        super().__init__(address, QuestionHandler)

    def question_lineage(self, id):
        """Read reverse links without letting an unrelated bad profile hide this question."""
        children, replacements = [], []
        for other_id in list_ids(self.root, "question"):
            if other_id == id:
                continue
            try:
                fields = load(self.root, other_id, self.kinds)["fields"]
                if fields.get("source_question") == id:
                    children.append(other_id)
                if fields.get("supersedes") == id:
                    replacements.append(other_id)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
        return {"derived_questions": sorted(children), "superseded_by": sorted(replacements)}

    def questions(self):
        records = [load(self.root, id, self.kinds) for id in list_ids(self.root, "question")]
        children, replacements = {}, {}
        for rec in records:
            fields = rec["fields"]
            if fields.get("source_question"):
                children.setdefault(fields["source_question"], []).append(rec["id"])
            if fields.get("supersedes"):
                replacements.setdefault(fields["supersedes"], []).append(rec["id"])
        for rec in records:
            rec["derived_questions"] = sorted(children.get(rec["id"], []))
            rec["superseded_by"] = sorted(replacements.get(rec["id"], []))
        return sorted(records, key=lambda r: (r["created"], parse_id(r["id"])[1]), reverse=True)


class QuestionHandler(BaseHTTPRequestHandler):
    server_version = "AssemblyLocal/0.1"

    def log_message(self, format, *args):
        return  # don't print question text, credentials or request bodies

    def _headers(self, status, content_type, length):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
                         "frame-ancestors 'none'; form-action 'self'")
        self.end_headers()

    def _json(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def _allowed_hosts(self):
        port = self.server.server_port
        return {"127.0.0.1:%s" % port, "localhost:%s" % port}

    def _check_host(self):
        if self.headers.get("Host", "").lower() not in self._allowed_hosts():
            raise RequestError(403, "Open Assembly using its localhost address.")

    def _check_write(self):
        self._check_host()
        origin = self.headers.get("Origin", "")
        if origin not in {"http://" + h for h in self._allowed_hosts()}:
            raise RequestError(403, "Save questions from the Assembly localhost page.")
        token = self.headers.get("X-Assembly-CSRF", "")
        if not token.isascii() or not secrets.compare_digest(token, self.server.csrf_token):
            raise RequestError(403, "This page's session has changed. Refresh before saving.")

    def _body(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise RequestError(415, "Send question data as JSON.")
        if self.headers.get("Transfer-Encoding"):
            raise RequestError(400, "Chunked requests are not supported.")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise RequestError(411, "A request length is required.")
        if length < 0:
            raise RequestError(400, "Invalid request length.")
        if length > MAX_REQUEST_BYTES:
            raise RequestError(413, "This submission exceeds the 8 MiB request limit. Your text has not been saved.")
        self.connection.settimeout(15)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError(400, "The submission was incomplete. Please retry.")
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeError, ValueError):
            raise RequestError(400, "The submission must be valid UTF-8 JSON.")
        if not isinstance(body, dict):
            raise RequestError(400, "A question must be a JSON object.")
        return body

    def _question(self, path, lineage=None):
        id = unquote(path.removeprefix("/api/questions/"))
        try:
            prefix, _ = parse_id(id)
        except ValueError:
            raise RequestError(404, "Question not found.")
        if prefix != self.server.kinds["question"].prefix:
            raise RequestError(404, "Question not found.")
        try:
            rec = load(self.server.root, id, self.server.kinds)
        except FileNotFoundError:
            raise RequestError(404, "Question not found.")
        if lineage is None:
            lineage = self.server.question_lineage(id)
        rec.update(lineage)
        return rec

    def _handle(self, action):
        try:
            action()
        except RequestError as error:
            self._json(error.status, {"error": str(error)})
        except (CreationError, ChangeError) as error:
            self._json(400, {"error": "; ".join(error.errors), "errors": error.errors})
        except (OSError, ValueError, KeyError):
            self._json(500, {"error": "Assembly could not read or save the record. Your entry is still available on this page."})

    def do_GET(self):
        self._handle(self._get)

    def _get(self):
        self._check_host()
        path = urlsplit(self.path).path
        if path == "/api/questions":
            with self.server.record_lock:
                self._json(200, {"questions": self.server.questions()})
            return
        if path.startswith("/api/questions/"):
            with self.server.record_lock:
                self._json(200, {"question": self._question(path)})
            return
        if path == "/api/schema":
            fields = self.server.kinds["question"].fields
            self._json(200, {"question_fields": [{"name": f.name, "type": f.type, "values": f.values,
                                                 "description": f.description} for f in fields if f.name in self.server.metadata_fields],
                             "max_request_bytes": MAX_REQUEST_BYTES})
            return
        assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                  "/styles.css": ("styles.css", "text/css")}
        if path not in assets:
            raise RequestError(404, "Page not found.")
        name, content_type = assets[path]
        raw = (self.server.assets / name).read_bytes()
        if name == "index.html":
            raw = raw.replace(b"__ASSEMBLY_CSRF__", self.server.csrf_token.encode("ascii"))
        self._headers(200, content_type + "; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def do_POST(self):
        self._handle(self._post)

    def _post(self):
        self._check_write()
        if urlsplit(self.path).path != "/api/questions":
            raise RequestError(404, "Page not found.")
        body = self._body()
        if set(body) - {"title", "text", "source_question"}:
            raise RequestError(400, "Capture accepts only title, text and an optional source question.")
        with self.server.record_lock:
            try:
                creation = apply_create(self.server.root, self.server.kinds, "question", body,
                                        self.server.root / "outbox" / "prompts", draft=True)
            except RuntimeError as error:
                if str(error).startswith("could not take the ID lock:"):
                    raise RequestError(503, "Assembly is busy creating another record. Your text has not been saved; retry shortly.")
                raise
            # A newly minted question cannot already have children or replacements.
            # The durable success receipt must not depend on reading other profiles.
            question = self._question("/api/questions/" + creation["id"],
                                      {"derived_questions": [], "superseded_by": []})
            self._json(201, {"question": question})

    def do_PATCH(self):
        self._handle(self._patch)

    def _patch(self):
        self._check_write()
        path = urlsplit(self.path).path
        if not path.startswith("/api/questions/"):
            raise RequestError(404, "Page not found.")
        body = self._body()
        if set(body) != {"fields", "rev"} or not isinstance(body["fields"], dict):
            raise RequestError(400, "Provide metadata fields and the current revision.")
        if isinstance(body["rev"], bool) or not isinstance(body["rev"], int) or body["rev"] < 0:
            raise RequestError(400, "Provide the current revision.")
        if set(body["fields"]) - set(self.server.metadata_fields):
            raise RequestError(400, "Only question metadata can be edited here. The original submission is preserved.")
        with self.server.record_lock:
            rec = self._question(path)
            if not rec.get("draft") or rec["status"] == "retired":
                raise RequestError(409, "Only active captured drafts can be edited here.")
            if rec.get("rev", 0) != body["rev"]:
                raise RequestError(409, "This question changed in another view. Load its latest revision before saving.")
            unset = [k for k, v in body["fields"].items() if v == ""]
            changes = {k: v for k, v in body["fields"].items() if k not in unset}
            plan = plan_set(self.server.root, self.server.kinds, rec["id"], changes, unset)
            if plan["errors"]:
                raise ChangeError(plan["errors"])
            apply_set(self.server.root, self.server.kinds, rec["id"], changes, unset, actor="local interface")
            # Metadata edits cannot change lineage. Reuse the pre-change links so a
            # later failure reading an unrelated profile cannot obscure a saved edit.
            lineage = {key: rec[key] for key in ("derived_questions", "superseded_by")}
            self._json(200, {"question": self._question(path, lineage)})


def make_server(root: Path, kinds: Dict[str, Kind], host="127.0.0.1", port=8031, assets=ASSETS, metadata_fields=()):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Assembly's local interface binds only to localhost.")
    if not 0 <= port <= 65535:
        raise ValueError("Choose a port between 0 and 65535.")
    return AssemblyServer(root, kinds, (host, port), assets, metadata_fields)


def run(root, kinds, host="127.0.0.1", port=8031, metadata_fields=()):
    server = make_server(root, kinds, host, port, metadata_fields=metadata_fields)
    print("Assembly: http://127.0.0.1:%s" % server.server_port, flush=True)
    print("Question records: %s" % Path(root).resolve(), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

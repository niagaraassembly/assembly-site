"""Site-owned annotations: comments, stars and flags on records and stages.

Append-only JSON lines in the site's own data directory (never in the Assembly record store, never in git).
Annotations are about records; they never edit a record and never flow into task documents. Text is kept
verbatim (a retract hides it from views, not from the file). Actor names are self-declared labels on a local
site, not authentication.
"""
import datetime
import json
import os
import re
import threading
import fcntl
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_TEXT = 4000


class NoteError(ValueError):
    pass


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _actor(a: Optional[str]) -> str:
    a = "".join(ch for ch in str(a or "") if ch.isprintable()).strip()[:40]
    return a or "owner"


def _text(s: str) -> str:
    return "".join(ch for ch in str(s) if ch in "\n\t" or ch.isprintable()).strip()


class Notes:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    # ---- storage
    def _sig(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _events(self) -> List[Dict[str, Any]]:
        """Parsed events, cached until the file changes (by this or any other process)."""
        sig = self._sig()
        c = getattr(self, "_cache", None)
        if c and c[0] == sig:
            return c[1]
        out = []
        if sig is not None:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue                      # a damaged line never hides the rest
                if isinstance(ev, dict) and ev.get("op") and ev.get("target"):
                    out.append(ev)
        self._cache = (sig, out, None)
        return out

    def _append(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        ev = dict(ev, at=_now())
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)         # exclusive across processes; released when the file closes
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return ev

    # ---- writes
    def comment(self, target: str, text: str, actor: str, parent: Optional[str] = None) -> Dict[str, Any]:
        text = _text(text)
        if not text:
            raise NoteError("comment: text is required")
        if len(text) > MAX_TEXT:
            raise NoteError("comment: longer than %d characters" % MAX_TEXT)
        if parent:
            p = [e for e in self._events() if e["op"] == "comment" and e["id"] == parent]
            if not p or p[0]["target"] != target:
                raise NoteError("comment: parent is not a comment on this item")
        return self._append({"id": uuid.uuid4().hex[:12], "op": "comment", "target": target,
                             "actor": _actor(actor), "text": text, "parent": parent})

    def star(self, target: str, actor: str, on: bool) -> Dict[str, Any]:
        return self._append({"op": "star", "target": target, "actor": _actor(actor), "on": bool(on)})

    def flag(self, target: str, actor: str, on: bool, reason: str = "") -> Dict[str, Any]:
        return self._append({"op": "flag", "target": target, "actor": _actor(actor), "on": bool(on),
                             "reason": _text(reason)[:300]})

    def resolve(self, comment_id: str, actor: str, on: bool) -> Dict[str, Any]:
        c = [e for e in self._events() if e["op"] == "comment" and e["id"] == comment_id]
        if not c:
            raise NoteError("resolve: no such comment")
        if c[0].get("parent"):
            raise NoteError("resolve: only the first comment of a thread can be resolved")
        return self._append({"op": "resolve", "target": c[0]["target"], "actor": _actor(actor), "ref": comment_id, "on": bool(on)})

    def seen(self, actor: str) -> Dict[str, Any]:
        """Mark everything up to now as read for this actor (mentions)."""
        return self._append({"op": "seen", "target": "@seen", "actor": _actor(actor)})

    _MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9._-]{1,40})")

    def _mentions(self, actor: str):
        """Mentions of actor as (event_index, mention). Event order, not clock time, decides what is unread."""
        me = _actor(actor).lower()
        evs = self._events()
        retracted = {e.get("ref") for e in evs if e["op"] == "retract"}
        out = []
        for i, e in enumerate(evs):
            if e["op"] != "comment" or e["id"] in retracted or e["actor"].lower() == me:
                continue
            if any(m.rstrip(".-_").lower() == me for m in self._MENTION.findall(e["text"])):
                out.append((i, {"id": e["id"], "target": e["target"], "actor": e["actor"], "at": e["at"], "text": e["text"]}))
        return out

    def mentions_for(self, actor: str) -> List[Dict[str, Any]]:
        return [m for _, m in self._mentions(actor)]

    def unread_mentions(self, actor: str) -> List[Dict[str, Any]]:
        me = _actor(actor)
        last = max((i for i, e in enumerate(self._events()) if e["op"] == "seen" and e["actor"] == me), default=-1)
        return [m for i, m in self._mentions(actor) if i > last]

    def hold(self, target: str, actor: str, on: bool, reason: str = "") -> Dict[str, Any]:
        """Hold a record back from dispatch. Site-level guard; the Assembly record is not changed."""
        return self._append({"op": "hold", "target": target, "actor": _actor(actor), "on": bool(on), "reason": _text(reason)[:300]})

    def retract(self, comment_id: str, actor: str) -> Dict[str, Any]:
        c = [e for e in self._events() if e["op"] == "comment" and e["id"] == comment_id]
        if not c:
            raise NoteError("retract: no such comment")
        if c[0]["actor"] != _actor(actor):
            raise NoteError("retract: only the author can retract a comment")
        return self._append({"op": "retract", "target": c[0]["target"], "actor": _actor(actor), "ref": comment_id})

    # ---- reads
    def _state(self) -> Dict[str, Dict[str, Any]]:
        """Replay every event once into per-target state; cached with the events."""
        evs = self._events()
        c = self._cache
        if c[2] is not None:
            return c[2]
        st: Dict[str, Dict[str, Any]] = {}
        for e in evs:
            t = st.setdefault(e["target"], {"comments": {}, "order": [], "stars": {}, "flag": None, "hold": None})
            op = e["op"]
            if op == "comment":
                t["comments"][e["id"]] = {"id": e["id"], "actor": e["actor"], "at": e["at"], "text": e["text"], "parent": e.get("parent"),
                                          "retracted": False, "resolved": False, "resolved_by": None}
                t["order"].append(e["id"])
            elif op == "retract" and e.get("ref") in t["comments"]:
                t["comments"][e["ref"]].update(retracted=True, text=None)
            elif op == "resolve" and e.get("ref") in t["comments"]:
                t["comments"][e["ref"]].update(resolved=bool(e.get("on")), resolved_by=e["actor"] if e.get("on") else None)
            elif op == "star":
                t["stars"][e["actor"]] = bool(e.get("on"))
            elif op in ("flag", "hold"):
                t[op] = {"actor": e["actor"], "at": e["at"], "reason": e.get("reason", "")} if e.get("on") else None
        self._cache = (c[0], c[1], st)
        return st

    def view(self, target: str) -> Dict[str, Any]:
        t = self._state().get(target) or {"comments": {}, "order": [], "stars": {}, "flag": None, "hold": None}
        return {"target": target, "comments": [dict(t["comments"][i]) for i in t["order"]],
                "starred_by": sorted(a for a, on in t["stars"].items() if on), "flag": t["flag"], "hold": t["hold"]}

    def index(self) -> Dict[str, Dict[str, Any]]:
        """Per-target summary: {comments, starred, flagged, held}. Retracted comments do not count."""
        return {tg: {"comments": sum(1 for c in t["comments"].values() if not c["retracted"]),
                     "starred": any(t["stars"].values()), "flagged": t["flag"] is not None, "held": t["hold"] is not None}
                for tg, t in self._state().items()}

    def activity(self, limit: int = 50) -> List[Dict[str, Any]]:
        evs = self._events()
        texts = {e["id"]: e for e in evs if e["op"] == "comment"}
        out = []
        for e in reversed(evs):
            row = dict(e)
            if e["op"] in ("retract", "seen", "resolve"):
                continue
            if e["op"] == "comment" and any(r["op"] == "retract" and r.get("ref") == e["id"] for r in evs):
                row["text"] = None
                row["retracted"] = True
            out.append(row)
            if len(out) >= limit:
                break
        return out

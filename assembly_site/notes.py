"""Site-owned annotations: comments, stars and flags on records and stages.

Append-only JSON lines in the site's own data directory (never in the Assembly record store, never in git).
Annotations are about records; they never edit a record and never flow into task documents. Text is kept
verbatim (a retract hides it from views, not from the file). Actor names are self-declared labels on a local
site, not authentication.
"""
import datetime
import json
import os
import threading
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
    def _events(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue                      # a damaged line never hides the rest
            if isinstance(ev, dict) and ev.get("op") and ev.get("target"):
                out.append(ev)
        return out

    def _append(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        ev = dict(ev, at=_now())
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
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
    def view(self, target: str) -> Dict[str, Any]:
        comments: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        stars: Dict[str, bool] = {}
        flag = None
        hold = None
        for e in self._events():
            if e["target"] != target:
                continue
            if e["op"] == "comment":
                comments[e["id"]] = {"id": e["id"], "actor": e["actor"], "at": e["at"], "text": e["text"],
                                     "parent": e.get("parent"), "retracted": False}
                order.append(e["id"])
            elif e["op"] == "retract" and e.get("ref") in comments:
                comments[e["ref"]].update(retracted=True, text=None)
            elif e["op"] == "star":
                stars[e["actor"]] = bool(e.get("on"))
            elif e["op"] == "flag":
                flag = {"actor": e["actor"], "at": e["at"], "reason": e.get("reason", "")} if e.get("on") else None
            elif e["op"] == "hold":
                hold = {"actor": e["actor"], "at": e["at"], "reason": e.get("reason", "")} if e.get("on") else None
        return {"target": target, "comments": [comments[i] for i in order],
                "starred_by": sorted(a for a, on in stars.items() if on), "flag": flag, "hold": hold}

    def index(self) -> Dict[str, Dict[str, Any]]:
        """Per-target summary: {comments, starred, flagged}. Retracted comments do not count."""
        idx: Dict[str, Dict[str, Any]] = {}
        targets = []
        for e in self._events():
            if e["target"] not in idx:
                idx[e["target"]] = {}
                targets.append(e["target"])
        for t in targets:
            v = self.view(t)
            idx[t] = {"comments": sum(1 for c in v["comments"] if not c["retracted"]),
                      "starred": bool(v["starred_by"]), "flagged": v["flag"] is not None, "held": v["hold"] is not None}
        return idx

    def activity(self, limit: int = 50) -> List[Dict[str, Any]]:
        evs = self._events()
        texts = {e["id"]: e for e in evs if e["op"] == "comment"}
        out = []
        for e in reversed(evs):
            row = dict(e)
            if e["op"] == "retract":
                continue
            if e["op"] == "comment" and any(r["op"] == "retract" and r.get("ref") == e["id"] for r in evs):
                row["text"] = None
                row["retracted"] = True
            out.append(row)
            if len(out) >= limit:
                break
        return out

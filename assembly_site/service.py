"""Site operations over the Assembly core. Every write goes through the core's creation/change actions.

Rules from AGENTS.md enforced here:
- capturing a draft never dispatches; dispatch is a separate, explicit action (preview first);
- an absent machine-flows is never shown as completed work: a dispatched record only means a task
  document was written to the outbox;
- editable metadata comes from the core schema, minus an explicit lock list.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import re

from . import core, stages as stagelib
from .notes import NoteError, Notes
from .core import KINDS, change, create, handback, handoff, records

# Fields the site never lets a person edit directly (provenance and links managed by actions).
EDIT_LOCKED = {"supersedes"}
PIPELINE = ["new", "dispatched", "running", "awaiting-confirmation", "answered", "failed", "retired"]


class SiteError(ValueError):
    def __init__(self, errors: List[str], code: int = 400):
        super().__init__("; ".join(errors))
        self.errors, self.code = errors, code


class Service:
    def __init__(self, root: Path, outbox: Optional[Path] = None, runs: Optional[Path] = None, data: Optional[Path] = None):
        self.root = Path(root)
        self.data = Path(data or os.environ.get("ASSEMBLY_SITE_DATA") or self.root.parent / "site-data").expanduser()
        self.notes_store = Notes(self.data / "annotations.jsonl")
        self.outbox = Path(outbox or os.environ.get("ASSEMBLY_OUTBOX") or self.root / "outbox" / "prompts").expanduser()
        self.runs = Path(runs or os.environ.get("ASSEMBLY_RUNS") or "~/machine-flows/files/runs").expanduser()

    # ---- reading
    def kinds(self) -> List[Dict[str, Any]]:
        out = []
        for k in KINDS.values():
            out.append({"name": k.name, "prefix": k.prefix, "description": k.description,
                        "dispatchable": any(s["do"] == "handoff" for s in k.steps),
                        "fields": [{"name": f.name, "type": f.type, "required": f.required, "values": f.values,
                                    "target": f.target, "description": f.description, "pattern": f.pattern,
                                    "editable": f.name not in EDIT_LOCKED} for f in k.fields]})
        return out

    def _load(self, id: str) -> Dict[str, Any]:
        try:
            return records.load(self.root, id, KINDS)
        except (ValueError, KeyError, OSError):
            raise SiteError(["%s: no such record" % id], 404)

    def _creation(self, id: str) -> Optional[Dict[str, Any]]:
        p = self.root / "creations" / (id + ".json")
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _row(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        c = self._creation(rec["id"])
        f = rec["fields"]
        return {"id": rec["id"], "kind": rec["kind"], "status": rec["status"], "rev": rec.get("rev", 0),
                "created": rec["created"], "title": " ".join(str(f.get("text") or f.get("name") or "").split())[:140],
                "lens": f.get("lens"), "intake": f.get("intake"), "trust": f.get("trust"), "due": f.get("due"),
                "sensitivity": f.get("sensitivity"), "creation": c["state"] if c else None,
                "last": rec["history"][-1] if rec["history"] else None}

    def records(self, kind: Optional[str] = None, status: Optional[str] = None, starred: bool = False) -> List[Dict[str, Any]]:
        rows = []
        idx = self.notes_store.index()
        for k in KINDS.values():
            if kind and k.name != kind:
                continue
            for id in records.list_ids(self.root, k.name):
                r = self._row(records.load(self.root, id, KINDS))
                n = idx.get(id, {})
                r.update(starred=n.get("starred", False), flagged=n.get("flagged", False), notes=n.get("comments", 0))
                rows.append(r)
        if starred:
            rows = [r for r in rows if r["starred"]]
        if status:
            rows = [r for r in rows if r["status"] == status]
        return sorted(rows, key=lambda r: r["created"], reverse=True)

    def summary(self) -> Dict[str, Any]:
        rows = self.records()
        by_status: Dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        dispatchable = {k.name for k in KINDS.values() if any(s["do"] == "handoff" for s in k.steps)}
        drafts = [r for r in rows if r["creation"] == "draft" and r["status"] == "new"]
        return {"total": len(rows), "by_status": by_status, "pipeline": PIPELINE,
                "by_kind": {k: sum(1 for r in rows if r["kind"] == k) for k in KINDS},
                "drafts": drafts,
                "attention": [r for r in rows if r["status"] in ("awaiting-confirmation", "failed")],
                "in_flight": [r for r in rows if r["status"] in ("dispatched", "running")],
                "dispatchable_kinds": sorted(dispatchable), "outbox": str(self.outbox), "runs": str(self.runs),
                "runs_present": self.runs.is_dir()}

    def record(self, id: str) -> Dict[str, Any]:
        rec = self._load(id)
        out = {"record": rec, "creation": self._creation(id), "tasks": []}
        if rec["status"] != "retired":
            try:
                out["tasks"] = self._tasks(rec)
            except ValueError as e:
                out["task_error"] = str(e)
        return out

    def _steps(self, rec):
        kind = KINDS[rec["kind"]]
        return kind, [s for s in kind.steps if s["do"] == "handoff" and create._applies(s, rec["fields"])]

    def _tasks(self, rec) -> List[Dict[str, Any]]:
        kind, steps = self._steps(rec)
        tasks = []
        for s in steps:
            name, md = handoff.build_task(rec, kind, s)
            errs = handoff.check_task(md)
            tasks.append({"step": s["id"], "file": name, "markdown": md, "errors": errs,
                          "written": (self.outbox / name).exists()})
        return tasks

    # ---- capture (never dispatches)
    def _validate_new(self, kind: str, values: Dict[str, Any]) -> Dict[str, Any]:
        plan = create.plan_create(self.root, KINDS, kind, values)
        if plan["errors"]:
            raise SiteError(plan["errors"])
        return plan

    def preview_new(self, kind: str, values: Dict[str, Any]) -> Dict[str, Any]:
        plan = self._validate_new(kind, values)
        return {"kind": kind, "fields": values, "steps": plan["steps"], "note": "Capturing saves a draft. It does not dispatch."}

    def capture(self, kind: str, values: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_new(kind, values)
        try:
            c = create.apply_create(self.root, KINDS, kind, values, self.outbox, hold_handoffs=True)
        except create.CreationError as e:
            raise SiteError(e.errors)
        return {"creation": c, "record": self._load(c["id"])}

    # ---- dispatch (separate, explicit)
    def dispatch_preview(self, id: str) -> Dict[str, Any]:
        rec = self._load(id)
        if rec["status"] == "retired":
            raise SiteError(["%s is retired; nothing is dispatched for a retired record" % id])
        tasks = self._tasks(rec)
        if not tasks:
            raise SiteError(["nothing to dispatch for %s (no handoff step applies)" % id])
        bad = [e for t in tasks for e in t["errors"]]
        return {"id": id, "tasks": tasks, "outbox": str(self.outbox), "errors": bad,
                "meaning": "Applying writes the task document to the outbox for machine-flows. It does not run it."}

    def dispatch(self, id: str) -> Dict[str, Any]:
        prev = self.dispatch_preview(id)
        if prev["errors"]:
            raise SiteError(prev["errors"])
        rec = self._load(id)
        c = self._creation(id)
        if c and any(s["status"] == "held" for s in c["steps"]):
            create.release_held(self.root, KINDS, id, self.outbox)
        else:
            kind, steps = self._steps(rec)
            for s in steps:
                handoff.emit_for_step(self.root, rec, kind, s, self.outbox)
            if rec["status"] == "new":
                rec["status"] = "dispatched"
                records.add_event(rec, "dispatched", "dispatch from site")
                records.save(self.root, rec)
        return self.record(id)

    # ---- changes (core actions)
    def _guard(self, fn):
        try:
            return fn()
        except change.ChangeError as e:
            raise SiteError(e.errors)

    def set_preview(self, id: str, changes: Dict[str, Any], unset: List[str]) -> Dict[str, Any]:
        rec = self._load(id)
        locked = [k for k in list(changes) + list(unset) if k in EDIT_LOCKED]
        if locked:
            raise SiteError(["%s: not editable here" % k for k in locked])
        plan = self._guard(lambda: change.plan_set(self.root, KINDS, id, changes, unset))
        if plan["errors"]:
            raise SiteError(plan["errors"])
        return {"id": id, "diff": plan["diff"], "rev": plan["rev"],
                "redispatch": bool(plan["diff"]) and rec["status"] != "new" and bool(self._steps(rec)[1])}

    def set(self, id: str, changes: Dict[str, Any], unset: List[str], actor: str = "owner (site)") -> Dict[str, Any]:
        self.set_preview(id, changes, unset)
        self._guard(lambda: change.apply_set(self.root, KINDS, id, changes, unset, actor=actor))
        return self.record(id)

    def retire(self, id: str, reason: str, apply: bool, actor: str = "owner (site)") -> Dict[str, Any]:
        if not reason.strip():
            raise SiteError(["reason: required"])
        self._guard(lambda: change.check_retire(self.root, KINDS, id))
        if apply:
            self._guard(lambda: change.retire(self.root, KINDS, id, reason, actor=actor))
        return self.record(id) if apply else {"id": id, "would": "retire", "reason": reason}

    def confirm(self, id: str) -> Dict[str, Any]:
        rec = self._load(id)
        if rec["status"] != "awaiting-confirmation":
            raise SiteError(["%s is %s, not awaiting-confirmation; only the owner confirms a finished run" % (id, rec["status"])])
        rec["status"] = "answered"
        records.add_event(rec, "confirmed", "owner (site)")
        records.save(self.root, rec)
        return self.record(id)

    # ---- handback (reads machine-flows run records)
    def handback(self, apply: bool) -> Dict[str, Any]:
        log = handback.apply_handback(self.root, KINDS, self.runs, dry_run=not apply)
        return {"log": log, "applied": apply, "runs": str(self.runs), "runs_present": self.runs.is_dir()}

    # ---- stage map
    def _count(self, rows, b) -> int:
        n = 0
        for r in rows:
            if r["kind"] != b["kind"]:
                continue
            if b["statuses"] and r["status"] not in b["statuses"]:
                continue
            if b["draft"] is True and r["creation"] != "draft":
                continue
            if b["draft"] is False and r["creation"] == "draft":
                continue
            n += 1
        return n

    def stages(self) -> List[Dict[str, Any]]:
        rows = self.records()
        idx = self.notes_store.index()
        out = []
        for st in stagelib.STAGES:
            subs = []
            for sub in st["substages"]:
                state = stagelib.sub_state(sub)
                n = idx.get("stage:%s.%s" % (st["key"], sub["key"]), {})
                subs.append({"key": sub["key"], "title": sub["title"], "summary": sub["summary"], "state": state,
                             "reason": stagelib.sub_reason(sub, state), "gate": sub["gate"], "plan": sub["plan"],
                             "buckets": [dict(b, count=self._count(rows, b)) for b in sub["buckets"]],
                             "actions": sub["actions"] if state != "unbuilt" else [],
                             "target": "stage:%s.%s" % (st["key"], sub["key"]),
                             "notes": n.get("comments", 0), "starred": n.get("starred", False), "flagged": n.get("flagged", False)})
            states = {x["state"] for x in subs}
            state = "built" if states == {"built"} else ("unbuilt" if states == {"unbuilt"} else "partial")
            n = idx.get("stage:" + st["key"], {})
            out.append({"key": st["key"], "group": st["group"], "title": st["title"], "ref": st["ref"], "summary": st["summary"],
                        "state": state, "substages": subs, "target": "stage:" + st["key"],
                        "notes": n.get("comments", 0), "starred": n.get("starred", False), "flagged": n.get("flagged", False)})
        return out

    def stage(self, key: str) -> Dict[str, Any]:
        for s in self.stages():
            if s["key"] == key:
                return s
        raise SiteError(["%s: no such stage" % key], 404)

    def gates(self) -> List[Dict[str, Any]]:
        by = {}
        for st in self.stages():
            for sub in st["substages"]:
                by["%s.%s" % (st["key"], sub["key"])] = sub
        out = []
        for g in stagelib.GATES:
            sub = by[g["at"]]
            out.append(dict(g, state=sub["state"], reason=sub["reason"], pending=sum(b["count"] for b in sub["buckets"]),
                            actions=sub["actions"], target=sub["target"]))
        return out

    # ---- notes (comments, stars, flags): about records, never edits to them
    def _target_title(self, target: str) -> Optional[str]:
        m = re.fullmatch(r"stage:([a-z0-9]+)(?:\.([a-z0-9]+))?", target)
        if m:
            for st in stagelib.STAGES:
                if st["key"] == m.group(1):
                    if not m.group(2):
                        return st["title"]
                    for sub in st["substages"]:
                        if sub["key"] == m.group(2):
                            return "%s / %s" % (st["title"], sub["title"])
            return None
        if re.fullmatch(r"[A-Z]+-\d{4,}", target):
            try:
                return self._row(records.load(self.root, target, KINDS))["title"] or target
            except (ValueError, KeyError, OSError):
                return None
        return None

    def notes(self, target: str) -> Dict[str, Any]:
        if self._target_title(target) is None:
            raise SiteError(["%s: no such record or stage" % target], 404)
        v = self.notes_store.view(target)
        v["title"] = self._target_title(target)
        return v

    def post_note(self, target: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if self._target_title(target) is None:
            raise SiteError(["%s: no such record or stage" % target], 404)
        op, actor = body.get("op"), body.get("actor")
        try:
            if op == "comment":
                self.notes_store.comment(target, body.get("text", ""), actor, body.get("parent"))
            elif op == "star":
                self.notes_store.star(target, actor, bool(body.get("on", True)))
            elif op == "flag":
                self.notes_store.flag(target, actor, bool(body.get("on", True)), body.get("reason", ""))
            elif op == "retract":
                self.notes_store.retract(str(body.get("id", "")), actor)
            else:
                raise SiteError(["op: must be comment, star, flag or retract"])
        except NoteError as e:
            raise SiteError([str(e)])
        return self.notes(target)

    def activity(self, limit: int = 50) -> List[Dict[str, Any]]:
        out = []
        for e in self.notes_store.activity(limit):
            t = self._target_title(e["target"])
            if t is not None:
                out.append(dict(e, title=t))
        return out

    def starred(self) -> List[Dict[str, Any]]:
        out = []
        for target, n in self.notes_store.index().items():
            if n["starred"] and self._target_title(target) is not None:
                out.append({"target": target, "title": self._target_title(target), "flagged": n["flagged"], "comments": n["comments"]})
        return sorted(out, key=lambda x: x["target"])

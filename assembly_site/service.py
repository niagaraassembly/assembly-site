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
import datetime
import hashlib
import shutil

from .core import lint as lint_mod
from .core import KINDS, bundle as bundlelib, change, create, handback, handoff, records

# Fields the site never lets a person edit directly (provenance and links managed by actions).
EDIT_LOCKED = {"supersedes"}
PIPELINE = ["new", "dispatched", "running", "awaiting-confirmation", "answered", "failed", "retired"]


def targetroute(t: str) -> str:
    return "#/stage/" + t[6:].split(".")[0] if t.startswith("stage:") else "#/r/" + t


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
        return {"kind": kind, "fields": values, "steps": plan["steps"], "similar": self.similar(kind, values),
                "note": "Capturing saves a draft. It does not dispatch."}

    # ---- duplicate warning (advisory; never blocks) and bulk capture
    _STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "what", "which", "that", "this", "with", "at", "by"}

    def _primary(self, kind: str) -> Optional[str]:
        k = KINDS.get(kind)
        for name in ("text", "name"):
            if k and k.field(name):
                return name
        return None

    def _tokens(self, s: str) -> set:
        import re as _re
        t = [x for x in _re.findall(r"[a-z0-9]+", str(s).lower()) if x not in self._STOP]
        t = [{"street": "st", "avenue": "ave", "road": "rd"}.get(x, x) for x in t]
        return set(t)

    def similar(self, kind: str, values: Dict[str, Any], threshold: float = 0.6) -> List[Dict[str, Any]]:
        prim = self._primary(kind)
        mine = self._tokens(values.get(prim, "")) if prim else set()
        if not mine:
            return []
        out = []
        for r in self.records(kind):
            if r["status"] == "retired":
                continue
            theirs = self._tokens(r["title"])
            if not theirs:
                continue
            score = len(mine & theirs) / len(mine | theirs)
            if score >= threshold:
                out.append({"id": r["id"], "title": r["title"], "status": r["status"], "score": round(score, 2)})
        return sorted(out, key=lambda x: -x["score"])

    BULK_MAX = 50

    def capture_bulk(self, kind: str, common: Dict[str, Any], texts: List[str], apply: bool) -> Dict[str, Any]:
        prim = self._primary(kind)
        if kind not in KINDS or not prim:
            raise SiteError(["%s: bulk capture is not available for this kind" % kind])
        if len(texts) > self.BULK_MAX:
            raise SiteError(["at most %d lines at a time" % self.BULK_MAX])
        errors, items = [], []
        for n, t in enumerate(texts, 1):
            if not str(t).strip():
                errors.append("line %d: empty" % n)
                continue
            values = dict(common, **{prim: str(t).strip()})
            plan = create.plan_create(self.root, KINDS, kind, values)
            errors += ["line %d: %s" % (n, e) for e in plan["errors"]]
            items.append({"line": n, "fields": values, "similar": self.similar(kind, values)})
        if errors or not items:
            raise SiteError(errors or ["nothing to capture"])       # nothing is minted unless every line is valid
        if not apply:
            return {"kind": kind, "items": items, "note": "Each line becomes its own draft. None is dispatched."}
        created = []
        for it in items:
            c = self.capture(kind, it["fields"])
            created.append({"id": c["record"]["id"], "state": c["creation"]["state"], "line": it["line"]})
        return {"kind": kind, "created": created}

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
            c2 = create.release_held(self.root, KINDS, id, self.outbox)
            bad = [st["detail"] for st in c2["steps"] if st["status"] in ("failed", "pending")]
            if bad:
                raise SiteError(["task document was not written (%s). The record stays a draft you can resume." % "; ".join(bad)])
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

    # ---- bundles (grouping rules live in the core; the site only presents and invokes)
    READY_ORDER = ("ready", "needs-you", "failed", "in-flight", "manual", "blocked", "done")

    def _readiness(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        f, st = rec["fields"], rec["status"]
        out = {"readiness": "blocked", "why": "", "needs_approval": bool(f.get("writes")) or f.get("trust", "external") != "owner"}
        if st == "new":
            if f.get("intake") == "file":
                out.update(readiness="manual", why="Intake is by filing: a person attaches the source records. No task document is written.")
            else:
                try:
                    tasks = self._tasks(rec)
                    errs = [e for t in tasks for e in t["errors"]]
                    out.update(readiness="blocked", why="; ".join(errs)) if errs or not tasks else out.update(readiness="ready", why="Task document can be written.")
                    if not tasks and not errs:
                        out["why"] = "No handoff step applies."
                except ValueError as e:
                    out.update(readiness="blocked", why=str(e))
        elif st in ("dispatched", "running"):
            out.update(readiness="in-flight", why="Task document written; waiting on machine-flows.")
        elif st == "awaiting-confirmation":
            out.update(readiness="needs-you", why="Run finished. Read the result and confirm.")
        elif st == "failed":
            out.update(readiness="failed", why="machine-flows reports the run failed or was cancelled.")
        elif st == "answered":
            out.update(readiness="done", why="Answered.")
        return out

    def bundles(self, on: Optional[datetime.date] = None) -> Dict[str, Any]:
        on = on or datetime.date.today()
        p = bundlelib.plan(self.root, KINDS, on)
        idx = self.notes_store.index()
        out, totals = [], {k: 0 for k in self.READY_ORDER}
        for b in p["bundles"]:
            members, counts = [], {k: 0 for k in self.READY_ORDER}
            for m in b["members"]:
                rec = self._load(m["id"])
                row = self._row(rec)
                n = idx.get(m["id"], {})
                x = dict(m, title=row["title"], status=rec["status"], lens=rec["fields"].get("lens"), created=row["created"],
                         starred=n.get("starred", False), flagged=n.get("flagged", False), notes=n.get("comments", 0),
                         **self._readiness(rec))
                members.append(x)
                counts[x["readiness"]] += 1
                totals[x["readiness"]] += 1
            out.append(dict(b, members=members, counts=counts))
        return {"on": on.isoformat(), "period": p["period"], "bundles": out, "excluded": p["excluded"], "totals": totals,
                "cap": bundlelib.CAP}

    def _bundle(self, key_id: str, on) -> Dict[str, Any]:
        for b in self.bundles(on)["bundles"]:
            if b["key_id"] == key_id:
                return b
        raise SiteError(["%s: no such bundle on %s" % (key_id, (on or datetime.date.today()).isoformat())], 404)

    def bundle_dispatch(self, key_id: str, on, apply: bool, ids: Optional[List[str]] = None) -> Dict[str, Any]:
        b = self._bundle(key_id, on)
        ready = [m["id"] for m in b["members"] if m["readiness"] == "ready"]
        if ids is not None:
            unknown = [i for i in ids if i not in {m["id"] for m in b["members"]}]
            if unknown:
                raise SiteError(["%s: not in this bundle" % i for i in unknown])
            ready = [i for i in ready if i in ids]
        if not ready:
            raise SiteError(["nothing ready to dispatch in this bundle"])
        if not apply:
            return {"key_id": key_id, "outbox": str(self.outbox),
                    "meaning": "Applying writes one task document per question to the outbox for machine-flows. It does not run them. "
                               "(v0 has one task per question; a per-bundle dispatch record comes with Plan 2.)",
                    "members": [dict(self.dispatch_preview(i), needs_approval=self._readiness(self._load(i))["needs_approval"]) for i in ready]}
        results = []
        for i in ready:
            try:
                self.dispatch(i)
                results.append({"id": i, "ok": True})
            except SiteError as e:
                results.append({"id": i, "ok": False, "errors": e.errors})
        return {"key_id": key_id, "results": results}

    # ---- the Dispatch workbench: what to do next, in order
    def workbench(self, on: Optional[datetime.date] = None) -> Dict[str, Any]:
        v = self.bundles(on)
        rows = {r["id"]: r for r in self.records("question")}
        by = lambda st: [r for r in rows.values() if r["status"] == st]
        ready_bundles = [b for b in v["bundles"] if b["counts"]["ready"]]
        needs, failed = by("awaiting-confirmation"), by("failed")
        flight = by("dispatched") + by("running")
        t = v["totals"]
        nxt = []
        if needs:
            nxt.append({"kind": "review", "label": "Review %d finished run%s" % (len(needs), "" if len(needs) == 1 else "s"),
                        "detail": "machine-flows says done. Only you mark a question answered.", "cta": "Review result", "route": "#/r/" + needs[0]["id"]})
        if failed:
            nxt.append({"kind": "failed", "label": "Look at %d failed run%s" % (len(failed), "" if len(failed) == 1 else "s"),
                        "detail": "Fix the question or dispatch again.", "cta": "Open failed run", "route": "#/r/" + failed[0]["id"]})
        if ready_bundles:
            nxt.append({"kind": "dispatch-ready", "label": "Dispatch %d ready question%s in %d bundle%s" % (
                t["ready"], "" if t["ready"] == 1 else "s", len(ready_bundles), "" if len(ready_bundles) == 1 else "s"),
                "detail": "Preview the task documents, then write them to the outbox.", "cta": "Open bundles", "route": "#/bundles"})
        if flight:
            nxt.append({"kind": "track", "label": "Check runs for %d dispatched question%s" % (len(flight), "" if len(flight) == 1 else "s"),
                        "detail": "Reads machine-flows run records (read-only).", "cta": "Check runs", "route": None})
        if not nxt:
            nxt.append({"kind": "capture", "label": "Nothing to do. Capture a question.", "detail": "Saving makes a draft; it does not dispatch.", "cta": "Capture question", "route": "#/new?kind=question"})
        steps = [
            {"key": "capture", "label": "1 Capture", "count": len([r for r in rows.values() if r["status"] != "retired"]), "hint": "questions", "route": "#/new?kind=question"},
            {"key": "bundle", "label": "2 Bundle", "count": len(v["bundles"]), "hint": "bundles", "route": "#/bundles"},
            {"key": "dispatch", "label": "3 Dispatch", "count": t["ready"], "hint": "ready", "route": "#/bundles"},
            {"key": "track", "label": "4 Track", "count": len(flight), "hint": "in flight", "route": None},
            {"key": "review", "label": "5 Review", "count": len(needs) + len(failed), "hint": "need you", "route": "#/records?status=awaiting-confirmation"},
        ]
        return {"on": v["on"], "next": nxt, "steps": steps, "ready_bundles": ready_bundles, "needs_you": needs, "failed": failed,
                "in_flight": flight, "runs": str(self.runs), "runs_present": self.runs.is_dir(), "outbox": str(self.outbox),
                "excluded": v["excluded"]}

    # ---- result (read-only view of the latest machine-flows run)
    def result(self, id: str) -> Dict[str, Any]:
        self._load(id)
        return {"id": id, "runs": str(self.runs), "runs_present": self.runs.is_dir(),
                "result": handback.run_result(self.runs, id)}

    # ---- inbox: everything that wants the operator, most pressing first
    AGING_DAYS = 3
    _INBOX_ORDER = {"review": 0, "failed": 1, "partial": 2, "aging": 3, "flagged": 4}

    def inbox(self) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        now = datetime.datetime.now().astimezone()
        idx = self.notes_store.index()
        for r in self.records():
            last = (r["last"] or {}).get("at") or r["created"]
            base = {"id": r["id"], "title": r["title"], "route": "#/r/" + r["id"], "at": last}
            if r["status"] == "awaiting-confirmation":
                items.append(dict(base, kind="review", detail="Run finished. Read the result, then confirm."))
            elif r["status"] == "failed":
                items.append(dict(base, kind="failed", detail="The run failed or was cancelled."))
            elif r["status"] in ("dispatched", "running"):
                try:
                    age = now - datetime.datetime.fromisoformat(last)
                except ValueError:
                    age = datetime.timedelta(0)
                if age >= datetime.timedelta(days=self.AGING_DAYS):
                    items.append(dict(base, kind="aging", detail="No change for %d days since the task document was written." % age.days))
            if r["creation"] == "partial":
                items.append(dict(base, kind="partial", detail="Creation is partial. Resume it to finish the remaining steps."))
        for target, n in idx.items():
            if n["flagged"]:
                title = self._target_title(target)
                if title is not None:
                    v = self.notes_store.view(target)
                    items.append({"kind": "flagged", "id": target, "title": title, "route": targetroute(target),
                                  "detail": "Flagged by %s: %s" % (v["flag"]["actor"], v["flag"]["reason"] or "(no reason)"), "at": v["flag"]["at"]})
        items.sort(key=lambda i: (self._INBOX_ORDER[i["kind"]], i["at"]))
        return {"items": items, "count": len(items)}

    # ---- resume a partial creation; supersede
    def resume(self, id: str) -> Dict[str, Any]:
        c = self._creation(id)
        if not c or c["state"] != "partial":
            raise SiteError(["%s: no partial creation to resume" % id])
        self._guard_create(lambda: create.resume_create(self.root, KINDS, id, self.outbox))
        return self.record(id)

    def _guard_create(self, fn):
        try:
            return fn()
        except (create.CreationError, OSError, ValueError) as e:
            raise SiteError([str(e)])

    def supersede(self, old: str, by: str, apply: bool, actor: str = "owner (site)") -> Dict[str, Any]:
        self._guard(lambda: change.check_supersede(self.root, KINDS, old, by))
        if not apply:
            return {"would": "supersede", "old": old, "by": by}
        self._guard(lambda: change.supersede(self.root, KINDS, old, by, actor=actor))
        return self.record(old)

    # ---- health and backups
    def health(self) -> Dict[str, Any]:
        errors, warnings = lint_mod.lint(self.root, KINDS)
        return {"errors": errors, "warnings": warnings, "backups": self.backups(), "root": str(self.root), "data": str(self.data)}

    _BK = re.compile(r"^\d{8}-\d{6}(?:-\d+)?$")

    def _sha(self, p: Path) -> str:
        h = hashlib.sha256()
        h.update(p.read_bytes())
        return h.hexdigest()

    def backup(self) -> Dict[str, Any]:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        base = self.data / "backups"
        name, n = stamp, 0
        while (base / name).exists():
            n += 1
            name = "%s-%d" % (stamp, n)
        dest = base / name
        manifest: Dict[str, str] = {}
        sources = [("records/" + d, self.root / d) for d in ("profiles", "creations", "registry")] + [("site/annotations.jsonl", self.data / "annotations.jsonl")]
        for rel, src in sources:
            files = [src] if src.is_file() else (sorted(x for x in src.rglob("*") if x.is_file()) if src.is_dir() else [])
            for f in files:
                if f.name.startswith(".") or f.suffix == ".lock":
                    continue
                r = rel if src.is_file() else rel + "/" + str(f.relative_to(src))
                (dest / r).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest / r)
                manifest[r] = self._sha(dest / r)
        (dest / "manifest.json").write_text(json.dumps({"created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                                                       "files": manifest}, indent=2, sort_keys=True), encoding="utf-8")
        v = self.verify_backup(name)
        return {"name": name, "files": len(manifest), "verified": v["ok"]}

    def backups(self) -> List[Dict[str, Any]]:
        base = self.data / "backups"
        out = []
        for d in sorted(base.iterdir(), reverse=True) if base.is_dir() else []:
            if d.is_dir() and self._BK.match(d.name) and (d / "manifest.json").exists():
                m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
                out.append({"name": d.name, "created": m.get("created"), "files": len(m.get("files", {}))})
        return out

    def verify_backup(self, name: str) -> Dict[str, Any]:
        if not self._BK.match(name or ""):
            raise SiteError(["backup name: not valid"])
        d = self.data / "backups" / name
        if not (d / "manifest.json").exists():
            raise SiteError(["%s: no such backup" % name], 404)
        files = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["files"]
        bad = [r for r, sha in files.items() if not (d / r).is_file() or self._sha(d / r) != sha]
        return {"name": name, "ok": not bad, "checked": len(files), "bad": bad}

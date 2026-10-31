"""The stage map: every stage and substage of the Assembly flow, per the Dispatch briefing (Part 3 and Part 5).

This is presentation data only. Rules, IDs and records stay in the core. Whether a substage is built is
probed from the core checkout, never asserted here:
  needs  - core files that must all exist for the substage to count as built ("module:assembly.treat", "kind:dispatch")
  v0     - an earlier, smaller piece already exists, so the substage reads "partial" until `needs` appears
  buckets- record counts shown for the substage: {label, kind, statuses[], draft}
  actions- only for built/partial substages; {label, route} where route is a site route that performs the core action
  gate   - the named human gate at this substage (briefing rule 4)
Mapping record statuses onto stages is the site's reading of the v0 status list, and is labelled as such in the UI.
"""
from typing import Any, Dict, List

from .core import CORE


def probe(spec: str) -> bool:
    what, _, name = spec.partition(":")
    if what == "module":
        return (CORE / "assembly" / (name.split(".", 1)[1] + ".py")).exists()
    if what == "kind":
        return (CORE / "kinds" / (name + ".json")).exists()
    return False


def _sub(key, title, summary, needs=None, v0=False, buckets=None, actions=None, gate=None, plan=None):
    return {"key": key, "title": title, "summary": summary, "needs": needs or [], "v0": v0,
            "buckets": buckets or [], "actions": actions or [], "gate": gate, "plan": plan}


def _b(label, kind, statuses=None, draft=None):
    return {"label": label, "kind": kind, "statuses": statuses or [], "draft": draft}


STAGES: List[Dict[str, Any]] = [
    {"key": "regional", "group": "Frame", "title": "Regional", "ref": "6.1",
     "summary": "Region and jurisdiction the work is about.",
     "substages": [_sub("region", "Region labels", "Today `region` is a free-text field on questions; no vocabulary yet.", v0=True, plan="Plan 1 (vocabulary)")]},
    {"key": "assembly", "group": "Frame", "title": "Assembly (library)", "ref": "6.2",
     "summary": "Profiles of what exists, plus the library of templates, joining rules, spin designs, timers and notification preferences.",
     "substages": [
         _sub("profiles", "Profiles", "Units, repos and datasets profiled as pointers (data and code do not live in the core).", v0=True,
              buckets=[_b("units", "unit"), _b("repos", "repo")], actions=[{"label": "Browse units", "route": "#/records?kind=unit"}, {"label": "Browse repos", "route": "#/records?kind=repo"}]),
         _sub("library", "Reference library", "Versioned templates, rules and prompts that Dispatch freezes at emit time.", needs=["module:assembly.library"], plan="Plan 1 Task 2")]},
    {"key": "services", "group": "Frame", "title": "Services", "ref": "6.3",
     "summary": "Internal services and external participation.",
     "substages": [_sub("profiles", "Service profiles", "Service records exist; external arrangements are not modelled yet.", v0=True,
                        buckets=[_b("services", "service")], actions=[{"label": "Capture service", "route": "#/new?kind=service"}, {"label": "Browse", "route": "#/records?kind=service"}])]},
    {"key": "goals", "group": "Frame", "title": "Goals", "ref": "6.4",
     "summary": "What companies and users want; converted into questions.",
     "substages": [
         _sub("profiles", "Goal profiles", "Goal records exist.", v0=True, buckets=[_b("goals", "goal")],
              actions=[{"label": "Capture goal", "route": "#/new?kind=goal"}, {"label": "Browse", "route": "#/records?kind=goal"}]),
         _sub("convert", "Goal to questions", "Convert a goal into precise questions.", needs=["module:assembly.goals"], plan="later")]},
    {"key": "questions", "group": "Questions", "title": "Questions", "ref": "6.5",
     "summary": "Historic or current, framed by one of six lenses; standing or time-limited.",
     "substages": [
         _sub("stamp", "Stamp (capture)", "The submitter stamps minimal metadata. Saving makes a draft; it never dispatches.", v0=True,
              buckets=[_b("questions", "question")], actions=[{"label": "Capture question", "route": "#/new?kind=question"}, {"label": "Browse", "route": "#/records?kind=question"}]),
         _sub("treat", "Treat", "Expand tags, find gaps, ask quick questions as decision cards.", needs=["module:assembly.treat"], plan="Plan 1"),
         _sub("vocabulary", "Vocabulary", "Controlled vocabulary; Dispatch drafts taxonomy proposals, only the owner approves.", needs=["module:assembly.vocabulary"], gate="vocabulary", plan="Plan 1"),
         _sub("lifecycle", "Lifecycle", "Active, paused, expired; time-limited questions.", needs=["module:assembly.lifecycle"], plan="Plan 2")]},
    {"key": "dispatch", "group": "Dispatch", "title": "Dispatch", "ref": "6.7",
     "summary": "The one executable core: resolve questions to pools, bundle by region and cadence, build context, emit, receive, assess, digest, hand on.",
     "substages": [
         _sub("resolve", "Resolve", "Labels and library rules to a set of intelligence pools; refuses untreated questions.", needs=["module:assembly.resolve"], plan="Plan 1"),
         _sub("bundle", "Bundle", "Group by region and cadence (splits on origin, sensitivity, trust, effort). Preview only.", needs=["module:assembly.bundle"], plan="Plan 1"),
         _sub("surround", "Surround", "Anticipated context frozen on the dispatch.", needs=["module:assembly.surround"], plan="Plan 2"),
         _sub("emit", "Emit", "Write the task document for machine-flows. v0 does this per question; per-bundle dispatch records come with the `dispatch` kind.",
              needs=["kind:dispatch"], v0=True, plan="Plan 2",
              buckets=[_b("drafts ready", "question", ["new"], draft=True), _b("dispatched", "question", ["dispatched"])],
              actions=[{"label": "Review drafts and dispatch", "route": "#/dispatch"}, {"label": "Capture question", "route": "#/new?kind=question"}]),
         _sub("receive", "Receive", "Register arrivals. v0 reads machine-flows run records and moves record status.", needs=["module:assembly.receive"], v0=True, plan="Plan 3",
              buckets=[_b("running", "question", ["running"]), _b("failed", "question", ["failed"])],
              actions=[{"label": "Check machine-flows runs", "route": "#/dispatch"}, {"label": "Failed", "route": "#/records?status=failed"}]),
         _sub("assess", "Assess", "Assessment scanners mark the bundle: quantity now, quality later.", needs=["module:assembly.assess"], plan="Plan 3"),
         _sub("digest", "Digest and approval", "Review point 1. v0 stand-in: the owner confirms a finished run.", needs=["module:assembly.digest"], v0=True, gate="digest", plan="Plan 3",
              buckets=[_b("awaiting you", "question", ["awaiting-confirmation"])],
              actions=[{"label": "Review results", "route": "#/records?status=awaiting-confirmation"}]),
         _sub("handon", "Hand on to Join", "An accepted digest goes to Join. v0 ends at answered.", needs=["module:assembly.join"], v0=True, plan="Plan 4",
              buckets=[_b("answered", "question", ["answered"]), _b("retired", "question", ["retired"])],
              actions=[{"label": "Answered", "route": "#/records?status=answered"}])]},
    {"key": "scan", "group": "Intake", "title": "Scan (automation)", "ref": "6.8",
     "summary": "Automated collection, executed by machine-flows.",
     "substages": [_sub("run", "Scan runs", "Execution belongs to machine-flows; Assembly says what is needed, never which tool.", needs=["module:assembly.scan"], plan="Plan 2-3")]},
    {"key": "file", "group": "Intake", "title": "File (manual, APIs)", "ref": "6.9",
     "summary": "Manual filing and API intake, including the Stores to API to File loop.",
     "substages": [
         _sub("manual", "Manual filing", "Questions with intake=file leave a checklist step for a person.", v0=True),
         _sub("api", "API intake", "Gap partners inject data by API and distill it into question bundles.", needs=["kind:party"], plan="Plan 7")]},
    {"key": "join", "group": "Join", "title": "Join (registries, digests)", "ref": "6.10",
     "summary": "Parse, give IDs, contribute to totals; two review points.",
     "substages": [
         _sub("contracts", "Join contracts", "Fields, rules and naming known in advance.", needs=["module:assembly.join"], plan="Plan 4"),
         _sub("mapping", "Mapping digest", "Field and value mapping presented for approval before Join.", needs=["module:assembly.mapping"], gate="mapping", plan="Plan 4"),
         _sub("review", "Join review", "Review point 2: aligned record writes are approved before Stores.", needs=["module:assembly.joinreview"], gate="join-review", plan="Plan 4")]},
    {"key": "stores", "group": "Hold", "title": "Stores", "ref": "6.12",
     "summary": "Databases and reviews; data stays outside the core.",
     "substages": [
         _sub("datasets", "Dataset profiles", "Pointers to stores.", v0=True, buckets=[_b("datasets", "dataset")],
              actions=[{"label": "Capture dataset", "route": "#/new?kind=dataset"}, {"label": "Browse", "route": "#/records?kind=dataset"}]),
         _sub("write", "Write path", "Approved change-sets written to main stores.", needs=["module:assembly.stores"], plan="Plan 5")]},
    {"key": "bays", "group": "Hold", "title": "Bays", "ref": "6.13",
     "summary": "Time-limited accumulation branches, checked then merged.",
     "substages": [
         _sub("profiles", "Bay profiles", "Bay records exist; lifecycle does not.", v0=True, buckets=[_b("bays", "bay")],
              actions=[{"label": "Capture bay", "route": "#/new?kind=bay"}, {"label": "Browse", "route": "#/records?kind=bay"}]),
         _sub("lifecycle", "Bay lifecycle", "Open, accumulate, check, merge, close.", needs=["module:assembly.bays"], plan="Plan 5 (NA-357)"),
         _sub("merge", "Bay merge", "Owner merges a checked bay into main.", needs=["module:assembly.baymerge"], gate="bay-merge", plan="Plan 5")]},
    {"key": "move", "group": "Run", "title": "Move (timers, checks)", "ref": "6.14",
     "summary": "Timers and checks that advance work on schedule.",
     "substages": [
         _sub("timers", "Timers", "`tick` creates due dispatches, run by a machine-flows scheduled job.", needs=["module:assembly.tick"], plan="Plan 5"),
         _sub("checks", "Checks", "Scheduled integrity and freshness checks.", needs=["module:assembly.checks"], plan="Plan 5")]},
    {"key": "notifications", "group": "Run", "title": "Notifications", "ref": "6.15",
     "summary": "Notices, decision cards, review packs.",
     "substages": [_sub("feed", "Event feed", "Events from machine-flows replace polling run folders.", needs=["module:assembly.events"], plan="Plan 6 (NA-358)")]},
    {"key": "line", "group": "Line", "title": "Line", "ref": "6.16",
     "summary": "The business line and its promises: View, Read, Make, Save, Acts.",
     "substages": [
         _sub("units", "Unit profiles", "Units carry their promises and stage.", v0=True, buckets=[_b("units", "unit")],
              actions=[{"label": "Browse units", "route": "#/records?kind=unit"}]),
         _sub("publish", "Publication", "Publication is a named human gate.", needs=["module:assembly.publish"], gate="publication", plan="Plan 8")]},
]

GATES = [
    {"key": "vocabulary", "title": "Vocabulary approval", "at": "questions.vocabulary", "summary": "Only the owner approves taxonomy proposals."},
    {"key": "digest", "title": "Digest approval", "at": "dispatch.digest", "summary": "Review point 1 before Join (v0 stand-in: owner confirms a finished run)."},
    {"key": "mapping", "title": "Mapping approval", "at": "join.mapping", "summary": "Field and value mapping approved before Join acts."},
    {"key": "join-review", "title": "Join review", "at": "join.review", "summary": "Review point 2 before writes reach Stores."},
    {"key": "bay-merge", "title": "Bay merge", "at": "bays.merge", "summary": "A checked bay is merged into main by the owner."},
    {"key": "publication", "title": "Publication", "at": "line.publish", "summary": "Nothing is published without the owner."},
]


def sub_state(sub: Dict[str, Any]) -> str:
    if sub["needs"] and all(probe(n) for n in sub["needs"]):
        return "built"
    return "partial" if sub["v0"] else "unbuilt"


def sub_reason(sub: Dict[str, Any], state: str) -> str:
    if state == "built":
        return ""
    missing = [n for n in sub["needs"] if not probe(n)]
    if state == "partial":
        return "Only the v0 piece exists. Full stage needs: %s (%s)." % (", ".join(missing), sub["plan"] or "planned")
    return "Not built in the core yet. Needs: %s (%s)." % (", ".join(missing) or "design", sub["plan"] or "planned")

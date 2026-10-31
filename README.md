# Assembly Site

Local website for Niagara Assembly's Assembly System, centred on **Dispatch**. Assembly System owns kinds, IDs,
records and workflow rules; this repo owns the localhost HTTP adapter and the browser UI. The core is imported, not copied.

```
bin/assembly-site [--port 8765] [--root DIR]     # http://127.0.0.1:8765
python3 -m unittest discover -s tests            # unit + HTTP tests (stdlib only)
```

Configuration (environment): `ASSEMBLY_SYSTEM` (core checkout, default `../assembly-system`), `ASSEMBLY_ROOT` (record
store, default `~/.local/share/assembly-site/root`, never inside this repo), `ASSEMBLY_SITE_DATA` (annotations), `ASSEMBLY_OUTBOX` (task documents for
machine-flows), `ASSEMBLY_RUNS` (machine-flows run records, read-only).

## What it does

- **Dispatch workbench**: a five-step strip (Capture, Bundle, Dispatch, Track, Review) with counts, a prioritised "Next up" list
  (finished runs, failures, ready bundles, runs to check), and four labelled lanes: Ready, Needs you, In flight, Failed.
- **Bundles**: questions grouped by the core's bundle key (region, cadence, intake, origin, sensitivity, trust, effort; cap 12),
  each key part labelled, each question marked ready / manual / in flight / needs you / failed with the reason, due or not due on the
  chosen day. Select ready questions, preview the exact task documents (permission and approval shown), tick to confirm, then write.
  v0 writes one task document per question; a per-bundle dispatch record comes with Plan 2. Needs `assembly/bundle.py` in the core.
- **Map** (home): every stage and substage of the flow from the Dispatch briefing (Regional through Line), with the six named
  human gates. Each substage reads *built*, *partial (v0)* or *not built*. State is probed from the core checkout (a substage flips
  to built when the core file it needs appears, e.g. `assembly/resolve.py`), so the site cannot claim work the core cannot do.
  Unbuilt substages offer no actions. Counts are the site's reading of v0 record statuses.
- **Stage pages** (`#/stage/KEY`): per-substage buckets that link to filtered records, the actions the core supports today, and notes.
- **Notes**: comments (threaded, author-retractable), stars (per actor) and flags (with reason) on any record and any stage or substage.
  They live in the site's own append-only store (`ASSEMBLY_SITE_DATA`, default next to the record store, never in git), never edit a
  record, and never reach task documents. A retract hides text from views but keeps it in the file. The "You" box sets a label, not a login.
- **Activity**: recent comments, stars and flags, and everything starred.

- **Dispatch** (home): pipeline counts, drafts ready to dispatch, items that need you (finished runs, failures), in-flight work, handback check.
- **Capture**: forms generated from the core schema for every kind. Saving creates a *draft* with a minted ID. It never dispatches.
- **Dispatch a record**: shows the exact task document, requires an explicit acknowledgement, then writes it to the outbox. Nothing is run here;
  "dispatched" only means a task document exists until a machine-flows run record says otherwise.
- **Records**: filter by kind/status; detail with fields, history, creation steps; edit metadata (preview diff, then save, bumping `rev`), retire, confirm a finished run.

## Also in the site

- **Inbox**: finished runs, failures, partial creations, dispatches idle 3+ days, flagged items and `@mentions` of you (badge in the nav).
  Result before confirming: a record awaiting confirmation shows the latest machine-flows run's files, read-only.
- **Health**: the core's lint results and checksummed backups (records, creations, ID counters, notes) with verify.
- **Capture**: grouped fields, link pickers, duplicate warnings (advisory), and atomic bulk capture (all lines valid or nothing is minted).
- **Dispatch safety**: diff against the earlier task document on re-dispatch; hold a question back (a site-level guard, record unchanged);
  a failed outbox write is reported as an error and the draft can be resumed.
- **Bundles**: week schedule, per-bundle history, "Fix" links for blocked questions, opt-in update check on the workbench.
- **Records**: search, sort, paging, CSV export (formula-safe), record timeline. **Notes**: resolve threads, `@name` mentions, unread.
- **Keyboard**: `g` then `m d b n r i a h` to go, `/` to search, `?` for help. Phone layout turns tables into cards.

Browser test: `tests/e2e` runs when Node and Playwright are installed (skipped otherwise).

- **Operations**: `GET /healthz`; `bin/assembly-site --log` prints one line per request (method, path without query, status, ms); the Health page shows
  versions, resolved paths and why each stage reads built or not. Changes are refused when made from a stale page (HTTP 409, with a reload button).

**What is not done: see [docs/UNFINISHED.md](docs/UNFINISHED.md).**

## Safety

Binds to 127.0.0.1 only; rejects non-local `Host` headers; writes need a JSON content type and `X-Assembly-Site` header; strict CSP and
no `innerHTML` (record text is inserted as text). Requires the core's `hold_handoffs` / `release_held` (assembly-system, same branch name).

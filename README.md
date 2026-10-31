# Assembly Site

Local website for Niagara Assembly's Assembly System, centred on **Dispatch**. Assembly System owns kinds, IDs,
records and workflow rules; this repo owns the localhost HTTP adapter and the browser UI. The core is imported, not copied.

```
bin/assembly-site [--port 8765] [--root DIR]     # http://127.0.0.1:8765
python3 -m unittest discover -s tests            # unit + HTTP tests (stdlib only)
```

Configuration (environment): `ASSEMBLY_SYSTEM` (core checkout, default `../assembly-system`), `ASSEMBLY_ROOT` (record
store, default `~/.local/share/assembly-site/root`, never inside this repo), `ASSEMBLY_OUTBOX` (task documents for
machine-flows), `ASSEMBLY_RUNS` (machine-flows run records, read-only).

## What it does

- **Dispatch** (home): pipeline counts, drafts ready to dispatch, items that need you (finished runs, failures), in-flight work, handback check.
- **Capture**: forms generated from the core schema for every kind. Saving creates a *draft* with a minted ID. It never dispatches.
- **Dispatch a record**: shows the exact task document, requires an explicit acknowledgement, then writes it to the outbox. Nothing is run here;
  "dispatched" only means a task document exists until a machine-flows run record says otherwise.
- **Records**: filter by kind/status; detail with fields, history, creation steps; edit metadata (preview diff, then save, bumping `rev`), retire, confirm a finished run.

## Safety

Binds to 127.0.0.1 only; rejects non-local `Host` headers; writes need a JSON content type and `X-Assembly-Site` header; strict CSP and
no `innerHTML` (record text is inserted as text). Requires the core's `hold_handoffs` / `release_held` (assembly-system, same branch name).

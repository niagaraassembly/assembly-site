# Assembly Site

Local interface for Niagara Assembly's Assembly System. The website lives here;
Assembly System owns its kinds, IDs, records and workflow rules.

Question data belongs in a separate local record store, never in this repository.

Repository separation is tracked in [NA-365](https://linear.app/niagaraassembly/issue/NA-365).

## Run locally

Python 3.9+ and the standard library are the only runtime requirements. Browser
assets are buildless; no npm install or external fonts are needed.

```sh
ASSEMBLY_SYSTEM_PATH=/path/to/assembly-system bin/assembly-site \
  --data ~/na/local-data/assembly --port 8031
```

Open <http://127.0.0.1:8031>. The core checkout must include the draft-capture work
from [NA-363](https://linear.app/niagaraassembly/issue/NA-363); older main revisions
are rejected with an explicit error. The core package and kinds are imported,
never copied into this repository. A fresh installation needs that dependency
checked out before running this site.

The initial compatible revision is `49354c9`, proposed in
[assembly-system PR #4](https://github.com/niagaraassembly/assembly-system/pull/4).

Paths can be supplied once in `~/.config/assembly-site/local.json`:

```json
{
  "core_path": "/absolute/path/to/assembly-system",
  "record_root": "/absolute/path/to/local-data/assembly"
}
```

Then run `bin/assembly-site`. `--core` and `--data` override environment variables
`ASSEMBLY_SYSTEM_PATH` and `ASSEMBLY_ROOT`, which override the configuration file.
The default record root is `~/na/local-data/assembly`, outside all Git checkouts.
The local configuration is not a credential store and is never committed.

The foreground server binds only to loopback. Stop it with Ctrl+C. It does not
install a service, execute scans, connect to an AI provider or publish a hosted site.

## Data and metadata

Original submissions use canonical Assembly Q IDs and are saved as capture-only
drafts. Large pasted text, Unicode and line breaks remain intact. The request
limit is 8 MiB; rejected saves retain the current form. Save before reloading or
closing the browser; an unsaved modal draft only lasts for that page session.

The table has three-line fading previews, full-text modals, expandable metadata,
and source/derived/supersession links. Add linked question preserves the original
submission; it does not automatically replace it. Retired drafts are read-only.

Question profiles, creation journals, ID counters, backups and outbox files live
under the selected record root. Metadata edits go through Assembly's change
operation, retain history, back up the prior profile, and reject stale browser
revisions. Use one writer at a time; those revision checks do not coordinate an
independent CLI process or a second server.

The core question schema's `capture.metadata` list is the edit policy. Field types,
allowed values and descriptions come from the same core schema. Add a field there
and opt it into the policy; the website does not maintain a parallel field list.
Controls support text, choices, dates, integers, booleans, newline-separated lists
and Assembly link IDs. Core validation remains authoritative. Original/provenance
and execution fields cannot be exposed as ordinary metadata by changing this list.
Restart the server after a core schema edit so its loaded kinds stay consistent.

## Migration and rollback

Stop all writers first. Preview a migration of the complete record store:

```sh
python3 -m assembly_site.migrate /old/record/root /new/record/root \
  --backup /new/rollback-snapshot
```

Repeat with `--apply` to copy byte-for-byte and verify SHA-256 hashes. The tool
refuses existing targets, overlapping roots, ID locks and symlinks. It retains
the source and a separate rollback snapshot with a manifest, then publishes the
verified target. It changes no IDs, fields or record history. Configuration must
be pointed at the new root separately after successful verification.

For rollback, stop the site, preserve any newer records from the active store,
and point it at a verified snapshot. Do not overwrite newer work with an old
snapshot. Existing Assembly CLI checkouts can use `ASSEMBLY_ROOT`, or the core's
ignored `.assembly-record-root` redirect, to share the same active store.

## Question processing

The proposed contextual top bar and one-button expansion/decomposition workflow
are specified in [docs/question-processing.md](docs/question-processing.md).
Processing needs real Assembly batch/receipt/proposal operations and an AI service
before it can execute; this migration does not simulate that capability.

## Verify

```sh
ASSEMBLY_SYSTEM_PATH=/path/to/assembly-system python3 -m unittest discover -s tests
node --check web/app.js
```

The HTTP tests bind ephemeral loopback ports and use temporary records. Migration
tests compare exact bytes and verify refusal of changed or unsafe sources. Browser
QA uses temporary record roots, never the user's saved questions.

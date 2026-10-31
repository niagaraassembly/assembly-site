# Unfinished work

A plain list of what is not done, why, and what would finish it. Kept in the site repo but covers the core
(`assembly-system`) too, because the site's stage map only shows what the core can do.
Last updated with the "everything" run (site v0.3.0). "Owner" means it needs a decision or action from the owner.

## A. Carried over from before this run

| # | Item | Why it is open | Next step | Owner |
|---|------|----------------|-----------|-------|
| A1 | Real sign-in / identity | The "You" box is only a label. A login on a single-user localhost site would be theatre. | Decide whether more than one person will use the site; if so, add per-user identity and make notes and holds attributable. | yes |
| A2 | Map drawn as a flow with arrows | The owner said to keep cards. | None unless the owner changes their mind. | no |
| A3 | Status-to-stage mapping on the map | It is the site's own reading of the v0 record statuses (for example a finished run counts at "Digest and approval"). | Owner confirms or corrects the mapping in `assembly_site/stages.py` (buckets). | yes |
| A4 | Core: `treat`, vocabulary, library, `resolve`, question lifecycle (Plan 1 in the briefing) | Specified in `docs/superpowers/plans/2026-10-27-dispatch-briefing-and-plan-1.md` but not built. Only `bundle` and `period` exist, and `bundle` is preview-only. | Build Plan 1 tasks 1 to 6 in `assembly-system`; the map flips each substage to "built" by itself when its file appears. | owner go-ahead |
| A5 | Core: per-bundle dispatch record, surround, receive, assess, digest, join, stores, bay lifecycle, timers, notifications, line (Plans 2 to 8) | Each needs its own plan and the owner's go-ahead (briefing Part 10). | Plan 2 first (the `dispatch` kind). | owner go-ahead |
| A6 | Bundles dispatch one task document per question | A bundle-level dispatch record is Plan 2. | Plan 2. | no |
| A7 | `effort` is "unstated" in every bundle key | v0 questions have no `effort` field and it must not be invented. | Add the field in Plan 1 task 1, after the owner approves the vocabulary. | yes |
| A8 | machine-flows handoff v1 contract (NA-330, NA-353) | Not agreed with machine-flows. | Agree the contract keys, then replace the `as:<ID>` tags. | yes |
| A9 | The architecture graphic is not in the repo | Stage placement and the red-event mapping cannot be checked. | Owner re-attaches the image. | yes |
| A10 | Linear issues for Plans 2 to 8 and the NA-361 follow-ups (Plan 1 task 8, step 5) | I have not created them. | Create them in project "Assembly System" when the owner wants. | yes |
| A11 | Pull requests, merging, and any hosted publication | Not requested; the site rules forbid merging or hosting without the owner. | Owner asks for PRs when ready. | yes |

## B. Left open by this run

### Behaviour that differs from what a reader might assume

| # | Item | Detail | Next step |
|---|------|--------|-----------|
| B1 | **A hold is a site-only guard** | The site refuses to dispatch a held draft, but `bin/assembly dispatch` and the core do not know about holds. | Move holds into the core (a record field or event) if they must bind every caller. |
| B2 | History keeps no snapshots | The core's history stores `field: old -> new` text, cut at 80 characters. The field-level history table shows that text, so long values are truncated, and there is no "view the record as of revision N". | Have the core store full old and new values (or revision snapshots). |
| B3 | Timestamps have one-second resolution | Events in the same second have no true order across records (timeline, bundle history). Mentions use event order, so they are not affected. | Higher-resolution timestamps in the core. |
| B4 | Comments cannot be edited | Retract and repost is the only way. A retract hides the text in views but keeps it in the file. | Add append-only edit revisions if wanted. |
| B5 | `@mentions` cannot contain spaces, and notices stay inside the site | There is no email or push. | Notifications belong to Plan 6. |
| B6 | Notes file is never compacted or rotated | It only grows; the cache is rebuilt when it changes. | Add compaction if it becomes large. |
| B7 | Record cache has no eviction | Fine at thousands of records (65 ms warm listing at 1,500), unbounded memory beyond that. | Add an LRU bound if the store grows. |

### Verified less than it sounds

| # | Item | Detail | Next step |
|---|------|--------|-----------|
| B8 | CI has never run | The workflows are committed, but GitHub has not run them. The site workflow needs a read-only token in the secret `ASSEMBLY_SYSTEM_TOKEN` to check out the private core repo. | Add the secret and watch the first run. |
| B9 | Python 3.9 is untested locally | CI lists 3.9 and 3.12; only 3.11 and 3.13 were run here. I scanned for newer syntax and found none. | Let CI confirm. |
| B10 | machine-flows run layout is inferred | `run_result` reads every text file in the run folder, based on `run.md` and `input.md`. It was only tested against fixtures I built. | Check against a real run folder. |
| B11 | The outbox is not checked against a real `mach run --inbox` | The core's conformance test uses the real validator only when `mach` is installed (5 core tests skip here). | Run the suite where `mach` is installed. |
| B12 | The legend is hand-written text | It can drift from the core's meaning. | Generate it from the core's schema where possible. |
| B13 | "Why built" only checks that files exist | The probe does not run them. | Add a smoke call per module when modules exist. |
| B14 | Accessibility is partly checked | Colour contrast for every text and background pair is tested (light and dark), and focus, labels, `aria-sort` and reduced motion were added. There has been no screen-reader pass and no automated audit such as axe. | Run axe in the browser test and do a manual pass. |
| B15 | Browser test is Chromium only and phone layout is checked at 390 px | | Add Firefox and WebKit; try real devices. |

### Features that exist but are narrower than they could be

| # | Item | Detail | Next step |
|---|------|--------|-----------|
| B16 | Browser test does not cover resume | Resume of a partial creation is covered by service tests only. | Add a browser test that makes a partial creation. |
| B17 | Unsaved-changes guard covers capture and edit forms only | Comment boxes, bulk reasons and the retire reason are not guarded. | Extend `watchDirty` to those inputs. |
| B18 | Bulk actions are limited | Star, unstar, hold, release, retire and dispatch only (50 at a time). Bulk dispatch previews file names, not the full documents. No bulk field edit or supersede. | Add if needed; full documents are available through the bundle flow. |
| B19 | Duplicate warning is simple | Token overlap with a fixed 0.6 threshold, within one kind. | Tune or replace with a better measure. |
| B20 | Inbox thresholds are fixed | "Aging" is 3 days. Auto-check only previews handback and runs only on the workbench. | Make them settings. |

### Security notes (by design, but worth knowing)

- The site binds to 127.0.0.1, rejects non-local `Host` headers, and requires a JSON content type plus an `X-Assembly-Site` header on writes.
  That header is not secret, so any other program running as a user on the same machine can use the API. There is no rate limiting.
- Anything typed into a comment or record is inserted as text, never as HTML, and is checked by a test (no `innerHTML`, no inline scripts, strict content security policy).

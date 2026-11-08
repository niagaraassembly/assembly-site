# One-button question preparation

Design proposal for NA-365. This is not an implemented AI service.

The default action is **Process questions**, using the saved **Prepare for research**
preset and **Automatic** treatment. A user can select rows or use all eligible
questions in the current view. The system explains what it will include and skip.
No user needs to decide in advance whether a question needs expansion or splitting.

## What the button means

1. Freeze the eligible input IDs, relevant metadata, original text hashes, chosen
   preset, schema version and exact support-document versions into a batch snapshot.
2. Retrieve maintained Assembly framing, question families, sector/region context
   and relevant internal support blocks. Record which sources were actually used.
3. For each submission, identify the underlying intent and independent inquiries.
   Choose expansion, decomposition, both, retain-as-is, or needs-clarification.
4. Express reusable question cores separately from regional/sectoral qualifiers.
   Expand nested aspects only when they follow from the stated intent or framing.
   A focused question can remain one question; a long block can yield several.
5. Match proposed inquiries to existing ones. Suggest reuse or relationships before
   producing duplicates. Do not silently equate superficially similar questions.
6. Return validated, reviewable proposals with source links, supporting references,
   rationale, uncertainties and proposed metadata. Keep the original submission intact.
7. Review accepts or edits proposals through Assembly's front door. Generated questions
   remain drafts with derived provenance. Explicit replacement is a separate decision.

Processing prepares inquiries; it does not perform a research scan, answer a question,
join findings into company data, or dispatch work. Those are later Assembly actions.

## Inputs and outputs to formalize in Assembly System

The processing contract needs versioned definitions for:

- **Intent preservation:** what can be inferred, what must remain unknown, and when to
  ask for clarification rather than inventing purpose or scope.
- **Treatment:** rules for expansion, decomposition, hierarchy, and reuse. A verbose
  submission can require both expansion of implicit aspects and separation of concerns.
- **Framing:** approved instructions, universal question families, metadata vocabulary,
  regional/sector context, support-document retrieval, and their precedence.
- **Output:** structured inquiries with optional parent/child relationships, original
  source IDs/spans, proposed metadata, rationale and unresolved points. Multiple source
  submissions may support one reusable question; do not lose that many-to-many provenance.
- **Review:** proposed → accepted/edited/rejected. Review does not erase the proposal,
  original, processing receipt or support-source versions.
- **Execution:** provider/model configuration, schema validation, bounded batch sizes,
  retries, idempotency and partial-batch results. Provider choice is a service setting,
  not a question the user answers on every click.

Treat submitted text and retrieved content as source material, never as permission to
change files, alter policy or dispatch work. AI output proposes fields; Assembly validates
and applies accepted changes. Trust and sensitivity are never silently elevated.

## Skipping questions already processed

The same identity rule will apply to uploaded/reference files: source ID + content
hash/version, rather than filename alone. A changed file should not be silently skipped.

Do not add a single permanent `processed=true` flag. A current completion is defined by
an input fingerprint: original text + metadata relevant to framing + processing preset
version + actual support-source versions + output-schema version. Retain provider/model
identity and settings on the run for reproducibility; decide explicitly whether a provider
change should invalidate prior work.

Use per-input receipts with input hash, source IDs, state, treatment, outputs and run ID.
States are unprocessed, running, completed-awaiting-review, accepted, failed and stale.
Successful current receipts are skipped by default, including those awaiting review.
Failures remain retryable; changed framing inputs become stale and eligible again.
A note or display-title edit need not invalidate processing. A deliberate Reprocess action
creates another receipt without deleting the earlier one.

The processing registry and output proposals belong to Assembly System's persistent
store, not browser storage or the website Git repo. Add an Assembly operation before
making the button execute; the site should not become a second workflow authority.

## Contextual top bar

Keep browsing scope, selection and action readiness visible together:

| Control/state | Behavior |
| --- | --- |
| Search, region, lens | Define the current view. |
| Checkboxes / Select current view | Define explicit inputs; display selected and eligible counts. |
| Processing state | Default to Not currently processed; allow All, Needs review, Failed, Stale. |
| Preset | Prepare for research by default; advanced changes are optional. |
| Eligible unprocessed/stale rows | Show Process N questions; disclose skipped current/running/retired rows. |
| Current proposals awaiting review | Offer Review N proposals; avoid rerunning them by accident. |
| Running rows | Show progress; suppress duplicate submission of the same input fingerprint. |
| Retired rows / no eligible rows | Disable processing and explain the reason. |
| Mixed selection | Summarize each group; act on the eligible subset with a frozen snapshot. |

The minimum user work is selection plus one click; if the default view is unprocessed
questions, even selection can be implicit and explicit in the button label. Ask a user
only about unresolved intent that materially changes the inquiry. Save those clarifications
as reusable framing when appropriate.

Next concrete implementation: define the Assembly batch/receipt/proposal operations,
approve a first processing preset and output schema, connect a real AI service, then
build the selection/action bar against that contract. Do not ship a button that merely
marks questions processed or fabricates derived questions without that service.

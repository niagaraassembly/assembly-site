# Assembly Site

- This repository owns the localhost HTTP adapter and website. Assembly business
  rules, IDs, schemas and record operations belong to `assembly-system`.
- Import the core; do not copy its package, kinds or runtime records here.
- Never commit submitted questions, local configuration, credentials or run data.
- Preserve original text and provenance. Changes to records must use Assembly's
  creation/change actions, never direct JSON edits.
- Captured drafts never dispatch work. Question processing and scan execution
  are separate actions. Do not represent an absent AI service as completed work.
- Metadata controls come from the core schema with an explicit edit policy.
- Python 3.9+, standard library only at runtime. Browser assets are buildless.
- Write meaningful failing tests first, then implement; verify with unit/HTTP
  tests and browser checks for changed interactions.
- Work in a feature worktree under `~/work`; primary checkout stays on `main`.
- Back up records and verify checksums before changing the active data root.
- Do not merge pull requests or publish a hosted site without owner direction.

# Rectify summary — paper-metadata-m1

Verdict routing of the 9 adversary findings (critique/adversary.md):

## Fixed (rect commit)

- MEDIUM `total=` denominator skew — summary line now emits `unique=` (deduped,
  version-stripped denominator the AC1 gate reads); comment documents
  hydrated+skipped+missing == unique; versioned-dup test extended.
- MEDIUM CLAUDE.md §7 stale — get_paper bullet amended: store + backfill CLI
  exist (shipped m1), handler wiring lands in m2.
- LOW email-before-slug ordering — `validate_slug` now first per
  _notebook_common convention.
- LOW non-retryable give-up untested — new test: HTTP 400 → exactly 1 attempt,
  exit 1, `http_400` reason on stderr.
- LOW synthesis test-count arithmetic — corrected to 9/20/14 = 43.

## Invalidated

- CRITICAL unsigned commits — user explicitly authorized `--no-gpg-sign` for
  this session (GPG pinentry cannot be answered from a background session;
  authorization recorded in session transcript 2026-07-05).

## Acknowledged / deferred

- HIGH AC1 live run never executed — **RESOLVED during rectify**: live run
  completed post-fix: `hydrated=127 skipped=0 missing=0 malformed=0
  unique=127 total=127` — 100% ≥ 95% gate, all 14 old-style IDs hydrated.
- HIGH diff size (1943 LOC) — acknowledged; driven by 3 comprehensive test
  files; no split action taken.
- MEDIUM t-ingest-hook descope untracked — deferred to the external-write
  boundary: filing a GitHub issue requires user authorization; listed in the
  completion report. Roadmap item stays `planned` (one-writer rule respected).

## Gates after rect

44/44 tests green across the three new test files; `ruff check .` clean;
schema hash pins untouched by rect diff (CLAUDE.md + tests only + 2 code files
re-verified by test run).

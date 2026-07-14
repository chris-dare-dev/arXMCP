# Rectify summary — license-serving-removal-m1

Critique found **0 CRITICAL / 0 HIGH / 0 MEDIUM / 2 LOW**. The two LOW findings
are doc-staleness only (no code/test defect). Both FIXED (cheap, and L1 is a
binding doc) rather than deferred, in the `rect` commit:

- **L1 FIXED** — `.claude/docs/trust-language-policy.md:212`: struck
  `truncated_for_license` from the get_chunk census row with an inline
  "removed in license-serving-removal-m1" note. Left the 2026-07-12 snapshot
  date as-is (it already predates m5's source-truth fields; a full re-census is
  data-plane-governance's job, out of this milestone's scope).
- **L2 FIXED** — appended "removed in license-serving-removal-m1" notes at
  `.claude/notes/05-storage-and-indexing.md:70`,
  `.claude/docs/security-pdf-sandbox.md:350-351` and `:467`.

Below-threshold (not actioned): the `tests/test_handlers_chunk.py` fixture names
`_OA_ID` / `_NONOA_ID` are now vestigial (no OA/non-OA distinction) — purely
cosmetic, left as-is to bound churn.

No CRITICAL/HIGH open. `ruff check .` clean. Full suite green EXCEPT the 2
PRE-EXISTING, orthogonal `test_textbook_chunker` golden-fixture failures
(stash-verified on the base; flagged for a separate fix — not part of this
milestone).

Rect commit changes docs only (no production code), so the "rect must touch a
test" rule (pipeline §4b) does not apply.

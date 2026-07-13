# Rectify summary — source-truth-m1

**Rect commit:** `823c43c` (GPG-signed; `Reviewed-by:` milestone-adversary-critic +
milestone-arxmcp-critic; `Co-Authored-By: Claude Opus 4.8`). 5 files (3 production + 2 test),
+108/-9. **Critique:** C0 H2 M2 L3. **Invalidation rate:** 1/7 = 14% (< 40%). **Gate:** OK.

## Fixed (4)

| id | sev | fix |
|----|-----|-----|
| H2 | HIGH | Clamp the 503 `Retry-After` wait to `POLITENESS_SLEEP_SECONDS` — a server-sent `Retry-After: 0` can no longer busy-loop arXiv. `tools/oai_license.py`. Test: `test_retry_after_zero_is_floored`. |
| M1 | MEDIUM | A `papers.txt` member with no `parsed/<id>/index.html` is now a per-id **miss** (row withheld, re-run retries) — no silent NULL parse checksum. `tools/notebook_documents_backfill.py`. Test: `test_missing_index_html_is_a_per_id_miss_not_a_silent_null`. |
| M2 | MEDIUM | Coverage-report docstring no longer asserts `not-allowlisted-open` papers "truncate at m4" (they serve full-body today under the `arxiv-license` allowlist token). `tools/documents_coverage_report.py`. |
| L3 | LOW | Added the actual-read byte-cap test (Threat 7). Test: `test_oversized_read_body_refused`. (Bundled — trivially adjacent to H2's file.) |

## Invalidated (1)

| id | sev | reason |
|----|-----|--------|
| H1 | HIGH | 2986-LOC diff-size auto-flag. Concern already handled: `allow_large_diff` was owner-approved (one coherent registry system) and 60 behavior-asserting tests mitigate; the residual untested edges it named were fixed as H2/M1. Not a code defect. |

## Deferred (2, LOW)

| id | reason |
|----|--------|
| L1 | Redirect-pin is a prefix-match, not exact-origin — still binds egress to the trusted arXiv host; exact-origin tightening deferred (non-trivial ripple, negligible risk). |
| L2 | The configurable `endpoint` knob is ignored by `_fetch_record` (dead) — harmless (production uses the default; tests bypass `_fetch_record` via the fetch seam); dropping/threading it deferred. |

## Regression tests

- `tests/test_oai_license.py` — `test_retry_after_zero_is_floored` (H2), `test_oversized_read_body_refused` (L3).
- `tests/test_notebook_documents_backfill.py` — `test_missing_index_html_is_a_per_id_miss_not_a_silent_null` (M1).
- Gate: all 4 m1 suites (60 tests) + the tools/list schema-hash pin green; ruff clean.

## Go-live step (NOT yet run — offered to the owner)

The milestone's CLIs are built, critiqued, rectified, and tested (incl. a 6-paper live OAI-PMH
smoke). The **full 194-paper backfill** of both notebooks (populating the live `documents.db`
registries + emitting the per-license coverage report + the >20% escalation the spike-1 flag
anticipated) is a ~10-minute live-arXiv operator run — offered separately, not auto-run.

## External write

- `git push origin main` — required (the m1 code commits + rect). Owner-authorized per-event;
  surfaced at the boundary. The backfill's OAI-PMH GETs are reads, not external writes.

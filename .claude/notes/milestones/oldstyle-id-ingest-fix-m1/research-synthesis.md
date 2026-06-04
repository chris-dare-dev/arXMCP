# Research Synthesis — oldstyle-id-ingest-fix-m1

**Mode:** single (one Sonnet researcher; no peer to reconcile)
**Source brief:** [research-brief-1.md](research-brief-1.md)
**Generated:** 2026-06-04 (orchestrator merge, main session)

Single-mode run: the synthesis is the brief verbatim on the load-bearing
points plus the orchestrator's scoping decision. No divergence to reconcile.

## Confirmed root causes (quoted from brief)

**Fix 1 — `ingest/ar5iv_fetch.py::try_cache()`.** Old-style ids embed a
literal `/`, so `cache_path = cache_dir / f"{paper_id}.html"` resolves to
`cache_dir/math/0212237.html`; `cache_path.parent` is the `math/` subdir,
distinct from `cache_dir`. Pre-fix `cache_dir.mkdir(...)` created only the
base, so the subsequent `cache_path.write_text(...)` raised
`FileNotFoundError` on a fresh tree. Fix: `cache_path.parent.mkdir(...)` —
correct for both styles (`parent == cache_dir` for new-style). The sibling
`parsed_paper_dir.mkdir(...)` was already correct. `is_valid_arxiv_paper_id`
(from `ingest/identifiers.py`) **accepts** old-style ids, so they reach the
path-construction code.

**Fix 2 — `tools/notebook_fetch.py::run()`.** `fetch_raw_tex_if_missing →
fetch_eprint → validate_paper_id` (in `tools/arxiv_fetch.py`, `PAPER_ID_RE =
^[0-9]{4}\.[0-9]{4,5}$`, new-style only) raises `ValueError` on old-style ids
**by design**. `fetch_raw_tex_if_missing`'s docstring does NOT list
`ValueError` in its exception envelope, so it escaped and aborted the whole
batch. Fix wraps only that call in `try/except ValueError → recovered =
False`, degrading to `raw_tex_missing`, which the module docstring defines as
covering "all non-OK raw-tex outcomes." Semantically correct; no new
`raw_tex_skipped` bucket needed. This milestone deliberately does NOT change
`validate_paper_id` (left new-style-only with documented rationale; identical
to the E09_S02 F2 decision).

## Implementation plan (adopted from brief recommendation)

1. **Extend `tests/test_ar5iv_fetch.py`** (existing conventions: `tmp_path`,
   `unittest.mock.patch` on `urllib.request.urlopen`, inline `_FakeResponse`,
   class-based grouping, offline):
   - `test_old_style_id_creates_subject_subdir` — `try_cache("math/0212237", ...)`
     with a fake `<math>`-bearing body; assert `cache_dir/math/0212237.html`
     and the parsed `index.html` under the `math/` subdir both exist. Direct
     regression for Fix 1; fails on pre-fix code with `FileNotFoundError`.
   - `test_old_style_id_local_cache_hit` — pre-populate both paths under the
     subject subdir; assert `urlopen` not called and `reason == "ok_local_cache"`.
2. **Create `tests/test_notebook_fetch.py`** (`TestNotebookFetchRun`):
   - `test_old_style_id_does_not_abort_run` — notebook dir in `tmp_path`,
     `papers.txt` with `2401.00001` + `math/0212237`. Mock
     `ingest.ar5iv_fetch.try_cache` (hit for both), mock
     `tools._notebook_common.fetch_raw_tex_if_missing` (True for new-style,
     raise `ValueError` for old-style), mock `time.sleep` and
     `resolve_contact_email` to no-ops. Assert `run()` returns `0` and the
     summary reports `raw_tex_recovered=1 raw_tex_missing=1`. Direct
     regression for Fix 2; fails on pre-fix code with an unhandled traceback.

The exact module attribute names / mock targets (`resolve_contact_email`,
`try_cache` signature, `Ar5ivResult` shape, summary string) must be verified
against the live source during implementation rather than trusted from the
brief — implementer reads the files first.

## Constraints carried forward

- Windows-safe: old-style ids use `/` (subdir), not `:`; does not add to the
  29 pre-existing Windows colons-in-filenames failures (confirmed live).
- No MCP tool-schema change → no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin.
- No new Markdown outside `.claude/`.
- `KMP_DUPLICATE_LIB_OK` autouse in `tests/conftest.py` — leave alone.
- Three-commit pattern: `feat(ingest,tools)` + optional `rect(...)` +
  `chore(notes)`. GPG-signed, HEREDOC, co-author trailer.

## Orchestrator synthesis note

Scoped to `--single` research mode: 2 files / ~15 LOC of production change
already in the working tree + 3 regression tests. No architecture, no
specialist domain, no external writes — the parallel-pair researcher would
have been waste. No divergence to resolve (one brief). Phase 2 path will be
**inline** (well under the <500 LOC / <5 files / no-novel-architecture bar).

## Open questions

None. The brief's single "question" (mock at the helper boundary vs the
deeper `fetch_eprint`) is self-resolved: mock
`fetch_raw_tex_if_missing` directly — the `run()` contract under test is
"a `ValueError` from that call does not abort the batch," and the
`fetch_eprint`/`validate_paper_id` chain is already covered by E09_S02 tests.

## External writes the implementation will require

None — purely local. (`git push` remains a separate per-event user
authorization at the Phase 4 boundary if the user later asks to push.)

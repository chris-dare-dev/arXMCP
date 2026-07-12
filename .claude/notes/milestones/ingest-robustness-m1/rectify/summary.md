# Rectify summary — ingest-robustness-m1

Phase-3 critique: **C1 H2 M5 L4** (12 findings across 3 critics: adversary,
arxmcp, infra-safety). Rect commit: `92ab095`.

## Re-verification (CRITICAL + HIGH, all CONFIRMED against live code)
- **C1** (make init broken): reproduced with `gmake -n init` →
  `*** insufficient number of arguments (1) to function 'if'. Stop.` on every
  var combo. Real regression.
- **H1** (diff-size): `git diff` is ~953 insertions — the finding is factual.
- **H2** (MinerU timeout): confirmed `run_mineru_sandboxed` re-raises
  `subprocess.TimeoutExpired` (ingest/textbook_parser.py:492), which the CLI's
  `except (RuntimeError, OSError)` did not catch. Real batch-abort bug.

Invalidation rate: 0% (0/3). No stale findings.

## Fixed (8) — each CRITICAL/HIGH with a regression guard
| id | fix | guard |
|---|---|---|
| C1 | reworded Makefile recipe comment to drop the literal `$(...)` | `test_make_init_recipe_expands` (`make -n init` dry-run) |
| H2 | added `subprocess.TimeoutExpired` to the CLI's caught tuple | `test_timeout_is_clean_per_paper_failure` |
| H1 | acknowledged; diff partitioned into 6 per-AC commits, no code change for a committed diff | per-AC commit partitioning (present) |
| M1 | — | `test_mineru_env_vars_rejected` (pins the 2 new server carve-out hints) |
| M2/L1 | single `ingest.chunker.STRUCTURE_SIGNAL_CLASSES` consumed by both AC4 sites | `test_chapter_render_is_structured`, `test_ac4_signal_set_is_single_source` |
| M4 | — | `test_fallback_chunk_ids_are_deterministic` |
| M5 | — | `test_make_init_recipe_expands` (also the C1 guard) |

## Deferred (4)
- **M3** (fallback drops standalone top-level display-math outside prose):
  documented limitation in `_extract_body_fallback_chunks` — the target
  old-format renders (hep-th/0002037) carry their math inline in `ltx_para`,
  which IS captured; free-standing display equations are a rarer shape left to a
  follow-up.
- **L2** (broad `except Exception` in the settings tier): deliberate mechanism
  to keep `ingest` decoupled from `server`; already covered by
  `test_operator_settings_read_error_degrades`.
- **L3** (past-tense commit subject `a7f6972`): the repo discourages
  amend/rebase on landed history; adopt imperative mood going forward.
- **L4** (private `_flat_paper_id` import in the CLI): low-risk internal
  coupling; promote to a public symbol in a follow-up if desired.

## Regression tests added
- tests/test_server_startup.py::test_mineru_env_vars_rejected
- tests/test_notebook_pdf_parse.py::test_timeout_is_clean_per_paper_failure
- tests/test_chunker.py::TestSectionLessFallback::test_fallback_chunk_ids_are_deterministic
- tests/test_bulk_ingest.py::TestDiagnoseEmptyRender::test_chapter_render_is_structured
- tests/test_bulk_ingest.py::TestDiagnoseEmptyRender::test_ac4_signal_set_is_single_source
- tests/tools/test_notebook_scripts.py::test_make_init_recipe_expands

## Gate
`findings.py gate` → OK (no open findings). ruff clean. pytest: only the 7
pre-existing Windows-platform failures remain (symlink×4, cp1252, subprocess,
path-sep); zero new.

## Pending external write (STOP)
- `git merge ingest-robustness-m1 -> main` — LOCAL, user-authorized. No push.

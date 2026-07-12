# Implement synthesis — ingest-robustness-m1

Inline implementation (delegation non-viable: no registered milestone-implementer
+ delegated worktree lacks the venv for the check gate). Per-AC commits off
`23b8628` on branch `ingest-robustness-m1`.

## Built
- **AC1 — section-less chunker fallback** (`f49bd05`). `ingest/chunker.py`:
  new `_extract_body_fallback_chunks(root, paper_id, counter)` invoked at the
  `if not all_chunks:` guard (chunker.py, right after the two structural
  passes combine). Token-packs top-level `ltx_para`/`ltx_p`/`<p>` prose under
  `ltx_document` into `STMT_MAX_TOKENS`-bounded `kind="section"` records routed
  through the existing `_compute_chunk_id` + dedup post-pass. Guard guarantees
  sectioned papers untouched (10 golden fixtures unmoved).
- **AC4 — structure gate** (`386490e`). `ingest/bulk_ingest.py`:
  `_diagnose_empty_render` → `failure_reason="render_unchunkable_no_sections"`
  when a zero-chunk render has math but no `ltx_section/theorem/proof/chapter`.
  `ingest/ar5iv_fetch.py`: `no_sections` WARN on the fresh-fetch hit path.
- **AC3 — standing MinerU wiring** (`f31916e`, `bbfb955`).
  `ingest/textbook_parser._resolve_mineru_binary(explicit)` precedence
  arg > env > operator_settings > which > raise, with
  `_mineru_bin_from_operator_settings` (lazy `server.operator_settings` import,
  degrades to next tier on any failure). `server/operator_settings.get_mineru_bin`
  reader. `tools/notebook_init.py --mineru-bin` + `_persist_mineru_bin`.
  `server/main.py`: `ARXMCP_MINERU_BIN` + `ARXMCP_MINERU_TIMEOUT_S` registered
  in `_KNOWN_INGEST_ENV_VARS`. `Makefile`: `MINERU_BIN` threaded into `init`.
  `tests/conftest.py`: `get_mineru_bin` added to the operator_settings re-point
  loop (test isolation).
- **AC2 — MinerU Stage-1 CLI** (`a7f6972`). New `tools/notebook_pdf_parse.py`:
  `run_mineru_sandboxed` + `render_mineru_to_html` → `parsed/<flat>/index.html`
  for a textbook notebook; idempotent (`--force` to re-run); mocked-mineru tests.
- **Docs** (`b2352c0`). `install.md` MinerU precedence + persistence;
  `usage.md` headless PDF-ingest lane.

## Branching note
Commits land on branch `ingest-robustness-m1` in an isolated worktree off local
HEAD `23b8628` (the main tree is dirty with unrelated in-flight work). Final
merge to `main` is the sole `external_writes_required` entry — Phase-4 boundary,
user-authorized. CLAUDE.md §4.1 "all work lands on main".

## Files touched
- `ingest/chunker.py` — AC1 fallback helper + guard.
- `ingest/bulk_ingest.py` — AC4 `_diagnose_empty_render`.
- `ingest/ar5iv_fetch.py` — AC4 no_sections WARN.
- `ingest/textbook_parser.py` — AC3 resolver precedence + settings tier.
- `server/operator_settings.py` — AC3 `get_mineru_bin`.
- `server/main.py` — AC3 env-var registration.
- `tools/notebook_init.py` — AC3 `--mineru-bin` persistence.
- `tools/notebook_pdf_parse.py` — AC2 CLI (NEW).
- `Makefile` — AC3 `make init MINERU_BIN=`.
- `docs/install.md`, `docs/usage.md` — AC2/AC3 docs.
- `tests/` — `test_chunker.py`, `test_bulk_ingest.py`, `test_ar5iv_fetch.py`,
  `test_textbook_parser.py`, `tests/tools/test_notebook_scripts.py`,
  `test_notebook_pdf_parse.py` (NEW), `conftest.py`.

## Deferred
- Operational (out of scope, post-merge against main-tree `var/`): re-ingest
  hep-th/0002037 (chunker fallback + MinerU backup), 2602.24016 SQLite
  bookkeeping backfill.
- `textbook_chunker` does NOT inherit the AC1 fallback (separate
  `_chunk_textbook_impl`) — acceptable; textbook path gets sections via the
  m6 markdown-heading→`\section` conversion. Flagged in brief-1 risk #4.

## external_writes_required
- `git merge ingest-robustness-m1 -> main` (LOCAL only; end-of-milestone, after
  explicit user authorization). No push/publish/deploy/network.

## Test deltas
New tests: AC1 (3, section-less recovery + empty-stays-empty + sectioned-guard),
AC4 (5, ar5iv WARN ×2 + diagnose ×3), AC3 (7, resolver tiers + notebook_init
persist/reject), AC2 (6, mocked mineru CLI). All pass.

## Check gate results
- `ruff check` (whole diff): PASS.
- pytest (touched subset + new modules): PASS — 7 failures, ALL pre-existing
  Windows-platform (4 symlink WinError 1314, 1 cp1252, 1 subprocess, 1 path-sep;
  see `test-baseline.md`). Zero new failures.
- git status: only the `.claude/notes/milestones/ingest-robustness-m1/`
  bookkeeping is uncommitted (committed in the Phase-4 chore); all CODE committed.

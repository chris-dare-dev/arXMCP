---
milestone_id: "ingest-robustness-m1"
phase: research-synthesis
research_mode: standard
external_writes_required:
  - "git merge ingest-robustness-m1 -> main (LOCAL only; end-of-milestone, after explicit user authorization)"
implementation_path: inline
implementation_path_rationale: >
  Briefs size this DELEGATED (~16 files / ~600 LOC). Delegation is NOT viable in
  this environment: (1) the bespoke milestone-implementer subagent type is not
  registered in this harness; (2) a delegated worktree has no .venv, so a
  delegated implementer cannot run the check gate to self-verify; (3) the work is
  correctness-critical (chunk_id determinism, golden-fixture byte-stability,
  server-startup fatal semantics) and the orchestrator holds the full research
  context. Proceed INLINE with per-AC coherent commits; run the gate under the
  main-tree venv python (PYTHONPATH pinned to the worktree) after each AC.
  The ~600-LOC total stays under the 800-LOC abort line.
estimated_diff_loc: 600
estimated_file_count: 16
---

# Research synthesis — ingest-robustness-m1

Two research briefs (explore=brief-1, general=brief-2) agree on approach and
anchors. This synthesis dedupes them, locks the open design decisions, and sets
the Phase-2 plan.

## Affected files (deduped)

**Source (code):**
- `ingest/chunker.py` — AC1 fallback hook at `:901` (`if not all_chunks:`), new
  helper `_extract_body_fallback_chunks(root, paper_id, counter)`.
- `tools/notebook_pdf_parse.py` — AC2, NEW shipped Stage-1 CLI.
- `ingest/textbook_parser.py` — AC3, `_resolve_mineru_binary` precedence chain.
- `server/operator_settings.py` — AC3, new `get_mineru_bin` convenience reader.
- `tools/notebook_init.py` — AC3, `--mineru-bin` persistence.
- `Makefile` — AC3, `MINERU_BIN` var threaded into `init`.
- `server/main.py` — AC3, register `ARXMCP_MINERU_BIN` + `ARXMCP_MINERU_TIMEOUT_S`
  in `_KNOWN_INGEST_ENV_VARS` (they currently FATAL `make up` if exported).
- `ingest/bulk_ingest.py` — AC4, `_diagnose_empty_render` → distinct
  `failure_reason="render_unchunkable_no_sections"`.
- `ingest/ar5iv_fetch.py` — AC4, `no_sections` WARN on fresh-fetch path.

**Tests + fixtures:**
- `tests/fixtures/chunker/hep-th_0002037/index.html` — NEW section-less fixture
  (derive by trimming the REAL `var/arxmcp/corpus/parsed/hep-th/0002037/index.html`
  from the MAIN tree — preserve `ltx_document`+`ltx_para`+`<math>`, zero
  `ltx_section`/`ltx_theorem`).
- `tests/test_chunker.py` — AC1 positive + sectioned-regression.
- `tests/test_notebook_pdf_parse.py` — NEW, AC2 (mocked mineru/renderer).
- `tests/test_textbook_parser.py` — AC3 operator_settings precedence tier.
- `tests/test_bulk_ingest.py`, `tests/test_ar5iv_fetch.py` — AC4.
- (possibly `tests/test_notebook_init.py`, `tests/test_operator_settings.py`.)

**Docs:** `docs/install.md`, `docs/usage.md`.

## Acceptance criteria (traced to brief)

1. **AC1 section-less fallback** — `chunk_paper` on a section-less/theorem-less
   but body-rich render yields ≥1 chunk; sectioned papers unchanged (10 golden
   fixtures byte-identical). Deterministic ids via existing `_compute_chunk_id`
   + dedup. No hardcoded `"v1.1"` literal (TestSingleVersionDefinition scans).
2. **AC2 MinerU Stage-1 CLI** — `tools/notebook_pdf_parse.py <slug> --paper-id <id>`
   chains `run_mineru_sandboxed` + `render_mineru_to_html` → `parsed/<flat>/index.html`;
   idempotent skip if it exists; mocked-mineru unit test (no GPU run).
3. **AC3 standing `ARXMCP_MINERU_BIN`** — resolver precedence arg > env >
   operator_settings > which > raise; `get_mineru_bin` reader; `make init
   MINERU_BIN=…` persistence; register both MinerU env vars in
   `_KNOWN_INGEST_ENV_VARS`; docs. (ingest→server import only; never ingest→tools.)
4. **AC4 structure gate** — bulk_ingest distinct `render_unchunkable_no_sections`
   for the residual math-but-no-prose case (fires only after AC1's fallback still
   empties); ar5iv_fetch `no_sections` WARN on fresh fetch.
5. **AC5 tests + gate** — per-AC tests; `ruff check .` clean; no NEW test
   failures vs the recorded baseline (`implement/test-baseline.md`: 5 pre-existing
   Windows/env failures in the touched subset).

## Locked design decisions (resolving the briefs' open questions)

- **AC1 granularity:** token-packed accumulation — walk `ltx_document`'s
  top-level `ltx_para`/`ltx_p`/bare `<p>` in document order, accumulate text
  until the next block would exceed `STMT_MAX_TOKENS`, flush a chunk (each flush
  `_truncate_to_token_budget`-capped). Skip blocks with <`MIN_SECTION_TEXT_CHARS`
  (80) of their own text; the fallback returns `[]` when total harvestable prose
  is trivial (this preserves AC4's "truly unchunkable stays empty").
- **AC1 kind/provenance:** `kind="section"` (already in `store._ALLOWED_KINDS`),
  `section_path=[]`. No new kind, no schema change.
- **AC1 hook:** `if not all_chunks:` at `chunker.py:901` — the structural
  guarantee sectioned papers are untouched. Fallback chunks join `all_chunks`
  BEFORE the `:930-961` id+dedup post-pass (inherit determinism for free).
- **AC4 diagnosis:** cheap regex scan (`ltx_(section|theorem|proof)\b`) of the
  on-disk parsed HTML in a `bulk_ingest._diagnose_empty_render` helper — no
  chunker return-contract change (lighter diff; brief-2 open-q 2).
- **AC3 resolver:** `_resolve_mineru_binary(explicit: str|None=None)`; lazy
  `from server.operator_settings import get_mineru_bin` with missing-DB
  graceful-degrade to the next tier; validate persisted path exists (same as env).

## external_writes_required (verbatim from brief-2)

- `git merge ingest-robustness-m1 -> main` — LOCAL git only, end-of-milestone,
  AFTER explicit user authorization. NO push, publish, deploy, or mutating API.
  All corpus re-ingest is OUT OF SCOPE (operational, post-merge, main tree).

## Phase-2 plan (inline, per-AC commits)

Order: AC1 (chunker fallback + fixture) → AC4 (gate signal, depends on AC1
behavior) → AC3 (MinerU wiring) → AC2 (CLI) → docs. Run the touched-subset gate
after AC1 and again at the end; `ruff check .` before the commit(s).

## Open questions carried into implementation (≤5)

1. Fixture fidelity: derive `hep-th_0002037` fixture from the real main-tree file
   (trim, preserve class structure) so the positive test proves the real path.
2. AC4 regex vs chunker drift — keep the scan's "no structure" verdict aligned
   with the chunker's actual gates (section + theorem + proof classes).
3. `section_path=[]` vs a provenance marker — verify `[]` perturbs no golden
   fixture (it won't fire on them, but confirm serialization).
4. `make init MINERU_BIN=` host — `tools/notebook_init.py --mineru-bin` (confirmed
   the email precedent's host).
5. Server-startup: after registering the MinerU vars, check
   `tests/test_server_startup.py` doesn't pin the old carve-out set.

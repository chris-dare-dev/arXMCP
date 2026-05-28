# Implementation Summary — notebook-retrieval-m1

**Path:** inline (orchestrator main session)
**Base SHA:** `da9a800f3eaf08d9549f73f1a108ce55d8a9d671`
**Generated:** 2026-05-28

---

## One-line

Fork C: `ARXMCP_NOTEBOOK=<slug>` makes the server serve a per-notebook lancedb — `Config` derives `lancedb_path` from the slug (via a shared `tools._notebook_common.notebook_lancedb_path` helper that fork A will reuse) before `Resources.startup` reads it. Dense-only retrieval, unchanged. ~2 source files + tests + docs.

## Commit range

`da9a800f..<HEAD>` (filled after the feat commit lands).

## Acceptance criteria status (post-synthesis ACs)

- **[AC1] (routing) ✅** `ARXMCP_NOTEBOOK=<slug>` rewrites `lancedb_path` to `var/arxmcp/notebooks/<slug>/lancedb`. Verified: `tests/test_server_startup.py::TestNotebookConfig::test_notebook_set_derives_lancedb_path` + `::test_notebook_set_via_env`. The end-to-end query (`0705.3794` surfaces) is a `requires_model` concern deferred to operator verification; the routing assertion (server opens the notebook path, not the empty shared corpus) is the CI-gating test.
- **[AC2 — corrected] ✅** Retrieval is the SAME dense-only path the shared corpus uses (single ANN over `embedding_stmt`, proof chunks excluded, `retrieval_mode=dense_only`). No retrieval-pipeline change — fork C only redirects which lancedb `Resources` opens. The accuracy spikes confirmed wiring BM25/RRF/rerank would REGRESS on these corpora; AC2's original "wire the full pipeline" was wrong and is corrected here.
- **[AC4] ✅** `ARXMCP_NOTEBOOK` unset → `lancedb_path` byte-identical to today's default. Validator is a no-op. Verified: `::test_notebook_unset_keeps_shared_corpus`.
- **[AC5] ✅** Notebook set but not ingested → clear `ValidationError` at config-load naming the ingest command, not a 500. Verified: `::test_missing_notebook_corpus_clear_error`.
- **[AC6 — reframed] ✅** The notebook's dense ANN uses the notebook's pinned `corpus_version` (opens the notebook's `lancedb`). BM25 off the live path → no BM25-version concern for m1.
- **[AC7] ✅** Docs: `.claude/notes/06-mcp-server-design.md` § "Notebook-scoped retrieval (fork C)" + `docs/install.md` § "Serving a notebook corpus".
- **[AC8 — new, stepping-stone] ✅** The slug→lancedb-path derivation lives in `tools._notebook_common.notebook_lancedb_path(slug)` — the shared seam fork C and the future fork A both call. Verified: `TestNotebookLancedbPathHelper`.
- **[X-1] ✅** `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED (no tools.py/handler/Field edit).
- **[X-2] ✅** `EXPECTED_BP1_SHA256` UNCHANGED (no prompts.py edit).
- **[X-3] ✅** `ruff` clean; `make test`: 3042 passed, 29 skipped, 1 xfailed, 3 pre-existing failures (latexmlc ×2 + Kùzu cite_neighbors ×1, all verified pre-existing).
- **[X-4] ✅** No `CHUNKER_VERSION` bump.

## Security (Threat 1)

The slug flows into a filesystem path; validated by `notebook_lancedb_path` → `notebook_dir` → `validate_slug` (regex + symlink rejection + containment) BEFORE any path use. Traversal/slash/uppercase/short slugs rejected at config-load. Verified: `::test_notebook_slug_traversal_rejected` + `TestNotebookLancedbPathHelper::test_helper_inherits_slug_validation` + `::test_helper_rejects_symlinked_notebook`.

## New / changed code

- **`tools/_notebook_common.py`**: new `notebook_lancedb_path(slug, *, base=None)` = `notebook_dir(slug) / "lancedb"` (shared C/A seam); exported.
- **`server/config.py`**: new `notebook` field (`ARXMCP_NOTEBOOK`); `derive_notebook_lancedb_path` model-validator (rewrites `lancedb_path`, rejects notebook+lancedb_path ambiguity, fails fast on un-ingested notebook). No-op when unset.

## New tests

- `tests/test_server_startup.py::TestNotebookConfig` (6) + `::TestNotebookLancedbPathHelper` (3).

## Docs

- `.claude/notes/06-mcp-server-design.md`, `docs/install.md`.

## External writes required

None — local server code + tests + docs.

## Deviations from the brief

1. **AC2 corrected** (full-pipeline → dense-only) per the accuracy spikes.
2. **AC1 end-to-end query operator-deferred** (routing is CI-gated; the surfaces-0705.3794 assertion needs BGE-M3 + live notebook).
3. **Fork A deferred to m2**; `notebook_lancedb_path` is the front-loaded shared helper (AC8) so C→A is additive.

## Operator note

Serve the bridgeland notebook now: `ARXMCP_NOTEBOOK=bridgeland-stability make up` (if `make up` fails the Py-3.9 assertion, use `ARXMCP_NOTEBOOK=bridgeland-stability /Users/chris.dare/Library/Python/3.9/bin/uv run python -m server.main`).

## Risk surface for Phase 3 critique

- `make up` PYTHON=3.9 trap (pre-existing Makefile issue; out of scope).
- AC1 end-to-end accuracy operator-deferred (adversary may want a `requires_model` stub).
- `Config` mutates `lancedb_path` in an after-validator (pydantic-settings; smoke-tested OK).
- Derived path is absolute (notebook_dir `.resolve()`) vs the relative shared default — confirm no downstream assumes relative.

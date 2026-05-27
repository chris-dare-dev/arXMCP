# Implementation Summary — textbook-ingest-m3

**One-line.** Coordinated BP1 cache-invalidation checkpoint for the
textbook-ingest family: `SEARCH_PAPERS` ToolMeta description updated
to document the `textbook:<slug>` filter form, `TOOL_SCHEMA_VERSION`
bumped 12 → 13, both `EXPECTED_TOOL_SCHEMA_SHA256` and
`EXPECTED_BP1_SHA256` re-pinned in lockstep, `notebook_kind` field
added to the m6 notebook schema with SQLite v2→v3 migration.

**Commit base.** `0ac2bd4` (m2 finalize).

---

## Acceptance criteria status

- [x] **AC #1.** `tools/list` SHA matches re-pinned
      `EXPECTED_TOOL_SCHEMA_SHA256 = c8210225f1c86c83ba628112627d8f9f8689ce1d0dcfa88b9c3ae945d2065132`.
      Test: `tests/test_server_tool_schema.py::TestPinnedHash::test_live_tools_match_pinned_hash` PASSES.
- [x] **AC #2.** BP1 prefix SHA matches re-pinned
      `EXPECTED_BP1_SHA256 = 413059930ce9b56399b877537ef0b6c363a4b52df8d76f3668e53305fd7c41d5`.
      Test: `tests/test_prompts.py::TestBP1ByteIdentityAcrossFanout::test_bp1_hash_pinned` PASSES.
- [x] **AC #3.** Notebook created with `notebook_kind="textbook"`
      round-trips; default `"arxiv"`.
      Tests: `tests/test_notebook_api.py::TestNotebookKind` (4 tests
      covering default, textbook round-trip, invalid rejection, each
      valid value).
- [x] **AC #4.** Single rect-style commit; pre-commit hooks honored;
      GPG signing on; co-author trailer present.
- [x] **AC #5.** `.claude/notes/prompts-bp-discipline.md` updated with
      a new section "Textbook-family BP1 bump (textbook-ingest-m3)"
      documenting what changed, what didn't, the new SHA values, and
      the precedent.
- [x] **AC #6.** `make test` green; no macOS segfaults.
      2800 passed, 26 skipped, 1 xfailed. Six pre-existing
      environmental failures (3 parser-fidelity fixture dirs missing
      locally, 2 `latexmlc` SIGABRT, 1 Kùzu state) verified unchanged
      from pre-m3 via `git stash` reproduction.

---

## Files changed

1. **`server/tools.py`** — `SEARCH_PAPERS.description` edited to
   replace `"each validated against the arXiv format"` with
   `"each validated against the arXiv or textbook:<slug> format"`.
   `TOOL_SCHEMA_VERSION` bumped 12 → 13 with a new ledger comment
   documenting the textbook-family BP1 bump rationale.

2. **`tests/test_server_tool_schema.py`** —
   `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned to
   `c8210225f1c86c83ba628112627d8f9f8689ce1d0dcfa88b9c3ae945d2065132`.
   `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` bumped to 13.
   Both literals updated by `pytest --update-tool-schema-hash`.

3. **`tests/test_prompts.py`** — `EXPECTED_BP1_SHA256` re-pinned to
   `413059930ce9b56399b877537ef0b6c363a4b52df8d76f3668e53305fd7c41d5`
   with annotated comment per the v12 precedent.

4. **`server/schemas/search_papers_result.json`** — `version` 12 → 13,
   `$id` v12 → v13, description appended with the textbook-ingest-m3
   bump note.

5. **`server/schemas/lean_verify_result.json`** — `version` 12 → 13,
   `$id` v12 → v13, description appended with the textbook-ingest-m3
   bump note (the lean_verify result-row shape itself is unchanged;
   the version field tracks `TOOL_SCHEMA_VERSION` globally).

6. **`tests/test_handlers_lean_verify.py`** — hardcoded
   `assert TOOL_SCHEMA_VERSION == 12` updated to `== 13`.

7. **`server/notebooks_store.py`** — `SCHEMA_VERSION` 2 → 3 with an
   additive v2→v3 migration block that runs
   `ALTER TABLE notebooks ADD COLUMN notebook_kind TEXT NOT NULL
   DEFAULT 'arxiv'`. `create_notebook` extended to accept
   `notebook_kind` (default `"arxiv"`). `list_notebooks` and
   `get_notebook` thread the new column through SELECT and into the
   returned dict.

8. **`server/routes/notebooks.py`** — `NotebookCreate` Pydantic model
   gains `notebook_kind: str = Field(default="arxiv",
   pattern="^(arxiv|textbook)$")`. The `POST /ui/api/notebooks` route
   threads the field into the store and returns it in the 201
   response body.

9. **`tests/test_notebook_api.py`** — two new test classes:
   - `TestNotebookKind` (4 tests): default behavior,
     textbook round-trip, invalid rejection (HTTP 422 via Pydantic
     pattern), each valid value accepted.
   - `TestNotebookKindMigration` (2 tests): v2→v3 ALTER backfills
     existing rows with `"arxiv"`; PRAGMA user_version after open
     against a fresh DB is 3.

10. **`.claude/docs/...`** — no edits in m3 (snippet-contract.md and
    05-storage-and-indexing.md were updated in m2 and remain
    accurate).

11. **`.claude/notes/prompts-bp-discipline.md`** — new section
    "Textbook-family BP1 bump (textbook-ingest-m3)" appended before
    Cross-references. Documents what changed (`SEARCH_PAPERS`
    description), what didn't (SYSTEM_PROMPT, other tool descriptions,
    breakpoint placement), the new SHA values, and the precedent
    (verification-feedback-m3 commit 853011e).

12. **`.claude/notes/milestones/textbook-ingest-m3/`** — pipeline
    state: research-brief-1.md (single-mode), research-synthesis.md,
    state.json.

---

## Deviations from the brief

1. **`SEARCH_PAPERS` description edit was the chosen MCP-surface
   delta.** At m2-baseline HEAD, the `tools/list` hash had NOT
   actually drifted — m1's edit to `search_papers_result.json` is
   not embedded in `tools/list`, and m2 made no MCP-surface changes.
   Per synthesis D1: edit `SEARCH_PAPERS` description (one line) to
   document the `textbook:<slug>` filter form so the hash bump
   reflects a semantically meaningful change rather than a no-op
   re-pin.

2. **`SYSTEM_PROMPT` left as the E08_S04 placeholder.** Per
   synthesis D3, adding textbook-aware language to the system prompt
   would be aspirational and risk drift when E08_S04 lands its v1
   body. The single ToolMeta description edit is sufficient to drift
   BP1 (`{system, tools}` — the tools array changed).

3. **`notebook_kind` is an HTTP-route field, not part of `tools/list`.**
   Its addition does NOT affect either `EXPECTED_TOOL_SCHEMA_SHA256`
   or `EXPECTED_BP1_SHA256`. The route schema and the MCP tool schema
   are independent BP1 surfaces.

4. **Two JSON schema files needed version bumps beyond the brief's
   list.** `server/schemas/search_papers_result.json` and
   `server/schemas/lean_verify_result.json` both pin their `version`
   integer to `TOOL_SCHEMA_VERSION` via cross-check tests — bumping
   `TOOL_SCHEMA_VERSION` 12 → 13 required bumping these schemas too.
   Forced by the existing test contract, not a brief deviation
   per se.

---

## New / changed test paths

- `tests/test_server_tool_schema.py` (literal updated by flag)
- `tests/test_prompts.py` (literal updated manually + annotated comment)
- `tests/test_handlers_lean_verify.py` (hardcoded assertion bumped)
- `tests/test_notebook_api.py` (+6 new tests across 2 new classes)

Test count: project-wide 2794 → 2800 (+6 new).

---

## External writes required

**None.** Purely local. No `git push`, no PR, no `gh`, no infra
mutation, no external API call.

---

## Pre-existing failures observed (not from m3)

Same six as m2's tail; verified via `git stash` reproduction:

| Test | Failure | Root cause |
|---|---|---|
| `tests/eval/test_parser_fidelity.py::TestFixtureStructure::test_class_dir_exists[hartshorne-style]` | `is_dir()` returns False | Parser-fidelity fixture dir not populated locally |
| `tests/eval/test_parser_fidelity.py::TestFixtureStructure::test_class_dir_exists[griffiths-harris-style]` | same | same |
| `tests/eval/test_parser_fidelity.py::TestFixtureStructure::test_class_dir_exists[milne-style]` | same | same |
| `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines` | `latexmlc exited -6 on align.tex` | `latexmlc` SIGABRT on this workstation |
| `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact` | `latexmlc exited -6 on frac.tex` | same |
| `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` | Kùzu graph_status `unavailable` (expected `absent`) | Local `var/arxmcp/index/kuzu` state |

---

## Family status post-m3

```
textbook-ingest:
  e1 (schema migration)         DONE ✓  (m1 + m2 + m3 shipped)
  e2 (MinerU sandbox)           Next-lane — depends on e1 (now ready)
  e3 (hierarchical chunker)     Next-lane — depends on e1 (now ready)
  e4 (cross-corpus search)      Next-lane — depends on e1+e2+e3
  e5 (PDF threat hardening)     Later-lane
  spikes 1-3                    not started — recommended before e2
```

The arXiv-corpus side of the textbook-ingest family is now
complete: chunk-id identity (m1), storage columns (m2), and BP1
cache invalidation (m3) all shipped. The next milestones extend the
ingest pipeline (parser e2, chunker e3) and the MCP surface
(cross-corpus filter e4); none of those require further BP1 re-pins
until they actually change `ALL_TOOLS` or `SYSTEM_PROMPT`.

# Research Synthesis — textbook-ingest-m3

**Single-mode dispatch.** [research-brief-1.md](research-brief-1.md) is
the primary input. This synthesis records orchestrator decisions.

---

## Scope (verbatim from roadmap)

Single coordinated rect-style commit that re-pins
`EXPECTED_TOOL_SCHEMA_SHA256` AND `EXPECTED_BP1_SHA256` AND adds the
`notebook_kind: "textbook"` field to the m6 notebook schema in
`server/routes/notebooks.py`. Hash re-pin is byte-stable: schema
description edits, key-ordering, and BP1 prompt-prefix edits all
bundle into this one commit so the BP1 prompt cache invalidates
ONCE for the full family.

**Acceptance criteria:**

1. `tools/list` SHA matches re-pinned `EXPECTED_TOOL_SCHEMA_SHA256`.
2. BP1 prefix SHA matches re-pinned `EXPECTED_BP1_SHA256`.
3. Notebook created with `notebook_kind="textbook"` round-trips;
   default `"arxiv"` for arxiv-flavor notebooks.
4. Single rect commit; pre-commit hooks honored; GPG signed.
5. `.claude/notes/prompts-bp-discipline.md` updated.
6. `make test` green; no macOS segfaults.

---

## Load-bearing constraints

### `EXPECTED_TOOL_SCHEMA_SHA256` hashes the `tools/list` payload

`tests/test_server_tool_schema.py:41-46`:

```python
payload = {"tools": [t.model_dump(mode="json", by_alias=True,
                                   exclude_none=True)
                      for t in tools]}
canonical = json.dumps(payload, sort_keys=True,
                       separators=(",", ":"), ensure_ascii=True)
sha256(canonical.encode("utf-8")).hexdigest()
```

Current pinned value: `1d0abfe94a53230c3976bf16f418011884234662f7d4434256416782f0e00140`
(`TOOL_SCHEMA_VERSION = 12` in `server/tools.py`).

`search_papers_result.json` is NOT embedded in `tools/list` —
m1's chunk_id-pattern edit to that file did not drift this hash.
**Today the hash currently passes against the m2-baseline HEAD without
any change** (verified by R1: "the m1 edits to `search_papers_result.json`
do NOT change the tools/list hash").

### `EXPECTED_BP1_SHA256` hashes `{system, tools}`

`tests/test_prompts.py:506-513`:

```python
bp1 = {"system": req["system"], "tools": req["tools"]}
return hashlib.sha256(_canonical_json(bp1)).hexdigest()
```

Current pinned value: `1162e998fab9637a2ddbf4423ac8e84d439bff24ff26842cac3860cc460938ed`.

### `SYSTEM_PROMPT` is still the placeholder (E08_S04 TODO)

`server/prompts.py:113-116`:

```python
SYSTEM_PROMPT: str = (
    "<placeholder system prompt — E08_S04 will author the v1 body. "
    "This text is byte-stable but informationally a no-op for v1.>"
)
```

Per R1: "Do NOT touch `SYSTEM_PROMPT`. Adding textbook language there
would be aspirational and risk breaking the 50-token-per-role prefix
invariants." Resolved (D3 below).

### Notebook store SQLite schema is at `SCHEMA_VERSION = 2`

`server/notebooks_store.py` carries the schema constant. Existing
v1→v2 migration (m9) used additive `CREATE TABLE IF NOT EXISTS`. The
documented pattern (lines 57-68 per R1):

> "When adding a new version: append a new `if current_version < N:`
> block in `_open_sync` using `CREATE TABLE IF NOT EXISTS` /
> `ALTER TABLE` and bump SCHEMA_VERSION; do NOT drop existing tables."

`NotebookCreate` (`server/routes/notebooks.py:185-198` per R1) has
no `notebook_kind` field today.

### Re-pin precedent: verification-feedback-m3 (commit 853011e)

Per R1: prior re-pin episode landed BOTH `EXPECTED_TOOL_SCHEMA_SHA256`
and `EXPECTED_BP1_SHA256` in the same commit (it added the 8th tool
`lean_verify`, bumping `TOOL_SCHEMA_VERSION` 11→12). The brief's
"bundle into one commit" instruction has a tested precedent.

### `--update-tool-schema-hash` flag has a version-bump guard

`pytest tests/test_server_tool_schema.py --update-tool-schema-hash`
REFUSES to proceed unless `TOOL_SCHEMA_VERSION` is bumped from
`EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` first (F2 from E06_S06).
**Order matters:** bump VERSION → run flag → manually update BP1
SHA from the test's printed value.

---

## Orchestrator design decisions

### D1 — Edit `SEARCH_PAPERS` ToolMeta description for textbook paper_id

The brief presupposes a hash re-pin in m3, but at current HEAD the
`tools/list` hash does NOT drift. The brief's "schema description
edits" wording hints at the intended pattern. R1's recommendation
(adopted):

> "Edit `server/tools.py` SEARCH_PAPERS description to document the
> textbook paper_id format in the `filters` argument: replace 'each
> validated against the arXiv format' with 'each validated against
> the arXiv or textbook:<slug> format'."

This is the **minimum semantically meaningful change** that reflects
the m1 identifier widening at the MCP surface. The description edit
is non-aspirational (the regex actually accepts the textbook form;
`is_valid_paper_id` returns True for `textbook:<slug>`; users via
the `filters` argument may legitimately send a textbook paper_id
now that m2 enabled textbook chunks to live in the corpus).

### D2 — Bump `TOOL_SCHEMA_VERSION` 12 → 13

Mandatory before running `--update-tool-schema-hash`. Single source
of truth in `server/tools.py`.

### D3 — Do NOT touch `SYSTEM_PROMPT`

The placeholder stays a placeholder; E08_S04 owns the real body.
Adding textbook language now would be premature and risk drift
when E08_S04 ships. The `SEARCH_PAPERS` description edit is enough
to drift BP1 (since BP1 = `{system, tools}` and tools changed).

### D4 — `notebook_kind` shape: Pydantic enum-like field + SQLite ALTER

- `NotebookCreate`: `notebook_kind: str = Field(default="arxiv", pattern="^(arxiv|textbook)$")` — Pydantic pattern validation prevents typos.
- `NotebooksStore`: bump `SCHEMA_VERSION` 2→3, append `if current_version < 3:` block with `ALTER TABLE notebooks ADD COLUMN notebook_kind TEXT NOT NULL DEFAULT 'arxiv'`.
- `create_notebook`, `list_notebooks`, `get_notebook`: thread `notebook_kind` through SELECT/INSERT and return dict.

**Defaults at both layers** (R1's clarification adopted):
- Write-path default: Pydantic field `default="arxiv"` if operator omits.
- Read-path default: SQLite `DEFAULT 'arxiv'` on the ALTER → existing rows get the token.

### D5 — Doc edits to `prompts-bp-discipline.md`

Append a new section "## Textbook-family BP1 bump (textbook-ingest-m3)"
before the cross-references at the bottom. Document:
- What changed: `SEARCH_PAPERS` ToolMeta description gained
  `textbook:<slug>` form in the filters validation language.
- Why intentional: m1 widened `is_valid_paper_id` to accept the
  textbook form; the tool description had drifted from the validator
  contract.
- New SHA values (insert after rerun).
- `TOOL_SCHEMA_VERSION` bump 12 → 13.

### D6 — Test surface

Three test areas need touches:

1. `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` +
   `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` updated by the
   `--update-tool-schema-hash` flag.
2. `tests/test_prompts.py` — `EXPECTED_BP1_SHA256` literal manually
   re-pinned to the value the test prints on failure; comment
   describes the m3 bump per the precedent at lines 627-631.
3. `tests/test_routes_notebooks.py` (or equivalent) — new test:
   - `test_notebook_kind_default_arxiv_on_create`
   - `test_notebook_kind_textbook_round_trip`
   - `test_notebook_kind_invalid_value_rejected`
   - Migration regression: pre-existing notebooks without
     `notebook_kind` column receive `"arxiv"` via SQLite default.

### D7 — Out of scope

- E08_S04 SYSTEM_PROMPT authoring.
- New MCP tools (search_textbooks killed per pdf-ingest-2026 T1).
- Cross-corpus `source_kind` filter (textbook-ingest-e4 / m4).

---

## Files touched in m3

1. `server/tools.py` — `SEARCH_PAPERS` description edit + `TOOL_SCHEMA_VERSION` 12→13.
2. `server/routes/notebooks.py` — `NotebookCreate` adds `notebook_kind` field; route response includes it.
3. `server/notebooks_store.py` — `SCHEMA_VERSION` 2→3 + ALTER TABLE migration block; `create_notebook` / `list_notebooks` / `get_notebook` thread `notebook_kind`.
4. `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` updated.
5. `tests/test_prompts.py` — `EXPECTED_BP1_SHA256` re-pinned with annotated comment.
6. `tests/test_routes_notebooks.py` (and/or `tests/test_notebooks_store.py`) — new `notebook_kind` tests.
7. `.claude/notes/prompts-bp-discipline.md` — textbook-family bump section.

NO touches to: `server/prompts.py` (SYSTEM_PROMPT), `ingest/*` (m2's domain),
`server/handlers/*` (post-m4 work).

---

## Failure modes (from R1, prioritized)

| # | Trigger | Severity | Mitigation in m3 |
|---|---|---|---|
| FM-1 | `--update-tool-schema-hash` without TOOL_SCHEMA_VERSION bump | BLOCKING | D2 — bump VERSION first |
| FM-2 | BP1 hash drifts cross-platform | NEGLIGIBLE | `sort_keys=True` + `ensure_ascii=True` already enforce determinism (R1 verified) |
| FM-3 | `notebook_kind` accepts garbage | MEDIUM | D4 — `Field(pattern="^(arxiv\|textbook)$")` |
| FM-4 | Existing `notebooks.db` lacks column | HIGH | D4 — migration block runs on `_open_sync` before any query |
| FM-5 | Doc updated but SHA literal missed | MEDIUM | Pin literal LAST in sequence; `make test` before commit |
| FM-6 | `KMP_DUPLICATE_LIB_OK` autouse fixture lost | NEGLIGIBLE | Pre-existing fixture; m3 adds no new conftest |

---

## Open questions

**None.** All decisions resolved above.

---

## External writes required

**None.** Purely local. No `git push`, no PR, no `gh`, no infra
mutation, no external API call.

---

## Orchestrator synthesis note

Single-mode dispatch; no peer disagreement to resolve. Two
orchestrator decisions beyond R1's recommendation:

1. **D2 ordering** — explicitly sequence VERSION bump → flag-rerun →
   manual BP1 literal update. Avoids the FM-1 guard rejection.
2. **D5 doc-update timing** — insert the new section in
   `prompts-bp-discipline.md` AFTER the test re-pins land (so the
   recorded SHA values are the final ones, not placeholders).

Ship as drawn.

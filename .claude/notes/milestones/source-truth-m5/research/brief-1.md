---
milestone_id: "source-truth-m5"
researcher_role: "explore"
injection_attempts: 0
---

# source-truth-m5 research brief-1 — serving path + schema-hash re-pin mechanism

## Headline finding (read this first)

`server/corpus.py::open_chunks_table` does **no column projection at all** — it just
opens/pins the raw LanceDB table handle. The actual row-read lives in
`server/handlers/chunk.py:53-58` (`r.chunks_table.search().where(...).limit(1).to_arrow()`),
which has **no `.select()` call**, so it returns *every column currently in the table's
schema*. That means **`server/corpus.py` needs zero changes** and the LanceDB query line
in `chunk.py` needs zero changes — m5 is a pure `server/handlers/chunk.py` dict-literal
edit (+ `server/tools.py` version bump + `tests/test_server_tool_schema.py` re-pin).

But this same "no `.select()`" behavior is a **live landmine**: I opened all 5 on-disk
notebook LanceDB tables directly (`.venv/Scripts/python.exe`, live data, 2026-07-13) and
found the roadmap's "hydrated on both live notebooks" claim is **narrower than it reads**:

| notebook | rows | schema | 5 cols present? | hydrated? |
|---|---|---|---|---|
| `bridgeland-stability` | 15,106 | v2 (26 cols) | yes | yes, 15,106/15,106 non-null `source_revision_id` |
| `fourier-duality` | 4,475 | v2 (26 cols) | yes | yes, 4,475/4,475 non-null |
| `bridgeland-stability-pdfs` | 780 | **v1 (21 cols)** | **NO** | not migrated |
| `fourier-duality-pdfs` | 2,051 | **v1 (21 cols)** | **NO** | not migrated |
| `demo-nb` | — | no `chunks` table | n/a | n/a |

15,106 + 4,475 = **19,581** — confirms the roadmap's row count, but "both live
notebooks" means the two HTML/ar5iv-sourced notebooks only. The two `-pdfs`
(MinerU) siblings — 2,831 rows, live and queryable today — are **still on the pre-m2
21-column schema**. No shared/global `var/arxmcp/index/lancedb/` exists (checked: absent);
the corpus is fully notebook-scoped, so this 4-way split is the complete picture, not a
sampling artifact.

I then reproduced `chunk.py`'s exact query (`.search().where(...).limit(1).to_arrow()`,
no `.select()`) against both an hydrated and an unmigrated table:

- Hydrated (`bridgeland-stability`): `arrow.column_names` includes all 5 new columns;
  `row["source_revision_id"]` etc. all resolve to real values.
- Unmigrated (`bridgeland-stability-pdfs`): `arrow.column_names` **does not contain the 5
  new columns at all** — `row["source_revision_id"]` would raise `KeyError`, not return
  `None`.

**Consequence for the implementer:** if the 5 new fields are added to the `chunk = {...}`
dict literal (`chunk.py:99-113`) using the same bracket-index style as the existing 11
fields (`row["kind"]`, `row["license"]`, …), `get_chunk` will **500 on every chunk_id
served from `bridgeland-stability-pdfs` or `fourier-duality-pdfs`** — a live regression,
not a hypothetical one. The fields must use `row.get("source_revision_id")` (etc.), not
`row["source_revision_id"]`. This is not addressed anywhere in the milestone brief, the
roadmap, or m2's artifacts (m2 rectify/summary.md's "Live tables untouched" section only
speaks to `bridgeland-stability`; nothing in m2 scoped or ran the backfill against the
`-pdfs` siblings). See "Risks" below.

## Affected files / context

1. **The row read — `server/corpus.py`** (547 lines, read in full).
   `open_chunks_table` (231-321) does `db.open_table(CHUNKS_TABLE_NAME)` then optionally
   `tbl.checkout(version)`; it returns the raw `lancedb.table.Table` handle with no
   `.select()`/projection logic anywhere in the module. **Zero changes needed here.** The
   "does get_chunk project all columns or a subset" question is answered one layer up, in
   the handler (below) — corpus.py is purely version-pinning plumbing.

2. **The response builder — `server/handlers/chunk.py`** (178 lines, read in full).
   - `handle_get_chunk` (33-157). Query at 53-58: `r.chunks_table.search().where(f"chunk_id
     = '{_escape_lance_str(chunk_id)}'", prefilter=True).limit(1).to_arrow()` — full-column
     projection (no `.select()`), confirmed live (see above).
   - `_arrow_first_row` (160-165): builds `row: dict` from `arrow.column_names` — a column
     **absent from the Arrow result** (unmigrated table) means the key is absent from
     `row` too (not `None` — genuinely missing), so `row["x"]` KeyErrors but `row.get("x")`
     returns `None`.
   - The `chunk = {...}` dict literal is at **99-113**, currently 11 keys in strict
     alphabetical order: `body_text, chunk_id, chunker_version, embedder_version, kind,
     license, paper_id, preamble_ref, section_path, theorem_label, theorem_name`. The 5 new
     keys slot in alphabetically: `license_ref` (after `license`), `printed_number` (after
     `preamble_ref`), `source_revision_id` + `source_span` (after `section_path`),
     `truncated` (after `theorem_name`). This ordering is stylistic (not
     hash-pinned/enforced anywhere for response bodies — alphabetical sort is only a
     contract for the `tools/list` **schema** hash, see item 3), but worth preserving for
     file-internal consistency.
   - **Existing `license`/`truncated_for_license` gate (94-98, textbook-ingest-m11/e5) is a
     DIFFERENT mechanism from the new `license_ref`.** `license` (chunk-level token,
     `server/license_policy.py`'s `OA_ALLOWLIST`) drives *actual* truncation-to-300-chars
     behavior TODAY. `license_ref` (source-truth-m2, per `ingest/schema.py:264-269`) is a
     **registry-derived, per-revision, advisory-only** field ("changes no serving behavior
     until the owner-gated m4 cutover" — verified verbatim in both `ingest/schema.py:267`
     and `server/license_policy.py`'s module docstring cross-reference). m5 must surface
     `license_ref` as a new, separately-named field and must NOT wire it into
     `is_open_access`/`license_truncated` — that rewiring is explicitly source-truth-m4's
     job (`plans/source-truth/roadmap.yaml:300-308`, gated on "owner sign-off").
   - `enforce_byte_cap` (132-136) and `wrap_retrieved_text` (145-147) operate only on
     `chunk.body_text`; none of the 5 new fields are byte-text, so neither needs new
     wiring — they just ride along as ordinary dict values in the JSON payload that
     `enforce_byte_cap` walks.

3. **The tool meta + version + re-pin mechanism — `server/tools.py`** (1000 lines; read
   the changelog block 91-168, `ToolMeta`/`GET_CHUNK` 193-262, and `register_all` 912-974
   in full).
   - `GET_CHUNK = ToolMeta(name="get_chunk", description=...)` at **228-237**. m5 adds NO
     new input parameters (`chunk_id`, `include_referenced`, `include_equations` are
     unchanged), so this description and the FastMCP-derived `inputSchema` are
     **byte-identical before/after m5**.
   - `TOOL_SCHEMA_VERSION: int = 17` at **line 168**, with a dated changelog comment
     immediately above (95-167) — **v16 (150-157) is the exact precedent for m5's shape**:
     "get_chunk's RESPONSE envelope grows a `truncated_for_license` flag ... This is a
     response-shape change only — the GET_CHUNK ToolMeta description and inputSchema are
     UNCHANGED, so EXPECTED_TOOL_SCHEMA_SHA256 re-pins (via the `_meta.tool_schema_version`
     echo) but EXPECTED_BP1_SHA256 does NOT." m5 is the same shape one level up (5 fields
     instead of 1) — same mechanism applies verbatim.
   - `register_all` (912-974): `meta = {"tool_schema_version": TOOL_SCHEMA_VERSION}`
     (**line 966**) is **one dict, reused for all 8 tools** in the `for tm in ALL_TOOLS`
     loop (967-973). This is the crux of *why* bumping `TOOL_SCHEMA_VERSION` alone forces
     a full-envelope hash change: `_meta` differs on **every** tool's wire record the
     moment the integer changes, even though only `GET_CHUNK`'s description/inputSchema
     stay untouched.
   - **Does surfacing new response fields require a tool-meta/description change?** No —
     confirmed by the v16 precedent and by `register_all`'s comment (950-965): the
     `_meta.tool_schema_version` echo is what the hash actually reacts to, not the response
     body shape itself (FastMCP's `tools/list` has no knowledge of a handler's runtime
     return value). **But this project's own discipline (the v16 precedent + the binding
     module-docstring rule at lines 16-20: "The constant TOOL_SCHEMA_VERSION is bumped
     manually on any schema change") treats a get_chunk response-shape change as a
     "schema change" requiring the bump regardless.** So m5 must still bump
     `TOOL_SCHEMA_VERSION` 17→18 with a new v18 changelog entry, purely to keep the
     version number meaningful as a wire-visible change marker — even though nothing in
     `ALL_TOOLS`'s `{name, description}` pairs differs.

4. **The schema-hash pin test — `tests/test_server_tool_schema.py`** (641 lines, read in
   full).
   - `EXPECTED_TOOL_SCHEMA_SHA256` at **94-96**; `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int
     = 17` at **line 109** (cross-check pin — the flag *refuses* to update the hash if
     `TOOL_SCHEMA_VERSION` wasn't bumped first, closing the "decorative version" gap: see
     `test_live_tools_match_pinned_hash`, 341-422, specifically the `live_hash != pinned_hash
     and live_version == pinned_version` guard at 368-382).
   - **What's hashed** (module docstring 38-61, `_serialize_tools` 158-179): the FULL
     `ListToolsResult` envelope for all 8 tools — `model_dump(mode="json", by_alias=True,
     exclude_none=True)` → `json.dumps(sort_keys=True, separators=(",",":"),
     ensure_ascii=True)` → sha256. `by_alias=True` is what turns Python's `meta` attr into
     the wire `_meta` key that actually changes when `TOOL_SCHEMA_VERSION` bumps.
   - **Re-pin procedure** (also in `tests/conftest.py:80-86`, flag registration):
     ```
     pytest tests/test_server_tool_schema.py --update-tool-schema-hash
     ```
     This rewrites `EXPECTED_TOOL_SCHEMA_SHA256` (regex-anchored on `# UPDATE-ANCHOR`,
     `_rewrite_pinned_hash` 242-276) **and** `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
     (`# VERSION-ANCHOR`, `_rewrite_pinned_version` 279-305) atomically, then **fails the
     test on purpose** with a "commit the changes and re-run pytest WITHOUT the flag"
     message (388-393) — the implementer must run it twice: once to write the new pin,
     once (flag-less) to confirm it's stable. The flag refuses to run under any CI env var
     (`_running_in_ci`, 308-322) and refuses silently-decorative bumps (368-382).
   - **What in the diff triggers the hash change:** *only* the `TOOL_SCHEMA_VERSION` bump
     (17→18) is required to change `EXPECTED_TOOL_SCHEMA_SHA256` — because it changes
     `_meta.tool_schema_version` identically on all 8 tools' wire records, and the hash
     covers the whole envelope. Nothing about `GET_CHUNK`'s `description` or `inputSchema`
     needs to change, and per the v16 precedent + `TestSchemaVersionMetaSurface` (425-460)
     this is the intended mechanism, not a workaround.
   - **`EXPECTED_BP1_SHA256` (separate pin, `tests/test_prompts.py:657-664`) should NOT
     need re-pinning** — it hashes only `{name, description}` per tool (confirmed by the
     v16 precedent's explicit note and by `snippet-contract.md:266-269`'s identical claim
     for the analogous m11 change). This is a *should*, not a *given*: the implementer
     must still run the BP1 test to confirm empirically, the same way m11 and m16 both
     did, rather than assume it from precedent alone.

5. **The snippet contract — `.claude/docs/snippet-contract.md`** (308 lines, read in
   full). Confirmed **out of scope for the 150-char snippet mechanics** (sections a-e are
   `search_papers`-only and untouched by m5). Section (g) (224-287) is the **existing
   get_chunk-response-shape precedent doc** — it documents the m11 `truncated_for_license`
   field, including its own "no re-pin of EXPECTED_BP1_SHA256" note (266-269), i.e. this
   doc is where m5's response-shape delta *should* eventually get a parallel short
   addendum (mirroring section g's structure: what the fields are, when they're null, the
   TOOL_SCHEMA_VERSION delta, the BP1 non-impact) for documentation completeness — not an
   AC, but the established convention in this repo (m11 did exactly this). No file named
   `server/schemas/get_chunk_result.json` exists (only `search_papers_result.json` and
   `lean_verify_result.json` do), so there is no separate machine-readable schema file to
   update for get_chunk.

6. **Tests for get_chunk — `tests/test_handlers_chunk.py`** (222 lines, read in full).
   The `_chunk_arrow` fixture (37-55) builds a synthetic 1-row Arrow table for the fake
   `chunks_table.search().where().limit().to_arrow()` chain, and **currently omits all 5
   v2 columns** (only the pre-v2 field set: chunk_id, paper_id, kind, section_path,
   body_text, theorem_name, theorem_label, chunker_version, embedder_version,
   preamble_ref, license). This is directly the empirical case I reproduced live against
   `bridgeland-stability-pdfs` — with today's fixture, any `row["source_revision_id"]`-style
   access in the handler would make **every existing test in this file** fail with
   `KeyError`, which is a useful regression tripwire but means the fixture needs a
   deliberate extension (not just a passive survivor): one variant of `_chunk_arrow` (or a
   new fixture) that includes the 5 columns with real values (hydrated-notebook case), and
   the *existing* fixture (columns absent entirely) should be kept and repurposed as an
   explicit unmigrated-notebook regression test once the handler is `.get()`-based. The
   existing `TestGetChunkLicenseTruncation` class (114-223) is the template for the
   assertion style (build via `res`/`_get` fixtures, assert on `r["chunk"][...]` and
   presence/absence of top-level flags) to mirror for the 5 new fields + the
   explicit-null-not-omitted contract (e.g. `assert "source_span" in r["chunk"]` even when
   `r["chunk"]["source_span"] is None`).

7. **The 5 columns' names + types — `ingest/schema.py`** `CHUNKS_SCHEMA_V1` tail
   (221-269, read in full; 511-line file). Exact declarations, all `nullable=True`:
   - `source_revision_id: pa.utf8()` — pointer into the m1 documents registry,
     `f"{work_id}@{arxiv_version}"` or bare `work_id`; NULL = unregistered paper or
     ambiguous (>1) registry match.
   - `source_span: pa.utf8()` — a **JSON string** (deliberately not a struct, so it rides
     the SQL-dict `add_columns` migration unmodified), shape
     `{"rev":<16-hex>,"txt":<64-hex sha256>,"id":<str|"">}`; `txt` is authoritative,
     `rev` a cross-check, `id` a debug hint. NULL = unresolved OR the backfill's
     chunk-id re-derivation didn't reproduce the row (an *abstention*, not silence).
     Live-verified shape on `bridgeland-stability`: `{"id":"","rev":"9e729a...","txt":"95e9c2..."}`.
   - `truncated: pa.bool_()` — persists `ChunkRecord.truncated`; "the ONLY v2 column with
     no legitimate NULL path once hydrated" per the schema's own comment (250-255) — the
     backfill fills 100% of rows on a hydrated notebook.
   - `printed_number: pa.utf8()` — rendered theorem number ("3.1", "A.2"); NULL is
     legitimate/common for non-theorem chunks (kind=section/proof-orphan) or genuinely
     unnumbered theorems, not just an error state.
   - `license_ref: pa.utf8()` — the registry's `license_status` denormalized onto the row
     (`eligible`/`not-allowlisted-open`/`unknown`); **advisory only** (see item 2 above);
     NULL exactly when `source_revision_id` is NULL.

## Acceptance criteria the implementer must meet

1. [AC1] `server/handlers/chunk.py`'s `chunk = {...}` dict literal (99-113) gains 5 keys —
   `source_revision_id`, `source_span`, `truncated`, `printed_number`, `license_ref` —
   each read via `row.get(<col>)` (NOT `row[<col>]`), so a chunk served from an unmigrated
   notebook (`bridgeland-stability-pdfs`, `fourier-duality-pdfs` — live today, 2,831 rows)
   degrades to explicit `null` for all 5 rather than a 500. This is required for
   correctness on the *current* live corpus, not just a future-proofing nicety.
2. [AC1] Every one of the 5 fields is present in the response `chunk` dict on every
   `found: true` response, with JSON `null` (Python `None`) when the underlying column
   value is NULL or absent — never omitted. Add a test asserting key-presence
   (`"source_span" in r["chunk"]`) independent of the value, mirroring the existing
   `TestGetChunkLicenseTruncation` style in `tests/test_handlers_chunk.py`.
3. [AC1] `license_ref` is surfaced as a plain new field and must NOT feed
   `server/license_policy.py::is_open_access` or the existing `license_truncated` branch
   (chunk.py 94-98) — that cutover is explicitly source-truth-m4's scope
   (`plans/source-truth/roadmap.yaml:300-308`), gated on separate owner sign-off.
4. [AC2] `server/tools.py::TOOL_SCHEMA_VERSION` bumps 17→18 with a new dated changelog
   comment (mirroring the v16 entry style, 150-157) stating this is a response-shape-only
   change to `GET_CHUNK`, no description/inputSchema delta.
5. [AC2] Re-pin `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` in
   `tests/test_server_tool_schema.py` via `pytest tests/test_server_tool_schema.py
   --update-tool-schema-hash`, run twice (write, then verify flag-less), consistent with
   AC2's "standalone TOOL_SCHEMA_VERSION re-pin" fallback — confirmed the correct path
   since no `agent-platform` milestone journal exists anywhere in this repo's `.claude/`
   tree to bundle into a W1 window (grepped; only conceptual references in ADRs/handoffs,
   no actual milestone artifacts).
6. [AC2] Confirm (not assume) `tests/test_prompts.py::EXPECTED_BP1_SHA256` (657-664) is
   unaffected by running that test after the change — expected to pass unmodified per the
   v16 precedent, but must be verified empirically since it's a testable claim, not
   inferred.

## Risks and open questions

1. **[Highest severity] The `row[col]` vs `row.get(col)` choice is the whole ballgame.**
   Every existing field in the `chunk` dict literal uses bracket-indexing because every
   pre-v2 column is guaranteed present in both schema versions. The 5 new columns are
   NOT guaranteed present — 2,831 live rows across 2 live, queryable notebooks lack them
   entirely today. If the implementer pattern-matches the existing style (very likely,
   since it's the file's own convention), `get_chunk` breaks in production for those two
   notebooks the moment this ships. This is not called out anywhere in the milestone
   brief, roadmap, or m2's artifacts — it's a genuinely new finding from live-inspecting
   the on-disk tables, not a restatement of a known caveat.
2. **Abstention vs. never-computed collapse to the same `null`.** A hydrated notebook's
   legitimately-abstained `source_span` (backfill ran, couldn't re-anchor; reason codes
   like `chunk_id_not_reproduced` exist in the *offline report* per m2's synthesis) and an
   unmigrated notebook's structurally-absent column both surface as bare JSON `null` under
   the `row.get()` fix in risk 1 — indistinguishable to the calling agent. AC1's literal
   text ("explicit null, not omission") is satisfied either way, but this brushes against
   the CLAUDE.md §4.9 rule against collapsing distinct epistemic states into one token.
   Out of scope to fully resolve in m5 (no schema column carries a reason code today), but
   the implementer should decide explicitly (e.g. a short code-comment acknowledging the
   collapse) rather than silently.
3. **`printed_number`'s NULL is heavily overloaded** (non-theorem chunk, unnumbered
   theorem [F1], OR backfill miss) with no way for `get_chunk` to distinguish which,
   since only the row itself is visible at serving time. Same class of issue as risk 2,
   smaller blast radius since printed_number is expected-null for most chunks by design.
4. **W1/agent-platform fallback is confirmed but worth re-confirming at implementation
   time.** I grepped this repo's entire `.claude/` tree for "agent-platform" and found
   only conceptual references (ADRs, handoffs, roadmap prose) — zero milestone-pipeline
   journal/state.json for it. Since that's a moment-in-time absence check (a sibling
   session could theoretically stand up an agent-platform repo/journal between now and
   implementation), the implementer should re-run the same check rather than trust this
   brief's timestamp.
5. **`.claude/docs/snippet-contract.md` addendum is a convention, not a gate.** m11 added
   a whole subsection (g) documenting its response-shape delta; nothing forces m5 to do
   the same, and the milestone's own ACs don't mention docs. Flagging so the implementer
   makes a deliberate choice (skip vs. add a short section h) rather than an accidental
   omission relative to established precedent.

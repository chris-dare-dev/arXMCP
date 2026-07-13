# Phase 1 synthesis — source-truth-m5

**Mode:** standard, but run as a **single explore brief** — justified: m5 is a focused
serving-surface change, and `brief-1.md` comprehensively covered mechanics AND the §4.9 framing
AND a live landmine (a second design brief would duplicate it). All findings live-verified against
the on-disk tables + `server/` source. `brief-1.md` is the authoritative map.

## The change (small + sensitive)
Surface the 5 m2 columns through `get_chunk`. Purely serving — no ingest, no corpus, no
`license_policy.py`.

- **`server/corpus.py`: NO change** — it does no column projection.
- **`server/handlers/chunk.py`:** the `chunk = {...}` dict literal (~:99-113) gains 5 keys —
  `source_revision_id`, `source_span`, `truncated`, `printed_number`, `license_ref` (alphabetical) —
  **each read via `row.get(<col>)`, NEVER `row[<col>]`**.
- **`server/tools.py`:** bump `TOOL_SCHEMA_VERSION` 17→18 + a v18 changelog entry (GET_CHUNK
  description/inputSchema UNCHANGED — this is a response-shape-only change, exactly the v16 precedent).
- **`tests/test_server_tool_schema.py`:** re-pin via `pytest tests/test_server_tool_schema.py
  --update-tool-schema-hash` (run twice: write, then verify flag-less) → rewrites
  `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`. **Standalone re-pin**
  (W1/agent-platform has NOT materialized — re-confirm at implement time).
- **`tests/test_handlers_chunk.py`:** extend the `_chunk_arrow` fixture with a hydrated variant
  (5 cols present) + keep the current column-absent fixture as an **unmigrated-notebook regression
  test** (asserts `get_chunk` returns explicit null, not a 500/KeyError).

## THE LANDMINE (highest-value finding)
**2 of 4 live notebooks are still on the pre-m2 21-col schema:** `bridgeland-stability-pdfs` (780
rows) + `fourier-duality-pdfs` (2,051 rows) — 2,831 rows, live + queryable today. m2 only hydrated
the 2 HTML notebooks. `chunk.py`'s query has no `.select()`, so its Arrow result **lacks the 5
columns entirely** for those notebooks → `row["source_revision_id"]` would `KeyError` → **500 in
production**. `row.get()` is mandatory, not stylistic. (Full `-pdfs` hydration needs m1 registry +
m2 backfill on those notebooks — a tracked m2-gap fast-follow, NOT m5's scope.)

## Decisions taken (autonomy §12)
1. **`row.get()` for all 5** → explicit null on unmigrated/absent (satisfies AC1 "explicit null, not
   omission" AND fixes the -pdfs 500).
2. **`license_ref` surfaced as a plain new field** carrying the 3-way `license_status`
   (`eligible`/`not-allowlisted-open`/`unknown`) — **advisory only, NOT wired into
   `is_open_access`/`license_truncated`** (that cutover is source-truth-m4, owner-gated). No bare
   "verified" — it's a namespaced, axis-specific value (§4.9 rule 1 satisfied).
3. **§4.9 abstention nuance (acknowledged, not silently collapsed):** a hydrated notebook's
   *abstained* `source_span` (backfill couldn't re-anchor) and an *unmigrated* notebook's
   structurally-absent column both surface as bare `null`. AC1 ("explicit null") is satisfied; the
   finer reason-code distinction is out of m5's scope (no chunk column carries a reason code — the
   reasons live only in m2's offline report). The implementer adds a code comment acknowledging the
   collapse rather than pretending it doesn't exist.
4. **BP1 unaffected:** `EXPECTED_BP1_SHA256` (`tests/test_prompts.py`) hashes only {name,
   description} per tool → the version bump doesn't touch it (v16 precedent). Verify empirically, don't assume.

## Path + acceptance
- **Path: DELEGATED** (small ~150-LOC diff, but the schema-hash re-pin is sensitive — I verify it
  carefully post-implement). No `allow_large_diff` needed.
- **AC1:** all 5 fields present on every `found:true` response, explicit-null when the column is
  NULL/absent (tested for both hydrated + unmigrated notebooks). **AC2:** `TOOL_SCHEMA_VERSION`
  17→18, `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned (standalone), `test_live_tools_match_pinned_hash`
  green, BP1 verified unaffected.
- Optional (convention, not a gate): a short `snippet-contract.md` §h addendum mirroring m11's §g.

## external_writes_required
```yaml
external_writes_required: ["git push origin main"]
```

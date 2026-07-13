# source-truth-m5 — implement + rectify summary

**get_chunk surfaces the 5 source-truth (m2 chunks schema v2) fields.** Ran research
(single explore brief, justified) → implement (inline) → critique (2 opus critics) → rectify (inline).

## Built (feat b92fcc7)
- `server/handlers/chunk.py`: the `chunk = {...}` response dict gains `source_revision_id`,
  `source_span`, `truncated`, `printed_number`, `license_ref` — **each via `row.get()`** (the
  landmine: 2 live `-pdfs` notebooks, 2,831 rows, are still on the pre-m2 21-col schema →
  bracket-indexing would 500; `row.get()` → explicit null, satisfying AC1). `license_ref` is
  ADVISORY (3-way `license_status`), NOT wired into serving (m4 owns that).
- `server/tools.py`: `TOOL_SCHEMA_VERSION` 17→18 + v18 changelog (response-shape only).
- `tests/test_server_tool_schema.py`: `EXPECTED_TOOL_SCHEMA_SHA256` (→`5189d7a6…`) +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` (→18) re-pinned **standalone** (W1/agent-platform not
  materialized). `EXPECTED_BP1_SHA256` verified unaffected (GET_CHUNK description/inputSchema
  byte-identical). `server/corpus.py` untouched (no `.select()` projection).
- `tests/test_handlers_chunk.py`: hydrated fixture + 4 tests (all-5, unmigrated-null landmine,
  abstained-null, license_ref-advisory).

## Critique: C0 H0 M2 L1 (both critics SHIP)
All sensitive parts verified clean: schema-hash re-pin, BP1 stability, `license_ref` advisory,
wire null-survival, §4.9 abstention-collapse acknowledged, `source_span` opaque passthrough.

## Rectify (rect 55238ed) — fixed 3, invalidated 0, deferred 0. Invalidation 0%. Gate OK.
| id | sev | fix |
|----|-----|-----|
| M1 | MED | Wire-level regression guard `test_get_chunk_source_truth_fields_survive_wire` (via `warm_app`/`_call_tool`) — pins the 5 keys' survival past FastMCP `convert_result` (a future `mcp` `exclude_none` bump would else silently drop nullable fields with the handler-dict tests green). |
| M2 | MED | Disambiguating comment at `chunk.truncated` (INGEST-time provenance, NOT served-body completeness — distinct from serving-time `truncated_for_license`/`body_truncated`) + a `snippet-contract.md` §h addendum. Cross-critic (adversary + arxmcp). |
| L1 | LOW | Fixture docstrings reference the schema version, not a literal (wrong) fixture column count. Cross-critic. |

## Deviations (recorded)
- **Single research brief** (not the standard 2): brief-1 comprehensively covered mechanics + §4.9 +
  the live landmine — a second design brief would duplicate it for this focused surface.
- **Inline implement + inline rectify** (trigger-3 suggests delegated rectify when implement was
  inline): both proportionate to a ~122-LOC serving change + ~30-LOC hardening; the implementer
  delegate returned empty (spurious) so implement was done inline.

## Not m5's scope (tracked)
The 2 unmigrated `-pdfs` notebooks (2,831 rows) surface the 5 fields as explicit null. Full
hydration needs m1 registry + m2 backfill run on those notebooks (they're MinerU/PDF, no
`ltx_theorem` markup) — a tracked m2-gap fast-follow.

## External write
- `git push origin main` — the m5 feat + rect + notes. Owner-authorized per-event.

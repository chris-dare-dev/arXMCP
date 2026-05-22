# Critique — verification-feedback-m1

**Critic:** adversary
**Generated:** 2026-05-22T00:00:00Z
**Commit range:** `ead7af9d99cae4f2c5b7561a9e35536a6944eabe..2e30dccc4b89bb2944ea95e3ac3b99a8f3be25fa`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- **SHIP-WITH-FIXES.** The handler wiring is correct on the common path; one HIGH and two MEDIUM findings must be closed first.
- **HIGH (F1):** `depth=3` is accepted by the handler's Pydantic schema (`Field(le=3)`) but the library raises `ValueError("depth must be 1 or 2")`. An agent passing a schema-legal value gets an unhandled exception from inside the handler — a wrong-behavior-on-an-input-path bug. No test covers `depth=3`.
- **MEDIUM (F2):** the `kuzu_path.exists()` graph-absent guard masks a genuinely broken / half-ingested Kùzu DB — a present-but-corrupt directory passes the guard and the Kùzu binder error surfaces as a 5xx, which the docstring claims it prevents.
- **MEDIUM (F3):** no regression test pins the F2 path-validation contract negatively — nothing asserts an agent-supplied `kuzudb_path`/`lancedb_path` JSON key is *rejected* or *ignored*; the contract is only exercised positively.
- The AC4 "met-by-exclusion" call is **sound** — option (b) from the sanctioned challenger is a real correctness equivalence, not a gap.
- D1 (`depth` kept at `le=3`) is the *root cause* of F1; the deviation's rationale ("avoids editing a security test") is itself the defect — see F1.
- Cache byte-stability, MCP envelope shape, local-first, tier-sequencing, and no-fork axes are all clean.
- The schema-hash / BP1 / `TOOL_SCHEMA_VERSION` re-pin triple is correct and properly paired.

## Severity calibration table

| Severity | Meaning | Count |
|---|---|---|
| CRITICAL | data loss / security breach / broken invariant | 0 |
| HIGH | wrong behavior on a common path | 1 |
| MEDIUM | subtle correctness / missing test | 3 |
| LOW | style / docs | 2 |

## Findings

### F1 — `depth=3` passes input validation but crashes inside the handler

**Severity:** HIGH
**Citation:** `server/handlers/citations.py:73` (`depth: Annotated[int, Field(ge=1, le=3, ...)]`) vs `server/graph_queries.py:109-110` (`if depth not in (1, 2): raise ValueError(...)`).

The handler's `depth` Pydantic field is `Field(ge=1, le=3)`. The MCP input
schema therefore advertises `depth=3` as a legal value. But the library's
`_build_query` rejects anything outside `{1,2}` with
`ValueError("depth must be 1 or 2, got 3")`. The flow for `depth=3`:

1. Pydantic validation passes (`3 <= 3`).
2. `is_valid_chunk_id` passes.
3. `kuzu_path.exists()` is true (graph present).
4. `await cite_neighbors(..., depth=3, ...)` is called.
5. `_build_query` raises `ValueError` — uncaught inside `handle_cite_neighbors`.

The research-synthesis §3 explicitly planned to "clamp `depth` validation to
`ge=1, le=2` at the Pydantic boundary ... failing fast at the input boundary
is the MCP-spec input-validation MUST." D1 reverses that decision to avoid
editing `tests/security/test_resource_exhaustion.py::test_cite_neighbors_depth_field_constraint_present`
(which pins `le == 3`). D1's claim — "`depth=3` is rejected by the library's
explicit `ValueError` — an equally clean, fast error" — is **wrong**: a
`ValueError` raised *inside the handler body* is not the same as a Pydantic
`ValidationError` raised *at the input boundary*. The MCP-spec input-validation
MUST means the schema and the accepted-value set must agree; here they do not.
A handler-body `ValueError` is, depending on the dispatch wrapper, either a
500-class internal error or a leaked stack detail — not the clean
`INVALID_PARAMS` an out-of-range numeric input should produce.

The correct fix is the synthesis's original plan: set `Field(le=2)` and update
the security test's pin to `le == 2` in lockstep (the security test exists to
assert a cap is *present*, not that it is specifically 3 — Threat-4's intent is
satisfied identically by `le=2`). Editing one assertion line in a security test
to keep the input schema honest is not "no functional gain"; it closes a real
input-contract mismatch.

This is also untested: `TestHandlerEndToEnd` exercises `depth=1` and `depth=2`
only. No test calls the handler with `depth=3`, so the crash ships silently.

### F2 — graph-absent guard masks a broken / half-ingested Kùzu DB

**Severity:** MEDIUM
**Citation:** `server/handlers/citations.py:96-101` (`if not kuzu_path.exists(): ... graph_status = "absent"`).

The handler's degradation guard is a single `Path.exists()` check on the Kùzu
directory. The handler docstring (lines 24-27) claims this returns
`graph_status="absent"` "rather than letting a Kùzu binder error surface as a
5xx." But `exists()` only distinguishes *absent* from *present-as-a-path*. A
directory that exists but is empty, half-written by an interrupted ingest, or
missing the `papers` node table will pass the `exists()` guard, fall into the
`else` branch, and the `cite_neighbors` library call will raise a Kùzu
`BinderException` / `RuntimeError` on the missing table — exactly the 5xx the
docstring says is prevented. The guard's stated contract ("not letting a binder
error surface") is stronger than what `exists()` delivers.

This is a masking error-handling pattern: the guard makes the *common* clean
case (truly no `kuzu/` directory) graceful, but a corrupt-DB operator failure
mode is silently routed into an opaque crash, and the `graph_status` field
gives a falsely binary "absent/present" signal. At minimum the `else` branch
should wrap the `cite_neighbors` call and, on a Kùzu binder/catalog error,
return `graph_status="absent"` (or a distinct `"unavailable"`) rather than
propagating. No test covers a present-but-empty `kuzu/` directory.

### F3 — F2 path-validation contract has no negative regression test

**Severity:** MEDIUM
**Citation:** `tests/test_proof_chain.py:536-657` (`TestHandlerEndToEnd` — all positive-path tests); `server/handlers/citations.py:93-94`.

AC3 / the E09_S03 F2 contract is the security spine of this milestone: Kùzu and
LanceDB paths MUST be derived from `Config`, never from agent JSON. The
implementation does this correctly — `handle_cite_neighbors` has only
`chunk_id`, `direction`, `depth`, `limit` in its signature, so an agent
*cannot* pass `kuzudb_path`. But the test surface only verifies the contract
*positively* (paths come from the fixture's `Config`). Nothing pins the
contract negatively: there is no test asserting that a `cite_neighbors` tool
call carrying a `kuzudb_path` or `lancedb_path` JSON key is rejected by the
FastMCP input schema (FastMCP rejects unknown args) or otherwise ignored.

The synthesis §5 FM-3 names the guard as "paths come from `get_resources().config`,
asserted in the handler test" — but a positive assertion does not protect
against a future refactor that adds a `kuzudb_path` parameter back to the
handler signature "for testability." A HIGH-severity security contract should
have a dedicated regression test that fails loudly if the path ever becomes
agent-controllable. This is the standard pattern in `tests/security/`.

### F4 — handler `depth` default (1) silently diverges from the library default (2)

**Severity:** MEDIUM
**Citation:** `server/handlers/citations.py:73` (`depth ... = 1`) vs `server/graph_queries.py:305` (`depth: int = 2`) and research-synthesis.md:16/21 (library "accepts 1 or 2", signature default `depth: int = 2`).

The handler defaults `depth=1`; the library defaults `depth=2`. The
proof-chain workflow doc and every library-level test (`TestRound1CiteNeighbors`,
`TestPerfGate`) use `depth=2` as the canonical proof-chain traversal. An agent
that calls `cite_neighbors` *without* specifying `depth` now gets a 1-hop
neighborhood through the MCP tool, but a 2-hop neighborhood if it calls the
library directly (the pattern CLAUDE.md §6 still documents as the live path).
This is a behavior divergence at the boundary the milestone exists to unify.
The synthesis did not call this out and the implementation-summary does not
record it as a deviation. Either the handler default should be `2` to match
the library and the proof-chain doc, or the divergence should be a documented,
reasoned deviation. As shipped it is an undocumented silent change.

### F5 — `depends_on` direction is wired but its data source is not ingested

**Severity:** LOW
**Citation:** `server/tools.py:1001-1006` (CITE_NEIGHBORS description advertises `depends_on`); `server/graph_queries.py:16-19` (depends_on relies on intra-paper `\ref{}` edges).

The re-aligned enum and the new tool description advertise `direction="depends_on"`
as a first-class option ("follows the intra-paper theorem-dependency chain").
`depends_on` depends on `source="intra-paper"` edges produced by
`ingest/intra_paper_refs.py`. For a seed-stage corpus with no graph ingest,
`depends_on` returns empty exactly like the other directions — acceptable. But
the tool description gives an agent no signal that `depends_on` is only
meaningful once intra-paper refs are ingested, while `graph_status="absent"`
covers the whole-graph-missing case, not the partial "graph present but no
intra-paper edges" case. This is a documentation/observability nit, not a
correctness break — hence LOW. Worth a one-line description caveat.

### F6 — implementation-summary D2 defers a known contradictory constitution note

**Severity:** LOW
**Citation:** implementation-summary.md:38 (D2); research-synthesis.md:71 (synthesis §3 decided to "correct the one stale enum line").

The research-synthesis §3 made an explicit decision: correct the stale
`direction` enum in `.claude/notes/06-mcp-server-design.md` because "shipping a
contradictory constitution note is itself a defect." D2 reverses this and
defers it. The deviation is documented and reasoned (scope), so per the brief
it is "not itself a finding" — but the *consequence* is: the design
constitution now contains a `direction` enum (`citers/cited/co_cited/...`) that
contradicts both the shipped library and the shipped handler. A future agent
reading `06-mcp-server-design.md` as authoritative will reintroduce the dead
enum. The synthesis explicitly judged this a defect; deferring it leaves a live
documentation landmine. LOW because it is docs-only and the library/handler are
the de-facto authority, but it should be tracked, not silently dropped.

## What was done well

- The stub removal is complete and clean: `infrastructure_status:"deferred"` and the `note` key are fully gone (AC1), not left as dead branches.
- The `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` / `TOOL_SCHEMA_VERSION` triple is re-pinned consistently (9→10 everywhere), and the version-anchor guard's intent is preserved.
- D4 — catching the `EXPECTED_BP1_SHA256` drift and re-pinning it in the same change — is exactly the paired byte-stability discipline `.claude/notes/07-multi-agent-caching.md` mandates; the synthesis missed it and the implementer caught it via the full-suite run.
- The F2 path-validation contract is implemented correctly: the handler signature exposes only `chunk_id/direction/depth/limit`; both paths are derived from `get_resources().config`. The HIGH E09_S03 F2 risk is genuinely closed at the code level.
- `neighbors` list order is preserved — the library's `(hop_distance, paper_id)` ordering is not re-sorted; `_sort_dict` correctly sorts dict keys only (verified at `server/tools.py:411-427`). No cache byte-stability regression.
- `dataclasses.asdict()` is the correct serialization for the frozen `CitationNeighbor` dataclass; `set(n) >= {...}` in the test pins all six fields.
- The `chunk_id` Threat-1 regex validation correctly runs *first*, before `get_resources()`, so the validator fires regardless of resource state — matching the documented forward-compat contract.
- The AC4 "met-by-exclusion" reasoning is genuinely sound: with no cache, there are no stale entries by construction; option (b) is the sanctioned challenger choice, not a hand-wave.
- `TestHandlerEndToEnd` exercises the real handler boundary (`handle_cite_neighbors`), not just the library, and the 500ms gate is measured at the handler level including `envelope` + `_cap` + `asdict` — AC5 met as specified.
- The graph-absent test (`test_handler_graph_absent_returns_empty`) does exist and exercises the degradation path for the truly-missing case.

## Recommended rectification order

1. **F1 (HIGH)** — change `Field(le=3)` to `Field(le=2)` in `handle_cite_neighbors`; update `test_resource_exhaustion.py::test_cite_neighbors_depth_field_constraint_present` to pin `le == 2` and the `ADVERSARIAL_DEPTH` test still passes; add a `depth=3`-rejected handler test.
2. **F2 (MEDIUM)** — wrap the `cite_neighbors` call in the `else` branch to catch Kùzu binder/catalog errors and degrade to `graph_status` accordingly; add a present-but-empty `kuzu/` directory test.
3. **F3 (MEDIUM)** — add a negative regression test asserting a `cite_neighbors` call with a `kuzudb_path`/`lancedb_path` JSON arg is rejected/ignored.
4. **F4 (MEDIUM)** — set handler `depth` default to `2` to match the library and proof-chain doc, or record the divergence as an explicit deviation.
5. **F5 (LOW)** — add a one-line `depends_on` caveat to the CITE_NEIGHBORS description.
6. **F6 (LOW)** — file or carry the `06-mcp-server-design.md` stale-enum correction as a tracked follow-up.

## Rectification status

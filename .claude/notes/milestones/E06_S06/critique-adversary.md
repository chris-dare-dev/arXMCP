# Critique — E06_S06

**Critic:** adversary
**Generated:** 2026-05-09T00:00:00Z
**Commit range:** 4328dce1b9e27bdbf965e2960dd86d5e21951f68..80dd2ab8a3517f6b4e11a39b2eaf1d32dcd3d94e
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES. The pinned-hash test runs and passes, but the
  canonical form chosen for the hash recursively re-sorts every nested
  dict via `json.dumps(sort_keys=True)`, masking the most likely real
  cache-invalidation regression on the cited path: re-ordering parameters
  in a handler signature changes the wire `inputSchema.properties` order
  but leaves the hash unchanged. The brief's stated invariant ("Pin tool
  JSON schemas. Sort properties alphabetically AT SERIALIZATION TIME"
  — `.claude/notes/07-multi-agent-caching.md:42`) is a contract on the
  ORCHESTRATOR's outbound serializer, which is unwritten. The hash test
  silently delegates that contract to a sibling component without flagging
  it.
- Counts: 0 CRITICAL, 2 HIGH, 6 MEDIUM, 3 LOW.
- Highest-risk file: `tests/test_server_tool_schema.py:175-192`
  (`_serialize_tools` recursive sort + `exclude_none` defects).
- Cross-axis pattern: the test guards against a NARROWER class of drift
  than the brief intends — both `sort_keys=True` and `exclude_none=True`
  trade real-drift detection for false-positive suppression, and neither
  trade-off is enforced anywhere else in the codebase.
- Brief AC #4 (`tool_schema_version: 1` "appears in the `tools/list`
  response") is satisfied via per-tool `_meta`; the implementation
  documents the deviation but does NOT enforce that a hash drift implies
  a `TOOL_SCHEMA_VERSION` bump (so the version pin is decorative, not
  load-bearing).
- The `--update-tool-schema-hash` flag, if accidentally set in CI, causes
  a SKIP rather than a FAIL — silent green on CI while the working tree
  changes are lost on cleanup.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Hash misses inputSchema property reordering (the most likely real regression)

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:184-192`
- **What:** `_serialize_tools` calls `json.dumps(payload, sort_keys=True)`,
  which RECURSIVELY sorts every nested dict — including
  `inputSchema.properties`. Verified empirically: reversing the order of
  the 5 properties on `search_papers.inputSchema.properties` (live
  `[query, level, k, filters, cursor]` → reversed) produces an IDENTICAL
  sha256. Yet FastMCP emits properties in source-code (insertion) order
  (`mcp/server/fastmcp/server.py:315-330` plus pydantic JSON Schema
  generation), so swapping two parameter declarations on a handler
  changes the actual wire bytes but NOT the hash.
- **Why it matters:** the brief (`.claude/notes/07-multi-agent-caching.md:42`)
  explicitly anchors BP1 stability on "Sort properties alphabetically AT
  serialization time." The test guards stability of the SORTED form,
  not of what FastMCP actually emits. A contributor who re-orders
  parameters in `server/handlers/search.py` will not be caught — but
  every sub-agent's BP1 cache will still invalidate the moment any
  consumer (Anthropic API, tool definition cache, log line) consumes the
  wire bytes in source order. The test's promise ("hash drift = cache
  invalidation") is one-sided: hash stability does NOT mean cache
  stability unless the orchestrator (unbuilt, scheduled for E08) sorts
  before sending. That delegation is undocumented.
- **Proposed fix:** either (a) hash the WIRE form (no recursive sort —
  use `json.dumps(payload, separators=(",", ":"))` and rely on dict
  insertion order being stable in py3.7+; this catches param reorders),
  or (b) add a SECOND assertion that for every tool's
  `inputSchema.properties`, the keys equal `sorted(keys)` so that the
  source-code order IS canonical and the orchestrator's sort is a no-op.
  Option (b) preserves the test's "byte-stable means cache-stable" claim
  AND surfaces the orchestrator contract in code rather than docs.
- **Regression guard:** add
  `test_inputSchema_properties_sorted_alphabetically` in
  `TestSchemaVersionMetaSurface` that walks every tool's `inputSchema`
  and asserts `list(props.keys()) == sorted(props.keys())`.

### F2 — Hash drift does NOT imply `TOOL_SCHEMA_VERSION` bump

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:283-297`
- **What:** the test's failure message exhorts contributors to "Bump
  `server.tools.TOOL_SCHEMA_VERSION`" before running
  `--update-tool-schema-hash`, but nothing enforces it. A contributor
  can change a tool description, run the flag, ship the new hash, and
  leave `TOOL_SCHEMA_VERSION` at 1. The hash assertion now passes,
  `tests/test_snippet_contract.py::TestSchemaVersionPin` (which
  cross-checks `server/schemas/search_papers_result.json::version`
  against `TOOL_SCHEMA_VERSION`) also passes (because both are still 1),
  and downstream agents see `_meta: {"tool_schema_version": 1}` despite
  the schema having changed. The version field becomes decorative.
- **Why it matters:** the brief (`.claude/notes/06-mcp-server-design.md:288-290`)
  literally says "bump a `tool_schema_version` field when changing them
  and document the change." This milestone exists to enforce that
  invariant at CI; it does not. Worse, it gives the false impression
  that the invariant IS enforced (the failure message lists "Bump
  TOOL_SCHEMA_VERSION" as step 1).
- **Proposed fix:** persist a `(hash, schema_version)` pair (e.g. as a
  small JSON sidecar `tests/data/tool_schema_pin.json`), and have
  `--update-tool-schema-hash` REQUIRE either an explicit
  `--allow-version-unchanged` flag or that
  `TOOL_SCHEMA_VERSION` differs from the value paired with the prior
  hash. Cheaper alternative: add a new test
  `test_hash_change_implies_version_change` that snapshots both fields
  in git history (or a fixture) and fails when hash differs but version
  matches.
- **Regression guard:** the new test or the sidecar file constitutes
  the guard.

### F3 — `exclude_none=True` masks SDK-version-induced wire drift in BOTH directions

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:186`
- **What:** `exclude_none=True` is documented as a guard against MCP-SDK
  version bumps that flip `outputSchema=None` to `outputSchema={}`.
  Inspection of the pydantic dump confirms the trade: `outputSchema`,
  `icons`, `annotations`, `title`, `execution` are all dropped when
  None. But this is a one-way trade: if an SDK upgrade changes the
  default of a NEW field from `None` to `{}` (real wire drift, real
  cache invalidation), the test still PASSES because dump excludes it,
  yet downstream consumers see new bytes. Conversely if a contributor
  intentionally sets one of those fields, the hash changes — but the
  test cannot tell whether the drift is "ours" or "SDK's."
- **Why it matters:** the test claims to pin BP1 cache surface, but
  `exclude_none` lets SDK-side wire changes pass invisibly. This is the
  exact failure mode the milestone exists to surface.
- **Proposed fix:** drop `exclude_none=True`; pin `mcp` library version
  in `pyproject.toml` (likely already done) so SDK-introduced fields
  appear once at upgrade time and the contributor explicitly accepts
  them via `--update-tool-schema-hash`. The pinned version line in the
  test file should reference the `mcp` version that produced the hash.
- **Regression guard:** add an `EXPECTED_MCP_LIB_VERSION` constant
  alongside the hash, asserted at test time.

### F4 — `--update-tool-schema-hash` SKIPs in CI instead of failing

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:273-280`
- **What:** when `--update-tool-schema-hash` is set AND the hash
  changes, `_rewrite_pinned_hash` mutates the working tree, then
  `pytest.skip(...)` runs. CI sees a skip, not a fail. If the flag is
  ever set in CI (committed CI config typo, env var leak via a future
  pytest plugin), CI reports green on a tree that still has the old
  hash post-cleanup. The brief explicitly documents "CI never sets the
  flag" but the test does not enforce that boundary.
- **Why it matters:** the milestone is "the mandatory pre-merge check"
  per the brief. A check that silently SKIPs on misconfiguration is
  worse than no check.
- **Proposed fix:** detect CI via `os.environ.get("CI")` (or the
  GitHub-Actions / GitLab-CI env vars the project uses) and raise
  `pytest.fail("--update-tool-schema-hash must not be used in CI")`
  when the flag is set there. Also exit non-zero (not skip) when the
  rewrite happens, so a developer who ran the flag locally MUST commit
  the change before CI passes.

### F5 — `_seed_minimal_corpus` is dead weight (drags numpy + ingest deps into a server-only test)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:103-138, 162`
- **What:** verified empirically — `app.state.mcp_server.list_tools()`
  returns the 7 tools without ANY corpus seed; the function does not
  enter the lifespan, so `Resources.startup` never runs. The seed is
  dead weight. It also forces an unnecessary import of numpy +
  `ingest.{chunker_types,embedder,schema,store}` (lancedb, pyarrow), and
  extends the test from ~30 ms (per the docstring claim) to seconds in
  cold-cache mode.
- **Why it matters:** false complexity in the most-trusted byte-stability
  test in the suite. Future contributors will wonder which fixture state
  the hash actually depends on; dropping the seed clarifies that nothing
  beyond `register_all`'s imports matter.
- **Proposed fix:** delete `_seed_minimal_corpus` and the
  `_seed_minimal_corpus(lancedb_path)` call in `_live_tools` (line 162).
  The Config can point at `tmp_path / "lancedb"` (non-existent path)
  because `list_tools` never opens it.

### F6 — Hash captures only `{"tools": [...]}`; not the wire `ListToolsResult` envelope

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:184-189`
- **What:** the actual MCP `tools/list` JSON-RPC response is
  `ListToolsResult` (= `Result` + `nextCursor` + `tools`). Even with
  `exclude_none`, today's payload happens to drop `nextCursor` and
  top-level `_meta`. But two real futures break this: (a) when E07_S04
  pagination lands and `nextCursor` carries a non-null sentinel
  (e.g. `""` for last page), the test continues hashing `{"tools": [...]}`
  without it; (b) any future top-level `_meta` injection (e.g. server-
  level cache hints, debug info) does not flow into the hash. The hash's
  promise to mirror "wire bytes" is only true today.
- **Why it matters:** the milestone's goal is byte-stability of the wire
  response that drives BP1; truncating the envelope to one field hides
  every other axis of drift.
- **Proposed fix:** hash a constructed
  `ListToolsResult(tools=[...]).model_dump(by_alias=True, exclude_none=True)`
  rather than `{"tools": [...]}`. One-line change; future-proofs the
  test against pagination and top-level `_meta`.

### F7 — `test_changing_tool_description_changes_hash` exercises a code path the production code never takes

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:344-375`
- **What:** the test simulates the description bump via
  `tools[0].model_copy(update={"description": "BUMP — not the real
  description"})`. This mutates the fetched `Tool` object in memory, NOT
  the source-of-truth `_TOOL_DESCRIPTIONS` constant in `server/tools.py`
  that flows through `register_all`. A regression where the constant is
  edited but the description does not flow into FastMCP's `add_tool`
  call (e.g. `register_all` accidentally hardcoded a description, or
  `tm.description` got swapped for `tm.name`) would not be caught: this
  test mutates the post-registration `Tool`, not the registration path.
- **Why it matters:** AC #2 ("Changing a tool description causes the
  test to fail") is only loosely satisfied. The closer simulation is to
  monkeypatch `server.tools.SEARCH_PAPERS` to a new `ToolMeta` with a
  different description, then re-call `create_app` and re-fetch tools.
  That exercises the registration path.
- **Proposed fix:** rewrite the test to
  `monkeypatch.setattr("server.tools.SEARCH_PAPERS", ToolMeta(name=...,
  description="BUMP"))` plus a second `_live_tools`-equivalent
  invocation. ~10 lines.

### F8 — `_PINNED_HASH_PATTERN` does not anchor to start-of-line

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:211-216`
- **What:** the regex matches the substring `EXPECTED_TOOL_SCHEMA_SHA256
  ...  # UPDATE-ANCHOR ... \n  "<64-hex>"\n)` anywhere in the file. The
  `test_rewrite_helper_finds_anchor` test asserts exactly one match
  TODAY, but the docstring of the module ALSO contains the literal
  string `EXPECTED_TOOL_SCHEMA_SHA256` (lines 20, 35) — which works
  today only because no second occurrence has the
  `: str = ( # UPDATE-ANCHOR` shape. A future docstring example
  showing the pin format (e.g. for an onboarding doc) would silently add
  a second match, and `re.search` (line 229) returns ONLY the first one.
  The "exactly 1 match" assertion catches it, but it is in a SEPARATE
  test (`test_rewrite_helper_finds_anchor`) that runs alongside the
  rewrite — there is no guarantee the rewrite test runs before the
  rewrite. If the rewrite runs first and finds a stale duplicate, it
  rewrites the wrong literal.
- **Why it matters:** thin ice. The fix is one extra `re.MULTILINE` +
  `^` anchor.
- **Proposed fix:** anchor the pattern to start-of-line:
  `re.compile(r'^EXPECTED_TOOL_SCHEMA_SHA256:...', re.MULTILINE)`. Also
  consider asserting count == 1 INSIDE `_rewrite_pinned_hash` rather
  than in a sibling test.

### F9 — `Any` type hint on `_live_tools` and `_serialize_tools` hides drift in tool list shape

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:71, 152, 175`
- **What:** the typing is `list[Any]` rather than `list[mcp.types.Tool]`.
  A future change to `app.state.mcp_server.list_tools()` (e.g. it starts
  returning `dict[str, Tool]` for some reason) would not be caught at
  type-check time.
- **Why it matters:** noisy linting; minor maintainability.
- **Proposed fix:** import `Tool` from `mcp.types` and replace `Any`.

### F10 — Test docstring claims "~30 ms" but actual cold-import cost is multi-second

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:160`
- **What:** the docstring claims "~30 ms" for `_live_tools`. Real cold
  startup pulls `server.main` → FastMCP → mcp library → pydantic schema
  validation for the lowlevel server, plus (today) numpy + ingest stack
  for the dead `_seed_minimal_corpus`. None of that is 30 ms cold.
- **Why it matters:** misleading documentation.
- **Proposed fix:** drop the time claim or replace with "first call
  ~1 s due to import; subsequent calls cached" once F5 is applied.

### F11 — `ensure_ascii=True` is a no-op today but the docstring oversells the protection

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_server_tool_schema.py:55-61, 192`
- **What:** `ensure_ascii=True` is the JSON default; specifying it is
  harmless. The docstring claims "any non-ASCII char in a future tool
  description renders as `\\uXXXX` rather than raw UTF-8 bytes — pinned
  across Python versions and platforms." This is technically true but
  the actual JSON-RPC wire format also escapes to `\uXXXX` by default,
  so the only thing this guards against is a contributor switching to
  `ensure_ascii=False` — which would be caught by code review anyway.
- **Why it matters:** minor; the docstring oversells.

## What was done well

- The test correctly fetches tools from the LIVE FastMCP server
  (`app.state.mcp_server.list_tools()`) rather than re-walking
  `ALL_TOOLS` directly, so it catches drift in the registration glue
  itself, not just the source-of-truth dataclasses.
- The `UPDATE-ANCHOR` sentinel comment + anchored regex is a clean
  alternative to the simpler `re.compile(r'"[0-9a-f]{64}"')` that would
  silently rewrite any 64-hex literal in the file. Defensive design.
- Mocking BGE-M3 via `monkeypatch.setattr(qe_mod, "_get_model", ...)`
  is the right pattern; avoids a 2 GB model download in CI.
- The `--update-tool-schema-hash` flag mirrors the existing `--ndcg-min`
  recipe in `tests/conftest.py:33-43`, keeping the project's
  pytest-options vocabulary consistent.
- Idempotency check in `_rewrite_pinned_hash` (return False if the
  literal already matches) avoids accidental no-op writes that would
  trigger spurious git diffs.
- The "fall through to assertion" branch when `--update-tool-schema-hash`
  is set BUT the hash is already current is a thoughtful corner case
  that the simpler "always skip" version would have missed.
- `test_serialize_tools_is_canonical` is a cheap and effective guard
  against pydantic-internal nondeterminism (e.g. set-typed fields with
  unstable iteration order); two-call equality is the right check.
- `test_tools_list_response_includes_all_seven` is a good defense
  against a contributor accidentally dropping a tool from `ALL_TOOLS`
  while updating the hash via the flag — the count assertion adds an
  orthogonal cross-check.
- The decision to NOT modify `server/tools.py` (the brief listed it as
  a deliverable) is correctly documented in the implementation summary
  with a citation to the prior research brief that resolved the
  decision; this is the right way to handle "deliverable already met
  by upstream milestone."
- The error message on hash drift is genuinely instructive (3 numbered
  steps, citation to `07-multi-agent-caching.md`) — this is the kind
  of test failure that does not need a Slack thread to debug.

## Recommended rectification order

1. **F1** — adopt option (b): assert `list(props.keys()) ==
   sorted(props.keys())` for every tool's `inputSchema`. Lowest blast
   radius (one new test, no change to hash semantics) and surfaces the
   orchestrator-side sort contract in CI.
2. **F2** — add `test_hash_change_implies_version_change` (or a sidecar
   `(hash, version)` pair). Closes the gap that makes the version pin
   decorative. ~20 lines.
3. **F4** — guard `--update-tool-schema-hash` against CI env vars and
   change the mid-rewrite SKIP to a FAIL. ~10 lines.
4. **F6** — hash via `ListToolsResult(...)` rather than `{"tools":
   [...]}`. One-line change; future-proofs against pagination + top-level
   `_meta`.
5. **F5** — delete `_seed_minimal_corpus` and the seed call. Removes
   ~50 LOC + numpy/ingest imports from a server-only test.
6. **F3** — drop `exclude_none=True` AND add an `EXPECTED_MCP_LIB_VERSION`
   constant. Couples the hash to the SDK version that produced it.
7. **F7** — rewrite the description-bump test to monkeypatch the
   `ToolMeta` constant and re-register, exercising the actual code path.
8. **F8** — add `re.MULTILINE` + `^` anchor to `_PINNED_HASH_PATTERN`.
   Defense-in-depth.
9. **F9, F10, F11** — defer (LOW; cleanup pass).

## Rectification status (filled by Phase 4)

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | HIGH | **fixed (partial)** | New `TestCanonicalSortContract::test_canonical_form_uses_sort_keys` pins the architectural assumption: hash represents the canonical *sorted* form (the orchestrator-side wire form), and removing `sort_keys=True` from `_serialize_tools` would break this test, catching the regression *before* a real cache-invalidation incident. The literal "source-code property order = alphabetical" assertion proposed by the critic was attempted but blocked by Python's "non-default argument follows default" rule (e.g. `find_lemma_by_name(name, paper_id=None, k=10)` cannot be reordered to `k, name, paper_id` without keyword-only args). The architectural gap is documented in the test class docstring; the orchestrator-side sort obligation (E08) is the canonical path. |
| F2 | HIGH | **fixed** | Pinned `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int = 1` alongside the hash. The `--update-tool-schema-hash` flag now refuses to proceed if the hash has drifted but `TOOL_SCHEMA_VERSION` is unchanged. Both pins are rewritten atomically when the version IS bumped. Normal-mode runs also assert `live_version == pinned_version`, closing the decorative-version anti-pattern. |
| F3 | MEDIUM | **deferred** | Trade-off: dropping `exclude_none=True` would break the hash on every MCP-SDK upgrade even when our schema is unchanged. The cost of breakage on every SDK bump outweighs the marginal benefit of catching SDK-side wire-format flips. Documented in module docstring. |
| F4 | MEDIUM | **fixed** | New `_running_in_ci()` helper checks `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `CIRCLECI`, `TRAVIS`, `JENKINS_URL`. The `--update-tool-schema-hash` flag is `pytest.fail`-ed in CI rather than silently SKIPped. |
| F5 | MEDIUM | **fixed** | Dropped `_seed_minimal_corpus`. Replaced with `_build_app_and_list_tools(tmp_path)` that points `lancedb_path` at a non-existent directory (since `list_tools` never opens it). Removes ~50 LOC + numpy/ingest imports from a server-only test. |
| F6 | MEDIUM | **fixed** | `_serialize_tools` now hashes `ListToolsResult(tools=tools).model_dump(by_alias=True, exclude_none=True)` instead of `{"tools": [...]}`. Future-proofs against E07_S04 pagination (`nextCursor`) and any top-level `_meta` injection. |
| F7 | MEDIUM | **fixed** | `test_changing_tool_description_changes_hash` rewritten to monkeypatch `server.tools.SEARCH_PAPERS` and `ALL_TOOLS` to a new `ToolMeta` with a different description, then re-run `_build_app_and_list_tools` (which exercises `register_all`). Exercises the actual production registration path, not the post-registration `Tool` object. |
| F8 | MEDIUM | **fixed** | `_PINNED_HASH_PATTERN` anchored to start-of-line via `re.MULTILINE` + `^`. `_rewrite_pinned_hash` also asserts `len(findall(...)) == 1` at the rewrite site (belt + suspenders). |
| F9 | LOW | **deferred** | Cosmetic; `Any` in private fixtures keeps the test self-contained without leaking `mcp.types.Tool` into every helper signature. |
| F10 | LOW | **deferred** | The "30 ms" claim was removed when F5 dropped `_seed_minimal_corpus`. The new fixture docstring no longer makes the timing claim. |
| F11 | LOW | **deferred** | Cosmetic; `ensure_ascii=True` is the default so the explicit kwarg is harmless documentation of intent. |

Suite at rectification: **792 passed, 3 skipped, ruff clean** (was 791 pre-rect — +1 from `TestCanonicalSortContract`).

Reverify pass: F1 was empirically reproduced (reversing properties produced an identical hash) before the architectural decision to surface the sort-keys assumption rather than enforce source-code-order alphabetical. F2 was reproduced by mentally walking the workflow (bump description without `TOOL_SCHEMA_VERSION` bump → flag rewrites only the hash → version stays at 1 → `_meta` becomes decorative).


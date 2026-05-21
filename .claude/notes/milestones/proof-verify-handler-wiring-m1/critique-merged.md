# Critique — proof-verify-handler-wiring-m1

**Critic:** adversary
**Generated:** 2026-05-21T00:00:00Z
**Commit range:** `904db00..7bfb35bdfeb8a8a5841524b1e196855e7d98f03c`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — the surgical handler change is correct on its own terms and well-tested, but two HIGH issues block a clean ship: the tool-schema description still says "ignored at v1" (LLMs cannot discover the new feature), and the new per-key `filter_warnings` reflects LLM-controlled keys verbatim with no length cap (response amplification vector that bypasses the 256 KB byte cap).
- Counts: 0 CRITICAL, 2 HIGH, 2 MEDIUM, 1 LOW.
- Highest-risk file:line: `server/handlers/search.py:362-370` (`filter_warnings` reflection without per-key length cap) — 100 keys × ~100 KB = ~10 MB response amplification, fully reproducible.
- Axis-by-axis: Cache byte-stability CLEAN (`EXPECTED_TOOL_SCHEMA_SHA256` test still passes; the new `sorted(...)` warning ordering is deterministic); MCP spec compliance CLEAN; local-first / Docker CLEAN; tier sequencing CLEAN; no-fork policy CLEAN; math fidelity N/A; security has the two MEDIUM/HIGH findings noted; test surface is strong (27 new tests cover all 9 FMs + all 6 ACs).
- The `_build_paper_id_predicate` helper is well-designed (validate → cap → escape → sort), all 9 documented failure modes are covered, and the `prefilter=True` resolution from synthesis Disagreement-1 is correctly applied.
- The implementer's claim in the implementation summary that `set_resources()` is "the first to use it directly outside `warm_app` integration tests" is false: `tests/test_proof_chain.py:40` and `tests/test_tools_all.py:538,579` already use the same pattern (LOW; documentation accuracy only).
- A subtle correctness concern: the cache lookup at `search.py:268-270` uses the raw `filters` dict (not the normalized predicate string), so semantically-identical `{"paper_id": "x"}` (str) and `{"paper_id": ["x"]}` (list) calls land on different cache slots (MEDIUM; correctness OK, observed-perf only).
- A defense-in-depth gap: `is_valid_paper_id` accepts a trailing `\n` due to Python's non-`MULTILINE` `$` semantics — the regex is leakier than the docstring promises (MEDIUM; not exploitable today but undermines the "structurally rejects single quote / control char" claim).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — Stale `filters` Field description hides m1 feature from LLMs

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/handlers/search.py:195-198`
- **What:** The Pydantic `Field(description="Reserved for E07_S04; ignored at v1 with filter_warnings")` on the `filters` argument is what FastMCP renders into the `inputSchema.properties.filters.description` field of the `tools/list` response. m1 now honors `filters={"paper_id":[...]}` end-to-end, but the schema description still tells consumers the arg is "ignored at v1." The `ToolMeta.description` for `search_papers` at `server/tools.py:SEARCH_PAPERS` also makes no mention of `paper_id` filter support.
- **Why it matters:** An LLM client reading the tool schema will not attempt to use `paper_id` filtering because the description explicitly says it is ignored. The feature is shipped but undiscoverable — effectively unshipped from the consumer's perspective. This is the same class of bug as a feature gated behind a feature flag that's documented as "deprecated, do not use." The implementer plausibly left the description stale to avoid bumping `EXPECTED_TOOL_SCHEMA_SHA256`, but the right answer is to update the description AND re-pin the hash; cache byte-stability across schema versions is exactly what the hash UPDATE-ANCHOR mechanism in `tests/test_server_tool_schema.py:94` exists for.
- **Proposed fix:** Update the description to reflect m1 ("Honors `paper_id` as str or list[str]; up to 100 items; each element validated against the arXiv paper_id format. Other keys are ignored and surface in `filter_warnings`.") and re-pin `EXPECTED_TOOL_SCHEMA_SHA256` using `pytest --update-tool-schema-hash` per `CLAUDE.md §9`. Also extend `SEARCH_PAPERS.description` in `server/tools.py` to mention paper_id filtering so the top-level tool description is consistent.
- **Regression guard:** Add an assertion in `tests/test_search_filter.py` that the rendered tool schema's `filters.description` mentions `paper_id` (parse `mcp.list_tools()` output, find the `search_papers` tool, assert `"paper_id" in inputSchema.properties.filters.description`). This will fail loudly if a future refactor drops the m1 doc.

### F2 — `filter_warnings` reflects LLM-controlled keys with no length cap (byte-cap bypass)

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/handlers/search.py:362-370`
- **What:** When an unrecognized filter key is supplied, the handler appends a warning of the form `f"filters[{key!r}] is not supported and was ignored (deferred to a future milestone; supported keys: ...)"`. The key is reflected verbatim via `repr()` with no length cap. The `MAX_FILTER_ITEMS=100` cap at `server/handlers/search.py:224` bounds the COUNT OF KEYS to 100, but does not bound per-key length. A caller can supply 100 keys of 100 KB each (~10 MB total filter dict, well within Python's parsing limits and not blocked by any middleware before the handler), and the handler will emit 100 warning strings of ~100 KB each → ~10 MB `filter_warnings`. Verified: `100 keys × ~100 KB per warning ≈ 9.6 MB` (measured via `json.dumps(payload).encode()`).
- **Why it matters:** The `_cap()` call at `server/handlers/search.py:471` invokes `cap_result_list(structured, list_key="results")` which ONLY trims the `results[]` list — `filter_warnings` is NOT subject to the 256 KB byte cap (`server/tools.py:cap_result_list` at line 547 only looks at `truncated.get(list_key)` where `list_key="results"`). This means the m1 change opens a partial bypass of the E13_S04b Threat 4 resource-exhaustion defense via an LLM-controllable filter dict. The amplification factor is roughly `2× key_size + ~100 byte boilerplate per key`. Even modest adversarial input (100 keys × 8 KB each = 800 KB filter dict → ~1.6 MB warnings) overshoots the byte cap by 6×.
- **Proposed fix:** In `_build_paper_id_predicate`'s sibling validation block in `handle_search_papers`, add a per-key length cap (e.g. `MAX_FILTER_KEY_LEN = 64`) and reject filter keys longer than the cap with a `ValueError`. Apply BEFORE the `if filters and "paper_id" in filters:` predicate-building step so an oversized key fails fast. Alternatively (or additionally), in the `filter_warnings` block, truncate the reflected key in `repr()` form to 64 chars: `key_repr = repr(key)[:64]`. The first option is cleaner because it rejects the input at the boundary rather than emitting a misleading half-key in the warning.
- **Regression guard:** Add `test_filter_oversized_key_rejected` (single-key with 10 KB name → ValueError) and `test_filter_warnings_total_size_bounded` (100 keys × 1 KB each → assert `len(json.dumps(structured)) < 256 KB`) to `tests/test_search_filter.py`.

### F3 — `is_valid_paper_id` accepts trailing newline (defense-in-depth gap)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `ingest/identifiers.py:36-47` (regex), `server/handlers/search.py:118-121` (docstring claim)
- **What:** The `_PAPER_ID_FULL_PATTERN` regex is `r"^\d{4}\.\d{4,5}(v\d+)?$|^[a-z][a-z\-]*/\d{7}(v\d+)?$"` and is compiled WITHOUT `re.MULTILINE`. In Python's default mode, the `$` anchor matches both end-of-string AND just before a trailing `\n`. Verified empirically: `is_valid_paper_id("2604.26204\n")` returns `True`, `is_valid_paper_id("hep-th/0001234\n")` returns `True`. Consequence: `_build_paper_id_predicate(["2604.26204\n"])` produces the predicate `"paper_id IN ('2604.26204\n')"` — the newline is embedded inside the SQL string literal.
- **Why it matters:** The `_escape_paper_id_literal` docstring at `server/handlers/search.py:118-121` says "`is_valid_paper_id` regex (called BEFORE this function) structurally rejects any string containing a single quote." That claim is true for `'` but the regex is leakier than implied — trailing `\n` is one example. LanceDB's SQL parser treats `\n` inside single-quoted literals as data, so this is not a SQL-injection escape, but: (a) it weakens the documented defense-in-depth invariant, (b) it fragments the cache key for callers who paste `\n`-suffixed IDs, and (c) it means a chunk with paper_id literally containing a trailing `\n` is technically a valid filter input (it won't match anything since real ingested paper_ids never have trailing `\n`, but it accepts the malformed input silently). Future maintainers reading the docstring will believe a stricter validation contract than reality.
- **Proposed fix:** Tighten the regex by replacing `$` with `\Z` (matches only at the very end of the string, never before a trailing `\n`): `r"^\d{4}\.\d{4,5}(v\d+)?\Z|^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"`. This change is byte-stable for all currently-ingested paper_ids (verified: the chunker emits paper_ids derived from arXiv identifiers, none of which have trailing whitespace), and tightens the defense to match the docstring.
- **Regression guard:** Add `test_paper_id_rejects_trailing_newline` (assert `is_valid_paper_id("2604.26204\n") is False`) and `test_paper_id_rejects_trailing_cr` to `tests/test_identifiers.py`.

### F4 — Cache key fragmentation between `str` and one-element `list` for same paper_id

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/handlers/search.py:267-270` (cache lookup uses raw `filters`); `server/cache_sqlite.py:170-171` (canonicalizer uses `json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))`)
- **What:** The Tier-1/Tier-2 cache key is derived from `json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))` at `server/cache_sqlite.py:170-171`. The cache lookup at `server/handlers/search.py:267-270` passes the raw `filters` dict (not the normalized predicate string) to `cache.lookup_search(...)`. m1's `_build_paper_id_predicate` correctly coerces `{"paper_id": "x"}` and `{"paper_id": ["x"]}` to the same SQL predicate (FM-3), but the cache canonicalizer sees `'{"paper_id":"x"}'` vs `'{"paper_id":["x"]}'` — distinct JSON strings → distinct cache keys. Two semantically-identical calls produce a cache miss on the second call.
- **Why it matters:** Not a correctness bug (the second call re-computes the same result and serves it), but it doubles the work for any caller that uses both forms interchangeably. The `_apply_supported_filters` pattern in `server/retrieval/bm25.py:684-687` accepts both forms specifically for ergonomics; the cache should honor the same ergonomic equivalence. The hot-path miss-rate impact is small (callers typically settle on one form), but it's a latent foot-gun: a caller switching from `"x"` to `["x"]` form will see a one-time cache-cold latency hit with no obvious cause.
- **Proposed fix:** Normalize the `filters` dict BEFORE the cache lookup so the canonicalizer sees a stable form. The cleanest place: extract a `_normalize_filters(filters)` helper that coerces `{"paper_id": "x"}` → `{"paper_id": ["x"]}` (mirroring the helper's own normalization) and sorts the inner list. Use the normalized form for the cache key. Alternatively, pre-compute the predicate before the cache lookup (already done at `search.py:235-237`) and key the cache off `(query, paper_id_predicate, k, level)` instead of `(query, filters, k, level)`. The first option is lower-risk.
- **Regression guard:** Add `test_cache_key_str_vs_one_element_list_equivalent` to `tests/test_search_filter.py`: invoke the handler twice (once with str, once with list) with a real cache enabled, assert the second call is a cache hit (verified via `set_cache_layer` attribute observation).

### F5 — Implementation summary incorrectly claims `set_resources()` is a new test pattern

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/notes/milestones/proof-verify-handler-wiring-m1/implementation-summary.md:63`
- **What:** The summary says "m1's test fixture is the first to use `set_resources()` directly outside `warm_app` integration tests." Grep finds the function used in `tests/test_proof_chain.py:40,195` and `tests/test_tools_all.py:538,552,579,590` — both predating m1.
- **Why it matters:** Pure documentation accuracy; no behavioral impact. Future agents reading the summary might over-engineer test infrastructure thinking they're paving new ground.
- **Proposed fix:** Strike the "first to use it" claim from the implementation summary. Mention the prior `set_resources()` users as proof the pattern is established. No code change required.
- **Regression guard:** N/A — documentation-only.

## What was done well

- The `_build_paper_id_predicate` helper enforces the correct invariant order (`isinstance` check → empty check → length cap → per-element validation → sort → escape → format), so a single mistake at any layer is caught by the layer above it. This is textbook defense-in-depth.
- `prefilter=True` was applied with explicit reasoning grounded in the synthesis Disagreement-1 resolution; the inline comment at `server/handlers/search.py:321-327` explains the codebase-convention argument so a future contributor cannot accidentally drop the kwarg.
- All 27 new tests pass on a single `pytest` run; the new file `tests/test_search_filter.py` follows the established `asyncio.run()` pattern and the existing `_FakeResources` fixture style — no new test infrastructure invented unnecessarily.
- The `EXPECTED_TOOL_SCHEMA_SHA256` byte-stability discipline was respected — validation is in the handler body, not as Pydantic `Field` constraints. `tests/test_server_tool_schema.py` still passes (verified).
- The new `SUPPORTED_FILTER_KEYS = frozenset({"paper_id"})` mirrors `server.retrieval.bm25.SUPPORTED_FILTER_KEYS` exactly, keeping the two SUPPORTED_FILTER_KEYS sets in mechanical alignment for the eventual hybrid-retrieval merge.
- The cache-key behavior is explicitly tested (`TestCacheKeyDistinguishesFilterSets`) even though no cache-layer code was changed — this is the right impulse: pin invariants you depend on but don't own.
- Per-element `is_valid_paper_id` validation raises a `ValueError` naming the FIRST invalid element (`first invalid: {invalid[0]!r}`), which is the right ergonomics for LLM debuggers: one bad element surfaces immediately rather than being silently dropped.
- The `_escape_paper_id_literal` helper is defended-in-depth (called even though the regex makes it redundant) and the docstring at `server/handlers/search.py:118-121` explicitly names the two-layer mitigation.
- Sorting the paper_ids before joining (`sorted(paper_ids)` at `server/handlers/search.py:172-174`) makes the predicate deterministic, which is the right call for any future caller that wants to hash or cache the predicate string itself.
- The test for boundary `MAX_PAPER_ID_FILTER_ITEMS` (`test_exactly_max_items_accepted`) verifies both the inclusive boundary and the predicate's quote count — small but high-leverage test.

## Recommended rectification order

1. **F2** (HIGH, `filter_warnings` reflection / byte-cap bypass) — fix first because it's an active security regression (response amplification on adversarial input). Per-key length cap at the handler-body boundary is ≤ 20 LOC + 2 tests. Highest blast-radius reduction per line of code.
2. **F1** (HIGH, stale `filters` schema description) — fix second; requires a `EXPECTED_TOOL_SCHEMA_SHA256` re-pin and a description update on both the Pydantic Field and `ToolMeta.description`. Without this fix, the m1 feature is shipped but undiscoverable.
3. **F3** (MEDIUM, regex `$` vs `\Z`) — fix third; 2-character regex change + 2 tests. Tightens the defense-in-depth contract to match its docstring. Cheap.
4. **F4** (MEDIUM, str-vs-list cache key fragmentation) — fix fourth IF cheap (≤ 30 LOC); a `_normalize_filters` helper called before the cache lookup is the cleanest answer. If touching the cache lookup risks regression, defer.
5. **F5** (LOW, summary accuracy) — strike the "first to use" claim from the implementation summary if convenient; no urgency.

## Rectification status

- F1 (HIGH) — **fixed**. Updated `filters` Field description (`server/handlers/search.py:205-213`) + `SEARCH_PAPERS` ToolMeta description (`server/tools.py:142-148`). Bumped `TOOL_SCHEMA_VERSION` 7→8 + re-pinned `EXPECTED_TOOL_SCHEMA_SHA256` + re-pinned `EXPECTED_BP1_SHA256` + bumped `server/schemas/search_papers_result.json` 7→8. Regression guards: `test_filters_field_description_documents_paper_id`, `test_search_papers_toolmeta_mentions_paper_id_filter`.
- F2 (HIGH) — **fixed**. Added `MAX_FILTER_KEY_LEN=64` + per-key length check at handler boundary. Closes the byte-cap bypass via `filter_warnings` reflection. Regression guards: `test_filter_oversized_key_rejected`, `test_filter_warnings_total_size_bounded`, `test_filter_warnings_rejects_non_str_key`.
- F3 (MEDIUM) — **fixed**. Tightened `_PAPER_ID_FULL_PATTERN` regex `$ → \Z` in `ingest/identifiers.py`, propagated to sibling regexes in `ingest/chunker.py` and `tools/validate_eval_fixtures.py` (locked by existing parity tests). Regression guard: `test_paper_id_rejects_trailing_newline`.
- F4 (MEDIUM) — **fixed**. Added `_canonicalize_filters` helper, wired into all 3 cache touchpoints (Tier-1 lookup + Tier-2 lookup + store_search). Regression guards: `test_cache_key_str_vs_one_element_list_equivalent`, `test_cache_key_unsorted_list_normalized`.
- F5 (LOW) — **fixed**. Struck the inaccurate "first to use set_resources()" claim from the implementation summary.

Total fixed: 5 (2 HIGH + 2 MEDIUM + 1 LOW). Deferred: 0. Invalidated: 0.

Adversary invalidation rate: **0%** (0 of 4 CRITICAL+HIGH invalidated — adversary prompt is calibrated correctly).

Project test count: 2238 passed, 9 skipped, 1 xfailed (up from 2230 post-feat baseline; +8 regression guards from this rect commit).

<!-- end rectification status -->

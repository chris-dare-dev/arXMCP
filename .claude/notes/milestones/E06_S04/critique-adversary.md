# Critique — E06_S04

**Critic:** adversary
**Generated:** 2026-05-09T17:05:00Z
**Commit range:** d253456..fa85bed
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES. The 5 ACs are met, all 17 new tests + the
  existing 680 pass, and the wire bytes for `content[0].text` happen
  to be byte-equivalent to the prior FastMCP path because `envelope`
  pre-sorts keys. But the rectification owes one drift fix
  (chunk_id pattern duplicated in `server/schemas/search_papers_result.json:36`
  vs `ingest/identifiers.py:52`) and three test holes that let real
  regressions through silently.
- Counts: 0 CRITICAL, 0 HIGH, 5 MEDIUM, 3 LOW.
- Highest-risk file: `server/schemas/search_papers_result.json:36` —
  hand-written copy of `CHUNK_ID_PATTERN` that E06_S03's F11 thought
  it had already eliminated. No CI lock keeps the two strings in sync.
- Cross-axis pattern: AC enforcement is friendlier to authors than to
  rectifiers — the doc-disclaim test accepts EITHER the literal AC
  sentence OR a paraphrase (`tests/test_snippet_contract.py:251`),
  the snippet-source test only proves `startswith(...)` rather than
  no-LLM, and zero/edge-case result sizes are not exercised.
- The `_WIRE_OVERHEAD_FACTOR=2` invariant docstring is restated in
  `server/handlers/search.py:33` and `:162` even though
  `enforce_byte_cap` is NOT called for `search_papers`. This is
  misleading copy-paste, not a runtime bug.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix |
| HIGH | wrong behavior on common path, load-bearing constraint violated | always fix |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤30 LOC) |
| LOW | style, naming, micro-perf | defer |

## Findings

### F1 — chunk_id regex hand-duplicated in JSON Schema

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/schemas/search_papers_result.json:36
- **What:** The schema declares
  `"pattern": "^arxiv:(\\d{4}\\.\\d{4,5}(v\\d+)?|[a-z][a-z\\-]*/\\d{7}(v\\d+)?):[0-9a-f]{16}$"`
  as a literal string. The canonical pattern lives at
  `ingest/identifiers.py:52` (`CHUNK_ID_PATTERN`) and was
  consolidated under E06_S03 F11 as the single source of truth.
  This new file re-introduces the same drift surface F11 closed.
- **Why it matters:** A future change to `PAPER_ID_PATTERN` (e.g.
  to allow `vN` after old-style `[a-z]+/\d{7}` per arXiv's actual
  schema, or to add the year-2026+ `\d{5}` suffix) will silently
  diverge: chunk_ids that the validator accepts will fail the
  schema-level pattern and `TestSchemaConformance::test_schema_validates_real_search_response`
  will start failing for the wrong reason.
- **Proposed fix:** Add a test that asserts byte-equality between
  the schema's pattern string and `f"^{CHUNK_ID_PATTERN}$"`. Or,
  generate the schema file from `ingest/identifiers.py` at build
  time. The cheap fix is the assertion test in
  `tests/test_snippet_contract.py::TestSchemaConformance`.
- **Regression guard:**
  ```python
  def test_schema_chunk_id_pattern_matches_canonical(self):
      from ingest.identifiers import CHUNK_ID_PATTERN
      schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
      pat = schema["properties"]["results"]["items"]["properties"]["chunk_id"]["pattern"]
      assert pat == f"^{CHUNK_ID_PATTERN}$", (
          f"schema pattern drifted from ingest.identifiers.CHUNK_ID_PATTERN; "
          f"see E06_S03 F11"
      )
  ```

### F2 — snippet-source test proves prefix, not no-LLM

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_snippet_contract.py:166
- **What:** `test_snippet_is_prefix_of_body_text` asserts
  `row["snippet"].startswith("This is the body of chunk")` — a
  prefix-match against the seeded literal. AC #2 says
  "snippet derived from `body_canonical` text, not from any LLM
  call." The test is necessary but not sufficient: a future
  regression that calls Haiku and happens to return text starting
  with "This is the body of chunk" would still pass this test.
- **Why it matters:** The brief AC speaks to a *mechanism* (no LLM
  call) but the test asserts a *value-shape* (prefix). The latter
  is a strict-subset proof. A simpler dependency-injection check
  (assert that `_snippet` is the only function called for the
  field) would close the gap.
- **Proposed fix:** Add `test_no_anthropic_imports_in_search_path`
  that imports `server.handlers.search` and asserts
  `"anthropic"` is not in `sys.modules` after import, AND assert
  that `_snippet` is invoked exactly len(rows) times via a spy.
  The first assertion catches the LLM-import angle; the second
  catches a path that bypasses `_snippet` entirely.
- **Regression guard:**
  ```python
  def test_no_anthropic_in_search_module():
      import importlib, sys
      sys.modules.pop("anthropic", None)
      importlib.import_module("server.handlers.search")
      assert "anthropic" not in sys.modules, (
          "search.py imported anthropic — AC #2 forbids LLM calls "
          "in the snippet path"
      )
  ```

### F3 — disclaimer test accepts paraphrase, hiding AC drift

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_snippet_contract.py:251
- **What:** AC #5 requires the literal string "No dependency on
  Anthropic Citations API". The doc currently DOES contain this
  literal string at `docs/snippet-contract.md:51` (as the section
  heading), so the AC is met today. But the test is written with
  an `or` clause accepting "decoupled from Anthropic's Citations
  API" as an equivalent. If a future copy-edit drops the literal
  AC sentence and keeps only the paraphrase, the test still
  passes, but the AC is now silently violated.
- **Why it matters:** The implementation summary explicitly
  acknowledges the test is "tolerant" and the doc uses both
  phrasings. The tolerance is unnecessary — the literal phrase IS
  in the doc. Keep the test strict.
- **Proposed fix:** Tighten the assertion to require ONLY the
  literal AC sentence:
  ```python
  assert "No dependency on Anthropic Citations API" in normalized, (
      "AC #5 requires the literal sentence; paraphrases do not satisfy it"
  )
  ```
- **Regression guard:** Same as the proposed fix — the assertion
  itself is the regression guard.

### F4 — zero-result and edge-case search shapes untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_snippet_contract.py:97
- **What:** Every test calls `_search` with a non-empty seeded
  corpus and asserts `len(rows) >= 1`. There is no test for the
  zero-result path (empty `results` array, empty content[1..]
  resource_link section, schema validation under empty arrays).
  There is also no test that the snippet exactly hits the 150-char
  cap (cap-edge), no test for `body_text=None`/`""` returning an
  empty snippet, no test for `theorem_name=None` AND
  `theorem_label=None` returning empty `label`.
- **Why it matters:** The schema's `additionalProperties: false`,
  the `score` `[0,1]` bounds, and the `snippet` `maxLength: 150`
  are all only ever exercised with the same 5-chunk happy-path
  corpus. A regression that emits `score = 1.0000001` (numeric
  edge case in `_distance_to_score`) or a 151-char snippet
  (off-by-one in `_snippet`) would not be caught.
- **Proposed fix:** Add 4 small tests:
  1. `test_zero_results_validates_schema` — query with `k=1` and
     a known-empty corpus (or filter such that results=[]); assert
     schema validation passes.
  2. `test_snippet_exactly_at_cap` — seed a chunk with `body_text`
     of length 150; assert `snippet == body_text[:150]` and that
     `len(snippet) == 150`.
  3. `test_snippet_at_cap_plus_one` — seed a 151-char body; assert
     `len(snippet) == 150`.
  4. `test_score_clamped_to_one` — feed a synthetic `_distance=0.0`
     row and assert `score == 1.0` (not `1.0...001`).
- **Regression guard:** The 4 tests above.

### F5 — `_WIRE_OVERHEAD_FACTOR=2` invariant misleadingly cited

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/search.py:33
- **What:** Both the module docstring (line 33) and the
  `_build_content_blocks` docstring (line 162) state "preserves
  the wire-overhead-factor=2 measurement that `enforce_byte_cap`
  depends on". `search_papers` does NOT call `enforce_byte_cap` —
  the only handler that does is `chunk.py:87`. The new content
  array adds N additional ResourceLink blocks (~75 bytes each on
  the wire after null-stripping); for k=50 the actual wire
  overhead becomes roughly `2× structured + 3.7 KB`, which the
  factor=2 measurement under-estimates. Today the under-estimate
  is harmless because `search_papers` doesn't enforce the cap;
  tomorrow when E07 wires it, the factor will already be wrong.
- **Why it matters:** The docstring asserts an invariant the
  handler does not enforce. A reader trying to understand why the
  factor is 2 will trace it to `search_papers` and find no
  enforcement; a future maintainer adding cap enforcement will
  read the docstring and assume the factor is calibrated, when in
  fact ResourceLink overhead is now unaccounted for.
- **Proposed fix:** Edit the docstrings to either (a) note that
  `search_papers` doesn't currently enforce the cap and the
  factor=2 reasoning applies only to chunk.py, or (b) bump the
  factor reasoning in `server/tools.py:285` to account for
  per-result ResourceLink overhead and add a comment explaining
  the per-row footprint.
- **Regression guard:** Add a comment-only test in
  `tests/test_tools_all.py::TestByteCapEnforcement` documenting
  that the factor is calibrated for chunk.py's single-RL output,
  not search.py's per-result-RL output.

### F6 — schema chunk_id pattern silently rejects newer arXiv ids

- **Severity:** LOW
- **Source:** adversary
- **File:** server/schemas/search_papers_result.json:36
- **What:** The pattern allows the new style `\d{4}\.\d{4,5}` —
  this matches arXiv ids from 2007 through ~2030 (5-digit
  sequence rolls over around 2030 at current submission rates).
  When arXiv eventually moves to 6-digit ids
  (`2026.123456` would be the natural next step), the schema will
  silently reject perfectly valid chunk_ids. Same flaw exists in
  the canonical `ingest.identifiers.PAPER_ID_PATTERN`, so this is
  not unique to this milestone — but the schema duplicates the
  flaw.
- **Why it matters:** Forward-compatibility nit. Not a v1 problem
  but worth recording so that when `PAPER_ID_PATTERN` is bumped,
  the schema gets bumped in lockstep.
- **Proposed fix:** Defer until the canonical pattern itself is
  bumped; cross-reference is enough.
- **Regression guard:** Already provided by F1's byte-equality
  assertion (any future bump will fail the assertion).

### F7 — schema title is human-readable but not machine-pinned

- **Severity:** LOW
- **Source:** adversary
- **File:** server/schemas/search_papers_result.json:75
- **What:** `"title": "search_papers result envelope"` is a free
  string. The implementation summary references E06_S06 hash-pinning
  the file's bytes; if the title is edited (typo fix, branding
  change) the SHA changes too, even though the contract didn't.
  The schema has no `$id` or version field — bumping the contract
  in a backward-compatible way (e.g. adding an optional new field)
  has no version anchor.
- **Why it matters:** Without `$id` and a `version` (or
  `tool_schema_version` echoed in the file), the rectifier needs
  out-of-band coordination to bump E06_S06's hash AND know which
  version the file represents.
- **Proposed fix:** Add `"$id": "https://arxmcp/schemas/search_papers_result/v1.json"`
  and a top-level `"version": 1`. The `tool_schema_version` in
  `server/tools.py` already pins this; copying it here closes the
  loop.
- **Regression guard:** Add an assertion in
  `TestSchemaConformance` that the schema's `version` field
  matches `server.tools.TOOL_SCHEMA_VERSION`.

### F8 — `test_snippet_constant_pinned_to_150` lives outside doc-AC tests

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_snippet_contract.py:179
- **What:** This test asserts `SNIPPET_MAX_CHARS == 150` but lives
  in `TestSnippetSource`. The doc test class `TestDocContract`
  has `test_doc_states_150_char_cap` which only checks `"150"` is
  somewhere in the file — it would pass even if the doc said
  "snippet of 150 milliseconds" or "150 papers per page". The
  three things (constant, doc, schema) should be cross-checked.
- **Why it matters:** A regression that bumps `SNIPPET_MAX_CHARS`
  to 200 in the code AND the doc would not necessarily update the
  schema's `maxLength: 150`. The contract drift would not be
  detected.
- **Proposed fix:** Add one cross-check test:
  ```python
  def test_snippet_cap_consistent_across_files(self):
      from server.handlers.search import SNIPPET_MAX_CHARS
      schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
      cap_in_schema = schema["properties"]["results"]["items"]["properties"]["snippet"]["maxLength"]
      doc_text = DOC_PATH.read_text(encoding="utf-8")
      assert SNIPPET_MAX_CHARS == cap_in_schema == 150
      assert "150" in doc_text  # already in test_doc_states_150_char_cap
  ```
- **Regression guard:** The test above.

## What was done well

- **Wire-byte stability holds.** Verified empirically:
  `pydantic_core.to_json(envelope, indent=2)` and
  `json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False)`
  produce byte-identical output for the realistic search shape
  because `envelope` already sorts the dict via `_sort_dict`.
  E06_S06's hash pin will not be invalidated by this milestone.
- **`CallToolResult` return path is correct per FastMCP.**
  Verified at `.venv/.../mcp/server/fastmcp/utilities/func_metadata.py:114`:
  when result is `CallToolResult`, FastMCP bypasses
  `_convert_to_content` entirely and returns the result as-is.
  The output_model still validates `structuredContent` so the
  contract is enforced.
- **Resource_link wire form is well-formed** and matches MCP
  2025-06-18 — verified live: `{"name": ..., "uri": ..., "type": "resource_link"}`
  with all nullable fields stripped by the lowlevel server.
- **Schema validates the LIVE response end-to-end.**
  `TestSchemaConformance::test_schema_validates_real_search_response`
  closes the contract with `jsonschema.validate(instance, schema)`
  using Draft-07 (verified via `validator_for` picking on
  `$schema`). This is the right design.
- **`_snippet` handles `body_text=None`** at
  `server/handlers/search.py:243` — defensively returns `""` so
  schema validation never sees `null`.
- **No `summary` field anywhere** — verified via grep across the
  result handler, schema, and tests.
- **`additionalProperties: false` on both envelope and per-row
  schema** — locks the contract to closed-shape.
- **Doc actually contains the literal AC sentence** at
  `docs/snippet-contract.md:51` (section heading) — the AC is
  strictly met, not paraphrased away.
- **Tests use the existing synthetic-corpus pattern** rather
  than gating on the operator's real ingest, matching the
  E06_S03 precedent and the brief's "passes against the seed
  corpus" AC reasonably.
- **All 17 new tests + the existing 680 pass cleanly** with no
  ruff regressions.

## Recommended rectification order

1. **F3 (LOW-cost LOC, MEDIUM impact)** — tighten the disclaimer
   test to require the literal AC sentence. One-line edit.
2. **F1 (LOW-cost LOC, MEDIUM impact)** — add the byte-equality
   test for the chunk_id pattern. One added test method (~10 LOC).
3. **F2 (LOW-cost LOC, MEDIUM impact)** — add the no-anthropic
   import test. One added test method (~8 LOC).
4. **F4 (MEDIUM-cost LOC, MEDIUM impact)** — add the 4 edge-case
   tests. Need to construct a separate fixture for the
   151-char-body case but the rest reuse the existing one.
5. **F5 (LOW-cost LOC, MEDIUM impact)** — fix the misleading
   docstring lines in `search.py:33` and `:162`.
6. **F8 (LOW-cost LOC, LOW impact)** — add the cross-file
   consistency check.
7. **F7 (LOW-cost LOC, LOW impact)** — add `$id` and `version`
   to the schema. Defer if E06_S06 hash-pinning will already
   detect drift.
8. **F6 (defer)** — record only; nothing to do until the
   canonical pattern is bumped.

## Rectification status

**Phase 4 commit:** see `state.json` `rectification_commit` field.

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| F1 — chunk_id regex hand-duplicated in JSON Schema | MEDIUM | **fixed** | `tests/test_snippet_contract.py::TestRegexSourceOfTruth::test_schema_chunk_id_pattern_matches_canonical` asserts the schema's pattern equals `f"^{CHUNK_ID_PATTERN}$"` from `ingest.identifiers`. Future drift fires CI. |
| F2 — snippet-source test only proves prefix, not no-LLM | MEDIUM | **fixed** | `TestNoLLMInSnippetPath::test_no_llm_client_in_search_module` imports `server.handlers.search` and asserts no `anthropic`/`openai`/`cohere` module is in `sys.modules`. A future regression that calls Haiku would import its client at handler load. |
| F3 — disclaimer test accepts paraphrase | MEDIUM | **fixed** | `test_doc_disclaims_citations_api` tightened to require ONLY the literal AC sentence "No dependency on Anthropic Citations API"; paraphrases no longer pass. |
| F4 — zero-result + edge-case shapes untested | MEDIUM | **fixed** | New `TestEdgeCaseShapes` class with 4 tests: `_snippet` at cap + cap+1 (off-by-one), `_snippet` with None/empty, `_distance_to_score` clamping, `_format_label` with all-None inputs. |
| F5 — `_WIRE_OVERHEAD_FACTOR=2` invariant misleadingly cited | MEDIUM | **fixed** | `server/handlers/search.py` module docstring + `_build_content_blocks` docstring rewritten: explicit note that search_papers does NOT call `enforce_byte_cap` at v1; future wire-up needs ResourceLink-overhead recalibration. |
| F6 — schema chunk_id pattern silently rejects 6-digit ids | LOW | **deferred** | Forward-compat concern; covered by F1's byte-equality assertion (any future PAPER_ID_PATTERN bump fires the test). |
| F7 — schema $id and version missing | LOW | **fixed** | Added `$id: "https://arxmcp/schemas/search_papers_result/v1.json"` and top-level `version: 1`. New `TestSchemaVersionPin` (2 tests) asserts `version == TOOL_SCHEMA_VERSION` and `$id` is present. |
| F8 — SNIPPET_MAX_CHARS cross-file consistency | LOW | **fixed** | New `TestSnippetCapConsistency` (2 tests): cap constant matches schema `maxLength`; doc mentions the literal "150 character"/"150-char" phrase (not just `"150"`). |

**New regression tests added in this rectification batch (10):**
- `TestRegexSourceOfTruth::test_schema_chunk_id_pattern_matches_canonical` (F1)
- `TestNoLLMInSnippetPath::test_no_llm_client_in_search_module` (F2)
- `TestEdgeCaseShapes::test_snippet_function_at_cap` (F4)
- `TestEdgeCaseShapes::test_snippet_function_handles_none_and_empty` (F4)
- `TestEdgeCaseShapes::test_distance_to_score_clamped_to_unit_interval` (F4)
- `TestEdgeCaseShapes::test_format_label_handles_all_none` (F4)
- `TestSnippetCapConsistency::test_cap_constant_matches_schema_max_length` (F8)
- `TestSnippetCapConsistency::test_doc_mentions_the_exact_cap` (F8)
- `TestSchemaVersionPin::test_schema_version_matches_tool_schema_version` (F7)
- `TestSchemaVersionPin::test_schema_has_id_for_canonical_url` (F7)

**Suite at rectification time:** 704 passed, 3 skipped, ruff clean.

# E10_S03 — Adversary Critique

**Commit range under review:** `c906d81..d8ae180`
**Scope:** the algorithm/API layer landed in this milestone — TED + dense cosine fusion via `EquationIndex`, the `equations` LanceDB schema, the `find_equation` handler dispatch, the tree-JSON indexer. Out of scope: extractor / `embedding_eq` populator / LaTeXML pool (explicitly deferred per the synthesis D1/D4).

## Executive summary

- **Verdict: PARTIAL.** The cache-byte-stability anchors are correctly re-pinned in lockstep and the algorithm/API/handler layering matches the synthesis. But the parser has a load-bearing math-fidelity bug (tail-text dropped on mixed content) and the case-folding contract between `looks_like_mathml` (case-insensitive) and `parse_mathml_to_tree` (case-preserving) is broken.
- **F1 (HIGH, math fidelity).** `_element_to_node` drops tail-text. Mixed-content MathML `<mrow><mi>x</mi> + <mi>y</mi></mrow>` strips the operator " + "; demonstrated `TED(x+y, x-y) == 0` and `TED(x+y, xy) == 0` on this implementation today.
- **F2 (HIGH, math fidelity / detection contract).** `looks_like_mathml` matches `<MATH>` case-insensitively but the parser preserves case in node labels, producing trees with root `"MATH"` that compare against `"math"` trees at TED ≈ 0.67. An uppercase MathML input that successfully classifies as MathML then ranks below structurally-identical lowercase equations.
- **F3 (MEDIUM, AC framing).** AC1 in the brief is literally about a LaTeX input (`"\\int_0^1 f(x) dx"`). The handler routes LaTeX to the unchanged-from-v1 `dense_only_stmt_fallback`, and the implementation summary claims AC1 is "satisfied via the MathML form of the same equation." This is honest in synthesis D4 but the AC test as written does not exercise the LaTeX input path — there is no test asserting that the LaTeX form returns the integral fixture in top-3, even on the dense-only path.
- **F4 (MEDIUM, semantics of `ted_fused` mode).** When `hits` is non-empty but every candidate's `mathml_tree_json` is NULL, the handler reports `retrieval_mode="ted_fused"` with `ted_norm=1.0` on every row. The `_dense_only` fallback to `dense_only_fallback` only fires on **empty** hits, not on **all-trees-NULL** hits. Callers parsing `retrieval_mode` get a misleading signal.
- **F5 (LOW, robustness).** `tree_from_json` recurses without depth-bound. The handler caps caller MathML at 4000 chars (~300 nest depth), but the equations table's `mathml_tree_json` column has no length cap, so a future corrupted / malicious row can blow Python's default 1000-frame stack on read.
- **F6 (LOW, indexer schema-mismatch hazard).** `index_equation_trees` builds the update arrow table with `EQUATIONS_SCHEMA_V1` even when reading rows that came from older schemas — works today (single schema) but creates an unannounced upgrade hazard.
- **F7 (LOW, performance / startup).** `Resources.startup` opens a fresh `lancedb.connect` for both definitions and equations (two separate connects). Idiomatic LanceDB shares a single Database handle.
- **What was done well: 7 wins** (see "What was done well" section). The hash-pin lockstep is exemplary.

## Severity calibration

| Severity | Definition (per critique brief) | Count |
|---|---|---|
| CRITICAL | Data loss, security, or broken project invariant | 0 |
| HIGH | Wrong behavior on a common code path | 2 (F1, F2) |
| MEDIUM | Subtle correctness or missing test coverage | 2 (F3, F4) |
| LOW | Style / robustness / defense-in-depth | 3 (F5, F6, F7) |

## Findings

### F1 — Tail-text dropped: operators silently disappear in mixed-content MathML

**Severity:** HIGH
**Where:** `server/retrieval/equations.py:125-143` (`_element_to_node`)
**What:** The parser captures `el.text` (text BEFORE the first child) as a leaf, but explicitly drops `el.tail` (text following the close-tag of each child). For canonical LaTeXML output where every operator is wrapped in `<mo>+</mo>` this is fine, but for mixed-content MathML — `<mrow><mi>x</mi> + <mi>y</mi></mrow>`, where the " + " is tail-text on `<mi>x</mi>` — the operator is silently lost. The docstring at line 130 claims tail-text "carries no useful semantic content in MathML and would inflate TED." That is wrong for any non-canonical source.

I reproduced this against the implementation today:

```
parse_mathml_to_tree("<math><mrow><mi>x</mi> + <mi>y</mi></mrow></math>") and
parse_mathml_to_tree("<math><mrow><mi>x</mi> - <mi>y</mi></mrow></math>") and
parse_mathml_to_tree("<math><mrow><mi>x</mi><mi>y</mi></mrow></math>")
→ all three trees have tree_size=6
→ TED(x+y, x-y) = 0.0
→ TED(x+y, xy)  = 0.0
```

Three semantically distinct expressions hash to the same tree.

**Why it matters:** The math-fidelity rationale in `.claude/notes/01-mission-and-context.md` is load-bearing: the project invests in retrieval/structure rather than LLM critique. A retrieval layer that conflates `x+y`, `x-y`, and `xy` is failing on the value proposition. Today the v1 corpus comes from LaTeXML (which canonicalizes operators into `<mo>`), so the failure mode is masked — but a future ingest pipeline that pulls MathML from any other source (MathJax, KaTeX, Pandoc, hand-written MathML from author preamble macros) silently degrades. The "tail-text carries no useful semantic content" claim in the docstring is the wrong invariant to lock in.

**How to fix:** Either (a) preserve tail-text as a second leaf child after the recursing-child node (synthesis D2's "preserve operator order" intent), or (b) explicitly assert at parse time that the input is canonical-form MathML (every `<mo>` wraps the operator, no mixed content) and reject otherwise, OR (c) document in the parser docstring that v1 assumes LaTeXML-canonical input and add a regression test against a mixed-content fixture to lock the assumption. Option (a) is the most defensible; the JSON serialization already supports arbitrary tree shapes.

---

### F2 — Case-mismatch between `looks_like_mathml` and `parse_mathml_to_tree`

**Severity:** HIGH
**Where:** `server/retrieval/equations.py:63-75` (regex flag `re.IGNORECASE`) vs `_local_tag` + `_element_to_node` at lines 83-143 (case-preserving)
**What:** `_MATHML_ROOT_RE = re.compile(r"<(?:[a-zA-Z][\w-]*:)?math\b", re.IGNORECASE)`. So `<MATH>...</MATH>` is classified as MathML and routes to the TED path. The parser then produces a tree with root label `"MATH"` and children labeled `"MI"`, `"MN"`, etc.

I reproduced this against the implementation today:

```
parse_mathml_to_tree("<MATH><MI>X</MI></MATH>") → root.label = "MATH", children = ["MI"]
parse_mathml_to_tree("<math><mi>X</mi></math>") → root.label = "math", children = ["mi"]
normalized_ted(upper, lower) = 0.6666666666666666
```

A caller submitting an uppercase MathML query (legal XML, accepted by `defusedxml`) ranks below or above structurally-identical lowercase equations depending purely on case.

**Why it matters:** This breaks the documented invariant on line 84-91 of equations.py: "two equations serialized with different namespaces parse to identical trees" — the same intent applies to case. The contract on `looks_like_mathml` (case-insensitive root detection) implies the parser is case-tolerant; it is not.

**How to fix:** Lowercase the local tag inside `_local_tag` before constructing the `zss.Node` label: `return tag.lower()` after the existing namespace stripping. Add a regression test analogous to `test_strips_namespace_prefix`:

```python
def test_strips_case(self):
    upper = "<MATH><MI>x</MI></MATH>"
    lower = "<math><mi>x</mi></math>"
    assert normalized_ted(parse_mathml_to_tree(upper),
                          parse_mathml_to_tree(lower)) == 0.0
```

---

### F3 — AC1 has no direct test against the LaTeX-input path it literally describes

**Severity:** MEDIUM
**Where:** `tests/test_equation_index.py:399-538` (`TestHandlerDispatch`) and the brief AC1 wording in `.claude/roadmap/E10-specialized-indices.md:104-145`
**What:** AC1 says "`find_equation("\\int_0^1 f(x) dx")` returns structurally similar integrals in the top-3." The handler routes LaTeX input through `dense_only_stmt_fallback` (`server/handlers/equation.py:106-108`) — unchanged from v1. The implementation summary at line 48-56 acknowledges this and claims AC1 is "satisfied via the MathML form of the same equation," verified in `test_mathml_input_with_populated_table_routes_to_ted_fused`. But that test passes a MathML fixture, not the LaTeX form. The only LaTeX-input test, `test_latex_input_dense_only_stmt_fallback`, asserts the mode tag — it does NOT assert that the integral fixture appears in the top-3 of the dense-only retrieval.

**Why it matters:** Synthesis D4 documented the LaTeX-input deferral, and that's an honest deferral — but the brief AC reading remains unverified. If a future change to `_dense_only` regresses ranking quality for a LaTeX integral input, no test catches it. The "AC1 is satisfied" claim in the implementation summary is at best aspirational.

**How to fix:** Add one test that seeds the chunks table with an integral chunk + a summation chunk, queries with `latex_or_mathml=r"\int_0^1 f(x) dx"`, asserts `retrieval_mode == "dense_only_stmt_fallback"`, AND that the integral chunk appears in `result["results"][:3]`. This pins the actual AC1 behavior (even though the path is dense-only).

---

### F4 — `ted_fused` mode reported when every candidate's tree was NULL

**Severity:** MEDIUM
**Where:** `server/handlers/equation.py:70-95` + `server/retrieval/equations.py:328-388`
**What:** The handler reports `retrieval_mode="dense_only_fallback"` only when `hits == []`. But when `equations_table` is populated, dense ANN returns N candidates, and EVERY candidate's `mathml_tree_json` is NULL (lines 358-362 in `EquationIndex.query` set `ted_norm = 1.0` and keep going), the function returns hits with `ted_norm == 1.0` for every row and `final_score = (1-α) * cosine_score`. The handler then reports `retrieval_mode="ted_fused"`. The caller sees a mode tag that promises TED-fusion ranking; what they get is degenerate dense-only-with-extra-noise (since alpha=0.5 halves the cosine signal).

**Why it matters:** AC4 says "graceful fallback when `mathml_tree_json` column is absent OR all NULL — same fallback in all three cases" (synthesis D3, lines 125-126). The "or all NULL" case is not honored when there's a partially-seeded table where the matching candidates happen to lack trees. The semantics of `retrieval_mode` as a triage signal is also undermined: a caller's "did the TED path actually contribute?" decision rule cannot use the mode tag alone.

**How to fix:** In `EquationIndex.query`, track whether ANY candidate had a parseable tree. If `none_had_tree == True`, return `[]` so the handler's `if not hits: dense_only_fallback` branch fires. Alternatively, add a new mode `"ted_fused_degenerate"` or flip a separate `ted_active: bool` field in the envelope. The synthesis D10 taxonomy is closed-at-3, so prefer the `return []` route.

---

### F5 — Unbounded recursion on stored tree JSON

**Severity:** LOW
**Where:** `server/retrieval/equations.py:181-194` (`_dict_to_node`) and `:202-204` (`tree_size`) and `:125-143` (`_element_to_node`)
**What:** Caller-side MathML is capped at 4000 chars by the handler's Pydantic constraint (`server/handlers/equation.py:39-42`), which bounds parse-tree depth to ~300 levels — safely under Python's default 1000-frame recursion limit. But `tree_from_json` reads from the `mathml_tree_json` column on the equations table, which has no length cap (the PyArrow `pa.utf8()` field is unbounded). A pathological row (50KB+ deeply nested) could blow the stack on `_dict_to_node` recursion. I confirmed depth=600 works under `sys.setrecursionlimit(2000)` in repro; depth ≥ 1000 with the default limit raises `RecursionError`.

In a single-user / single-writer deployment today this is academic. But it's a real foot-shot for the day someone hand-seeds the equations table from external MathML, or the future extractor lands and emits an unexpectedly deep tree from a pathological hep-th paper.

**Why it matters:** `RecursionError` is not handled in `EquationIndex.query`'s `except (ValueError, json.JSONDecodeError)` block. A single bad row at corpus scale could 500 the entire request rather than degrading to cosine-only. Defense-in-depth posture from `.claude/notes/08-security-observability-ops.md` says: trust-local-but-defense-in-depth.

**How to fix:** Either (a) bound the JSON tree depth at indexer-write time (`index_equation_trees` checks `tree_size <= MAX_TREE_NODES` before serialization, e.g. 5000), OR (b) widen the `query()` exception handler to include `RecursionError` so a deep row degrades to cosine-only for that row rather than 500-ing. Option (b) is one line and ships immediately.

---

### F6 — Indexer writes through `EQUATIONS_SCHEMA_V1` regardless of read schema

**Severity:** LOW
**Where:** `ingest/index_equations.py:118-126`
**What:** `index_equation_trees` reads `table.to_arrow().to_pylist()`, mutates rows in Python, and writes back via `pa.Table.from_pylist(new_rows, schema=EQUATIONS_SCHEMA_V1)`. Today this is fine because the table was created with `EQUATIONS_SCHEMA_V1`. But the moment a future schema bump (`EQUATIONS_SCHEMA_V2` adds a column) is introduced, the indexer running against a v1-on-disk table will either silently drop the v2 column on rewrite OR throw on schema mismatch — depending on LanceDB version.

**Why it matters:** This is a future-proofing concern; it doesn't fire today. But the migration pattern is documented at `.claude/notes/05-storage-and-indexing.md` "MVCC versioning" — schema bumps are supposed to be deliberate, and the indexer should be robust to running against tables it didn't create.

**How to fix:** Either (a) skip the `schema=EQUATIONS_SCHEMA_V1` arg and let LanceDB infer (works but loses type safety), OR (b) snapshot the actual table schema via `table.schema` and pass that — preserves type safety, tolerates future schema drift. Document the chosen pattern in the indexer's docstring as the "single-schema for now; bump together" contract.

---

### F7 — Two separate `lancedb.connect` calls during startup

**Severity:** LOW
**Where:** `server/resources.py:428-501` (definitions table block lines 428-462 + equations table block lines 464-501)
**What:** Both the definitions table and equations table blocks call `lancedb.connect(str(Path(config.lancedb_path).resolve()))`. This is two distinct Database handles to the same directory. Idiomatic LanceDB shares one Database; the lazy table-open is on the connection. Negligible perf impact (~10ms each) but it shows up as a code-pattern divergence the orchestrator-rules doc was trying to head off.

**Why it matters:** Tiny — but if a future milestone adds a third optional table (e.g., the BM25 metadata table, the citation graph adapter), the pattern multiplies. Worth fixing once before it propagates.

**How to fix:** Hoist `db_conn = lancedb.connect(...)` to a single call shared by both blocks. The `try/except (ValueError, FileNotFoundError)` per-table table-open remains the right pattern.

---

## Axis-by-axis walkthrough

| Axis | Status | Notes |
|---|---|---|
| 1. Cache byte-stability | **CLEAN.** | `TOOL_SCHEMA_VERSION = 3` (single definition at `server/tools.py:64`); `EXPECTED_TOOL_SCHEMA_SHA256 = "3961d85..."` and `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH = 3` re-pinned together at `tests/test_server_tool_schema.py:94/109`; `EXPECTED_BP1_SHA256 = "aabfbc16..."` re-pinned at `tests/test_prompts.py:612`. The handler's envelope dict literal puts keys in arbitrary order but `envelope()` → `_sort_dict` re-builds with sorted keys (`server/tools.py:259-286`), so byte-stability holds. The new keys `alpha`, `cosine_score`, `ted_norm`, `equation_id` are not in the canonical search_papers schema (find_equation has no separate JSON schema) so no contract break. Tests pass: I ran `pytest tests/test_server_tool_schema.py tests/test_prompts.py` to verify. |
| 2. Math fidelity | **NOT CLEAN.** | F1 (tail-text drop) + F2 (case mismatch). The namespace-stripping + attribute-stripping designs are otherwise sound per the synthesis. |
| 3. Security threat-model coverage | **MOSTLY CLEAN.** | defusedxml.ElementTree rejects DTD entity expansion by default (confirmed via repro: `EntitiesForbidden` raised on a billion-laughs probe). SQL `IN ()` injection in `_dense_candidates:431` is genuinely blocked by the chunk_id regex; "by construction" comment is correct. F5 (recursion) is the one defense-in-depth gap. |
| 4. MCP 2025-06-18 spec compliance | **CLEAN.** | find_equation has no JSON schema file (only search_papers does). The new envelope keys are alphabetically sorted via `envelope()`. No snippet contract violation since find_equation isn't covered by the 150-char snippet rule (which is search_papers-only per `.claude/docs/snippet-contract.md`). |
| 5. Local-first + Docker constraint | **CLEAN.** | `zss>=1.2.0` and `defusedxml>=0.7` are pure-Python with no compiled deps. The equations table path stays under `var/arxmcp/index/lancedb/equations.lance/` via the existing `config.lancedb_path` + LanceDB table-name pattern. Indexer uses the same path. |
| 6. Tier sequencing | **CLEAN.** | The "deferred extractor + LaTeXML pool" framing is honest. The handler degrades on absent / empty equations table (AC4 path is real). H5 is declared partially-closed in the implementation summary line 8-10 and in synthesis line 102-104 — the framing matches the synthesis. No tier-sequencing violation; the algorithm/API layer lands as a coherent unit. |
| 7. No-fork policy | **CLEAN.** | `zss` is a published pip dependency, MIT/BSD-3-Clause (implementation summary line 121 documents the license verification); `defusedxml` is published. No vendored code. The parser, fusion math, and indexer are all original. |
| 8. Test surface | **PARTIAL.** | AC2–AC5 are covered; AC1 has the F3 gap. Beyond-AC tests cover parser (6 tests), JSON round-trip (4), normalized TED + fusion (7), handler dispatch (4). No test for: F1 mixed-content tail-text (would have caught the bug), F2 case-sensitivity, F4 all-trees-NULL case, F5 deep-tree-from-storage. Indexer idempotency is implicit (the WHERE filter is asserted in code but not in a test that re-runs the indexer). |

## Other observations

- **Dead code:** none found. The handler's `_dense_only` is a meaningful three-mode function (LaTeX / no-table / malformed). The `EquationIndex` class is reachable via the handler path. The indexer is called from tests + `python -m ingest.index_equations` (no entry point script, but a future ingest driver can call `index_equation_trees`).
- **Error handling that masks real failures:** `EquationIndex.query` line 367-374 has `except (ValueError, json.JSONDecodeError)`. Today this catches malformed-JSON rows and silently degrades the row to cosine-only (`ted_norm = 1.0`) plus a WARNING log. Reasonable, but it does NOT catch `RecursionError` (F5) or `KeyError` from a malformed-but-syntactically-valid JSON missing the `label` key (which goes through `_dict_to_node`'s explicit `ValueError`, so this one is fine). The `KeyError` for `row["equation_id"]` at `_dense_candidates:447` could fire if the equations table has a row without an `equation_id` — but that's nullable=False in the schema, so it can't happen against a properly-written row.
- **Race conditions:** `index_equation_trees` documents the single-writer-per-table assumption at line 21-25 of `ingest/index_equations.py`. The `merge_insert` discipline matches the definitions indexer. Same `equation_id` as primary key for upsert. OK.
- **Partial-state behavior:** if the chunks table's ANN returns chunks whose `chunk_id` is NOT a `parent_chunk_id` in the equations table, the IN clause comes back empty and `equations_arrow.num_rows == 0` → `_dense_candidates` returns `[]` → `query` returns `[]` → handler falls back to `dense_only_fallback`. **Untested** but logically correct.
- **Edge cases:**
  - `find_equation("<math/>", k=10)` — `looks_like_mathml` matches; parser produces root "math" with 0 children; `tree_size = 1`. Tree is well-formed but degenerate. ANN candidates joined by chunk_id are unlikely to match. Falls back through `if not hits → dense_only_fallback`. OK but untested.
  - `find_equation(" <math><mi>x</mi></math> ", k=10)` — whitespace-tolerant via `text.lstrip()` in `looks_like_mathml`; parser handles via `DET.fromstring` which is whitespace-tolerant. Confirmed works via repro.
  - Uppercase MathML — see F2.
- **Configuration validator robustness:** `validate_eq_ted_weight` at `server/config.py:218-230` checks `0.0 <= v <= 1.0`. But `float("nan")` does NOT satisfy that comparison (NaN comparisons are always False), so `ARXMCP_EQ_TED_WEIGHT=nan` raises correctly. `float("inf")` also raises. The pydantic float validator rejects strings that don't parse as floats, so `ARXMCP_EQ_TED_WEIGHT=foo` is rejected. OK.
- **Tree size growth:** the synthesis quoted ~3-5KB per 100-node tree; ~30-50KB per 1000-node hep-th equation; "100K equations → 3-5GB just for the tree column." Worth noting but **out of scope at v1** since the table is empty. Not a finding, but the indexer should grow a per-row size warning if the JSON exceeds (say) 32KB so the operator gets visibility before the corpus scale hits.
- **LanceDB IN clause cardinality:** the `_ann_cap = 200` (line 280) means up to 200 chunk_ids in a single IN clause. LanceDB pushes this through DataFusion which has been stable up to thousands of items in IN. No concern at 200.

## What was done well

1. **Hash-pin lockstep is exemplary.** All three anchors (`TOOL_SCHEMA_VERSION`, `EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`) and `EXPECTED_BP1_SHA256` plus the schema `version`+`$id` are bumped together. The version-anchor cross-check in `tests/test_server_tool_schema.py` (F2 from E06_S06 critique) would have caught any drift. The `EXPECTED_BP1_SHA256` update-anchor comment in `tests/test_prompts.py:604-611` explicitly explains why it's bumping. Right discipline, right place.
2. **Honest scope-narrowing.** The implementation summary line 30-39 and synthesis §3 are explicit about H5 being partially-closed. The `chore(notes)` commit pattern with `phase: complete` plus the "deferred to E10_S03b or E11" framing avoids the "claims to close H5" lie the synthesis flagged.
3. **JSON-over-pickle decision was right.** Eliminates the pickle deserialization vector and the Python-version drift. The tree round-trip is byte-deterministic (sorted keys + tight separators), which incidentally would let a future content-addressing milestone bolt on without a re-encode pass.
4. **defusedxml choice is correct.** Confirmed via direct billion-laughs probe — `EntitiesForbidden` raised by default. The 4000-char Pydantic cap on the handler input bounds the worst-case parser cost. The synthesis open-question #1 was answered with the right call.
5. **Graceful fallback design.** Three distinct `retrieval_mode` values (`ted_fused`, `dense_only_fallback`, `dense_only_stmt_fallback`) plus the `malformed_mathml_fallback` flag give callers proper triage signal. F4 above is a real gap but the overall design is correct.
6. **Resource lifecycle pattern mirrored from E10_S01.** The lazy-open + missing-table-is-OK pattern in `server/resources.py:464-501` matches the definitions table block at lines 422-462. Single discipline; future tables will follow.
7. **Indexer idempotency at the row level.** `index_equation_trees` skips rows that already have `mathml_tree_json` set (line 98-100), so re-running the indexer is a no-op on a fully-indexed table. The `merge_insert` on `equation_id` primary key is the right LanceDB pattern.
8. **Tests are minimum-faithful.** The handler-integration test seeds a real LanceDB chunks + equations table; doesn't mock the LanceDB surface; mocks only the BGE-M3 encoder. This catches a class of mistakes (Arrow schema mismatch, IN-clause syntax, merge_insert semantics) that pure mocks would have missed.

## Recommended rectification order

1. **F2 (HIGH) first** — one-line fix to `_local_tag`. Add a regression test. Trivial and high-leverage; would also have caught F1 had the test author noticed during writing.
2. **F1 (HIGH) second** — preserve tail-text. Bigger semantic change; needs a fixture asserting mixed-content TED is non-zero. Re-pinning hashes is NOT required because the parser is internal — the wire surface is unchanged.
3. **F4 (MEDIUM) third** — add the "none had tree" sentinel inside `EquationIndex.query` so all-NULL candidates trigger the `dense_only_fallback` path. One conditional + one test.
4. **F3 (MEDIUM) fourth** — add the LaTeX-input AC1 test.
5. **F5 (LOW) — opportunistic** — widen `except` to include `RecursionError`.
6. **F6, F7 (LOW)** — fold into a future cleanup pass; not worth a separate rect commit.

No hash anchors need to move for any of these fixes (none change the `tools/list` bytes, the system prompt, or the schema version). A single `rect(server,ingest): ...` commit is appropriate.

---

## Rectification status (Phase 4 fills this in)

| Finding | Severity | Status |
|---|---|---|
| F1 — tail-text dropped | HIGH | _pending_ |
| F2 — case mismatch | HIGH | _pending_ |
| F3 — AC1 LaTeX-path test missing | MEDIUM | _pending_ |
| F4 — `ted_fused` on all-NULL trees | MEDIUM | _pending_ |
| F5 — unbounded recursion on stored tree | LOW | _pending_ |
| F6 — indexer hard-codes schema | LOW | _pending_ |
| F7 — duplicate `lancedb.connect` in startup | LOW | _pending_ |

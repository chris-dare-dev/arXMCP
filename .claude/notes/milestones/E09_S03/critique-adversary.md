# Critique — E09_S03

**Critic:** adversary
**Generated:** 2026-05-10T00:00:00Z
**Commit range:** e5ecbee..d10157d
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — implementation is functionally sound and 8/8 ACs
  are addressed, but two ACs (#2 and #3) lack non-vacuous depth=2
  test coverage in the `cited_by` and `depends_on` directions, and
  AC#7 (`chunk_id=None` for graph-only papers) is tested only via
  the `lancedb_path=None` shortcut, not via a real LanceDB where the
  paper is genuinely missing. These are missing-test gaps, not
  shipping bugs.
- Finding count: 0 CRITICAL, 2 HIGH, 5 MEDIUM, 3 LOW.
- Highest-risk file: `tests/test_graph_queries.py:298-309` — the
  AC#7 test as written would pass even if the LanceDB path branch
  were wholly unreachable.
- Cross-axis pattern: the test surface privileges `direction="cites"`
  at depth-2 and exercises the other two directions only at depth-1
  or via direction-filter unit tests — depth-2 + dedup behavior in
  `cited_by` / `depends_on` is unverified.
- No schema mutation; `KUZU_SCHEMA_VERSION` correctly stays at 2 —
  cache byte-stability is preserved (axis 1 clean).
- No HTTP, no MCP-tool wiring this milestone — security threat
  model is narrowed to `kuzudb_path` / `chunk_id` validation, both
  of which have at least the input-side regex (`paper_id_from_chunk_id`)
  on the chunk_id surface. `kuzudb_path` is unvalidated but the
  function isn't yet wrapped by an MCP handler — see F2.
- Local-first + Docker (axis 5) clean: Kùzu is embedded, LanceDB is
  local, no new runtime deps, no network calls.
- F-finding inheritance (the implementation summary's claim that
  every E09_S01/S02 closed finding was re-applied) holds up to
  inspection: no schema mutation, atomic checkpoint, paper_id
  validation before I/O, no multi-source-write, etc. — see "What
  was done well."

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — AC#7 test exercises only the `lancedb_path=None` shortcut

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_graph_queries.py:298-309
- **What:** `test_chunk_id_none_when_lancedb_path_none` calls
  `cite_neighbors(..., lancedb_path=None)` and asserts every
  neighbor's `chunk_id is None`. The function's implementation
  returns the all-None dict immediately when `lancedb_path is None`
  (`server/graph_queries.py:246-247`), so this test passes even if
  the real-LanceDB-but-paper-missing branch is broken.
- **Why it matters:** AC#7 is "Papers in graph but not in chunked
  corpus return chunk_id=None." The intended branch is
  `_lookup_chunk_ids_for_papers` querying a real LanceDB and finding
  no row for some `paper_id`. That branch (lines 261-289) is
  currently UNCOVERED by any test. A regression where, say, the
  arrow grouping logic accidentally filled `out[paper_id]` with a
  garbage value for a missing paper would not be caught.
- **Proposed fix:** add a sibling test
  `test_chunk_id_none_when_paper_missing_from_lancedb` that builds a
  tiny LanceDB chunks table containing chunks for paper P_B (only),
  then runs `cite_neighbors(CHUNK_A, depth=1, direction="cites")`
  with `lancedb_path` pointing at that tiny table. Expected: P_B
  has a `chunk_id`, P_C has `chunk_id=None`.
- **Regression guard:** the new test above; assertion must verify
  that `out[P_C] is None` AND `out[P_B] is not None` simultaneously
  so a future regression in either branch fails non-vacuously.

### F2 — `cite_neighbors` accepts an unvalidated `kuzudb_path`

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/graph_queries.py:308, 340
- **What:** `cite_neighbors(..., kuzudb_path: str | Path = ...)`
  passes the path straight to `kuzu.Database(str(Path(kuzudb_path)))`
  with no allowlist or normalization. The library function is
  intended to be wrapped by an MCP-tool handler in E06_S04 / E09_S04,
  at which point the path argument MUST NOT be agent-controllable.
- **Why it matters:** Threat 1 (`08-security-observability-ops.md`)
  treats agent-supplied tool inputs as attacker-controlled. If the
  E06_S04 wrapper passes `kuzudb_path` through from the JSON args,
  an LLM that has been prompt-injected can read any Kùzu DB on the
  filesystem (and `kuzu.Database` will create the directory if it
  doesn't exist — a write side effect). Today this is latent
  because no MCP wrapper exists; locking the contract NOW prevents
  a downstream regression.
- **Proposed fix:** in the docstring AND via assertion at the top
  of `cite_neighbors`, require that `kuzudb_path` be either the
  default constant or a path under `Path("var/arxmcp/index").resolve()`.
  Example:

  ```python
  resolved = Path(kuzudb_path).resolve()
  allowed_root = Path("var/arxmcp/index").resolve()
  if not _is_under(resolved, allowed_root):
      raise ValueError(f"kuzudb_path must be under var/arxmcp/index/")
  ```

  Document explicitly that the MCP-tool wrapper (E06_S04) must NOT
  expose `kuzudb_path` to agent JSON args — derive it from
  `Resources` instead.
- **Regression guard:** add `tests/test_graph_queries.py::TestPathValidation::test_kuzudb_path_outside_var_rejected`
  that calls `cite_neighbors(CHUNK_A, kuzudb_path="/tmp/evil")`
  and asserts ValueError.

### F3 — No depth=2 test for `direction="cited_by"`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_graph_queries.py:233-248
- **What:** AC#3 says "direction='cited_by' returns incoming edges"
  and AC#2 says "depth=2 returns hop-1 and hop-2 with correct
  hop_distance values." The existing `cited_by` test only exercises
  depth=1. The arrow-reversal in `_build_query("cited_by", 2)` is
  unit-tested for syntactic shape but not exercised end-to-end.
- **Why it matters:** the 5-paper fixture has only one incoming
  edge to A (E→A) so depth=2 cited_by would also return E (no
  hop-2 incoming). Adding a test would still pin the code path
  and surface any regression in arrow-reversal + dedup.
- **Proposed fix:** add `test_cited_by_depth_2_returns_hop1_and_no_hop2`
  that calls `cite_neighbors(CHUNK_A, depth=2, direction="cited_by")`
  and asserts `[n.paper_id for n in result] == [P_E]` and
  `result[0].hop_distance == 1`. (The fixture has no hop-2 incoming;
  asserting that explicitly is non-vacuous.)
- **Regression guard:** the test above.

### F4 — No depth=2 test for `direction="depends_on"`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_graph_queries.py:251-273
- **What:** `depends_on` direction is the most semantically novel
  branch (it KEEPS intra-paper edges and self-loops). The depth=2
  case is interesting because it interacts with the A→A self-loop:
  the path A→A→B is a valid `depends_on` path (the intra-paper
  hop is allowed) but B is also reachable via A→B at depth=1 — the
  dedup logic must keep the depth=1 hit.
- **Why it matters:** the implementation summary § "Implementation
  choices for Phase 3 to scrutinize" item 3 explicitly calls out
  this case: "the self-loop excluding only fires when the RESULT
  paper equals the source paper" — but nothing in the test surface
  exercises the A→A→B traversal. A regression in
  `_row_passes_direction_filter` for `depends_on` would not be
  caught.
- **Proposed fix:** add `test_depends_on_depth_2_dedups_self_loop_paths`
  that calls `cite_neighbors(CHUNK_A, depth=2, direction="depends_on")`
  and asserts:
    - P_A is in the result with `edge_kind="ref"` and
      `hop_distance=1` (the direct self-loop wins);
    - P_B and P_C appear with `hop_distance=1` (direct cites edges,
      not via A→A→B/C);
    - P_D appears with `hop_distance=2`.
- **Regression guard:** the test above.

### F5 — `_lookup_chunk_ids_for_papers` priority logic untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/graph_queries.py:271-289 (logic) + tests/test_graph_queries.py (no test)
- **What:** the `kind="stmt"` priority list with fallback to
  `lemma > proposition > corollary > definition > remark` is a
  documented deviation from the brief (implementation summary
  § "Deviations from the brief" item 5). The implementation sorts
  hits by `(rank, chunk_id)` and picks the smallest. Neither the
  fallback path NOR the tie-break is exercised.
- **Why it matters:** R2's research recommendation was specifically
  about expository math papers that have no `kind="stmt"` chunk.
  If a future refactor of `_REPRESENTATIVE_KIND_PRIORITY` swapped
  ranks or omitted a kind, no test would catch it.
- **Proposed fix:** add a test that builds a LanceDB with a paper
  whose only chunks are `kind="lemma"` and asserts the lookup
  returns the lemma chunk_id (not None). Add a second test where
  two `kind="stmt"` chunks exist; assert lexicographic tie-break.
- **Regression guard:** the two tests above.

### F6 — `_resolved_labels_for_paper` opens LanceDB once per paper

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/intra_paper_refs.py:181-227
- **What:** `process_paper` calls `_resolved_labels_for_paper(...)`
  which itself calls `open_chunks_table(...)` (line 207) — once
  per paper. For an N-paper ingest pass, LanceDB is reopened N
  times, which (per the `open_chunks_table` contract in
  `server/corpus.py`) involves a corpus-version marker check and
  table-handle materialization.
- **Why it matters:** at Tier-3 scale (≤ 50 papers) this is a
  micro-cost; at the production scale this milestone is intended
  to support (any number of seeded papers), the per-paper
  re-open multiplies wall-clock by 10x-100x. The implementation
  summary explicitly claims "single batched LanceDB query" for
  the graph-query path (which IS batched) but NOT for the ingest
  path.
- **Proposed fix:** hoist `open_chunks_table(...)` out of
  `_resolved_labels_for_paper` and into `ingest()`; pass the
  table handle into `process_paper`. This also fixes the
  invariant that the same table version is queried for every
  paper in one pass.
- **Regression guard:** assert in the ingest test that
  `open_chunks_table` is called exactly once per `ingest()`
  invocation (mock + assertion via `unittest.mock.patch`).

### F7 — `_list_paper_ids_from_lancedb` uses unbounded `limit(1_000_000)`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/intra_paper_refs.py:394
- **What:** the CLI default-paper enumeration uses
  `table.search().limit(1_000_000).to_arrow()`. A Tier-3 corpus is
  ~50 papers and well under this bound, but the constant is a
  silent ceiling: a future Tier-4 corpus with > 1M chunks would
  silently truncate.
- **Why it matters:** silent truncation is the worst class of
  bug — it presents as "ingest pass completed successfully" while
  some papers are quietly skipped. The fix is trivial: stream via
  pagination or assert the row count is below the cap.
- **Proposed fix:** replace the `.limit(1_000_000)` with a paged
  loop (LanceDB supports `.offset(...)`) OR query the full row
  count first and assert it < cap before fetching. At minimum
  raise a `RuntimeError` if `len(arrow) == 1_000_000` (the
  saturation case).
- **Regression guard:** N/A in this milestone (the function isn't
  exercised by any test); add a unit test that mocks the LanceDB
  row count and asserts the saturation-case error.

### F8 — Invalid `direction` strings silently route to "cites"-like

- **Severity:** LOW
- **Source:** adversary
- **File:** server/graph_queries.py:111, 168, 204
- **What:** `direction` is typed as `Literal["cites", "cited_by",
  "depends_on"]` but Python doesn't enforce this at runtime. A
  caller passing `direction="other"` would: take the outgoing
  arrow path (`_build_query`), apply the non-`depends_on`
  intra-paper filter, and get `edge_kind="cites"` — silently
  degrading to "cites"-like behavior.
- **Why it matters:** if the MCP-tool wrapper (E06_S04) passes
  agent-supplied JSON `direction` through, this silent fall-through
  hides a typo / prompt-injection. The fix is one early `if
  direction not in {"cites","cited_by","depends_on"}: raise`.
- **Proposed fix:** at the top of `cite_neighbors`, after the
  `chunk_id` parse:

  ```python
  if direction not in ("cites", "cited_by", "depends_on"):
      raise ValueError(f"direction must be one of cites/cited_by/depends_on, got {direction!r}")
  ```
- **Regression guard:** add `test_invalid_direction_raises` to
  the input-validation suite.

### F9 — `_extract_intrapaper_labels` returns bibliography refs

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/intra_paper_refs.py:116-144
- **What:** the BeautifulSoup walk extracts every
  `<a class="ltx_ref" href="#X">` regardless of whether `X` is a
  theorem label or a bibliography entry. The brief says "intra-paper
  `\ref{}` chain" — `\cite{}` rendering also uses `class="ltx_ref"`
  in LaTeXML output. The downstream `theorem_label` LanceDB
  filter drops bibliography refs, so the BUG in the data flow is
  benign, but `raw_ref_count` returned by `_IntraPaperResult`
  conflates the two and the test on
  `tests/test_intra_paper_refs.py:164` explicitly asserts
  `bib1` IS in labels — locking in the over-extraction as
  intended behavior.
- **Why it matters:** the over-extraction is documented and
  filtered downstream; this is a comment-clarity issue. A future
  reader inspecting `raw_ref_count` for telemetry would
  systematically over-count. The fix is to filter
  `class="ltx_bibref"` (the bibliography variant) at extraction.
- **Proposed fix:** in the BS4 walk, also exclude anchors whose
  class set contains `"ltx_bibref"`:

  ```python
  classes = anchor.get("class") or []
  if "ltx_bibref" in classes:
      continue
  ```

  Update the test fixture comment to match.
- **Regression guard:** existing `test_extracts_intra_paper_anchor_hrefs`
  must invert the `bib1` assertion to `assert "bib1" not in labels`.

### F10 — `_result_source` returns `("", 0.0)` for empty rels

- **Severity:** LOW
- **Source:** adversary
- **File:** server/graph_queries.py:186-189
- **What:** if `rels` is empty (which the comment claims "should
  never happen"), `_result_source` returns `("", 0.0)`. The
  CitationNeighbor dataclass would then carry a non-recognizable
  source string and a 0.0 confidence — fed to a downstream agent,
  this is indistinguishable from a real "low-confidence" edge.
- **Why it matters:** if the impossible-but-defensive case ever
  fires (e.g. a Kùzu-version migration that stops populating
  `relationships(p)` correctly), the agent silently treats a
  null-source edge as legitimate. Better: filter the row out.
- **Proposed fix:** in the dedup loop, skip rows where `rels` is
  empty:

  ```python
  if not rels:
      logger.warning("path with no rels: %s -> %s", paper_id, neighbor_paper_id)
      continue
  ```
- **Regression guard:** unit test that constructs an empty rels
  list and asserts the row is excluded.

## What was done well

- 8/8 brief ACs addressed with non-trivial unit tests for the
  primary direction (`cites`) at both depths; test count delta
  (+41 tests, 1294 passing) is generous.
- `paper_id_from_chunk_id` correctly delegates to the single-source-
  of-truth regex in `ingest.identifiers` rather than re-inlining a
  fresh regex (closes the F11 spirit from E06_S03 critique). The
  helper validates BOTH non-string AND malformed-string input
  with explicit `ValueError`.
- The `kind="stmt"` priority-list deviation is well-rationalized
  in the implementation summary AND documented in the function
  docstring. R2's expository-math edge case is a legitimate
  operational concern, not gold-plating.
- `KUZU_SCHEMA_VERSION` correctly stays at 2 — no schema mutation,
  preserving the F6 invariant inherited from E09_S01/S02 and
  keeping cache byte-stability intact.
- The `_merge_cite` helper is correctly reused for the intra-paper
  self-edge — closing F4 (multi-source-write) by going through
  the rel-table-only write path with `MERGE` keyed on
  `(src, dst, source)`.
- Self-loop filter logic correctly distinguishes
  "neighbor==source" (filter for cites/cited_by) from
  "intermediate==source" (don't filter — A→A→B is a real depth-2
  path for `depends_on`).
- `_row_passes_direction_filter` uses Python-side filtering for
  `cites`/`cited_by` because Kùzu 0.11.3's `ALL(r IN rels ...)`
  predicate fails on recursive-rel bindings — the workaround is
  documented, the alternative is verified-impossible.
- Atomic checkpoint discipline is preserved: `save_checkpoint`
  reuse, `parse_failures` tracking with non-zero exit (F3 spirit),
  no `_tmp` left behind (test verifies).
- `MAX_HTML_BYTES = 50 MiB` cap on parsed HTML reads — Threat 7
  (source ingestion) mitigation, even though no HTTP is involved.
- `_escape_sql` mirrors the existing `_escape` pattern in
  `server.handlers.paper` — no SQL-injection drift introduced.

## Recommended rectification order

1. **F1 + F3 + F4** (test gaps for the AC battery). Adding three
   missing-direction × depth tests is the cheapest highest-leverage
   fix. They share fixtures and are independent of any code edit.
2. **F2** (`kuzudb_path` validation). Locking the contract NOW
   before E06_S04 wires it to JSON args is much cheaper than
   rolling it back later.
3. **F8** (invalid `direction` early-raise). One line in
   `cite_neighbors`, one test. Same reasoning as F2.
4. **F6** (per-paper LanceDB re-open). Hoist the table handle
   into `ingest()`; mid-effort but non-controversial.
5. **F5** (priority-list test). Two new tests, no production code
   change.
6. **F7** (`limit(1_000_000)` foot-gun). Defer if Tier-3 is the
   only deployment target; flag otherwise.
7. **F9 + F10** (extractor over-fetch + empty-rels defaults). LOW
   severity; defer unless trivially included in the same PR.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->

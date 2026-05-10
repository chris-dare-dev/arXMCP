# E09_S03 — Research brief 2

**Milestone:** `cite_neighbors(chunk_id, depth, direction)` graph traversal +
intra-paper `\ref{}` ingest pass.

---

## 1. In-codebase context (load-bearing constraints)

**LanceDB chunks schema (`ingest/schema.py`).** `kind` is free-form
`pa.utf8()`; the chunker emits `"stmt"`, `"proof"`, `"lemma"`,
`"proposition"`, `"corollary"`, `"definition"`, `"remark"`, … (see
`ingest/chunker.py:_THEOREM_ENV_KINDS`, lines 154-188). The brief's
"first `kind="stmt"`" rule misses papers with only lemma/definition
chunks. Treat as **best-effort**: fall back to first theorem-kind
chunk before declaring `chunk_id=None`.

`theorem_label` is a real column (schema.py:79) populated by
`_extract_theorem_label`: returns the LaTeXML element `id` IFF the id
is NOT auto-generated (`_AUTO_ID_RE` rejects `S1.SS1.Thmtheorem2`).
Labels exist only when the author wrote `\label{}` — exactly what
`\ref{}` consumes. **No schema mutation needed.**

**Identifiers (`ingest/identifiers.py`).** `chunk_id` format is
`"arxiv:" + PAPER_ID_PATTERN + ":" + [0-9a-f]{16}`. There is **no
helper to parse paper_id out of a chunk_id** — `is_valid_chunk_id`
only validates. Recommend: add `paper_id_from_chunk_id(chunk_id) ->
str` to `ingest/identifiers.py` (F11 discipline: one source of truth).

**Open-table pattern.** `server/handlers/{chunk,paper}.py` use
`get_resources().chunks_table.search().where(...).to_arrow()` — they
don't call `open_chunks_table` directly; that's the cold-start
primitive (one-time at startup per `server/corpus.py` docstring).
For `cite_neighbors`, the same discipline applies to Kùzu: opening
`kuzu.Database` per call is wasteful. **Cache `kuzu.Connection` on
`Resources`**, keyed on `kuzudb_path` + schema version
(`ingest.kuzudb_schema.read_schema_version`).

**`Config.kuzudb_path` is missing.** `server/config.py` has
`lancedb_path` and `cache_db_path` but no `kuzudb_path`. **Add
`kuzudb_path: Path = Path("var/arxmcp/index/kuzu")` to `Config`** —
env var `ARXMCP_KUZUDB_PATH` becomes the override knob. The brief's
function-arg shape is fine for the **library API**; the MCP-tool
wrapper (E06_S04) MUST read from Config, never from agent input
(Threat 1 / path-traversal, `08-security-observability-ops.md`).

**Conftest pattern.** Autouse fixtures use either
`monkeypatch.setattr(mod, "PATH_CONST", ...)` for module constants OR
`monkeypatch.setenv("ARXMCP_*", ...)` for Config defaults. For
E09_S03 library-function tests, pass `tmp_path` directly;
`test_graph_ingest.py` is the template (5-paper mocked corpus with
A→B→C cycle). MCP-boundary tests (`test_tools_all.py` — `TestClient`
+ lifespan + `_seed_corpus`) are E06_S04's concern, not this milestone.

**LaTeXML `\ref{}` rendering.** No live fixture in the repo carries a
`\ref{}` — the two parsed papers under `var/arxmcp/corpus/parsed/` are
near-empty stubs and `tests/fixtures/chunker/` has no `ltx_ref`
classes (verified). Per LaTeXML 0.8.x docs (the chunker's footer
comment confirms `LaTeXML (version 0.8.8)`), `\ref{foo}` becomes `<a
class="ltx_ref" href="#foo" title="..."><span
class="ltx_text">3.1</span></a>`. The intra-paper pass should walk
BeautifulSoup for `<a class*="ltx_ref">`, extract `href`, strip `#`,
and filter out hrefs containing `/` or starting with `http` (external
links, not intra-paper labels).

---

## 2. Prior decisions and lessons

**Path resolution.** E09_S01 synthesis §2.1: *"Follow the design
notes — `var/arxmcp/index/kuzu/`. […] Only the brief's AC text uses
`kuzudb/`."* E09_S03's brief signature default
`"var/arxmcp/index/kuzudb/"` repeats the same drift. **Use
`var/arxmcp/index/kuzu/`** — match Makefile + design notes + live
E09_S01/S02 code; document the brief drift in the implementation
summary as a docs-PR follow-up.

**F-finding inheritance from E09_S01/S02.**

- **F9 (E09_S01 deferred): `papers.categories` carries OpenAlex Topic
  display names.** Does NOT affect `cite_neighbors` (returns paper_id
  + chunk_id, not categories); fixture corpora must not rely on it.
- **Source-casing: `"openAlex"` / `"inspire"` / `"intra-paper"`.**
  `_merge_cite` writes these literal strings (`graph_ingest.py:621`).
  **Surface raw values in this milestone** — cheaper, doesn't create
  a new normalization seam, doesn't mask the deferred F-finding.
  Document in the docstring that case-folding belongs at the agent
  layer.

**Atomic checkpoint discipline.** Every E09 ingest pass writes JSON
via `tmp + os.replace` and records `resolved` / `edges_done` /
`fetch_failures`. Intra-paper ref-chain pass follows the same shape:
`var/arxmcp/ops/intra-paper-refs-checkpoint.json` with `processed`,
`edges_added`, `parse_failures`. Small but required.

**Kùzu 0.11.3 archived-but-pinned** (`pyproject.toml: "kuzu==0.11.3"`).
**Verified live (§3)**: `[:cites*1..N]` works, `length(path)` works,
self-loops are queryable, but `[rel IN r | rel.source]` fails with
`Binder exception: Variable rel is not in scope` — Kùzu 0.11.3 does
NOT bind relationship variables inside list comprehensions. Per-edge
metadata is NOT directly accessible on multi-hop matches.
**Recommend: execute depth=1 and depth=2 as separate queries** —
cost is negligible (≤50 results) and source/confidence stays
per-hop accurate.

---

## 3. External sources (verified live, Kùzu 0.11.3)

Live test in `/tmp/_kuzu_test` against `kuzu==0.11.3`:

```
=== TEST 1: [:cites*1..2] outgoing from A ===  → ['C'], ['C'], ['E'], ['B']
=== TEST 2: MATCH p = … RETURN b.paper_id, length(p) AS hop ===
                    → ['C', 2], ['C', 2], ['E', 1], ['B', 1]
=== TEST 3: [r:cites*1..2] … length(r) AS hop ===   → identical to #2
=== TEST 4: cited_by — (n)-[r:cites*1..2]->(target {C}) ===
                    → ['A', 2], ['A', 2], ['E', 1], ['B', 1]
=== TEST 5: self-loop (A->A added) — A->[r*1..2]->b ===
                    → C(2), A(2), A(1), E(2), E(1), B(2), B(1)
=== TEST 6: [rel IN r | rel.source] AS sources ===
                    → ERR: Binder exception: Variable rel is not in scope
```

**Findings.** (1) `[:cites*1..N]` works and is the right form;
**relationship-type elision (`[*1..N]`) is unnecessary** — keep the
explicit type. (2) `length(p)` AND `length(r)` both return the hop
count; either is fine. (3) `cited_by` is implemented by reversing the
arrow: `(n)-[r:cites*1..2]->(target)` with the target's `paper_id`
bound — verified. (4) Self-loops ARE allowed and ARE traversed by the
variable-length path, so a paper that cites itself shows up as a
hop=1 neighbor of itself. (5) **Result deduplication is required** —
test 1 returns `'C'` twice because A→B→C and A→E→C are two distinct
paths to the same paper at depth 2. Kùzu does not auto-dedupe;
`cite_neighbors` must apply `min()` over hop_distance keyed on
paper_id (return the shorter path) and dedupe before applying
`max_results`. (6) `[rel IN r | rel.source]` does not work in 0.11.3,
so per-edge properties on multi-hop paths are **not extractable in a
single query**.

**LaTeXML `\ref{}` rendering.** The repo's parsed fixtures are too
sparse to confirm empirically; per LaTeXML 0.8.x documented output the
form is `<a class="ltx_ref" href="#<label>" title="..."><span
class="ltx_text">…</span></a>`. The chunker version pinned in this
project (per `ingest/chunker_types.py`) renders LaTeXML 0.8.8 (visible
in the parsed-file footer comment line: *"Generated on Wed May 6
20:53:28 2026 by LaTeXML (version 0.8.8)"*). A larger fixture (a
real arXiv paper passed through LaTeXML) is needed to lock the regex;
recommend committing one as part of the milestone deliverable
(`tests/fixtures/intra_refs/<paper_id>/index.html`).

---

## Open questions

- **`CitationNeighbor.chunk_id` type.** Pick **`str | None`**. The
  risk-note says *"`chunk_id` is returned as `None`"*; the dataclass
  declaration `chunk_id: str` is inconsistent. Use `str | None` and
  document that None means "graph-only paper; call
  `get_chunk(paper_id=…)` for the fallback." Best-effort
  `kind="stmt"` lookup with fallback to any theorem-kind chunk first.
- **`direction="depends_on"` semantics.** Pick **"intra-paper
  primarily, fall back to outgoing `cites` for cross-paper hops"**.
  Traverse `cites` edges with `source="intra-paper"` first; if depth
  budget remains, follow any `cites` edge. `edge_kind="ref"` for
  intra-paper, `"cites"` for fallback — gives the agent enough
  signal without a second tool call.
- **Intra-paper checkpoint.** **Yes** — `var/arxmcp/ops/intra-paper-
  refs-checkpoint.json` with `processed`, `edges_added`,
  `parse_failures`. Mirrors `graph_ingest`'s shape; required by the
  discipline.
- **Async `cite_neighbors`.** **Yes — `async def`** even though
  Kùzu's driver is sync. Matches `server/handlers/*` convention
  (every handler is `async def handle_…`), avoids a
  `run_in_executor` band-aid in E06_S04. Use
  `asyncio.to_thread(conn.execute, …)` internally.
- **Variable-length form.** `[:cites*1..2]` — explicit type, no
  binding. Do NOT use `[*1..2]` (rel-type elision); only one rel
  type today, but elision silently includes any future rel type.
- **`cited_by` direction.** Verified: `MATCH (n:papers)-
  [r:cites*1..2]->(target:papers {paper_id: $id}) RETURN
  n.paper_id, length(r) AS hop` works in Kùzu 0.11.3.
- **Self-loops.** Kùzu 0.11.3 ALLOWS them and includes them in
  variable-length matches. Intra-paper ingest creates
  `(p)-[:cites]->(p)` with `source="intra-paper"`. **Filter
  self-loops out for `direction="cites"`/`"cited_by"`** (a paper
  does not "cite itself" in the outward sense), **keep them for
  `direction="depends_on"`** (intra-paper dep IS the self-loop).
- **`theorem_label` column existence.** Already exists (§1). Intra-
  paper ingest reads `theorem_label` from chunks AND re-walks
  `var/arxmcp/corpus/parsed/<paper_id>/index.html` for
  `<a class="ltx_ref" href="#<label>">` — the chunker doesn't
  preserve per-chunk DOM ranges so re-parse is unavoidable.
- **Result deduplication at depth=2.** **Dedupe** — keep smallest
  `hop_distance` per `paper_id`. Verified live: Kùzu returns `'C'`
  twice on A→B→C and A→E→C. Apply `min()` BEFORE `max_results` —
  otherwise the cap can silently shadow distinct papers. Also:
  exclude the source paper from results (handles the
  intra-paper-self-loop case).

---

## External writes the implementation will require

| Write | Path / target | Trigger |
|---|---|---|
| Kùzu `MERGE` of `cites` edges, `source="intra-paper"`, `confidence=1.0` | `var/arxmcp/index/kuzu/` | Intra-paper ref-chain CLI run |
| Atomic checkpoint JSON | `var/arxmcp/ops/intra-paper-refs-checkpoint.json` | Intra-paper ref-chain CLI run, after each batch |
| Optional new test fixture | `tests/fixtures/intra_refs/<paper_id>/index.html` | Test fixture for `\ref{}` parsing |
| Optional `paper_id_from_chunk_id` helper added to `ingest/identifiers.py` | (existing file) | Code change, not a runtime write |
| Optional `kuzudb_path` field added to `server/config.py` | (existing file) | Code change, not a runtime write |

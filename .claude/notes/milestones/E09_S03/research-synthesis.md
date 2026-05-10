# E09_S03 Research Synthesis

**Milestone:** `cite_neighbors(chunk_id, depth, direction)` graph
traversal + intra-paper `\ref{}` ingest pass.
**Inputs merged:** [research-brief-1.md](research-brief-1.md),
[research-brief-2.md](research-brief-2.md).
**Date:** 2026-05-10.

Both researchers verified Kùzu 0.11.3 behavior live in tmp DBs; their
findings agree on most operational facts. Disagreements are minor —
mostly about which Cypher form to use and whether the per-hop edge
metadata can be extracted in a single query. The synthesis picks the
simpler/safer path on each disagreement and flags Phase-2 verification
items.

---

## 1. Vendor facts both researchers verified live

| fact | result |
|---|---|
| `[:cites*1..N]` variable-length path works | ✅ both confirm |
| `length(p)` returns the hop count for `MATCH p = ...` | ✅ both confirm; `length(r)` also works (R2) |
| `cited_by` direction = reverse arrow: `(n)-[r:cites*1..N]->(target)` with `target.paper_id` bound | ✅ both confirm |
| Self-loops are stored AND traversed by variable-length path | ✅ both confirm |
| Same paper reachable via multiple paths returns multiple rows | ✅ both confirm — dedup is required |
| `[rel IN r \| rel.source]` list-comp on relationship variables | ❌ R2 confirms FAILS (`Binder exception`) |
| `relationships(p)` projection function | R1 says ✅ works; R2 not tested |
| `MIN(length(p))` aggregation in Cypher | R1 says ✅ works |
| `ORDER BY ... LIMIT` at the Cypher layer | R1 says ✅ works |
| `var/arxmcp/index/kuzu/` (vs brief's `kuzudb/`) | both recommend follow E09_S01/S02 — `kuzu/` |

**Phase-2 verification needed**: R1's claim that `relationships(p)`
projection works (returns list of edge dicts with `source` /
`confidence` accessible). R2's negative result is on the list-comp
form, not the function-call form — these are different. Implementer
must verify before relying on per-hop metadata extraction.

---

## 2. CRITICAL Kùzu finding — per-hop metadata on multi-hop paths

R2's live test:

```
MATCH p = (s:papers {paper_id: 'A'})-[r:cites*1..2]->(n:papers)
RETURN n.paper_id, [rel IN r | rel.source]
=> Binder exception: Variable rel is not in scope
```

Kùzu 0.11.3 does NOT support relationship-list comprehensions on
variable-length-path bindings. This means **per-hop `source` /
`confidence` on a depth=2 path is not directly extractable in the
natural openCypher way.**

R1's claim is that `relationships(p)` (the function form, applied to
a path variable bound via `MATCH p = ...`) works. If true, the
implementer can extract a list of relationship objects from each
result row.

**Decision tree for the implementer:**

1. **Try `relationships(p)`** first. If it returns a list of dicts
   with `source` and `confidence` accessible, use it; the dataclass
   `source` field for hop=2 results is the LAST element of the
   list (the edge closest to the result paper — symmetric with
   `cited_by` direction semantics).
2. **If `relationships(p)` doesn't work**, run TWO separate queries:
   - depth=1: `MATCH (s)-[r:cites]->(n)` returns r.source /
     r.confidence directly. Trivially correct.
   - depth=2-only-via-2-hops: `MATCH (s)-[r1:cites]->(m)-[r2:cites]->(n)
     WHERE n <> s AND m <> s` returns `r1`, `r2` as bound vars.
     Pick `r2.source` / `r2.confidence` as the result's source
     (last-hop semantics).
   - Merge results, dedupe by `paper_id` with min(hop), apply
     `max_results`.

**Recommendation: write the simpler two-query form first**
(option 2). It's verified to work, doesn't depend on
`relationships()`, and is straightforward to understand. If
performance becomes an issue at production scale (>10k papers), the
implementer can revisit. For Tier-3 (50 seed papers) the cost is
trivial.

---

## 3. Path-name drift (same as E09_S01/S02)

Brief signature: `kuzudb_path: str = "var/arxmcp/index/kuzudb/"`.
Existing repo state (Makefile bootstrap + design notes + E09_S01/S02
shipped code): `var/arxmcp/index/kuzu/`. Both researchers recommend
following the existing path.

**Resolution:** ship `kuzudb_path: str = "var/arxmcp/index/kuzu/"`
(keep the parameter NAME `kuzudb_path` to minimize diff, but its
default VALUE is `kuzu/`). Document the brief drift in the function
docstring exactly as `ingest/kuzudb_schema.py:6-13` does.

---

## 4. `CitationNeighbor` dataclass — the type adjustments

The brief's signature has `chunk_id: str` but explicitly says "Papers
in the graph but not in the chunked corpus return `chunk_id=None`."
Both researchers flag this; both pick `chunk_id: str | None`.

Final shape:

```python
@dataclass(frozen=True)
class CitationNeighbor:
    chunk_id: str | None        # None when paper isn't in chunked corpus
    paper_id: str               # arXiv ID
    edge_kind: str              # "cites" | "cited_by" | "ref"
    hop_distance: int           # 1 or 2
    source: str                 # raw rel.source value: "openAlex" | "inspire" | "intra-paper"
    confidence: float           # rel.confidence
```

Frozen for hashability + immutability — matches the project's
`_ResolvedWork` / `_ResolvedInspire` dataclass discipline.

---

## 5. `direction` semantics — final decisions

Three direction modes; both researchers converged on:

- **`"cites"`**: outgoing edges; FILTER OUT `source = "intra-paper"`
  edges in the WHERE clause (intra-paper edges represent
  proof-dependency relations, not citations); FILTER OUT self-loops
  in result post-processing.
- **`"cited_by"`**: incoming edges; same filters.
- **`"depends_on"`**: KEEP `source = "intra-paper"` edges (this is the
  whole point of the direction); KEEP self-loops; for cross-paper
  fallback (when an intra-paper hop crosses into a different paper —
  rare but the brief specifies this), follow ANY `cites` edge type
  with the brief-specified `edge_kind="cites"` annotation.

**Edge_kind annotation per result row:**

- `edge_kind="ref"` when the result row's last hop has
  `source="intra-paper"`.
- `edge_kind="cited_by"` when the query direction is `cited_by`.
- `edge_kind="cites"` otherwise.

This gives the agent enough signal to know which kind of relation
the neighbor came from without needing a follow-up query.

---

## 6. Result deduplication + ordering

R2 verified: Kùzu 0.11.3 returns the same `paper_id` multiple times
when reachable via multiple paths (e.g. A→B→C and A→D→C). Dedup
is mandatory.

**Algorithm:**

1. Run the Cypher query (or the two-query variant from §2).
2. Build a Python dict `{paper_id: (chunk_id, hop_distance, source,
   confidence)}` keyed on paper_id; keep the row with smallest
   `hop_distance` (ties broken by lexicographic paper_id, but
   the row contents are nearly identical so the choice doesn't
   matter much in practice).
3. Filter self-loops (where `paper_id == source_paper_id`) for
   `cites` / `cited_by` directions; keep them for `depends_on`.
4. Sort by `(hop_distance ASC, paper_id ASC)` for deterministic
   ordering.
5. Slice to `max_results=50`.
6. Map each remaining `paper_id` to its representative `chunk_id`
   via the LanceDB lookup (§7).

The `LIMIT 50` could be applied in Cypher AFTER `min(hop)`
aggregation, but doing it in Python lets us guarantee the dedup
and self-loop filter happen before the cap. **Apply max_results in
Python** for correctness.

---

## 7. `chunk_id` representative lookup (single batched query)

Both researchers recommend a single batched LanceDB query rather
than per-paper queries.

**Approach (R1's recommendation):**

```python
import pyarrow.compute as pc
table = get_resources().chunks_table
# Build SQL-style WHERE for batched filter
ids_csv = ",".join(f"'{pid}'" for pid in candidate_paper_ids)
arrow = (
    table.search()
    .where(f"paper_id IN ({ids_csv}) AND kind = 'stmt'", prefilter=True)
    .limit(len(candidate_paper_ids) * 5)  # generous; we'll group
    .to_arrow()
)
# Group by paper_id; pick lexicographically-first chunk_id per paper.
```

R2 added a useful enhancement: the brief's "first kind=stmt chunk"
rule misses papers with only `kind="lemma"` / `"definition"` /
`"corollary"` chunks (some math papers don't have a top-level
theorem-stmt chunk). **Best-effort fallback:** if no `kind="stmt"`
chunk exists for a paper, fall back to other theorem-kinds in
priority order:

```
priority = ["stmt", "lemma", "proposition", "corollary",
            "definition", "remark"]
```

Pick the first-priority kind that has at least one chunk for the
paper. If NO theorem-kind chunk exists, return `chunk_id=None`.

This is a Phase-2 implementation detail; the synthesis just states
the rule.

---

## 8. Intra-paper `\ref{}` ingest pass

**File: `ingest/intra_paper_refs.py`** (new).

**Approach (both researchers agree):**

1. For each paper in the chunked corpus (read from LanceDB), open
   `var/arxmcp/corpus/parsed/<paper_id>/index.html` (LaTeXML
   output).
2. BeautifulSoup-walk to find `<a class="ltx_ref" href="#<label>">`
   anchors. The chunker's confirmed LaTeXML output format is
   `<a class="ltx_ref" href="#<label>" title="...">...</a>`.
3. For each `<a>` element: strip the `#` from `href`, filter out
   external links (those with `/` or starting with `http`).
4. Look up the chunk with `paper_id == X AND theorem_label == href`
   in the LanceDB chunks table.
5. If found: emit a `cites` edge from `(papers {paper_id: X})` to
   `(papers {paper_id: X})` with `source="intra-paper"`,
   `confidence=1.0`. (This is a self-edge on the paper node;
   Kùzu 0.11.3 supports self-loops — verified by R2.)
6. CLI: `python -m ingest.intra_paper_refs --kuzudb ... --parsed-dir ...`.
7. Atomic-write checkpoint at
   `var/arxmcp/ops/intra-paper-refs-checkpoint.json` with
   `processed`, `edges_added`, `parse_failures` (mirrors E09_S01/S02
   discipline; per the F-finding inheritance rule).

**Note:** the brief frames intra-paper as `\ref{<theorem_label>}`
edges between *chunks*, but the Kùzu schema only has `papers`
nodes — there are no chunk nodes. So the edge is from paper-X to
paper-X (a self-edge), and the agent recovers the chunk-level info
by following up with `cite_neighbors(direction="depends_on")` and
then `get_chunk` on the resulting `chunk_id`s. This is a documented
limitation; expanding the schema to `chunk` nodes is out of scope
for E09_S03 (would require schema v3).

**`confidence=1.0`** for `source="intra-paper"`: R1 suggested 0.5
(static-analysis edges are weaker than curated citations); R2
suggested 1.0. **Pick 1.0** — `\ref{}` IS a curated reference (the
author wrote both the label and the ref); the static-analysis label
applies to the *extraction*, not the *evidence*. R1's lower value
would be appropriate if we extracted refs from raw text via NLP.

---

## 9. Identifier helper

R2 recommends adding `paper_id_from_chunk_id(chunk_id) -> str` to
`ingest/identifiers.py`:

```python
def paper_id_from_chunk_id(chunk_id: str) -> str:
    """Extract the paper_id segment from a chunk_id.

    chunk_id format is `arxiv:<paper_id>:<16-hex>`. This delegates
    to the same regex used by validation, so any drift would
    surface as both validation failure and a parsing failure
    here — single source of truth.
    """
    match = CHUNK_ID_RE.match(chunk_id)
    if not match:
        raise ValueError(...)
    return match.group(1)
```

R1 recommends inline regex parsing. R2's helper is cleaner — single
source of truth, can be tested, used by anyone needing the same
mapping. Pick R2's approach.

---

## 10. Async-vs-sync `cite_neighbors`

R2 recommends `async def cite_neighbors(...)` with internal
`asyncio.to_thread(conn.execute, ...)` so the function fits the
existing `server/handlers/*` async-handler convention. R1 silent.

**Pick R2:** make `cite_neighbors` an async function. Kùzu's driver
is sync; wrap each `conn.execute` in `asyncio.to_thread`.

**Caveat:** `Resources.kuzu_connection` (a new field on `server.resources.Resources`,
created in this milestone) is shared across requests — Kùzu's
single-connection-per-process safety model says read-only queries
are safe to share. If the implementer is unsure, opening a new
`kuzu.Connection` per call (against a shared `kuzu.Database`) is the
safe path; it's a few microseconds.

**Open: should `kuzu_connection` live on `Resources`?** R2 recommends
yes. R1 silent. For this milestone the function takes `kuzudb_path`
as an argument — adding to `Resources` couples the library function
to server-state and complicates the test fixture. **Defer the
`Resources` field to E06_S04** (the MCP-tool wiring milestone);
this milestone keeps `cite_neighbors` as a free function with an
explicit `kuzudb_path` argument.

---

## 11. F-finding inheritance from E09_S01/S02

The implementer must NOT re-introduce any closed finding:

- **F1 (CLI casing)**: the intra-paper CLI's argparse should follow
  the same case-insensitive pattern OR avoid `--source` entirely
  (E09_S02's F7 closure — drop the gratuitous flag). This module
  has nothing to dispatch on `--source` (only one source: `intra-paper`),
  so DROP the flag.
- **F2 (response cap)**: N/A — no HTTP calls in this milestone.
- **F3 (fetch failure tracking)**: N/A — operates on local files.
  Instead: track `parse_failures` (HTML missing, BeautifulSoup
  errors) the same way.
- **F4 (multi-source-write)**: not applicable — intra-paper writes
  ONLY to `cites` rel table, never to `papers` columns.
- **F5 (seed reader)**: N/A — iteration is over LanceDB chunks
  (`SELECT DISTINCT paper_id`).
- **F6 (schema version)**: NO schema mutation in this milestone —
  intra-paper edges fit the existing v2 schema. `KUZU_SCHEMA_VERSION`
  stays at 2.
- **F7 (atomic fs)**: reuse `graph_ingest.save_checkpoint`.
- **F8 (collision detection)**: N/A — no external IDs to collide on.
- **F10 (non-vacuous tests)**: every assertion must fail when
  production behavior is wrong.

---

## 12. Open questions consolidated

Items resolved in this synthesis:

1. ✅ `chunk_id → paper_id` mapping: new
   `ingest.identifiers.paper_id_from_chunk_id` helper.
2. ✅ `kuzudb_path` default: `var/arxmcp/index/kuzu/` (same as E09_S01/S02).
3. ✅ "First kind=stmt" lookup: single batched LanceDB query with
   priority-list fallback to other theorem kinds.
4. ✅ `depends_on` semantics: keep intra-paper edges; cross-paper
   fallback follows any `cites` edge type.
5. ✅ `cited_by` Cypher: `(n)-[:cites*1..2]->(target {paper_id: $id})`.
6. ✅ Source-string normalization: surface raw values; document the
   `"openAlex"` (camelCase) / `"inspire"` (lowercase) /
   `"intra-paper"` split.
7. ✅ `max_results` truncation: in Python, after dedup + filter +
   sort.
8. ✅ Result ordering: `(hop_distance ASC, paper_id ASC)`.
9. ✅ `chunk_id: str | None`: dataclass field is Optional.
10. ✅ Intra-paper checkpoint: `var/arxmcp/ops/intra-paper-refs-checkpoint.json`.
11. ✅ `cite_neighbors` async: `async def`; wrap `conn.execute` via
    `asyncio.to_thread`.
12. ✅ Self-loops: filter for cites/cited_by; keep for depends_on.
13. ✅ `theorem_label` column: already exists (verified in
    `ingest/schema.py`).

Items the implementer should resolve during Phase 2:

1. **Verify `relationships(p)` works** in Kùzu 0.11.3. If yes, use
   it for per-hop source extraction at depth=2. If no, use the
   two-query variant (§2).
2. **Pick `confidence=1.0` for intra-paper** vs documenting an
   alternate value. Synthesis recommends 1.0; verify no
   downstream cache or display logic assumes a hierarchy.
3. **Test fixture for `\ref{}` parsing**: a stripped LaTeXML output
   with one or two `<a class="ltx_ref">` anchors. Commit under
   `tests/fixtures/intra_refs/<paper_id>/index.html` so the parser
   has a real input to test against (R2's recommendation).
4. **Verify Kùzu `WHERE` clauses on relationship properties** in
   variable-length paths: `WHERE r.source <> 'intra-paper'` for
   each `r` in the path — does Kùzu support this on multi-hop?
   If not, the source-filter has to happen in Python after
   extraction.

---

## 13. External writes the implementation will require

Both briefs agree this is a pure-local milestone.

| type | target | why |
|---|---|---|
| code | `server/graph_queries.py`, `server/graph_types.py`, `ingest/intra_paper_refs.py`, `ingest/identifiers.py` (helper add), `tests/test_graph_queries.py`, `tests/test_intra_paper_refs.py` | new module + helpers + tests |
| filesystem write (operator-only) | `var/arxmcp/index/kuzu/` (intra-paper edges added) | gitignored; tests use `tmp_path` |
| filesystem write (operator-only) | `var/arxmcp/ops/intra-paper-refs-checkpoint.json` | gitignored |
| (optional) test fixture | `tests/fixtures/intra_refs/<paper_id>/index.html` | parsing regression pin |

**No HTTP calls.** No new runtime dependencies.

**Phase 4 boundary:** no `git push`, no GitHub mutations. The
`external_writes_required` at the milestone gate is empty.

---

## 14. Severity-tagged risk register for Phase 3

The adversary critic should focus here:

- **CRITICAL**: live network calls leak into CI (would mean someone
  added one — easy to spot); `cite_neighbors` returns wrong
  hop_distance values; AC violations (e.g. `chunk_id=None` not
  returned for graph-only papers).
- **HIGH**: per-hop source/confidence extraction wrong on depth=2
  (cite vs intra-paper edges miscategorized); self-loop filtering
  inconsistent with direction semantics; result ordering
  non-deterministic; `kuzudb_path` default still pointing at
  `kuzudb/`.
- **MEDIUM**: depth-2 dedup missing (paper appears twice in
  results); `max_results` cap applied before dedup (silently
  drops distinct papers); no test for the
  `kind="stmt"`-fallback-to-lemma path; `paper_id_from_chunk_id`
  not raising on malformed input; intra-paper ingest skips
  papers whose parsed HTML is missing without surfacing.
- **LOW**: `\ref{}` regex is too narrow (misses LaTeXML variants);
  source-casing inconsistency not documented; `confidence=1.0`
  for intra-paper not justified.

---

**End of synthesis.** Phase 2 reads this in full + both briefs
(R1 for the `relationships(p)` recommendation, R2 for the
verified-fail list-comprehension behavior + LaTeXML format details).

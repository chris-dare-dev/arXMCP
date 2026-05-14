# E10_S03 Research Brief — Equation TED Index (Researcher 1)

Generated: 2026-05-14

---

## 1. In-Codebase Context

### Design notes applicable to E10_S03

- **`04-parsing-and-chunking.md`** — load-bearing on equation atom structure.
- **`05-storage-and-indexing.md`** — authoritative schema for `equations` table.
- **`07-multi-agent-caching.md`** — BP1 byte-stability; tool description changes blow the hash.
- **`01-mission-and-context.md`** — math fidelity over coverage; determinism over cleverness.

### Equation atoms — what exists today

`04-parsing-and-chunking.md` § "Equation atom record" defines the canonical shape:

```json
{
  "equation_id": "arxiv:2401.01234:eq789...",
  "paper_id": "2401.01234",
  "label": "(3.7)",
  "presentation_latex": "\\partial_t f = \\Delta f + V f",
  "mathml": "<math>...</math>",
  "ascii_form": "d/dt f = laplacian f + V f",
  "context_sentence": "As shown in equation (3.7), the heat operator...",
  "parent_chunk_id": "arxiv:2401.01234:a1b2c3d4e5f60718",
  "is_numbered": true,
  "is_display": true
}
```

Rule 3 from `04-parsing-and-chunking.md`: "Each numbered display equation gets its own retrievable record with: the equation in canonical form (macro-expanded MathML + presentation LaTeX), the surrounding sentence as context, and a back-reference to the parent theorem chunk."

**Critical finding:** `presentation_latex` is a first-class field on the equation atom record per both `04-parsing-and-chunking.md` and `05-storage-and-indexing.md`. It is NOT something to extract at query time.

### `equations` table schema (existing in design constitution)

`05-storage-and-indexing.md` § "Table: equations":

```
equation_id          string (primary key)
paper_id             string
label                string
presentation_latex   string
mathml               string
ascii_form           string
context_sentence     string
parent_chunk_id      string
embedding_eq         fixed_size_list<float32, D>
```

"Indexes: HNSW on `embedding_eq`, B-tree on `paper_id`."

**Critical finding:** The `equations` table is a SEPARATE LanceDB table from `chunks`. It is not a `kind="equation"` filter view. It is defined in the design constitution but has NO corresponding `EQUATIONS_SCHEMA_V1` constant in `ingest/schema.py` today — that schema must be created. The `mathml_tree_pickle` column (for `zss.Node` trees) is also absent and must be added.

### `embedding_eq` status in `chunks` table

`ingest/schema.py` line 107-114 (verbatim):
```python
# ``embedding_eq`` is reserved for E10_S03 (equation embeddings).
# The embedder NEVER populates this; every row written by E03_S01
# has ``embedding_eq=None``.
pa.field(
    "embedding_eq",
    pa.list_(pa.float32(), EMBEDDING_DIM),
    nullable=True,
),
```

`ingest/embedder.py` routing (line ~971): `"embedding_proof" if kind == "proof" else "embedding_stmt"`. No `embedding_eq` branch exists. **E10_S03 must add the population path for `equations.embedding_eq`**, but this is on the EQUATIONS table, not the chunks table. The `chunks.embedding_eq` column is a separate reserved slot that may remain NULL.

### LaTeXML — no subprocess pool in `server/resources.py`

`server/resources.py` manages: BGE-M3, LanceDB chunks table, BGE-reranker, BM25Phase, ANNPhase, RerankPhase, RetrievalCache, and definitions table. **There is no LaTeXML subprocess pool**. The only LaTeXML invocation in the codebase is `tools/arxiv_fetch.py::parse_with_latexml`, which is dev tooling running `latexmlc` synchronously via `subprocess.run`. This is documented explicitly: "Production ingestion (E11) will re-implement these in `ingest/` with subprocess UID isolation."

**Critical finding:** The brief says "reusing the existing pool from `server/resources.py`" — this pool does not exist. Creating a query-time LaTeXML subprocess pool is significant new scope. The implementer must decide whether to add a minimal async `latexmlc` subprocess call or use a lighter-weight MathML parser.

### Current `find_equation` handler

`server/handlers/equation.py` is a 67-line dense-only fallback that:
1. Embeds `latex_or_mathml` via `encode_query` (BGE-M3 over `embedding_stmt`).
2. Queries `r.chunks_table` ANN on `embedding_stmt` (NOT `embedding_eq`).
3. Returns `retrieval_mode: "dense_only_stmt_fallback"`.

The handler uses `get_resources()` → `r.chunks_table`. After E10_S03 it must use a different table handle (`equations_table`) from Resources.

### Tool schema version and BP1 discipline

`server/tools.py` line 64: `TOOL_SCHEMA_VERSION: int = 2`. The `FIND_EQUATION` description explicitly announces the v1 fallback and defers to E10_S03. After E10_S03 ships, the description MUST change (remove the "v1 ships dense-only fallback" warning). Any description change → `TOOL_SCHEMA_VERSION` bump `2→3` → `EXPECTED_TOOL_SCHEMA_SHA256` re-pin via `pytest --update-tool-schema-hash` → `EXPECTED_BP1_SHA256` re-pin.

### `zss` — not in `pyproject.toml`

`pyproject.toml` lists 14 runtime dependencies. `zss` is absent. It must be added.

### Chunker — no `kind="equation"` chunks emitted

`ingest/chunker.py` emits `kind` values from `_THEOREM_ENV_KINDS` (theorem, lemma, proposition, etc.) and `kind="proof"`, `kind="section"`. There is no `kind="equation"` emitted by the chunker. Equation atoms per `04-parsing-and-chunking.md` are a separate first-class index, NOT a chunk kind. The chunker as implemented (E02_S01) focuses on theorem/proof pairs and section prose — equation atom extraction is a distinct ingest step that does NOT yet exist in `ingest/chunker.py` or anywhere in `ingest/`.

**Critical implication:** The `equations` table is currently EMPTY. E10_S03 must include an equation atom extractor, or the TED index has nothing to query against.

---

## 2. Prior Decisions and Lessons

### `zss` package status

- Version `1.2.0`, released **2018-03-12** (7+ years ago). Last commit activity in repo is 2024 (issue opened), but no releases since 2018.
- API: `Node(label, children=None)`, `node.addkid(other_node, before=False)`, `simple_distance(A, B, get_children=..., get_label=..., label_dist=strdist)`.
- License: not clearly specified in PyPI metadata. The GitHub repo (timtadh/zhang-shasha) is the source. The implementer MUST verify the license before adding this dependency.
- Complexity: O(n·m·l²) where l is keyroots count. For a physics MathML tree with 50+ nodes and 200 candidates, worst-case is O(50·50·50²) = 6.25M ops per candidate × 200 = 1.25B ops at query time. **Performance risk is real** for deep hep-th MathML trees.
- No active maintenance. This is acceptable for a well-understood algorithm that is effectively frozen.
- No known conflict with PyTorch/faiss that would trigger the `KMP_DUPLICATE_LIB_OK` issue (pure Python, no C extensions).

### Embedding `equations.embedding_eq`

The embedder (`ingest/embedder.py`) encodes `preamble + "\n\n" + body_text`. For equation atoms, the equivalent is `presentation_latex + " " + context_sentence` per the brief. This is a new encoding path — the existing embedder routes by chunk `kind` (proof vs everything else) and never touches `embedding_eq`. E10_S03 must add a new embedding function or extend `embed_paper` for equation atoms. Recommendation: add `ingest/embed_equations.py` rather than modifying `ingest/embedder.py` (single-responsibility; embedder already has enough routing complexity).

### Pickle security model

`mathml_tree_pickle` stores pickled `zss.Node` trees. The ingest pipeline writes these; the query path loads them. Loading pickles from a trusted local path written by trusted ingest code is acceptable (not loading from network). However: (a) document that `pickle.loads` must only be called on files under `var/arxmcp/` owned by the same user; (b) add a schema-version tag alongside the pickle so a `zss` version bump can invalidate stale pickles. Use `pickle.HIGHEST_PROTOCOL` at write time.

### Three-commit pattern: this milestone needs all three

feat(index): equation TED index + `EquationIndex` (E10_S03)
rect(index): close N findings from E10_S03 critique
chore(notes): finalize E10_S03 state -> complete

### E10_S04 dependency

E10_S04 (LaTeXML drift detector) depends on E10_S03. E10_S04 needs: (a) the `equations` LanceDB table populated with `mathml` strings, (b) a stable `LATEXML_VERSION` constant or equivalent in the ingest path to detect. E10_S03 should define a `LATEXML_VERSION_USED` field on the equations table (or in a metadata record) so E10_S04 has something to diff against.

### `assert` ban

`ingest/schema.py` uses `if … raise ValueError` everywhere, not `assert`. The same discipline applies throughout E10_S03 deliverables.

### Pure-ASGI middleware rule

Not directly applicable to E10_S03 (no new middleware). `EquationIndex.query()` is a sync/async helper, not middleware.

---

## 3. External Sources

### `zss` API (verified from source)

```python
from zss import Node, simple_distance

# Build a tree: root with two children
root = Node("int").addkid(Node("0")).addkid(Node("1"))

# Compute TED
dist = simple_distance(tree_a, tree_b)
# Returns: float (number of edit operations)
```

`simple_distance` returns the minimum edit cost. Default `label_dist` is `strdist` (Levenshtein on node label strings). For MathML, node labels are element tag names (e.g., `"mfrac"`, `"mi"`, `"mn"`) — Levenshtein between `"mi"` and `"mi"` is 0 (no cost), between `"mfrac"` and `"mrow"` is 4. This is correct behavior.

**Algorithm complexity (Zhang-Shasha):** O(|A|·|B|·min(depth(A), leaves(A))·min(depth(B), leaves(B))) per the original paper (Zhang & Shasha, 1989, "Simple Fast Algorithms for the Editing Distance between Trees and Related Problems"). The `zss` implementation uses the keyroot-based formulation. For a 50-node MathML tree (typical integral), depth ~10, leaves ~25: O(50·50·10·10) = 250K ops per pair. At 200 candidates: 50M ops. Acceptable on modern hardware (~0.1s). For a 200-node hep-th tree (dense commutative diagrams), depth ~20, leaves ~100: O(200·200·20·20) = 16M ops per pair × 200 = 3.2B ops. **This is the pathological case and could cause query latency of 10+ seconds.**

### MCP 2025-06-18 response shape for `find_equation`

The current handler returns:
```json
{"corpus_version": N, "results": [{"chunk_id": "...", "paper_id": "...", "score": 0.87}], "retrieval_mode": "dense_only_stmt_fallback"}
```

After E10_S03, the shape should update `retrieval_mode` to `"ted_fusion"` (or `"dense_only_fallback"` when `mathml_tree_pickle` absent) and results should reference `equation_id` not `chunk_id` (or both). The `score` field carries `final_score` from the fusion formula.

---

## Open Questions

1. **Equation atom extraction gap.** The `equations` LanceDB table has no population path — no extractor in `ingest/` emits equation atom records. The chunker does NOT produce `kind="equation"` rows. Does E10_S03 also include writing the equation atom extractor (`ingest/extract_equations.py`) that populates the `equations` table? Or is this a prerequisite gap that blocks E10_S03 entirely? The brief implies the table exists ("reads `equations` table"), but it cannot exist without an extraction step. **This is the single biggest scope question.** If equation extraction is out of scope, E10_S03 is untestable against real corpus data.

2. **`embedding_eq` population path.** The brief says E10_S03 populates `embedding_eq` on the `equations` table. The existing `ingest/embedder.py` has no code path for this. Does E10_S03 add a new `ingest/embed_equations.py`, or extend `embed_paper`? Recommendation: new file to avoid coupling.

3. **LaTeXML subprocess at query time.** The brief says "reusing the existing pool from `server/resources.py`" but no such pool exists. Options: (a) add a minimal `asyncio.Semaphore`-gated `latexmlc` subprocess call to Resources (new scope, ~50 LOC); (b) use `lxml` to parse the LaTeX query string directly into an XML tree without LaTeXML (loses macro expansion, but acceptable for query-time since the query is typically clean LaTeX); (c) skip LaTeXML at query time and accept that the query MathML differs from the corpus MathML structurally (degrades TED precision). **Recommend option (a) as a minimal `latexmlc` subprocess with 30s timeout**, gated by a `latexml_semaphore` on Resources.

4. **`normalized_ted` formula.** The brief specifies `1 - normalized_ted`. How is normalization computed? Dividing by `max(|A|, |B|)` (the "upper bound" normalization) is standard and produces values in [0, 1]. Dividing by the max TED seen in the candidate set is corpus-size-sensitive. **Recommend `normalized_ted = raw_ted / max(|A|, |B|)`.** Document as a constant.

5. **200-candidate cap vs. small corpus.** The seed corpus has 50 papers with an estimated ~2000 numbered equations. Retrieving top-200 candidates by dense cosine is fine. In unit tests with synthetic data (3–10 equations), the cap must be `min(200, len(corpus))`. The `EquationIndex.query` method should cap at `min(200, corpus_size)`.

6. **`EQUATIONS_SCHEMA_V1` missing.** `ingest/schema.py` has `CHUNKS_SCHEMA_V1` and `DEFINITIONS_SCHEMA_V1` but NO `EQUATIONS_SCHEMA_V1`. E10_S03 must add it, including the `mathml_tree_pickle` column (as `pa.large_binary()` for the pickled bytes). This is a write to `ingest/schema.py`, which will need careful coordination with `EMBEDDING_COLUMN_NAMES` and `CHUNKS_TABLE_NAME` constants.

7. **Tool description update and BP1 re-pin.** When `FIND_EQUATION.description` is updated to remove the "v1 ships dense-only fallback" disclaimer, `TOOL_SCHEMA_VERSION` must bump `2→3` and `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` in `tests/test_server_tool_schema.py` and `tests/test_prompts.py` must be re-pinned via `pytest --update-tool-schema-hash`.

8. **`equations_table` handle in Resources.** After E10_S03, `server/resources.py` needs an `equations_table` field analogous to `definitions_table` (optional, graceful absent). The startup sequence must attempt to open the `equations` LanceDB table.

9. **`zss` license.** The PyPI page does not clearly state the license. The GitHub repository at `timtadh/zhang-shasha` must be checked — README or LICENSE file must be read before adding as a dependency. If it is MIT or Apache-2.0, proceed. If it is GPL, reconsider.

---

## External Writes the Implementation Will Require

| type | target | why |
|---|---|---|
| local-file-write | `pyproject.toml` | Add `zss>=1.2.0` to `dependencies` |
| local-file-write | `ingest/schema.py` | Add `EQUATIONS_SCHEMA_V1`, `EQUATIONS_TABLE_NAME`, `mathml_tree_pickle` column |
| local-file-write | `ingest/index_equations.py` | New indexer: reads `equations` table, computes `zss.Node` trees, writes `mathml_tree_pickle` |
| local-file-write | `ingest/embed_equations.py` | New embedder path for `equations.embedding_eq` |
| local-file-write | `server/retrieval/equations.py` | New `EquationIndex` class |
| local-file-write | `server/handlers/equation.py` | Update handler to delegate to `EquationIndex`; add fallback |
| local-file-write | `server/resources.py` | Add `equations_table` field; open at startup; add `latexml_semaphore` |
| local-file-write | `server/tools.py` | Update `FIND_EQUATION.description`; bump `TOOL_SCHEMA_VERSION` 2→3 |
| local-file-write | `tests/test_server_tool_schema.py` | Re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `--update-tool-schema-hash` |
| local-file-write | `tests/test_prompts.py` | Re-pin `EXPECTED_BP1_SHA256` |
| local-file-write | `tests/test_equation_index.py` | New test file per deliverables |
| local-file-write | `var/arxmcp/index/lancedb/` | New `equations` LanceDB table written at ingest time (runtime artifact, not a source file) |
| network-read | `pypi.org` / `uv lock` | `uv lock` fetches `zss` wheel to resolve lockfile; requires internet access once |

# 05 — Storage and Indexing

Two storage engines, both embedded (no separate server processes), both file-based,
both fit comfortably in a single Docker container.

## Vector + lexical index: LanceDB

`https://github.com/lancedb/lancedb`

**Why LanceDB beats the alternatives for this use case:**

| Candidate | Verdict |
|---|---|
| **LanceDB** | **PICK.** Embedded (no server). Columnar Lance format. MVCC via dataset versions — `dataset.checkout(version=N)` gives snapshot isolation. Native vector + scalar filters + full-text via Tantivy. Incremental indexing. Fast cold start. Disk roughly 1.5–2× raw embedding size. RAM at query time is tiny. |
| **Qdrant** | Acceptable second choice. Separate server in Rust. Strong hybrid (BM25 + dense fusion since v1.10+). Extra ops we don't need at single-workstation scale. Pick this if we ever expose beyond localhost. |
| **pgvector + Postgres FTS** | Tempting if we already ran Postgres. HNSW is fine but not great at 1M scale; `tsvector` BM25 is mediocre on technical text (no subword, weak with LaTeX tokens). Skip unless we want a single box for vectors + citation graph (Kùzu beats this). |
| **Chroma** | Single-node toy. Persistence has been shaky across versions. Skip. |
| **Weaviate / Milvus / Vespa** | Massive overkill. Vespa is technically the best of these and the most painful to operate. |
| **Typesense / Marqo** | Not in the running. |

## Index layout

LanceDB tables (one Lance dataset per table):

### Table: `chunks`

The primary retrievable unit. Columns:

```
chunk_id              string (primary key)
paper_id              string
version               int
level                 enum {paper, section, theorem}
kind                  enum {abstract, section, theorem_with_proof, definition, equation_context, ...}
section_path          list<string>
label                 string nullable
preamble              string (per-paper notation, prepended to embedding_text)
body_canonical        string (macro-expanded)
body_raw_latex        string
mathml                string nullable
referenced_chunks     list<string>
equation_atoms        list<string>
char_offsets_start    int
char_offsets_end      int
embedding_stmt        fixed_size_list<float32, 1024>  # preamble+statement, ≤512 tok; set for kind=stmt
embedding_proof       fixed_size_list<float32, 1024>  # preamble+stmt_header+proof window, ≤512 tok, 64-tok overlap; set for kind=proof
embedding_eq          fixed_size_list<float32, 1024>  # reserved; NULL until E10_S03
chunker_version       string
embed_model           string
created_at            int64
```

> **Updated 2026-05-06 (see E04_S01 in `.claude/roadmap/E04-vector-store.md`).**
> The original `embedding_prose` / `embedding_latex` dual columns are replaced by
> `embedding_stmt` (nullable; set for `kind="stmt"` chunks) and `embedding_proof`
> (nullable; set for `kind="proof"` chunks). Embedding dimension is fixed at 1024
> (BGE-M3). The old column names and approach are superseded.

Indexes:
- HNSW on `embedding_stmt` (M=16, efConstruction=200).
- HNSW on `embedding_proof` (M=16, efConstruction=200).
- BM25 over `body_tokens` using Python `rank_bm25` (BM25Okapi); index stored at
  `var/arxmcp/index/bm25/v<N>/`. `body_tokens` is a space-joined token stream
  produced at chunk-write time by a Python regex pre-tokenizer (E02_S03) that
  preserves backslash tokens like `\Spec`, `mathrm_Pic`, etc. Standard whitespace
  split is all that BM25 needs over pre-tokenized input. **No Tantivy LaTeX
  analyzer** — Tantivy ships no such analyzer; the approach was fictional.
  See E02_S03 / E04_S04 in `.claude/roadmap/E04-vector-store.md`.
- B-tree (scalar index) on `paper_id`, `version`, `level`, `kind`.

### Table: `equations`

Display equations as first-class atoms (see
[04-parsing-and-chunking.md](04-parsing-and-chunking.md)).

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

Indexes: HNSW on `embedding_eq`, B-tree on `paper_id`.

### Table: `definitions`

Per-paper notation/definition table.

```
definition_id        string (primary key, content-addressable)
paper_id             string
symbol               string                    # canonical form, e.g. "\mathcal{A}"
symbol_raw           string                    # author's form, e.g. "\AA"
expansion            string                    # human-readable expansion text
defining_chunk_id    string
scope                enum {paper, section, theorem}
```

Indexes: B-tree on `(paper_id, symbol)`, B-tree on `symbol_raw`.

### Table: `theorem_names`

Mathlib-style exact-match index on theorem labels.

```
name                 string (primary key)      # "Yoneda lemma", "Riemann-Roch", normalized
paper_id             string
chunk_id             string
confidence           float                     # how sure we are this is a named theorem
```

Indexes: full-text on `name` (FTS5-style trigram for fuzzy match).

### Table: `papers`

Metadata table.

```
paper_id             string (primary key)
versions             list<int>                 # all known versions
latest_version       int
title                string
authors              list<string>
abstract             string
abstract_embedding   fixed_size_list<float32, D>
categories           list<string>
submitted_at         date
updated_at           date
withdrawn            bool
withdrawal_reason    string nullable
license              string
parse_status         enum {ok, degraded, failed}
parser_used          enum {ar5iv, latexml_local, nougat}
n_chunks             int
n_equations          int
n_definitions        int
```

## Versioning via LanceDB MVCC

> **Updated 2026-05-06 (see E04_S02 in `.claude/roadmap/E04-vector-store.md`).**
> Manual symlink swaps (`current -> v0007`) are **explicitly prohibited** under
> the new design. Use LanceDB's native MVCC mechanism instead.

LanceDB exposes native versioning: every `write` operation on a dataset creates
a new integer version (starting from 1). Readers pin a specific version by
calling `dataset.checkout(version=N)`, which returns a read-only snapshot of
the dataset as it existed after version N was written. This provides snapshot
isolation — the ingestion service writes new versions without disrupting
running reader sessions.

The ingestion pipeline (E04_S01–S02) returns the new version integer from
`write_chunks()` and records it in `var/arxmcp/index/lancedb/corpus-version.json`.
The MCP server reads `corpus-version.json` at startup and calls
`dataset.checkout(version=N)` once; that pinned view is used for the entire
process lifetime. **No symlinks are created or modified.**

Keep N=7 prior LanceDB dataset versions for rollback; a compaction job GCs
older versions after readers have migrated (see E11).

## Citation graph: Kùzu

`https://github.com/kuzudb/kuzu`

**Why Kùzu beats the alternatives:**

- Embedded (no server). One file. Same operational footprint as LanceDB.
- Columnar storage. Cypher query language.
- Comfortable with 100M-edge graphs on a workstation.
- Active development as of 2025.

**Alternatives considered:**

- **Neo4j Community** — works but heavyweight (separate JVM server).
- **FalkorDB** — fine but newer; ecosystem smaller.
- **Postgres + recursive CTE** — fine for "citers of X" but breaks down on
  "papers within 2 hops sharing a lemma name." Once you ask multi-hop questions,
  you want Cypher.

### Schema (Cypher DDL)

```cypher
CREATE NODE TABLE Paper (
  paper_id STRING PRIMARY KEY,
  title STRING,
  arxiv_categories STRING[],
  submitted_date DATE,
  withdrawn BOOLEAN
);

CREATE NODE TABLE Author (
  author_id STRING PRIMARY KEY,         -- ORCID or disambiguated key
  name STRING,
  affiliations STRING[]
);

CREATE NODE TABLE Theorem (
  theorem_id STRING PRIMARY KEY,        -- chunk_id of the theorem chunk
  name STRING,                          -- "Yoneda lemma" or null
  paper_id STRING
);

CREATE REL TABLE CITES (
  FROM Paper TO Paper,
  citation_count INT,
  source ENUM('inspire', 'openalex', 'tex_extracted')
);

CREATE REL TABLE AUTHORED (
  FROM Author TO Paper,
  position INT
);

CREATE REL TABLE PROVES (
  FROM Theorem TO Theorem,              -- "this theorem's proof depends on that theorem"
  context STRING
);

CREATE REL TABLE NAMED_AFTER (
  FROM Theorem TO Theorem               -- "Theorem 3.4 of paper X is the same as the named theorem"
);
```

### Seeded from

- **OpenAlex** for math.AG, math.NT (Work-to-Work `referenced_works` edges,
  monthly bulk diff).
- **INSPIRE-HEP** for hep-th, math-ph (per-paper API enrichment, continuous).
- **Local extraction** of `\ref{}` for intra-paper `PROVES` edges.

Don't try to extract `\cite{}` from .tex and resolve them yourself — INSPIRE
and OpenAlex have already done the disambiguation.

### Query patterns we serve

```cypher
-- "Papers that cite this paper, with at least 5 citations themselves"
MATCH (p:Paper {paper_id: $id})<-[:CITES]-(citer:Paper)
WHERE size((citer)<-[:CITES]-()) >= 5
RETURN citer LIMIT 50;

-- "Theorems this proof depends on (within paper)"
MATCH (t:Theorem {theorem_id: $id})-[:PROVES*1..3]->(dep:Theorem)
RETURN dep;

-- "Co-citation cluster around a topic" (papers commonly cited together with X)
MATCH (x:Paper {paper_id: $id})<-[:CITES]-(p:Paper)-[:CITES]->(co:Paper)
WHERE co.paper_id <> $id
RETURN co.paper_id, count(*) AS strength
ORDER BY strength DESC LIMIT 30;
```

## Embedding strategy

### Durable index uses BGE-M3, end-to-end

> **Updated 2026-05-06 (see E03_S01 in `.claude/roadmap/E03-embedder.md`,
> closing critique H8).** Using a different model at query time than at index
> time (cross-model encoding) drops nDCG 30–60% and is rejected as a footgun.
> The new design uses **BGE-M3 self-hosted for both index and query** — same
> model end-to-end. API embedders (Voyage, Cohere, OpenAI) are **rejected** for
> both durable index and query-time encoding.

**Hard rule:** `BAAI/bge-m3` is the sole embedder for arXMCP v1, used for both
corpus indexing and query-time encoding. It is strong on multilingual + math,
MIT licensed, ~2GB. It keeps the system air-gappable and eliminates the
cross-model alignment problem.

Alternatives `intfloat/e5-mistral-7b-instruct` and `Salesforce/SFR-Embedding-Mistral`
remain documented below for reference if the embedder is ever swapped, but any
swap requires a full corpus re-embed (new LanceDB version) and must be applied
consistently to both index and query path.

### Dual-representation indexing

> **Updated 2026-05-06 (see E02_S01 / E03_S01 / E04_S01 in the roadmap).** The
> original design gave every chunk two embeddings (prose-only + raw-LaTeX). The
> new design splits by chunk *kind*, closing critique H3 (BGE-M3 mean-pooling at
> 8k tokens flattens embeddings when full theorem+proof is used as a single unit).

The dual encoding is now **kind-gated**:

1. **`embedding_stmt` (set for `kind="stmt"` chunks):** preamble + statement text,
   ≤512 tokens. For semantic similarity queries ("papers about Hodge structures").
2. **`embedding_proof` (set for `kind="proof"` chunks):** preamble + statement
   header + proof window, ≤512 tokens with 64-token overlap. For proof-technique
   queries ("papers that prove flatness via base change").

Chunks of other kinds (section, definition) receive `embedding_stmt`; `embedding_proof`
is NULL for non-proof chunks. Retrieval fuses both via Reciprocal Rank Fusion at
query time over `embedding_stmt` ANN and `embedding_proof` ANN results.

### ColBERT for long technical chunks (v1.5 feature)

For theorem+proof chunks (often 500–2000 tokens), single-vector dense retrieval
loses information. **ColBERT-v2** late-interaction materially beats single-vector
on math. Cost: ~10× the storage. Worth it for the tactician's queries; overkill
for the sketcher's broad survey queries.

Plan: ship without ColBERT in v1; add as v1.5 once we have query-quality data
showing where retrieval fails.

### Equation embeddings (v2 feature)

Train a small encoder on `(equation, surrounding_sentence)` pairs from our own
corpus once we have it. Not a day-one task. Until then, embed equations using
the same prose embedder over `presentation_latex + context_sentence`.

## Hybrid search at query time

> **Updated 2026-05-06 (see E07_S01 / E07_S02 / E07_S03 in
> `.claude/roadmap/E07-hybrid-retrieval.md`).** The old four-stream design (two
> BM25 streams + two ANN streams) is replaced by the three-phase pipeline below.
> Cohere Rerank is dropped; self-hosted BGE-reranker-v2-m3 only.

Three-phase ranking:

1. **Phase 1 (cheap, broad):** BM25 over `body_tokens` using Python `rank_bm25`.
   The `body_tokens` field is a pre-tokenized stream (E02_S03) that preserves
   backslash tokens like `\Spec`, `mathrm_Pic`, etc. Take top-200.
2. **Phase 2 (medium):** Dual ANN search — one query embedding over
   `embedding_stmt` and one over `embedding_proof`, top-50 each. Reciprocal Rank
   Fusion (k=60) across the Phase-1 BM25 list and both ANN lists. Take top-50.
3. **Phase 3 (expensive):** `bge-reranker-v2-m3` local cross-encoder. Gated by
   `ARXMCP_ENABLE_RERANK` environment variable (default `false`). When disabled,
   Phase-2 RRF order is returned directly. Take top-k (default 10, max 50).

Each phase has its own cache layer (see [07-multi-agent-caching.md](07-multi-agent-caching.md)).

## Disk and memory budget at v1 scale

For ~200K papers (math.AG, math.NT, math-ph, hep-th, post-2007 with usable source):

- **Chunks table:** ~5M rows × ~5 KB raw + ~12 KB embeddings ≈ 80 GB.
- **Equations table:** ~10M rows × ~1 KB ≈ 10 GB.
- **Definitions table:** ~2M rows × ~0.5 KB ≈ 1 GB.
- **Theorem names:** small (<100 MB).
- **Papers metadata:** ~200K rows × ~5 KB ≈ 1 GB.
- **Kùzu graph:** ~5 GB.
- **Total persistent state:** ~100 GB across LanceDB + Kùzu.
- **RAM at query time:** ~4–8 GB for HNSW indexes + cache. Embedder model
  another ~2 GB. Reranker another ~1 GB.

Comfortable on a workstation with 32GB RAM and a 1TB SSD.

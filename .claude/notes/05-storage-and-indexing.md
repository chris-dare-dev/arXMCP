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
embedding_text        string
embedding_prose       fixed_size_list<float32, D>     # prose-only embedding
embedding_latex       fixed_size_list<float32, D>     # raw-LaTeX-with-macros embedding
embedding_colbert     fixed_size_list<float32, ?>     # late-interaction (optional, theorem-level only)
chunker_version       string
embed_model           string
created_at            int64
```

Indexes:
- HNSW on `embedding_prose` (M=16, efConstruction=200).
- HNSW on `embedding_latex` (M=16, efConstruction=200).
- BM25 / Tantivy on `body_canonical` and `body_raw_latex` (separate analyzers —
  the LaTeX analyzer preserves backslash tokens like `\Spec`).
- B-tree on `paper_id`, `version`, `level`, `kind`.

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

## Versioning and atomic swaps

LanceDB datasets support versioning natively. Ingestion writes a new version;
the MCP server reads via a symlink:

```
/var/arxmcp/index/lancedb/
  v0001/
  v0002/
  ...
  v0007/
  current -> v0007        # symlink the MCP server pins at session start
```

The MCP server resolves `current` once at session start and uses the resolved
version for the whole session. Daily ingestion swaps the symlink atomically;
running sessions are unaffected because they pinned the old version.

Keep N=7 prior versions for rollback. Older versions are GC'd by a nightly job.

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

### Durable index uses self-hosted embedders

**Hard rule: never use a hosted embedding API for the durable corpus index.** If
Voyage retires `voyage-3`, we re-embed everything. Use one of:

- **`BAAI/bge-m3`** — strong on multilingual + math; MIT license; ~2GB.
  Recommended default.
- **`intfloat/e5-mistral-7b-instruct`** — best open-weights for technical
  retrieval; ~14GB; needs decent GPU.
- **`Salesforce/SFR-Embedding-Mistral`** — competitive with e5-mistral.

API embedders (Voyage, Cohere, OpenAI) are acceptable for **query-time encoding
only** if we want better paraphrase handling than the local embedder gives.
Even then, prefer self-hosted to keep the system air-gappable.

### Dual-representation indexing

Each chunk gets two embeddings:

1. **Prose-only (`embedding_prose`):** math stripped to `[MATH]` tokens or
   rendered to unicode-math. For semantic similarity ("papers about Hodge
   structures").
2. **Raw-LaTeX-with-expanded-macros (`embedding_latex`):** preserves command
   structure. For exact-form matching ("papers that compute `\dim H^1(\mathcal{F})`").

Retrieval fuses both via Reciprocal Rank Fusion at query time.

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

Three-phase ranking, modeled on Vespa's tiered approach:

1. **Phase 1 (cheap, broad):** BM25 over `body_raw_latex` (LaTeX analyzer
   preserves `\Spec`, `\mathrm{Pic}`, etc.) PLUS BM25 over `body_canonical`
   (English analyzer). Take top-200.
2. **Phase 2 (medium):** ANN search over `embedding_prose` and `embedding_latex`,
   k=200 each. Reciprocal Rank Fusion across all four candidate lists. Take top-50.
3. **Phase 3 (expensive):** Reranker (`bge-reranker-v2-m3` local; or Cohere
   Rerank v3 if budget allows). Take top-k where k is the user's requested k
   (default 10, max 50).

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

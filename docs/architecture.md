# Architecture

How arXMCP turns arXiv source into grounded context for a multi-agent
pipeline. This is the operator-facing tour; the architectural *why* lives in
the design constitution under
[`.claude/notes/`](../.claude/notes/) (quoted inline below).

## The shape

```
arXiv / ar5iv / PDF
      │  fetch (polite pool) → LaTeXML / MinerU → HTML5 + MathML
      ▼
  ingest pipeline   chunker → preamble extractor → BGE-M3 embedder → indices
      │
      ▼
  storage           LanceDB (chunks) · BM25 · FTS5 (theorem names) ·
      │             equations (TED) · Kùzu (citation graph) · definitions
      ▼
  arxmcp-server     FastAPI + Streamable HTTP · eight MCP tools · 3-tier cache ·
      │             query router · per-session caps · operator console (/ui/)
      ▼
  arxmcp-shim       one stdio↔HTTP bridge per Claude sub-agent (loopback only)
      ▼
  Claude pipeline   sketcher → autoformalizer → tactician → fixer
```

Design rationale: [`02-architecture-overview.md`](../.claude/notes/02-architecture-overview.md).

## Ingestion

arXiv source is fetched through the polite pool (User-Agent with contact
email, 503 backoff, ≥3 s spacing). ar5iv HTML is preferred; `latexmlc` is the
fallback for cache misses. The **theorem-aware chunker** emits dual chunks
per result — a 512-token *statement* chunk and a *proof* chunk — so retrieval
can favor statements without losing proofs. A per-paper **preamble
extractor** captures `\newcommand` / `\DeclareMathOperator` / `\def` macros
into the definitions table. Chunk IDs are content-addressable
(`arxiv:<paper_id>:<sha256[:16]>`), making re-ingest idempotent.

Math fidelity is a hard constraint: LaTeXML + MathML, never PyPDF as a
primary parser. See [`03-ingestion-pipeline.md`](../.claude/notes/03-ingestion-pipeline.md)
and [`04-parsing-and-chunking.md`](../.claude/notes/04-parsing-and-chunking.md).

## Embeddings & storage

A **BGE-M3 dual-column encoder** produces `embedding_stmt` and
`embedding_proof` vectors. The canonical store is a **LanceDB `chunks`
table** (PyArrow schema in [`ingest/schema.py`](../ingest/schema.py)) with
HNSW + scalar indices, MVCC versioning, and idempotent
`merge_insert(on="chunk_id")`. A `corpus_version` marker file keys the
retrieval cache. Specialized indices sit alongside it:

| Index | Backs |
|---|---|
| BM25 (per corpus version) | future hybrid retrieval (E07) |
| SQLite FTS5 | `find_lemma_by_name` |
| Equations + Zhang–Shasha TED | `find_equation` (MathML) |
| Definitions table | `get_definitions` |
| Kùzu graph | `cite_neighbors` |

[`05-storage-and-indexing.md`](../.claude/notes/05-storage-and-indexing.md)
has the schemas.

## The citation graph

A Kùzu embedded graph (`kuzu==0.11.3`, pinned — upstream archived
2025-10-10) is populated from **OpenAlex** (bulk citations + prose),
**INSPIRE-HEP** (identifiers for hep-th / math-ph), and **intra-paper
`\ref{}` chains** (self-edges). `cite_neighbors` traverses it in 1–2 hops.

## The server

`arxmcp-server` is a single-process FastAPI app speaking MCP 2025-06-18
Streamable HTTP at `/mcp/`, plus:

- **3-tier retrieval cache** — SQLite exact memo + FAISS semantic-query memo
  + LRU rerank-set memo, corpus-version keyed, fall-through on failure.
- **Query router** — a regex classifier tags each query into one of four
  agent roles (`LOOKUP`, `SYNTHESIS`, `VERIFICATION`, `AUTOFORMALIZATION`);
  no LLM planner.
- **Per-session caps** — 3 `search_papers` + 4 `get_chunk` per
  `Mcp-Session-Id`.
- **Prompt-cache discipline** — `tools/list` is byte-stable (BP1) and role
  prefixes are pinned (BP2) so warm caches survive across sub-agents. This is
  load-bearing; see [`07-multi-agent-caching.md`](../.claude/notes/07-multi-agent-caching.md).
- **Operator console** — loopback-only Jinja2 + htmx at `/ui/`.

[`06-mcp-server-design.md`](../.claude/notes/06-mcp-server-design.md) is the
server design note.

## The shim

`arxmcp-shim` is a ≤60-line stateless stdio↔HTTP bridge. Claude Code spawns
one per sub-agent; all shims hit the same warm server and share its cache.
Egress is loopback-only. This split is why a 4-agent pipeline pays the
BGE-M3 warmup cost once, not four times.

## Security & ops posture

Loopback-only bind (refuses `0.0.0.0`), Origin/Host pinning, body-size caps,
identifier regex validation, safetensors-only model loading, TLS-verified
outbound fetches. The full threat model is
[`08-security-observability-ops.md`](../.claude/notes/08-security-observability-ops.md);
the public summary is [`SECURITY.md`](../SECURITY.md). Observability and the
corpus lifecycle are covered in [Observability](observability/README.md) and
[Operations](ops/README.md).

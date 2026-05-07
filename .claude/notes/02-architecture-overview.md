# 02 — Architecture Overview

## The two headline corrections (read these first)

Before any code lands, internalize these two design choices. Every other decision in
arXMCP depends on them.

### Correction 1: MCP transport must be Streamable HTTP, not stdio

**Naive design:** stdio MCP server registered in `~/.claude.json`. Each Claude
sub-agent spawns the server and gets its own process.

**Why this fails:** stdio launches the server as a *subprocess of each client*.
Four sub-agents = four independent server processes, each with its own LanceDB
handle, its own embedding model loaded into RAM (`bge-m3` is ~2GB), its own rerank
cache, its own query cache. Every "shared cache" argument falls apart immediately.

**Right architecture:**

- **One long-running Streamable HTTP MCP server** bound to `127.0.0.1`, owning
  indices, embedding model, reranker, and all caches.
- **A small stdio shim binary** (~50 lines) registered in `~/.claude.json` that
  proxies JSON-RPC frames over HTTP. Each sub-agent spawns the shim; the shim is
  stateless; all state lives in the central HTTP server.

The MCP spec (2025-06-18, Transports section) is explicit that Streamable HTTP
servers can serve multiple concurrent clients. Pin `Origin` validation and bind to
localhost only — the spec calls these out as MUSTs.

### Correction 2: Macros must be expanded before embedding

**Naive design:** "treat LaTeX as literal tokens" — let the embedder see raw .tex.

**Why this fails:**

- Standard BPE tokenizers split `\partial` and `\bar{\partial}` inconsistently.
  Two papers writing the same operator different ways become non-aligned in vector
  space.
- Author-local macros are guaranteed fragmentation. `\newcommand{\AA}{\mathcal{A}}`
  used 400 times in one paper means the embedder sees `\AA` and has no semantic
  anchor; a different paper writes `\mathcal{A}` directly. The two papers become
  distant in vector space despite saying identical things.

**Right architecture:** expand macros via **LaTeXML** before chunking. LaTeXML is the
same engine that powers ar5iv, so we get it for free on most papers via the ar5iv
HTML cache; we run LaTeXML locally only on the long tail of cache misses. Estimated
retrieval-quality gain: 10–20% on math papers. Skip this and you build a worse
system regardless of what else you get right.

## Full system diagram

```
                 [ Claude Code sub-agents (sketcher, autoformalizer, tactician, fixer) ]
                         │            │            │            │
                         ▼            ▼            ▼            ▼
                  stdio shim    stdio shim    stdio shim    stdio shim    (50-line proxies)
                         └────────────┼────────────┼────────────┘
                                      ▼            ▼
                            [ ONE Streamable HTTP MCP server ]
                                      │
                ┌─────────────┬───────┴────────┬──────────────────┐
                ▼             ▼                ▼                  ▼
        Retrieval cache   Embedding cache  Rerank cache    Summary cache
         (3 tiers)         (singleflight)   (set-keyed)    (Haiku output)
                │             │                │                  │
                └─────────────┴────────┬───────┴──────────────────┘
                                       ▼
                  [ LanceDB (vectors+BM25, version-pinned) ]   [ Kùzu (citation graph) ]
                                       ▲
                                       │ new dataset version written; readers call
                                       │ dataset.checkout(version=N) — no symlinks
        [ Ingestion service (separate process, single-writer) ]
                │             │              │
                ▼             ▼              ▼
        OAI-PMH delta   ar5iv cache    LaTeXML local   ←── seed: Academic Torrents
                                    (macro expansion)        deltas: arxiv.org /e-print/
                                                             enrichment: INSPIRE + OpenAlex
```

## Three properties this gives you

1. **One process owns the embedder, reranker, and indices.** Loading `bge-m3` four
   times because four agents each spawned a stdio MCP would be a real failure mode
   of a naive design.
2. **Cross-agent prompt-cache reuse is achievable**, because tool definitions and
   tool results are deterministic bytes from one canonical source. See
   [07-multi-agent-caching.md](07-multi-agent-caching.md).
3. **Ingestion can't break a running agent**, because reads pin a LanceDB version at
   session start; the writer creates new versions, never mutates in place.

## Component responsibilities

| Component | Owns | Does NOT own |
|---|---|---|
| Ingestion service | Fetching, parsing, chunking, embedding, writing new LanceDB versions, updating Kùzu graph | Serving queries to agents |
| MCP HTTP server | Tool surface, all read-path caches, query embedding, retrieval, reranking, summary generation | Writing to indices, parsing source |
| stdio shim | Proxy JSON-RPC over HTTP. Stateless. | Anything else |
| LanceDB | Vector + BM25 index, content-addressable chunks, MVCC versions | Citation graph |
| Kùzu | Citation graph (Cypher queries: shortest path, neighborhood expansion, co-citation clusters) | Vectors |

The single most important separation here is **ingestion service vs MCP read-path
server**. They are different processes. A fast tactician query must never block on
a `latexml` build. Conversely, a long ingestion run must never invalidate caches the
agents are currently reading.

## Determinism contract

Every public-facing tool result from the MCP server must be bit-identical for the
same `(query, filters, k, corpus_version)` tuple. This is non-negotiable because:

- Anthropic prompt caching is byte-keyed. Non-deterministic results break cache
  reuse across agents.
- Reproducibility matters for science: if the tactician retrieved Lemma 3.4 of paper
  X yesterday, it must retrieve the same Lemma 3.4 today (until the corpus version
  is explicitly bumped).

Concrete rules:

- Results sorted by `(score_desc, chunk_id_asc)`.
- Chunk IDs are content-addressable: `arxiv:<paper_id>:<sha256(canonical_chunk_bytes)[:16]>`.
- No timestamps in tool results.
- No random tie-breaking.
- JSON keys serialized in alphabetical order.

## Versioning

Three versioned things:

1. **Corpus version** (LanceDB dataset version). New ingestion writes a new version;
   reads pin a version at session start.
2. **Embedding model version** (`bge-m3@2024-08`, etc.). Tied to the corpus version
   — a chunk embedded with model A and model B are different chunks. Never mix.
3. **Chunker version** (`v1.0`, etc.). Bumped when chunk strategy changes. Re-chunking
   means re-embedding.

When any of these changes, build a new index alongside the old one. LanceDB's
native MVCC (`dataset.checkout(version=N)`) provides snapshot isolation — the
ingestion service appends a new dataset version; readers pin their version at
startup via `corpus-version.json`. **Never mutate in place. No manual symlink swaps**
(see E04_S02 in `.claude/roadmap/E04-vector-store.md`). Keep N=7 prior LanceDB
dataset versions for rollback.

## Non-goals for v1

- Multi-host scaling, replication, leader election.
- Authentication / multi-tenancy. localhost-only.
- General-purpose web search agent capabilities.
- Auto-discovery of new arXiv categories beyond the four specified
  (math.AG, math.NT, math-ph, hep-th).
- Beautiful UI. The MCP tool surface is the UI.
- Full automation of proof discovery. arXMCP is a power tool for a human-driven
  agent pipeline, not an autonomous solver.

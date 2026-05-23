# OSS Trends Brief — 2026-Q2 Verification-Feedback Scan

**Scout:** oss-trends  
**Run date:** 2026-05-22  
**Scope:** Execution-based verification feedback for sketcher→autoformalizer→tactician→fixer; `cite_neighbors` MCP tool gap; adjacent retrieval/embedding/parsing capabilities.

---

## 1. TL;DR

The **leanprover-community/repl** project (Apache-2.0, stdin/stdout JSON REPL with environment pickling) is the clearest primitive for building an MCP `lean_verify` tool that returns real compile/typecheck/proof-state output to the tactician→fixer loop — no GPU, no network dependency, pure subprocess. The **Vela-Engineering/kuzu** fork adds concurrent multi-writer semantics to the archived Kùzu 0.11.3 codebase and is the only actively maintained drop-in migration path for arXMCP's citation graph, unblocking the `cite_neighbors` tool wiring. The main thematic gap in arXMCP is the absence of any **execution-feedback surface** — every existing MCP tool returns retrieved or pre-computed content, but none closes the verify→error→revise loop that makes the tactician→fixer pipeline self-correcting.

---

## 2. Project candidates

### 2.1 leanprover-community/repl

- **URL:** https://github.com/leanprover-community/repl
- **License:** Apache-2.0
- **Stars:** 203 | **Last commit:** active (no specific date surfaced, repo shows recent development)
- **What it does:** A minimal Lean 4 REPL that reads JSON commands from stdin and writes JSON responses to stdout. Supports two interaction modes: *command mode* (submit declarations, receive environment IDs + error messages) and *tactic mode* (submit a `proofState` ID + tactic string, receive the resulting goal state or error). Environments can be pickled to `.olean` files and unpickled, enabling stateful incremental proof interaction without restarting the process. File-mode (`{"path": "...lean", "allTactics": true}`) processes whole files and returns per-tactic states.
- **Specific capability worth borrowing:** The **stdin/stdout JSON protocol for proof-state inspection**. Each response carries: `env` (environment ID for backtracking), `messages` (severity + position + text, covering type errors, unknown identifier, goal unsolved), and `sorries` (containing `goal` string showing the current proof state with hypotheses). This is exactly the verification-trace format the tactician needs — structured, machine-readable, and carries enough information to route to the fixer. No GPU. No network. Subprocess-safe.
- **arXMCP positioning:** Design-pattern lift → native re-implementation. Add a new MCP tool `lean_verify` in `server/handlers/lean_verify.py` that spawns `lake exe repl` as a managed subprocess, writes a JSON command, reads one JSON response, and returns the parsed `messages` + `sorries` fields as the tool output. The tool wraps the protocol but does not import any repl code. Lands in `server/handlers/`.
- **Risk flags:** Requires a local Lean 4 + mathlib4 installation (`lake exe repl` must be on PATH). This is a system-level dependency, not a pip dep — arXMCP's `pyproject.toml` cannot declare it. Must be treated like `latexmlc`: guarded by a `requires_lean_repl` pytest marker, and the tool handler must return a graceful error when the binary is absent. The subprocess spawn latency (~1–2 s for first Lean elaboration) means this tool is not in the fast-path retrieval pipeline — it is a deliberate, slow verification call.

---

### 2.2 Vela-Engineering/kuzu (Kùzu fork)

- **URL:** https://github.com/Vela-Engineering/kuzu
- **License:** MIT
- **Stars:** 32 | **Last commit:** 2026-05-19 (5,262 commits on master)
- **What it does:** An actively maintained fork of the archived kuzudb/kuzu 0.11.3, developed by Vela Partners specifically for multi-agent AI workloads. The single meaningful addition to the upstream codebase is removal of the single-writer constraint, enabling concurrent writes from multiple agent threads. All Cypher query semantics, Python bindings, and the LanceDB-adjacent embedded model are preserved. The fork appears pip-installable as `kuzu` (same package name as upstream).
- **Specific capability worth borrowing:** **Concurrent multi-writer support** is not the primary need for arXMCP today (the citation graph is append-only during ingest and read-only at query time). The value is continuity: this fork keeps MIT-licensed Kùzu alive with active commits past the 2025-10-10 archive date, giving arXMCP a migration path that does not require a graph-DB rewrite. The Python binding compatibility means `ingest/kuzudb_schema.py`, `ingest/graph_ingest.py`, and `server/graph_queries.py` should work without modification.
- **arXMCP positioning:** Drop-in replacement (not a design-pattern lift). Update `pyproject.toml` pin from `kuzu==0.11.3` to `kuzu @ git+https://github.com/Vela-Engineering/kuzu` (or the PyPI name if published). No code changes required beyond the pin — unblocks the `cite_neighbors` tool handler wiring by removing the "pinned to an archived project" risk flag.
- **Risk flags:** 32 stars and unknown release cadence — abandonment risk is real if Vela Partners loses interest. The concurrent-writer focus suggests it is purpose-built for a narrower use case than arXMCP's; upstream compatibility may diverge if Vela adds multi-writer semantics that break single-writer assumptions. The Kineviz/bighorn fork (129 stars, MIT, last commit unknown) is an alternative but shows no clear recent activity signal. Migration should be done in a test branch with the full test suite (`tests/_graph_helpers.py` synthetic Kùzu fixtures) before cutting over.

---

### 2.3 lean-dojo/LeanDojo

- **URL:** https://github.com/lean-dojo/LeanDojo
- **License:** MIT
- **Stars:** 799 | **Last commit:** 2025-06-13 (v4.20.0)
- **What it does:** A Python library for machine-learning-oriented Lean 4 interaction. Provides two capabilities: (a) *static extraction* — traces a Lean repository and produces structured datasets of proof states, tactics, premises, and AST nodes; (b) *dynamic interaction* — spawns a Lean process and supports step-by-step tactic interaction, exposing proof goals at each step as Python objects. Powers the ReProver retrieval-augmented theorem prover (ByT5-based premise retriever + tactic generator, best-first proof search).
- **Specific capability worth borrowing:** The **theorem-state → premise-retrieval** design pattern from ReProver. At each proof step, the current goal string is embedded and used to retrieve relevant mathlib4 lemmas from a pre-indexed corpus. This is a direct analog of what arXMCP's `search_papers` tool does for informal context — the difference is that the retrieval target is a formal library (mathlib4 tactic/lemma corpus) rather than arXiv chunks. The design pattern: `proof_goal_string → embed → ANN search over pre-indexed mathlib4 → top-k lemmas → inject into tactician context` is a native re-implementation target for arXMCP's `search_papers` or a new `search_lemmas` tool.
- **arXMCP positioning:** Design-pattern lift. A new `search_lemmas` MCP tool in `server/handlers/search_lemmas.py` could serve as the retrieval half of the LeanDojo pattern — pre-index a mathlib4 lemma corpus using the existing BGE-M3 embedder + LanceDB pipeline, then expose it as a tool that accepts a proof-goal string and returns top-k lemma names + statements. No LeanDojo code imported; the embedding and retrieval infrastructure already exists in `ingest/` and `server/retrieval/`.
- **Risk flags:** Last commit was 2025-06-13 — 11 months ago. Still within the 9-month abandonment threshold but close to the edge. v4.20.0 supports Lean 4 ≥ v4.3.0-rc2; mathlib4 moves fast and there is a compatibility risk if the Lean version advances past what LeanDojo's tracer supports. The static extraction path (building the LeanDojo benchmark dataset) is heavyweight — requires a full mathlib4 build. For arXMCP's purpose (retrieving lemmas at query time), only the *pre-built* index needs to exist; the extraction step is a one-time offline cost.

---

### 2.4 LanceDB (lancedb/lancedb)

- **URL:** https://github.com/lancedb/lancedb
- **License:** Apache-2.0
- **Stars:** 10.4k | **Last commit:** 2026-05-22 (v0.33.0-beta.0 Python, v0.30.0-beta.0 Node/Rust)
- **What it does:** arXMCP's current vector store. Embedded Lance-format columnar storage with MVCC, HNSW vector indexing, BM25 full-text search, SQL-style scalar filters, and a PyArrow-backed schema. Active development: the main branch now ships **IVF_HNSW_FLAT** vector indexing (faster build, similar recall to pure HNSW), **model-backed native FTS tokenizers** (custom tokenization pipelines for BM25 without pickle serialization), **LSM write spec** for tuning write amplification, **nested field path support in native index creation**, and **nested vector column discovery by default**.
- **Specific capability worth borrowing:** **Model-backed native FTS tokenizers** (shipped May 2025, v0.32.0). arXMCP currently serializes a `rank-bm25` pickle index in `ingest/bm25_indexer.py` as a separate artifact from LanceDB's own BM25. Migrating to LanceDB's native FTS with a custom tokenizer (plugging in arXMCP's math-aware regex pre-tokenizer from `ingest/tokenizer.py`) would: (a) eliminate the separate pickle-index artifact, (b) make BM25 ACID-consistent with the LanceDB MVCC lifecycle, and (c) unblock scalar-filter pushdown in hybrid search (BM25 + ANN + filter in a single query plan).
- **arXMCP positioning:** Design-pattern lift → native re-implementation. Retire `ingest/bm25_indexer.py`'s pickle path; migrate to `lancedb.Table.create_fts_index(tokenizer=...)` with a Python tokenizer backed by `ingest/tokenizer.py`'s regex logic. Update `server/retrieval/bm25.py` to query via `table.search(...).where(...)` rather than loading a pickle. Target milestone: E15 or a follow-on E11 sub-step.
- **Risk flags:** The native FTS tokenizer API is in the Python beta channel (v0.33.x); the stable API surface may shift before a production pin. arXMCP currently pins `lancedb>=0.6` — a specific version bump with a regression test is needed. No GPU requirement.

---

### 2.5 MCP Python SDK (modelcontextprotocol/python-sdk)

- **URL:** https://github.com/modelcontextprotocol/python-sdk
- **License:** MIT
- **Stars:** 23.1k | **Last commit:** active (v1.x stable; v2 pre-alpha)
- **What it does:** The reference Python implementation of the Model Context Protocol. arXMCP already uses this (`mcp>=1.27,<2` pin). Recent additions beyond what arXMCP currently uses: **structured tool output** (Pydantic/TypedDict annotations produce auto-validated JSON schemas), **elicitation** (server requests additional user input mid-call), **sampling** (server invokes LLM completions through the client), **progress notifications** (`report_progress()` incremental updates), **resource subscriptions** (proactive `send_resource_updated()` notifications), **OAuth/TokenVerifier** authentication extensions, and **completions** (argument auto-complete for resource templates).
- **Specific capability worth borrowing:** **Progress notifications** (`report_progress()` with percentage + message) for long-running tools like `lean_verify` (proof elaboration can take 5–30 s). Also **structured tool output** — arXMCP's tool handlers return ad-hoc `dict` results; switching to annotated Pydantic response models would make the schema self-documenting and let the calling agent rely on validated structure rather than parsing free-text.
- **arXMCP positioning:** Design-pattern lift. For `lean_verify`: wire `progress_token` through the handler and emit progress notifications as the REPL subprocess produces intermediate output. For all handlers: replace the ad-hoc `dict` envelope with typed Pydantic response models. Neither change requires bumping the `mcp` pin; both are within the 1.x API already in use. Lands in `server/handlers/` (response models) and a new `server/handlers/lean_verify.py` (progress wiring).
- **Risk flags:** The v2 pre-alpha is in active design flux — the `<2` upper pin in `pyproject.toml` correctly buffers this. Progress notifications require the calling client (Claude) to display or forward them; if the client ignores `notifications/progress`, the benefit is zero. No GPU, no dep-bloat.

---

### 2.6 FastMCP (jlowin/fastmcp → now modelcontextprotocol/fastmcp)

- **URL:** https://github.com/jlowin/fastmcp
- **License:** Apache-2.0
- **Stars:** 25.3k | **Last commit:** 2026-05-15 (v3.3.1)
- **What it does:** A higher-level MCP server framework built on top of the MCP Python SDK. v3.x introduces a **proxy/gateway** pattern where a FastMCP instance can transparently forward tool calls to one or more upstream MCP servers, with transport negotiation, authentication, and lifecycle management handled automatically. Also provides declarative tool composition via `@mcp.tool` decorators, first-class resource and prompt abstractions, and built-in client symmetry for consuming other MCP servers.
- **Specific capability worth borrowing:** The **proxy/gateway pattern**. arXMCP could expose a `lean_verify` MCP tool that proxies to a separately running Lean REPL server (started by `lake exe repl` + a thin HTTP shim) rather than managing a subprocess inline. This decouples Lean's process lifecycle from arXMCP's FastAPI lifespan, making the Lean dependency optional and hot-swap-capable. The gateway pattern also opens a path to composing arXMCP with other MCP servers (e.g., a separate mathlib4-search server) without protocol-level changes.
- **arXMCP positioning:** Design-pattern lift. The proxy concept is the relevant idea — arXMCP would NOT import FastMCP (it already has its own `mcp>=1.27` integration). Instead, implement a `LeanReplClient` abstraction in `server/handlers/lean_verify.py` that speaks to the REPL subprocess with a well-defined start/stop/query lifecycle, mirroring the proxy pattern's separation of concerns.
- **Risk flags:** FastMCP v3 is diverging from the reference SDK ergonomics. 25k stars indicates strong community adoption, but arXMCP's custom FastAPI+MCP architecture is an intentional choice (E06_S01 design decision) and swapping frameworks would require re-wiring all 7 tool handlers. The proxy *pattern* is the take-away, not the library.

---

### 2.7 FlagEmbedding / BGE-M3 (FlagOpen/FlagEmbedding)

- **URL:** https://github.com/FlagOpen/FlagEmbedding
- **License:** MIT
- **Stars:** 11.7k | **Last commit:** 2026-04-22 (v1.4.0)
- **What it does:** arXMCP's current embedding family. BGE-M3 provides dense + sparse + ColBERT multi-vector retrieval in a single model. Recent additions: **BGE-VL** (multimodal image+text embeddings, March 2025), **bge-en-icl** (in-context-learning embeddings — inject task examples at query time), **bge-multilingual-gemma2** (9B parameter multilingual model), **bge-reranker-v2.5-gemma2-lightweight** (token compression + layerwise inference for faster reranking).
- **Specific capability worth borrowing:** **bge-en-icl** in-context-learning embeddings. For math retrieval, being able to inject a few exemplar (query, relevant-theorem) pairs at query time to sharpen the embedding for a specific proof context is directly useful — e.g., the tactician's current goal string as a query with a couple of known-relevant lemmas as ICL examples. This is a query-time improvement that does not require re-embedding the corpus. The model is significantly larger than BGE-M3, so a lightweight variant matters.
- **arXMCP positioning:** Design-pattern lift → native re-implementation. The ICL approach does not require importing a new model; it can be prototyped by modifying the query prefix in `server/retrieval/ann.py` to prepend few-shot examples before embedding. A future model swap (BGE-M3 → bge-en-icl) is a one-file change in `ingest/embedder.py` if the vector dimension matches (1024 → verify). No re-indexing needed for the query path; re-embedding the corpus is needed only if the model is swapped for the index path.
- **Risk flags:** bge-en-icl is a 7B+ parameter model — significantly larger than BGE-M3 (570M). On a single workstation without GPU, inference latency increases ~10–30x. The model-swap path is a future E15+ concern, not a near-term action. Staying on BGE-M3 for the index and using ICL only for query re-ranking is the correct local-first-preserving posture.

---

### 2.8 pgvector (pgvector/pgvector)

- **URL:** https://github.com/pgvector/pgvector
- **License:** PostgreSQL License (OSI-approved, BSD-style)
- **Stars:** 21.4k | **Last commit:** v0.8.2 (recent)
- **What it does:** A PostgreSQL extension adding `vector`, `halfvec`, `sparsevec`, and `bit` column types with HNSW and IVFFlat indexes. Recent additions (within the study window): **iterative index scans** for HNSW (better recall under filtered queries), **binary quantization** (up to 64k dimensions, faster build), **half-precision halfvec** (up to 4k dims, reduced memory), **sparsevec type** (up to 1000 non-zero elements), and **L1/Hamming/Jaccard distance operators**.
- **Specific capability worth borrowing:** **Iterative HNSW index scans** — pgvector's pattern of automatically widening the HNSW search beam when the filtered result count falls below k is a design idea arXMCP's LanceDB query path doesn't yet implement. arXMCP's `server/retrieval/ann.py` fetches `top_k * OVERSAMPLE` and applies filters post-hoc; a cleaner pattern is to iterate, widening the HNSW candidate set, until k post-filter results are returned.
- **arXMCP positioning:** Design-pattern lift. Implement an iterative-widening loop in `server/retrieval/ann.py`'s `search()` function: if `len(filtered_results) < k`, double `top_k` and re-query, up to a configurable max multiplier (e.g., 8x). This is a pure-Python change inside the existing retrieval module.
- **Risk flags:** pgvector requires PostgreSQL — not relevant as an import for arXMCP (LanceDB is the storage layer). The pattern is the take-away. Postgres itself is a distributed-system dependency arXMCP correctly avoids.

---

### 2.9 Sentence-Transformers (UKPLab/sentence-transformers)

- **URL:** https://github.com/UKPLab/sentence-transformers
- **License:** Apache-2.0
- **Stars:** 18.7k | **Last commit:** 2026-05-20 (v5.5.1)
- **What it does:** The standard Python tooling for embedding model training, fine-tuning, and inference. v5.x adds: **Matryoshka embedding models** (variable-size embeddings truncated with minimal quality loss — enabling adaptive dimensionality), **Sparse Encoder models** (sparse embedding training + inference alongside dense), **20+ loss functions for dense + 10+ for sparse** training.
- **Specific capability worth borrowing:** **Matryoshka embedding support** for adaptive dimensionality. arXMCP stores BGE-M3 vectors at full 1024 dimensions in LanceDB. If BGE-M3 is fine-tuned or replaced with a Matryoshka-aware model, the vector dimension could be reduced for Tier-0/1 cache lookups (e.g., 256-dim for cache hit detection) while the full 1024-dim vector is used for final ANN. This would shrink the Tier-2 FAISS cache in `server/cache.py` by 4x with minimal recall cost.
- **arXMCP positioning:** Design-pattern lift → future native re-implementation. The Matryoshka pattern is a model-training concern, not a current sprint item. Relevant when BGE-M3 is upgraded or fine-tuned. Note the pattern in `server/cache.py`'s FAISS ring buffer as a candidate for dimension reduction.
- **Risk flags:** Sentence-Transformers v5 requires PyTorch ≥2.0 (already satisfied). Matryoshka inference requires a model trained with Matryoshka loss — BGE-M3 was not. This is a future fine-tuning investment, not a drop-in today.

---

### 2.10 Vela-Engineering/kuzu + Kineviz/bighorn (comparative)

(Bighorn captured separately for reference in the sources table; Vela is the primary candidate — see §2.2.)

- **URL:** https://github.com/Kineviz/bighorn
- **License:** MIT
- **Stars:** 129 | **Last commit:** not explicitly surfaced (post-archive activity unclear)
- **What it does:** A Kineviz-maintained fork of kuzudb/kuzu 0.11.3, preserving the original codebase as-is without the concurrent-writer additions in Vela's fork.
- **Specific capability worth borrowing:** Lower-risk continuity than Vela — no API changes, pure preservation fork. But 129 stars and no clear development signal makes it a weaker choice than Vela.
- **arXMCP positioning:** Fallback option only if Vela's fork proves incompatible. Not the primary recommendation.
- **Risk flags:** No evidence of active development beyond fork maintenance. Do not use as the primary migration path.

---

## 3. Sources reviewed

| Project | URL | Stars | Last commit (approx.) | High-signal? |
|---|---|---|---|---|
| leanprover-community/repl | https://github.com/leanprover-community/repl | 203 | active (2025–2026) | YES |
| Vela-Engineering/kuzu | https://github.com/Vela-Engineering/kuzu | 32 | 2026-05-19 | YES |
| lean-dojo/LeanDojo | https://github.com/lean-dojo/LeanDojo | 799 | 2025-06-13 | YES |
| lean-dojo/ReProver | https://github.com/lean-dojo/ReProver | 326 | 2025 (active) | YES |
| lancedb/lancedb | https://github.com/lancedb/lancedb | 10,400 | 2026-05-22 | YES |
| modelcontextprotocol/python-sdk | https://github.com/modelcontextprotocol/python-sdk | 23,100 | 2026-05-22 | YES |
| jlowin/fastmcp | https://github.com/jlowin/fastmcp | 25,300 | 2026-05-15 | YES |
| FlagOpen/FlagEmbedding | https://github.com/FlagOpen/FlagEmbedding | 11,700 | 2026-04-22 | YES |
| pgvector/pgvector | https://github.com/pgvector/pgvector | 21,400 | recent (v0.8.2) | YES (pattern only) |
| UKPLab/sentence-transformers | https://github.com/UKPLab/sentence-transformers | 18,700 | 2026-05-20 | YES (future) |
| kuzudb/kuzu (archived) | https://github.com/kuzudb/kuzu | 3,900 | 2025-10-10 | NO (archived) |
| Kineviz/bighorn | https://github.com/Kineviz/bighorn | 129 | unclear | LOW |
| trishullab/copra | https://github.com/trishullab/copra | 73 | unclear | LOW |
| leanprover/lean4 | https://github.com/leanprover/lean4 | 8,100 | 2026-04-14 | YES (context only) |
| leanprover-community/mathlib4 | https://github.com/leanprover-community/mathlib4 | 3,300 | 2026-04-18 | YES (context only) |
| stanford-futuredata/ColBERT | https://github.com/stanford-futuredata/ColBERT | 3,900 | stale (362 commits, GPU-req) | NO |
| brucemiller/LaTeXML | https://github.com/brucemiller/LaTeXML | 1,300 | 2024-02-26 | LOW (no recent activity) |
| qdrant/qdrant | https://github.com/qdrant/qdrant | 31,500 | 2026-05-22 | LOW (not local-first) |
| chroma-core/chroma | https://github.com/chroma-core/chroma | 28,100 | 2026-05-05 | LOW (duplicate of LanceDB) |
| duckdb/duckdb | https://github.com/duckdb/duckdb | 38,400 | 2026-05-20 | LOW (no graph/vector ANN) |
| microsoft/multilspy | https://github.com/microsoft/multilspy | 575 | 2026-04-16 | NO (no Lean 4 support) |
| wellecks/ntptutorial | https://github.com/wellecks/ntptutorial | 179 | 2023 (IJCAI tutorial) | NO (educational, stale) |

---

## 4. Themes

**Verification feedback is an unsolved gap.** Every existing arXMCP tool returns retrieved or pre-computed content; none closes the verify→error→revise loop. The Lean 4 REPL project (leanprover-community/repl) represents a minimal, local-first, zero-dependency primitive for bridging this gap — the protocol is 10 lines of JSON and a subprocess, not a distributed system. **The citation-graph stub is a dependency problem, not a design problem.** The `cite_neighbors` tool is architecturally complete (`server/graph_queries.py` is real); the only blocker is the archived Kùzu pin, which the Vela fork directly resolves. **Math-domain retrieval improvements converge on two design patterns**: ICL-enhanced query embeddings (bge-en-icl) for sharper proof-goal→lemma matching, and iterative-widening HNSW search (pgvector pattern) for better recall under filter constraints — both are CPU-friendly, pattern-lift changes to existing arXMCP modules. **LanceDB's native FTS tokenizer** eliminates the most operationally fragile part of the current pipeline (the separate `rank-bm25` pickle artifact), but requires a careful version bump since the feature is still in the beta channel.

---

## 5. Out of scope / parking lot

| Project | Reason rejected |
|---|---|
| ColBERT / RAGatouille | GPU-required for indexing; `cpu_inference` branch deprecated; math-domain results absent; stale main branch |
| Qdrant | Requires a separate server process; violates local-first single-workstation constraint; no embedded mode parity with LanceDB |
| ChromaDB 1.5.9 | Provides no capabilities not already covered by LanceDB; redundant addition would increase dep surface without net gain |
| DuckDB | Graph and ANN capabilities not surfaced in release notes; primary strength is OLAP analytics, not vector search — no clear migration path from LanceDB |
| pandoc | GPL-2.0 — study-only under arXMCP no-fork policy; LaTeX→HTML conversion already handled by LaTeXML; no theorem-structure improvement identified |
| LaTeXML (brucemiller/LaTeXML) | Last commit 2024-02-26 — 15 months without a release; arXMCP already depends on it (`requires_latexmlc` marker); no new theorem-parsing capability to surface; drift detector (E10_S04) already handles its known limitations |
| trishullab/copra | 73 stars; last commit unclear; COPRA's multi-ITP REPL management is useful but its architecture is heavier than the minimal lean-repl approach; pattern already captured via leanprover-community/repl |
| microsoft/multilspy | No Lean 4 LSP support confirmed; general-purpose LSP client library with no proof-state handling; does not close the verification gap |
| wellecks/ntptutorial | Educational repo (IJCAI 2023); no production infrastructure; stale |
| bgm-reranker-v2.5-gemma2-lightweight | 9B+ parameter reranker; eliminates local-first CPU inference posture; defer to GPU-enabled future milestone |
| BGE-VL (multimodal) | Image+text embeddings; arXMCP's corpus is text+math, no image retrieval need identified |
| leanprover-community/lean4 LSP | Lean 4's built-in LSP server (elan/lake) is documented but not separately packaged; interaction via leanprover-community/repl is the correct abstraction level for arXMCP |

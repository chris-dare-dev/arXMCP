# E01 — Vertical Slice (Tier 0)

**Epic dependencies:** none. This is the root epic; everything else depends on it.

**Goal:** prove the end-to-end loop on a 50-paper math.AG sub-corpus before scaling anything. Exit criterion (from `09-feature-priorities.md`): a Claude Code agent can call `search_papers` against the running server and get back a coherent `chunk_id` + snippet for "find the theorem about X in this corpus." No quality, no scale, no caching — just the loop wired together.

**Effort:** 1–2 weeks calendar.

**References:** `09-feature-priorities.md` (Tier 0 checklist), `02-architecture-overview.md` (full diagram), `06-mcp-server-design.md` (transport, `search_papers` tool surface).

---

### E01_S01 — Initialize repo skeleton with mono-repo layout

**Description.** Create the top-level directory layout the rest of the roadmap assumes: `server/` (Streamable HTTP MCP server), `ingest/` (separate ingestion process), `shim/` (stdio proxy), `infra/` (docker-compose), `tests/`, plus root `pyproject.toml` (or per-component pyprojects) and a `README.md` that points at `.claude/notes/`. No code logic — structure only. See `08-security-observability-ops.md` § Docker deployment for the eventual two-service compose target.

**Acceptance criteria.**
- [ ] `server/`, `ingest/`, `shim/`, `infra/`, `tests/` directories exist with placeholder `__init__.py` / `README.md` markers.
- [ ] Top-level `pyproject.toml` with at least Python ≥3.11 and ruff + pytest pinned.
- [ ] `make help` (or equivalent) lists the planned dev tasks (`bootstrap`, `test`, `up`, `ingest`).
- [ ] `.gitignore` excludes `.venv/`, `__pycache__/`, `/var/arxmcp/` (the on-disk corpus path used in `03-ingestion-pipeline.md`).
- [ ] Root `README.md` links to `.claude/notes/README.md` and lists the four target arXiv categories.

**Dependencies.** none.

**Complexity.** S.

**Labels.** `area:infra`, `kind:infra`, `tier:0`.

---

### E01_S02 — Pick one math.AG paper and verify hand-fetch of `/e-print/` source

**Description.** Choose a clean math.AG paper (post-2010, single .tex file, no exotic `.sty` chain — for example, a recent Annals or Duke paper that ships cleanly). Manually fetch `https://arxiv.org/e-print/<paper_id>` per `03-ingestion-pipeline.md` § Source 3, untar it, and confirm the .tex compiles with vanilla LaTeXML. This proves the source-fetch path works end-to-end with the politeness headers required by arXiv's TOS.

**Acceptance criteria.**
- [ ] `tools/fetch_one_paper.py` (or equivalent script) downloads a single `/e-print/` tarball using the `arXMCP/0.1 (mailto:...)` `User-Agent` per `03-ingestion-pipeline.md`.
- [ ] Tarball is extracted under `var/arxmcp/corpus/raw/<paper_id>/`.
- [ ] LaTeXML 0.8.x or newer runs against the extracted source and emits HTML5+MathML to `var/arxmcp/corpus/parsed/<paper_id>/`.
- [ ] Script exits cleanly on the chosen paper.
- [ ] The chosen paper ID is committed in a `tools/seed-papers.txt` file alongside the script.

**Dependencies.** E01_S01.

**Complexity.** S.

**Labels.** `area:ingestion`, `kind:research`, `tier:0`.

---

### E01_S03 — Hand-pick 50 math.AG seed papers and stage their source

**Description.** Extend the single-paper script from E01_S02 to a list of 50 math.AG arXiv IDs, fetched serially with the 3-second-per-IP politeness rule from `03-ingestion-pipeline.md` § Source 3. The 50 papers should bias toward post-2015 submissions with clean .tex (no JHEP-style class file chains). This is the seed corpus for the rest of E01.

**Acceptance criteria.**
- [ ] `tools/seed-papers.txt` lists 50 arXiv IDs from category math.AG.
- [ ] `tools/fetch_seed.py` walks the list, fetches each, and writes raw + LaTeXML output under `var/arxmcp/corpus/`.
- [ ] Fetch loop honors a 3-second sleep between requests and 503 backoff.
- [ ] At least 45 of 50 papers parse successfully via LaTeXML; failures are listed in `var/arxmcp/ops/parser-failures/seed.log`.
- [ ] Total wall-clock for the fetch is documented (used as a sanity baseline before E11 scales this up).

**Dependencies.** E01_S02.

**Complexity.** M.

**Labels.** `area:ingestion`, `tier:0`.

---

### E01_S04 — Naive section-only chunker

**Description.** Implement the simplest possible chunker: split the LaTeXML HTML on `<section>` boundaries and emit one chunk per section. No theorem/proof pairing, no equation atoms, no preamble — those land in E04. The chunker writes JSON to `var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json` with a minimal record `{paper_id, chunk_idx, section_path, body_text}`. Per `09-feature-priorities.md` Tier 0 explicitly says "Naive chunker: split on `\section` only; macro normalization stub."

**Acceptance criteria.**
- [ ] `ingest/chunker_v0.py` reads parsed HTML for one paper and emits 1–N chunk JSON files.
- [ ] Chunks include `paper_id`, `chunk_idx`, `section_path`, and a `body_text` field of plaintext (LaTeX retained verbatim; no canonicalization).
- [ ] Running on the 50 seed papers produces at least 200 total chunks.
- [ ] No external state is written outside `var/arxmcp/corpus/chunks/`.
- [ ] Unit test: chunker on a fixture two-section HTML emits exactly two chunks with the expected `section_path`.

**Dependencies.** E01_S03.

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`, `tier:0`.

---

### E01_S05 — Stub macro normalizer (no-op pass-through)

**Description.** Per Tier 0 in `09-feature-priorities.md`, ship a "macro normalization stub" — a function that today just returns its input unchanged but defines the call site that will later be filled by E03. This is scaffolding so E02–E04 can land cleanly without a refactor.

**Acceptance criteria.**
- [ ] `ingest/macros.py` exposes `normalize(html: str, paper_id: str) -> NormalizedDoc`.
- [ ] `NormalizedDoc` is a dataclass with `body`, `notation_table`, `chunker_version` fields.
- [ ] Stub returns `body=html`, empty `notation_table`, `chunker_version="v0.0-stub"`.
- [ ] Chunker (E01_S04) calls `normalize` before splitting.
- [ ] Module docstring cites `04-parsing-and-chunking.md` § Macro normalization as the contract this stub will eventually satisfy.

**Dependencies.** E01_S04.

**Complexity.** S.

**Labels.** `area:parser`, `kind:feature`, `tier:0`.

---

### E01_S06 — LanceDB v0 single-table write path

**Description.** Stand up LanceDB locally, create one table named `chunks_v0` with columns `chunk_id` (string), `paper_id` (string), `body_text` (string), and `embedding` (fixed_size_list<float32, 1024>) — single embedding column, no hybrid, no scalar indices. Write the seed-corpus chunks to it. Per `05-storage-and-indexing.md` § Vector + lexical index: LanceDB; this is the v0 of that table, not the full schema.

**Acceptance criteria.**
- [ ] `ingest/store_v0.py` creates the table at `var/arxmcp/index/lancedb/v0001/` if missing.
- [ ] Each seed-corpus chunk is upserted with a placeholder zero vector.
- [ ] Total row count matches the chunk count from E01_S04.
- [ ] `chunk_id` follows the format `arxiv:<paper_id>:<chunk_idx>` (full content-addressable ID lands in E04).
- [ ] A read-back query (`dataset.to_pandas().head()`) returns the expected rows.

**Dependencies.** E01_S04.

**Complexity.** M.

**Labels.** `area:storage`, `kind:feature`, `tier:0`.

---

### E01_S07 — Embed seed chunks with bge-m3 and overwrite the placeholder vectors

**Description.** Load `BAAI/bge-m3` (the v1 default per `05-storage-and-indexing.md` § Embedding strategy), embed each chunk's `body_text`, and overwrite the placeholder vectors in the LanceDB table from E01_S06. CPU-only is fine for 50 papers; the GPU path is an E11 concern.

**Acceptance criteria.**
- [ ] `ingest/embed_v0.py` loads bge-m3 from a pinned commit SHA (per `08-security-observability-ops.md` Threat 6).
- [ ] All seed-corpus chunks are embedded and the LanceDB column populated.
- [ ] Embedding dimension matches the table schema declared in E01_S06.
- [ ] Re-running the script is idempotent (skips rows whose embedding is already populated).
- [ ] An HNSW vector index is created on the `embedding` column (M=16, efConstruction=200 per `05-storage-and-indexing.md`).

**Dependencies.** E01_S06.

**Complexity.** M.

**Labels.** `area:storage`, `area:embedder`, `tier:0`.

---

### E01_S08 — Streamable HTTP MCP server skeleton with `search_papers` only

**Description.** Build a minimal long-running MCP server bound to `127.0.0.1:7733` that implements the Streamable HTTP transport per `06-mcp-server-design.md` § Transport. Expose exactly one tool: `search_papers` with the schema from `06-mcp-server-design.md` (query, level, k, filters, cursor — but for v0 only `query` and `k` are honored). Implementation does dense ANN over the LanceDB table from E01_S07 and returns the top-k as `structuredContent`. No caching, no reranker, no hybrid — those come later.

**Acceptance criteria.**
- [ ] `server/main.py` starts an aiohttp/FastAPI app that responds to JSON-RPC over Streamable HTTP per the MCP 2025-06-18 spec.
- [ ] `tools/list` returns exactly one tool entry: `search_papers`.
- [ ] `tools/call` for `search_papers` accepts `{query, k}` and returns `{structuredContent: {results: [...], corpus_version: 1, embed_model: "bge-m3@<sha>"}}`.
- [ ] Each result includes `chunk_id`, `paper_id`, `score`, `snippet` (≤200 chars).
- [ ] Server binds to `127.0.0.1` only; binds to a random port in tests.
- [ ] `Origin` header validation accepts requests from the stdio shim (no Origin header) and rejects non-localhost origins (full hardening in E13).

**Dependencies.** E01_S07.

**Complexity.** L.

**Labels.** `area:server`, `kind:feature`, `tier:0`.

---

### E01_S09 — `arxmcp-shim` stdio proxy

**Description.** Implement the ~50-line stdio shim per `06-mcp-server-design.md` § Transport. The shim reads JSON-RPC frames from stdin, forwards each as an HTTP POST to `http://127.0.0.1:7733`, and writes the response body to stdout. Stateless. The shim is registered in `~/.claude.json` so each Claude sub-agent that wants to use arXMCP spawns it.

**Acceptance criteria.**
- [ ] `shim/arxmcp-shim` is an executable script that takes `--server <url>` argument.
- [ ] Shim forwards JSON-RPC requests verbatim and returns responses verbatim — no stateful transformation.
- [ ] Shim performs a single `GET /readyz` probe at startup and exits non-zero if the server is not ready (per `06-mcp-server-design.md` § Health and readiness).
- [ ] Sample `~/.claude.json` snippet is in `docs/install.md`.
- [ ] End-to-end test: a fixture JSON-RPC `tools/list` request piped into the shim returns the expected tool list.

**Dependencies.** E01_S08.

**Complexity.** S.

**Labels.** `area:server`, `kind:feature`, `tier:0`.

---

### E01_S10 — End-to-end happy-path test from a Claude Code session

**Description.** Manual verification step from the Tier 0 exit criterion in `09-feature-priorities.md`: register the shim in `~/.claude.json`, spawn a Claude Code session, and ask "find the theorem about <topic> in this corpus." Confirm the agent calls `search_papers` and gets back at least one chunk with a coherent snippet. This is the gate that proves the loop is wired end-to-end before E02 starts replacing pieces.

**Acceptance criteria.**
- [ ] `~/.claude.json` contains an `arxmcp` entry pointing at the shim.
- [ ] A documented Claude Code session transcript (in `docs/tier-0-demo.md`) shows the agent invoking `search_papers` and receiving a non-empty result.
- [ ] At least one returned `chunk_id` resolves to a real chunk file under `var/arxmcp/corpus/chunks/`.
- [ ] No exceptions in `server/` logs during the session.
- [ ] Demo transcript includes the exact query phrasing used for reproducibility.

**Dependencies.** E01_S09.

**Complexity.** S.

**Labels.** `area:server`, `kind:research`, `tier:0`.

---

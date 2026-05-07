# E01 — Vertical Slice (PRESERVED — DONE)

**Epic dependencies:** none. This is the root epic; everything else depends on it.

**Goal:** Prove the end-to-end loop on a 50-paper math.AG sub-corpus before scaling anything. Exit criterion (from `09-feature-priorities.md`): a Claude Code agent can call `search_papers` against the running server and get back a coherent `chunk_id` + snippet for "find the theorem about X in this corpus." No quality, no scale, no caching — just the loop wired together.

**Effort:** Shipped — approximately 1–2 weeks calendar time across commits `8633cc6` through `01c6579`.

**References:** `09-feature-priorities.md` (Tier 0 checklist), `02-architecture-overview.md` (full diagram), `06-mcp-server-design.md` (transport, `search_papers` tool surface), `03-ingestion-pipeline.md` (fetch politeness rules), `08-security-observability-ops.md` (Threat 6, pinned model SHA).

---

### E01_S01 — Initialize repo skeleton with mono-repo layout

**Status:** DONE (commit `8633cc6` — approximate; repo skeleton established in earliest commits)
**Tier:** 0
**Effort:** S
**Dependencies:** none

**Description.** Create the top-level directory layout the rest of the roadmap assumes: `server/` (Streamable HTTP MCP server), `ingest/` (separate ingestion process), `shim/` (stdio proxy), `infra/` (docker-compose), `tests/`, plus root `pyproject.toml` (or per-component pyprojects) and a `README.md` that points at `.claude/notes/`. No code logic — structure only. See `08-security-observability-ops.md` § Docker deployment for the eventual two-service compose target.

**Deliverables.**
- `server/`, `ingest/`, `shim/`, `infra/`, `tests/` directories with placeholder markers
- Root `pyproject.toml` with Python ≥3.11, ruff, pytest pinned
- `Makefile` with `bootstrap`, `test`, `up`, `ingest` targets
- `.gitignore` excluding `.venv/`, `__pycache__/`, `/var/arxmcp/`
- Root `README.md` linking to `.claude/notes/README.md`

**Acceptance criteria.**
- [x] `server/`, `ingest/`, `shim/`, `infra/`, `tests/` directories exist with placeholder `__init__.py` / `README.md` markers.
- [x] Top-level `pyproject.toml` with at least Python ≥3.11 and ruff + pytest pinned.
- [x] `make help` (or equivalent) lists the planned dev tasks (`bootstrap`, `test`, `up`, `ingest`).
- [x] `.gitignore` excludes `.venv/`, `__pycache__/`, `/var/arxmcp/` (the on-disk corpus path used in `03-ingestion-pipeline.md`).
- [x] Root `README.md` links to `.claude/notes/README.md` and lists the four target arXiv categories.

**Out of scope.** No code logic, no ingestion, no server — structure only. Full server skeleton is E01_S08 (superseded by E06).

**Risk notes.**
- Establishes the `var/arxmcp/` path convention used throughout all subsequent epics.

**Shipped:** Repo skeleton established in earliest project commits. See git log for `pyproject.toml`, `Makefile`, `.gitignore`.

**Labels.** `area:infra`, `kind:infra`, `tier:0`.

---

### E01_S02 — Pick one math.AG paper and verify hand-fetch of `/e-print/` source

**Status:** DONE (commit `8633cc6`)
**Tier:** 0
**Effort:** S
**Dependencies:** E01_S01

**Description.** Choose a clean math.AG paper (post-2010, single .tex file, no exotic `.sty` chain). Manually fetch `https://arxiv.org/e-print/<paper_id>` per `03-ingestion-pipeline.md` § Source 3, untar it, and confirm the .tex compiles with vanilla LaTeXML. This proves the source-fetch path works end-to-end with the politeness headers required by arXiv's TOS.

**Deliverables.**
- `tools/fetch_one_paper.py` — single-paper download script
- `var/arxmcp/corpus/raw/<paper_id>/` — extracted tarball
- `var/arxmcp/corpus/parsed/<paper_id>/` — LaTeXML HTML5+MathML output
- `tools/seed-papers.txt` — committed paper ID

**Acceptance criteria.**
- [x] `tools/fetch_one_paper.py` (or equivalent script) downloads a single `/e-print/` tarball using the `arXMCP/0.1 (mailto:...)` `User-Agent` per `03-ingestion-pipeline.md`.
- [x] Tarball is extracted under `var/arxmcp/corpus/raw/<paper_id>/`.
- [x] LaTeXML 0.8.x or newer runs against the extracted source and emits HTML5+MathML to `var/arxmcp/corpus/parsed/<paper_id>/`.
- [x] Script exits cleanly on the chosen paper.
- [x] The chosen paper ID is committed in a `tools/seed-papers.txt` file alongside the script.

**Out of scope.** Batch fetch (E01_S03), chunking, embedding — all later milestones.

**Risk notes.**
- arXiv TOS compliance (3-second politeness delay) established here; ingestion-at-scale tracking in E11.

**Shipped:** `tools/fetch_one_paper.py` and initial `tools/seed-papers.txt` entry. See commit `8633cc6`.

**Labels.** `area:ingestion`, `kind:research`, `tier:0`.

---

### E01_S03 — Hand-pick 50 math.AG seed papers and stage their source

**Status:** DONE (commits `c486b26`, `a79a802`, `6a69a2b`, `0280852`, `01c6579`)
**Tier:** 0
**Effort:** M
**Dependencies:** E01_S02

**Description.** Extend the single-paper script from E01_S02 to a list of 50 math.AG arXiv IDs, fetched serially with the 3-second-per-IP politeness rule from `03-ingestion-pipeline.md` § Source 3. The 50 papers should bias toward post-2015 submissions with clean .tex (no JHEP-style class file chains). This is the seed corpus for the rest of E01 — and the basis for the E05 eval harness that gates Tier-0 exit.

**Deliverables.**
- `tools/seed-papers.txt` — 50 math.AG arXiv IDs
- `tools/fetch_seed.py` — batch fetch loop
- `var/arxmcp/corpus/raw/<paper_id>/` — 50 extracted tarballs
- `var/arxmcp/corpus/parsed/<paper_id>/` — LaTeXML output for ≥45 papers
- `var/arxmcp/ops/parser-failures/seed.log` — failure log

**Acceptance criteria.**
- [x] `tools/seed-papers.txt` lists 50 arXiv IDs from category math.AG.
- [x] `tools/fetch_seed.py` walks the list, fetches each, and writes raw + LaTeXML output under `var/arxmcp/corpus/`.
- [x] Fetch loop honors a 3-second sleep between requests and 503 backoff.
- [x] At least 45 of 50 papers parse successfully via LaTeXML; failures are listed in `var/arxmcp/ops/parser-failures/seed.log`.
- [x] Total wall-clock for the fetch is documented (used as a sanity baseline before E11 scales this up).

**Out of scope.** Chunking, embedding, BM25 indexing, server — all later epics. Multi-category ingest (math.NT, hep-th, math-ph) is E11.

**Risk notes.**
- 503 backoff and per-paper exception catching shipped in commits `0280852` and `01c6579` to fix brittle loop.
- Tar-vs-tex sniffing fixed in commit `0280852` (decompressed bytes, not Content-Type header).

**Shipped:** Commits `c486b26` (50-paper fetch loop), `a79a802` (seed list populated), `6a69a2b` (seed-papers.txt with 50 curated IDs), `0280852` (tar sniff fix), `01c6579` (per-paper exception catching).

**Labels.** `area:ingestion`, `tier:0`.

---

### E01_S04 — Naive section-only chunker

**Status:** SUPERSEDED_BY E02_S01

E01_S04 (naive section chunker) is superseded by **E02_S01** because the new design requires theorem+proof pairing and dual 512-tok embedding columns (`embedding_stmt` + `embedding_proof`) from the start. A section-only chunker would force a destructive schema refactor at Tier 1 and cannot produce the content-addressable `chunk_id`s that the E05 eval harness references by hash. Implementing a temporary chunker would yield throw-away artifacts and mislead the ground-truth fixture curation in E02_S05.

---

### E01_S05 — Stub macro normalizer (no-op pass-through)

**Status:** SUPERSEDED_BY E02_S02

E01_S05 (stub macro normalizer) is superseded by **E02_S02** because the new design collapses the stub into the preamble extractor milestone. Rather than a no-op pass-through, E02_S02 implements a real `preamble.json` per paper (extracting `\newcommand`, `\renewcommand`, `\DeclareMathOperator`, `\def`) and defines the deterministic preamble-prepend contract that replaces the original stub's `NormalizedDoc` dataclass. A stub would add dead code that must be ripped out immediately.

---

### E01_S06 — LanceDB v0 single-table write path

**Status:** SUPERSEDED_BY E04_S01

E01_S06 (single-column `embedding` LanceDB table) is superseded by **E04_S01** because the v1 schema introduces two required embedding columns (`embedding_stmt`, `embedding_proof`) and a reserved nullable `embedding_eq` column from day one; a single-column v0 table would require a destructive migration. E04_S01 also replaces the `v0001/` directory convention with native LanceDB MVCC versioning via `dataset.checkout(version=N)` per the critique finding on symlink swaps (MEDIUM).

---

### E01_S07 — Embed seed chunks with bge-m3 and overwrite the placeholder vectors

**Status:** SUPERSEDED_BY E03_S01 + E03_S02

E01_S07 (single-column embedding pass) is superseded jointly by **E03_S01** (which defines the dual-column `embedding_stmt` / `embedding_proof` batch encoder with a pinned BGE-M3 commit SHA and explicit GIL notes) and **E03_S02** (idempotent re-embed that skips already-populated rows and handles chunker_version bumps). The original milestone embedded a single column without version tracking; the new design requires both columns and a version-aware skip logic from the first write.

---

### E01_S08 — Streamable HTTP MCP server skeleton with `search_papers` only

**Status:** SUPERSEDED_BY E06_S01

E01_S08 (minimal aiohttp/FastAPI MCP server skeleton) is superseded by **E06_S01**, which builds the full Streamable HTTP server with the complete 7-tool surface (`search_papers`, `get_chunk`, `find_equation`, `get_definitions`, `find_lemma_by_name`, `get_paper`, `cite_neighbors` — `list_papers` collapsed into `search_papers(level="paper")` per E06_S03), Origin-header validation (E06_S05), and the `readyz` / `livez` health probes. Standing up a bare-bones skeleton first would require replacing rather than extending the transport layer at Tier 1.

---

### E01_S09 — `arxmcp-shim` stdio proxy

**Status:** SUPERSEDED_BY E06_S02

E01_S09 (stdio shim) is superseded by **E06_S02** (Sonnet B), which ships the shim alongside the full server in E06 so that the shim's `--server <url>` argument, the `GET /readyz` startup probe, and the `~/.claude.json` registration instructions are all written against the final server URL rather than a stub endpoint. Building the shim against E01_S08's skeleton would require a revisit.

---

### E01_S10 — End-to-end happy-path test from a Claude Code session

**Status:** SUPERSEDED_BY E05_S03

E01_S10 (manual "vibes-check" Claude Code session transcript) is superseded by **E05_S03**, which defines the Tier-0 exit gate as a measurable nDCG@5 ≥ 0.70 ANN-only score against 20 hand-labeled queries — a repeatable, automatable standard rather than a one-time qualitative demo. The transcript-based gate would pass even if retrieval quality were poor; the eval harness catches real regressions.

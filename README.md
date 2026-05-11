# arXMCP

A local-first [Model Context Protocol (MCP)](https://modelcontextprotocol.io/specification/2025-06-18)
server that exposes a research-mathematics arXiv corpus to multi-agent Claude
pipelines. Designed for a workflow where a Claude **sketcher → autoformalizer →
tactician → fixer** pipeline shares one substrate of grounded math context.

The full design rationale lives in [`.claude/notes/01-mission-and-context.md`](.claude/notes/01-mission-and-context.md).

**Target arXiv categories:** `math.AG`, `math.NT`, `math-ph`, `hep-th`.

---

## Status

- **Tier 0 → Tier 2 epics SHIPPED** (E01–E09). 4 milestones × 9 epics; every
  milestone closed via the [`milestone-pipeline`](.claude/skills/milestone-pipeline/SKILL.md)
  four-phase Research → Implement → Critique → Rectify discipline.
- **1312 tests passing**, 4 skipped (`requires_model`), `ruff check .` clean.
- **Tier-3+ epics PENDING:** E10 (specialized indices), E11 (scale cutover —
  production ingest driver), E13 (security audit), E14 (observability/ops).
- **Eval gate (Tier-0 → Tier-1)** harness shipped; the curated 20-query
  fixture for the actual gate run is still being hand-labeled (see
  [`docs/eval-curation.md`](docs/eval-curation.md) and
  [`docs/retrieval-quality-report.md`](docs/retrieval-quality-report.md)).

See [`.claude/roadmap/README.md`](.claude/roadmap/README.md) for the
authoritative epic index with current ship status.

---

## Quick start

```bash
# 1. bootstrap (Python ≥3.11, create venv, install deps, create var/ tree)
python3 -m venv .venv && source .venv/bin/activate
make bootstrap

# 2. fetch the 50-paper math.AG seed corpus (one-time; takes ~15min on first run)
export ARXMCP_CONTACT_EMAIL=you@example.com   # arXiv TOS §3 polite-pool
python tools/fetch_seed.py                    # idempotent; ≥45/50 must succeed

# 3. (optional) run the test suite
make test                                     # ruff + pytest (~1m for full suite)

# 4. start the long-running MCP server on 127.0.0.1:7733
make up                                       # python -m server.main

# 5. register the stdio shim in Claude Code's ~/.claude.json
#    (see docs/install.md for the JSON snippet)
```

Full operator setup: [`docs/install.md`](docs/install.md).
Makefile targets: `make help`.

---

## What arXMCP can do today

The MCP server registers **7 tools** on `tools/list`. Six are fully wired;
one (`cite_neighbors`) is a v1 stub pending the boundary-contract wiring
in a future milestone (the underlying library
[`server/graph_queries.py`](server/graph_queries.py) is shipped and tested).

| Tool | Status | Capability |
|---|---|---|
| `search_papers` | shipped | Dense-only ANN over `embedding_stmt`; level=`theorem`/`section`/`paper`. |
| `get_chunk` | shipped | Direct LanceDB chunk lookup with 256 KB inline cap + `resource_link` fallback. |
| `find_equation` | shipped | Dense-only fallback over `embedding_stmt`; full TED index lands in E10. |
| `get_definitions` | shipped | Per-paper `\newcommand` / `\DeclareMathOperator` / `\def` macro table. |
| `find_lemma_by_name` | shipped | In-memory case-insensitive substring scan over `theorem_name`. |
| `get_paper` | shipped | Chunks-synthesized metadata (chunk_count, sections, chunker_version). |
| `cite_neighbors` | **stub** | Registered; handler returns `{neighbors: [], infrastructure_status: "deferred"}`. Real library at [`server/graph_queries.py`](server/graph_queries.py). |

Beyond the tool surface, the server ships:

- **Streamable HTTP MCP transport** at `/mcp` (loopback bind, MCP 2025-06-18 spec).
- **3-tier retrieval cache** (SQLite exact + FAISS semantic + LRU rerank-set).
- **Per-session retrieval caps** (3 search + 4 chunk calls per `Mcp-Session-Id`).
- **Query router** (regex patterns → 4 agent roles, no LLM planner).
- **Model-selection policy** (Haiku/Sonnet only; no Opus in `server/`).
- **Hybrid retrieval pipeline** (BM25 → dual-ANN+RRF → optional BGE reranker).
- **Citation graph** (Kùzu, OpenAlex + INSPIRE-HEP + intra-paper `\ref{}`).
- **Prompt-cache discipline** (BP1 + BP2 byte-stable across the 4-agent fan-out).

---

## Documentation map

The full table of contents is layered by audience. Click any path to open it.

### For operators (how to install + run)

| | |
|---|---|
| [`docs/install.md`](docs/install.md) | Step-by-step install + Claude Code MCP registration |
| [`Makefile`](Makefile) | `make help` — all CLI entry points |
| [`docs/eval-curation.md`](docs/eval-curation.md) | How to hand-label the 20-query eval fixture (Tier-0/1 gate) |
| [`TIER-GATES.md`](TIER-GATES.md) | What "Tier-0 done" / "Tier-1 done" / etc. mean (machine-checkable) |
| [`docs/retrieval-quality-report.md`](docs/retrieval-quality-report.md) | nDCG@5 + latency report (PRELIMINARY pending fixture) |

### For Claude agents and human implementers

| | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **Start here.** Full context for agents working in this repo. |
| [`.claude/notes/README.md`](.claude/notes/README.md) | Index of the design constitution (10 numbered notes) |
| [`.claude/notes/01-mission-and-context.md`](.claude/notes/01-mission-and-context.md) | Why arXMCP exists; "Lean kernel is the better critic" framing |
| [`.claude/notes/02-architecture-overview.md`](.claude/notes/02-architecture-overview.md) | Top-level system shape |
| [`.claude/notes/03-ingestion-pipeline.md`](.claude/notes/03-ingestion-pipeline.md) | arXiv → LaTeXML → chunker → embedder → LanceDB |
| [`.claude/notes/04-parsing-and-chunking.md`](.claude/notes/04-parsing-and-chunking.md) | Theorem/proof chunk discipline; 512-token BGE-M3 limit |
| [`.claude/notes/05-storage-and-indexing.md`](.claude/notes/05-storage-and-indexing.md) | LanceDB schema; MVCC; Kùzu citation graph |
| [`.claude/notes/06-mcp-server-design.md`](.claude/notes/06-mcp-server-design.md) | MCP 2025-06-18 spec; Streamable HTTP; loopback-only |
| [`.claude/notes/07-multi-agent-caching.md`](.claude/notes/07-multi-agent-caching.md) | BP1/BP2 breakpoints; 3-tier retrieval cache; tool-use ID canonicalization |
| [`.claude/notes/08-security-observability-ops.md`](.claude/notes/08-security-observability-ops.md) | 7-threat model; observability stack; daily ops |
| [`.claude/notes/10-references-and-prior-art.md`](.claude/notes/10-references-and-prior-art.md) | PaperQA2, LeanDojo, DeepSeek-Prover, OpenAlex, INSPIRE |
| [`.claude/roadmap/README.md`](.claude/roadmap/README.md) | Epic-level plans (E01-E14) + ship status |
| [`docs/orchestrator-rules.md`](docs/orchestrator-rules.md) | Tool-use ID canonicalization + per-session caps (E08_S04) |
| [`docs/model-policy.md`](docs/model-policy.md) | `(RouteTag, TurnType) → model` table (E08_S05) |
| [`docs/proof-chain-workflow.md`](docs/proof-chain-workflow.md) | 2-round cross-paper proof-chain pattern (E09_S04) |
| [`server/prompts.md`](server/prompts.md) | Role-prefix constants + BP1/BP2 cache breakpoint placement |

### For contributors (test, gate, ship)

| | |
|---|---|
| [`docs/snippet-contract.md`](docs/snippet-contract.md) | 150-char snippet contract for `search_papers` rows (E06_S04) |
| [`docs/chunker-fixtures.md`](docs/chunker-fixtures.md) | E02_S05 fixture suite + regeneration runbook |
| [`.claude/skills/milestone-pipeline/SKILL.md`](.claude/skills/milestone-pipeline/SKILL.md) | The 4-phase milestone discipline used to land all E01-E09 work |

---

## Repo layout

```
arXMCP/
├── server/         long-running MCP server (FastAPI + Streamable HTTP; owns indices + caches)
├── ingest/         corpus ingestion pipeline (chunker, embedder, BM25, graph ingest)
├── shim/           stateless stdio↔HTTP shim registered in Claude Code's ~/.claude.json
├── tools/          dev utilities (seed fetch, eval-fixture validator)
├── tests/          1312 pytest tests + 4 skipped (requires_model); retrieval-quality eval gate under tests/eval/
├── docker/         multi-stage Dockerfile (non-root, tini, HEALTHCHECK on /readyz)
├── infra/          deployment manifests (docker-compose; placeholder until E14)
├── docs/           public-facing operator + contributor docs
├── .claude/
│   ├── notes/      design constitution (10 numbered notes + HANDOFF + milestones/)
│   ├── roadmap/    14 per-epic plans (E01–E14)
│   └── skills/     milestone-pipeline + other skill definitions
└── var/            gitignored data tree (created by `make bootstrap`)
    └── arxmcp/
        ├── corpus/   raw/, parsed/, chunks/
        ├── index/    lancedb/, kuzu/, bm25/v<N>/
        ├── cache/    ar5iv/, retrieval.db
        └── ops/      parser-failures/
```

---

## Hard constraints

From [`.claude/notes/README.md`](.claude/notes/README.md) — these never change:

1. **Local-first, single-user, single-workstation.** No multi-host orchestration.
2. **Loopback-only bind.** `127.0.0.1:7733`. The MCP server refuses to bind to
   `0.0.0.0` at config-parse time.
3. **MCP 2025-06-18 Streamable HTTP transport.** No SSE; single-shot
   `application/json` responses.
4. **Math fidelity over retrieval recall.** LaTeXML + MathML; never PyPDF as a
   primary parser.

---

## License

MIT. See [`pyproject.toml`](pyproject.toml).

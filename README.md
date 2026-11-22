# arXMCP

[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP spec](https://img.shields.io/badge/MCP-2025--06--18-blueviolet.svg)](https://modelcontextprotocol.io/specification/2025-06-18)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Status](https://img.shields.io/badge/status-pre--release-orange.svg)](CHANGES.md)
[![Release](https://img.shields.io/github/v/release/chris-dare-dev/arXMCP?display_name=tag&sort=semver)](https://github.com/chris-dare-dev/arXMCP/releases)
[![Downloads](https://img.shields.io/github/downloads/chris-dare-dev/arXMCP/total.svg)](https://github.com/chris-dare-dev/arXMCP/releases)
[![Last commit](https://img.shields.io/github/last-commit/chris-dare-dev/arXMCP.svg)](https://github.com/chris-dare-dev/arXMCP/commits)

A local-first [Model Context Protocol (MCP)](https://modelcontextprotocol.io/specification/2025-06-18)
server that exposes a research-mathematics arXiv corpus to multi-agent Claude
pipelines. arXMCP is the substrate a Claude **sketcher → autoformalizer →
tactician → fixer** workflow shares — every sub-agent uses the same MCP
endpoint to fetch grounded context (theorem statements, proofs, lemma
references, citation neighborhoods) from a single, version-pinned corpus.

**Target arXiv categories:** `math.AG`, `math.NT`, `math-ph`, `hep-th`.

## What it does

Run the long-running `arxmcp-server`; register the stateless `arxmcp-shim`
in Claude Code's `~/.claude.json`; sub-agents then call MCP tools over
loopback `127.0.0.1:7733`. The server exposes **eight** tools:

| Tool | Capability |
|---|---|
| `search_papers` | Dense ANN over BGE-M3 statement embeddings; `level` = `theorem` / `section` / `paper`; notebook + `paper_id` filters. |
| `get_chunk` | Direct LanceDB chunk lookup with a 256 KB inline cap + `resource_link` fallback. |
| `find_equation` | MathML → Zhang–Shasha tree-edit-distance fused with dense cosine; LaTeX falls back to dense-only. |
| `get_definitions` | Per-paper `\newcommand` / `\DeclareMathOperator` / `\def` notation table with term lookup. |
| `find_lemma_by_name` | SQLite FTS5 theorem-name index — exact → trigram → fuzzy Jaccard. |
| `get_paper` | Chunks-synthesized per-paper metadata. |
| `cite_neighbors` | Kùzu citation-graph traversal (`cites` / `cited_by` / `depends_on`, depth 1–2). |
| `lean_verify` | Verify a Lean 4 snippet against a managed local kernel (gated by `ARXMCP_ENABLE_LEAN`). |

Under the hood: a 3-tier retrieval cache (SQLite exact + FAISS semantic + LRU
rerank-set), per-session retrieval caps, a regex query router, a Kùzu
citation graph from OpenAlex + INSPIRE-HEP + intra-paper `\ref{}` chains, and
a loopback-only operator console at `/ui/` for notebook management. Corpus
is organized into independently ingested **notebooks**; textbook PDFs ingest
via MinerU + LaTeXML. All transport is MCP 2025-06-18 Streamable HTTP,
loopback bind only.

## Quick start

```bash
# 1. bootstrap (Python ≥3.11): create venv, install deps, create var/ tree
python3 -m venv .venv && source .venv/bin/activate
make bootstrap

# 2. create a notebook and add papers (EMAIL persists the arXiv polite-pool
#    contact so the server never needs ARXMCP_CONTACT_EMAIL)
make init NOTEBOOK=demo EMAIL=you@example.com
make add  NOTEBOOK=demo PAPER=1309.4265

# 3. ingest, then serve it
make ingest ARGS="--paper-ids-file=src/arxmcp/tools/seed-papers.txt --limit=5"
ARXMCP_NOTEBOOK=demo make up        # MCP server on 127.0.0.1:7733

# 4. register the stdio shim: merge this into ~/.claude.json
#    {"mcpServers": {"arxmcp": {"command": "arxmcp-shim",
#                               "args": ["--server", "http://127.0.0.1:7733"]}}}
```

`make help` lists every target. The `Makefile` is bash-only; on Windows run
the server with `python -m arxmcp.server.main` from the activated venv.

## Documentation

Install, usage, API and operations guides are moving to the
[wiki](https://github.com/chris-dare-dev/arXMCP/wiki). Until a page lands
there, its last version is in the [archived tree](https://github.com/chris-dare-dev/arXMCP/tree/433ba41ba8710be74d6f99c627dce7d3b5383fca/docs).

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) ·
Security: [SECURITY.md](SECURITY.md) ·
Changes: [CHANGES.md](CHANGES.md).

## Repo layout

```
arXMCP/
├── server/     long-running MCP server (FastAPI + Streamable HTTP; indices + caches + /ui/ console)
├── ingest/     corpus pipeline (chunker, embedder, BM25, citation-graph ingest)
├── shim/       stateless stdio↔HTTP bridge registered in Claude Code's ~/.claude.json
├── ops/        operability layer (backup, cutover, restore drill, drift watchdog, cron/systemd units)
├── tools/      dev + ingest utilities (seed/notebook fetch, eval gates, ops reports)
├── tests/      pytest suite + retrieval-quality eval harness under tests/eval/
├── deploy/     multi-stage Dockerfile (non-root, tini, HEALTHCHECK on /readyz)
├── deploy/      deployment + observability manifests
├── apps/       desktop shell (Tauri supervisor + PyInstaller packaging)
└── var/        gitignored data tree (created by `make bootstrap`)
```

## Hard constraints

These never change:

1. **Local-first, single-user, single-workstation.** No multi-host orchestration.
2. **Loopback-only bind.** `127.0.0.1:7733`. The server refuses to bind to
   `0.0.0.0` at config-parse time.
3. **MCP 2025-06-18 Streamable HTTP transport.** No SSE; single-shot
   `application/json` responses.
4. **Math fidelity over retrieval recall.** LaTeXML + MathML; never PyPDF as
   a primary parser.

## License

[MIT](LICENSE). © 2026 Chris Dare.

---

Working conventions for contributors and agents: [`CLAUDE.md`](CLAUDE.md).

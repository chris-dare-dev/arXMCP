# arXMCP

<!--
  Badges: the GitHub-dynamic ones (downloads, last-commit, release) render
  once the repo is public and (for downloads/release) once a release is cut.
  The static ones always render. See docs/releasing.md.
-->
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
a loopback-only [operator console](docs/usage.md#the-operator-console) at
`/ui/` for notebook management. Corpus is organized into independently
ingested **notebooks**; textbook PDFs ingest via MinerU + LaTeXML. All
transport is MCP 2025-06-18 Streamable HTTP, loopback bind only. See the
[architecture chapter](docs/architecture.md).

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
make ingest ARGS="--paper-ids-file=tools/seed-papers.txt --limit=5"
ARXMCP_NOTEBOOK=demo make up        # MCP server on 127.0.0.1:7733

# 4. register the stdio shim in Claude Code's ~/.claude.json (see docs/install.md)
```

`make help` lists every target. Full setup is in the
[install guide](docs/install.md); end-to-end tasks are in the
[usage guide](docs/usage.md).

> **Windows:** the `Makefile` is bash-only, but the server + `/ui/` console run
> on native Windows via make-free PowerShell commands — see
> [Running on Windows](docs/install.md#running-on-windows-no-make).

## Documentation

| Guide | For |
|---|---|
| [Install](docs/install.md) | Setup + Claude Code registration. |
| [Usage](docs/usage.md) | Notebooks, ingest, search, the operator console. |
| [MCP tool API](docs/api.md) | The exact tool surface agents call. |
| [Architecture](docs/architecture.md) | How retrieval, caching, and the graph fit together. |
| [Operations](docs/ops/README.md) | Corpus lifecycle, failures, daily cadence. |
| [Observability](docs/observability/README.md) | Metrics, tracing, Phoenix, Grafana. |
| [Evaluation](docs/evaluation.md) | Retrieval-quality + parser-fidelity gates. |
| [Support](docs/support.md) | Troubleshooting and how to get help. |

**Operations runbooks** — the [operations index](docs/ops/README.md) is the
entry point. Common runbooks:
[bulk ingest](docs/ops/bulk-ingest-runbook.md) ·
[delta loop](docs/ops/delta-loop.md) ·
[re-embed](docs/ops/re-embed-runbook.md) ·
[drift watchdog](docs/ops/drift-watchdog.md) ·
[LaTeXML drift](docs/ops/latexml-drift-runbook.md) ·
[cutover](docs/ops/cutover-runbook.md) ·
[backup & restore](docs/ops/backup-restore.md).

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) ·
Security: [SECURITY.md](SECURITY.md) ·
Changes: [CHANGES.md](CHANGES.md) ·
Releases: [docs/releasing.md](docs/releasing.md).

## Repo layout

```
arXMCP/
├── server/     long-running MCP server (FastAPI + Streamable HTTP; indices + caches + /ui/ console)
├── ingest/     corpus pipeline (chunker, embedder, BM25, citation-graph ingest)
├── shim/       stateless stdio↔HTTP bridge registered in Claude Code's ~/.claude.json
├── ops/        operability layer (backup, cutover, restore drill, drift watchdog, cron/systemd units)
├── tools/      dev + ingest utilities (seed/notebook fetch, eval gates, ops reports)
├── tests/      pytest suite + retrieval-quality eval harness under tests/eval/
├── docker/     multi-stage Dockerfile (non-root, tini, HEALTHCHECK on /readyz)
├── infra/      deployment + observability manifests
├── docs/       user/operator-facing documentation (this README's chapters)
├── var/        gitignored data tree (created by `make bootstrap`)
└── .claude/    agent-internal: design notes, roadmap, milestones, engineering refs
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

For agent context, design notes, and working conventions, see
[`CLAUDE.md`](CLAUDE.md) and the [`.claude/`](.claude/) directory.

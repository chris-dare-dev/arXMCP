# arXMCP

A local-first, Docker-deployable [Model Context Protocol](https://modelcontextprotocol.io/specification/2025-06-18) server that exposes a research-mathematics arXiv corpus to multi-agent Claude pipelines.

The intended consumer is a multi-agent math-proof workflow (sketcher → autoformalizer → tactician → fixer), each a Claude sub-agent, all sharing one corpus through this server.

## Target arXiv categories

- `math.AG` — algebraic geometry
- `math.NT` — number theory
- `math-ph` — mathematical physics
- `hep-th` — high-energy physics, theory

## Documentation

The design constitution lives in [`.claude/notes/`](.claude/notes/README.md). Every implementation decision should trace back to one of those notes — start there before reading code.

The roadmap is at [`ROADMAP.md`](ROADMAP.md) (15 epics, Tier 0 → Tier 7) with per-epic detail under [`.claude/roadmap/`](.claude/roadmap/).

## Repo layout

| Path | Purpose |
|---|---|
| [`server/`](server/) | Streamable HTTP MCP server (long-running, owns indices + caches) |
| [`ingest/`](ingest/) | Ingestion service (separate process, single-writer) |
| [`shim/`](shim/) | stdio → HTTP proxy registered in `~/.claude.json` |
| [`infra/`](infra/) | Docker Compose, container definitions |
| [`tools/`](tools/) | One-off developer scripts (seed corpus fetch, etc.) |
| [`tests/`](tests/) | Test suite (`pytest`) |
| [`.claude/notes/`](.claude/notes/) | Design constitution (11 files) |
| [`.claude/roadmap/`](.claude/roadmap/) | Per-epic sub-issue specs |

## Hard constraints

From [`.claude/notes/README.md`](.claude/notes/README.md):

- **No AWS S3** in the ingestion path (Backblaze B2 etc. for backups is fine)
- **No forking** of existing arxiv-MCP repos (steal ideas, not code)
- **Local-first** — must run in Docker on a single workstation
- **Math fidelity over coverage** — 50K papers correct beats 500K with PyPDF mangling

## Tier exit gates

Promotion between tiers is gated by **machine-checkable** conditions, not subjective demos. The single authoritative source is [`TIER-GATES.md`](TIER-GATES.md). The active gate today is Tier-0 → Tier-1: `make eval` must report `1 passed` (not `1 skipped`) for ANN-only retrieval at nDCG@5 ≥ 0.70.

## Quick start

```sh
make help           # list available targets
make bootstrap      # set up the dev environment
make test           # run ruff + pytest
make eval           # run the Tier-0 retrieval-quality gate (TIER-GATES.md)
```

The corpus directory `var/arxmcp/` is gitignored and created at bootstrap time.

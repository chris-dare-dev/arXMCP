# arXMCP

A local-first [Model Context Protocol (MCP)](https://modelcontextprotocol.io/specification/2025-06-18)
server that exposes a research-mathematics arXiv corpus to multi-agent Claude
pipelines. arXMCP is the substrate a Claude **sketcher → autoformalizer →
tactician → fixer** workflow shares — every sub-agent uses the same MCP
endpoint to fetch grounded context (theorem statements, proofs, lemma
references, citation neighborhoods) from a single, version-pinned corpus.

**Target arXiv categories:** `math.AG`, `math.NT`, `math-ph`, `hep-th`.

## What it does

Run the long-running `arxmcp-server` process; register the stateless
`arxmcp-shim` in Claude Code's `~/.claude.json`; sub-agents then call MCP
tools over loopback `127.0.0.1:7733`. The server exposes seven tools on
`tools/list`:

| Tool | Capability |
|---|---|
| `search_papers` | Dense ANN over BGE-M3 `embedding_stmt`; level=`theorem` / `section` / `paper`. |
| `get_chunk` | Direct LanceDB chunk lookup with a 256 KB inline cap + `resource_link` fallback. |
| `find_equation` | Dense-only fallback over `embedding_stmt` (full equation TED index is on the roadmap). |
| `get_definitions` | Per-paper `\newcommand` / `\DeclareMathOperator` / `\def` macro table. |
| `find_lemma_by_name` | Case-insensitive substring scan over `theorem_name`. |
| `get_paper` | Chunks-synthesized per-paper metadata. |
| `cite_neighbors` | Citation-graph traversal (`cites` / `cited_by` / `depends_on`, depth 1-2). |

Under the hood the server runs a 3-tier retrieval cache (SQLite exact + FAISS
semantic + LRU rerank-set), enforces per-session retrieval caps, routes
queries to one of four agent roles via a regex classifier, and ships a Kùzu
citation graph populated from OpenAlex + INSPIRE-HEP + intra-paper
`\ref{}` chains. All transport is MCP 2025-06-18 Streamable HTTP — single-
shot `application/json`, loopback bind only.

## How to use it

Full operator setup: [`docs/install.md`](docs/install.md).

Quick version:

```bash
# 1. bootstrap (Python ≥3.11, create venv, install deps, create var/ tree)
python3 -m venv .venv && source .venv/bin/activate
make bootstrap

# 2. fetch the 50-paper math.AG seed corpus (one-time)
export ARXMCP_CONTACT_EMAIL=you@example.com   # arXiv TOS §3 polite pool
python tools/fetch_seed.py                    # idempotent

# 3. start the MCP server on 127.0.0.1:7733
make up

# 4. register the stdio shim in Claude Code's ~/.claude.json
#    (see docs/install.md for the JSON snippet)
```

Other entry points: `make help`, `make test` (ruff + pytest), `make eval`
(retrieval-quality gate).

## Operations

Operator runbooks live under [`docs/ops/`](docs/ops/). The
[**runbook index**](docs/ops/README.md) is the single entry-point
for failure and maintenance scenarios; the table below lists
the underlying files directly.

| Runbook | Epic | When to use |
|---|---|---|
| [`latexml-drift-runbook.md`](docs/ops/latexml-drift-runbook.md) | E10_S04 | LaTeXML version drift detected (daily cron alert) |
| [`bulk-ingest-runbook.md`](docs/ops/bulk-ingest-runbook.md) | E11_S01 | Initial bulk ingest of the Academic Torrents corpus |
| [`delta-loop.md`](docs/ops/delta-loop.md) | E11_S02 | Nightly OAI-PMH delta harvest |
| [`re-embed-runbook.md`](docs/ops/re-embed-runbook.md) | E11_S03 | Partial re-embed after a chunker or embedder bump |
| [`drift-watchdog.md`](docs/ops/drift-watchdog.md) | E11_S04 | nDCG@5 regression watchdog after staging updates |
| [`cutover-runbook.md`](docs/ops/cutover-runbook.md) | E11_S05 | 200K staging → active cutover activation + rollback |
| [`backup-restore.md`](docs/ops/backup-restore.md) | E11_S05 | restic backup + restore drill |
| [`daily-ops-cadence.md`](docs/ops/daily-ops-cadence.md) | E14_S04 | Daily/weekly/quarterly cron + systemd schedule |
| [`parser-failure-review.md`](docs/ops/parser-failure-review.md) | E14_S04 | Weekly parser-failures triage workflow |
| [`failure-modes.md`](docs/ops/failure-modes.md) | E14_S05 | Detection + recovery for the 9 documented failure modes |
| [`notebook-modes.md`](docs/ops/notebook-modes.md) | pv-m3 | Multi-notebook deployment topology (per-daemon vs per-call filter) |

### Importing the dashboard

A provisioned Grafana dashboard with cache hit-ratio and latency panels
lives at [`infra/observability/grafana-dashboard.json`](infra/observability/grafana-dashboard.json).
Companion provisioning config:
[`infra/observability/grafana-provisioning.yml`](infra/observability/grafana-provisioning.yml).

**Option A — manual UI import** (one-off, simplest):

1. Open Grafana → **Dashboards → New → Import**.
2. Upload `infra/observability/grafana-dashboard.json` (or paste its
   contents) and select your Prometheus datasource.
3. The dashboard appears as `arXMCP — Cache and Latency`.

**Option B — provisioned auto-load** (durable across Grafana restarts):

Mount the two provisioning fragments + the dashboard JSON into Grafana's
provisioning tree, then start Grafana. The fragments are bundled in one
YAML for documentation; physically split them into Grafana's two
expected paths:

```bash
# Split the provisioning YAML into Grafana's two expected files.
# (The bundled YAML at infra/observability/grafana-provisioning.yml
#  has two top-level blocks: 'datasources' and 'providers'. Split on
#  the comment markers in that file.)

# On the host running Grafana, mount:
#   infra/observability/grafana-provisioning.yml (datasources block)
#     → /etc/grafana/provisioning/datasources/arxmcp.yml
#   infra/observability/grafana-provisioning.yml (providers block)
#     → /etc/grafana/provisioning/dashboards/arxmcp.yml
#   infra/observability/grafana-dashboard.json
#     → /etc/grafana/provisioning/dashboards/arxmcp/arxmcp-cache-latency.json

# Then `docker restart grafana` (or equivalent) — dashboard auto-loads.
```

Tested against Grafana 10.x and 11.x (`schemaVersion: 39`). Requires
a Prometheus datasource scraping the arXMCP `/metrics` endpoint.

## Repo layout

```
arXMCP/
├── server/         long-running MCP server (FastAPI + Streamable HTTP; owns indices + caches)
├── ingest/         corpus ingestion pipeline (chunker, embedder, BM25, citation-graph ingest)
├── shim/           stateless stdio↔HTTP bridge registered in Claude Code's ~/.claude.json
├── tools/          dev utilities (seed fetch, eval-fixture validator)
├── tests/          pytest suite + retrieval-quality eval harness under tests/eval/
├── docker/         multi-stage Dockerfile (non-root user, tini, HEALTHCHECK on /readyz)
├── infra/          deployment manifests
├── docs/           operator-facing documentation (install + setup)
├── var/            gitignored data tree (created by `make bootstrap`)
└── .claude/        agent-internal: design notes, roadmap, milestones, internal docs
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

MIT. See [`pyproject.toml`](pyproject.toml).

---

For agent context, design notes, working conventions, and the milestone
history, see [`CLAUDE.md`](CLAUDE.md) and the `.claude/` directory.
Changes are tracked in [`CHANGES.md`](CHANGES.md). Security reporting:
[`SECURITY.md`](SECURITY.md). Ownership: [`OWNERS.md`](OWNERS.md).

# arXMCP documentation

User- and operator-facing documentation for arXMCP. Start at the
[project README](../README.md) for the overview; this directory holds the
chapter-length guides linked from it.

> Agent-internal material — the design constitution, roadmap, milestone
> history, and per-feature engineering references — lives under
> [`.claude/`](../.claude/), not here. This directory is for people running
> and using arXMCP.

## Chapters

| Chapter | Read it when you want to… |
|---|---|
| [Install](install.md) | Set arXMCP up on a workstation and register the shim with Claude Code. |
| [Usage guide](usage.md) | Create notebooks, ingest papers, run searches, and drive the operator console. |
| [MCP tool API](api.md) | Look up the exact tool surface agents call — arguments, returns, error envelopes. |
| [Architecture](architecture.md) | Understand how retrieval, caching, and the citation graph fit together. |
| [Operations](ops/README.md) | Run the corpus lifecycle, handle failures, and follow the daily/weekly cadence. |
| [Observability](observability/README.md) | Wire up `/metrics`, OpenTelemetry tracing, Phoenix, Grafana, and Langfuse. |
| [Evaluation](evaluation.md) | Run the retrieval-quality and parser-fidelity (CDM) gates. |
| [Support](support.md) | Troubleshoot, find answers, and report a problem the right way. |
| [Releasing](releasing.md) | Cut a versioned release (maintainer workflow). |

## Contributing & policy

- [Contributing guide](../CONTRIBUTING.md) — how changes are made in this repo.
- [Security policy](../SECURITY.md) — reporting a vulnerability.
- [Changelog](../CHANGES.md) — what shipped, by release and epic.
- [License](../LICENSE) — MIT.

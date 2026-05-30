# capability-scout-multi-agent — lessons

<!-- Append one generalizable lesson per line as scout runs surface them.
     Format: `YYYY-MM-DD [<scout-id>] <lesson>`. Append only; do not delete. -->
2026-05-28 [2026q2-notebook-ux-storage-ops] MCP 2025-06-18 resources/subscriptions/logging are spec-normative and Claude Code v2.1.121+ supports them, but most arXMCP-style servers do not advertise these capabilities in their `initialize` response — the highest-leverage capability gap is not adding new tools but advertising existing spec features (resources, logging, listChanged) at connect time.
2026-05-28 [2026q2-notebook-ux-storage-ops] Agent-facing corpus management (add doc, watch ingest, retrieve) has no published research framework pattern as of early 2026 — the Agentic RAG literature covers retrieval workflows but not corpus governance; arXMCP's IngestTaskTracker + DB-tracked run state is ahead of the published SOTA on this sub-problem.
2026-05-28 [2026q2-notebook-ux-storage-ops] Docker Compose with `depends_on: condition: service_healthy` is the 2025 ecosystem standard for local MCP server packaging; the bare-Dockerfile-without-compose pattern is the most visible operator UX gap for local-first MCP servers.

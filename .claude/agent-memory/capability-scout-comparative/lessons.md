# capability-scout-comparative — lessons

<!-- Append one generalizable lesson per line as scout runs surface them.
     Format: `YYYY-MM-DD [<scout-id>] <lesson>`. Append only; do not delete. -->

2026-05-28 [2026q2-notebook-ux-storage-ops] For operability/UX-scope scouts, Paperless-ngx api.md (github raw) is the highest-signal source for async ingest-task patterns (task_id poll shape); docs.paperless-ngx.com returns 403 — always use the GitHub raw path. LM Studio docs.lmstudio.ai/cli/serve/server-status is the cleanest "is it running" JSON shape reference. Ollama has no dedicated health endpoint — community uses /api/tags as proxy (confirmed by GitHub issue #1378). Docker healthcheck patterns: last9.io/blog/docker-compose-health-checks is high-signal and directly applicable. For local-first storage scouts, litestream.io/reference/config is the authoritative source for file-replica config (not the README). MinIO docs redirect to enterprise AIStor (AGPL/proprietary) — community open-source MinIO is at hub.docker.com/r/minio/minio, not min.io docs.

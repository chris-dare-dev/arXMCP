---
project: arxmcp
type: doc
tags:
- project/arxmcp
- type/doc
- authorship/agent-generated
authorship: agent-generated
---

# Server crash recovery

The arXMCP daemon exited unexpectedly. Bring it back.

> Indexed from [`docs/ops/README.md`](README.md) #1.
> Related: [`failure-modes.md`](failure-modes.md) for in-process
> failure modes that DON'T crash the daemon (degraded mode, slow
> reranker, OOM-during-large-result).

---

## Symptoms

- `curl http://127.0.0.1:7733/healthz` connection refused.
- systemd `arxmcp.service` shows `failed` or `inactive (dead)`.
- Last log lines in `journalctl -u arxmcp` show one of:
  - `SIGSEGV` (segmentation fault — usually faiss/torch native lib)
  - `MemoryError` / OOM-killer entry in `dmesg`
  - Uncaught Python exception with traceback
  - `RuntimeError: Server already running` after a previous crash
    left a stale PID file.

## Detection

- Prometheus alert `ArXMCPDown` (defined in
  `infra/prometheus/alerts.yml`) fires after the `/metrics` scrape
  fails twice in a row (~60s).
- Phoenix UI shows no new spans for > 60s.
- The orchestrator (in the caller's codebase) gets connection
  refused on `tools/call`.

## Steps

1. **Capture forensics before restarting.** Even on an OOM or
   SIGSEGV, the stderr tail in `journalctl -u arxmcp --since '5
   minutes ago'` is the only diagnostic you'll have.

   ```bash
   journalctl -u arxmcp --since '5 minutes ago' --no-pager \
     > /tmp/arxmcp-crash-$(date +%s).log
   ```

2. **Check disk first.** If the crash was OOM-related, check disk
   too (a full disk can manifest as OOM via swap exhaustion):

   ```bash
   df -h /var/arxmcp
   free -h
   ```

   If disk-full, see [disk-full handling](failure-modes.md#disk-full).

3. **Clear any stale PID / lock files.** If the previous instance
   left a PID file (defensive — current code uses systemd's own
   liveness tracking), remove it:

   ```bash
   rm -f /var/arxmcp/run/arxmcp.pid
   ```

4. **Restart the daemon.**

   ```bash
   sudo systemctl restart arxmcp
   ```

5. **Watch the startup logs** for the LanceDB integrity check and
   model warm-up:

   ```bash
   journalctl -u arxmcp -f
   ```

   Expected lines (in order):
   - `corpus_version=<N> loaded` (LanceDB MVCC pin)
   - `BGE-M3 warm pass complete`
   - `BGE-reranker warm pass complete`
   - `lifespan ready: /readyz now returns 200`

   If LanceDB manifest fails to load, see
   [`failure-modes.md` #2 — LanceDB corruption](failure-modes.md#lancedb-corruption).
   If readiness never goes green, the daemon falls back to degraded
   mode automatically; see
   [`failure-modes.md` #1 — Hosted-embedder outage](failure-modes.md#hosted-embedder-outage).

## Verification

```bash
# Health endpoints
curl -fsS http://127.0.0.1:7733/healthz   # → 200 always once bound
curl -fsS http://127.0.0.1:7733/readyz    # → 200 once warm

# /metrics is exposed
curl -fsS http://127.0.0.1:7733/metrics | head -5

# tools/list round-trip (uses the stdio shim against the live daemon)
make smoke   # if defined; else run a single tools/call manually
```

If `/readyz` is 200 and `tools/list` returns the 7 frozen tools, the
service is recovered. Post-mortem: capture the forensic log from
step 1 in `var/arxmcp/ops/post-mortems/` and add an entry to
`.claude/notes/deferred-work-tracker.md` if the crash class is new.

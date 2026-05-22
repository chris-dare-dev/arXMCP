# Notebook deployment topology — per-daemon vs per-call filter

This runbook covers the three operational modes for serving multiple
research notebooks (curated arXiv paper sets) from arXMCP, plus the
session-cap discipline + fresh-session-per-query pattern that the
downstream `/proof-verify` pipeline relies on. Read this before
deploying a multi-notebook workflow on top of arXMCP.

The corpus / index conventions referenced here are defined in
[`.claude/notes/05-storage-and-indexing.md`](../../.claude/notes/05-storage-and-indexing.md);
the session-cap mechanics live in
[`server/session.py`](../../server/session.py); the `paper_id` filter
honored by `search_papers` landed in `proof-verify-handler-wiring-m1`
and its `filters_applied` echo in `proof-verify-handler-wiring-m2`.

---

## Summary table

| Mode | Daemons | Corpus isolation | Session-cap behavior | RAM cost | Best for |
|---|---|---|---|---|---|
| 1 — Per-daemon | N (one per notebook) | Hard (separate LanceDB dir) | 3 calls per notebook session | ~3.5 GB × N | ≤ 10 notebooks; strong isolation; today's working pattern |
| 2 — Per-call filter | 1 (shared) | Soft (`paper_id` predicate) | 3 calls shared across all notebooks in one session | ~3.5 GB total | Many notebooks; small per-pipeline call budget; new in m1/m2 |
| 3 — Hybrid | 1 + N — mix | Per-notebook for hot sets, filter for the long tail | Hybrid | Between 1 and 2 | Production deployment with one "hot" notebook and many cold |

The 22-paper math.AG working example used during the 2026-05-21
pivot lives at `var/arxmcp/index/lancedb-staging` (see
[`.claude/notes/proof-verify-pivot/synthesis.md`](../../.claude/notes/proof-verify-pivot/synthesis.md)).
The canonical production single-corpus path is
`var/arxmcp/index/lancedb`; per-notebook indices (Variant 1 layout
from `proof-verify-handler-wiring-m6`) live at
`var/arxmcp/notebooks/<slug>/lancedb/`.

---

## Mode 1 — Per-daemon isolation

**What.** Run one arXMCP daemon per notebook, with each daemon
pointed at a notebook-specific LanceDB directory via
`ARXMCP_LANCEDB_PATH`. Each daemon binds a unique port via
`ARXMCP_BIND_PORT`. The downstream consumer registers each daemon
as a separate MCP server in `~/.claude.json`.

**Why.** Hard isolation — a misconfigured query for notebook A
cannot leak into notebook B's index. The 3-call session cap is
per-daemon, so each notebook conversation gets its own budget. This
is the pattern used to unblock the 2026-05-20 spike and is what's
running today.

**Trade-off.** Each daemon holds ~3.5 GB resident (BGE-M3 + LanceDB
+ optional BGE reranker). 10 daemons = ~35 GB. On commodity
workstation hardware this is borderline at 10 notebooks, painful at
20+. Use Mode 2 once the per-notebook count exceeds ~10.

### Launch

```bash
# Notebook A — bridgeland-stability, port 7733 (the default).
# Record the PID so `restart after ingest` can find it later:
# env-var assignments don't appear in argv, so `pkill -f` matching
# on ARXMCP_LANCEDB_PATH would silently match zero processes.
export ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb
export ARXMCP_BIND_PORT=7733
export ARXMCP_CONTACT_EMAIL=you@example.com
mkdir -p var/arxmcp/notebooks/bridgeland-stability/ops
nohup uv run python -m server.main \
  &> var/arxmcp/notebooks/bridgeland-stability/ops/daemon.log &
echo $! > var/arxmcp/notebooks/bridgeland-stability/ops/daemon.pid

# Notebook B — shimura-varieties, port 7734
ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/shimura-varieties/lancedb \
ARXMCP_BIND_PORT=7734 \
ARXMCP_CONTACT_EMAIL=you@example.com \
  nohup uv run python -m server.main \
    &> var/arxmcp/notebooks/shimura-varieties/ops/daemon.log &
echo $! > var/arxmcp/notebooks/shimura-varieties/ops/daemon.pid
```

The bind-host validator
[`reject_non_loopback_bind`](../../server/config.py) at
`server/config.py:294` rejects any non-loopback bind (see
[`.claude/notes/08-security-observability-ops.md`](../../.claude/notes/08-security-observability-ops.md)
§Threat 7); both daemons listen on `127.0.0.1` only.

### Sanity check (do this every time you launch a new daemon)

The most common deployment mistake is a typo in `ARXMCP_LANCEDB_PATH`
that points the daemon at the wrong directory — `/readyz` returns
200, `tools/list` works, but every retrieval is from the wrong
corpus. Catch this immediately:

```bash
# Verify the daemon serves the expected notebook
curl -s -X POST -H 'Content-Type: application/json' \
  -H 'Accept: application/json,text/event-stream' \
  http://127.0.0.1:7733/mcp/ \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"search_papers",
        "arguments":{"query":"<a known title>","k":1}}}' \
  | jq -r '.result.structuredContent.results[0].paper_id'
```

The returned `paper_id` must be one of the IDs in the notebook's
`papers.txt`. If not, the `ARXMCP_LANCEDB_PATH` is wrong — stop the
daemon and re-launch with the correct path.

### Restart after ingest

The daemon caches `corpus_version` at process start and keys its
Tier-1 retrieval cache on it (see
[`.claude/notes/07-multi-agent-caching.md`](../../.claude/notes/07-multi-agent-caching.md)).
After any `tools/notebook_ingest.py <slug>` run that adds papers,
**restart the daemon**:

```bash
# Stop the daemon for the affected notebook using the PID file
# written by the launch recipe above. DO NOT use `pkill -f
# ARXMCP_LANCEDB_PATH=...` — env-var assignments aren't in argv
# and the match silently returns zero processes (m3 rect F1).
PID_FILE=var/arxmcp/notebooks/bridgeland-stability/ops/daemon.pid
if [ -f "$PID_FILE" ]; then
  kill -TERM "$(cat "$PID_FILE")" && rm -f "$PID_FILE"
fi

# Verify the daemon is actually gone before re-launching:
ps -p "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null \
  && echo "WARNING: daemon still running" \
  || echo "daemon stopped"

# Re-launch with the same env vars (and a new daemon.pid).
```

v1 has no hot-reload — the in-memory `corpus_version` is set once
at startup. Running `notebook_ingest.py` against a path a live
daemon is serving is **unsafe** (LanceDB write contention); always
stop the daemon first.

---

## Mode 2 — Per-call `paper_id` filter

**What.** Run one daemon at the default path. Each `search_papers`
call passes `filters={"paper_id": [...]}` listing the notebook's
paper IDs. The handler honors the filter via
`LanceDB.search(...).where("paper_id IN (...)", prefilter=True)`
(see [`server/handlers/search.py:463-468`](../../server/handlers/search.py),
the `with span_ann(k=k):` block enclosing the `.search(...).where(...)`
chain) and echoes the canonical filter shape back as `filters_applied`
(see [`_inject_filters_applied` at
`server/handlers/search.py:195-241`](../../server/handlers/search.py)
and the schema at
[`server/schemas/search_papers_result.json`](../../server/schemas/search_papers_result.json)).

**Why.** One warm process. The Tier-1/Tier-2 retrieval cache is
shared across notebooks, which speeds up cross-notebook queries.
Memory cost stays at ~3.5 GB regardless of notebook count. Adding
a new notebook is one-line config in the calling pipeline.

**Trade-off.** Soft isolation only — a buggy caller could pass a
filter that includes papers from another notebook. The 3-call
session cap is shared across ALL notebooks in one session, so a
pipeline that wants to query 4 notebooks in one conversation will
exhaust the cap on the 4th. See "Session cap" below.

### Call shape

```jsonc
// JSON-RPC over Streamable HTTP at POST http://127.0.0.1:7733/mcp/
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_papers",
    "arguments": {
      "query": "Bridgeland stability conditions on K3 surfaces",
      "k": 5,
      "filters": {
        "paper_id": ["2604.26204", "0712.1083", "0705.3794"]
      }
    }
  }
}
```

Response structure (relevant fields only):

```jsonc
{
  "structuredContent": {
    "results": [ /* up to k rows, all from the supplied paper_id set */ ],
    "filters_applied": { "paper_id": ["0705.3794", "0712.1083", "2604.26204"] },
    "retrieval_mode": "dense_only",
    "...": "..."
  }
}
```

The `filters_applied` echo is the **canonical** form of the honored
filter: sorted, deduped, list-coerced. It is **absent** (not null)
when no filter was passed — preserving byte-equivalence for the
unfiltered hot path. Use it to verify scoping at the consumer
without re-parsing `filter_warnings`.

### Per-call budget

| Bound | Value | Site |
|---|---|---|
| `MAX_PAPER_ID_FILTER_ITEMS` | 100 IDs | [`server/handlers/search.py:108`](../../server/handlers/search.py) |
| `DEFAULT_RESULT_BYTE_CAP` | 256 KB | [`server/config.py:58`](../../server/config.py) |
| `MAX_FILTER_KEY_LEN` | 64 chars per key | [`server/handlers/search.py`](../../server/handlers/search.py) (m1 rect F2) |

The 100-ID hard cap is enforced by the m1 validator and is
exercised by the test suite at
[`tests/test_search_filter.py::TestRectificationGuards`](../../tests/test_search_filter.py).
At ~12 bytes per arXiv ID, 100 IDs is ~1.2 KB — comfortably under
the 256 KB envelope cap. **Deduplicate the list client-side** before
passing; the canonicalizer dedups internally (m2 rect F5), but
sending duplicates wastes envelope bytes.

A list of >100 IDs is rejected with a structured error in
`result.isError=true`. There is no silent truncation.

### Unsupported filter keys

`filters` keys other than `paper_id` are accepted but **ignored**
and surfaced in `filter_warnings`. Today only `paper_id` is honored
(`SUPPORTED_FILTER_KEYS = frozenset({"paper_id"})` at
[`server/handlers/search.py:192`](../../server/handlers/search.py)).
Keys like `categories` or `year_min` are reserved for a future
milestone.

---

## Mode 3 — Hybrid

Run one Mode-1 daemon for the hottest notebook (the one your
pipeline hits most) plus a Mode-2 daemon serving the long tail
of less-frequently-queried notebooks via per-call `paper_id`
filters. The hot daemon gets dedicated cap and dedicated cache;
the shared daemon trades isolation for memory.

This is the recommended deployment shape for >10 notebooks where
one or two are dominant.

---

## Session cap and the fresh-session-per-query pattern

The MCP server enforces a per-session retrieval cap to protect
against runaway pipelines. The cap is **defensive, not security**
(see [`server/session.py`](../../server/session.py) docstring): an
adversary can simply open more sessions. The cap exists to
backstop bugs in the calling pipeline.

| Constant | Value | Site |
|---|---|---|
| `MAX_SEARCH_PAPERS_CALLS` | 3 | [`server/session.py:54`](../../server/session.py) |
| `MAX_GET_CHUNK_CALLS` | 4 | [`server/session.py`](../../server/session.py) |

When the 4th `search_papers` call arrives in one session, the
server returns a structured error with code `RETRIEVAL_CAP_REACHED`
and a hint to "proceed with chunks already retrieved or open a new
session."

### Fresh-session-per-query is spec-normative

The MCP spec at
[modelcontextprotocol.io/specification/2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18)
defines the session lifecycle:

> When a client receives HTTP 404 in response to a request
> containing an `Mcp-Session-Id`, it MUST start a new session by
> sending a new `InitializeRequest` without a session ID attached.

> Clients that no longer need a particular session SHOULD send an
> HTTP DELETE to the MCP endpoint with the `Mcp-Session-Id` header,
> to explicitly terminate the session.

Starting a fresh MCP session — sending a new `InitializeRequest`
without a session ID — is the **normative** way to reset the cap.
In Claude Code's MCP harness, this happens automatically when the
user starts a new conversation. The daemon does NOT need to be
restarted; the per-session counter is reset on the new session.

For pipelines that ground each claim with a separate retrieval
(`/proof-verify`'s pattern), the recommended discipline is:

- One MCP session per claim being verified.
- That session uses 1 of 3 allowed `search_papers` calls plus up
  to 4 `get_chunk` calls for follow-up routing.
- Next claim opens a new session.

### Session rotation does NOT invalidate the prompt cache

A common worry: "won't starting a new session per claim destroy
the prompt cache?" No. The Anthropic prompt cache is **org-scoped,
not session-scoped** (see
[`.claude/notes/07-multi-agent-caching.md`](../../.claude/notes/07-multi-agent-caching.md)).
The BP1 breakpoint covers the system prompt + tool definitions,
which are identical across sessions. The 5-minute default TTL (or
1 hour with the extended-cache-ttl beta header) is the only
constraint. As long as queries land within the TTL, the BP1 cache
is hit regardless of how many sessions you open.

---

## Schema stability commitment

The `search_papers` tool descriptor (name, input schema, result
envelope shape) is byte-stable and pinned by
[`tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256`](../../tests/test_server_tool_schema.py).
The paired version
`tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
must move in lockstep with `server.tools.TOOL_SCHEMA_VERSION` (also
re-pinned via `pytest --update-tool-schema-hash`).

The constraint is documented at
[`.claude/notes/07-multi-agent-caching.md`](../../.claude/notes/07-multi-agent-caching.md)
Property 1:

> Tool definitions are byte-stable. Pin tool JSON schemas. Sort
> properties alphabetically at serialization time. Freeze
> descriptions as constants in source. A casual edit to a tool
> description blows every sub-agent's cache. … bump the hash
> deliberately when intentionally changing schema; treat as an
> API version bump.

**For the consumer:** the `filters` argument and the
`filters_applied` response field are v1-stable. They will not
change shape without a `TOOL_SCHEMA_VERSION` bump (visible in
both the test pin and `_meta.tool_schema_version` on `tools/list`
responses). The orchestrator on the consumer side MUST strip
`_meta` from the live `tools/list` response before submitting to
the Anthropic Messages API `tools=[...]` kwarg; otherwise the
schema-version bump would invalidate the BP1 cache on every
upgrade. See the contract comment at
[`server/tools.py::register_all`](../../server/tools.py) (m2
rect F6) for the canonical projection.

---

## Failure modes and recovery

### FM1 — `ARXMCP_LANCEDB_PATH` typo serves wrong corpus

**Trigger.** Operator launches a Mode-1 daemon with a typo or
stale path in `ARXMCP_LANCEDB_PATH`. The path resolves (LanceDB
auto-creates an empty directory if the parent exists) but points
at the wrong corpus.

**Symptom.** `/readyz` is 200, `tools/list` works, every
`search_papers` result is from the wrong paper set (or empty).
No error is raised — silent until a human inspects results.

**Recovery.** Always run the sanity-check query from Mode 1's
"Launch" subsection above immediately after starting a daemon.
This was the EXACT bug that triggered the 2026-05-20 corpus-rebuild
investigation.

### FM2 — `paper_id` list exceeds the 100 cap

**Trigger.** Mode-2 caller passes >100 IDs (or accidentally
duplicates a large list).

**Symptom.** Structured error with `result.isError=true` and a
message naming the cap. The agent sees `FILTER_VALIDATION_ERROR`.

**Recovery.** Deduplicate the list client-side; split the notebook
across multiple calls if it has >100 papers (or fall back to
Mode 1 for that notebook).

### FM3 — Two daemons against the same LanceDB directory

**Trigger.** Two `python -m server.main` invocations both set
`ARXMCP_LANCEDB_PATH` to the same path.

**Symptom.** Two **read-only** daemons are safe (LanceDB MVCC).
But if either is also writing (e.g. `notebook_ingest.py` runs
against the path while a daemon serves it), MVCC permits the
write but the serving daemon's `corpus_version` and Tier-1 cache
remain pinned to the pre-write snapshot. Queries silently return
stale results.

**Recovery.** Stop the serving daemon before any ingest. Run
ingest. Re-launch the daemon. Two read-only daemons against one
path can co-exist (e.g. for blue-green hand-off during cutover —
see [`docs/ops/cutover-runbook.md`](cutover-runbook.md)).

### FM4 — Session cap fires mid-pipeline

**Trigger.** A pipeline runs more than 3 `search_papers` calls in
one MCP session. The 4th returns `RETRIEVAL_CAP_REACHED`.

**Symptom.** Pipeline stalls or returns partial results. The
error message names the cap and suggests opening a new session.

**Recovery.** Start a new MCP session (in Claude Code: new
conversation). The daemon does NOT need to be restarted.

### FM5 — Warm daemon serves stale corpus after ingest

**Trigger.** Operator runs `tools/notebook_ingest.py` and adds new
papers to a notebook while the daemon is alive. The daemon's
`corpus_version` was set at startup and does not auto-refresh.

**Symptom.** `search_papers` for a query relevant to the new
paper returns results that don't include it.

**Recovery.** Restart the daemon (`SIGTERM` + relaunch). The new
process reads the updated `corpus-version.json` and serves the
fresh corpus. Tier-1 cache entries from the old version are
unreachable by construction (key includes `corpus_version`).

### FM6 — Mode 2: shared cap exhausted across multiple notebooks

**Trigger.** A pipeline queries N notebooks in one session, each
with one `search_papers` call. N > 3.

**Symptom.** Same `RETRIEVAL_CAP_REACHED` as FM4, but unexpectedly
fast because the operator was thinking per-notebook.

**Recovery.** Either:
- Restructure the pipeline to issue ≤ 3 `search_papers` calls
  total per session (use larger `k` to pull more candidates per
  call, then route via `get_chunk`), OR
- Fall back to Mode 1 for the notebooks involved (separate
  daemons → separate caps), OR
- Open one MCP session per notebook (fresh-session-per-query
  pattern, applied per-notebook instead of per-claim).

---

## See also

- [`docs/install.md`](../install.md) — install + Claude Code MCP registration.
- [`docs/ops/bulk-ingest-runbook.md`](bulk-ingest-runbook.md) — initial corpus ingest.
- [`docs/ops/failure-modes.md`](failure-modes.md) — server-side failure modes
  (orthogonal to the deployment-topology failure modes above).
- [`.claude/notes/06-mcp-server-design.md`](../../.claude/notes/06-mcp-server-design.md)
  — server-design constitution; session-cap rationale.
- [`.claude/notes/07-multi-agent-caching.md`](../../.claude/notes/07-multi-agent-caching.md)
  — BP1/BP2 prompt-cache discipline; tool-schema byte-stability.
- [`.claude/notes/proof-verify-pivot/synthesis.md`](../../.claude/notes/proof-verify-pivot/synthesis.md)
  — the 2026-05-20 pivot synthesis that motivated this runbook.

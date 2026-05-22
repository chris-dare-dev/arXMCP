# Research Brief — proof-verify-handler-wiring-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T00:30:00Z

## In-codebase context

### Doc placement constraint (load-bearing)

From `CLAUDE.md §1`:

> `docs/` — ONLY user-facing documentation referenced by the root README.md. Today: just `docs/install.md`.

The milestone brief says "docs/install.md (or new `docs/notebooks.md` if it grows)."
A new `docs/notebooks.md` is operator-facing and WOULD be valid at `docs/` IF it is
linked from the root README. The brief's parenthetical "if it grows" is the correct
gate: if the new content can be folded into `docs/install.md` cleanly (one new section),
stay in `install.md`. If the notebooks runbook becomes a standalone reference (>400 words,
separate concern), create `docs/notebooks.md` and add a link from `docs/install.md`.
Either placement is spec-legal; the implementer must pick one and link it.

**Recommendation:** extend `docs/install.md` with a new §5 "Notebook topology". A
second `docs/*.md` at this size would fragment the install experience unnecessarily.

### Session cap constants — verbatim from `server/session.py`

```python
MAX_SEARCH_PAPERS_CALLS: int = 3
MAX_GET_CHUNK_CALLS: int = 4
MAX_REGISTRY_SIZE: int = 10_000
MAX_CALLS_PER_HOUR: int = 1000
HOURLY_WINDOW_SECONDS: int = 3600
```

The docstring states:
> *"The brief AC: 'A session that calls `search_papers` four times receives
> `RETRIEVAL_CAP_REACHED` on the fourth call.' So the cap is 3 successful
> calls; the 4th is rejected."*

The cap is **in-memory only** — resets on server restart. The docstring is explicit:
> *"Counters reset on server restart. The brief is explicit; per the project's
> caching note: 'Caching is performance, not correctness.' The cap is a defensive
> ceiling, not a security contract."*

### Corpus path — verbatim from roadmap milestone brief (state.json)

The milestone brief says: "Doc explicitly names the 22-paper math.AG corpus at
`var/arxmcp/index/lancedb-staging` as the working example for downstream cross-reference."

**CONFLICT FLAG:** `08-security-observability-ops.md` line 241 states:
> `LanceDB indices: /var/arxmcp/index/lancedb/`

The canonical production path is `var/arxmcp/index/lancedb/` (without `-staging`).
The staging path `var/arxmcp/index/lancedb-staging` is a local convention established
during the 2026-05-20 corpus-rebuild work, but it is not documented anywhere in the
design constitution. **The doc must name `-staging` as a developer-only path and use
the canonical `lancedb/` path for production examples.** The implementer should verify
the actual path in use at `var/arxmcp/index/` before finalizing the doc.

### BP1 tool-schema stability commitment

From `07-multi-agent-caching.md`:
> "Pin tool JSON schemas. Sort properties alphabetically at serialization time.
> Freeze descriptions as constants in source. A casual edit to a tool description
> blows every sub-agent's cache."

And from the roadmap (Phase 3, KR5):
> "No MCP tool input-schema break: `EXPECTED_TOOL_SCHEMA_SHA256` in
> `tests/test_server_tool_schema.py` stays pinned through this entire roadmap."

The doc's AC requires citing this stability commitment. The correct citation target
is `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256` (the pinned hash)
and the underlying guarantee from `07-multi-agent-caching.md` Property 1.

### Per-call filter payload budget

From the roadmap (REFINE Assumptions):
> "[SHOULD] Per-call paper_id lists of ~100 ids fit comfortably inside the MCP
> request byte caps. 100 × ~12 bytes ≈ 1.2 KB; cap is 256 KB (E13_S04b)."

This is the "tested up to N" number the doc AC requires. The implemented cap is
`DEFAULT_RESULT_BYTE_CAP = 256 * 1024` (from `server/config.py:58`).

### arXiv politeness contract — verbatim from `tools/arxiv_fetch.py`

```python
POLITENESS_SLEEP_SECONDS = 3.0
DEFAULT_503_BACKOFF_SECONDS = 30.0
MAX_503_BACKOFF_SECONDS = 300.0
```

The runbook should mention this when discussing daemon-restart-after-ingest, because
ingest uses this sleep contract and cannot be run continuously while the daemon is live.

## Prior decisions and lessons

Recent git log shows the last commit is `0555ea2 chore(notes): mark E13_S04b external
writes as completed`. The milestone is newly initialized (phase: `research-running`,
no implementation_commit_range).

From MEMORY.md (present in agent context):
- **E13_S04 memory:** `filters: dict[str, Any] | None` previously had NO item-count
  limit. The m1 milestone adds a paper_id list validator — the doc should cite the
  maximum validated list size once m1's implementation is known.
- **Doc placement correction pattern (E13_S01):** Audit docs go to `.claude/docs/`.
  For this milestone, the content is operator-facing and goes to `docs/install.md` or
  `docs/notebooks.md` — NOT `.claude/`. This is correct.
- The roadmap explicitly marks e3 (hybrid+rerank wiring) **CLOSED 2026-05-21 (verdict
  NO from m5)**. The doc should NOT mention hybrid+rerank as a current or planned mode.
  The three operational modes are: dense-only per-daemon, dense-only per-call filter,
  and the session-cap tradeoff between them.

### Confirmed gap from proof-chain-workflow.md

From `.claude/docs/proof-chain-workflow.md`:
> "A `paper_id` filter passed via `filters={"paper_id": "<id>"}` is acknowledged in
> the response's `filter_warnings` but NOT honored — the server returns a generic
> top-k search result that is not paper-scoped."

This is the pre-m1 state. The m3 doc is written AFTER m1 ships (dependency), so the
doc correctly documents the NEW behavior (filter honored). The implementer must verify
m1 has actually shipped before writing the doc — if m1's commit is absent, this doc
should not be written yet.

## External sources

### MCP spec 2025-06-18 — Session lifecycle (version-pinned)

From `https://modelcontextprotocol.io/specification/2025-06-18/basic/transports`:

> "A server using the Streamable HTTP transport **MAY** assign a session ID at
> initialization time, by including it in an `Mcp-Session-Id` header on the HTTP
> response containing the `InitializeResult`."

> "If an `Mcp-Session-Id` is returned by the server during initialization, clients
> using the Streamable HTTP transport **MUST** include it in the `Mcp-Session-Id`
> header on all of their subsequent HTTP requests."

> "When a client receives HTTP 404 in response to a request containing an
> `Mcp-Session-Id`, it **MUST** start a new session by sending a new
> `InitializeRequest` without a session ID attached."

> "Clients that no longer need a particular session **SHOULD** send an HTTP DELETE
> to the MCP endpoint with the `Mcp-Session-Id` header, to explicitly terminate
> the session."

**Implication for the fresh-session-per-query pattern:** Starting a fresh session
is SPEC-COMPLIANT. The client sends a new `InitializeRequest` without a session ID.
The server issues a new session ID. Counters start at 0. This is NOT a workaround —
it is the normative MCP session lifecycle. The doc should state this explicitly.

**No MUST clause prohibits session proliferation.** The spec does not say clients
must reuse sessions across queries. The fresh-session-per-query pattern is valid.

### Anthropic prompt-caching TTL

From `07-multi-agent-caching.md`:
> "TTL: 5 minutes default; 1 hour via beta header
> `anthropic-beta: extended-cache-ttl-2025-04-11`"

> "Cache is org-scoped, not session-scoped."

**Implication for the runbook:** A fresh MCP session (new `Mcp-Session-Id`) does NOT
reset the Anthropic prompt cache. The BP1 cache key is the hash of the system prompt
+ tool definitions — independent of session ID. However, BP2 includes the problem
statement, which per-query is different anyway. The fresh-session pattern restarts
the retrieval-cap counters but does NOT invalidate the prompt cache for the system
prompt block. This is the correct behavior; the doc may note it briefly to dispel
any misconception that session rotation is expensive.

### arXiv politeness

From `tools/arxiv_fetch.py`: 3s sleep between requests, 30s initial 503 backoff,
300s max backoff. The doc should note that ingest runs require `ARXMCP_CONTACT_EMAIL`
per arXiv TOS §3 ("arXMCP/0.1 (mailto:{email})") and should NOT be run while the
daemon serves the same LanceDB path under write.

## Failure-mode analysis

### FM1 — ARXMCP_LANCEDB_PATH typo → daemon serves wrong corpus

**Trigger:** Operator copy-pastes the env var path with a trailing slash, a typo in
the notebook slug, or the wrong index subdirectory (e.g., `lancedb-staging` vs
`lancedb`). The daemon starts, /readyz returns 200, but all queries return results
from the wrong paper set.

**Observable symptom:** `search_papers` returns papers not in the target notebook;
no error is raised. The bug is silent until a human inspects the paper_ids in results.

**Mitigation the doc must provide:** After starting a daemon, run a sanity-check query
(`search_papers(query="<a known title>", k=1)`) and verify the returned `paper_id` is
in the expected notebook. Name the path explicitly with a copy-pasteable example:
`ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb`.

### FM2 — Per-call filter mode: paper_id list exceeds the validated budget

**Trigger:** Operator passes a list of 1000+ paper_ids per call, either due to a
large notebook or an accidental duplicate IDs in the list.

**Observable symptom (post-m1):** The m1 validator rejects oversized lists with a
structured error in the `result.isError=true` envelope (not a 500). The agent sees
a `FILTER_VALIDATION_ERROR` (or equivalent) but may not know the list-size limit.

**Mitigation the doc must provide:** State the tested limit (~100 paper_ids; 1.2 KB
well under the 256 KB cap). State the maximum validated size once m1 ships. Document
deduplication: the client should deduplicate paper_ids before passing to avoid
silent overcounting.

### FM3 — Two daemons against the same LanceDB directory

**Trigger:** Operator launches two daemons pointing at the same
`ARXMCP_LANCEDB_PATH` — e.g., during a daemon-restart or a port conflict. If one
daemon is running ingest while the other serves, LanceDB MVCC semantics apply but
writes from ingest may not be immediately visible to the serving daemon.

**Observable symptom:** LanceDB uses MVCC (E04) — concurrent reads are safe. But if
the operator is also running `notebook_ingest.py` against the same path, the serving
daemon caches the old corpus_version and serves stale results until restart.

**Mitigation the doc must provide:** Rule: do NOT run `notebook_ingest.py` against a
path that a live daemon is serving. After ingest completes, restart the daemon
(SIGTERM + relaunch) so it picks up the new corpus_version from `corpus-version.json`.
Two READ-ONLY daemons against the same path are safe (MVCC).

### FM4 — 3-call cap fires mid-pipeline; operator doesn't know how to reset

**Trigger:** A `/proof-verify` pipeline uses 2 calls in round 1 (search + refine),
then hits the cap on the third search attempt. The agent receives `RETRIEVAL_CAP_REACHED`
with `code: "RETRIEVAL_CAP_REACHED"`. The operator sees an error in the pipeline log
but doesn't recognize the recovery pattern.

**Observable symptom:** The pipeline stalls or returns partial results. The error
message says "proceed with chunks already retrieved or open a new session" — but
the operator may not know how to open a new session.

**Mitigation the doc must provide:** Explain the fresh-session-per-query pattern
explicitly. In Claude Code's MCP harness, a new session is started by starting a new
conversation (or by the harness issuing a new `InitializeRequest`). The operator
does NOT need to restart the daemon. Name the cap constants by their code values:
`MAX_SEARCH_PAPERS_CALLS = 3`.

### FM5 — Daemon warm corpus becomes stale after ingest of new notebook

**Trigger:** Operator ingests a new paper into a notebook after the daemon has been
running for hours. The daemon holds a warm LanceDB connection and an in-memory
retrieval cache keyed by `corpus_version`. The new paper is written to LanceDB under
a new corpus version, but the daemon's Tier-1 cache still serves old results until
the 1-hour TTL expires or the daemon restarts.

**Observable symptom:** `search_papers` for a query relevant to the new paper returns
results that don't include it, even though the paper has been ingested.

**Mitigation the doc must provide:** After any `notebook_ingest.py` run that adds
new papers, restart the daemon. The corpus_version key in the Tier-1 cache
(from `07-multi-agent-caching.md`: "key includes `corpus_version: int` as a mandatory
component; stale entries from old corpus versions are unreachable by construction after
a restart") ensures correctness after restart. Do NOT expect live reload; v1 has no
hot-reload.

### FM6 — Per-call mode: shared 3-call cap across notebooks causes unexpected exhaustion

**Trigger:** A pipeline processes multiple notebooks in a single session, calling
`search_papers` once per notebook. With 3+ notebooks in one session, the cap fires
before all notebooks are queried.

**Observable symptom:** Same as FM4 but triggered by multi-notebook usage, not
per-notebook query volume. The operator assumes per-call filter mode is "free" of
per-notebook isolation issues, not realizing the cap is shared.

**Mitigation the doc must provide:** This is the core trade-off table row:
"per-call = shared 3-call-cap across ALL notebooks in one session." The doc must
state: if you have N notebooks and plan >3 total `search_papers` calls per pipeline
run, either use per-daemon mode (separate cap per daemon) or design the pipeline
to use ≤3 calls across all notebooks and rely on larger k values to pull sufficient
candidates in fewer calls.

## Recommendation

**Write the runbook as a new §5 in `docs/install.md`** (not a new file). The section
should be titled "§5. Notebook topology: per-daemon vs per-call filter mode."

Structure:
1. **2-line scope statement** — who this is for, what it covers.
2. **§5.1 Per-daemon mode** (Mode 1, today's working pattern) with a copy-pasteable
   `ARXMCP_LANCEDB_PATH=...` command block. Name the 22-paper corpus path
   (`var/arxmcp/index/lancedb-staging` labeled as developer-only; production path
   is `var/arxmcp/index/lancedb`).
3. **§5.2 Per-call filter mode** (Mode 2, post-m1) with a copy-pasteable Python
   snippet showing `filters={"paper_id": [...]}`. State the ~100-paper_id budget
   and the 256 KB cap source.
4. **§5.3 Trade-off matrix** (4-column table):
   - Isolation | Session-cap behavior | Restart-on-ingest | Startup cost
5. **§5.4 Session-cap and fresh-session pattern** — explain `MAX_SEARCH_PAPERS_CALLS = 3`,
   the `RETRIEVAL_CAP_REACHED` error, the MCP spec clause on new sessions, and
   the BP1 prompt-cache note (session rotation does NOT invalidate the tool-schema
   cache; the EXPECTED_TOOL_SCHEMA_SHA256 stability commitment holds).
6. **§5.5 Failure modes and recovery** — distill FM1–FM6 above into 2-line bullets.

**Prose density target:** Match `docs/install.md` §4 (Verify the shim). Each subsection
should be 3–8 lines of prose + one copy-pasteable block. NOT a terse reference card
(too dense to onboard), NOT a narrative essay (too slow for an operator with a problem).
The troubleshooting table at the bottom of `docs/install.md` is the right density for
FM5 and FM6 — extend that table rather than creating a separate failure-modes section.

**Trade-off matrix headers (implementer starts here):**

| Dimension | Per-daemon mode | Per-call filter mode |
|---|---|---|
| Corpus isolation | Hard (separate LanceDB dir) | Soft (filter predicate, same LanceDB) |
| Session-cap behavior | 3 calls per notebook daemon session | 3 calls shared across ALL notebooks |
| Restart required after ingest | Yes (always) | Yes (always) |
| Startup cost | High (BGE-M3 reload per daemon) | Low (one warm process) |

## Open questions

1. **What is the exact maximum paper_id list size validated by m1?** The milestone brief
   says "~100 paper_ids per call comfortably; tested up to N" — N is unknown until m1's
   implementation is read. The implementer must check `server/handlers/search.py`
   post-m1 for the validator's hard limit and state it in the doc.

2. **Does `var/arxmcp/index/lancedb-staging` exist on the current system at the time
   this doc is written?** The milestone brief names it as "the working example," but
   the design constitution's canonical path is `var/arxmcp/index/lancedb`. The
   implementer must check `var/arxmcp/index/` and use the path that actually exists,
   labeled appropriately (staging vs production).

3. **Should the troubleshooting table in `docs/install.md` be extended (appending FM1–FM6
   rows), or should §5.5 be a standalone failure-mode section?** The existing table has
   4 rows; adding 6 more keeps it in one place but makes it longer. Implementer's call —
   both are valid.

## External writes the implementation will require

None — this milestone is purely local. The doc change lands in `docs/install.md` (or
`docs/notebooks.md`) and a link is added to `README.md`. Both are in-repo file edits
with no external API calls, no git push (gated on user authorization per CLAUDE.md §4.4),
and no infra mutations.

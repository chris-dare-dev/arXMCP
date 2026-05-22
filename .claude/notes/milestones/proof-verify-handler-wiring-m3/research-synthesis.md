# Research Synthesis — proof-verify-handler-wiring-m3

**Orchestrator merge of:** `research-brief-1.md`, `research-brief-2.md`
**Generated:** 2026-05-22T01:15:00Z
**Mode:** standard (2× Sonnet in parallel)

## TL;DR for the implementer

Pure-docs milestone. Create **`docs/ops/notebook-modes.md`** and add ONE
row to the operator-runbook table in `README.md`. The doc covers the
three operational modes (per-daemon vs per-call filter vs the trade-off),
documents the `MAX_SEARCH_PAPERS_CALLS = 3` cap + fresh-session pattern,
cites `EXPECTED_TOOL_SCHEMA_SHA256` for schema stability, and names
`var/arxmcp/index/lancedb-staging` as the developer-facing working
example while noting the canonical production path is
`var/arxmcp/index/lancedb`. Target prose density: match the existing
runbooks under `docs/ops/` (bulk-ingest-runbook.md, latexml-drift-runbook.md).
No code changes. No external writes.

## Resolved disagreements

### Disagreement 1 — Doc location

**R-1:** Create `docs/ops/notebook-modes.md` and add one row to the
README's runbook table.

**R-2:** Extend `docs/install.md` with a new `§5. Notebook topology`.

**Synthesis decision: R-1 wins.** R-2 did not see the established
precedent R-1 surfaced from `README.md:63-76`:

> Operator runbooks live under [`docs/ops/`](docs/ops/):
> | [`latexml-drift-runbook.md`](docs/ops/latexml-drift-runbook.md) | E10_S04 | … |
> | [`bulk-ingest-runbook.md`](docs/ops/bulk-ingest-runbook.md) | E11_S01 | … |
> … (10 runbooks listed) …

This is decisive. Every prior operator runbook in the project lives
under `docs/ops/` and is linked from the README's runbook table. The
notebook-mode topology decision is exactly the kind of per-scenario
operator-facing reference these runbooks provide. Embedding the
content in `docs/install.md` would mix install-time setup with
deployment-time topology decisions. The milestone brief itself allowed
"docs/install.md or new docs/notebooks.md if it grows" — neither
option matches the project's established `docs/ops/` convention.
`docs/ops/notebook-modes.md` satisfies the AC ("linked from root
README.md or docs/install.md") with the canonical README link.

### Disagreement 2 — `lancedb-staging` path vs canonical `lancedb` path

Both researchers flagged this. The milestone brief AC says to "name
the 22-paper math.AG corpus at `var/arxmcp/index/lancedb-staging` as
the working example." R-2 cites `08-security-observability-ops.md:241`
naming `var/arxmcp/index/lancedb/` as the canonical production path.

**Synthesis decision:** Use BOTH, labeled. The doc explicitly names
`var/arxmcp/index/lancedb-staging` as the **developer-only / spike**
path (this is what's actually populated on Chris's box today and what
the downstream `/proof-verify` consumer references), AND notes that
the **canonical production path** for a single-corpus operator is
`var/arxmcp/index/lancedb`. The per-notebook Variant 1 pattern (from
m6) uses `var/arxmcp/notebooks/<slug>/lancedb/`. Implementer must
verify `var/arxmcp/index/lancedb-staging` exists at write time:

```bash
ls /Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/index/
```

R-1 confirmed it does: `bm25 kuzu lancedb lancedb-staging` are all
present.

### Disagreement 3 — "tested up to N" wording

R-2 wants the doc to state the m1-validated maximum. R-1 says the
m1 synthesis records no tested-N beyond 100 and recommends stating
the hard cap (`MAX_PAPER_ID_FILTER_ITEMS = 100`) as the guarantee.

**Synthesis decision: R-1 wins.** Write the hard cap as the
guarantee: "up to 100 paper IDs per call (`MAX_PAPER_ID_FILTER_ITEMS
= 100` at `server/handlers/search.py:108`, exercised by the m1 test
suite at `tests/test_search_filter.py::TestRectificationGuards`)."
Do NOT invent a higher tested-N. The 256 KB envelope cap
(`DEFAULT_RESULT_BYTE_CAP` at `server/config.py:58`) is the
secondary structural bound (R-2's contribution); cite both.

## Load-bearing constants (verbatim from code)

These are the numbers the doc body must include unchanged. Implementer
should reference by `file:line` so a future refactor cannot silently
drift them.

| Symbol | Value | Site |
|---|---|---|
| `MAX_SEARCH_PAPERS_CALLS` | `3` | `server/session.py:54` |
| `MAX_GET_CHUNK_CALLS` | `4` | `server/session.py` (companion; R-2 surfaced) |
| `MAX_PAPER_ID_FILTER_ITEMS` | `100` | `server/handlers/search.py:108` |
| `DEFAULT_RESULT_BYTE_CAP` | `256 * 1024` (256 KB) | `server/config.py:58` |
| `ARXMCP_LANCEDB_PATH` default | `Path("var/arxmcp/index/lancedb")` | `server/config.py:97` |
| Default bind port | `7733` | `server/config.py:48` |

## Quoted constraints (verbatim from design constitution)

**Doc-placement rule** (`CLAUDE.md §1`, R-1 quote):
> | **`docs/`** | ONLY user-facing documentation referenced by the root `README.md`. Today: just `docs/install.md`. |

**README precedent** (`README.md:63-76`, R-1 quote — DECISIVE for
doc-location ruling):
> Operator runbooks live under [`docs/ops/`](docs/ops/)

**Tool-schema stability commitment** (`07-multi-agent-caching.md:40-48`,
R-1 quote):
> Property 1: Tool definitions are byte-stable. … A casual edit to a
> tool description blows every sub-agent's cache. … bump the hash
> deliberately when intentionally changing schema; treat as an API
> version bump.

**Session cap docstring** (`server/session.py`, R-2 quote):
> The cap is in-memory only — resets on server restart. … 'Caching is
> performance, not correctness.' The cap is a defensive ceiling, not
> a security contract.

**MCP spec session lifecycle** (R-2 quote from spec 2025-06-18):
> When a client receives HTTP 404 in response to a request containing
> an `Mcp-Session-Id`, it MUST start a new session by sending a new
> `InitializeRequest` without a session ID attached.

> Clients that no longer need a particular session SHOULD send an
> HTTP DELETE … to explicitly terminate the session.

This is decisive: **the fresh-session-per-query pattern is
spec-normative, not a workaround**. The doc should say so plainly.

**Anthropic prompt-cache TTL** (`07-multi-agent-caching.md`, R-2 quote):
> TTL: 5 minutes default; 1 hour via beta header. Cache is org-scoped,
> not session-scoped.

This dispels the misconception that session rotation invalidates the
BP1 prompt cache. It does not — BP1 is keyed on the system prompt +
tool definitions, independent of `Mcp-Session-Id`. The doc should
note this in passing so an operator doesn't fear session churn.

## Failure modes the doc must inoculate against

R-2's catalog (FM1–FM6), distilled into doc requirements:

1. **`ARXMCP_LANCEDB_PATH` typo serves wrong corpus** — the EXACT bug
   Chris hit on 2026-05-20. Mitigation: after starting a daemon, run
   a sanity-check `search_papers(query="<known title>", k=1)` and
   verify the returned paper_id is in the expected notebook.
2. **paper_id list exceeds 100** — m1 validator rejects with a
   structured error; doc must name the limit + recommend client-side
   dedup before passing.
3. **Two daemons against the same LanceDB dir** — read-only is safe
   (MVCC), but **never run `notebook_ingest.py` against a path a live
   daemon is serving**. After ingest, SIGTERM + relaunch.
4. **3-call cap fires mid-pipeline** — operator must know that
   starting a new conversation in Claude Code = new MCP session = cap
   resets; daemon restart is NOT required.
5. **Warm-daemon staleness after ingest** — Tier-1 cache is keyed on
   `corpus_version`, so a restart after ingest is sufficient and
   necessary. v1 has no hot-reload.
6. **Per-call shared-cap surprise** — the 3-call cap is per-session,
   not per-notebook. Multi-notebook pipelines in one session must
   plan for ≤3 total `search_papers` calls or use per-daemon mode.

## Doc structure (synthesis of R-1 §Recommendation + R-2 §Recommendation)

`docs/ops/notebook-modes.md`:

```
# Notebook deployment topology — per-daemon vs per-call filter

## Scope                       (2–3 lines; who/what)

## Mode 1 — Per-daemon isolation
   - Copy-pasteable env-var + launch command
   - Cite ARXMCP_LANCEDB_PATH default + override
   - Name var/arxmcp/index/lancedb-staging as the dev example
   - Note: ~3.5 GB RAM per daemon (pivot synthesis Finding E)

## Mode 2 — Per-call paper_id filter
   - Copy-pasteable JSON-RPC tool_call snippet showing
     filters={"paper_id": [...]}
   - State the 100-id cap + 256 KB envelope cap
   - Note: filters_applied echo (m2) lets the caller verify scoping

## Trade-off matrix
   | Dimension           | Per-daemon  | Per-call filter |
   |---|---|---|
   | Corpus isolation    | Hard        | Soft (predicate) |
   | Session-cap         | Per-daemon  | Shared (3 total) |
   | Startup cost        | High (BGE×N)| Low (1 process)  |
   | Restart after ingest| Yes         | Yes              |
   | RAM cost            | ~3.5 GB × N | ~3.5 GB total    |

## Session cap and the fresh-session pattern
   - MAX_SEARCH_PAPERS_CALLS = 3 (cite server/session.py:54)
   - In-memory; resets on server restart (NOT a security contract)
   - Fresh session = new InitializeRequest per MCP spec 2025-06-18
   - Session rotation does NOT invalidate BP1 prompt cache
     (cite 07-multi-agent-caching.md)

## Schema stability commitment
   - EXPECTED_TOOL_SCHEMA_SHA256 pin at tests/test_server_tool_schema.py
   - filters arg + filters_applied are v1-stable
   - Bumps treated as API version (cite 07-multi-agent-caching.md
     Property 1)

## Failure modes and recovery
   - FM1–FM6 distilled into 2-line bullets each

## See also
   - docs/install.md (install + Claude Code MCP registration)
   - docs/ops/bulk-ingest-runbook.md
```

## Acceptance-criteria mapping

From the milestone brief:
- [ ] **Doc section exists and is linked from root README or
  docs/install.md** — satisfied by creating `docs/ops/notebook-modes.md`
  and adding ONE row to the runbook table in `README.md:63-76`.
- [ ] **Doc explicitly names the 22-paper math.AG corpus at
  `var/arxmcp/index/lancedb-staging` as the working example** —
  satisfied by Mode 1 subsection.
- [ ] **Doc states the per-call paper_id list size budget** —
  satisfied by Mode 2 subsection, citing `MAX_PAPER_ID_FILTER_ITEMS = 100`
  at `server/handlers/search.py:108` and the 256 KB envelope cap at
  `server/config.py:58`.
- [ ] **Doc cites the `EXPECTED_TOOL_SCHEMA_SHA256` stability
  commitment** — satisfied by the "Schema stability commitment"
  subsection citing `tests/test_server_tool_schema.py` and
  `07-multi-agent-caching.md` Property 1.
- [ ] **No code changes — pure docs** — satisfied by construction.

## Open questions (deduped union)

1. **Exact wording for the recommended second-port example** (R-1).
   The default bind port is 7733 (`server/config.py:48`). For
   per-daemon mode with two notebooks, the doc should show a concrete
   second port (7734) plus the env var `ARXMCP_BIND_PORT` if it
   exists, or instructing the operator to set the port via the
   shim/launch script. **Recommended resolution:** show `7733` for
   notebook A and `7734` for notebook B, both as bind-port overrides
   via env. Implementer verifies the actual env-var name in
   `server/config.py` at write time.

2. **Whether to extend the existing `docs/install.md` troubleshooting
   table OR keep a separate Failure-modes subsection in the new
   runbook** (R-2). **Recommended resolution:** keep the failure-modes
   in the new runbook (FM1–FM6 are notebook-mode-specific; the
   install.md troubleshooting table is install-specific).
   Cross-link only.

3. **Whether `var/arxmcp/index/lancedb-staging` exists at write time
   on the implementer's machine** (R-2). R-1 confirmed it does. The
   implementer must re-verify this before naming it as a working
   example; if it has been wiped between R-1's check and write time,
   re-name to the bridgeland-stability notebook path
   (`var/arxmcp/notebooks/bridgeland-stability/lancedb/`) instead.

None of the open questions are blockers — all have a defensible
default resolution.

## External writes required

**None.** Pure-docs milestone. All file changes are in-repo:
1. NEW: `docs/ops/notebook-modes.md` (~250–400 lines target;
   matching the prose density of existing `docs/ops/*.md` runbooks).
2. EDIT: `README.md` — add one row to the runbook table at
   approximately lines 63–76. Row format must match the existing
   rows verbatim (epic | path | one-line description).

Phase 4 has no external-write authorization gates to fire.

## Orchestrator synthesis note

The two researchers converged tightly on substance and diverged only
on doc location. R-2's failure-mode catalog and MCP-spec quotes are
the strongest contributions to the implementation; R-1's surfacing of
the `docs/ops/` precedent decided the location call. The
`lancedb-staging` vs canonical-`lancedb` flag was independently
caught by both — the doc must label both paths explicitly to avoid a
future operator confusing them.

The recommended commit type is `docs(repo)` (per `CLAUDE.md §4.3`)
since the change is repo-doc-layout-touching (adds to README's
runbook table). One file added + one file edited = inline-path
implementation in the orchestrator (well under the 500 LOC / 5 file
threshold).

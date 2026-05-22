# Research Brief — proof-verify-handler-wiring-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T00:30:00Z

---

## In-codebase context

### 1. Doc-placement rule + README link policy

From `CLAUDE.md §1` (verbatim):

> | **`docs/`** | ONLY user-facing documentation referenced by the root `README.md`. Today: just `docs/install.md`. |

From `CLAUDE.md §1` (verbatim):

> When you create a new Markdown file, default to `.claude/` unless the content is BOTH operator-facing AND linked from the root README.

**However:** the root `README.md` has an established precedent for `docs/ops/` runbooks that is live TODAY. `README.md:63-76` reads:

> Operator runbooks live under [`docs/ops/`](docs/ops/):
> | [`latexml-drift-runbook.md`](docs/ops/latexml-drift-runbook.md) | E10_S04 | …
> | [`bulk-ingest-runbook.md`](docs/ops/bulk-ingest-runbook.md) | E11_S01 | …
> …(10 runbooks listed)…

This means `docs/ops/` is an established, README-linked location for operator-facing runbooks. The per-notebook daemon vs per-call filter runbook is clearly operator-facing (it tells arXMCP operators how to deploy for notebook use cases). It belongs in `docs/ops/`, NOT in `docs/install.md` and NOT under `.claude/`.

**Ruling: create `docs/ops/notebook-modes.md` linked from `README.md`.**

Reasons:
1. The content is purely operator-facing — how to run the daemon in each mode.
2. `docs/install.md` covers installation, registration, and startup. The notebook-mode trade-off is a deployment topology decision, not an installation step. It warrants its own runbook.
3. `docs/install.md` is already a focused "getting-started" document. Embedding a three-mode operational runbook there would bloat it with topology content that only relevant for multi-notebook consumers.
4. All other per-scenario runbooks (bulk ingest, delta loop, backup, etc.) live in `docs/ops/` and are linked from `README.md:63-76`. The notebook-mode runbook fits this exact pattern.

**The milestone brief says "docs/install.md (or new docs/notebooks.md if it grows)."** Both are inferior to `docs/ops/notebook-modes.md`. The `docs/notebooks.md` suggestion would create a top-level docs file outside the established `docs/ops/` sub-pattern; `docs/install.md` would mix setup with topology. `docs/ops/notebook-modes.md` matches the project's existing operator-runbook convention.

**CONFLICT FLAG: The milestone brief's suggested destinations (`docs/install.md` or `docs/notebooks.md`) are inconsistent with the established `docs/ops/` runbook pattern.** The brief is not wrong that `docs/` is the right top-level location, but it does not name the correct sub-path. The correct destination is `docs/ops/notebook-modes.md`. The implementer should use `docs/ops/notebook-modes.md` and link it from `README.md`.

---

### 2. Substantive content the doc must cover

#### MAX_SEARCH_PAPERS_CALLS = 3

- **Definition:** `server/session.py:54`
  ```python
  MAX_SEARCH_PAPERS_CALLS: int = 3
  ```
- **Docstring at `server/session.py:50-53`:** "Maximum number of `search_papers` tool calls per MCP session. The brief AC: `A session that calls `search_papers` four times receives `RETRIEVAL_CAP_REACHED` on the fourth call.` So the cap is 3 successful calls; the 4th is rejected."
- **Enforcement site:** `server/session.py:208` (the `SessionCapMiddleware` calls `limit = MAX_SEARCH_PAPERS_CALLS` when checking the per-session counter)
- **Pivot synthesis reference (verbatim):** `Finding D — the 3-call-per-session MCP cap is intentional`: "Downstream's fresh-session-per-query workaround is the correct workaround for their use case (per-claim retrieval)." (`.claude/notes/proof-verify-pivot/synthesis.md:131`)

#### MAX_PAPER_ID_FILTER_ITEMS = 100

- **Definition:** `server/handlers/search.py:108`
  ```python
  MAX_PAPER_ID_FILTER_ITEMS = 100
  ```
- **Docstring at `server/handlers/search.py:100-108`:** "Hard upper bound on the length of the `filters['paper_id']` list … 100 matches the roadmap's design target ('~100 paper_ids per call comfortably'). Enforced in handler body for the same BP1 byte-stability reason as `MAX_FILTER_ITEMS`."
- This is the "~100 paper_ids per call" budget number the AC requires. The doc should cite 100 as the hard cap (no tolerance for more). The "tested up to N" wording in the AC refers to the spike; the m1 synthesis does not record a specific tested-N beyond 100, so the doc should state the hard cap as the guarantee.

#### ARXMCP_LANCEDB_PATH

- **Config field:** `server/config.py:97`
  ```python
  lancedb_path: Path = Path("var/arxmcp/index/lancedb")
  ```
- **Env prefix:** `server/config.py:80` — `env_prefix="ARXMCP_"` — so the env var is `ARXMCP_LANCEDB_PATH`.
- **Threading:** `Config.lancedb_path` is passed into `Resources.startup()` (the lifespan handler) where the LanceDB connection is opened. Setting a different path before server startup routes the process to a different corpus directory.
- The pivot synthesis (`synthesis.md:43-44`, verbatim) documents the per-daemon pattern: "One daemon per notebook via `ARXMCP_LANCEDB_PATH=<dir>` on different ports … Used today to unblock spike-4; 22-paper math.AG corpus is a working example at `var/arxmcp/index/lancedb-staging`."

#### EXPECTED_TOOL_SCHEMA_SHA256 stability commitment

- **File:** `tests/test_server_tool_schema.py:94-98`
- **Commitment (from the file module docstring at lines 1-20):** "A drift means: either you intentionally changed a tool name / description / argument schema (in which case bump `server.tools.TOOL_SCHEMA_VERSION` AND run `pytest --update-tool-schema-hash` to refresh the constant below), or you made an accidental edit that just nuked every sub-agent's cached prefix."
- **From `07-multi-agent-caching.md:40-48` (verbatim):** "Property 1: Tool definitions are byte-stable. Pin tool JSON schemas. Sort properties alphabetically at serialization time. Freeze descriptions as constants in source. A casual edit to a tool description blows every sub-agent's cache. Implementation: a single `tools.py` module with frozen dataclasses + a unit test that asserts `sha256(serialize_tools()) == EXPECTED_HASH`. Bump the hash deliberately when intentionally changing schema; treat as an API version bump."
- The AC requires the runbook to cite this commitment. The doc should state that the `filters` argument to `search_papers` and its behavior are stable at v1; tool schema changes are treated as API version bumps tracked by `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`.

#### 22-paper math.AG corpus at var/arxmcp/index/lancedb-staging

- **Confirmed to exist:** `ls /Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/index/` returns `bm25 kuzu lancedb lancedb-staging`.
- **Canonical reference:** `.claude/notes/proof-verify-pivot/synthesis.md:43-44` — "22-paper math.AG corpus is a working example at `var/arxmcp/index/lancedb-staging`."
- The corpus is the bridgeland-stability notebook (39 papers) + shimura-varieties notebook (12 papers) mentioned in the spike notes, but the `lancedb-staging` path is the one the milestone brief specifies. The implementer should name it exactly as `var/arxmcp/index/lancedb-staging` in the doc.

#### Fresh-session-per-query pattern

- The `Mcp-Session-Id` is issued by the server and tracked per-client by the shim. A new session starts when the shim reconnects. The per-session counter resets.
- The session cap is enforced at `server/session.py:195-210` (the `check_and_increment` method). The `MAX_SEARCH_PAPERS_CALLS = 3` cap means a client that issues 4 `search_papers` calls in one session receives `RETRIEVAL_CAP_REACHED` on the 4th.
- The "fresh-session-per-query" pattern means: for each claim or sub-question the downstream pipeline wants to ground, it issues one `search_papers` call in a fresh MCP session. This uses 1 of 3 allowed calls and leaves 2 spare for follow-up `get_chunk` routing.
- This pattern is not documented anywhere in `docs/`; it exists only in the pivot synthesis note. The runbook is its first operator-facing documentation.

---

## Prior decisions and lessons

**Recent git log (last 20):**
- `9e17617 chore(notes): finalize proof-verify-handler-wiring-m2 state -> complete`
- `5a130c6 rect(server): close F1, F2, F3, F4, F5, F6 from m2 critique`
- `ba574e9 feat(server): echo filters_applied on search_papers (proof-verify-handler-wiring-m2)`
- `a1aa11b chore(notes): finalize proof-verify-handler-wiring-m1 state -> complete`
- `7bfb35b feat(server): paper_id filter wiring (proof-verify-handler-wiring-m1)`
- `904db00 chore(notes): finalize proof-verify-handler-wiring-m6 state -> complete`

Both m1 and m2 are complete. The `search_papers` handler now honors `filters={"paper_id": [...]}` (m1) and echoes `filters_applied` in its output (m2). The tool schema hash was re-pinned in m2 (`TOOL_SCHEMA_VERSION` 8→9). The `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` were both re-pinned as part of m2.

**m1 synthesis key finding for the doc:** "MAX_PAPER_ID_FILTER_ITEMS = 100" is the hard cap; "filters arg is accepted but not yet processed" warning is REMOVED when `paper_id` is honored (FM-9). The fresh-session workaround is the correct pattern for downstream.

**m2 synthesis key finding for the doc:** `filters_applied` is ABSENT (key not set) when no filter was passed — preserves byte-equivalence with pre-m2 responses.

**Pivot synthesis Finding E:** "22-paper corpus uses ~3.5 GB RAM (BGE-M3 + LanceDB + reranker if enabled). 10 notebooks × per-daemon = 35 GB peak. On commodity workstation hardware that's borderline; on a server it's trivial. Per-daemon is fine indefinitely up to ~10 notebooks, marginal at 20, painful at 50."

This is load-bearing context the runbook should include: when to prefer per-daemon vs per-call is not just a cap question, it's also a memory footprint question.

**The `docs/ops/` pattern is established.** The README already links 10 runbooks in `docs/ops/`. This is the correct home for the new runbook. No prior researcher or implementer has written a runbook outside `docs/ops/` since E11.

---

## External sources

No external sources are required for this pure-docs milestone. All relevant numbers, constraints, and behavioral descriptions exist in the codebase source files (`server/session.py`, `server/handlers/search.py`, `server/config.py`), the design constitution (`.claude/notes/07-multi-agent-caching.md`), and the prior milestone synthesis docs. The MCP spec and Anthropic prompt-caching docs are not needed — this runbook is about operational deployment topology, not protocol internals.

---

## Recommendation

**Create `docs/ops/notebook-modes.md` and add one row to the `README.md` Operations table.**

The file should cover:
1. **Mode 1 — per-daemon isolation:** `ARXMCP_LANCEDB_PATH=var/arxmcp/index/lancedb-staging` on a unique port; session cap applies per notebook cleanly; RAM cost is ~3.5 GB per daemon; recommended up to ~10 notebooks.
2. **Mode 2 — per-call filter:** one daemon at the default path; each `search_papers` call passes `filters={"paper_id": ["<id1>", ...]}` (up to 100 IDs hard cap, `MAX_PAPER_ID_FILTER_ITEMS = 100`); the 3-call session cap is shared across ALL notebooks in one session.
3. **Trade-off table:** per-daemon = hard notebook isolation + 3-call-cap per notebook session; per-call = single warm process + shared cap across all notebooks in one session.
4. **Fresh-session-per-query pattern:** for per-claim retrieval, start a new MCP session per query; uses 1 of 3 allowed `search_papers` calls.
5. **Working example:** `var/arxmcp/index/lancedb-staging` (22-paper math.AG corpus).
6. **Schema stability commitment:** `EXPECTED_TOOL_SCHEMA_SHA256` (in `tests/test_server_tool_schema.py`) is the pin; tool schema changes are treated as API version bumps.

Do NOT embed this in `docs/install.md` — the install doc is for getting started, not for deployment topology decisions. Do NOT create `docs/notebooks.md` at the top level of `docs/` — it breaks the `docs/ops/` convention for runbooks.

The commit type for this milestone is `docs(repo)` (per `CLAUDE.md §4.3`).

---

## Open questions

1. **Exact tested-N for the paper_id list budget.** The milestone AC says "tested up to N" — but neither the m1 synthesis nor the spike notes record a specific N above 100. The hard cap is 100 (`MAX_PAPER_ID_FILTER_ITEMS`). The doc should state the hard cap as the guarantee and note that 100 is "the design target" (exact language from the code comment at `server/handlers/search.py:107`). The implementer should NOT invent a higher tested-N without evidence. Recommended wording: "up to 100 paper IDs per call (the hard cap; tested in the proof-verify-handler-wiring-m1 test suite)."

2. **Which port to recommend for Mode 1 (per-daemon).** The default is 7733 (`server/config.py:48`). The pivot synthesis says "on different ports" but gives no example. The implementer should pick a concrete second port (e.g., 7734) for the runbook example, or use `ARXMCP_BIND_PORT=...` with a placeholder.

No open questions are blockers — implementation can proceed with the above recommendation and resolved defaults.

---

## External writes the implementation will require

None — this milestone is purely local. The only file changes are:
1. New file: `docs/ops/notebook-modes.md` (operator-facing runbook).
2. Edit: `README.md` — add one row to the Operations table linking to `docs/ops/notebook-modes.md`.

No git push, no PR, no infra mutation, no third-party API calls. Phase 4 has no external-write authorization gates to fire.

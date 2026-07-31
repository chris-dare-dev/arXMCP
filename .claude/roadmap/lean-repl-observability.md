---
project: arxmcp
type: plan
status: active
authorship: agent-generated
tags:
- project/arxmcp
- type/plan
- authorship/agent-generated
---

# Lean REPL observability — standalone milestone brief

> [!done] ARCHIVED — track complete, retained for the record
> **Moved** from `plans/lean-repl-observability.md` to `.claude/roadmap/` on 2026-07-29.
> `plans/` is reserved for live `roadmap/1` tracks (`plans/<slug>/roadmap.yaml`);
> `CLAUDE.md` § 1 allows no other Markdown outside `.claude/`. This directory is
> already the home of completed standalone briefs (`notebook-cutover.md`,
> `embedder-truncation.md`, …) and stays inside
> `milestone-pipeline-resolve-brief.py`'s legacy-prose glob, so `/milestone-pipeline`
> still resolves every id below.
>
> **Not `complete` in state.json:** `lean-repl-observability-m1` → `rectify-running`
> ⚠️ `state.json` reads `rectify-running`, but the full close-out triple landed (`8844bd4` feat → `101bd4f` rect → `54232e0` finalize). The finalize commit added the state file without flipping the phase. Left as-is deliberately — it is another session's artifact to correct, not this archive pass's.
> **Last commit touching this track:** `54232e0 chore(notes): finalize lean-repl-observability-m1`


A one-off prose brief the `/milestone-pipeline` command resolves via its legacy
`plans/*.md` fallback (see `.claude/scripts/milestone-pipeline-resolve-brief.py`).
It is deliberately NOT part of any `roadmap/1` thesis — it is a single,
cross-cutting observability milestone pulled out of R3's warm-pool track so it
can ship ahead of R3's trust gate. Run it with
`/milestone-pipeline lean-repl-observability-m1` from a session rooted in this
repo.

### lean-repl-observability-m1 — Lean REPL env-tree + worker-age telemetry gauge

**Kind:** milestone (standalone / observability)
**Created:** 2026-07-25
**Relates to:** R3 verification-contract m7 (warm pools) —
[`.claude/roadmap-briefs/R3-verification-contract.md`](../.claude/roadmap-briefs/R3-verification-contract.md);
resolves the "no in-product signal" half of **F7** from the
`lean-verify-continuation-m1` adversary critique
([`critique-adversary.md`](../.claude/notes/milestones/lean-verify-continuation-m1/critique-adversary.md)).

#### Why this is standalone (and why now)

F7 is unbounded in-process growth of the Lean REPL's immutable environment-snapshot
tree: every REPL command records a snapshot into an append-only array (env id =
array index), freed only by the timeout kill+respawn or an operator restart
(~3.1 GB RSS for a Mathlib-resident process). Growth model + the pinned-source
census are in
[`.claude/docs/lean-sandbox-design.md`](../.claude/docs/lean-sandbox-design.md)
§ "Environment-snapshot accumulation (F7)".

The **real fix** — bounding the tree by recycling pooled workers on a
snapshot-count / age budget, optionally `pickle`-migrating the hot env across a
recycle — belongs to R3 **m7**, which is gated behind R3's trust gate (m2–m5).
This milestone is the one piece safely pullable *ahead* of that gate: **read-only
telemetry**. It changes no REPL lifecycle, invalidates no continuation token, and
touches no MCP tool surface — it only lets the operator *see* the growth (and
gives m7's recycling policy a signal to act on). Today there is no in-product
signal at all: the Lean REPL is a **separate child process**, so its growth is
invisible to the arXMCP server's own `/metrics` counters.

#### Scope

1. **Harness (`server/lean_repl.py`).** `LeanRepl` tracks, per spawn/generation:
   - a monotonic **env-snapshot proxy** — either the count of successful `query`
     round-trips this generation, or (tighter) the max REPL `env` / `proofState`
     id observed (both are faithful proxies for `cmdStates.size` /
     `proofStates.size`, since ids are append-only array indices); and
   - the **spawn time** (`time.monotonic()`), for a worker-age reading.
   Exposed as read-only properties. Both reset naturally on a kill+respawn (a new
   `LeanRepl` instance / new `generation`), which is exactly the semantics we want
   — the gauge should drop when the tree is actually freed.
2. **Metrics (`server/metrics.py`).** Add scrape-time-refreshed **gauges**
   (mirroring `CACHE_BYTES_GAUGE`; note `prometheus_client` strips `_total` from
   *counters*, so gauges are correct here):
   - `arxmcp_lean_repl_env_snapshots` — live env-snapshot proxy for the running
     REPL (0 when disabled/absent).
   - `arxmcp_lean_repl_age_seconds` — seconds since the current REPL spawned
     (0 when absent).
   - **(optional, platform-gated)** `arxmcp_lean_repl_rss_bytes` — RSS of the REPL
     *child* process, the metric that directly reflects the ~3.1 GB concern. Only
     if child-RSS is resolvable without a heavy new dependency (e.g. `/proc` on
     Linux, or `psutil` **iff** already available); otherwise omit and record it
     as a deferred sub-item. The count + age gauges are the portable floor.
   - a `reset_lean_repl_metrics_for_tests()` helper, mirroring the other
     `reset_*_for_tests` functions.
3. **Scrape hook (`server/health.py`).** Refresh the gauges at `/metrics` scrape
   time from the `Resources.lean_repl` singleton (mirroring
   `refresh_cache_metrics` / `refresh_sentinel_metrics`). A `None` REPL (disabled
   path) sets the gauges to 0 — never a missing series, never a crash.
4. **Docs.** Replace the "no in-product signal today" caveat in
   `.claude/docs/lean-sandbox-design.md` § F7 with a pointer to these gauges and a
   short restart-threshold ops note. Surfacing the snapshot/age reading on
   `/status` and the daily ops report is **optional** (do it only if it drops out
   cheaply).

#### Acceptance criteria

1. Given `ARXMCP_ENABLE_LEAN=true` and a running REPL, when N successful
   `lean_verify` cmd-mode calls have been made, then `/metrics` exposes
   `arxmcp_lean_repl_env_snapshots` as monotonically non-decreasing across those
   calls, and `arxmcp_lean_repl_age_seconds` as positive and increasing.
2. Given a per-query-timeout kill+respawn, when the REPL respawns, then the
   snapshot-count gauge drops toward 0 for the new generation (reflecting the
   freed tree) and the age gauge resets — verified by a test that forces a
   respawn.
3. Given `ARXMCP_ENABLE_LEAN` unset (REPL disabled), when `/metrics` is scraped,
   then the gauges are present and read 0 — no crash, no missing series
   (consistent with the graceful-unavailable path).
4. Given the MCP `tools/list` surface, when the schema hash is checked, then
   `EXPECTED_TOOL_SCHEMA_SHA256` **and** `EXPECTED_BP1_SHA256` are **unchanged**
   — `/metrics` is not the MCP tool surface and `lean_verify`'s input schema /
   result schema are untouched.
5. (Only if the optional RSS gauge ships) Given a platform where child-process
   RSS is resolvable, when the REPL child is running, then
   `arxmcp_lean_repl_rss_bytes` reads positive; given an unresolvable platform,
   then the gauge is absent or 0 with no error and no new hard dependency.
6. Given the full suite, when `make test` runs, then it is green (ruff clean +
   pytest), with new tests covering the snapshot-proxy increment, the respawn
   reset, the disabled-path 0 values, and the scrape hook (mirroring the existing
   `tests/test_server_metrics.py` pattern).
7. Given `.claude/docs/lean-sandbox-design.md` § F7, when the change lands, then
   the "no in-product signal today" caveat is replaced by a pointer to the new
   gauges plus a restart-threshold ops note.

#### Out of scope

- **Any env-tree bounding** — eviction, worker recycling, respawn *policy*,
  pickle-migration. That is R3 **m7** (gated behind the trust gate); this
  milestone is telemetry ONLY and changes no REPL lifecycle behavior and no
  continuation-token semantics.
- No new MCP tool, no MCP tool input-schema change, no change to `lean_verify`
  behavior or its result schema.
- No child-process **memory cap** (the separate deferred POSIX `RLIMIT_AS` /
  Windows Job-Object work — `lean-sandbox-design.md` "Memory cap" row).
- No alerting rules wired (the gauge is exposed; alert-rule authoring in
  `infra/`/ops is a later follow-up). If the implementer adds an alert rule, the
  `milestone-infra-safety-critic` fires on the `infra/` touch.

#### Dependencies

- **None blocking.** Deliberately independent of R3's trust gate (m2–m5): it adds
  no untrusted-execution surface. Requires only the shipped `ARXMCP_ENABLE_LEAN`
  REPL path (verification-feedback-m2+).
- **Complements R3 m7:** provides the operator signal m7's recycling policy will
  act on; m7 consumes/extends these gauges rather than reinventing them.

#### Complexity

**S (~1 day).** ~3–4 files: `server/lean_repl.py` (snapshot proxy + spawn time),
`server/metrics.py` (gauges + reset helper), `server/health.py` (scrape hook),
tests, plus the `lean-sandbox-design.md` § F7 pointer. Small blast radius; **no
schema/hash cascade** (no `TOOL_SCHEMA_VERSION` bump, no `server/schemas/*`
change).

#### Data-plane note (CLAUDE.md §4.8)

Read-only operational telemetry — same class as the retrieval-cache byte gauges.
Not a corpus write, not per-agent memory. Within the data-plane boundary.

#### Notes for the implementer

- Run the 4-phase pipeline (CLAUDE.md §4.2 — touches >3 files + adds tests):
  `/milestone-pipeline lean-repl-observability-m1`. Expect the `feat` + `rect` +
  `chore` commit triple. Always-on `milestone-adversary-critic` plus the repo
  overlay `milestone-arxmcp-critic`; `milestone-infra-safety-critic` fires only
  if `infra/` / `Makefile` paths are touched (they should not be here).
- Keep the optional RSS gauge genuinely optional: do **not** add `psutil` as a
  hard runtime dependency for it. Ship the portable count + age gauges; record
  the RSS gauge as a deferred sub-item if child-RSS isn't cheaply resolvable on
  the Windows tier-1 host.
- Follow the `arxmcp_<subsystem>_<metric>` naming convention already in
  `server/metrics.py`, and the scrape-time-refresh pattern (gauges set from the
  singleton in `server/health.py`, never incremented on the hot path).

---
milestone_id: "lean-repl-observability-m1"
researcher_role: "general"
external_writes_required:
  - "git push origin main — lands the feat/rect/chore commit triple on main; USER-GATED at the Phase-4 boundary (CLAUDE.md §4.4, re-ask each time). No other external write is in scope for this milestone."
sources:
  - url: "https://prometheus.github.io/client_python/instrumenting/gauge/"
    sha256: "2e9a3837e90577a632e00cd207ffd21c718dd38d14ad417b83ef2c11d843afd9"
    takeaway: "Official prometheus_client docs: \"A Gauge tracks a value that can go up and down. Use it for things you sample at a point in time\" — exactly the env-snapshot-proxy and worker-age semantics this milestone needs, not a Counter."
injection_attempts: 0
---

# Research brief (general) — lean-repl-observability-m1

## External sources

Only one external fetch was warranted: this milestone mirrors an established
in-repo `prometheus_client` pattern rather than adopting a new library, so I
pinned the official Gauge semantics doc instead of doing broader vendor
research. `pip install prometheus-client` / PyPI details were already
resolved locally (pinned versions below) and needed no fetch.

- `https://prometheus.github.io/client_python/instrumenting/gauge/` (sha256
  above) — confirms Gauge is documented for exactly "things you sample at a
  point in time — active connections, queue depth, memory usage,
  temperature," which is the env-snapshot-proxy / worker-age / RSS use case
  here, not a monotonic Counter.
- (Not separately pinned) `https://raw.githubusercontent.com/prometheus/client_python/master/README.md`
  — checked and found to be a thin stub that only redirects to the docs site
  above; no independent content worth citing.

## 1. prometheus_client usage — Gauge vs Counter, version, pattern to copy

**Gauges are correct, not Counters.** Both proposed metrics are
scrape-time-refreshed *current-state* readings that must be able to reset to
(near-)zero when a new `LeanRepl` generation spawns — that is precisely
Gauge semantics ("value that can go up **and down**"; a Counter can only
increase, and `prometheus_client` strips a Counter's registered `_total`
suffix at scrape time, which the milestone brief itself already correctly
notes as a reason gauges — not counters — are used here). The repo's own
`server/metrics.py` docstring makes the identical point about
`LATEXML_DRIFT_DETECTED_GAUGE` vs `LATEXML_DRIFT_DETECTED_COUNTER`
(`server/metrics.py:193-198`): "prometheus_client strips the conventional
`_total` suffix when assigning the time-series name... We use
`arxmcp_latexml_drift_fixtures` here to avoid the collision."

**Version.** `pyproject.toml:106` pins `"prometheus-client>=0.20"`;
`uv.lock:1274-1276` resolves the installed version to **`0.25.0`**. No
version bump or new pin is needed — `Gauge` has had a stable API across this
entire range.

**The pattern to copy is `refresh_cache_metrics`, confirmed exactly as the
brief states.** Concretely:

- Metric definition style: `CACHE_BYTES_GAUGE` (`server/metrics.py:103-109`)
  — a `Gauge` with a docstring stating "Refreshed at scrape time (NOT
  continuously). Operational telemetry, not a hard limit." The two required
  Lean gauges (`arxmcp_lean_repl_env_snapshots`, `arxmcp_lean_repl_age_seconds`)
  should be defined the same way, unlabeled (no per-instance label needed —
  there is exactly one REPL singleton, mirroring `PROCESS_START_TIME_GAUGE`
  at `server/health.py:150-154`, which is also a bare scalar gauge).
- Refresh-function style: `refresh_cache_metrics(cache: RetrievalCache | None)`
  (`server/metrics.py:332-353`) — takes the singleton (or `None`), is a
  no-op on `None`, and is documented as "intentionally cheap... any cost
  would be borne on every Prometheus scrape." A new
  `refresh_lean_repl_metrics(lean_repl: LeanRepl | None)` should follow this
  exact shape: `None` → set both gauges to `0.0` and return; otherwise read
  the two read-only properties and `.set(...)` them.
- Reset-for-tests style: `reset_cache_metrics_for_tests()`
  (`server/metrics.py:369-383`) using the shared `_reset_child` helper
  (`server/metrics.py:356-366`) which prefers the public `Counter.reset()` /
  direct `Gauge.set(0)` and only falls back to the documented-private
  `._value` accessor. A `reset_lean_repl_metrics_for_tests()` should reuse
  `_reset_child` or just `.set(0)` directly (gauges have no labels here, so
  the private-accessor fallback path is not even needed).
- **Wiring into the scrape hook is at `server/health.py`, not
  `server/metrics.py`.** The master hook is
  `refresh_metrics_from_singleton_state(resources: Resources)`
  (`server/health.py:545-626`), called from exactly one place:
  `server/main.py`'s `/metrics` ASGI mount wrapper
  (`server/main.py:809-821` — `app.mount("/metrics", metrics_wrapper)`,
  where `metrics_wrapper` calls
  `refresh_metrics_from_singleton_state(resources)` immediately before
  delegating to `prometheus_client.make_asgi_app()`). This *is* the
  scrape-time trigger — it fires once per `/metrics` GET, never on the hot
  request path. The existing call at `server/health.py:595-597`
  (`from server.metrics import refresh_cache_metrics; refresh_cache_metrics(...)`)
  is the exact model: add a symmetric
  `refresh_lean_repl_metrics(getattr(resources, "lean_repl", None))` call
  alongside it.
- **The `Resources.lean_repl` singleton is `None` on the disabled path**,
  confirmed at `server/resources.py:989` (constructed with `lean_repl=None`)
  and only overwritten at `server/resources.py:1016-1023` inside
  `if config.enable_lean:`. So `getattr(resources, "lean_repl", None)` (same
  defensive-getattr idiom already used for `cache` at
  `server/health.py:597` and `startup_unindexed_rows` at
  `server/health.py:579`) gives exactly the "0 when disabled/absent, never a
  missing series, never a crash" contract the brief's AC3 requires.
- **What the harness needs to expose (not yet present).** `LeanRepl`
  currently exposes only `is_running` and `generation` as read-only
  properties (`server/lean_repl.py:278-293`); there is no snapshot-count or
  spawn-time tracking yet. The constructor (`server/lean_repl.py:111-139`)
  already threads a per-instance `_generation` token that resets naturally
  on respawn (a brand-new `LeanRepl` object) — the new snapshot-proxy
  counter and `time.monotonic()` spawn timestamp are natural siblings of
  that same per-instance state and get the same free "resets on respawn"
  property the brief's AC2 depends on. (This is squarely in `explore`/
  `implement` territory, not `general` — noted here only because it is load
  bearing for where the scrape-hook reads from.)

## 2. Child-process RSS (the optional gauge) — recommendation: defer

**`psutil` is NOT a dependency today.** Verified two ways:
`grep -i "psutil" pyproject.toml` and a full-repo grep of `uv.lock` both
return zero matches; a repo-wide grep across `*.py, *.toml, *.txt, *.cfg,
*.ini` for the literal `psutil` also returns **zero files** — it is not
vendored, not optionally imported anywhere, not referenced in any comment.
Adding it now would be a genuinely new hard dependency, which the brief
explicitly forbids ("do NOT add `psutil` as a hard runtime dependency").

**No stdlib/`/proc` shortcut exists on this Windows tier-1 host either.**
Two candidate stdlib paths, both dead ends here:
- `resource.getrusage(resource.RUSAGE_CHILDREN)` — POSIX-only (the repo
  already has a documented precedent for this exact
  import-fails-on-Windows shape: `server/lean_repl.py:48-51`,
  `try: import resource as _resource / except ImportError`). Even on POSIX
  it only aggregates **terminated** children's peak RSS, not a **live**
  child's current RSS — architecturally wrong for "read the running REPL's
  RSS right now."
- Reading `/proc/<pid>/status` — Linux-only, and this workstation is
  Windows (`sys.platform == "win32"`; confirmed in the environment and by
  the existing `sys.platform != "win32"` / `sys.platform == "win32"` guards
  already sprinkled through `server/lean_repl.py:200-219`). No `/proc`
  filesystem exists on Windows.
- The only Windows-native path is `ctypes.windll.psapi.GetProcessMemoryInfo`
  (or the higher-level `kernel32.OpenProcess` + `psapi.GetProcessMemoryInfo`
  combo). **Zero precedent for this in the codebase** — a repo-wide grep for
  `ctypes|windll|GetProcessMemoryInfo` returns no hits at all (the one
  `/proc/` hit found, in `tools/arxiv_fetch.py:532-537`, is an unrelated
  LaTeXML sandbox bind-mount comment, not a memory-reading path). Building
  this from scratch for one optional gauge is exactly the kind of new,
  untested, platform-specific surface the brief's "cheaply resolvable"
  bar is meant to exclude.

**Recommendation: ship the portable count + age gauges now; record the RSS
gauge as a deferred sub-item.** Concretely:
- `arxmcp_lean_repl_env_snapshots` and `arxmcp_lean_repl_age_seconds` are
  both derivable from state the harness already owns in-process (query
  count / max env-id, and `time.monotonic()` at construction) — zero new
  dependencies, zero platform gating needed.
- `arxmcp_lean_repl_rss_bytes` should be **omitted from this milestone**.
  Record it in the implementation summary / docs update as: "deferred —
  needs either `psutil` (a new hard dependency, against this milestone's
  constraint) or a Windows-native `ctypes` RSS reader (no precedent, real
  implementation risk for one optional gauge); revisit if/when R3 m7's
  recycling policy needs an RSS-based recycle trigger, at which point the
  dependency trade-off can be made once, deliberately, for that milestone."
  This matches AC5's "given an unresolvable platform, then the gauge is
  absent... no new hard dependency" — the honest reading of AC5 on *this*
  host is "absent," not "positive."
- **If a future milestone pursues it anyway, the pid access path is
  already there:** `LeanRepl.__init__` stores the `asyncio.subprocess.Process`
  handle as `self._proc` (`server/lean_repl.py:111-118`), and `proc.pid` is
  already read once today for a log line at spawn time
  (`server/lean_repl.py:241-250`, `logger.info("...pid=%s...", proc.pid, ...)`).
  There is no public `pid` property yet — adding one (mirroring the
  `is_running` / `generation` property pattern at
  `server/lean_repl.py:278-293`) would be the one-line prerequisite for any
  later RSS reader, whether `psutil.Process(lean_repl.pid).memory_info().rss`
  or a platform-specific reader.

## 3. No-schema-impact proof

Both pinned hashes are computed from data structures that never touch
`server.metrics` or `server.health`'s Gauge/Counter objects — confirmed by
reading the exact hash-construction code, not just the constant names:

- **`EXPECTED_TOOL_SCHEMA_SHA256`** is defined at
  `tests/test_server_tool_schema.py:94-96` and computed by
  `compute_tool_schema_hash` → `_serialize_tools`
  (`tests/test_server_tool_schema.py:158-190`), which does:
  `ListToolsResult(tools=tools).model_dump(mode="json", by_alias=True,
  exclude_none=True)` then canonical-JSON + sha256. `tools` here is the
  FastMCP-registered tool list obtained via `mcp_server.list_tools()`
  (`tests/test_server_tool_schema.py:143`) — i.e. purely
  `server.tools.ALL_TOOLS` registration metadata (name, description, input
  schema, per-tool `_meta`). Nothing in that call graph imports
  `server.metrics` or `server.health`.
- **`EXPECTED_BP1_SHA256`** does **not** live in `server/prompts.py` — I
  want to flag this precisely because the dispatch brief assumed it did.
  `server/prompts.py` holds only `SYSTEM_PROMPT` + `ROLE_PREFIXES` + the
  BP1/BP2 breakpoint-contract docstring (confirmed by reading
  `server/prompts.py:1-40`; grepping that file for the literal
  `EXPECTED_BP1_SHA256` returns **zero matches**). The actual pinned
  constant and its hash function live in **`tests/test_prompts.py`**: the
  hash function `_bp1_hash(req)` is at `tests/test_prompts.py:506-513` —
  `bp1 = {"system": req["system"], "tools": req["tools"]}` then
  canonical-JSON + sha256 — and the pinned value is asserted inside
  `TestBP1ByteIdentityAcrossFanout.test_all_four_roles_share_one_bp1_hash`
  at `tests/test_prompts.py:664-681`. `req["tools"]` there is
  `_live_tools_payload()` (`tests/test_prompts.py:487`), the
  Anthropic-shaped `{name, description, input_schema}` projection of the
  same `ALL_TOOLS` registration — again disjoint from the Prometheus
  registry. `server/tools.py:150-192`'s version-history comment block
  (documenting `TOOL_SCHEMA_VERSION` v16→v20) independently corroborates
  the rule in its own words: "BP1 hashes `{name, description}` only"
  (`server/tools.py:157, 165, 176-177, 184-185`).
- **Structural proof that `/metrics` cannot reach either hash:** `/metrics`
  is mounted as a wholly separate ASGI sub-application —
  `prometheus_client.make_asgi_app()` wrapped by `metrics_wrapper` and
  mounted via `app.mount("/metrics", metrics_wrapper)`
  (`server/main.py:809-821`) — a different code path from the MCP
  `tools/list` handler entirely. Adding `Gauge` objects to
  `server/metrics.py` (or a refresh call in `server/health.py`) changes
  bytes served at `GET /metrics`; it changes zero bytes of what
  `mcp_server.list_tools()` returns, which is the only input to both
  hashes. AC4 ("both hashes unchanged") is not just plausible but
  structurally guaranteed by this separation, independent of what values
  the new gauges hold.

## 4. external_writes_required — enumerated verbatim

This milestone runs in a git worktree at
`.claude/worktrees/laughing-goldstine-b8ea4f` on branch
`claude/laughing-goldstine-b8ea4f`. I audited the entire in-scope file set
(`server/lean_repl.py`, `server/metrics.py`, `server/health.py`,
`.claude/docs/lean-sandbox-design.md`, plus new test files) for anything
that mutates state outside the local repo, and checked `git remote -v`
(`origin` → `git@github.com:chris-dare-dev/arXMCP.git`) and `.git/hooks`
(no active hooks beyond the stock `*.sample` files — nothing fires on
commit/push that could trigger a hidden external write).

**Exactly one external write applies, as expected:**

- `git push origin main` (or the orchestrator's equivalent land-on-main
  step) — lands the milestone's `feat` + `rect` + `chore` commit triple.
  **USER-GATED**: per CLAUDE.md §4.4, "Push is per-event authorization. A
  user 'yes, push' once does NOT authorize future pushes. Re-ask each
  time." This is a Phase-4 boundary action for the orchestrator, not
  something any Phase-1/2/3 agent (including this one) may perform.

**Confirmed absent** (all checked directly against the milestone's actual
scope, not assumed):
- No network calls of any kind. The Lean REPL subprocess itself is a local
  `lake exe repl` process (`server/lean_repl.py:221-235`,
  `asyncio.create_subprocess_exec`) — no HTTP client, no socket, nothing
  that reaches arXiv / OpenAlex / INSPIRE-HEP / any external API. The new
  telemetry reads only in-process counters, `time.monotonic()`, and (if
  ever pursued) a local `/proc` or Windows API read of the REPL's own pid —
  never a network round-trip.
  <br>Note: this milestone changes nothing about the `ARXMCP_CONTACT_EMAIL`-
  bearing ingest tools (`tools/arxiv_fetch.py`,
  `tools/notebook_fetch.py`, etc.) — those are out of scope and untouched.
- No deploys, no container builds/pushes, no `infra/`/`Makefile` changes
  (the brief's own "Out of scope" section rules this out, and the
  `milestone-infra-safety-critic` fires only if those paths are touched —
  they should not be, per my file audit).
- No package publishes (no `pyproject.toml` version bump implied or
  needed; `prometheus-client` is already a satisfied dependency at
  `>=0.20`, resolved to `0.25.0`).
- No mutating external API calls of any kind — this is a pure read-only
  telemetry addition over already-in-process state.

## 5. Data-plane boundary (CLAUDE.md §4.8)

Read-only operational telemetry is squarely inside the data-plane boundary,
confirmed against the actual rule text (not paraphrased):

- **Rule 2** explicitly enumerates the category this falls into:
  "Server-internal operational writes (retrieval-cache SQLite, logs,
  **metrics**, ingest-status transitions) are implementation detail, not
  corpus writes." The two new gauges are metrics in exactly this sense —
  they persist nothing to the corpus, nothing to LanceDB, nothing to any
  notebook state; they are process-local `prometheus_client` registry
  entries recomputed at every scrape from harness-local counters.
- **Rule 1**'s carve-out — "Observability labeling of a *calling* agent's
  role and per-session budget counters are not agent memory" — covers the
  adjacent worry directly: these gauges label the **Lean REPL subprocess's**
  own lifecycle (its age, its snapshot growth), not any calling agent's
  conversation state, so there is no agent-memory concern either.
  `lean_verify` itself already "computes; it never persists corpus-visible
  state" (rule 2, parenthetical) — the new gauges observe that same
  compute-only subprocess from the outside, adding no persistence.
  This is the identical class as the already-shipped
  `CACHE_BYTES_GAUGE` / `PROCESS_START_TIME_GAUGE` / `RESOURCE_WARM_GAUGE`
  family — no new boundary question is raised.

## Acceptance criteria the implementer must meet

(Traced 1:1 to `plans/lean-repl-observability.md`'s 7 ACs; research-informed
notes attached where I found something concrete.)

1. With `ARXMCP_ENABLE_LEAN=true` and a live REPL, `arxmcp_lean_repl_env_snapshots`
   is monotonically non-decreasing across successful `lean_verify` cmd-mode
   calls, and `arxmcp_lean_repl_age_seconds` is positive and increasing. —
   Both must be sourced from new per-instance state on `LeanRepl` (there is
   none today beyond `generation`/`is_running`); the scrape hook must call
   `.set(...)`, never `.inc(...)` (these are point-in-time samples, not
   monotonic totals at the metric-family level, even though the snapshot
   count happens to only grow within one generation).
2. On a per-query-timeout kill+respawn, the snapshot gauge drops toward 0
   for the new generation and the age gauge resets. — Falls out for free if
   the new counters live on the `LeanRepl` instance itself (a new instance
   on respawn), exactly like `generation` already does
   (`server/lean_repl.py:121-135`).
3. With `ARXMCP_ENABLE_LEAN` unset, `/metrics` exposes both gauges at 0 —
   no crash, no missing series. — `getattr(resources, "lean_repl", None)` →
   `None` branch must `.set(0.0)` both gauges unconditionally (mirrors the
   `cache is None` early-return already in `refresh_cache_metrics`,
   `server/metrics.py:347-348`, adjusted to explicitly zero rather than
   no-op, since AC3 requires the series to be *present* at 0, not merely
   unset-and-therefore-absent).
4. `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` unchanged. —
   Structurally guaranteed per §3 above; no action needed beyond not
   touching `server/tools.py`'s `ALL_TOOLS` / `TOOL_SCHEMA_VERSION` or
   `server/prompts.py`'s `SYSTEM_PROMPT` / `ROLE_PREFIXES`.
5. (Only if RSS ships) positive RSS on a resolvable platform, absent/0 with
   no error and no new hard dependency otherwise. — Per §2, the correct
   choice on this host is to not ship it at all this milestone; the
   "absent... no new hard dependency" branch is what applies here.
6. `make test` green (ruff + pytest), with new tests covering the
   snapshot-proxy increment, respawn reset, disabled-path 0 values, and the
   scrape hook — mirroring `tests/test_server_metrics.py`'s existing
   pattern: a `reset_lean_repl_metrics_for_tests` fixture akin to
   `reset_all_metrics` (`tests/test_server_metrics.py:125-146`), and an
   integration assertion against the rendered Prometheus text via
   `prometheus_client.parser.text_string_to_metric_families` (already
   imported at `tests/test_server_metrics.py:32` for exactly this style of
   check).
7. `.claude/docs/lean-sandbox-design.md` § F7's "no in-product signal
   today" caveat (currently at lines 99-105, ending "...pullable ahead of
   R3 m7") is replaced with a pointer to the new gauges + a restart-
   threshold ops note. — Straightforward doc edit once the gauge names are
   final; no other doc in the repo needs updating for this milestone.

## Risks and open questions

1. **Choosing the snapshot proxy (query-round-trip count vs max env/proofState
   id) is an implementation decision this brief doesn't need to resolve, but
   it changes the AC1 test's exact shape.** The milestone brief offers both
   as valid proxies ("either the count of successful `query` round-trips
   this generation, or (tighter) the max REPL `env` / `proofState` id
   observed"). The tighter option requires parsing the REPL's JSON response
   for an `env`/`proofState` integer field on every call (which
   `lean_verify`'s handler almost certainly already does, to hand tokens
   back to the caller) — reusing that parse is cheaper than adding a second
   independent counter, but it does mean the gauge should be named/scoped
   as "id observed," which can legitimately not increase on a call that
   fails before an env is minted (e.g. a parse error), whereas a bare
   call-counter always increases. Pick one and document which in the
   implementation summary so the AC1 "monotonically non-decreasing" test
   asserts the right thing.
2. **The `LeanRepl` harness has zero existing tests exercising a real
   respawn today** (all current tests almost certainly construct one
   `LeanRepl` per test with a fake subprocess) — AC2's "verified by a test
   that forces a respawn" likely needs a new fake/stub subprocess fixture
   that supports being torn down and re-constructed mid-test, not just
   reused from an existing fixture. Budget for this as new test
   infrastructure, not a one-line addition.
3. **`server/metrics.py` vs `server/observability/metrics.py` — the brief
   picks the former, and that's consistent with existing precedent, but
   don't be surprised there are two metrics modules.** `server/metrics.py`
   docstring documents itself as the legacy home "kept for backwards
   compatibility with existing tests" (E08_S03/E10_S04/E11_S04);
   `server/observability/metrics.py` is the newer E14_S01 home for
   per-request/embedder/reranker families. Both register on the same
   default `prometheus_client.REGISTRY`, so either would work mechanically
   — the brief's explicit instruction to mirror `CACHE_BYTES_GAUGE` in
   `server/metrics.py` is the right call for consistency with the sibling
   scrape-hook-refreshed gauges already there (`CORPUS_UNINDEXED_ROWS`,
   `LATEXML_DRIFT_DETECTED_GAUGE`, etc.), and I found nothing that argues
   for the other module.
4. **The optional `/status` / daily-ops-report surfacing mentioned in the
   brief's scope item 4 ("Surfacing the snapshot/age reading on `/status`
   and the daily ops report is optional") has no natural cheap hook.**
   `compute_health_status` (`server/health.py:314-506`) already threads
   `resources` through and could add a `lean_repl:snapshots` check
   trivially, but the daily ops report is a separate cron artifact
   (`var/arxmcp/ops/ingest-summary.json`-style) with no existing Lean-aware
   producer — wiring that in is realistically a follow-up, not a "drops out
   cheaply" item. Recommend the implementer treat `/status` as the only
   "if cheap" candidate and skip the ops-report half without treating it as
   a scope miss.
5. **No test today constructs a real `asyncio.subprocess.Process` handle
   with a controllable `pid`** for a future RSS-gauge test — if a later
   milestone (R3 m7 or a dedicated follow-up) does pick up `psutil` or a
   `ctypes` reader, it will need a new fixture that exposes a real (or
   realistically-faked) OS-level process, since today's `LeanRepl` tests
   almost certainly stub `_proc` with a bare mock/`SimpleNamespace`. Not
   this milestone's problem, but worth flagging so the deferred-sub-item
   note in the docs update doesn't understate the follow-up cost.

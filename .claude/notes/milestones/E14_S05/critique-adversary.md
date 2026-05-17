# Critique — E14_S05

**Critic:** adversary
**Generated:** 2026-05-16T04:30:00Z
**Commit range:** 6fca689..c03cfae
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: 4 detection paths land, the test surface and
  alerts file pass, but two correctness bugs and one doc-layout violation
  must close before this milestone is "done."
- Finding counts: 2 HIGH, 4 MEDIUM, 4 LOW. No CRITICAL — no data-loss or
  security regression was found; the bugs are correctness on a degraded
  path and operator-facing path drift, not core-invariant breakage.
- Highest-risk file is `server/handlers/search.py:122-161` — Tier-1 / Tier-2
  cache hits short-circuit BEFORE the `degraded` flag is computed, so cached
  payloads served while the server is degraded MISS the `degraded=true` tag
  the orchestrator depends on.
- Second-highest: `ops/cron/arxmcp-delta.sh:68` hardcodes
  `${REPO_ROOT}/var/arxmcp/ops/ingest-paused` while
  `tools/ingest_sentinel._resolve_sentinel_path` honors `ARXMCP_DATA_DIR` —
  the cron and the Python module look at DIFFERENT files when the env var
  is set, defeating the cron-side defense.
- Cross-axis pattern: the brief AC "Synthetic LanceDB corruption → degraded
  mode" is interpreted as "monkeypatch the open function to raise"; no real
  on-disk corrupt fragment ever crosses the test surface. The implementation
  summary acknowledges this gap and defers to a "manual smoke step." Acceptable
  at v1 but worth flagging as a regression-guard hole.
- Doc-layout violation: `docs/ops/failure-modes.md` is NEW and is NOT linked
  from the root `README.md`. CLAUDE.md §1 says `docs/` is ONLY for
  user-facing docs referenced by root README; everything else goes under
  `.claude/`. The runbook either needs a README link OR a move to `.claude/`.
- Cache byte-stability: `TOOL_SCHEMA_VERSION` stays at 6, no changes to
  `server/tools.py` or `ALL_TOOLS`; BP1 byte-stability is preserved at the
  schema layer. The conditional `degraded` keys in `structuredContent` are
  response-content, NOT schema — `tools/list` response is unaffected.
- "What was done well" section is substantive; the implementation is
  thoughtful (hysteresis bands, WARN-once log, two-phase atomic write,
  separate counter for hosted-fallback events). The bugs below are about
  edge cases, not the happy path.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC) |
| LOW | style, naming, micro-perf | defer to `deferred_findings` |

## Findings

### F1 — Cache short-circuits before `degraded` flag is computed

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/handlers/search.py:122-161
- **What:** The Tier-1 and Tier-2 cache lookup paths return the cached
  payload BEFORE the `degraded_reasons` list at line 203-220 is computed.
  A payload written while the server was healthy will be served unchanged
  while the server is degraded; conversely, a payload written while the
  hosted embedder was failing will keep `degraded=true` after the hosted
  embedder recovers. The cache key (E08_S03) does not include the
  `degraded` axis (see `server/corpus.py:69-80` cache key formula —
  `model_name + model_version + canonical_form(query) + corpus_version`).
- **Why it matters:** The brief's failure-mode contract says results
  served from a degraded path MUST be tagged `degraded=true` so the
  orchestrator can deprioritize them. The Tier-1/Tier-2 hit path silently
  defeats that contract. For the LanceDB-corruption case the server is
  PINNED at the fallback version for its entire lifetime (no auto-recovery
  per `Resources.startup` discipline), so on a degraded-startup process
  every Tier-1 hit from a prior healthy process returns un-flagged stale
  rows.
- **Proposed fix:** After a cache hit, mutate the returned payload to
  reflect the CURRENT degraded state — add the `degraded_reasons` list
  to `structured` before returning the `CallToolResult`. Two-line fix at
  the two hit sites. The cached payload is the search RESULT (rows); the
  degraded flag is a server-state attribute that should be re-stamped on
  every response. Alternatively, include `degraded_reasons` in the cache
  key — but that would balloon the key space across recovery transitions
  and re-warm cost on flap.
- **Regression guard:** New test
  `tests/test_failure_modes.py::TestHostedEmbedderFallback::test_cached_payload_retagged_on_degraded_server`
  — populate Tier-1 with a healthy payload, flip `r.degraded` to a
  `DegradedState`, call the handler again, assert the cached path returns
  `degraded=True`.

### F2 — Cron sentinel path drifts from Python sentinel path

- **Severity:** HIGH
- **Source:** adversary
- **File:** ops/cron/arxmcp-delta.sh:68
- **What:** The bash cron wrapper hardcodes
  `PAUSE_FLAG="${REPO_ROOT}/var/arxmcp/ops/ingest-paused"`. The Python
  module `tools/ingest_sentinel.py:98-107` resolves the sentinel path via
  `_resolve_sentinel_path` which honors `ARXMCP_DATA_DIR`. When the
  operator runs with `ARXMCP_DATA_DIR=/var/lib/arxmcp` (the documented
  production pattern per `server/config.py:188-192`), the cron writes
  the sentinel to `/var/lib/arxmcp/ops/ingest-paused` (because the
  server's `refresh_disk_free_metric` reads `config.data_dir`) but the
  cron checks `${REPO_ROOT}/var/arxmcp/ops/ingest-paused`. The cron
  proceeds because its hardcoded path doesn't exist — the pause is
  defeated.
- **Why it matters:** This is the entire point of the cron sentinel
  check — to short-circuit a delta run when ingest is paused. A
  production operator (the documented use case for `ARXMCP_DATA_DIR`)
  gets a silently-broken safety check. The Python `_cli` path (line 773
  of `ingest/oai_delta.py`) does honor the env var, so manual
  invocations are fine — but the cron is the load-bearing trigger.
- **Proposed fix:** Resolve the path in bash using the same precedence
  as `_resolve_sentinel_path`:
  ```bash
  PAUSE_FLAG="${ARXMCP_DATA_DIR:-${REPO_ROOT}/var/arxmcp}/ops/ingest-paused"
  ```
  Three-line change; add a test that captures this drift by setting
  `ARXMCP_DATA_DIR` and asserting the cron honors it.
- **Regression guard:** New shell-level test (or contract test in
  `tests/test_failure_modes.py`) that scrapes `ops/cron/arxmcp-delta.sh`
  and asserts `ARXMCP_DATA_DIR` appears in the PAUSE_FLAG expression.

### F3 — `docs/ops/failure-modes.md` violates the doc-placement rule

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/ops/failure-modes.md (the file is new in this commit)
- **What:** CLAUDE.md §1 says: "`docs/` — ONLY user-facing documentation
  referenced by the root README.md. Today: just `docs/install.md`." This
  milestone adds `docs/ops/failure-modes.md` (272 lines) but does NOT
  add a link from `README.md`. The README's "Operator runbooks" table at
  line 63-73 lists 7 prior runbooks but does NOT include `failure-modes.md`.
- **Why it matters:** The rule is load-bearing per CLAUDE.md §1: "Don't
  bring back `ROADMAP.md` at the root — the authoritative roadmap is
  `.claude/roadmap/README.md`." Drift at `docs/ops/` was previously
  tolerated for milestones E10-E11 because those runbooks ARE referenced
  from README. This one isn't. The pattern (`docs/ops/<runbook>.md`) is
  consistent with prior runbooks AND every prior runbook gets a README
  row — leaving this one un-linked is just a missed step.
- **Proposed fix:** Add a row to the README operator-runbooks table:
  ```
  | [`failure-modes.md`](docs/ops/failure-modes.md) | E14_S05 | Detection + recovery for the 9 documented failure modes |
  ```
- **Regression guard:** Update `tests/test_doc_layout.py` (if present)
  to enforce that every file under `docs/ops/` is linked from the root
  README. If no such test exists, add one — it's a 20-line ruff-scan-style
  test.

### F4 — Reranker warm-up materializes whole table

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/resources.py:439-441
- **What:** `arrow = chunks_table.to_arrow()` materializes the FULL chunks
  table just to slice off the first 10 rows. For a 200K-chunk corpus
  (E11_S05 target), this allocates a ~hundreds-of-MB Arrow table at
  startup, then garbage-collects 99.995% of it. A `to_arrow().slice(0, 10)`
  call would still materialize the full table because LanceDB's
  `to_arrow` is eager. The correct primitive is
  `chunks_table.head(10).to_arrow()` (LanceDB exposes `head(limit)` as a
  bounded scan).
- **Why it matters:** Per the implementation summary the live chunk_id
  scan at line 378-380 ALSO materializes the full table — but that one
  needs every chunk_id. The warm-up only needs 10 rows. Wastes hundreds
  of MB and several seconds of startup wall-clock for nothing. Startup
  is the moment the disk-free metric is also being initialized — a fat
  memory spike here racing the disk-free sentinel write is a real (if
  unlikely) interaction.
- **Proposed fix:** Replace `chunks_table.to_arrow()` with
  `chunks_table.head(10).to_arrow()` and adjust the slice/len math
  accordingly. Three lines.
- **Regression guard:** Hard to test absolute memory; a process-RSS
  check is flaky. Add a smaller test that mocks `chunks_table.head` and
  asserts it was called with `10`, OR documents the perf-sensitive call
  in `_warmup_rerank_pass`'s docstring so a future refactor doesn't
  regress.

### F5 — `voyage_api_key` is a plain `str | None`, not `SecretStr`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/config.py:207
- **What:** The `voyage_api_key: str | None = None` field is plain
  `str`. Pydantic's `Config.__repr__` includes ALL fields verbatim by
  default. If any code path ever logs the config (e.g. `logger.info("config=%s", config)` —
  none today, but plausible for a future debug-line addition), the API
  key leaks to logs. The brief explicitly cites the
  `RESTIC_PASSWORD never in source` discipline as a model — the same
  treatment should apply to the Voyage key.
- **Why it matters:** Threat 6 in 08-security-observability-ops.md
  treats credentials with model-tampering severity. The discipline is
  cheap to add (`from pydantic import SecretStr; voyage_api_key: SecretStr | None = None`).
  Today's runtime risk is low because no code logs the config — but the
  defense-in-depth posture is a one-line cost.
- **Proposed fix:** Change the field type to `SecretStr | None`; update
  any future code that READS the field to call `.get_secret_value()`.
  Current code path doesn't read it, so the only diff is the config
  declaration.
- **Regression guard:** A test that builds a `Config` with
  `voyage_api_key="secret-token-XYZ"`, calls `repr(config)`, and asserts
  `"secret-token-XYZ"` does NOT appear in the output.

### F6 — Missing test: hosted embedder + local fallback both fail

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_failure_modes.py:359-386 (TestHostedEmbedderFallback)
- **What:** The fallback wrapper at
  `server/query_encoder.py:486-509` catches `Exception` broadly and
  routes to `encode_query`. If `encode_query` ITSELF fails (BGE-M3 model
  un-loadable, OOM during encode, etc.), the wrapper propagates the
  exception unchanged to the caller. No test exercises this path. The
  result is the caller observes whatever BGE-M3 raises — which could
  be a `RuntimeError`, `OSError`, or torch-specific exception — none
  of which is the documented fallback contract.
- **Why it matters:** This is the "both legs of the failure-mode tree
  broken" case. At minimum the contract should be: when BOTH paths
  fail, the wrapper raises a single documented exception class (e.g.
  `_HostedEmbedderUnavailable`-like) so the caller has one type to
  catch. Today's behavior is whatever the local path raises.
- **Proposed fix:** Either (a) add a documented test that asserts the
  current behavior (BGE-M3 exception propagates unchanged), so future
  refactors don't silently break it; OR (b) wrap the inner
  `await encode_query(query_text)` call in a try/except and translate
  to a single contract class. (a) is the lighter touch.
- **Regression guard:** New test
  `test_voyage_fallback_propagates_local_failure` — monkeypatch
  `encode_query` to raise `RuntimeError("BGE OOM")`; assert
  `encode_query_with_fallback("q", "voyage")` raises the same
  `RuntimeError`.

### F7 — No test for `refresh_disk_free_metric` OSError path

- **Severity:** LOW
- **Source:** adversary
- **File:** server/health.py:576-585
- **What:** `refresh_disk_free_metric` catches `OSError` from
  `shutil.disk_usage` and logs a warning. No test exercises the
  OSError path. `data_dir` could plausibly not exist on a fresh
  install (the disk-full hook fires before `make bootstrap` creates
  the tree); the silent log-and-return is the correct behavior but
  the contract should be locked in.
- **Why it matters:** Latent foot-gun. If a future refactor narrows
  the except clause (e.g. to `FileNotFoundError`) the contract changes
  silently. Adding the test is 10 lines.
- **Proposed fix:** Add
  `TestDiskFullSentinelLogic::test_oserror_from_disk_usage_logged_and_skipped`:
  monkeypatch `shutil.disk_usage` to raise `OSError("[Errno 2]")`;
  assert no sentinel was written and the gauge was not updated.
- **Regression guard:** the new test itself.

### F8 — 8 vs 9 failure modes drift between brief and runbook

- **Severity:** LOW
- **Source:** adversary
- **File:** docs/ops/failure-modes.md:1-7
- **What:** The brief AC says: "`docs/ops/failure-modes.md` covers all
  8 failure modes (NOTE: design note has 9)." The runbook table
  documents 9 modes. The implementation summary §"Drift from brief"
  point 3 reads the parenthetical as license to expand to 9. Both
  positions are defensible — the design note (08-security-observability-ops.md
  §"Failure modes") lists 9 rows, so 9 is the correct count. But the
  parenthetical in the brief was ambiguous and could be read as "the
  design note has 9 but only 8 are in-scope for this milestone."
- **Why it matters:** Pure documentation alignment. The implementation
  summary already calls this out so the rectifier has a clear paper
  trail; this finding is just to confirm the resolution is recorded.
- **Proposed fix:** No code change. Confirm in the rectification commit
  body that "9 modes documented" is the deliberate resolution, and
  consider editing the brief's AC text to read "all 9 failure modes"
  for future-roadmap clarity.
- **Regression guard:** None applicable.

### F9 — `_warmup_rerank_pass` catches `Exception` silently

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:460-465
- **What:** The reranker warm-up `try / except Exception` at line 460
  catches a broad exception class, logs a WARN, and continues. The
  brief AC says the readiness probe should BLOCK the shim until ready
  ("readiness probe blocks shim until ready"). On a warm-up failure the
  server still opens `/readyz`; the first real request pays the
  cold-start cost. The intent is "non-fatal" per the inline comment
  (`# noqa: BLE001 — non-fatal`), and the brief's intent is "warm-up
  is best-effort," but the disconnect between the AC wording and the
  implementation is worth surfacing.
- **Why it matters:** If a future operator misreads the brief and
  expects a warm-up failure to refuse-to-start, today's behavior
  surprises them. The Voyage / LanceDB-corrupt paths DO refuse to
  start; the reranker warm-up path does not. The asymmetry is
  defensible but should be documented.
- **Proposed fix:** Tighten the log line to mention "warm-up is
  best-effort; the server starts anyway" so an operator reading the
  log understands. Or, narrow the catch to the specific torch / OSError
  classes (rather than bare `Exception`) so KeyboardInterrupt /
  SystemExit don't get caught (NB: `Exception` doesn't catch those
  today since they inherit from `BaseException`, but a future refactor
  could regress). Either is a 2-line change.
- **Regression guard:** None applicable — pure log-wording.

### F10 — `_warmup_rerank_pass` query string `"reranker warmup query"` is ASCII-only

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:443
- **What:** The warm-up uses a hardcoded English ASCII query. The
  production query traffic includes Unicode (per `_canonicalize` —
  `unicodedata.normalize("NFC", ...)`) — LaTeX accents like
  `\\'etale`/`étale`, Greek symbols, etc. The warm-up exercises the
  CPU-cache-warming path but NOT the unicode tokenization branch of
  the model.
- **Why it matters:** Real warm-up benefit is on the inference path;
  tokenization for ASCII vs Unicode shares 99% of the code. So this
  is a real but small gap.
- **Proposed fix:** Use a query that includes a single Unicode
  character (e.g. `"étale cohomology warmup"`) so the tokenizer's BPE
  paths for non-ASCII bytes are also warmed.
- **Regression guard:** None applicable.

## What was done well

- The N-1 fallback logic in `server/corpus.py:140-228` is clean, narrowly
  catches the documented union `(OSError, RuntimeError, ValueError)`, and
  preserves the original exception chain via `raise ... from primary_exc`
  for operator triage.
- The disk-full hysteresis (10 GB write threshold, 15 GB clear threshold)
  prevents the boundary-flap pattern. The hysteresis-band test at
  `tests/test_failure_modes.py:176-198` explicitly pins the contract.
- The "only auto-clear sentinels we wrote (reason=disk_low)" discipline at
  `server/health.py:609-622` correctly preserves operator-written
  maintenance pauses through auto-recovery. The matching test at
  `tests/test_failure_modes.py:150-174` is exactly the right shape.
- The two-phase atomic write in `tools/ingest_sentinel.py:142-144`
  (tmp → rename) matches the discipline of the E11_S05 backup-status
  wrapper — consistent project-wide pattern.
- The WARN-once log gate (`_HOSTED_FALLBACK_LOGGED`) at
  `server/query_encoder.py:436` + `_reset_hosted_fallback_logged_for_tests`
  prevents log spam during sustained outages while keeping the counter
  as the rate signal. Right separation of "ops alert" vs "operator
  notification."
- Separate `HOSTED_EMBED_FALLBACK_COUNTER` Counter (events) vs
  `DEGRADED_MODE_ACTIVE` Gauge (current state) — the two-metric pattern
  lets an operator distinguish "we had 47 outages this hour" from
  "we are CURRENTLY outage-ing."
- `TOOL_SCHEMA_VERSION` stays at 6; the conditional `degraded` /
  `degraded_reasons` keys live in response content, not schema —
  BP1 byte-stability for `tools/list` is preserved.
- The `infra/prometheus/alerts.yml` shape passes both the PyYAML
  smoke test and the threshold-cross-check
  (`test_disk_full_threshold_matches_implementation`) — the alert
  threshold and the sentinel-write threshold are pinned to the same
  constant; a future drift fires the test loudly.
- The runbook at `docs/ops/failure-modes.md` is genuinely operator-
  facing — every section names a detection signal, a recovery
  procedure, and an alert. The cross-references to other runbooks
  (`backup-restore.md`, `latexml-drift-runbook.md`) make the operator
  workflow navigable.

## Recommended rectification order

1. **F2 (HIGH)** — cron path drift. Fix first because it's a defense
   bypass at the operator-control-plane layer and is independent of
   the other fixes. 3-line bash edit.
2. **F1 (HIGH)** — cache-degraded interaction. Fix second; the
   change is at the cache-hit return sites in `search.py` and
   compounds badly with F2 if the cron is silently broken AND the
   server is silently mis-tagging payloads.
3. **F3 (MEDIUM)** — doc-layout. Add the README row and (optionally)
   the test for the README-vs-`docs/ops/` invariant.
4. **F5 (MEDIUM)** — `SecretStr` for `voyage_api_key`. Defense-in-
   depth; cheap.
5. **F4 (MEDIUM)** — `.head(10)` replacement for `to_arrow()` in
   reranker warm-up. Pure perf nit but affects scale-cutover
   readiness.
6. **F6 (MEDIUM)** — Test for hosted+local both-fail path. 15 lines.
7. **F7, F8, F9, F10 (LOW)** — defer to `deferred_findings` unless
   any rectification under #1-#6 makes them trivially co-fixable.

## Rectification status (filled by Phase 4)

- **F1** (HIGH — cache short-circuits before degraded flag): fixed.
  Computed ``base_degraded_reasons`` ONCE at handler entry and
  re-stamped cached payloads via new ``_restamp_degraded`` helper
  at both Tier-1 and Tier-2 hit sites. The cache key intentionally
  does NOT include the degraded axis (would balloon key space).
  Regression guards: ``TestF1CacheDegradedRestamping::test_restamp_adds_degraded_when_server_degraded``,
  ``test_restamp_removes_stale_degraded_when_server_healthy``.
- **F2** (HIGH — cron sentinel path drift): fixed. The wrapper at
  ``ops/cron/arxmcp-delta.sh`` now resolves
  ``DATA_DIR="${ARXMCP_DATA_DIR:-${REPO_ROOT}/var/arxmcp}"`` with
  the same precedence as ``tools.ingest_sentinel._resolve_sentinel_path``.
  Guard: ``TestF2CronSentinelPathDrift::test_cron_wrapper_references_arxmcp_data_dir``.
- **F3** (MEDIUM — failure-modes.md not linked from README): fixed.
  Added rows for ``daily-ops-cadence.md`` (E14_S04 carryover),
  ``parser-failure-review.md`` (E14_S04), and ``failure-modes.md``
  (E14_S05) to the README operator-runbooks table.
- **F4** (MEDIUM — reranker warm-up materialises whole table):
  fixed. Replaced ``chunks_table.to_arrow()`` with
  ``chunks_table.take_offsets(list(range(10))).to_arrow()`` — a
  bounded scan reading only the 10 rows we actually use. Plus
  ``count_rows()`` guard for the seed-corpus case.
- **F5** (MEDIUM — voyage_api_key plain str): fixed. Type changed
  to ``pydantic.SecretStr | None``; ``repr(config)`` now masks
  the value. Guard: ``TestF5VoyageKeyIsSecretStr::test_secret_value_masked_in_repr``.
- **F6** (MEDIUM — no test for both-paths-fail): fixed. New
  ``TestHostedEmbedderFallback::test_voyage_fallback_propagates_local_failure``
  asserts the current behaviour (local exception propagates
  unchanged) so a future refactor that silently swaps types is
  caught.
- **F7** (LOW — no OSError test for refresh_disk_free_metric):
  DEFERRED. The existing code path is intentionally tolerant
  (catch + log + skip); the contract is documented in the
  docstring. A test would be 10 lines but the latent-foot-gun
  surface is small.
- **F8** (LOW — 8 vs 9 failure modes): DEFERRED. Already
  documented in the implementation-summary's §"Drift from brief"
  point 3; no further action needed.
- **F9** (LOW — silent warm-up failure): fixed in part. Updated
  the WARN log message to explicitly say "server starts anyway
  (best-effort warm-up)" so an operator reading the log
  understands the warm-up is non-fatal. The catch remains broad
  per the inline ``# noqa: BLE001`` rationale.
- **F10** (LOW — ASCII-only warm-up query): fixed. Replaced
  ``"reranker warmup query"`` with ``"étale cohomology warmup"``
  so the BPE tokenizer's non-ASCII path is exercised during
  warm-up (production queries contain Unicode: LaTeX accents,
  Greek symbols).

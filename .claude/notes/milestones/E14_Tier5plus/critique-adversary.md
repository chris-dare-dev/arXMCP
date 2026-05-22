# Critique — E14_Tier5plus

**Critic:** adversary
**Generated:** 2026-05-22T22:03:39Z
**Commit range:** a0a00d64e344d679c7f37abc15ab9dec8d180dd8..28b06c50ea7da5dab54a4d1929201cf81ba68007
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- 0 CRITICAL, 4 HIGH, 5 MEDIUM, 2 LOW. The dashboard JSON, spend-counter
  module, runbook skeletons, and tracker structure are all sound; the
  load-bearing problems concentrate in the Langfuse doc (S11) and the
  ops runbooks (S10) where claims drift from server reality.
- Highest-risk file:line — `docs/observability/langfuse-orchestrator.md:23`
  ("server does NOT emit `Mcp-Session-Id`...") directly contradicts the
  same doc 11 lines later AND contradicts `shim/arxmcp_shim.py:150` which
  proves the server emits it. Synthesis A4 is wrong; the doc inherited
  the wrong claim and then half-corrected itself in the next paragraph.
- The spend module is structurally orphaned at runtime: nothing in the
  live server imports `server/observability/spend_constants.py`, so the
  `arxmcp_api_spend_usd_total` Counter is never registered with the
  default REGISTRY and never appears in `/metrics` (F2).
- `LAST_VERIFIED` staleness has zero enforcement — the docstring at
  `spend_constants.py:80-81` claims a `test_last_verified_within_six_months`
  guard, but no such test exists. Operator-visible date can decay
  silently while the brief flagged staleness as a key concern (F3).
- The S11 snippet hardcodes `model="claude-sonnet-4-5"` — wrong version
  (real is `claude-sonnet-4-6`) AND duplicates a model-ID literal in
  exactly the SSoT anti-pattern the fixup commit `c7cf81d` had to
  rectify in `spend_constants.py` (F4).
- Two of four new runbooks (`corpus-rollback.md`, `latexml-restart.md`)
  hardcode `/Users/chris.dare/Library/Python/3.9/bin/uv run python`
  paths — non-portable for any other operator (F5).
- `corpus-rollback.md:105` instructs the operator to verify rollback
  via `curl http://127.0.0.1:7733/healthz/version` — that endpoint
  does NOT exist anywhere in `server/` (F6).
- Anchor links in `docs/ops/README.md` (#2 "ingestion-pause recovery" →
  `failure-modes.md#disk-full`) point at a section that is named "Disk
  full", not "ingestion-pause" — confusing operator UX and the link-check
  test cannot catch it because it strips anchors before checking (F7).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Langfuse doc self-contradicts on Mcp-Session-Id emission

- **Severity:** HIGH
- **Source:** adversary
- **File:** docs/observability/langfuse-orchestrator.md:23
- **What:** The doc states "The arXMCP server does **NOT** emit
  `Mcp-Session-Id` as a response header — it only *consumes* the header
  from the client request." Eleven lines later (line 34) the same doc
  acknowledges "Per the MCP 2025-06-18 spec, the server echoes the
  session ID in its initialize response." `shim/arxmcp_shim.py:150` is
  `sid = resp.getheader("mcp-session-id") or sid` — proving the server
  emits it (via the upstream MCP `StreamableHTTPSessionManager`).
  Synthesis A4 was wrong: the absence of an emission site in
  `server/middleware.py` does not imply the server doesn't emit the
  header — the MCP library session manager does.
- **Why it matters:** Operator-facing doc with an internally contradictory
  claim about a load-bearing MCP protocol detail. An orchestrator
  implementer reading the first paragraph will design around an
  incorrect assumption (caller-only session-ID), then trip on the
  contradictory paragraph below. Synthesis A4 is itself wrong and
  needs correction so future milestones don't propagate the error.
- **Proposed fix:** Replace lines 22–36 with a single accurate
  paragraph: "The arXMCP server emits `Mcp-Session-Id` on the
  initialize response per MCP 2025-06-18 spec; subsequent requests
  carry the value back as the `Mcp-Session-Id` request header.
  Orchestrator: extract the session-id from the initialize response
  (e.g., `resp.headers['mcp-session-id']`), then pass the same value
  as the Langfuse `session_id` so both halves of the trace join."
  Update `research-synthesis.md` §A4 with a correction note.
- **Regression guard:** Add `test_doc_session_id_paragraph_is_internally_consistent`
  to `tests/test_langfuse_doc.py` that asserts the doc does NOT contain
  the substring "does **NOT** emit" (or contains it ONLY in a clearly-
  flagged corrigendum block).

### F2 — Spend module is orphaned at runtime; metric never registers

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/observability/spend_constants.py:114
- **What:** `API_SPEND_USD_TOTAL = Counter(...)` registers the metric at
  module import time. Grepping `server/` and `ingest/` for runtime
  imports of `spend_constants` returns ZERO production importers — the
  only references are (a) the test file and (b) a comment inside
  `server/query_encoder.py:454`. Result: in the running server, the
  module is never imported, so the Counter is never registered with
  `prometheus_client.REGISTRY`, so `arxmcp_api_spend_usd_total` never
  appears in `/metrics` output.
- **Why it matters:** The brief's acceptance criterion is that the spend
  metric is "registered" — but registration is conditional on import,
  and nothing live imports the module. Operators scraping `/metrics`
  will not see the metric series at all (even at zero) until E08_S07 or
  the Voyage client lands. The dashboard does NOT reference this metric
  today, but the implementation-summary's claim that S12 "ships
  Prometheus metric registration" is technically false at runtime.
- **Proposed fix:** Either (a) eagerly import `spend_constants` from
  `server/main.py` in a side-effect-only import block (with a comment
  explaining the registration side-effect), so the metric is visible
  in `/metrics` from day 1 — even at zero counts; or (b) register the
  Counter in the existing `server/observability/metrics.py` module
  which IS imported at startup, and move just the constants/helpers
  into `spend_constants.py`. (a) is simpler.
- **Regression guard:** Add `test_spend_metric_registered_in_main_module`
  to `tests/test_spend_constants.py` that imports `server.main` (without
  building the app) and asserts `arxmcp_api_spend_usd_total` is
  retrievable via `REGISTRY.get_sample_value` (returns 0.0, not None).

### F3 — LAST_VERIFIED staleness guard does not exist

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/observability/spend_constants.py:80
- **What:** Docstring claims: "A failing
  `test_last_verified_within_six_months` regression guard will surface
  stale constants." No such test exists in `tests/test_spend_constants.py`
  (the only LAST_VERIFIED test is `test_last_verified_parses_as_iso_date`
  which only validates format, not freshness). Pricing constants can
  go stale silently for years, and the docstring lies about a guard
  that protects them.
- **Why it matters:** The brief flagged "pricing-constant staleness" as
  a specific concern. The implementation claims the concern is
  addressed via a regression guard. The claim is false. Two harms:
  (a) operators trust LAST_VERIFIED to be enforced when it isn't; (b)
  the project's "load-bearing test" culture is eroded by a documented-
  but-absent guard.
- **Proposed fix:** Implement the missing test — fail when
  `(date.today() - date.fromisoformat(LAST_VERIFIED)).days > 180`. The
  fix is ~6 LOC. If the project doesn't want the test to block CI
  semi-annually, gate it with `@pytest.mark.skipif(SKIP_STALENESS_CHECK)`
  but make it run by default. Alternatively, delete the docstring's
  false promise (lines 80–81) and accept that staleness is
  operator-discipline.
- **Regression guard:** The test itself IS the guard. Add
  `tests/test_spend_constants.py::TestLastVerifiedFresh::test_last_verified_within_six_months`.

### F4 — Langfuse snippet hardcodes wrong-version Sonnet ID

- **Severity:** HIGH
- **Source:** adversary
- **File:** docs/observability/langfuse-orchestrator.md:60
- **What:** The function signature has `model: str = "claude-sonnet-4-5"`.
  The canonical Sonnet model ID in `server/orchestrator/model_selector.py:88`
  is `MODEL_SONNET_4_6 = "claude-sonnet-4-6"`. The snippet hardcodes a
  stale/wrong version (`4-5` instead of `4-6`) AND duplicates the
  literal — exactly the SSoT anti-pattern that the fixup commit
  `c7cf81d` had to clean up for the Haiku ID in `spend_constants.py`
  during this same bundle.
- **Why it matters:** The brief specifically asked whether the SSoT
  regression was "a real bug class that could resurface" — and it
  resurfaced in the same milestone bundle, in a different artifact, the
  day after the fixup commit. Operators copying the snippet into their
  orchestrator codebase will get the wrong model. The doc is a
  reference template; "use anywhere" semantics demand the model ID be
  authoritative.
- **Proposed fix:** Two paths: (a) replace the literal with a comment
  pointing the reader to choose their model and remove the default
  (`model: str` without default + docstring "set to whichever Anthropic
  model you target — see `model_selector.py` for the project's pinned
  IDs"); (b) update the literal to `"claude-sonnet-4-6"` and add a
  test that asserts the doc references the canonical ID. (b) is more
  fragile because every Sonnet bump requires a doc edit. Prefer (a).
- **Regression guard:** Add
  `test_snippet_does_not_hardcode_obsolete_model_id` to
  `tests/test_langfuse_doc.py` — fails if the snippet contains
  `claude-sonnet-4-5` or any literal `claude-` model ID not present in
  `model_selector.py`.

### F5 — Two new runbooks hardcode an operator-specific Python path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/ops/corpus-rollback.md:47 and docs/ops/latexml-restart.md:97
- **What:** Both runbooks contain `/Users/chris.dare/Library/Python/3.9/bin/uv
  run python ...`. This is the absolute path to chris.dare's user-level
  uv install. Per CLAUDE.md (gotcha 8): the `uv run` invocation is a
  test-time hack to avoid the Python 3.9 vs 3.12 mismatch; the absolute
  path is OK for AGENT-internal docs but `docs/ops/` is operator-facing
  documentation. Any operator who is not chris.dare cannot run these
  commands as-written.
- **Why it matters:** Runbook usability — the runbooks are meant to be
  followed when a daemon is down or a corpus has been rolled back.
  Failing on a copy-paste because the path doesn't exist on the
  operator's machine wastes outage time. The existing
  `latexml-drift-runbook.md` (line 117) has the same antipattern, so
  this is a pre-existing repo-wide issue; the new milestone propagates
  rather than fixes it.
- **Proposed fix:** Replace `/Users/chris.dare/Library/Python/3.9/bin/uv
  run python` with `uv run python` (assumes `uv` on PATH; document the
  prereq once in `docs/install.md` or the README "Operations"
  section). Backfill `latexml-drift-runbook.md` in the same pass.
- **Regression guard:** Add a `test_no_hardcoded_user_paths_in_ops_docs`
  test in `tests/test_runbook_index.py` that walks `docs/ops/*.md` and
  fails on regex `/Users/[a-z.]+/` matches.

### F6 — corpus-rollback.md instructs use of a non-existent endpoint

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/ops/corpus-rollback.md:105
- **What:** Verification step says `curl -s http://127.0.0.1:7733/healthz/version`
  and "Expected: matches the TARGET_CORPUS from step 3." Grepping
  `server/` for `/version` or `healthz/version` shows zero matches —
  this endpoint does not exist. `server/health.py` registers `/healthz`
  and `/readyz` only.
- **Why it matters:** Operator running the rollback runbook will hit a
  404 on the verification step and have no way (per the runbook) to
  confirm the rollback succeeded. The remaining verification steps
  (`make smoke`, `make eval`) work but the corpus-version check is the
  most direct signal that the rollback took effect.
- **Proposed fix:** Either (a) replace with an actual command that works:
  e.g. `cat var/arxmcp/corpus-version.json` (which is what step 2 of
  the same runbook tells the operator to read); or (b) add a real
  `/healthz/version` endpoint to `server/health.py` exposing the
  pinned `corpus_version`. (a) is the trivial fix; (b) is a follow-up
  feature.
- **Regression guard:** Add a `test_runbook_curl_endpoints_exist`
  test that extracts every `curl http://127.0.0.1:7733/<path>` from
  `docs/ops/*.md` and asserts each `<path>` is a registered FastAPI
  route in `server/main.py`'s app or in `server/health.py`.

### F7 — Anchor-link UX bug; link-check test cannot catch it

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/ops/README.md:25
- **What:** Index entry #2 is `[ingestion-pause recovery](failure-modes.md#disk-full)`
  — the label "ingestion-pause recovery" sends operators to the
  "Disk full" section of `failure-modes.md`. The two are related (a
  full disk creates an `ingest-paused` sentinel) but a separate-named
  scenario in the index strongly implies a separate destination
  section. The link-check test
  (`tests/test_runbook_index.py::TestAllIndexedRunbooksExist`) strips
  anchors before checking, so it cannot catch this label/destination
  mismatch.
- **Why it matters:** Operator UX during an incident. An operator
  responding to an `ingest-paused` sentinel that did NOT come from
  disk-full (e.g., manual operator pause) will land on the wrong
  section. The brief specifically flagged: "current tests check file
  existence; do they catch anchor drift?" — answer is no.
- **Proposed fix:** Two options. (a) Create a real `#ingestion-pause`
  section header in `failure-modes.md` and link to that anchor; (b)
  Re-label the index entry to "ingestion-pause from disk-full" so the
  destination matches. (a) is more correct; (b) is faster.
- **Regression guard:** Extend the link-check test to assert that
  every `<file>.md#<anchor>` link resolves to a real `<anchor>` in
  `<file>.md`. Implementation: parse the target file's `^#+ ` headings
  and slugify (lowercase + spaces→hyphens) per CommonMark anchor rules.

### F8 — README dashboard-import instructions require manual YAML splitting

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** README.md (line 92 of diff, "Importing the dashboard")
- **What:** Provisioning is shipped as a single
  `infra/observability/grafana-provisioning.yml` file with two top-level
  blocks (`datasources:` and `providers:`). The README instructs the
  operator to "split on the comment markers" into two physical files
  at `/etc/grafana/provisioning/{datasources,dashboards}/arxmcp.yml`.
  This is a manual `sed`/copy operation, error-prone, and no test
  validates that the comment markers are stable enough for splitting.
- **Why it matters:** Synthesis D6 deliberately punted on shipping a
  `grafana-compose.yml` for "scope discipline," but the resulting
  documentation requires undocumented operator-side YAML surgery. The
  in-file comments are NOT machine-readable separators. A future edit
  that removes/changes the dashed-comment headers would silently
  break the operator's split procedure.
- **Proposed fix:** Either (a) ship two physical files
  (`grafana-datasource.yml` + `grafana-dashboard-provider.yml`) so the
  operator can mount them directly with no surgery — minimal scope
  growth, ~20 LOC of YAML split into two; or (b) provide a tiny
  `tools/grafana-provision-split.sh` script that performs the split
  reliably and reference it from the README.
- **Regression guard:** Add a `test_provisioning_yaml_splits_cleanly`
  test in `tests/test_grafana_dashboard.py` — assert the file contains
  exactly two top-level YAML documents OR the documented split
  separators. If shipping two files (option a), the test simply
  asserts each file parses standalone.

### F9 — Singleflight panel shows cumulative counter; UX confusion

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/observability/grafana-dashboard.json:66
- **What:** Panel 2 ("Embedder singleflight dedup count") queries the
  bare counter: `expr: "arxmcp_embed_singleflight_dedup_total"`. This
  renders a monotonically-increasing staircase on a timeseries graph
  — which is technically correct for a Counter but is the wrong
  visualization for "rate of dedup events." Operators looking at the
  panel will see "always going up" and have to mentally
  differentiate; the panel's description text doesn't warn them.
- **Why it matters:** Dashboard utility. The panel exists to surface
  *rate of dedup* (so the operator can spot when concurrency is high
  and dedup is therefore active). A raw-counter visualization
  obscures that signal.
- **Proposed fix:** Change the `expr` to
  `rate(arxmcp_embed_singleflight_dedup_total[5m])` and update the
  panel `title` to "Embedder singleflight dedup rate (5m)" + adjust
  the description.
- **Regression guard:** No test needed; the byte-stability test will
  re-canonicalize after the edit.

### F10 — `_resolve_agent_role` defensive coercion silently swallows config drift

- **Severity:** LOW
- **Source:** adversary
- **File:** server/observability/spend_constants.py:154
- **What:** `if role is None or role not in VALID_AGENT_ROLES: return "unknown"`
  silently swallows a foreign value in the ContextVar (i.e., a future
  middleware leak that put e.g. `"attacker-role"` in
  `current_agent_role`). The defensive coercion is correct for label-
  cardinality protection — but the code does not log/warn when this
  fires. A genuine bug in upstream middleware will silently route to
  `agent_role="unknown"` and operators won't notice.
- **Why it matters:** Defensive coercion without logging is debt. The
  comment at line 142–144 acknowledges this is "defensive against
  future middleware changes" but provides no observability hook for
  the defensive path firing.
- **Proposed fix:** Add a `logger.warning(...)` (once per foreign
  value via a `set()` cache) when coercion fires. Existing
  `server/observability/log_filter.py` provides redaction; this is
  safe to log.
- **Regression guard:** None needed for LOW.

### F11 — Spend module 24-vs-20 cardinality docstring drift

- **Severity:** LOW
- **Source:** adversary
- **File:** server/observability/spend_constants.py:26
- **What:** Module docstring says "Maximum 2 × 2 × 5 = 20 label
  combinations" but research-synthesis.md §D3 says "2 providers × ~3
  models × 4 roles = 24 max combinations." Both are arithmetically
  safe under Prometheus best practices, but the discrepancy is
  documentation drift.
- **Why it matters:** Trivially confusing for the next reader.
- **Proposed fix:** Update synthesis §D3 to "2 × 2 × 5 = 20" to match
  the implementation. (5 = 4 roles + "unknown".)
- **Regression guard:** None needed for LOW.

## What was done well

- Synthesis A1 was caught and held: the dashboard uses the registered
  `arxmcp_request_latency_seconds_bucket`, not the brief's wrong
  `arxmcp_tool_latency_seconds`, and a dedicated test
  (`test_dashboard_uses_correct_per_tool_latency_metric`) is the
  regression guard. Both halves of the assertion are present.
- The metric-truth test (`TestMetricNamesAreRegistered`) is exactly
  the right shape — textual regex scan against the 3 metric source
  files, plus a positive "this specific metric is referenced" and a
  negative "this wrong metric is NOT referenced." This is the kind
  of test that catches the next brief-vs-codebase metric-name drift
  automatically.
- The dashboard JSON byte-stability test re-serializes with
  `sort_keys=True, indent=2` and asserts equality with disk bytes —
  exact right discipline for byte-stable JSON. The error message even
  provides the canonicalization command for self-recovery.
- Synthesis D2 (do NOT increment Voyage counter on the stub fallback
  path) was correctly enforced. The TODO block at
  `query_encoder.py:451–463` is verbose and points at the future call
  site, and `test_voyage_stub_carries_future_client_todo` is the
  regression guard.
- The SSoT model-ID discipline was caught at full-suite test time
  (the fixup commit `c7cf81d` imports `MODEL_HAIKU_4_5` from
  `model_selector` rather than re-defining the literal). Good
  recovery; the fix-as-separate-commit pattern matches CLAUDE.md.
- The `test_no_anthropic_import_in_server` regression guard
  correctly enforces CLAUDE.md §4.7. `assert result.returncode == 1`
  (grep "no match") is the right pattern.
- The Voyage stub TODO block uses a discoverable grep token
  (`TODO(future-voyage-client)`) and explicitly mentions
  `record_spend` so future grep finds the wiring location — good
  cross-reference discipline.
- `_resolve_agent_role` correctly uses a local import (line 148) to
  break the circular import with `tracing.py` — good defensive
  engineering with a comment explaining why.
- The deferred-work tracker un-park triggers are mostly concrete +
  falsifiable; the 6-month review cadence is documented and the
  reviewer's steps are listed.
- The runbook index 4-part skeleton is enforced by
  `test_new_runbook_has_all_skeleton_sections` parameterized over the
  4 new runbooks — exact correspondence between AC and test.

## Recommended rectification order

1. **F4** (HIGH, langfuse model-ID drift) — same bug class as the
   fixup commit; fix the doc before someone copy-pastes the wrong
   model ID into orchestrator code.
2. **F1** (HIGH, langfuse self-contradiction) — pair-fix with F4 since
   both are in the same doc; also requires a synthesis correction so
   the wrong belief doesn't propagate.
3. **F2** (HIGH, spend metric never registers at runtime) — small fix
   (one `import` line in `server/main.py` or `server/observability/__init__.py`)
   with a regression test; high-leverage because the brief's S12 AC
   "Counter registered" is structurally unmet.
4. **F3** (HIGH, missing LAST_VERIFIED guard) — either implement the
   6-LOC test or delete the docstring promise. Cheap either way.
5. **F6** (MEDIUM, `/healthz/version` doesn't exist) — runbook
   correctness; trivial doc fix, replace with `cat var/arxmcp/corpus-version.json`.
6. **F5** (MEDIUM, hardcoded user paths) — backfill all three runbook
   files (`corpus-rollback.md`, `latexml-restart.md`, +
   `latexml-drift-runbook.md`) in one sweep; add the regression test
   so this doesn't regrow.
7. **F7** (MEDIUM, anchor drift) — easier path is the label-only fix
   (rename index entry #2 to "ingestion-pause from disk-full"); the
   anchor-validating test extension is the durable fix.
8. **F8** (MEDIUM, manual YAML splitting) — ship two physical YAML
   files rather than ask operators to split by comment markers.
9. **F9** (MEDIUM, singleflight panel UX) — one-line PromQL fix +
   panel title bump.
10. **F10**, **F11** (LOW) — defer to a future doc-tidy pass.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

# Critique — E11_S02 (merged)

**Critics:** adversary (Opus) + infra-safety (Sonnet)
**Generated:** 2026-05-15 (orchestrator merge)
**Commit range:** 76f7373..478cd44
**Verdict:** REWORK (adversary) + SHIP-WITH-FIXES (infra-safety) → **REWORK**

## Executive summary (orchestrator)

- Combined: **2 CRITICAL, 4 HIGH, 8 MEDIUM, 7 LOW** (21 findings).
- Adversary flagged 2 CRITICAL: F1 (dead 503-handling branch +
  no `Retry-After` backoff — the very risk the brief claims to
  close) and F2 (OAI-PMH egress missing F9-style redirect
  pinning). Both must be fixed.
- Infra-safety flagged 2 HIGH operator-reproducibility issues:
  IS1 (`ExecStart` not called out as a substitution target in
  the systemd unit's operator comment) and IS2 (`UV_BIN` defaults
  to a single-user macOS path — same hardcode as
  `latexml-drift-check.sh`).
- 2 HIGH protocol-correctness issues from adversary: F3 (set-naive
  token recovery — same-day crash + same-day resume feeds a set-2
  token to set-1) and F4 (`<error code="noRecordsMatch">` on quiet
  days crashes the run; this is a normal OAI-PMH response).
- Cross-critic agreement: F13 + IS5 — both critics flagged the
  missing `make delta` Makefile target.
- The brief's headline "Closes MEDIUM: arXiv 429 backoff" is
  **unfulfilled** until F1's `HTTPError` + `Retry-After` handler
  ships and F6's regression test exists.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

- **F13 (adversary, LOW) + IS5 (infra-safety, MEDIUM):** missing
  `make delta` Makefile target. Upgrade to MEDIUM per the
  infra-safety severity (operator reproducibility).
- **F12 (adversary, LOW) + IS3 (infra-safety, MEDIUM):** runbook
  is not linked from the root README; `Documentation=` URI
  points to a non-existent install-time path. Both flag
  operator-facing doc plumbing.

## Findings (full bodies preserved from per-critic files)

See [critique-adversary.md](critique-adversary.md) and
[critique-infra-safety.md](critique-infra-safety.md) for the
full file:line citations and proposed fixes. Headings + severities
preserved verbatim:

### CRITICAL

- **F1** — Dead `if status != 200` branch + no 503/Retry-After
  handling (`ingest/oai_delta.py:259-263`). Closes brief's
  named MEDIUM:arXiv-429-backoff risk.
- **F2** — OAI-PMH egress missing F9 redirect pinning
  (`ingest/oai_delta.py:247-263`).

### HIGH

- **F3** — State file set-naive; cross-set crash recovery is
  broken (`ingest/oai_delta.py:411-417, 549-571`).
- **F4** — `noRecordsMatch` on quiet days crashes the run
  (`ingest/oai_delta.py:291-296`).
- **IS1** — `ExecStart` hardcode not flagged in operator comment
  (`ops/systemd/arxmcp-delta.service:21`).
- **IS2** — `UV_BIN` default is a single-user workstation path
  (`ops/cron/arxmcp-delta.sh:36`).

### MEDIUM

- **F5** — AC3 500-paper test does not model real per-paper cost.
- **F6** — No test exercises 503 / Retry-After. (Closed by F1
  regression guard.)
- **F7** — XML billion-laughs concern. **Defer to E13.**
- **F8** — `_resolve_resume` future-clock-drift edge.
- **F9** — `from > until` operator-error path uncovered.
- **IS3** — `Documentation=` URI points to non-existent path.
- **IS4** — Reentrancy guard not NFS / multi-host aware.
- **IS5** — Missing `make delta` target (cross-critic with F13).

### LOW

- **F10** — Redundant `_feed_record_to_pipeline` for deleted
  records.
- **F11** — Stale timeout flag not cleared on dry-run.
- **F12** — Runbook not referenced from root README (cross-critic
  with IS3).
- **F13** — `make delta:` target missing (cross-critic; upgraded
  via IS5).
- **F14** — Docstring overclaims inherited fixes — adjust when
  fixing F2.
- **IS6** — Timer fires in local time; ops-cadence comment claims
  UTC. Defer.
- **IS7** — Missing systemd defense-in-depth hardening
  directives. Defer.

## What was done well (merged)

- **Reuse of `ingest_one_paper` is correctly framed** — the
  delta loop is a thin harvester + per-paper feed.
- **Staging-path discipline preserved** — writes route to
  `DEFAULT_LANCEDB_STAGING_PATH`; active marker untouched.
- **HTTPS endpoint + `arXivRaw` metadata format right** per
  synthesis D4/D5.
- **Four per-set ListRecords calls** (not `set=math` umbrella).
- **Atomic state-file writes** (`.tmp` + `replace()`).
- **`flock -n` reentrancy guard** is the right pattern and
  matches the drift-check precedent.
- **No tool-schema changes; no hash bumps.**
- **Sentinel-flag pattern mirrors the E10_S04 drift detector.**
- **Cross-day token expiry handled correctly** in
  `_resolve_resume`.
- **`<header status="deleted">` correctly treated as skip.**
- **`set -euo pipefail` + `${BASH_SOURCE[0]}` resolution + `exec
  flock`** in the shell wrapper are textbook correct.
- **`Type=oneshot` + `Persistent=true` + `RandomizedDelaySec=300`
  + `TimeoutStartSec=7200`** systemd directives all right.
- **Documentation completeness**: prerequisites, smoke test,
  scheduling, latency budget, failure modes, state-file schema
  all in `docs/ops/delta-loop.md`.

## Recommended rectification order (orchestrator)

1. **F1** (CRITICAL) — `HTTPError` + 503/`Retry-After` /
   exponential-backoff handler. Closes brief's named risk.
2. **F2** (CRITICAL) — Pin `_fetch_page` response.url to
   `oaipmh.arxiv.org`. Defense-in-depth on new egress.
3. **F4** (HIGH) — Treat `noRecordsMatch` as empty-success.
   Common-path correctness.
4. **F3** (HIGH) — Persist `last_set_spec`; scope token to set
   on resume. (Or, simpler: discard the token on cross-set
   transition and re-harvest the whole window.)
5. **IS2** (HIGH) — Replace hardcoded `UV_BIN` fallback with
   `command -v uv` guard.
6. **IS1** (HIGH) — Extend systemd unit comment to call out
   `ExecStart` + `ReadWritePaths` as substitution targets.
7. **F6** (MEDIUM) — Regression test for 503-with-Retry-After
   sequence. (Pairs with F1 fix.)
8. **F8 + F9** (MEDIUM) — Validate `from <= until` and
   `last_harvest_date <= today` at entry; fail fast.
9. **F5** (MEDIUM) — Rescope AC3 claim in
   implementation-summary.md (mocked-pipeline acknowledgment).
10. **IS5 + F13** (MEDIUM, cross-critic) — Add `make delta`
    target.
11. **IS3** (MEDIUM) — Change `Documentation=` to a URL.
12. **IS4** (MEDIUM) — Add NFS / single-writer caveat to runbook.
13. **F11** (LOW) — Clear timeout flag before dry-run early-return.
14. **F14** (LOW) — Scope the docstring's "inherited fixes" claim.
15. **F12** (LOW) — Link runbook from root README. **Defer**
    (precedent: bulk-ingest-runbook also unlinked).
16. **F7, F10, IS6, IS7** — Defer per critic recommendations.

## Rectification status (filled by Phase 4)

- F1 — fixed in `_fetch_page` (HTTPError catch + Retry-After +
  exponential backoff capped at 1 hour). Regression guards:
  `TestRetryAfterParsing` (5 sub-tests),
  `TestFetchPage503Backoff::test_503_then_200_succeeds_after_retry`,
  `test_non_503_error_propagates_without_retry`,
  `test_503_retry_cap_exhaustion_raises`.
- F2 — fixed in `_fetch_page` (response.url pinned to endpoint).
  Regression guards: `TestFetchPageRedirectPin`
  (`test_off_host_response_url_rejected`,
  `test_on_host_response_url_accepted`).
- F3 — fixed in `_resolve_resume` (now returns 3-tuple with
  `last_set_spec`) + `harvest_set` (persists `last_set_spec`) +
  `run_delta` (token consumed only by origin set). Regression
  guard: `TestSetAwareTokenRecovery::test_token_used_only_for_origin_set`.
- F4 — fixed in `_parse_listrecords` (noRecordsMatch returns
  empty-success). Regression guards:
  `TestNoRecordsMatch::test_norecordsmatch_returns_empty_no_token`,
  `test_one_quiet_set_does_not_crash_run`.
- F5 — implementation summary AC3 rescoped with adversary F5
  caveat (mocked-pipeline acknowledgement; real-load deferred
  to E11_S05).
- F6 — closed by F1's regression guards.
- F7 — **deferred to E13** per critic recommendation
  (defusedxml is not in pyproject.toml; flagged for the
  threat-model audit milestone).
- F8 — fixed in `_resolve_resume` (future-date guard resets to
  yesterday). Regression guard:
  `TestResolveResume::test_future_date_resets_to_yesterday`.
- F9 — fixed in `run_delta` (rejects `from_date > until_date` at
  entry). Regression guard:
  `TestFromUntilValidation::test_from_greater_than_until_rejected`.
- F10 — deferred (cosmetic; not a bug per critic note).
- F11 — fixed in `run_delta` (`_clear_budget_flag` moved before
  dry-run early-return). Regression guard:
  `TestStaleTimeoutFlagCleared::test_dry_run_clears_old_flag`.
- F12 — deferred. Precedent: bulk-ingest-runbook.md is also
  unlinked from the root README; rolling both into a single
  "Operator runbooks" bullet is a follow-up doc-tidy task.
- F13 — closed by IS5's fix (`make delta` target).
- F14 — fixed in module docstring (scoped the "inherited fixes"
  claim to per-paper-pipeline scope; the OAI-PMH egress channel
  has its own F9-style mitigation).
- IS1 — fixed in `ops/systemd/arxmcp-delta.service` (operator
  comment names `ExecStart` and `ReadWritePaths` as substitution
  targets alongside `WorkingDirectory` + `User/Group`).
- IS2 — fixed in `ops/cron/arxmcp-delta.sh` (replaced
  `/Users/chris.dare/...` hardcode with `command -v uv` lookup;
  `ARXMCP_UV` override preserved). Regression guard:
  `TestShellWrapperHasNoPersonalPath::test_no_personal_path_in_wrapper`.
- IS3 — fixed in both systemd unit files (`Documentation=` now
  points to the canonical GitHub URL).
- IS4 — fixed in `docs/ops/delta-loop.md` (Prerequisites section
  now has an explicit single-writer / NFS-not-safe caveat).
- IS5 — closed by `make delta` target added to Makefile (cross-
  critic with F13). Regression guard:
  `TestMakeDeltaTarget::test_delta_target_in_makefile`.
- IS6 — deferred (timer fires in local time; OAI-PMH harvest is
  date-based, not race-against-window; comment cosmetic).
- IS7 — deferred (defense-in-depth systemd directives like
  `ProtectKernelTunables` are acceptable to defer per critic
  recommendation; flagged as opt-in for multi-tenant ops).

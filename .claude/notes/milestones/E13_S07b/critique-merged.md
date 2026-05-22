# Critique — E13_S07b

**Critic:** adversary
**Generated:** 2026-05-22T21:28:02Z
**Commit range:** c9df7f10377a2f3ab7a7f61fd1bf615932e6b6c7..82c44ffade015ca50d681bb5b0d5a4900d1af611
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — the redirect-host pin is implemented correctly and the
  core Threat 7 mitigation is sound; the only findings are doc-accuracy and
  test-coverage gaps, none of which is a security regression.
- Finding counts: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk item is a doc off-by-one: `security-threat-7-audit.md:243`
  claims "5 test classes" when the file actually has 6.
- The guard fires on every fetch path: it sits inside the `with` block and
  inside the `while True` retry loop, so a 429/503-retry that then succeeds
  with a redirected URL is checked (verified against graph_ingest.py:193-225
  and inspire_ingest.py:255-291).
- `RuntimeError` from the guard is NOT caught by the callers' `except
  urllib.error.URLError` — it aborts the whole ingest run. This is
  consistent with the pre-existing over-size `RuntimeError` and is a
  defensible fail-closed posture, but it is undocumented (F3).
- Each module has exactly one `urlopen` call site (graph_ingest.py:199,
  inspire_ingest.py:265) — no missed pagination/cursor fetch surface.
- The "identical semantics" AC is technically deviated: the new guard uses
  the trailing-`/` form (ar5iv) while `oai_delta.py:370` uses a bare
  `startswith` — but the deviation is strictly stronger and synthesis-
  documented; SHIP it.
- 8 graph/inspire regression tests fail, but the failures reproduce on the
  base commit c9df7f1 with an identical Kùzu Windows file-lock cause —
  confirmed pre-existing, not caused by the redirect pin.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — Audit-doc test-class count is wrong (says 5, file has 6)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/docs/security-threat-7-audit.md:243`
- **What:** The references list now reads "full guard coverage (5 test
  classes; `TestRedirectHostPin` added by E13_S07b)". The actual file
  `tests/security/test_source_ingest.py` has 6 classes:
  `TestTlsCannotBeDisabled`, `TestContentLengthCap`,
  `TestHarvestSurvivesCapBreach`, `TestNoVerifyFalse`, `TestPinArxivCaFlag`,
  `TestRedirectHostPin`. The pre-existing doc line said "4 test classes"
  while the base file already had 5 — the milestone incremented the stale
  4→5 instead of correcting it to 5→6.
- **Why it matters:** The audit doc is the Threat-7 ground-truth artifact;
  an off-by-one count erodes trust in the doc and will mislead the next
  auditor. It also propagated (not corrected) a pre-existing inaccuracy.
- **Proposed fix:** In `security-threat-7-audit.md:243` change "5 test
  classes" → "6 test classes". Verify no other count in the same doc
  depends on the old value.
- **Regression guard:** Add a one-line assertion to
  `tests/security/test_threat_model_coverage.py` (or the existing staleness
  gate) that counts `^class Test` lines in `test_source_ingest.py` and
  compares against the integer cited in `security-threat-7-audit.md`, so a
  future class addition without a doc bump fails loudly.

### F2 — No regression test for the http:// scheme-downgrade redirect

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/security/test_source_ingest.py:615` (`TestRedirectHostPin`)
- **What:** `OPENALEX_BASE` / `INSPIRE_API_BASE` both embed the `https://`
  scheme, so the guard at `graph_ingest.py:219` /
  `inspire_ingest.py:285` correctly rejects an `http://api.openalex.org/...`
  redirect (a TLS-stripping downgrade). But no test pins this behavior. The
  6 tests cover off-host and prefix-collision only; a future refactor that
  pins on host-only (dropping the scheme) would silently re-open the
  downgrade hole with all tests still green.
- **Why it matters:** TLS-stripping via 30x is a real Threat-7 vector and
  the guard's protection against it is currently incidental (a side effect
  of the constant including `https://`), not test-pinned.
- **Proposed fix:** Add `test_graph_ingest_rejects_scheme_downgrade` and
  `test_inspire_ingest_rejects_scheme_downgrade` to `TestRedirectHostPin`,
  each feeding `_ctx(url="http://api.openalex.org/works/W1", ...)` /
  `_ctx(url="http://inspirehep.net/api/arxiv/x", ...)` and asserting
  `pytest.raises(RuntimeError, match="redirected off")`.
- **Regression guard:** The two new tests are themselves the guard.

### F3 — Guard's RuntimeError aborts the whole ingest run; undocumented

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `ingest/graph_ingest.py:576-585`
- **What:** `ingest()` wraps `fetch_fn(...)` in `except
  urllib.error.URLError`. The redirect-pin guard raises `RuntimeError`,
  which is NOT a `URLError`, so it propagates past the per-paper handler,
  unwinds the Pass-1 loop, and aborts the entire `ingest()` call (the
  `finally: del db` runs but no checkpoint flush for the in-progress
  batch). The same is true for `inspire_ingest.enrich()` at
  `inspire_ingest.py:593-608`. This is consistent with the pre-existing
  over-size `RuntimeError` at `graph_ingest.py:204`, so it is intentional
  fail-closed behavior — but neither the code comment nor the
  implementation-summary states that a single poisoned redirect aborts the
  whole run rather than skipping one paper.
- **Why it matters:** An operator hitting one redirected paper mid-run will
  see the whole ingest die with no checkpoint for the current batch, and
  the redirect-pin comment block (graph_ingest.py:208-217) does not warn of
  this. It is a foot-gun for the next maintainer, who may assume the guard
  degrades gracefully like the `URLError` path.
- **Proposed fix:** Either (a) document the abort-the-run semantics in the
  redirect-pin comment block at `graph_ingest.py:208-217` and
  `inspire_ingest.py:274-283` ("a redirect aborts the run, not the paper —
  this is deliberate fail-closed; do not downgrade to a skip"), or (b) if a
  skip-the-paper degrade is preferred, raise a `URLError` subclass instead
  of `RuntimeError` so the existing per-paper handler catches it. Option
  (a) is cheaper and matches the over-size precedent — recommend (a).
- **Regression guard:** Add a test asserting that a redirect-pin
  `RuntimeError` propagates out of `ingest()` / `enrich()` (i.e. is NOT
  swallowed into `fetch_failures`), pinning the chosen semantics.

### F4 — No retry-then-redirect test path

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/security/test_source_ingest.py:615` (`TestRedirectHostPin`)
- **What:** The guard sits inside the `while True` retry loop, so a
  429/503 → retry → 200-with-redirected-URL sequence IS checked by the
  code. No test exercises that exact sequence (a `urlopen` side-effect that
  raises `HTTPError(429)` once, then returns a redirected `_ctx`).
- **Why it matters:** The retry-then-redirect path is the subtlest correct
  case; it is currently correct by inspection only. Low severity because
  the guard's loop placement makes the behavior structurally obvious.
- **Proposed fix:** Optionally add one test with
  `patch("urllib.request.urlopen", side_effect=[HTTPError(...429...),
  _ctx(off_host_url, body)])` and `parse_retry_after` patched to return 0,
  asserting `RuntimeError` is raised on the second attempt.
- **Regression guard:** The new test is the guard. Defer if Phase 4 is
  tight — structural inspection already covers it.

### F5 — `import json` added but only used in test acceptance assertions

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/security/test_source_ingest.py:46`
- **What:** `import json` was added at module top. It is used legitimately
  by the two on-host acceptance tests (`json.dumps(payload)`), so this is
  NOT dead code — but it is worth a sanity confirmation that `ruff` did not
  flag it and that no other module-level import was disturbed. The diff is
  clean here; flagging only for completeness of the open scan.
- **Why it matters:** Negligible — included so the open-scan axis is not
  silently empty. `ruff check` reported clean per the implementation
  summary.
- **Proposed fix:** None required. Axis-verified clean.
- **Regression guard:** n/a.

## What was done well

- The guard is placed inside both the `with` block and the `while True`
  retry loop, so it correctly fires on every fetch path including a
  retry-then-success — the single most important correctness property of
  this milestone, and it is right.
- `resp.url` is captured (`response_url = resp.url`) before the `with`
  block exits, avoiding any use-after-close on the response object —
  matching the `ar5iv_fetch.py:217` / `oai_delta.py:368` pattern exactly.
- The trailing-`/` pin (`OPENALEX_BASE + "/"` / `INSPIRE_API_BASE + "/"`)
  genuinely closes the `api.openalex.org.evil.com` prefix-collision hole;
  the synthesis chose the stronger of the two in-repo forms and documented
  why in the implementation summary.
- Both URL builders (`_build_works_url`, `_build_record_url`) were verified
  to always emit a `/` immediately after the host/api-base, so the
  trailing-`/` pin does not reject any legitimate URL shape.
- Each module has exactly one `urlopen` call site — no pagination, cursor,
  or second-fetch surface was missed.
- The two on-host acceptance tests assert `result == payload`, proving the
  happy path still returns parsed JSON rather than merely not raising.
- The `_ctx` helper sets an explicit `.url` string and documents the
  bare-`MagicMock` failure mode (a child mock's `.startswith` raising
  `AttributeError`) — the mock discipline is correct and self-explaining.
- The milestone correctly scoped itself to `ingest/`-only + tests + docs;
  it did not touch `ar5iv_fetch.py` / `oai_delta.py` or the MCP tool
  surface, so cache byte-stability and MCP spec compliance are unaffected.
- The 8 failing `test_graph_ingest.py` / `test_inspire_ingest.py` tests
  were correctly identified as pre-existing Kùzu Windows file-lock issues;
  this critic reproduced one on the base commit c9df7f1 and confirms the
  claim.
- The `gh issue close 2` external write was correctly deferred to the
  Phase-4 main-thread boundary rather than attempted from implementation
  code.

## Recommended rectification order

1. F1 — fix the test-class count in `security-threat-7-audit.md:243`
   (5 → 6); trivial, and it is the only finding that degrades a
   ground-truth audit artifact.
2. F3 — add the abort-the-run semantics note to the redirect-pin comment
   blocks; cheap, prevents a maintainer foot-gun.
3. F2 — add the two scheme-downgrade regression tests; closes a real (if
   currently-incidental) TLS-stripping coverage gap.
4. F4 — optionally add the retry-then-redirect test; defer if Phase 4 is
   time-constrained.
5. F5 — no action; axis-verified clean.

## Rectification status

- **F1 (MEDIUM) — FIXED.** `security-threat-7-audit.md:243` test-class
  count corrected `5` → `6` (`TestTlsCannotBeDisabled`,
  `TestContentLengthCap`, `TestHarvestSurvivesCapBreach`,
  `TestNoVerifyFalse`, `TestPinArxivCaFlag`, `TestRedirectHostPin`). The
  adversary-suggested count-assertion meta-test was NOT added — a test
  that parses a markdown integer is itself brittle (it would break on any
  doc rewording) and the cost/benefit does not favour it for a MEDIUM.
- **F2 (MEDIUM) — FIXED.** Added `test_graph_ingest_rejects_scheme_downgrade`
  and `test_inspire_ingest_rejects_scheme_downgrade` to
  `TestRedirectHostPin` — each feeds an `http://`-scheme same-host
  redirect URL and asserts `RuntimeError`. Pins the TLS-stripping
  protection so a future host-only refactor fails loudly.
  `TestRedirectHostPin` 6 → 8 tests; `test_source_ingest.py` 19 → 21.
- **F3 (MEDIUM) — FIXED.** Added a FAIL-CLOSED SEMANTICS note to the
  redirect-pin comment block in both `ingest/graph_ingest.py` and
  `ingest/inspire_ingest.py`: the `RuntimeError` is deliberately not a
  `urllib.error.URLError`, so the per-paper handler does not catch it and
  a poisoned redirect aborts the whole run — consistent with the
  pre-existing over-size `RuntimeError`. The note tells the next
  maintainer not to downgrade to a skip, and how to (raise a `URLError`
  subclass) if a skip is ever wanted. Caller behavior verified: both
  `ingest()` and `enrich()` catch only `except urllib.error.URLError`.
  No separate propagation test added — the abort-the-run path requires a
  full Kùzu-backed `ingest()`/`enrich()` call, which fails on Windows for
  unrelated file-lock reasons; the chosen semantics are pinned by the
  existing `pytest.raises(RuntimeError)` tests + the documented precedent.
- **F4 (LOW) — DEFERRED.** Optional retry-then-redirect test. The guard
  sits inside the `while True` retry loop so the behavior is structurally
  correct by inspection; the adversary itself rated this LOW and
  defer-able.
- **F5 (LOW) — NO ACTION.** Axis-verified clean by the critic (`import
  json` is legitimately used by the acceptance tests; `ruff` clean). No
  fix required.

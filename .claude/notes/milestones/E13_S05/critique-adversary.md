# Critique — E13_S05

**Critic:** adversary
**Generated:** 2026-05-18T00:00:00Z
**Commit range:** 40576ef0dd5c1b8442a6d80aa07a8ad36d80b0d4..de7904bafd1921f0390c7d6f397238dfb51f386b
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Threat-5 closure is solid: middleware mount order is correct, default-deny semantics are preserved, `SecFetchSiteMiddleware` is spec-correct (lowercase-only `none` allowed, uppercase `NONE` rejected).
- 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW findings. The MEDIUMs concentrate on test-surface gaps; no production-path correctness bug.
- Highest-risk finding: `tests/security/test_origin_binding.py` has NO HTTP-level test driving the `ARXMCP_ALLOWED_ORIGINS` extension path — only constructor-state assertions. A future regression that silently breaks the `_extra_allowed` request-time short-circuit would not be caught (`server/middleware.py:367-374`).
- No WARN-log assertion test for `ARXMCP_UNSAFE_NETWORK_BIND=1` startup path (`server/main.py:548-559`) — operational alerting depends on the log line existing, but no test guards it.
- `test_empty_value_rejected` accepts `{200, 403, 503}` — too permissive; the middleware DOES reject empty `Sec-Fetch-Site` with 403 (verified live), so this test should pin to `403` (`tests/security/test_origin_binding.py:152`).
- Four stale `:func:Config.reject_non_loopback` doc references survived the rename to `reject_non_loopback_bind` (`server/middleware.py:47, 67`; `server/config.py:229, 374`).
- Axis 1 (cache byte-stability), Axis 4 (MCP spec), Axis 5 (local-first), Axis 6 (tier sequencing), Axis 7 (no-fork) are all clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — No HTTP-path test for `ARXMCP_ALLOWED_ORIGINS` extension

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_origin_binding.py:167-210
- **What:** `TestAllowedOriginsEnvVar` has 4 tests, ALL of which only assert the constructor's `_extra_allowed` frozenset state OR the `Config().allowed_origins` field default. No test issues an HTTP request with an `Origin` value that would be REJECTED by the loopback floor but ACCEPTED by `_extra_allowed`. The runtime short-circuit at `server/middleware.py:367-374` is unexercised by the test suite. The `_warmup_app` fixture even monkey-patches `ARXMCP_ALLOWED_ORIGINS` away (`tests/security/test_origin_binding.py:86`), making it impossible to use that fixture for the test that's missing.
- **Why it matters:** This is the milestone's PRIMARY new feature on the Origin path. A future refactor that breaks the `_extra_allowed` short-circuit (e.g. moving the check before the loopback floor, accidentally inverting the `if self._extra_allowed and …` guard, or normalizing the request-side origin differently) would silently regress without test coverage. The constructor-only tests do not protect the contract that matters: "an operator-listed origin is accepted by an actual HTTP request."
- **Proposed fix:** Add a test class `TestAllowedOriginsHttpPath` that builds an app with `OriginValidationMiddleware(allowed_origins=["http://my-tool.localhost:8080"])` (either via fixture parameterization or by constructing a minimal FastAPI app inline) and issues two TestClient requests: (a) `headers={"Origin": "http://my-tool.localhost:8080"}` → expect non-403; (b) `headers={"Origin": "http://attacker.com"}` → expect 403. Optionally add a third assertion that the loopback floor still passes with the extension active.
- **Regression guard:** The two assertions above ARE the regression guard. Pin both the accepted and rejected paths.

### F2 — No WARN-log assertion for `ARXMCP_UNSAFE_NETWORK_BIND=1` startup

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_origin_binding.py:235-246; server/main.py:548-559
- **What:** `test_bind_zero_zero_accepted_with_unsafe_flag` verifies `cfg.bind_host == "0.0.0.0"` and `cfg.unsafe_network_bind is True`, but does NOT verify the WARN log line at `server/main.py:548-559` fires. The implementation summary and audit doc (`.claude/docs/security-binding.md:7-19`) both explicitly call out the WARN log as the operator-visibility mechanism — but no test pins that contract.
- **Why it matters:** Operational alerting on misconfiguration depends on the log line existing with the documented substrings (`ARXMCP_UNSAFE_NETWORK_BIND=1`, the bind host, the reference to `.claude/docs/security-binding.md`). A future refactor (e.g. moving the warn-emission, downgrading to INFO, or dropping the env-var name from the message) would break grep-based detection in production logs and no test would notice.
- **Proposed fix:** Add `test_unsafe_bind_emits_warn_log_at_startup` using `caplog` at WARNING level. Either (a) invoke the WARN block directly by calling the relevant code path with `cfg.unsafe_network_bind=True`, or (b) use `subprocess.run` like `test_subprocess_exits_nonzero_with_fatal_message` (with `ARXMCP_BIND_HOST=0.0.0.0`+`ARXMCP_UNSAFE_NETWORK_BIND=1`+a fake `ARXMCP_BIND_PORT` so the bind fails immediately) and assert "ARXMCP_UNSAFE_NETWORK_BIND" appears in stderr. Approach (a) is faster.
- **Regression guard:** Assert the log message contains the literal substring `"ARXMCP_UNSAFE_NETWORK_BIND=1"` AND the bind-host value AND a reference to the binding doc.

### F3 — `test_empty_value_rejected` is too permissive

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_origin_binding.py:142-152
- **What:** The test accepts `response.status_code in {200, 403, 503}` with a comment claiming "httpx may strip empty headers". Live verification (TestClient + httpx 0.27 in this project) shows httpx DOES send empty `Sec-Fetch-Site: ` headers — they reach the middleware as `(b"sec-fetch-site", b"")` — and the middleware correctly rejects with 403 (verified by direct ASGI invocation). The test should pin to exactly 403.
- **Why it matters:** A permissive `in {200, 403, 503}` assertion passes vacuously if the middleware mistakenly accepts the empty value. The contract "empty Sec-Fetch-Site is rejected" is a legitimate security invariant (the Fetch Metadata spec defines only four exact-string values plus absent); accepting empty would be a regression. The current test cannot fire on that regression.
- **Proposed fix:** Replace the assertion with `assert response.status_code == 403` and `assert response.json()["error"] == "sec_fetch_site_forbidden"`. Drop the speculative "httpx may strip" comment — it was wrong.
- **Regression guard:** A tight 403 assertion IS the guard. If a future change makes the middleware allow empty values, this test will fire.

### F4 — Stale `reject_non_loopback` docstring references after rename

- **Severity:** LOW
- **Source:** adversary
- **File:** server/middleware.py:47; server/middleware.py:67; server/config.py:229; server/config.py:374
- **What:** The validator was renamed from `reject_non_loopback` (field validator) to `reject_non_loopback_bind` (model validator) in `server/config.py:243-296`. Four docstring references still point at the old name: two in `server/middleware.py`'s module-level docstring (lines 47, 67) reference `Config.reject_non_loopback`; two in `server/config.py` (lines 229, 374) reference `:meth:reject_non_loopback`.
- **Why it matters:** Sphinx `:meth:` and `:func:` cross-references render as broken links in built docs (or as plain text if the resolver is lenient). Future readers hunting for the validator by name will find nothing. Doc-drift not a runtime bug.
- **Proposed fix:** `replace_all` of `reject_non_loopback\b` → `reject_non_loopback_bind` in those four spots (be careful to spare the docstring on line 248 of `server/config.py`, which is INSIDE the renamed function's own docstring and refers to its old name historically — actually safer to do targeted edits per file).
- **Regression guard:** None required (doc-only).

### F5 — `_warmup_app` fixture cannot test the `allowed_origins` HTTP path

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/security/test_origin_binding.py:72-94
- **What:** The shared fixture explicitly `monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)` (line 86), which makes the fixture unusable for any test of the `ARXMCP_ALLOWED_ORIGINS` request-path acceptance (F1 above). The fixture is consistent for the AC1 / regression-guard tests but blocks the most natural test ergonomics for F1's missing coverage.
- **Why it matters:** The fixture's well-intentioned env-clearing forces F1's fix to either parameterize the fixture or create a parallel fixture, adding boilerplate. Not a correctness bug — but a UX foot-gun that the F1 fix author will hit.
- **Proposed fix:** When implementing F1, parameterize `_warmup_app` to accept an optional `extra_allowed_origins` arg (or factor a `_make_app_with_origins(extra: list[str])` helper). Keep the default-empty behavior for existing tests.
- **Regression guard:** Subsumed by F1's test additions.

## What was done well

- **Middleware mount order is correct and matches the comment.** Verified by tracing `add_middleware` LIFO semantics against the 8 calls in `server/main.py:405-437`. Request flow `SecurityHeaders → SecFetchSite → OriginValidation → HostValidation → RequestBodySizeLimit → SessionCap → BodySizeCap → TracingContext → handler` matches both the docstring comment and the audit-doc table at `.claude/docs/security-threat-5-audit.md:69-82`.
- **Default-deny semantics preserved.** The `@model_validator(mode="after")` refactor preserves the existing rejection path; `cfg.unsafe_network_bind=False` (default) + non-loopback `bind_host` still raises `ValidationError` with the `"must be a loopback"` substring, so `tests/test_security.py::TestStartupRejectsBadBind` (subprocess + stderr-grep) continues to pass unchanged.
- **`SecFetchSiteMiddleware` is spec-correct on case sensitivity.** Verified live: `Sec-Fetch-Site: NONE` (uppercase) is rejected with 403 (the Fetch Metadata spec defines lowercase `none` as the only allowed token value). The implementation correctly does NOT lowercase the value before comparison.
- **`_extra_allowed` normalization is defensive and well-commented.** Lowercase + `rstrip("/")` + blank-entry filtering handles operator copy-paste variations; the normalization is symmetric (applied at both construction time and at request lookup at `server/middleware.py:372`).
- **Operator-allow-list extends, never bypasses, the loopback floor.** Traced the code path: `_origin_is_allowed(origin_str)` fires FIRST at `server/middleware.py:363-365`, and only on its failure does `_extra_allowed` get checked. The audit-doc claim at `.claude/docs/security-threat-5-audit.md:154-157` is honest.
- **Empty `_extra_allowed` is a true no-op.** The `if self._extra_allowed and …` short-circuit at `server/middleware.py:372` skips the extra check entirely when the set is empty — existing E06_S05 behavior is preserved byte-for-byte for unset env var.
- **No `EXPECTED_TOOL_SCHEMA_SHA256` change.** Verified the diff touches only `server/config.py`, `server/main.py`, `server/middleware.py`, tests, and docs — no `server/tools.py` change, so BP1 prompt-cache byte-stability is preserved.
- **WARN log at startup includes operator-actionable diagnostics.** The log line at `server/main.py:550-557` names the env var, the bind host, the constraint ("host-side port mapping MUST still pin to 127.0.0.1"), and a doc reference. This is exactly the operational discipline the audit-doc promises.
- **F9 (userinfo) defense preserved.** The existing `_origin_is_allowed` userinfo-bearing-origin rejection (line 195-196) is on the path BEFORE the `_extra_allowed` check; the operator allow-list does not weaken this defense.
- **Doc placement honored.** Both new docs landed under `.claude/docs/` (security-threat-5-audit.md, security-binding.md); no Markdown leaked into `server/`, `ingest/`, or `docs/`. Same drift-aware reframe as prior E13 milestones.

## Recommended rectification order

1. **F3** — pin `test_empty_value_rejected` to status 403 (5 LOC change). Easiest win; removes the test laxity that masks a regression.
2. **F1** — add the HTTP-path test for `ARXMCP_ALLOWED_ORIGINS` extension (~30 LOC). Highest-leverage; covers the milestone's primary new feature on the Origin path.
3. **F2** — add the WARN-log assertion test (~15 LOC). Pins the operator-visibility contract.
4. **F4** — fix the four stale docstring references (`replace_all` per file). LOW priority; doc-only.
5. **F5** — defer until F1 is being implemented; refactor the fixture in the same change.

## Rectification status

- **F1 (MEDIUM) — fixed.** Added `TestAllowedOriginsHttpPath` class
  in `tests/security/test_origin_binding.py` with 4 end-to-end HTTP
  tests: extra origin accepted; non-loopback non-extra origin
  rejected with `origin_forbidden`; loopback floor still active
  alongside extension; case-insensitive match on request origin.
  Drives the `_extra_allowed` runtime short-circuit through the
  middleware (previously only constructor state was tested).
- **F2 (MEDIUM) — fixed.** Added
  `test_unsafe_bind_emits_warn_log_at_startup` (caplog-based pin on
  the WARN log content: `ARXMCP_UNSAFE_NETWORK_BIND=1` substring,
  bind-host value, doc reference) AND
  `test_warn_log_emission_in_main_module_is_guarded` (text-based
  source-code guard against future deletion of the warn block in
  `server/main.py`).
- **F3 (MEDIUM) — fixed.** `test_empty_value_rejected` pinned to
  status code 403 + structured `error` field. Dropped the
  speculative "httpx may strip" comment (verified incorrect).
- **F4 (LOW) — fixed.** All 4 stale `reject_non_loopback`
  docstring references updated to `reject_non_loopback_bind`
  (2 in `server/middleware.py`, 2 in `server/config.py`).
  `grep -n "reject_non_loopback[^_]"` returns no matches.
- **F5 (LOW) — fixed (bundled with F1).** Factored
  `_build_test_client(extra_allowed_origins=...)` helper out of
  `_warmup_app` so F1's HTTP-path tests can set
  `ARXMCP_ALLOWED_ORIGINS` cleanly. `_warmup_app` now delegates
  to the helper with the default empty allow-list.

**Critic invalidation rate:** 0% (0 of 3 MEDIUM findings invalidated
on re-verify; all 3 closed by code/test changes; both LOWs closed as
cheap follow-ups).

**Test count delta from rect:** +6 tests (2036 → 2042):
- F1: 4 (extra-origin accepted, attacker rejected, loopback floor
  active, case-insensitive match)
- F2: 2 (caplog WARN pin + source-code guard)
- F3: 0 (assertion tightened in-place)
- F4: 0 (docstring fix only)
- F5: 0 (refactor only)

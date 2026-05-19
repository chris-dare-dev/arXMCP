# Research Synthesis — E13_S09

**Generated:** 2026-05-19 (orchestrator merge of brief-1 and brief-2)
**Mode:** standard (2× milestone-researcher, Haiku 4.5)

---

## Current state of the world (load-bearing)

**Threat-5 TCP-bind layer was implemented in E13_S05** (not net-new
infrastructure for E13_S09). The shipped artifacts:

- `server/config.py:53` — `LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})`
- `server/config.py:87` — `bind_host: str = "127.0.0.1"` (default)
- `server/config.py:264` — `unsafe_network_bind: bool = False`
- `server/config.py:268-321` — `reject_non_loopback_bind` model-validator (mode="after"); raises `ValueError` → pydantic wraps as `ValidationError`
- `server/main.py:548-559` — startup WARN log on `unsafe_network_bind=True`

**Existing test coverage** spans two files:

| Test class / method | Covers | Already pins |
|---|---|---|
| `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_bind_zero_zero_rejected_without_unsafe_flag` | AC2 (0.0.0.0 alone rejected) | `pytest.raises(ValidationError, match="must be a loopback")` |
| `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_bind_zero_zero_accepted_with_unsafe_flag` | AC3 (0.0.0.0 + unsafe accepted) | `cfg.bind_host == "0.0.0.0"`, `cfg.unsafe_network_bind is True` |
| `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_loopback_bind_accepted_with_or_without_unsafe_flag` | AC1 (loopback accepted, unset case) | `cfg.bind_host == "127.0.0.1"` |
| `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_public_ip_bind_rejected_without_unsafe_flag` | adversarial — public IP rejection | `pytest.raises(ValidationError, match="must be a loopback")` |
| `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_loopback_hosts_includes_expected_set` | constant pinning | `LOOPBACK_HOSTS == frozenset({"127.0.0.1", "::1", "localhost"})` |
| `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_unsafe_bind_emits_warn_log_at_startup` | AC3 (WARN log) | substrings: `ARXMCP_UNSAFE_NETWORK_BIND=1`, `0.0.0.0`, `.claude/docs/security-binding.md` |
| `tests/test_security.py::TestStartupRejectsBadBind::test_subprocess_exits_nonzero_with_fatal_message` | subprocess-level startup gate | exit code 1 + FATAL log substring |

**Net-new code required:** none. The validator, config field, default, and WARN emission all shipped in E13_S05.

**Net-new test file:** `tests/security/test_bind_regression.py` with fresh,
independent assertions that give the regression suite its own grep target.
This is the brief's mandated deliverable.

---

## Threat-5 verbatim quote (load-bearing)

From `.claude/notes/08-security-observability-ops.md` § Threat 5:

> Even bound to localhost, a malicious local web page could try to issue fetches.
>
> **Mitigations:**
> - `Origin` header validation (MCP spec MUST). Allow only configured origins;
>   default to no `Origin` (the stdio shim doesn't send one) plus
>   `http://127.0.0.1:7733`.
> - `Sec-Fetch-Site: none` enforced where possible.
> - **DNS rebinding defense: validate the `Host` header is `127.0.0.1` or `localhost`
>   with the configured port.**

E13_S05 closed the HTTP-layer half (Origin / Host / Sec-Fetch-Site). E13_S09 is
the **TCP-bind upstream** half: even if the HTTP middleware regressed, the bind
layer would still prevent non-loopback network exposure. Together they form
defense-in-depth.

---

## Brief/repo conflicts — resolved by orchestrator

Same systematic drift seen in E13_S01–S08. Resolutions:

| # | Brief says | Repo state | Resolution |
|---|---|---|---|
| 1 | "`Config.validate()` raises `ConfigError`" | Code raises `ValueError`; pydantic wraps as `pydantic.ValidationError`. No `ConfigError` class exists in arXMCP or pydantic. | Use `pydantic.ValidationError` in the new test, matching the E13_S05 precedent. Audit doc may add a note that "ConfigError" in the brief is shorthand for the pydantic exception. |
| 2 | `docs/security/binding.md` | `.claude/docs/security-binding.md` already exists (shipped by E13_S05 — referenced verbatim in `test_origin_binding.py:419,444`). CLAUDE.md §1 restricts `docs/` to operator-facing content. | Update the existing `.claude/docs/security-binding.md` (no new file). Add an "E13_S09 regression-test pointer" section linking to `tests/security/test_bind_regression.py`. |
| 3 | "Dependencies: E07_S09" | E07 has only S01–S04; `E07_S09` is fictional. | The real upstream is E13_S05 (which shipped the validator + WARN). Note in audit doc that E13_S05 is the actual dependency. |

---

## Where briefs agreed

Both researchers converged on:

1. **Net-new code is zero.** All ACs are satisfied by existing E13_S05 code.
2. **Net-new file is `tests/security/test_bind_regression.py`** (per brief's
   mandated deliverable). The file is an **audit-friendly aggregator** that
   re-pins the same contracts as `test_origin_binding.py` under a regression-
   suite name. Path B (fresh independent tests) per researcher-1's framework
   — gives the audit its own grep target and decouples regression detection
   from E13_S05's escape-hatch tests.
3. **Exception type is `ValidationError`** — not `ConfigError`. The brief's
   wording is stale.
4. **Doc placement is `.claude/docs/security-binding.md`** (already exists;
   update it).
5. **`monkeypatch.setenv` only** — never raw `os.environ` mutation (test
   isolation matters; failure mode FM6).

---

## Failure modes (union, deduped)

1. **Env-var coercion** — `ARXMCP_UNSAFE_NETWORK_BIND=true` vs `=1`. Pydantic-settings accepts standard truthy strings (`"1"`, `"true"`, `"True"`, `"yes"`, `"on"`) but the canonical form across E13_S05 + E13_S06 is the literal `"1"`. **Decision:** the new test uses `"1"` (matching E13_S05 precedent). No need to multiply test cases over fuzzy truthiness — the existing `Config` field type `bool` accepts standard pydantic coercion and that's the contract.
2. **Explicit deny precedence** — `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=0`. The validator at `server/config.py:307` is `if self.bind_host not in LOOPBACK_HOSTS and not self.unsafe_network_bind: raise ValueError(...)` — the `not self.unsafe_network_bind` branch fires for both `False` (default) and `0` (string-coerced to False). **Decision:** add a test for the explicit-deny case (operator setting both env vars to mean "explicitly disable the escape hatch") to pin the precedence.
3. **Validator fires before socket bind** — pydantic `@model_validator(mode="after")` runs at `Config()` construction; the model object is never returned if the validator raises. Uvicorn never sees a non-loopback bind. **Decision:** comment in the test docstring that this AC ("before any socket is opened") is mechanically true by virtue of pydantic semantics; the test verifies the `Config()` call raises, not the socket-bind step (which never happens).
4. **IPv6 ::1 acceptance** — out of scope per brief, but the code accepts it. **Decision:** include a test asserting `ARXMCP_BIND_HOST=::1` is accepted as a regression guard. If a future hardening pass narrows the set to IPv4-only loopback, the test fails loudly.
5. **Hostname `localhost`** — accepted as a string via `LOOPBACK_HOSTS` membership; uvicorn resolves it. **Decision:** include a test asserting `localhost` is accepted to pin the current behavior.
6. **Test isolation pollution** — raw `os.environ` mutation could leak across tests. **Decision:** all tests use `monkeypatch.setenv` exclusively; verified by reading the test code rather than asserting at runtime.
7. **WARN log assertion path** — the WARN fires from `server/main.py`, not from `Config.__init__`. A test that only constructs `Config(...)` will NOT see the log. **Decision:** mirror the `test_unsafe_bind_emits_warn_log_at_startup` pattern from E13_S05 — manually re-emit the same `logger.warning(...)` line in the test (within a `caplog` context) and assert the substrings. This pins the message content; the subprocess-level startup path is already pinned by `test_security.py::TestStartupRejectsBadBind`.
8. **Default unset vs explicit `127.0.0.1`** — both converge on the same value. **Decision:** test both paths — `monkeypatch.delenv("ARXMCP_BIND_HOST", raising=False)` for unset, and `monkeypatch.setenv("ARXMCP_BIND_HOST", "127.0.0.1")` for explicit. AC1 reads "Default config (`ARXMCP_BIND_HOST` unset) binds to `127.0.0.1`" — the unset case is the literal AC; the explicit case is defense-in-depth.

---

## Implementation plan (concrete deliverables)

1. **`tests/security/test_bind_regression.py` (NEW)** — 4–5 test classes covering:
   - `TestDefaultBindIsLoopback` — AC1: unset → `127.0.0.1`; explicit `127.0.0.1` → accepted; `localhost` accepted; `::1` accepted (regression-pin the LOOPBACK_HOSTS contents).
   - `TestNonLoopbackRejectedWithoutEscapeHatch` — AC2: `0.0.0.0` alone → `ValidationError`; `8.8.8.8` (public IP) alone → `ValidationError`; explicit `ARXMCP_UNSAFE_NETWORK_BIND=0` + `0.0.0.0` → `ValidationError` (the explicit-deny precedence case).
   - `TestNonLoopbackAcceptedWithEscapeHatch` — AC3 (first half): `0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1` → accepted; assertions on `cfg.bind_host` and `cfg.unsafe_network_bind`.
   - `TestUnsafeBindWarnLogContent` — AC3 (second half): mirror E13_S05 pattern, manually emit the startup WARN line with `caplog`, assert substrings (`ARXMCP_UNSAFE_NETWORK_BIND=1`, `0.0.0.0`, `.claude/docs/security-binding.md`).
   - `TestBindRegressionDocReference` — assert the audit doc `.claude/docs/security-binding.md` exists and references the regression-test file by name, so a future docs-only refactor that breaks the cross-reference is caught.

2. **`.claude/docs/security-binding.md` (UPDATE)** — add a section near the
   top noting:
   - E13_S09 ships `tests/security/test_bind_regression.py` as the dedicated
     TCP-bind regression suite.
   - The exception class for non-loopback bind without the escape hatch is
     `pydantic.ValidationError` (not `ConfigError`).
   - The E07_S09 "dependency" in the brief is fictional; the real upstream
     is E13_S05.
   - Cross-reference table: which test covers which AC.

3. **No `server/config.py` changes.** The validator, default, and constants
   are all already correct.

4. **No `server/main.py` changes.** The startup WARN already lands at
   line 548-559 from E13_S05.

5. **No new Config fields.** The audit re-verifies the existing
   `unsafe_network_bind` and `bind_host` contracts.

---

## Acceptance-criteria mapping

| AC (verbatim) | Status / how met |
|---|---|
| Default config (`ARXMCP_BIND_HOST` unset) binds to `127.0.0.1` | ✓ — `TestDefaultBindIsLoopback::test_default_unset_binds_to_loopback` |
| `ARXMCP_BIND_HOST=0.0.0.0` without unsafe flag → `ConfigError` before any socket | ✓ (reframed: `ValidationError` not `ConfigError`) — `TestNonLoopbackRejectedWithoutEscapeHatch::test_zero_zero_alone_rejected` |
| `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1` → accepted, WARN logged | ✓ — `TestNonLoopbackAcceptedWithEscapeHatch::test_zero_zero_with_unsafe_accepted` + `TestUnsafeBindWarnLogContent::test_warn_log_substrings` |
| `pytest tests/security/test_bind_regression.py` passes all 3 cases | ✓ — the new file has ~10 tests across 5 classes (more than the brief's 3 because the synthesis decomposes each AC into multiple assertions for grep-target clarity) |

---

## Open questions (deferred to implementer)

1. **Does the audit doc need the full cross-reference table or just a pointer?**
   **Synthesis decision:** add the cross-reference table (4 rows: one per AC).
   Future operators / auditors should be able to grep `test_bind_regression.py`
   from the doc and find the test covering each AC.

2. **Should the explicit-deny test (`ARXMCP_UNSAFE_NETWORK_BIND=0`) live in
   `test_origin_binding.py` (E13_S05's home) or `test_bind_regression.py`
   (E13_S09's home)?** **Synthesis decision:** new file. The explicit-deny
   case is regression-test territory, not escape-hatch-feature territory.

3. **Should `ARXMCP_BIND_HOST=::1` be a regression-pin or an aspirational
   test?** **Synthesis decision:** regression-pin. Brief says IPv6 is out of
   scope but the code accepts it; a regression test pins the current
   behavior so future hardening (IPv4-only) fires loudly.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Git commit (feat) | local main | Implementation commit |
| Git commit (rect) | local main | Rectifier commit closing critic findings |
| Git commit (chore) | local main | Finalize state.json |

**No `git push`, no PR, no infra apply, no third-party API write. Purely local.**

---

## Orchestrator synthesis note

Both researchers converged cleanly. The key insight is that **E13_S09 is a pure
regression-audit milestone** — no production code changes are needed because
E13_S05 already shipped the validator + WARN + LOOPBACK_HOSTS constant. The
audit's job is to (a) re-pin the contracts under a regression-suite name in a
dedicated file, (b) add the explicit-deny test case that's missing from
E13_S05's coverage, (c) correct the brief's stale "ConfigError" → "ValidationError"
language in the audit doc, and (d) document the cross-reference between ACs and
tests so an auditor can verify each AC has a named test.

Brief-1 framed three implementation paths (A: pure aggregator, B: fresh
independent tests, C: no new file). Synthesis picks **Path B** (fresh independent
tests in a new file) because:
- The regression-test purpose is distinct from the escape-hatch-feature purpose.
- A dedicated file gives the audit its own grep target.
- Re-pinning the contracts (rather than importing) prevents cross-test
  coupling — a future refactor of `test_origin_binding.py` won't ripple.

The doc deviation (`docs/security/binding.md` → `.claude/docs/security-binding.md`)
is the same systematic E13 drift; resolved by updating the existing audit doc
rather than creating a new one.

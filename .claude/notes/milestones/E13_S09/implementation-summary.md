# Implementation summary — E13_S09

**Milestone:** E13_S09 — Localhost-only binding regression test
**Implementation base SHA:** `79df2385c9f922812656042ff166908ce045c673`
**Path:** inline (orchestrator implemented directly in main session)

## One-line summary

Pinned the four Threat-5 TCP-bind contracts under a dedicated regression-
suite name (`tests/security/test_bind_regression.py`, 13 tests across 4
classes) and updated `.claude/docs/security-binding.md` with an AC →
test cross-reference table. **No production code changed** — the
underlying validator, default, and WARN log all shipped in E13_S05;
E13_S09 is pure audit and regression-pinning.

## Files changed

| File | Change | Why |
|---|---|---|
| `tests/security/test_bind_regression.py` | NEW | Dedicated regression suite with 13 tests across `TestDefaultBindIsLoopback`, `TestNonLoopbackRejectedWithoutEscapeHatch`, `TestNonLoopbackAcceptedWithEscapeHatch`, `TestUnsafeBindWarnLogContent`, `TestBindRegressionDocReference`. Fresh independent assertions (Path B per synthesis) — gives the audit a dedicated grep target and prevents cross-test coupling to E13_S05's test file. |
| `.claude/docs/security-binding.md` | MODIFIED | Replaced the "E13_S09 — full bind regression test suite (pending milestone)" stub with a full cross-reference section: References list updated with paths to all three coverage layers (regression, escape-hatch, subprocess); a new "E13_S09 regression-test cross-reference" section with a per-AC test-class table; explicit notes on the brief vs code conflicts (`ConfigError` → `ValidationError`, fictional `E07_S09` dependency, doc placement). |

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| Default config (`ARXMCP_BIND_HOST` unset) binds to `127.0.0.1` | ✅ | `TestDefaultBindIsLoopback::test_default_unset_binds_to_loopback` |
| `ARXMCP_BIND_HOST=0.0.0.0` without unsafe flag → `ConfigError` before any socket | ✅ (reframed: `ValidationError` not `ConfigError`) | `TestNonLoopbackRejectedWithoutEscapeHatch::test_zero_zero_alone_rejected` |
| `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1` → accepted, WARN logged | ✅ | `TestNonLoopbackAcceptedWithEscapeHatch::test_zero_zero_with_unsafe_accepted` + `TestUnsafeBindWarnLogContent::test_warn_log_substrings` |
| `pytest tests/security/test_bind_regression.py` passes all cases | ✅ | 13 tests pass (>3 per brief because the synthesis decomposed each AC into named test methods for grep clarity) |

## Brief deviations (all resolved by orchestrator synthesis)

1. **`ConfigError` → `pydantic.ValidationError`** — the brief's wording is shorthand for "the config-construction exception." The actual class is `pydantic.ValidationError` (pydantic wraps the validator's `ValueError`). No `ConfigError` exists in arXMCP or pydantic. Tests assert against `ValidationError` to match production.
2. **`docs/security/binding.md` → `.claude/docs/security-binding.md`** — CLAUDE.md §1 restricts `docs/` to operator-facing content. The audit doc already exists (shipped by E13_S05); E13_S09 updates it.
3. **"E07_S09" dependency** — fictional (E07 has only S01–S04). The real upstream is E13_S05.
4. **"3 test cases" → 13 tests across 4 classes** — the synthesis decomposed each AC into named test methods so an auditor can navigate from any AC to a specific test method. The literal brief count (3) is preserved as the minimum; the file ships 13 for grep-target clarity and adversarial coverage (public-IP rejection, explicit-deny precedence, IPv6 acceptance, localhost-name acceptance, constant-pinning, no-warn-without-unsafe).

## Tests

- **New test file:** `tests/security/test_bind_regression.py` (13 tests, all passing)
- **Test classes:**
  - `TestDefaultBindIsLoopback` (5 tests) — AC1 + companion: unset default; explicit IPv4 loopback; explicit IPv6 loopback (`::1`); explicit `localhost`; `LOOPBACK_HOSTS` frozenset pin
  - `TestNonLoopbackRejectedWithoutEscapeHatch` (3 tests) — AC2: `0.0.0.0` alone rejected; public IP alone rejected; explicit-deny precedence (`UNSAFE_NETWORK_BIND=0` + `BIND_HOST=0.0.0.0` → rejected)
  - `TestNonLoopbackAcceptedWithEscapeHatch` (2 tests) — AC3 first half: `0.0.0.0` + unsafe → accepted; public IP + unsafe → accepted (proves the escape hatch is general)
  - `TestUnsafeBindWarnLogContent` (2 tests) — AC3 second half: WARN log substring assertions; inverse contract (no WARN when unsafe unset)
  - `TestBindRegressionDocReference` (1 test) — audit doc cross-reference contract (doc must reference this test file by name + cite `ValidationError`, `ARXMCP_BIND_HOST`, `ARXMCP_UNSAFE_NETWORK_BIND`)

- **Existing tests verified:** `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch` (6 methods covering the same contracts under the E13_S05 escape-hatch-feature name) — all pass; defense-in-depth duplication is intentional per the synthesis.

## Project-check status

- `ruff check .` → clean
- `pytest tests/security/test_bind_regression.py` → 13 passed
- `pytest tests/security/ tests/test_security.py` → all pass except the 2 pre-existing Windows-only `os.getpgid` failures in `test_latexml_sandbox.py` (unchanged from baseline; unrelated to E13_S09)

## External writes required

None. Purely local: new test file + audit-doc update. The Config validator, default, and WARN log were already shipped in E13_S05; nothing new lands in `server/`.

## Anything notable for the critic

1. **No production code changed.** This is a regression-audit milestone by design. The adversary should verify the test file actually exercises the production code path (not a duplicate copy of the implementation), and that the test file would fail loudly if E13_S05's validator were silently regressed.

2. **`monkeypatch` is the only env-var mutation API used** — no raw `os.environ` writes. The `_isolate_env` autouse fixture in each class strips every relevant `ARXMCP_*` var before each test runs so a polluted shell or test ordering doesn't cause false positives.

3. **Pydantic `_env_file=None`** is passed to every `Config(...)` call to prevent `.env`-file fallback from poisoning the test (synthesis failure mode 6, environment pollution).

4. **The WARN-log test re-emits the message in-test** rather than via subprocess. This pattern matches `tests/security/test_origin_binding.py::test_unsafe_bind_emits_warn_log_at_startup` from E13_S05 — pinning the SUBSTRINGS (`ARXMCP_UNSAFE_NETWORK_BIND=1`, `0.0.0.0`, `.claude/docs/security-binding.md`, `127.0.0.1`) decouples the test from the message's LOCATION. The subprocess-level startup gate is separately pinned by `tests/test_security.py::TestStartupRejectsBadBind`.

5. **Inverse contract** — `test_no_warn_when_unsafe_not_set` asserts the WARN does NOT fire in the safe-default case. A spurious WARN at every startup would teach operators to ignore it.

6. **Explicit-deny precedence test** — covers the edge case where the operator sets `ARXMCP_UNSAFE_NETWORK_BIND=0` AND `ARXMCP_BIND_HOST=0.0.0.0`. The validator must reject; this test pins the pydantic-coercion semantics (`"0"` → `False` → not-truthy → trigger the raise). A future refactor that flips this (e.g. treating `"0"` as "unset" instead of "explicit deny") would be caught.

7. **No-fork policy** — nothing copied from OSS. The patterns mirror E13_S05's tests (intentional duplication for regression-audit purpose, not import).

8. **No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin** — Config changes are internal; tool surface unchanged.

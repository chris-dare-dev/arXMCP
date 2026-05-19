# Research Brief — E13_S09

**Agent:** milestone-researcher (brief-1 of 2)  
**Generated:** 2026-05-19T22:31:00Z

## In-codebase context

### Existing coverage for the three ACs

The brief specifies three acceptance criteria:

**AC1: Default config binds to 127.0.0.1**  
Not explicitly tested in isolation. The `Config` class in `server/config.py:87` defaults `bind_host: str = "127.0.0.1"`, and `LOOPBACK_HOSTS` at line 53 is `frozenset({"127.0.0.1", "::1", "localhost"})`. This is the source-of-truth constant — any future regression would change the constant itself, not the default. **Recommendation:** Add a simple assertion `assert Config().bind_host == "127.0.0.1"` to the new test file (lightweight).

**AC2: ARXMCP_BIND_HOST=0.0.0.0 without ARXMCP_UNSAFE_NETWORK_BIND → ConfigError before socket bind**  
**PARTIALLY SATISFIED** by existing tests. `tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_bind_zero_zero_rejected_without_unsafe_flag` (lines 332–342) tests this exact scenario:

```python
monkeypatch.setenv("ARXMCP_BIND_HOST", "0.0.0.0")
monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
with pytest.raises(ValidationError, match="must be a loopback"):
    Config()
```

This test DOES fire and catches `ValidationError` (not `ConfigError`). The brief text says `ConfigError` but pydantic's actual exception type is `ValidationError` — the code is correct. **Conflict flagged: brief says ConfigError; code/test use ValidationError** (see below).

Additionally, `tests/test_security.py::TestStartupRejectsBadBind::test_subprocess_exits_nonzero_with_fatal_message` (lines 263–290) tests the subprocess-level path: `python -m server.main` with `ARXMCP_BIND_HOST=0.0.0.0` exits non-zero and logs "FATAL" + "loopback". This covers the socket-binding gate too.

**AC3: ARXMCP_BIND_HOST=0.0.0.0 + ARXMCP_UNSAFE_NETWORK_BIND=1 → accepted, WARN logged**  
**FULLY SATISFIED** by existing tests. `test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_bind_zero_zero_accepted_with_unsafe_flag` (lines 344–355) verifies acceptance. And `test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_unsafe_bind_emits_warn_log_at_startup` (lines 385–429) verifies the WARN log fires with the correct substrings: `"ARXMCP_UNSAFE_NETWORK_BIND=1"`, `"0.0.0.0"`, and `.claude/docs/security-binding.md` reference.

### Brief vs code friction: Exception type

The brief AC #2 states: `Config.validate() raises ConfigError: binding to 0.0.0.0 requires...`

The code at `server/config.py:307–320` uses `raise ValueError(...)` inside a `@model_validator(mode="after")`. Pydantic wraps this as `ValidationError` at instantiation. The existing test correctly asserts `pytest.raises(ValidationError, match="must be a loopback")`.

**This is NOT a bug.** The brief is imprecise about the exception type — it conflates "config validation error" with the pydantic exception class name. The implementation is correct per pydantic semantics.

### Doc placement

The brief says "**docs/security/binding.md** — updated (links from E13_S05)." Per `CLAUDE.md §1` and the project pattern (see memory entry 2026-05-17 — E13_S01), user-facing documentation goes in `docs/`; audit documentation goes in `.claude/docs/`. The milestone should update the existing `.claude/docs/security-binding.md` (which already exists and is referenced by the test at line 419 and 444). No new file is needed; the brief is a documentation-placement drift (same as E13_S01–S08 precedent).

### Fictional milestone dependency

The brief cites **E07_S09** as a dependency. E07 has only S01–S04 (verified via roadmap). This is the same fictional-dependency drift noted in memory for E07_S12 (E13_S01), E07_S13 (E13_S02), and E07_S10/E06_S07/S08 (E13_S04). **The brief should reference E13_S05 instead** — E13_S05 closes Threat 5 (HTTP-layer enforcement); E13_S09 closes it at the TCP-bind layer. They are siblings in the same epic, not a linear chain.

### Design constitution load-bearing references

- **`server/config.py:LOOPBACK_HOSTS`** (line 53) — the canonical constant that defines which values pass bind-host validation
- **`server/config.py:reject_non_loopback_bind()`** (lines 293–321) — the `@model_validator(mode="after")` that implements the bind-host rejection logic; uses `ValueError`, which pydantic wraps as `ValidationError`
- **`server/main.py:548–559`** — the WARN log emission block when `cfg.unsafe_network_bind=True` (pinned by test at line 431–444 of test_origin_binding.py)
- **`.claude/notes/08-security-observability-ops.md` § Threat 4/5** — the threat model for localhost-only binding
- **`.claude/docs/security-binding.md`** — the audit document (exists, referenced by tests)

## Prior decisions and lessons

1. **E13_S05 already shipped this feature** (per memory 2026-05-18 — E13_S05). `Config.unsafe_network_bind` field and the `reject_non_loopback_bind()` model-validator landed in E13_S05 implementation. The AC#2 and AC#3 logic is NOT new; only the regression test (AC#1 + test aggregation) is.

2. **Exception type settled in E13_S05.** The memory and implementation-summary from E13_S05 confirm `ValidationError` (not `ConfigError`) is the correct exception class. The brief's "ConfigError" wording is stale from an earlier draft.

3. **Test class exists but is in test_origin_binding.py (E13_S05), not test_bind_regression.py (E13_S09).** The brief calls for a new file `tests/security/test_bind_regression.py` with 3 test cases. The existing coverage is scattered across two files and multiple test classes:
   - `test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch` (4 methods testing the escape hatch)
   - `test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch::test_unsafe_bind_emits_warn_log_at_startup` (WARN log)
   - `test_security.py::TestStartupRejectsBadBind::test_subprocess_exits_nonzero_with_fatal_message` (process-level gate)

4. **Audit vs regression test semantic difference.** E13_S05 tested "Threat 5 is closed" (HTTP-layer + config-layer). E13_S09 tests "TCP-bind regression prevention." The test names should reflect this — i.e., `test_bind_regression.py` should focus on the **regression guard** (the constant and the validator don't regress) and **default behavior** (unset config uses 127.0.0.1), not re-testing the escape-hatch logic that's already in E13_S05.

5. **Recent git confirms E13_S05 landed.** `git log --oneline -5` shows `c900209 chore(notes): finalize E13_S07 state -> complete`, meaning E13_S05–S07 are done. The bind-host validator is live in the codebase.

## External sources

Not needed for this milestone. All critical context is in-codebase: config.py, test_origin_binding.py, test_security.py, and .claude/notes/08-security-observability-ops.md.

## Recommendation

**Create a dedicated `tests/security/test_bind_regression.py` file with 3 test cases that aggregate and re-pin the existing coverage for the TCP-bind layer, independent of E13_S05's HTTP-layer tests.**

Rationale: E13_S05 tests the escape-hatch *feature*; E13_S09 tests the *regression surface* for the default loopback binding. A separate file makes the distinction explicit and prevents future bind-logic changes from evading the regression suite.

The 3 test cases:
1. **Default (no env vars):** `Config().bind_host == "127.0.0.1"`  
   Assert the hardcoded default is the canonical loopback.

2. **Rejection without escape hatch:** `ARXMCP_BIND_HOST=0.0.0.0` (no unsafe flag) → `ValidationError` with substring "must be a loopback"  
   Re-pin the exception type (ValidationError, not ConfigError) and the message content.

3. **Escape-hatch acceptance + WARN log:** `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1` → Config succeeds, startup logs WARN with substrings "ARXMCP_UNSAFE_NETWORK_BIND=1", "0.0.0.0", and ".claude/docs/security-binding.md"  
   Pin the log emission (already tested, but re-pin to catch refactors that drop it).

### Brief vs code friction summary

| Item | Brief says | Code/test actual | Status |
|------|-----------|------------------|--------|
| Exception type | `ConfigError` | `ValidationError` | **CONFLICT:** Brief is wrong; test is correct |
| Doc placement | `docs/security/binding.md` | `.claude/docs/security-binding.md` | **CONFLICT:** Brief violates CLAUDE.md §1 doc-placement rule |
| Dependency | E07_S09 | E13_S05 (E07 stops at S04) | **CONFLICT:** E07_S09 is fictional; should cite E13_S05 |

## Open questions

1. **Implementation path (A vs B vs C)?**
   - **Path A (pure aggregator):** Create `test_bind_regression.py` that imports the E13_S05 test classes and re-runs them under regression-test labels. Minimal code; maximum reuse.
   - **Path B (independent tests):** Create 3 fresh test methods in `test_bind_regression.py` that re-implement the same ACs independently. Defensive duplication; gives the regression suite its own grep target.
   - **Path C (no new file):** Skip the file, add a single AC#1 assertion to the existing test_origin_binding.py, and cite the existing coverage in the audit doc.

   **Recommendation: Path B.** The regression surface is distinct enough to warrant dedicated tests, and fresh implementation prevents cross-test dependencies.

2. **Exception type in the audit doc:** Should the `.claude/docs/security-binding.md` doc (already exists) be updated to correct the brief's "ConfigError" → "ValidationError" language, or is it already correct? (Brief artifact, not implementer task, but may flag a doc-update note.)

## External writes the implementation will require

None. This is a pure-local regression test addition. The doc `.claude/docs/security-binding.md` already exists and should be reviewed/updated if needed (not a git write, just a read-then-decide-whether-to-edit).


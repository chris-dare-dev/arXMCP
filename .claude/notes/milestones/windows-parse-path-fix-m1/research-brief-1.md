# Research Brief — windows-parse-path-fix-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-06-05T00:20:00Z

## In-codebase context

### Design notes that apply

**`08-security-observability-ops.md` (Threat 3):** "LaTeXML runs in a **subprocess with a hard timeout** (5 minutes). Subprocess runs as a **separate UID**." The env-scrub fix (Fix 1) is a direct extension of the subprocess sandbox philosophy: minimal inherited environment, no credentials or proxies. The new Windows vars must not violate this.

**`.claude/docs/security-pdf-sandbox.md` §Implementation:** "Strips proxies, AWS / GCP / Azure / HuggingFace credentials. Whitelists ONLY the variables MinerU genuinely needs (PATH for binary lookup; HOME for ~/.cache lookup of bundled ONNX models; LANG / LC_ALL for locale). `TMPDIR` is explicitly OVERRIDDEN to `str(output_dir)` rather than inherited."

The doc says "canonical implementation lives at `ingest/textbook_parser.py`... When the two diverge, the implementation wins and this doc updates in lockstep." **The implementer does NOT need to update security-pdf-sandbox.md**, but should note that it now describes only POSIX behavior; the doc will need a Windows paragraph in a follow-up.

**CLAUDE.md §8 gotcha #9:** "resource.setrlimit(RLIMIT_AS, ...) is non-functional on macOS... `server/lean_repl.py` has the same broken-on-Darwin guard (`sys.platform != 'win32'`) — separate follow-up issue." The existing platform guard pattern in `textbook_parser.py` uses `sys.platform == "linux"` — this milestone's env-whitelist fix uses `sys.platform == "win32"`. Both are intentional and correct per the stated platform semantics.

**CLAUDE.md §8 gotcha #10:** MinerU grandchild FastAPI server survives `os.killpg`. Fix 3 (`proc.kill()` on Windows) has the same known gap — on Windows `proc.kill()` only terminates the direct child, not MinerU's internal FastAPI server. This is already an **accepted gap** (loopback-only, documented in `security-pdf-sandbox.md §"What this milestone explicitly does NOT do"`). Do NOT reopen it.

### Exact state of the three fixes (from `git diff`)

**Fix 1 — `ingest/textbook_parser.py`:** Renamed `_ENV_WHITELIST` to `_ENV_WHITELIST_POSIX` (keeps `PATH, HOME, LANG, LC_ALL`). Added `_ENV_WHITELIST_WINDOWS = frozenset({SystemRoot, SYSTEMROOT, USERPROFILE, LOCALAPPDATA, APPDATA, TEMP, TMP, windir, SystemDrive, PATHEXT, NUMBER_OF_PROCESSORS, PROCESSOR_ARCHITECTURE, COMSPEC})`. Computed `_ENV_WHITELIST = _ENV_WHITELIST_POSIX | (_ENV_WHITELIST_WINDOWS if sys.platform == "win32" else frozenset())`. `_scrub_subprocess_env` still iterates `_ENV_WHITELIST` — no call-site change needed.

**Fix 2 — `tools/arxiv_fetch.py`:** Changed `if shutil.which("latexmlc") is None: raise ...` to `latexmlc_bin = shutil.which("latexmlc"); if latexmlc_bin is None: raise ...`. Changed `cmd = ["latexmlc", ...]` to `cmd = [latexmlc_bin, ...]`. Comment added explaining `.BAT` resolution failure.

**Fix 3 — `tools/arxiv_fetch.py`:** Changed `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` to `if hasattr(os, "getpgid"): os.killpg(os.getpgid(proc.pid), signal.SIGKILL) else: proc.kill()`. Wrapped inside the existing `contextlib.suppress(ProcessLookupError)`.

### Breaking test conflict — MUST fix

**`tests/test_textbook_parser.py:197` has a hardcoded assertion:**
```python
assert frozenset({"PATH", "HOME", "LANG", "LC_ALL"}) == _ENV_WHITELIST
```
After Fix 1, `_ENV_WHITELIST` on Windows includes 13 additional vars; on POSIX it still equals the original 4. **This test will fail on Windows with the fix applied.** The implementer must update this test. The new assertion should:
1. Import `_ENV_WHITELIST_POSIX` and `_ENV_WHITELIST_WINDOWS` from `ingest.textbook_parser`.
2. Assert `_ENV_WHITELIST_POSIX == frozenset({"PATH", "HOME", "LANG", "LC_ALL"})` (always true on all platforms).
3. Assert `_ENV_WHITELIST_WINDOWS == frozenset({...13 vars...})` (always true on all platforms).
4. Assert on Windows: `_ENV_WHITELIST == _ENV_WHITELIST_POSIX | _ENV_WHITELIST_WINDOWS`.
5. Assert on POSIX: `_ENV_WHITELIST == _ENV_WHITELIST_POSIX`.

The test import at `test_textbook_parser.py:33-48` also imports `_ENV_WHITELIST` directly — the import list must add `_ENV_WHITELIST_POSIX` and `_ENV_WHITELIST_WINDOWS`.

### Existing test coverage gaps for Fixes 2 and 3

`tests/test_arxiv_fetch.py` has ZERO tests for `parse_with_latexml`. The fix for latexmlc binary resolution (Fix 2) and the killpg fallback (Fix 3) have no regression coverage at all. New tests must be added there.

The existing `tests/test_textbook_parser.py:TestRunMineruSandboxedSurface.test_timeout_triggers_killpg` (lines 481-515) tests the MinerU path — it patches `os.killpg` and `os.getpgid` and verifies killpg is called. This test is POSIX-only in behavior; it should continue to pass unchanged because it patches the os module directly.

### Latent gap — `server/config.py` (do NOT fix here)

`server/main.py::_scan_unknown_arxmcp_env_vars` rejects `ARXMCP_MINERU_BIN` and `ARXMCP_MINERU_TIMEOUT_S` as undeclared. These are consumed by `ingest/textbook_parser.py` at import time — they work fine in the CLI parse path but the server-hosted UI upload path cannot be launched with them set. **This milestone should NOT fix this** — it is a separate architectural concern (ingest-tool vars vs server-config vars) and the brief explicitly marks it as "Latent gap (NOT fixed here)."

## Prior decisions and lessons

**Recent git log:** The three most recent milestones are `oldstyle-id-ingest-fix-m1`, `ui-htmx-json-fix-m1`, and `corpus-integrity-completion-e1`. All follow the three-commit pattern (feat + rect + chore). This milestone should do the same.

**Platform-gating idiom already established:** `ingest/textbook_parser.py` uses `if sys.platform == _RLIMIT_AS_PLATFORM:` for the RLIMIT_AS gate. The env-whitelist fix uses `sys.platform == "win32"` inline in the constant definition — consistent with the established idiom of module-level platform dispatch.

**`test_textbook_parser.py:TestRunMineruSandboxedSurface.test_timeout_triggers_killpg`** directly patches `os.killpg` and `os.getpgid`. After Fix 3 wraps the call in `if hasattr(os, "getpgid")`, this POSIX-path test still passes because `hasattr(os, "getpgid")` is True on POSIX (the test runs on the host OS, which is Windows in this project — but note that Python's `os` module on Windows does NOT have `getpgid`). **Risk:** on Windows the existing `test_timeout_triggers_killpg` test will now follow the `else: proc.kill()` branch, so `mock_killpg.assert_called_once_with(12345, signal.SIGKILL)` will FAIL. The implementer must add a Windows-path variant or add platform-conditional assertions.

**GPG signing broken on workstation** (per `memory/gpg-signing-broken-on-workstation.md`): commits will land unsigned — acceptable per user approval. Use HEREDOC form for commit messages.

**`assert` is BANNED for invariants** — the existing test uses `assert` statements, which is fine inside pytest (assertions are the test mechanism). In production code, `if ... raise RuntimeError(...)` is the pattern. No new production-code `assert` should be introduced.

**`_ENV_WHITELIST` is also referenced in `_scrub_subprocess_env` docstring** (`"Whitelist passes through PATH, HOME, LANG, LC_ALL"`). The docstring must be updated to reflect Windows-aware behavior.

## External sources

**Python 3.11 docs — subprocess.Popen on Windows** (`https://docs.python.org/3.11/library/subprocess.html`): "For maximum reliability, use a fully qualified path for the executable. To search for an unqualified name on PATH, use `shutil.which()`." CreateProcess with `shell=False` and a sequence arg does NOT invoke the shell extension resolution that finds `.BAT` files — the fix (using the resolved `shutil.which()` result) is the documented correct approach.

**Python 3.11 docs — `os.getpgid`** (`https://docs.python.org/3.11/library/os.html#os.getpgid`): "Availability: Unix, not Emscripten, not WASI." Windows is absent — `os.getpgid` does not exist on Windows. `hasattr(os, "getpgid")` is the correct guard.

**Python 3.11 docs — `subprocess.Popen` `start_new_session`:** "If `start_new_session` is true the `setsid()` system call will be made in the child process prior to the execution of the subprocess. Availability: POSIX." On Windows, `start_new_session=True` is silently accepted but is a no-op (no `setsid` exists). The code already passes `start_new_session=True` on all platforms; this is fine — on Windows it is a documented no-op, not an error.

**Windows `WinError 10106`** (WSAPROVIDERFAILEDINIT): The `SystemRoot` registry/env var is required by `WSAStartup` for the Winsock service provider chain. Without it, `socket` initialization fails, and by extension `torch`/`onnxruntime` which initialize network stacks on import. The fix (adding `SystemRoot` to `_ENV_WHITELIST_WINDOWS`) is the documented cure.

## Recommendation

Implement as-is — the three fixes are correct and minimal. Focus Phase 2 effort on:

1. **Fix the broken `test_whitelist_set_unchanged` test** — replace the POSIX-only pin with a split assertion that separately pins `_ENV_WHITELIST_POSIX` and `_ENV_WHITELIST_WINDOWS` (import both from the module), and then asserts `_ENV_WHITELIST` is their union on win32 or equals `_ENV_WHITELIST_POSIX` on POSIX.

2. **Add tests for Fix 2 (`latexmlc_bin` path)** in `tests/test_arxiv_fetch.py`: mock `shutil.which` returning a fake path, mock `subprocess.Popen`, and assert `cmd[0]` equals the `which()` result (not the bare string "latexmlc"). Add a second test that verifies `parse_with_latexml` raises `RuntimeError` when `shutil.which` returns `None`.

3. **Add tests for Fix 3 (killpg fallback)** in `tests/test_arxiv_fetch.py`: (a) on a platform with `os.getpgid` (`hasattr(os, "getpgid")` True), `TimeoutExpired` triggers `os.killpg`; (b) mock `hasattr(os, "getpgid")` to return False (or monkeypatch `os` to remove `getpgid`), verify `proc.kill()` is called instead.

4. **Fix the existing `test_timeout_triggers_killpg` test in `test_textbook_parser.py`** — after Fix 3, on Windows the `else: proc.kill()` branch fires. The test patches `os.killpg`, which would now be unreached. Add a platform-conditional assertion or use `pytest.mark.skipif(not hasattr(os, "getpgid"), ...)` on the existing test and add a Windows-path sibling.

5. **Update `_scrub_subprocess_env` docstring** to reflect Windows-aware behavior.

6. **Do not update `security-pdf-sandbox.md`** — the doc tracks the canonical implementation; it is accurate for POSIX and the Windows gap is a future addendum, not a blocking inconsistency.

The env-whitelist expansion security posture is sound: `SystemRoot`, `SYSTEMROOT`, `COMSPEC`, `PATHEXT`, `windir`, `SystemDrive`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE` are pure OS runtime infrastructure — not credentials, not proxy configs, not cloud tokens. `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `TEMP`, `TMP` are filesystem path pointers that MinerU needs for its cache and scratch. None enable network egress or credential leakage.

## Open questions

No open questions — implementation can proceed on the above recommendation. The broken test (`test_whitelist_set_unchanged`) is the only blocker before `make test` goes green, and its fix is specified above.

## External writes the implementation will require

None — this milestone is purely local. The brief explicitly says "commit per repo conventions" with no push authorization; push is a separate per-event authorization gate.

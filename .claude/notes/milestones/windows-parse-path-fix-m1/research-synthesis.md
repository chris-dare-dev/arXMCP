# Research Synthesis — windows-parse-path-fix-m1

**Orchestrator-merged from research-brief-1.md + research-brief-2.md**
**Generated:** 2026-06-04

## Scope

Three working-tree fixes make the textbook-PDF parse path (MinerU + LaTeXML)
run on native Windows. They touch security-audited subprocess code
(`ingest/textbook_parser.py` env scrub + `tools/arxiv_fetch.py` LaTeXML
driver). This milestone productionizes them: regression tests, security
review of the env-whitelist expansion, ruff + `make test`, and a
conventional-commit triple. The fixes themselves are correct as written;
the milestone work is **tests + two small scope additions + the broken-pin
test repair**.

## The three working-tree fixes (verified correct as-is)

**Fix 1 — `ingest/textbook_parser.py` env whitelist split.** `_ENV_WHITELIST`
renamed to `_ENV_WHITELIST_POSIX` (`PATH, HOME, LANG, LC_ALL`); new
`_ENV_WHITELIST_WINDOWS` (13 OS vars); effective `_ENV_WHITELIST =
_ENV_WHITELIST_POSIX | (_ENV_WHITELIST_WINDOWS if sys.platform == "win32"
else frozenset())`. Call site `_scrub_subprocess_env` unchanged. POSIX
behavior byte-identical.

**Fix 2 — `tools/arxiv_fetch.py::parse_with_latexml` binary resolution.**
`latexmlc_bin = shutil.which("latexmlc")` captured (None check unchanged);
`cmd[0]` is now `latexmlc_bin` not the bare string `"latexmlc"`. On Windows
`latexmlc` is `latexmlc.BAT`; `CreateProcess` appends `.exe` not `.bat` →
`FileNotFoundError` with the bare name. On POSIX the resolved path is the
same binary the bare name found.

**Fix 3 — `tools/arxiv_fetch.py::parse_with_latexml` timeout kill.**
`os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` guarded with
`if hasattr(os, "getpgid"): ... else: proc.kill()`. `os.getpgid`/`os.killpg`
are POSIX-only; `start_new_session` is a no-op on Windows.

## Security review — VERDICT: scrub intent preserved (from brief-2, primary)

The scrub's intent (Threat-3, `08-security-observability-ops.md`): strip all
proxies, AWS/GCP/Azure/HuggingFace credentials, anything enabling network
egress or credential leak. **None of the 13 new Windows vars is a
credential, proxy/egress route, or cloud token.** Per-var verdict (brief-2
table): all KEEP. Categories:

- Pure OS runtime infra (no path/secret): `SystemRoot`, `SYSTEMROOT`,
  `windir`, `SystemDrive`, `PATHEXT`, `NUMBER_OF_PROCESSORS`,
  `PROCESSOR_ARCHITECTURE`. `SystemRoot` is load-bearing — without it
  Winsock init fails (`WinError 10106`, verified live), torch/onnxruntime
  can't import.
- Filesystem path pointers (home-dir disclosure, same category as the
  already-whitelisted POSIX `HOME`): `USERPROFILE`, `LOCALAPPDATA`,
  `APPDATA`, `TEMP`, `TMP`. MinerU needs these for `mineru.json` config +
  HF/ONNX model cache + scratch.
- `COMSPEC` (path to `cmd.exe`): the only borderline one. NOT a credential,
  but it is a shell path. Risk is LOW — arXMCP never starts the subprocess
  with `shell=True`, and MinerU 3.x uses an internal FastAPI server, not
  shell invocations. KEEP, but the implementer should keep the inline
  comment noting the shell-path nature.

The four credential families the security-pdf-sandbox.md doc names —
proxies, AWS, GCP, Azure/HF — **remain stripped** (the scrub is a whitelist,
so anything not listed is dropped). Verdict: **security intent preserved.**
`SYSTEMROOT` is redundant with `SystemRoot` on Windows (case-insensitive
`os.environ`) — harmless belt-and-suspenders; KEEP.

## Scope additions adopted by the orchestrator (divergence resolution)

### ADD-1 — Windows `TEMP`/`TMP` override in `_scrub_subprocess_env` (from brief-2; brief-1 silent)

`_scrub_subprocess_env` overrides only `TMPDIR` to `str(output_dir)` (the
documented per-invocation scratch-isolation contract — "preventing scratch
files from landing in another notebook's tree"). On Windows, Python's
`tempfile` honors `TMPDIR` first, but **native libraries (torch,
onnxruntime, Perl) read `TEMP`/`TMP` directly via the OS, not `TMPDIR`.**
Fix 1 now whitelists `TEMP`/`TMP`, so the REAL host temp dir is passed
through — re-opening exactly the cross-notebook contamination the override
exists to prevent (FM-4/FM-8). **Resolution: ADOPT.** On `win32`, after the
whitelist loop, also set `env["TEMP"] = env["TMP"] = str(output_dir)`. Gate
on `sys.platform == "win32"` so POSIX env dict stays byte-identical (no new
keys on POSIX). This is in-scope: Fix 1 introduced the exposure, so closing
it belongs in this milestone, and an adversary would otherwise flag it.

### ADD-2 — extend Fix 3's killpg guard to `textbook_parser.py:409-410` (orchestrator finding; both briefs flagged the test symptom)

`ingest/textbook_parser.py::run_mineru_sandboxed` line 410 has the SAME
unguarded `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` on its MinerU
timeout path, wrapped in `contextlib.suppress(ProcessLookupError, OSError)`.
On Windows `os.getpgid`/`os.killpg` don't exist → **`AttributeError`, which
`suppress(ProcessLookupError, OSError)` does NOT catch** → a MinerU timeout
crashes with a traceback instead of cleanly killing + re-raising
`TimeoutExpired`. The brief's Fix 3 only patched `arxiv_fetch.py`, but this
is the same Windows-native parse-path bug in the same milestone subsystem
("make the MinerU + LaTeXML parse path work on Windows"). **Resolution:
ADOPT.** Apply the identical `if hasattr(os, "getpgid"): killpg else:
proc.kill()` guard at line 409-410. This also fixes the existing
`test_timeout_triggers_killpg` behavior on Windows.

## Required test work (union of both briefs)

1. **Repair `test_textbook_parser.py:194 test_whitelist_set_unchanged`** —
   currently pins `frozenset({"PATH","HOME","LANG","LC_ALL"}) ==
   _ENV_WHITELIST`. Fails on Windows (the effective set is larger). Replace
   with platform-split assertions: import `_ENV_WHITELIST_POSIX` +
   `_ENV_WHITELIST_WINDOWS`; pin each constant exactly (true on all
   platforms); assert `_ENV_WHITELIST == _ENV_WHITELIST_POSIX |
   _ENV_WHITELIST_WINDOWS` on win32 and `== _ENV_WHITELIST_POSIX` on POSIX.
   Update the import block at lines 33-48 to add both new constants. The
   "pinned exactly so a future widening must update both" intent is
   preserved per-constant.

2. **New: TEMP/TMP override test** (`test_textbook_parser.py`,
   `TestScrubSubprocessEnv`) — on win32 (or simulated via
   `monkeypatch.setattr(textbook_parser.sys, "platform", "win32")` if the
   override is read from `sys.platform` at call time — note the override
   logic must be call-time, not import-time, to be testable), assert
   `env["TEMP"] == env["TMP"] == str(output_dir)`. POSIX path: assert
   `TEMP`/`TMP` NOT added (byte-identical). Always: assert
   `env["TMPDIR"] == str(output_dir)` unchanged.

3. **Repair `test_textbook_parser.py:481 test_timeout_triggers_killpg`** —
   after ADD-2, make it cross-platform. Two tests: (a) getpgid-present path
   → killpg called (use `create=True` on the `os.killpg`/`os.getpgid`
   patches so it runs on a Windows host too, OR `skipif(not hasattr(os,
   "getpgid"))`); (b) NEW getpgid-absent path → `monkeypatch.delattr(os,
   "getpgid", raising=False)`, assert `proc.kill()` called and killpg NOT
   reached. The delattr approach simulates Windows on any host — preferred.

4. **New: `tests/test_arxiv_fetch.py` parse_with_latexml coverage** (ZERO
   today). Add:
   - cmd[0] uses the `shutil.which("latexmlc")` result, not the bare
     string. Mock `shutil.which` → fake path, mock `subprocess.Popen`,
     capture the `cmd` arg, assert `cmd[0]` == fake path.
   - `RuntimeError` raised when `shutil.which("latexmlc")` is None.
   - killpg fallback: getpgid present → `os.killpg` called on
     `TimeoutExpired`; getpgid absent (`delattr`) → `proc.kill()` called.

## Failure modes carried forward (from brief-2, for the adversary)

- FM (accepted gap): `proc.kill()` on Windows reaps only the direct child;
  Perl helpers / MinerU grandchild FastAPI survive. Analogous to the
  documented MinerU-grandchild gap (`security-pdf-sandbox.md §"explicitly
  does NOT do"`, CLAUDE.md gotcha #10). DOCUMENT in a comment; do not
  reopen.
- FM (handled): `shutil.which` None → RuntimeError before `cmd` built.
- FM (test trap): module-level `_ENV_WHITELIST` computed at import →
  `monkeypatch.setattr(sys, "platform", ...)` does NOT recompute it. Tests
  must import the split constants directly or patch the constant. The
  TEMP/TMP override (ADD-1) must read `sys.platform` at CALL time to be
  monkeypatchable, or tests gate on the real platform.

## Out of scope (do NOT fix here)

- **`server/config.py` `_scan_unknown_arxmcp_env_vars` rejects
  `ARXMCP_MINERU_BIN` / `ARXMCP_MINERU_TIMEOUT_S`.** Pre-existing latent gap
  (server-config vars vs ingest-tool vars). Touches security-audited
  server config unrelated to the Windows parse path. Both briefs agree:
  OUT OF SCOPE. Document as a follow-up (file an issue / note in commit
  body); do not fix.
- **Update `security-pdf-sandbox.md`** — the doc tracks the canonical
  implementation and is accurate for POSIX; a Windows addendum is a future
  doc task, not a blocking inconsistency (brief-1).
- **MinerU's internal bare-name LaTeXML invocation** (brief-2 FM-6) —
  upstream's responsibility.

## Implementation path

INLINE (orchestrator, main session). Prod delta is ~35 lines across 2 files
(`ingest/textbook_parser.py`, `tools/arxiv_fetch.py`); test delta ~150 lines
across 2 files. Well under the 500-LOC / 5-file delegated threshold; no
novel architecture; no specialist match.

## Project conventions

- ruff + `make test` must be green (note ~60 pre-existing Windows-only
  failures per CLAUDE.md §3 — confirm the count does not GROW; the repaired
  pin + killpg tests should REDUCE it).
- Conventional commits, GPG signed (will land UNSIGNED per the workstation's
  known no-key state — memory `gpg-signing-broken-on-workstation.md`), HEREDOC
  body, co-author trailer. Three-commit triple (feat + rect + chore).
- `assert` banned for invariants in PROD code (`if ... raise` instead);
  `assert` in tests is fine.

## Open questions

1. **TEMP/TMP override timing** — must `_scrub_subprocess_env` read
   `sys.platform` at call time (testable via monkeypatch) or is import-time
   gating + real-platform test gating acceptable? **Resolution:** read at
   call time inside the function (`if sys.platform == "win32":`) — cheap,
   makes the override unit-testable cross-platform, and matches the
   established inline-platform-dispatch idiom.
2. **`server/config.py` gap** — confirmed OUT OF SCOPE (see above).

## External writes the implementation will require

NONE. Purely local. The milestone produces local commits only; `git push`
is a separate per-event authorization gate not requested in the brief.

## Orchestrator synthesis note

Briefs agree the three fixes are correct and that the env-scrub security
intent is preserved. Divergences resolved: (1) brief-2's TEMP/TMP override
(ADD-1) ADOPTED — Fix 1 introduced the temp-dir exposure, so closing it is
in-scope; (2) orchestrator added ADD-2 (extend the killpg guard to
`textbook_parser.py`'s MinerU timeout path) — same bug class, same
subsystem, both briefs flagged its test symptom without tracing it to the
unguarded prod call. brief-1's claim that the existing `test_timeout_*`
"continues to pass unchanged" is INCORRECT on Windows (patch.object on a
missing `os.getpgid` errors at setup) — brief-2's analysis is adopted.

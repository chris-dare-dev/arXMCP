# Critique — E13_S03b

**Critic:** adversary
**Generated:** 2026-05-23T04:30:00Z
**Commit range:** 3c5d47fc771e5602fcc0eb9784bb3d3bd133e2a0..da71402a6bcbaf5e7458a8b4ca5ce66c1c176544
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The wiring approach is correct (single helper, fail-closed degraded path, AST guard preserved), but the bwrap argv is **missing two flags that LaTeXML/Perl actually need at runtime** (`--proc /proc` and `--dev /dev`) and contains a `--unshare-pid` flag that REQUIRES `--proc /proc` to function — so the Linux production path is likely to silently break first-run smoke tests against the seed corpus.
- 0 CRITICAL, 3 HIGH, 5 MEDIUM, 2 LOW.
- Highest-risk citation: `tools/arxiv_fetch.py:447-457` — bwrap argv composition omits `/proc` and `/dev` mounts; `--unshare-pid` without `--proc /proc` is documented by bwrap maintainers as broken.
- D6 drift from synthesis: synthesis line 288 said the secondary `render_fixture` site should "also gain `start_new_session=True` for parity"; the implementation prepends the sandbox argv but does NOT add `start_new_session=True` to the `subprocess.run(...)` call at `ops/drift_check.py:166-173`. This is a documented divergence from the agreed plan.
- The `--timeout=300` latexmlc CLI flag is correctly interpreted as a parse-time budget (per LaTeXML issue #741 testimony), but no test exercises the flag against live latexmlc — the only test that touches it is the mock-based `test_parse_with_latexml_threads_sandbox_to_popen`, which only asserts the flag is present in the post-`--` argv tail. If the locally-installed LaTeXML version rejects `--timeout=300`, every paper would silently fail to parse on the production path.
- One test (`test_detect_sandbox_layer_darwin_when_present`) blanket-stubs `Path.is_file` to always return True, so the test would still pass even if the implementation dropped one of the two existence checks. Weak guard.
- The macOS sandbox.sb profile allows `(allow file-read*)` only on a fixed allowlist of paths; macOS's `tempfile.TemporaryDirectory` typically lives under `/var/folders/...` which is NOT in the allowlist. The profile permits `file-write*` on `TMPDIR_SUBDIR` but SBPL does NOT promote file-write to file-read — so a Perl helper that reads back files it wrote in the tmp area could trip the sandbox.
- Otherwise the implementation is well-scoped, doc-honest, and correctly limits the scope to wiring (not profile-authoring). The 9 new tests cover the wiring discipline; the AST guard for `start_new_session=True` is preserved; cache discipline (no MCP tool surface) is unaffected.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — bwrap argv missing `--proc /proc` while using `--unshare-pid`

- **Severity:** HIGH
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:447-457
- **What:** The bwrap argv includes `--unshare-pid` but does NOT mount a fresh procfs in the new PID namespace (`--proc /proc`). Bubblewrap maintainers document that "When using `--unshare-pid`, you really need to mount /proc, or all of the PIDs are wrong in /proc and things will get confused" ([bubblewrap manpages](https://manpages.debian.org/testing/bubblewrap/bwrap.1.en.html)). Because `/proc` is also not bound from the host (`--ro-bind /usr /usr` etc. do not cover `/proc`), inside the sandbox `/proc` does not exist at all.
- **Why it matters:** Perl on Linux (LaTeXML's runtime) sometimes reads `/proc/self/exe` for interpreter discovery, `/proc/cpuinfo` for parallelism, or `/proc/self/cmdline` for `$0` reconstruction. Many CPAN modules silently fall back, but some (e.g., `IPC::Run`, `Sys::Info`, locale resolvers) throw fatal errors. The synthesis flagged a smoke-test against the 50-paper seed corpus as an operator-time validation — but with `/proc` entirely absent, the first deploy is very likely to fail across many papers.
- **Proposed fix:** Add `--proc /proc` to the bwrap argv. Two-line change at `tools/arxiv_fetch.py:450`:
  ```python
  bwrap_args.extend([
      "--ro-bind", str(source_dir), str(source_dir),
      "--bind", str(output_dir), str(output_dir),
      "--tmpfs", "/tmp",
      "--proc", "/proc",        # NEW — required by --unshare-pid
      "--dev", "/dev",          # NEW — see F2
      "--unshare-net",
      "--unshare-pid",
      ...
  ])
  ```
- **Regression guard:** Extend `test_build_sandbox_cmd_linux_prepends_bwrap` to assert `"--proc"` and `"--dev"` appear in `result`, paired with `/proc` and `/dev` respectively. The existing test's load-bearing-flag loop currently covers `--unshare-net`, `--unshare-pid`, `--die-with-parent`, `--new-session` — extend to require `--proc` and `--dev` too.

### F2 — bwrap argv missing `--dev /dev` (no /dev/null, /dev/urandom inside sandbox)

- **Severity:** HIGH
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:447-457
- **What:** The bwrap argv does NOT mount `/dev` (neither `--dev /dev` nor `--dev-bind /dev/null /dev/null`). Inside the sandbox, `/dev/null`, `/dev/urandom`, `/dev/zero`, and `/dev/tty` do not exist. This is the exact issue documented in [openai/codex#12056](https://github.com/openai/codex/issues/12056): "When a sandbox command needs to read from /dev/urandom, it fails. Some commands (like git) requires secure random number from that device."
- **Why it matters:** Perl's `Math::Random`, `Crypt::Random`, fontconfig, and any subprocess that opens `/dev/null` as a stdin/stderr placeholder will fail with `ENOENT` inside the sandbox. LaTeXML's Perl helpers fork additional processes; those routinely redirect to `/dev/null`. This will trip the bwrap sandbox on essentially every ingest.
- **Proposed fix:** Add `--dev /dev` to the bwrap argv (mounts a minimal `/dev` with `null`, `zero`, `random`, `urandom`, `tty`, `full`). See F1 for the diff sketch.
- **Regression guard:** Same as F1 — extend the load-bearing-flag assertion in `test_build_sandbox_cmd_linux_prepends_bwrap`.

### F3 — `--timeout=300` flag passed to latexmlc has no live-integration test

- **Severity:** HIGH
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:503
- **What:** The implementation adds `f"--timeout={LATEXML_INTERNAL_TIMEOUT_SECONDS}"` (=`--timeout=300`) to the latexmlc argv as "defense-in-depth." Per [LaTeXML issue #741](https://github.com/brucemiller/LaTeXML/issues/741) the flag is a parse-time budget. But the only test that touches this is `test_parse_with_latexml_threads_sandbox_to_popen` (line 1038), which mocks `Popen` — so the test asserts the flag is in the argv, NOT that latexmlc actually accepts it. The implementer's own narrative in implementation-summary.md says "If LaTeXML rejects the flag on an older version, the test surface catches it against live latexmlc" — but the only LIVE test in the file is `TestLatexmlSandboxContainment` (line ~200ish), which is unconditionally skipped on Windows AND skips when latexmlc is absent.
- **Why it matters:** If the locally-installed LaTeXML version is 0.8.x and the flag form is `--timeout 300` (space-separated) rather than `--timeout=300`, latexmlc may reject the unknown option and exit non-zero before doing any parsing. Every paper in the production ingest would silently fail. The "test surface catches it" claim is unsupported by the test code.
- **Proposed fix:** Either (a) drop the `--timeout=300` flag entirely (the Python-side `subprocess` timeout is already in place) and document the rationale; or (b) add a live-integration test under `TestLatexmlSandboxContainment` that runs `latexmlc --timeout=300 --help` (or `--version`) against the locally-installed binary and asserts non-zero rejection raises a clear failure. Option (a) is the safer ship; option (b) is the better long-term posture.
- **Regression guard:** If keeping the flag, add `test_latexmlc_accepts_timeout_flag` under `TestLatexmlSandboxContainment` (skipif latexmlc absent) that invokes `latexmlc --timeout=300 --help`.

### F4 — `render_fixture` missing `start_new_session=True` despite synthesis decision D6 demanding parity

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ops/drift_check.py:166-173
- **What:** Research synthesis D6 (line 288): "also gain `start_new_session=True` for parity." The implementation prepends the sandbox argv via `_build_sandbox_cmd` but the `subprocess.run(...)` call at line 166 does NOT pass `start_new_session=True`. A hostile fixture that escapes the sandbox (e.g. because the operator hasn't installed bwrap, the degraded path) and forks Perl helpers via `latexmlc` would still leave grandchildren behind on `TimeoutExpired`.
- **Why it matters:** D6 explicitly called out this exact symmetry. The drift_check site runs on potentially-untrusted `.tex` fixtures (the same threat class as `parse_with_latexml`). The implementation diverges from the agreed plan without surfacing the divergence in the implementation summary's "Deviations from the brief" section.
- **Proposed fix:** Add `start_new_session=True` to the `subprocess.run(...)` keyword args at `ops/drift_check.py:170`. One-line change.
- **Regression guard:** Add `test_render_fixture_uses_start_new_session` to the drift_check test suite (mirroring `TestProcessGroupKill::test_parse_with_latexml_uses_process_group_kill` AST guard) that walks the `render_fixture` function body for the `start_new_session=True` token.

### F5 — `test_detect_sandbox_layer_darwin_when_present` is too weak to catch regression

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_latexml_sandbox.py:742-755
- **What:** The test sets `monkeypatch.setattr(af.Path, "is_file", lambda self: True)` — a blanket stub that makes EVERY `Path.is_file()` call return True. The function `_detect_sandbox_layer` is supposed to check BOTH `Path("/usr/bin/sandbox-exec").is_file()` AND `SANDBOX_PROFILE_PATH.is_file()`. A future refactor that drops either of those checks would still make this test pass.
- **Why it matters:** Adversary critic for E13_S03 (the precursor) shipped F1 highlighting credential-read exposures because the profile-authoring tests were too permissive. The successor's wiring tests inherit the same anti-pattern — overly-stubbed `Path.is_file` that doesn't isolate which path is being checked.
- **Proposed fix:** Replace the blanket stub with a discriminating stub:
  ```python
  checked_paths: list[str] = []
  def selective_is_file(self):
      checked_paths.append(str(self))
      return True
  monkeypatch.setattr(af.Path, "is_file", selective_is_file)
  af._detect_sandbox_layer()
  assert "/usr/bin/sandbox-exec" in checked_paths
  assert "sandbox.sb" in " ".join(checked_paths)
  ```
- **Regression guard:** The fix IS the regression guard — the test now asserts both paths are touched.

### F6 — bwrap argv missing `--ro-bind` guard for `/lib` (asymmetric with `/lib64`)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:440-446
- **What:** The implementation has `if Path("/lib64").exists():` to guard the `/lib64` bind, but unconditionally appends `--ro-bind /lib /lib`. On minimal Linux images (Alpine, some musl-libc systems, scratch-based containers) `/lib` may not exist as a path; bwrap exits with `bwrap: Can't bind /lib: No such file or directory`. Note also that on most modern "merged-usr" systems `/lib` is a symlink to `usr/lib`, which bwrap follows — that works, but the asymmetry remains a latent foot-gun.
- **Why it matters:** Production Linux is usually Debian/Ubuntu where `/lib` exists, so this is unlikely to fire in the operator's primary target. But the implementation is shipped to a single-user repo where the operator may run from inside a minimal container during testing. A simple existence-guard removes the foot-gun for ~0 cost.
- **Proposed fix:** Mirror the `/lib64` guard pattern:
  ```python
  bwrap_args = ["bwrap", "--ro-bind", "/usr", "/usr"]
  if Path("/lib").exists():
      bwrap_args.extend(["--ro-bind", "/lib", "/lib"])
  if Path("/lib64").exists():
      bwrap_args.extend(["--ro-bind", "/lib64", "/lib64"])
  ```
- **Regression guard:** Adjust `test_build_sandbox_cmd_linux_prepends_bwrap` to monkeypatch `Path.exists` deterministically (currently the test only checks `/lib` is present unconditionally) and assert both code branches.

### F7 — sandbox-exec sandbox.sb profile may not cover macOS `tempfile` location under `/var/folders/...`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:512-514 + infra/latexml/sandbox.sb:50-56
- **What:** The macOS `tempfile.TemporaryDirectory(prefix=f"arxmcp-latexml-{paper_id}-")` resolves to `$TMPDIR`, which on macOS is typically `/var/folders/<random>/T/...`. The sandbox.sb profile `(allow file-read*)` covers `/usr`, `/System`, `/Library`, `/opt/homebrew`, `/opt/local`, and `(subpath (param "SOURCE_DIR"))` — but NOT `/var/folders` or `/private/var`. The profile permits `(allow file-write*)` on the `TMPDIR_SUBDIR` param, but in SBPL `file-write*` does NOT imply `file-read*` — both must be explicitly allowed for the same path. If a Perl helper writes a file under TMPDIR_SUBDIR and then reads it back (common pattern for atomic writes), the read could be denied.
- **Why it matters:** This is the kind of latent sandbox-trip that surfaces only at production smoke-test time. The synthesis flagged a "first-deploy smoke test against the 50-paper seed corpus" as the validation gate — but a profile bug here means the rectification path is to widen `infra/latexml/sandbox.sb`, not to revert E13_S03b. Worth flagging now so the operator can pre-emptively add `(allow file-read* (subpath (param "TMPDIR_SUBDIR")))` to the profile.
- **Proposed fix:** Add to `infra/latexml/sandbox.sb` after line 100 (the existing `file-write* TMPDIR_SUBDIR` allow):
  ```scheme
  (allow file-read*
    (subpath (param "TMPDIR_SUBDIR")))
  ```
  And document the pattern in the audit doc's operator-runbook section.
- **Regression guard:** Add an assertion to `TestSandboxProfile` that the `sandbox.sb` profile contains both `file-write*` AND `file-read*` rules for `TMPDIR_SUBDIR`.

### F8 — `_FakeProc` test for Popen does not exercise the `--proc`/`--dev` flags

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_latexml_sandbox.py:1006-1042
- **What:** The `_FakeProc` mock pattern in `test_parse_with_latexml_threads_sandbox_to_popen` asserts (a) argv[0] == "bwrap"; (b) `--` separator exists; (c) post-`--` cmd starts with "latexmlc"; (d) `--timeout=300` is in the post-`--` tail. It does NOT assert any specific bwrap isolation flag is present. So a future refactor that drops `--unshare-net` (or, post-F1/F2, `--proc`/`--dev`) would not fail this test.
- **Why it matters:** The implementation summary names this test as "FM-3/FM-5 regression guard" but the assertion surface is narrower than the failure-mode list claims. A wiring bug that drops a load-bearing flag would survive.
- **Proposed fix:** Extend the test to assert the load-bearing isolation flags are present in the captured argv (the same flag list used in `test_build_sandbox_cmd_linux_prepends_bwrap`, plus F1/F2's additions).
- **Regression guard:** The fix is the regression guard.

### F9 — `cmd` variable rebinding inside `with` block obscures lexical scope

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:512-520
- **What:** `parse_with_latexml` initializes `cmd` at line 501, then re-binds the same name `cmd = _build_sandbox_cmd(cmd, ...)` inside the `with tempfile.TemporaryDirectory(...)` block. The original argv is then unreachable outside the with-block. The implementation summary advertises that `_build_sandbox_cmd` doesn't mutate its input — but the function shadows that input. If a future debug-logger needs to print the original (unsandboxed) cmd outside the with-block, it can't.
- **Why it matters:** Style only; no behavior change. But the contract clarity of "`_build_sandbox_cmd` does not mutate input" is undercut by the immediate re-bind on the only known caller.
- **Proposed fix:** Use distinct names:
  ```python
  base_cmd = ["latexmlc", f"--timeout={...}", ...]
  with tempfile.TemporaryDirectory(...) as tmpdir_str:
      wrapped_cmd = _build_sandbox_cmd(base_cmd, ...)
      proc = subprocess.Popen(wrapped_cmd, ...)
  ```
- **Regression guard:** None required (style finding).

### F10 — `from tools.arxiv_fetch import _build_sandbox_cmd` is a function-local import in `render_fixture`

- **Severity:** LOW
- **Source:** adversary
- **File:** ops/drift_check.py:155
- **What:** The new import lives inside the `render_fixture` function body (line 155) rather than at the module top. This pattern occurs sometimes to avoid circular imports — but no circular dependency exists between `ops.drift_check` and `tools.arxiv_fetch` (the latter doesn't import from `ops`). The function-local import imposes a tiny per-call cost and is a smell.
- **Why it matters:** Style only; the function-local import works correctly. But function-local imports are typically a signal of either a circular-import workaround OR a "I forgot to move this up after debugging" leftover.
- **Proposed fix:** Move the import to the module top (line ~50, alongside the other imports). If a future refactor introduces a real circular dependency between `ops.drift_check` and `tools.arxiv_fetch`, the move can be reversed.
- **Regression guard:** None required.

## What was done well

- Cache discipline preserved. No MCP tool surface change. `EXPECTED_TOOL_SCHEMA_SHA256` untouched as required for BP1 prompt-cache byte-stability.
- AST guard preservation. `start_new_session=True` and `os.killpg` calls stayed on the main code path inside `parse_with_latexml`, NOT moved into a platform-conditional branch — the `TestProcessGroupKill::test_parse_with_latexml_uses_process_group_kill` AST guard still inspects `ast.unparse(func)` for both tokens and passes.
- Fail-closed degraded path. When `_SANDBOX_LAYER is None`, `_build_sandbox_cmd` returns the original `cmd` unchanged (identity-preserving); there's no silent partial sandbox. The module-import-time INFO log surfaces the active layer (or its absence) ONCE per process, so the operator gets a single startup signal without per-paper noise.
- Honest scoping in the audit doc. The Docker-wiring deferral to E14 is called out explicitly in the phasing table AND in the new "Phase 2 wiring (E13_S03b)" section. The G3 row's strike-through-then-close-with-footnote pattern is the right level of disclosure.
- Wiring-only discipline. The implementation respects E13_S03's profile-authoring scope; no changes to `infra/latexml/sandbox.sb` (the profile shipped + statically validated by E13_S03 stays intact). The brief's misplaced `docker/Dockerfile.server` deliverable was correctly dropped per synthesis D1.
- POSIX-skip pattern on `TestSandboxWiring`. The class-level `@pytest.mark.skipif(sys.platform == "win32", ...)` is the right pattern for tests that monkey-patch POSIX-only code paths. Avoids spurious Windows failures.
- No banned-pattern introductions. No `assert` for runtime invariants in production code (the AST-guard tests use `assert` legitimately as pytest assertions). No `BaseHTTPMiddleware`. No `anthropic` SDK. No fork-from-OSS. No `0.0.0.0` bind. No `latest` Docker tag.
- Tier-sequencing clean. E13_S03 is shipped; E13_S03b consumes only what exists. No premature dependency on E10/E11/E14.
- Test counts plausible. 9 new tests for a wiring milestone of ~80 LOC production change is the right magnitude. The mock-based pattern is appropriate for cross-platform CI-friendly wiring tests.
- The `--die-with-parent` + `--new-session` combination on bwrap (synthesis D2) is correct — they address different concerns (parent-death cleanup vs. session-leadership for killpg), and both are cheap.

## Recommended rectification order

1. **F1 + F2 + F8** (rectify together — same file, same test). Add `--proc /proc` and `--dev /dev` to the bwrap argv and extend the `test_build_sandbox_cmd_linux_prepends_bwrap` and `test_parse_with_latexml_threads_sandbox_to_popen` flag assertions to cover them. Highest leverage: closes the most likely smoke-test failure mode on the production Linux path.
2. **F3**. Decide whether to keep `--timeout=300` on latexmlc. If keeping, add a live-integration test under `TestLatexmlSandboxContainment` that proves the flag is accepted by the locally-installed latexmlc; if dropping, remove the constant + argv addition + docstring claim. Resolving F3 before F4 lets you settle the test-surface shape first.
3. **F4**. Add `start_new_session=True` to `subprocess.run` in `render_fixture`. One-line fix matching synthesis D6. Add an AST guard test mirroring `test_parse_with_latexml_uses_process_group_kill`.
4. **F5**. Tighten `test_detect_sandbox_layer_darwin_when_present` to discriminate between the two `is_file` checks. Small refactor; protects against future drop of either check.
5. **F6**. Mirror the `/lib64` existence guard for `/lib` in the bwrap argv builder. Two-line fix.
6. **F7**. Widen the `infra/latexml/sandbox.sb` profile to add `(allow file-read*)` on the `TMPDIR_SUBDIR` param. This is technically out of E13_S03b's wiring scope (touches profile-authoring), but the smoke-test risk note in the synthesis says profile widening is a separate follow-up — fine to defer if not cheap.
7. **F9 + F10**. Style cleanup — distinct `cmd`/`wrapped_cmd` names; move the function-local import to module top. Defer to a future style sweep.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

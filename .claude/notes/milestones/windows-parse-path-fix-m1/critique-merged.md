# Critique — windows-parse-path-fix-m1

**Critic:** adversary
**Generated:** 2026-06-04T00:00:00Z
**Commit range:** 702b58607e7e2728c59d8e2506c278ccdb076578..f70c8a5598768a54108ea5ffb291a20b8a4234fc
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the three base fixes + ADD-1/ADD-2 are correct in production code and the killpg branch tests genuinely pass cross-platform (verified live on this Windows host); the residual issues are test-fidelity gaps around the TEMP/TMP scratch-isolation contract, not production bugs.
- Findings: 0 CRITICAL, 0 HIGH, 2 MEDIUM, 2 LOW.
- Highest-risk surface: `ingest/textbook_parser.py:240-242` (call-time TEMP/TMP override) vs `ingest/textbook_parser.py:78-81` (import-time `_ENV_WHITELIST`) — a timing split the POSIX-negative test masks with `delenv`.
- Security axis (PRIMARY): the 13-var Windows whitelist is sound — none is a credential/proxy/egress/cloud-token var; COMSPEC is the only borderline entry (cmd.exe path) and subprocess is `shell=False`, so the risk is indirect and acceptable.
- Cross-platform test trick is legitimate: `monkeypatch.setattr(af.signal, "SIGKILL", 9, raising=False)` mutates the shared `signal` module so the `signal.SIGKILL` assertion resolves on Windows — NOT a fabricated false-pass.
- The getpgid-absent test (`monkeypatch.delattr(os, "getpgid")`) is the real Windows-branch guard and is correct; the getpgid-present test is synthetic-but-valid branch coverage.
- Both documented deferrals (server/config.py ARXMCP_MINERU_BIN rejection; TestUserAgent SQLite leakage) are correctly out of scope and do not block the milestone goal (CLI + UI-upload Windows parse path works when those env vars are unset).
- Implementer's "74 -> 66, zero new" claim is plausible; the milestone's own new/changed tests all pass here (the one local failure is a pre-existing missing `prometheus_client`, unrelated).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (<= 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under deferred_findings) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — POSIX-negative TEMP/TMP test masks import/call-time split with delenv

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_textbook_parser.py:1063-1076 (`test_temp_tmp_not_added_on_posix`); root cause `ingest/textbook_parser.py:78-81` (import-time `_ENV_WHITELIST`) vs `:240-242` (call-time `sys.platform` read)
- **What:** `_ENV_WHITELIST` is frozen at IMPORT time (`_ENV_WHITELIST_POSIX | (_ENV_WHITELIST_WINDOWS if sys.platform == "win32" else frozenset())`), but the TEMP/TMP override reads `sys.platform` at CALL time. On a Windows host the import-time whitelist already contains TEMP/TMP, so `test_temp_tmp_not_added_on_posix` only passes because it calls `monkeypatch.delenv("TEMP")`/`delenv("TMP")` — remove those two lines and the test fails on Windows while still passing on a real POSIX box.
- **Why it matters:** The test claims to pin "POSIX env dict stays byte-identical" but does not exercise a real POSIX `_ENV_WHITELIST`; it exercises the Windows import-time whitelist with a faked call-time platform and masking `delenv`. A future regression that wired TEMP/TMP into the POSIX whitelist could slip past this test on the dev workstation.
- **Proposed fix:** Either (a) make the test assert against `_ENV_WHITELIST_POSIX` membership directly rather than env-dict absence, or (b) drop the import-time `sys.platform` gate and compute the effective whitelist at call time so import-time and call-time platform reads cannot diverge, then drop the `delenv` masking. Option (a) is the cheaper fix.
- **Regression guard:** Add an assertion that `"TEMP" not in _ENV_WHITELIST_POSIX and "TMP" not in _ENV_WHITELIST_POSIX` (platform-independent, no delenv), so the POSIX byte-identical contract is pinned on the constant, not on a faked call.

### F2 — Windows TEMP/TMP test proves "set" not "override-over-inherited"

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_textbook_parser.py:1049-1061 (`test_temp_tmp_overridden_on_windows`); contract at `ingest/textbook_parser.py:231-242`
- **What:** The test fakes win32, calls `_scrub_subprocess_env(tmp_path)`, and asserts `env["TEMP"] == env["TMP"] == str(tmp_path)`. It never seeds a real host `TEMP`/`TMP` in `os.environ` before the call, so it cannot distinguish "override clobbered the inherited host value" from "key was simply set." The whole point of ADD-1 is that the whitelist (line 232-234) first COPIES the real host `TEMP`/`TMP`, then lines 240-242 must CLOBBER them.
- **Why it matters:** The cross-notebook scratch-contamination contract (the documented security/correctness intent of ADD-1) is exactly the clobber, not the set. If a future edit reordered the override before the whitelist loop, the host TEMP would win and the test would still pass green — silently re-opening the contamination ADD-1 closed.
- **Proposed fix:** In `test_temp_tmp_overridden_on_windows`, set `monkeypatch.setenv("TEMP", "C:\\host\\temp")` and `setenv("TMP", "C:\\host\\temp")` before the call, plus add TEMP/TMP to the simulated whitelist path, then assert the returned values equal `str(tmp_path)` and NOT the seeded host value.
- **Regression guard:** The seeded-host-value assertion above is the guard; it fails on any reorder that lets the inherited value survive.

### F3 — COMSPEC shell-path admitted with no negative-guard test pinning the borderline set

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/textbook_parser.py:90-92 (`COMSPEC` in `_ENV_WHITELIST_WINDOWS`); guard at tests/test_textbook_parser.py:1028-1039
- **What:** The security guard test (`test_no_credential_or_egress_var_in_windows_whitelist`) asserts disjointness from a fixed forbidden set, but COMSPEC (the cmd.exe path — the one var both research briefs flagged as borderline) is not called out anywhere in the test as the single tolerated shell-path entry. The risk is indirect (it only matters if a downstream call uses `shell=True`, which arXMCP does not — confirmed by `# noqa: S603 — fixed argv, no shell` at tools/arxiv_fetch.py:577).
- **Why it matters:** Documentation of the borderline call lives only in research-synthesis.md, not in an executable guard; a future whitelist widening that adds a second shell-adjacent var would not be flagged.
- **Proposed fix:** Add a one-line comment beside COMSPEC at `_ENV_WHITELIST_WINDOWS` noting it is the sole tolerated shell-path var and is safe only because every subprocess in this module is `shell=False`. Optionally extend the forbidden-set test to also assert no NEW shell-path var beyond COMSPEC.
- **Regression guard:** Inline COMSPEC rationale comment + (optional) an assertion that `_ENV_WHITELIST_WINDOWS & {"PROMPT", "PSModulePath"} == set()` if you want to pin shell-adjacency.

### F4 — Windows orphan Perl/MinerU grandchild gap documented only in code comments

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:594-600 and ingest/textbook_parser.py:424-431 (code comments); operator-facing `.claude/docs/security-pdf-sandbox.md` (not updated this milestone)
- **What:** On Windows `proc.kill()` reaps only the direct child; Perl helpers (latexmlc) and MinerU's grandchild FastAPI survive — `start_new_session` is a no-op there so process-group kill is unavailable. This accepted gap is noted in two code comments but the operator-facing `security-pdf-sandbox.md` still describes only the POSIX process-group-kill discipline.
- **Why it matters:** The doc is the operator-facing threat-model claim. An operator reading it on Windows would believe grandchildren are reaped on timeout when they are not. Implementation-summary correctly lists the Windows addendum as a deferred doc task, so this is a known deferral, not a silent regression.
- **Proposed fix:** Add a short Windows paragraph to `.claude/docs/security-pdf-sandbox.md` under the existing "explicitly does NOT do" section stating that on Windows only the direct child is killed (grandchild Perl/MinerU survive), analogous to the documented MinerU-grandchild gap (CLAUDE.md gotcha #10).
- **Regression guard:** Doc-only; no test. Cross-link the doc paragraph to tools/arxiv_fetch.py:594 and ingest/textbook_parser.py:424 so future code/doc drift is greppable.

## What was done well

- The `hasattr(os, "getpgid")` guard is the documented-correct Windows guard and is applied identically in both call sites (tools/arxiv_fetch.py:597 and ingest/textbook_parser.py:430), closing the same bug class consistently (ADD-2 caught the unguarded MinerU-timeout twin that the brief's Fix 3 missed).
- ADD-2 correctly identified that `contextlib.suppress(ProcessLookupError, OSError)` does NOT catch the `AttributeError` Windows raises — a genuinely subtle find that a naive reviewer would miss.
- The cross-platform test idiom (`raising=False`/`create=True` on os.killpg/getpgid + `monkeypatch.setattr(signal, "SIGKILL", 9)`) is legitimately sound: because `af.signal is signal`, the monkeypatch mutates the shared module so the `signal.SIGKILL` assertion resolves on a Windows host — verified live, all four killpg tests pass here.
- The getpgid-absent test using `monkeypatch.delattr(os, "getpgid", raising=False)` genuinely exercises the Windows `proc.kill()` branch on any host — the real load-bearing regression guard, and it is present for both call sites.
- POSIX byte-identical intent is preserved: `_ENV_WHITELIST_WINDOWS` is unioned only on win32 and the TEMP/TMP override is win32-gated, so no new keys appear in the POSIX env dict.
- The Fix 2 `latexmlc_bin = shutil.which(...)` swap reuses the existing presence-check call (no extra PATH scan) and the None check runs before `cmd` is built, so `Popen(cmd[0]=None)` is unreachable on the normal path.
- The security review of the 13 Windows vars is thorough and correct: all are OS-infra/path pointers, the four named credential families (proxies, AWS, GCP, Azure/HF) remain stripped, and a disjointness guard test pins it.
- Both deferrals (server/config.py env-var rejection; TestUserAgent SQLite leakage) are correctly scoped out with accurate rationale — neither blocks the Windows parse path.
- No tool-schema, MCP-surface, dependency, or fork changes — the milestone stays tightly within its blast radius (ingest/tools/tests + .claude markdown only).
- Math fidelity untouched: cmd[0] is a path swap only; `--dest`/`--format=html5`/`detect_parse_success` are unchanged, so MathML output and parse-success detection are unaffected.

## Recommended rectification order

1. F2 — seed host TEMP/TMP in the Windows override test so it proves clobber-over-inherited (protects the scratch-isolation security contract; highest leverage).
2. F1 — pin the POSIX byte-identical contract on `_ENV_WHITELIST_POSIX` directly and drop the delenv masking (closes the import/call-time blind spot).
3. F4 — add the Windows paragraph to security-pdf-sandbox.md (operator-facing accuracy; doc-only).
4. F3 — inline COMSPEC rationale comment (cheapest; pure documentation).

## Rectification status

- F1 — fixed; pinned the POSIX byte-identical contract on the constant via
  new `test_posix_whitelist_excludes_temp_tmp` (asserts `"TEMP"/"TMP" not in
  _ENV_WHITELIST_POSIX`, platform-independent); the former call-based test
  split into `test_temp_tmp_override_not_fired_off_win32`.
  (tests/test_textbook_parser.py)
- F2 — fixed; `test_temp_tmp_overridden_on_windows` now seeds a host
  `TEMP`/`TMP` and asserts the override CLOBBERS it (`env["TEMP"] !=
  host_temp`), proving clobber-over-inherited, not mere set.
  (tests/test_textbook_parser.py:237)
- F3 — fixed; inline COMSPEC rationale comment (sole tolerated shell-path
  var, safe under shell=False) at ingest/textbook_parser.py
  `_ENV_WHITELIST_WINDOWS` + new `test_no_extra_shell_path_var_beyond_comspec`.
- F4 — deferred (LOW; doc-only). The Windows grandchild-reaping paragraph
  for `.claude/docs/security-pdf-sandbox.md` was scoped OUT by the research
  synthesis (the doc tracks the canonical impl; Windows addendum is a future
  doc task). The accepted gap IS documented in code comments at
  tools/arxiv_fetch.py:594 and ingest/textbook_parser.py:424. Tracked for a
  follow-up doc pass.

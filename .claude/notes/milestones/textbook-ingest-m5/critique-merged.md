# Critique — textbook-ingest-m5

**Critic:** adversary
**Generated:** 2026-05-28T01:59:11Z
**Commit range:** `8dda5ae6..b0bf74cc`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. Core sandbox driver is sound; lockstep doc updates and dependency-supply-chain hygiene have a small handful of misses that warrant rectification before m6 builds on this surface.
- Finding counts: 0 CRITICAL, 3 HIGH, 4 MEDIUM, 2 LOW.
- Highest-risk site: `uv.lock::transformers` silently downgraded 5.8.0 → 4.57.6 as a side-effect of adding the MinerU `[pdf]` extra. Affects every BGE-M3 / BGE-reranker call path in the project; not justified or tested in this milestone.
- Lockstep doc miss: `.claude/docs/security-pdf-sandbox.md:44` still references "MinerU 2.5" — the implementation summary claimed full sweep done. Same shape as the m4 F2 "stale-docstring" anti-pattern guard.
- F-FLAG-1 from research synthesis was punted to a "separate follow-up issue" but the issue was never filed. `gh issue list --repo chris-dare-dev/arXMCP` returns only Threats 2/6/7 — no entry for `server/lean_repl.py` RLIMIT_AS audit. "Deferred without tracking" violates the synthesis contract.
- Observability gap on timeout path: partial-output drain via second `proc.communicate()` is discarded by `contextlib.suppress`. Stdout/stderr captured during the drain window is silently dropped.
- The happy-path "integration" coverage in `TestRunMineruSandboxedSurface` pre-creates the output tree before mocking Popen — the test exercises a hand-crafted shape, not the actual `_locate_outputs` fallback against real MinerU output. Synthesis explicitly called out FM-4; the fallback's `md_candidates[0]` selection is untested against multi-file outputs.
- `test_default_timeout_used_when_none` is a tautology: asserts `comm_kwargs["timeout"] == textbook_parser._CONFIGURED_TIMEOUT_S` where both sides resolve to the same module-level constant. Cannot detect a regression where the driver started ignoring `None` and using a hard-coded literal.
- No regression test that the `RLIMIT_AS not enforceable` WARN log fires at module import on Darwin/Windows. Synthesis §D1 explicitly required this.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Silent `transformers` major-version downgrade via [pdf] extras

- **Severity:** HIGH
- **Source:** adversary
- **File:** uv.lock (transformers entry); pyproject.toml:191-192
- **What:** Adding `mineru[pipeline]>=3.2.0,<4` to `[project.optional-dependencies].pdf` silently downgraded `transformers` from 5.8.0 → 4.57.6 in `uv.lock` because MinerU's transitive deps cap transformers at v4. The downgrade also removed `typer`, `rich`, `shellingham`, `markdown-it-py`, `mdurl` (formerly transitive transformers v5 deps) and added ~30 new direct/transitive packages.
- **Why it matters:** `transformers` is used directly by `ingest/embedder.py`, `ingest/chunker.py`, `server/resources.py`, `server/retrieval/rerank.py` — every BGE-M3 / BGE-reranker code path in the project. v5 → v4 is a major-version change, not a patch. The project's `transformers>=4.40` spec allows both, but the milestone never acknowledges that adding the `[pdf]` extra forces the entire project to v4 (no opt-out). The implementation summary does not mention this. CLAUDE.md §3 status table marks E03/E07 as SHIPPED on the v5 tree; this re-pins them onto v4 without retesting the embedder pipeline. Tests pass because the BGE-M3 calls use stable `AutoTokenizer.from_pretrained` / `AutoModel.from_pretrained` APIs — but `requires_model` tests are skipped by default, so the cold-path BGE-reranker code on v4 has not been exercised in this milestone.
- **Proposed fix:** Either (a) document the downgrade in `implementation-summary.md` + `CLAUDE.md §8` as a deliberate trade-off and run `pytest -m requires_model` to validate BGE-M3/reranker still works on transformers 4.57.6, or (b) avoid the project-level transitive pull by removing the `[pdf]` extra from the lockfile (operators install MinerU into the separate venv per `docs/install.md` — which is the actually-recommended path). If (b), regenerate `uv.lock` without the `[pdf]` extra resolved.
- **Regression guard:** Add a `tests/test_dep_pins.py` check that asserts `transformers.__version__.startswith("5.")` (or whichever is canonical) so a future lock churn does not silently regress it. Pin transformers explicitly in `pyproject.toml` (`transformers>=5.0` if the project intends to track v5).

### F2 — Stale "MinerU 2.5" reference in lockstep-updated security doc

- **Severity:** HIGH
- **Source:** adversary
- **File:** .claude/docs/security-pdf-sandbox.md:44
- **What:** The threat-mitigation table row for "Network egress from PDF parser" still says "Confirmed: MinerU 2.5 has no documented network-fetch path during PDF parsing". The implementation summary claimed `"MinerU 2.5" → "MinerU 3.2.0" everywhere` was completed in lockstep. `grep -n "MinerU 2\.5" .claude/docs/security-pdf-sandbox.md` returns this line.
- **Why it matters:** Same shape as the recurring "doc says X, code does Y" pattern (m3 F1 BP1-description-vs-handler drift; m4 F2 stale-docstring anti-pattern). The threat-model claim is now factually unverifiable — we have NOT confirmed MinerU 3.2.0 has no network-fetch path (3.x adds a grandchild FastAPI server that DOES bind a loopback port). The doc states a claim about 2.5 inside a doc that the milestone otherwise updates to 3.2.0. Operator-facing security contract drift.
- **Proposed fix:** Edit line 44 to either (a) "Confirmed: MinerU 3.2.0 with `-b pipeline -m auto` runs ONNX inference from `~/.cache/mineru/` with no external network calls observed in B1 smoke test (the internal FastAPI server binds loopback only — see §architectural caveat)", or (b) drop the "Confirmed" framing and say "MinerU 3.2.0's pipeline backend has no documented external-network-fetch path; the internal FastAPI server is loopback-only".
- **Regression guard:** Add `tests/test_doc_consistency.py` (new) that greps `.claude/docs/security-pdf-sandbox.md` for `MinerU 2\.5` and fails if any match. Lockstep-update tripwire.

### F3 — F-FLAG-1 (`server/lean_repl.py` RLIMIT_AS audit) deferred without a tracked follow-up issue

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/lean_repl.py:176-188 (broken-on-Darwin guard); research-synthesis.md:38, 124; implementation-summary.md:38
- **What:** The research synthesis §F-FLAG-1 (and the docstring update in `.claude/docs/security-pdf-sandbox.md:465`) explicitly directed that the `server/lean_repl.py` RLIMIT_AS audit be filed as a follow-up GitHub issue at `chris-dare-dev/arXMCP`. The implementation summary says "Outstanding follow-up: `server/lean_repl.py` audit (separate issue)" — but `gh issue list --repo chris-dare-dev/arXMCP --limit 30` returns only three open issues (Threats 2, 6, 7). No entry for the Lean REPL RLIMIT_AS audit. Meanwhile `server/lean_repl.py:179` still gates on `sys.platform != "win32"`, meaning the SAME broken-on-Darwin RLIMIT_AS pattern this milestone documented as a verified gap is still live in the Lean REPL path.
- **Why it matters:** "Deferred without tracking" is the named anti-pattern. The verified Darwin gap on RLIMIT_AS exists in both `ingest/textbook_parser.py` (fixed) and `server/lean_repl.py` (still broken). The lean_repl gap matters because that subprocess also runs operator-supplied code (Lean proofs) — same threat shape as MinerU. Without a tracking issue, this knowledge evaporates after the m5 chore commit.
- **Proposed fix:** File the GitHub issue at `chris-dare-dev/arXMCP` BEFORE the chore-notes commit closes the milestone. Title: `server/lean_repl.py: broken-on-Darwin RLIMIT_AS guard (verified by textbook-ingest-m5)`. Body: cite `server/lean_repl.py:179`, the verified live test in `textbook-ingest-m5 research-brief-2`, and the fix shape (gate on `sys.platform == "linux"`, not `!= "win32"`).
- **Regression guard:** Add a comment in `server/lean_repl.py` at line 179 referencing the GitHub issue number so a future agent finds the tracking ID.

### F4 — `_locate_outputs` glob fallback may pair a markdown from one section with content_list from another

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_parser.py:269-284
- **What:** When the documented direct path is not found, the fallback runs two independent `rglob("*.md")` + `rglob("*_content_list.json")` calls and returns `md_candidates[0]` + `cl_candidates[0]` — alphabetically first of each. If a future MinerU release emits multiple `.md` files per parse (e.g. per-chapter splits, or `<stem>.md` + `<stem>_images.md`), the markdown returned may not be the principal output AND it is paired with whichever `_content_list.json` happens to sort first — possibly from a different subdirectory.
- **Why it matters:** Synthesis §D3 explicitly called out FM-4 as a mitigated risk. The direct-path probe IS the mitigation; the fallback's "pick the first alphabetically" is fragile. MinerU 3.2.0 today emits a single `.md` + `.json` pair per parse — but the milestone's selling point is the contract m6 consumes, and that contract should not silently mis-pair files on a 3.x point-release that adds a per-section breakdown.
- **Proposed fix:** Restrict the fallback to MD+CL pairs that live in the SAME parent directory: walk `md_candidates`, find the first whose `parent` also contains a matching `_content_list.json`; return that pair. If none match, raise RuntimeError with the directory listing.
- **Regression guard:** Add `TestLocateOutputs::test_glob_fallback_picks_paired_files` covering the scenario where `output_dir` contains `dirA/x.md` + `dirB/y_content_list.json` (no paired set) — current code would happily return mismatched files; new code raises.

### F5 — Timeout-path observability: drain `communicate()` output is silently discarded

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_parser.py:381-382
- **What:** On `subprocess.TimeoutExpired`, the driver kills the process group, then runs `with contextlib.suppress(subprocess.TimeoutExpired): proc.communicate(timeout=_DRAIN_TIMEOUT_S)`. The drain call's return value (stdout, stderr captured between kill and reap) is bound to nothing. The re-raised `TimeoutExpired` exception carries the partial output from BEFORE the kill (Python's `Popen.communicate` populates the exception's `.stdout` / `.stderr` from what was already in the buffer when the timeout fired), but anything that arrived during the kill window — including potential SIGKILL-aborted log lines like `[ERROR] killed mid-page-decode at offset N` — is gone.
- **Why it matters:** The timeout path is the most security-relevant code path (this is where a malicious PDF wedges the parser). Losing diagnostics here makes triage harder. The fix is one line.
- **Proposed fix:**
  ```python
  drained_stdout = drained_stderr = ""
  with contextlib.suppress(subprocess.TimeoutExpired):
      drained_stdout, drained_stderr = proc.communicate(timeout=_DRAIN_TIMEOUT_S)
  logger.warning(
      "textbook_parser: mineru exceeded %ds wall timeout for %s; killed pgid=%s; "
      "drain stderr tail: %s",
      effective_timeout, pdf_path.name, proc.pid, _tail(drained_stderr or "", 1024),
  )
  raise
  ```
- **Regression guard:** Extend `test_timeout_triggers_killpg` to have the second `communicate()` side-effect return non-empty `("late stdout", "late stderr")` and assert the WARN log captures them (via `caplog`).

### F6 — `test_default_timeout_used_when_none` is a tautology, not a regression guard

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_textbook_parser.py:470-483
- **What:** The test asserts `comm_kwargs["timeout"] == textbook_parser._CONFIGURED_TIMEOUT_S`. `_CONFIGURED_TIMEOUT_S` is a module-level constant resolved at import time from `_parse_timeout_from_env()`. The test passes `timeout_s=None`; the driver computes `effective_timeout = _CONFIGURED_TIMEOUT_S if timeout_s is None else int(timeout_s)`. Both sides of the assertion resolve to the same constant on the same import. A regression where the driver started using a hard-coded literal (e.g. `effective_timeout = 1800`) on the `None` path would pass this test silently because `_CONFIGURED_TIMEOUT_S == 1800` by default.
- **Why it matters:** The synthesis (and CLAUDE.md §8 landmines) emphasized that timeout misconfig must surface at server-startup. A test that cannot detect "driver ignores `_CONFIGURED_TIMEOUT_S`" provides false confidence.
- **Proposed fix:** Either (a) reload the module under a monkeypatched env (`importlib.reload(textbook_parser)` after `monkeypatch.setenv("ARXMCP_MINERU_TIMEOUT_S", "180")`) and assert `comm_kwargs["timeout"] == 180`, or (b) replace the assertion with a direct check that `effective_timeout` was the module's `_CONFIGURED_TIMEOUT_S` at function-call time — by patching `_CONFIGURED_TIMEOUT_S` in-module to a sentinel value and verifying the driver picked it up. The reload variant is cleaner.
- **Regression guard:** The fix IS the regression guard.

### F7 — No regression test that the macOS/Windows RLIMIT_AS WARN log fires at module import

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_parser.py:141-146; tests/test_textbook_parser.py (missing)
- **What:** Synthesis §D1 explicitly required "Darwin / Windows WARN log at module import time (not call time)". The driver implements this at lines 141-146 (the `else` branch of the platform gate). There is NO regression test that the WARN fires. A future PR that silently drops the WARN (e.g. moves the gate but forgets the log) would not be caught.
- **Why it matters:** The WARN is the only operator signal that the verified-live macOS gap is in effect. Silence here means an operator on Darwin assumes the documented RLIMIT_AS cap is active when in fact only the wall timeout is.
- **Proposed fix:** Add a test that reimports the module under `monkeypatch.setattr(sys, "platform", "darwin")` and asserts `caplog.records` contains the expected WARN. The challenge is that `sys.platform` is checked at import — the test must use `importlib.reload(textbook_parser)` inside the monkeypatch context.
- **Regression guard:** New `TestPlatformSetup::test_warn_fires_on_non_linux_import` using `importlib.reload` + `caplog`.

### F8 — Happy-path Popen mock bypasses `_locate_outputs` against realistic MinerU output

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_textbook_parser.py:336-349
- **What:** `_make_pdf_and_outputs` pre-creates `out_dir/<stem>/auto/<stem>.md` + `<stem>_content_list.json` BEFORE the Popen mock is installed. The "happy path" test therefore exercises the direct-path branch of `_locate_outputs`, not the fallback glob, and does so against a hand-crafted shape that may diverge from real MinerU output. The synthesis explicitly flagged FM-4 (MinerU output-tree convention drift); the only meaningful coverage is the opt-in `TestRealMineru` test which is skipped by default.
- **Why it matters:** Low because the fallback glob HAS its own dedicated unit tests in `TestLocateOutputs`. But the gap between "we mocked the happy path" and "we ran MinerU 3.2.0" is wider than the implementation summary implies. Operator who reads `tests/test_textbook_parser.py` should not infer that `requires_mineru`-skipped tests are not running on CI; they aren't.
- **Proposed fix:** Add a comment at the top of `_make_pdf_and_outputs` explicitly noting it produces a HAND-CRAFTED output tree to satisfy `_locate_outputs`, and pointing readers at `TestRealMineru` for the only end-to-end coverage. Consider a separate test that runs the locator against the actual `b1-smoke-test` output tree fixture (if preserved) to validate the direct-path matches reality.
- **Regression guard:** None required for LOW — informational.

### F9 — Import-time WARN log emits on every Darwin test run (noise)

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/textbook_parser.py:141-146
- **What:** The WARN at lines 141-146 fires at every module import on non-Linux platforms. Running the test suite on macOS (the user's primary dev box) emits this warning once per test process. With pytest's default fixture / session setup, this can pollute test output. No real harm — but operator-perceived noise.
- **Why it matters:** Low. The user's dev environment is macOS; reducing log noise is quality-of-life. The warning is correct; the placement is the issue.
- **Proposed fix:** Two options: (a) accept the noise (current behavior — it IS load-bearing operator signal); (b) emit at first `run_mineru_sandboxed()` call instead of import (use a module-level `_warn_fired` flag). Option (a) is probably right — the synthesis explicitly chose import-time. If keeping, no change.
- **Regression guard:** None.

## What was done well

- Layer-2 sandbox profile is implemented faithfully against the prescriptive contract in `.claude/docs/security-pdf-sandbox.md`. Process-group kill via `start_new_session=True` + `os.killpg`, drain `communicate()` to avoid deadlock, env scrubbing with TMPDIR override — all match the spec.
- `_parse_timeout_from_env()` validates at module load with clear RuntimeError on out-of-range or non-integer. No silent clamp. ARXMCP_MINERU_TIMEOUT_S misconfig surfaces at server startup, not first PDF upload — exactly as the synthesis required.
- D1 disagreement (macOS RLIMIT_AS) was resolved per the live-tested research finding, not the optimistic assertion. Gating on `sys.platform == "linux"` is the correct mitigation; the WARN log is the right escape hatch.
- D2 disagreement (MinerU grandchild gap) is documented in `.claude/docs/security-pdf-sandbox.md §"explicitly does NOT do"` with the threat-model rationale (loopback-only, accepted gap). Not silently swallowed.
- `MinerUResult` is a frozen dataclass — m6 cannot accidentally mutate. The `_tail()` truncation is UTF-8-safe via `errors="replace"`.
- `requires_mineru` marker correctly mirrors the `requires_pdflatex` pattern: opt-in via marker + env var with lazy-string skipif (the F7 pattern from `parser-fidelity-eval-m1`).
- The 45 always-run unit tests cover the helper surface comprehensively: env parsing, binary resolution, env scrubbing, tail truncation, output locator, and the run_mineru_sandboxed surface with Popen mocked.
- Zero `assert` statements in production code (`ingest/textbook_parser.py`). All invariant checks raise `RuntimeError` — respects the CLAUDE.md §4.7 ban.
- No shell escape: `subprocess.Popen` invoked with explicit args list, no `shell=True`. No git submodule, no vendored MinerU code lift — no-fork policy honored.
- `pyproject.toml` extras correctly isolates MinerU under `[pdf]` rather than core deps. The `[mlx]` deliberately omitted from the project extra (would break Linux installs) — documented correctly in `docs/install.md` as a separate-venv concern.
- CLAUDE.md §8 entries #9 (macOS RLIMIT_AS) and #10 (grandchild FastAPI gap) document both verified-live findings as landmines so future agents do not relitigate them.

## Recommended rectification order

1. **F2** (stale doc) — single-line edit, prevents the recurring "doc-implementation drift" pattern from breeding another instance.
2. **F3** (file the follow-up issue) — must happen before chore-notes commit; otherwise the audit gets lost.
3. **F1** (transformers downgrade) — either justify-and-test or remove from project lockfile. Highest blast radius; lowest fix effort if option (b) is chosen.
4. **F5** (timeout observability) — one-line capture + add to WARN log. Two-line code change + test extension.
5. **F4** (glob fallback pair-matching) — small refactor; the unit-test scaffold is already in place.
6. **F6** (tautology test) — replace with reload-based variant. ~10 LOC.
7. **F7** (WARN log regression test) — new test with `importlib.reload` + `caplog`. ~15 LOC.
8. **F8, F9** — defer to `deferred_findings`; informational only.

## Rectification status

- F1 — FIXED: removed `[pdf]` extras from `pyproject.toml`; ran `uv lock --upgrade-package transformers` to restore transformers from 4.57.6 → 5.9.0. The driver invokes MinerU via subprocess only (no `import mineru` in project code, confirmed via grep), so the dropped Python package has no in-process consumer. Documented rationale in pyproject.toml comment block.
- F2 — FIXED: edited `.claude/docs/security-pdf-sandbox.md:44` to reflect MinerU 3.2.0 + the loopback-only LocalAPIServer. The remaining line-14 "MinerU 2.5" reference is intentional historical preservation in the Scope section.
- F3 — PARTIALLY FIXED in this commit: added a code comment at `server/lean_repl.py:171-180` explicitly cross-referencing CLAUDE.md §8 #9 + the m5 verified-live finding, and queueing the audit-issue creation. **Remainder requires external write** (`gh issue create`) — surfaced in the Phase-4 external-write boundary check below for user authorization.
- F4 — FIXED: `_locate_outputs` fallback now pair-matches md+content_list in the SAME parent dir via `md.with_name(stem + "_content_list.json")`, never cross-pairing across subdirs. Regression guards added: `TestLocateOutputs::test_glob_fallback_picks_paired_files` (mismatched layout raises) + `::test_glob_fallback_finds_first_paired` (multiple md, picks first with companion).
- F5 — FIXED: drained stderr now captured in the timeout-path WARN log; tail-truncated to 1024 bytes. Regression guard: extended `test_timeout_triggers_killpg` with `caplog` assertion that the drained stderr (`"[ERROR] killed mid-decode at offset 42"`) appears in the WARN message.
- F6 — FIXED: replaced tautological `test_default_timeout_used_when_none` with a `monkeypatch.setattr(textbook_parser, "_CONFIGURED_TIMEOUT_S", 173)` sentinel variant. A regression where the driver hard-codes a literal would now fail with `173 != <literal>`.
- F7 — FIXED: added `TestPlatformSetup::test_warn_fires_on_non_linux_import` that spawns a Python subprocess with `sys.platform = "darwin"` set BEFORE the `from ingest import textbook_parser` import, then asserts the RLIMIT_AS WARN appears in stderr. Subprocess isolation chosen over `importlib.reload` to avoid in-process class-identity pollution that would invalidate downstream `isinstance(x, MinerUResult)` checks.
- F8 — DEFERRED (LOW; informational only per adversary recommendation).
- F9 — DEFERRED (LOW; informational only per adversary recommendation).

**Invalidation rate:** 0% (none of the 9 findings invalidated on re-verify; all matched the cited file:line region exactly).

**External writes still required after this commit:**
- `gh_issue_create` on `chris-dare-dev/arXMCP` — final closure of F3. Gated through Phase 4's external-write boundary check.

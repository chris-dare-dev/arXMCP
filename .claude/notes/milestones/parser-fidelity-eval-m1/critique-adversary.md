# Critique — parser-fidelity-eval-m1

**Critic:** adversary
**Generated:** 2026-05-23T00:00:00Z
**Commit range:** `96395ee594f573f0b59d74c5e88c3800bf06a14e..9f6efe9c199983c6149ea9b1c1912d26feee1ac3`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES — the milestone lands a clean, well-isolated CDM scaffold and the subprocess discipline mirrors the LaTeXML precedent, but two real correctness/security gaps need to land before the gate can be trusted as a parser-bake-off arbiter.
- Finding counts: 0 CRITICAL, 2 HIGH, 6 MEDIUM, 3 LOW.
- Highest-risk file:line — `tools/cdm_eval.py:565` (ordering-cost normalization divides by `m`/`n` after invisible tokens are filtered, distorting `lo` past 1.0 for any formula whose visible token count is smaller than its raw token count — i.e., almost every formula).
- Second-highest — `.claude/docs/security-cdm-sandbox.md:22-23` claims `--no-shell-escape` blocks `\openout` redirects (factually wrong — `openout_any` is a separate kpathsea setting) and claims TMPDIR cwd bounds the file-system view from `\input` (false — `\input{/etc/passwd}` uses absolute paths, controlled by `openin_any`, not cwd).
- Cross-axis pattern: the implementation is honest about its deviations (5 explicit ones listed in the summary), but two undocumented deviations slipped in — the fixture's MathML is hand-written despite README/manifest claiming "LaTeXML output", and `_pdflatex_available()` is evaluated at module-import time rather than test-run time, which subtly affects late-bound env-var enablement.
- The 0.85 threshold + 4-band interpretation rubric are project-invented; the README presents them as if backed by the CDM paper or OmniDocBench, but neither defines those bands. Defensible defaults but should be labeled "arXMCP-chosen" so future re-tuning doesn't get blocked by phantom upstream authority.
- The `aggregate_cdm` silent-zero-on-failure behavior is the right call for a continuous eval (halt-loud would prevent partial-fixture iteration), but the returned tuple loses the failure count — operator reads "mean=0.72" without learning that 3/20 pages crashed. Easy fix; no test asserts the failure-as-zero path.
- Test count delta +44 vs brief target +15-25 is justified by class-parametrized fixture-structure tests; not padding. No Tier-3 (`requires_pdflatex`) test exercises `_cost_matrix` integration with `aggregate_cdm`, so the ordering-cost bug (F1) is invisible until a real-world fixture is scored.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Ordering cost `lo` normalizes by visible-count, distorting >1.0

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/cdm_eval.py:565`
- **What:** `_cost_matrix` computes `lo = abs(p.index / max(m, 1) - g.index / max(n, 1))` where `m`/`n` are the **visible-token counts** (tokens with a detected bbox), but `p.index`/`g.index` are the **raw-tokenizer indices** (including invisible braces, sub/super markers, etc.). For `\frac{a}{b}`, tokenizer produces 7 tokens, but only `a` and `b` render — so `m=2` while `p.index∈{2,5}`. The normalized positions become `1.0` and `2.5`, and `lo` for the (a,b) pair is `1.5`, dwarfing the other cost terms.
- **Why it matters:** The CDM paper specifies `Lo` as a normalized ordering cost intended to be in `[0,1]`. The combined cost `Wt*Lt + Wp*Lp + Wo*Lo` with `Wo=0.1` and `Lo=1.5` adds `0.15` per pair — pushing many otherwise-perfect token matches over the `0.5` `cost_threshold`. This biases the F1 score DOWNWARD on any formula with bracing/scripting, which is nearly every math formula. The gate is supposed to certify parsers at ≥0.85; this bug makes ≥0.85 harder to clear than the paper intends, and worse, it does so non-uniformly (long formulas suffer more), which makes the bake-off comparisons meaningless across formula lengths.
- **Proposed fix:** Normalize by raw-token-count, not visible-count. Capture `len(predicted)` and `len(ground_truth)` (before the `bbox is not None` filter) into `_cost_matrix` and use them as denominators. Sketch:
  ```python
  def _cost_matrix(predicted, ground_truth, *, pred_img_shape, gt_img_shape):
      pred_raw_n = len(predicted)   # NEW: full count before filter
      gt_raw_n = len(ground_truth)
      pred_visible = [t for t in predicted if t.bbox is not None]
      gt_visible = [t for t in ground_truth if t.bbox is not None]
      ...
      lo = abs(p.index / max(pred_raw_n, 1) - g.index / max(gt_raw_n, 1))
  ```
- **Regression guard:** Add a unit test that builds two synthetic `TokenBbox` lists with `m`/`n` much smaller than `max(p.index)`/`max(g.index)` (e.g., 2 visible tokens with index=5 and index=10) and asserts `lo ≤ 1.0` for every cell. The current code yields `lo=2.5` for the index-5/index-10 pair under `m=n=2`.

### F2 — Sandbox doc materially misstates `--no-shell-escape` / `\input` mitigations

- **Severity:** HIGH
- **Source:** adversary
- **File:** `.claude/docs/security-cdm-sandbox.md:22-23`
- **What:** The threat-surface table makes two factually-wrong claims:
  1. Line 22 — "`\write18` shell escape | `--no-shell-escape` (hard flag; cannot be overridden by `\openout` redirects)". `--no-shell-escape` controls `\write18` (process spawn), but `\openout` is governed by the separate `openout_any` kpathsea setting (`p`/`r`/`a` = paranoid/restricted/any). `--no-shell-escape` does not affect `openout_any`. A hostile `.tex` can still `\openout1=/path/file \write1{contents}\closeout1` to write arbitrary files under the user's open-file permissions on a default-installed texlive (which usually sets `openout_any=p` to restrict to cwd — meaning the mitigation exists but is delivered by `openout_any`, NOT by `--no-shell-escape`).
  2. Line 23 — "`\input{/etc/passwd}` arbitrary read | TMPDIR-only working directory (the process can still read system fonts, but the file-system view is bounded to the sandbox cwd)". This is wrong on two counts: (a) pdflatex resolves absolute paths in `\input` regardless of cwd — the cwd binding does nothing for absolute paths; (b) the actual mitigation is `openin_any` (also kpathsea), which defaults to `a` (any) on most distros, meaning `\input{/etc/passwd}` succeeds on a stock texlive install and dumps the file contents into the rendered PDF. This is an information-disclosure vector against any deployment that runs `cdm_score` on operator-uploaded LaTeX (current scope is test-fixture-only, but the threat-3-peer doc must be accurate for future scope expansion).
- **Why it matters:** Threat models that document false mitigations are worse than no threat model — they convince future contributors not to add the real mitigation. The Threat-3 peer doc is the canonical reference for "is this safe?" reviews; if it falsely promises shell-escape coverage of `\openout`, a future milestone that exposes `cdm_score` to operator-controlled LaTeX (e.g., as a quality probe on parser-emitted output) will inherit the false sense of safety.
- **Proposed fix:** Two changes:
  1. Rewrite the table rows for `\write18`, `\openout`, and `\input` to separate the mitigations. The accurate row set:
     | `\write18` shell escape | `--no-shell-escape` (kpathsea `shell_escape=f`) |
     | `\openout` arbitrary file write | NOT mitigated by `--no-shell-escape` — set `openout_any=p` via env (`TEXMF_OUTPUT_DIRECTORY` + kpathsea config) or accept the risk for test-fixture-only scope |
     | `\input{/etc/passwd}` arbitrary read | NOT mitigated by cwd binding — set `openin_any=p` via env (`OSFONTDIR`/`TEXMFCNF`) or accept the risk for test-fixture-only scope |
  2. Wire the actual mitigation in `tools/cdm_eval.py::render_latex_to_image` by passing `env={**os.environ, "openin_any": "p", "openout_any": "p", "shell_escape": "f"}` to `subprocess.Popen` — texlive honors these env vars at startup.
- **Regression guard:** Add a `requires_pdflatex` test that attempts `\input{/etc/passwd}` inside a wrapped formula and asserts pdflatex reports an `openin_any` violation (or alternately, that the rendered PDF does not contain the string "root:x:" — easier to assert without filesystem dep). Today the test would silently succeed because there is no mitigation.

### F3 — `aggregate_cdm` loses failure count when pages crash

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/cdm_eval.py:686-704`
- **What:** `aggregate_cdm` returns `(mean: float, scores: list[float])`. When a page raises `RuntimeError` or `TimeoutExpired`, it appends `0.0` and continues. The returned `scores` list does not distinguish "rendered but scored 0.0" from "render crashed and we substituted 0.0", and the mean is computed across both.
- **Why it matters:** The operator reads `mean=0.72` and has no signal whether the gate failed because the parser is bad or because the fixture has 3/20 broken pages. With a 0.85 threshold and 20 pages, just 3 crashed pages substituting zero would drop a true 0.90 parser to 0.765 — below the gate. The eval reports a false-negative without surfacing the cause. This is a load-bearing observability gap for the parser-bake-off use case.
- **Proposed fix:** Return a dataclass `AggregateResult(mean: float, scores: list[float], failures: list[tuple[int, str]])` where `failures` is `(pair_index, exception_msg)` for each substituted-zero entry. Update the gate's TIER-GATES.md command to reject when `len(failures) > N` regardless of mean.
- **Regression guard:** Add a Tier-1 (no pdflatex) test that uses a mocked `cdm_score` raising `RuntimeError("boom")` for the second of three pairs and asserts the returned `AggregateResult.failures == [(1, "boom")]`.

### F4 — Fixture MathML files are hand-written but documented as "LaTeXML output"

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/eval/textbook_fixtures/README.md:39-40` + `tests/eval/textbook_fixtures/paper-control/01-formula.mathml`
- **What:** The fixture README claims:
  > "For the `paper-control` and `milne-style` fixtures, this is generated via LaTeXML on the original `.tex` source."
  Inspecting `01-formula.mathml` and `02-formula.mathml`, they use bare `<math>`/`<munderover>`/`<mfrac>` tags without LaTeXML's typical namespace prefixes, `xref` cross-IDs, `RDFa` annotations, or `<semantics>/<annotation encoding="application/x-tex">` blocks. A real `latexmlc --noinvisibletimes` output for `\sum_{i=1}^{n} a_i x^i` produces ~80-120 lines of MathML with attributes like `class="ltx_Math"`, `xml:id="m1"`, `<annotation encoding="application/x-tex">`. The shipped files are 9 and 19 lines — visibly hand-typed approximations.
- **Why it matters:** The future parser-bake-off will use these files as ground truth for CDM scoring. A parser whose MathML matches LaTeXML's verbose form will score POORLY against the hand-typed sparse form (the .tex round-trip will differ), and vice versa. The fixture's ground-truth basis must be one or the other — consistently — and the doc must say which. Hand-typed is fine for a v0 harness, but it must be labeled to prevent the operator from regenerating later via `latexmlc` and accidentally rebasing the fixture against a different ground-truth shape.
- **Proposed fix:** Either (a) regenerate the 2 example pages with `latexmlc --dest=... --noinvisibletimes` and commit the verbose output, OR (b) update the README and `manifest.json:classes.paper-control.attribution` to say "synthetic LaTeX, hand-written MathML approximation — when the operator adds the remaining 3 pages, decide whether to use LaTeXML or continue hand-typing; ground-truth shape MUST be consistent across pages". Then update the regenerate-from-LaTeXML bash snippet at README:122-126 to either run only against the 18 hand-curated pages or skip the existing 2.
- **Regression guard:** Add a Tier-2 fixture-validation test that picks one shape rule (e.g., "all paper-control MathML files contain `<annotation encoding=\"application/x-tex\">`" for the LaTeXML path, or "all paper-control MathML files are ≤ 50 lines" for the hand-typed path) and asserts it across the directory. Catches future drift between the two shapes.

### F5 — `\halt-on-error` missing; `--interaction=nonstopmode` can spin on warnings

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/cdm_eval.py:395-403`
- **What:** pdflatex is invoked with `--interaction=nonstopmode` but without `-halt-on-error`. `nonstopmode` only suppresses the interactive prompt on error; pdflatex continues processing, emitting warnings/errors to the log, and can produce a non-zero retcode AND a partially-valid PDF. For pathological input (e.g., a deeply nested `\edef` macro), the run consumes most of the 30s timeout emitting warning noise before failing — wasting fixture-eval wallclock and producing a cryptic `pdflatex failed (exit 1)` error tail.
- **Why it matters:** With `-halt-on-error`, pdflatex exits on the first true error (not warning), letting the gate fail fast and surface a clean error line in the log tail. Without it, the `result.stdout[-500:]` log tail captured at line 408 often misses the actual triggering error because it's buried under hundreds of cascading warnings.
- **Proposed fix:** Add `-halt-on-error` to the argv at line 397-401:
  ```python
  [pdflatex, "--no-shell-escape", "--interaction=nonstopmode",
   "-halt-on-error",
   "-output-directory", str(work), str(tex_path)]
  ```
- **Regression guard:** Add a `requires_pdflatex` test that passes a deliberately-broken formula (e.g., `\frac{a` with no close brace) and asserts the subprocess returncode is nonzero AND the elapsed wallclock is under 5s (proving `-halt-on-error` prevented the 30s timeout path).

### F6 — `proc.wait()` after killpg can deadlock on full PIPE buffers

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/cdm_eval.py:325-331`
- **What:** On `TimeoutExpired`, the code does `os.killpg(...)` then `proc.wait()`. The LaTeXML precedent at `tools/arxiv_fetch.py:383-391` uses `contextlib.suppress(subprocess.TimeoutExpired): proc.communicate(timeout=5)` instead — to **drain stdout/stderr PIPEs** before reaping. If pdflatex (or pdftoppm) had filled the pipe buffer (64 KB on Linux, varies on macOS) and the killed process hasn't been fully reaped, `proc.wait()` can block indefinitely waiting for the OS to mark the process gone while the kernel still holds buffered output destined for the closed reader. The precedent's pattern handles this.
- **Why it matters:** pdflatex emits its full log to stdout in nonstopmode; on a complex formula or macro-recursion hang, the 64KB pipe buffer fills quickly. The current code's `proc.wait()` is best-case-instant, worst-case-hang. Since the surrounding test has a 30s timeout already, the hang surfaces as test infra noise, but the failure mode (test runner blocked indefinitely until killed by external timeout) is harder to debug than a clean propagated `TimeoutExpired`.
- **Proposed fix:** Replace `proc.wait()` with the precedent's pattern:
  ```python
  except subprocess.TimeoutExpired:
      with contextlib.suppress(ProcessLookupError, OSError):
          os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
      with contextlib.suppress(subprocess.TimeoutExpired):
          proc.communicate(timeout=5)
      raise
  ```
  (Also drops the bare `logger.warning` swallow — `OSError`/`ProcessLookupError` here are benign and quietly suppressed in the precedent.)
- **Regression guard:** Hard to write a deterministic test for this without controlling pipe-buffer fill, so this fix is "match the precedent and inherit its coverage." Acceptable for MEDIUM.

### F7 — `_pdflatex_available()` evaluated at module import, not test run

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/eval/test_parser_fidelity.py:349-352`, `:365-368`, `:386-389`
- **What:** `@pytest.mark.skipif(not _pdflatex_available(), reason=...)` evaluates `_pdflatex_available()` at module-collection time (when pytest imports the test file). The function checks `shutil.which("pdflatex")`, `shutil.which("pdftoppm")`, AND `os.environ.get("ARXMCP_RUN_REAL_PDFLATEX") == "1"`. If a CI or developer harness sets `ARXMCP_RUN_REAL_PDFLATEX=1` via a pytest plugin or fixture (after import), the skipif still sees the import-time value and skips. The standard pytest pattern is to wrap the check in a lambda or pass the bool literal at definition: `pytest.mark.skipif("os.environ.get('X') != '1'", reason=...)` evaluates lazily.
- **Why it matters:** Hidden footgun for CI integrations that set the env via `pytest_collection_modifyitems` or session-scope autouse fixtures. The bug doesn't manifest in the current invocation pattern (`ARXMCP_RUN_REAL_PDFLATEX=1 pytest ...`) where the env is set before import. But it's the kind of thing that breaks silently a year from now when someone adds a CI fixture to flip the marker.
- **Proposed fix:** Use the string-condition form which pytest evaluates lazily:
  ```python
  @pytest.mark.skipif(
      "shutil.which('pdflatex') is None or shutil.which('pdftoppm') is None or os.environ.get('ARXMCP_RUN_REAL_PDFLATEX') != '1'",
      reason="pdflatex + pdftoppm not on PATH, or ARXMCP_RUN_REAL_PDFLATEX != 1",
  )
  ```
  Or define a session-scope fixture that does the check and use `pytest.skip()` inside the test body.
- **Regression guard:** Add a tests/conftest.py session-scope autouse fixture that sets `ARXMCP_RUN_REAL_PDFLATEX=1` if a sentinel env (`ARXMCP_PDFLATEX_LATE_BOUND_TEST=1`) is set, then assert in CI that the Tier-3 tests would not have been skipped if the sentinel was active. (Skip writing this if it's > 30 LOC; the fix itself is cheap.)

### F8 — README's CDM-band interpretation rubric is project-invented but presented as authoritative

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `README.md:97-105` (the "What scores mean" table)
- **What:** The four bands ≥0.95 / 0.85-0.95 / 0.70-0.85 / <0.70 are not in the CDM paper (arXiv:2409.03643), not in OmniDocBench's published thresholds, and not derived from a reproducible measurement. The README's only citation is "Nougat ~85% on clean papers" — which loosely justifies the 0.85 threshold, but says nothing about the other three bands. The table reads like an authoritative external rubric.
- **Why it matters:** When the parser-bake-off milestone runs Marker / MinerU / Docling and one comes back at 0.83, the operator will read "Marginal; recommend secondary parser" as if that were a published guideline. The cited source (Nougat paper) does not anchor the 0.70 boundary or the secondary-parser recommendation. This is the kind of "spec creep into folklore" that becomes load-bearing once cited.
- **Proposed fix:** Update the README to mark the rubric explicitly as arXMCP-chosen, with the reasoning. Sketch:
  > **What scores mean** (CDM F1 in [0, 1]; the four bands below are **arXMCP-chosen** based on the CDM paper's worked examples + the Nougat baseline — re-tune as parser-bake-off data accumulates):
- **Regression guard:** No test (this is documentation calibration). Phase 4 can fold into the rectification commit directly.

### F9 — TP=0 special-case branch is dead code

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/cdm_eval.py:666-669`
- **What:** The conditional:
  ```python
  if tp == 0 and (fp > 0 or fn > 0):
      score = 0.0
  elif tp == 0:
      score = 1.0  # already handled above; defensive
  ```
  The `elif tp == 0` branch fires only when `tp == 0 AND fp == 0 AND fn == 0`, i.e., `m == 0 AND n == 0`. But that case is already handled at lines 650-655 with an early `return`. So the `elif` is unreachable. The "defensive" comment acknowledges this, but the branch can be deleted.
- **Why it matters:** Dead code in a math kernel is a smell — future readers spend cycles trying to understand the unreachable case. Tiny LOC fix.
- **Proposed fix:** Remove the `elif tp == 0: score = 1.0` branch. The remaining `if tp == 0 and (fp > 0 or fn > 0)` collapses to `if tp == 0: score = 0.0` since the `m == 0 == n == 0` case is gone via early-return. The final shape:
  ```python
  if tp == 0:
      score = 0.0
  else:
      score = 2 * tp / (2 * tp + fp + fn)
  ```

### F10 — Token regex drops Unicode math identifiers (α, β, ∇, etc.)

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/cdm_eval.py:120-122`
- **What:** `_LATEX_TOKEN_RE = r"\\[a-zA-Z]+|\\[^a-zA-Z]|[a-zA-Z0-9]|[^a-zA-Z0-9\s\\]"`. The single-char alternations are ASCII-only — `[a-zA-Z0-9]` excludes accented letters and Greek symbols that appear as literal unicode in some author papers (e.g., `α + β = γ` written with literal Greek chars). The fall-through `[^a-zA-Z0-9\s\\]` will match them as "non-alphanumeric non-whitespace" — but each unicode char becomes its own token, and a multi-byte codepoint splits into bytes under naive regex (Python's `re` handles unicode correctly by default, so this is OK), but it means `α` is tokenized as one char, not as `\alpha`. Parser outputs that emit `\alpha` will mismatch against fixture-MathML that uses unicode `α`, scoring 0.
- **Why it matters:** Low because the fixture is project-controlled (operator will use `\alpha`-style), but it's a fragility worth a comment. The math-fidelity contract from `.claude/notes/01-mission-and-context.md` is about NOT silently dropping symbols; the regex doesn't drop, just under-canonicalizes.
- **Proposed fix:** Document the ASCII-only assumption in the docstring of `tokenize_latex`, and add a regression test that asserts `tokenize_latex("α + β")` returns `['α', '+', 'β']` (proving unicode round-trips even if it doesn't canonicalize to `\alpha`/`\beta`).

### F11 — `kpsewhich` / texlive-bin not detected; pdflatex-present-but-broken misclassified

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/eval/test_parser_fidelity.py:339-344`
- **What:** `_pdflatex_available()` checks only `pdflatex` and `pdftoppm` on PATH. On thin Debian/Ubuntu installs (`apt install texlive-base` without `texlive-binaries`), `pdflatex` can be present but `kpsewhich` (font-search helper) absent — pdflatex then fails with `! I can't find file ...` at run time. The test marker enables, the subprocess fires, and the test fails (rather than skipping cleanly). The intent of `requires_pdflatex` is "skip cleanly on broken env"; a more thorough check would call `pdflatex --version` once at module load and skip if it exits nonzero.
- **Why it matters:** The cold-start behavior of "skip cleanly when binaries missing" breaks subtly when binaries are present-but-non-functional. Developer-experience issue; low because the test failure surfaces a useful error (`pdflatex failed (exit 1). Last 500 chars: ! I can't find file 'cmr10.tfm'`), just not as a skip.
- **Proposed fix:** Extend `_pdflatex_available()` to also check `shutil.which("kpsewhich") is not None`. Optionally, call `subprocess.run(["pdflatex", "--version"], timeout=5, capture_output=True)` once during pytest_configure and cache the result. Skip if either check fails.

## What was done well

- Subprocess discipline (`start_new_session=True` + `os.killpg` + `--no-shell-escape` + `--interaction=nonstopmode` + 30s timeout) is **structurally correct** and consciously mirrors the LaTeXML precedent in `tools/arxiv_fetch.py::parse_with_latexml`. The pattern lift is documented in the sandbox doc with explicit cross-references.
- Choice to ship NumPy + scipy (no OpenCV) is **the right call**: the design note from research-synthesis §D1 about the KMP_DUPLICATE_LIB_OK landmine is real and would have bitten on macOS. The detect_bbox implementation via `np.where + .all(axis=2)` is the elegant minimal version.
- Color-grid generation skips pure black to avoid aliasing with default ink — a small detail that would have caused mysterious zero-bbox failures on the first token of every formula if missed.
- The `requires_pdflatex` marker registration is the FIRST commit of the milestone (per research-synthesis §D4), so the marker is known to pytest before any test references it. This avoids the unknown-marker warning trap.
- Test coverage spans 3 explicit tiers (pure-Python → fixture-validation → end-to-end gated), with each tier's invariant tested independently. The Tier-1 grid-capacity boundary test (`test_grid_capacity_boundary` at 4913) is exactly the kind of edge-case test that catches off-by-one drift.
- The fixture's per-page contract (`NN-formula.tex` + `NN-formula.mathml`) is enforced by structural tests (`test_every_tex_has_mathml`, `test_every_mathml_has_tex`, `test_mathml_files_are_well_formed_xml`) — operator slips during hand-curation surface immediately.
- The cold-start matrix is explicitly documented in TIER-GATES.md with three clear states (empty / partial / complete), and the in-test behavior of `test_tier1_promotion_gate_status` honors that matrix correctly via `pytest.skip()` with a descriptive reason.
- The 5 explicit deviations from the brief are honestly documented in the implementation summary (including the 4913 vs 5832 color-grid discrepancy and the dataclass-return vs bare-float shape change), which makes adversary verification much faster.
- The Threat-3 peer sandbox doc explicitly enumerates what is NOT done (sandbox-exec, seccomp/landlock, UID drop) with un-park triggers — a pattern this project values for honest scope-fencing.
- No banned imports (no `cv2`, no `anthropic`, no `assert` for invariants — verified by grep across the diff).
- The README's "Parser fidelity evaluation" subsection lands under the existing Operations heading rather than introducing a new top-level section, respecting the doc-layout discipline.

## Recommended rectification order

1. **F1** (HIGH, ordering-cost bug) — fix first; it's a 3-line code change but invalidates every CDM score the harness has ever produced. Without it, the gate's calibration is wrong, so F8's defensibility discussion is moot until the math is right.
2. **F2** (HIGH, sandbox doc + env-var mitigation) — the doc rewrite is fast; the `env={...}` plumbing in `render_latex_to_image` is 5 lines. Land both together because the doc references the impl.
3. **F6** (MEDIUM, deadlock-on-drain) — match the LaTeXML precedent; mechanical change, inherits precedent's test coverage.
4. **F5** (MEDIUM, `-halt-on-error`) — single argv addition, immediate gain.
5. **F3** (MEDIUM, aggregate failures observability) — small dataclass + test. Keep the failure-as-zero behavior; just add the failure count to the return.
6. **F4** (MEDIUM, fixture MathML provenance) — pick one (LaTeXML or hand-typed), regenerate or label, update README. ~20 minutes.
7. **F8** (MEDIUM, README rubric labeling) — pure docs.
8. **F7** (MEDIUM, late-bound skipif) — string-condition refactor, 3 skipif decorators.
9. **F9** (LOW, dead-code branch) — delete and re-pin.
10. **F10** (LOW, unicode regex) — add docstring + one test.
11. **F11** (LOW, kpsewhich check) — defer; record under `deferred_findings` unless cheap.

## Rectification status (filled by Phase 4)

- **F1** (HIGH, ordering-cost bug) — **CLOSED.** `_cost_matrix` now
  captures `pred_raw_n` / `gt_raw_n` before the visible-token filter
  and uses raw counts as `lo` denominators. Two regression tests in
  `TestCostMatrixOrderingNormalization` exercise the
  `\frac{a}{b}`-style and 11-raw/1-visible cases pre-fix would have
  failed.
- **F2** (HIGH, sandbox doc + env-var mitigation) — **CLOSED.**
  Rewrote `.claude/docs/security-cdm-sandbox.md` threat-surface
  table to separate `\write18` / `\openout` / `\input` mitigations
  and call out the false claims explicitly in the rectification
  note. `tools/cdm_eval.py::render_latex_to_image` now passes
  `env={"openin_any":"p", "openout_any":"p", "shell_escape":"f", ...}`
  to both pdflatex and pdftoppm subprocesses. The implementation
  snippet in the sandbox doc was updated in lockstep.
- **F3** (MEDIUM, aggregate failures observability) — **CLOSED.**
  New `AggregateResult` dataclass with `mean` / `scores` / `failures`
  fields. `aggregate_cdm` records `(pair_index, exception_msg)` for
  every substituted-zero entry. Two regression tests in
  `TestAggregateFailuresObservability` cover the failure-as-zero
  path AND the all-clean path.
- **F4** (MEDIUM, fixture MathML provenance) — **CLOSED.** README
  and `manifest.json` now state the v0 fixture uses hand-typed
  sparse MathML (≤ 50 lines, no LaTeXML markers). README §
  Regenerating documents the shape-switch protocol. New
  `TestFixtureShape` Tier-2 test enforces shape consistency across
  all MathML files AND pins the v0 hand-typed-sparse contract on
  the 2 example pages — drifts surface immediately on the next
  `make test`.
- **F5** (MEDIUM, `-halt-on-error`) — **CLOSED.** Added to the
  pdflatex argv. Documented in the sandbox-doc subprocess snippet.
- **F6** (MEDIUM, deadlock-on-drain) — **CLOSED.**
  `_run_subprocess_with_pgkill` now uses the LaTeXML precedent's
  pattern: `contextlib.suppress(ProcessLookupError, OSError)` around
  `os.killpg` and `proc.communicate(timeout=5)` instead of
  `proc.wait()`. The `logger.warning` swallow is dropped per
  precedent.
- **F7** (MEDIUM, late-bound skipif) — **CLOSED.** Three `@pytest.mark.skipif`
  decorators converted to the string-condition form so pytest
  evaluates at test-run time. The `_pdflatex_available` helper is
  removed; a comment in the test file documents why.
- **F8** (MEDIUM, README rubric labeling) — **CLOSED.** README
  table prefaces with "**arXMCP-chosen**" and the closing paragraph
  explicitly says neither the CDM paper nor OmniDocBench defines
  the 0.70 / 0.95 boundaries.
- **F9** (LOW, dead-code branch) — **CLOSED.** Removed the
  unreachable `elif tp == 0: score = 1.0` branch; the
  `if tp == 0: score = 0.0 else: ...` simplified to a ternary
  expression per ruff SIM108.
- **F10** (LOW, unicode regex) — **CLOSED.** Added unicode caveat
  paragraph to `tokenize_latex` docstring + new `TestUnicodeTokenization`
  test class covering the literal-α-vs-`\alpha` asymmetry.
- **F11** (LOW, kpsewhich check) — **DEFERRED.** Not addressed in
  this rectification pass. Tracked as a known footgun in the
  `_pdflatex_available`-removal comment block (the lazy skipif still
  only checks `pdflatex` + `pdftoppm` presence; the kpsewhich gap
  surfaces as a real-run failure rather than a clean skip). Re-park
  if it bites during the parser-bake-off milestone.

**Test count delta from rectification:** +9 (2702 → 2711). The new
tests are: 2 in `TestCostMatrixOrderingNormalization`, 2 in
`TestAggregateFailuresObservability`, 3 in
`TestUnicodeTokenization`, 2 in `TestFixtureShape`. All pass under
`make test`. Pre-existing `test_cite_neighbors_wired` failure
(HF Hub network) remains unrelated.

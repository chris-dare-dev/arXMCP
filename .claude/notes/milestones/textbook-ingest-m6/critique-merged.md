# Critique — textbook-ingest-m6

**Critic:** adversary
**Generated:** 2026-05-27T00:00:00Z
**Commit range:** ea8eb8d..191ddd8
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the e2-closure pipeline is sound and well-tested at the unit
  layer, but two real correctness/security gaps and one test-surface hole need
  rectification before the path is trustworthy.
- Finding counts: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 1 LOW.
- Highest-risk: `server/parse_tracker.py:235` stores the absolute repo path into
  `parsed_html_path`, which leaks the operator's home dir via `/parse-status`
  JSON — the m9 `redact_paths` precedent exists precisely to prevent this.
- Math-fidelity: `ingest/textbook_renderer.py:78` wraps MinerU markdown with zero
  sanitization, so a literal `\end{document}` in the PDF text silently truncates
  the rendered document (content loss) — load-bearing per axis 2.
- Test surface: NO test exercises the upload→schedule path; the `client` fixture
  never sets `app.state.parse_tracker`, so the route's parse-dispatch branch
  (`server/routes/notebooks.py:941-982`) ships entirely uncovered.
- Cross-axis: the documented `has_running_parse` 409 fallback is implemented +
  tested at the store layer but never wired into the route — dead code plus a
  TOCTOU window on concurrent same-slug uploads.
- Clean axes: cache byte-stability (no `ALL_TOOLS`/tool-schema touch), MCP spec
  (N/A), local-first (in-process asyncio, no network), no-fork (all original),
  tier-sequencing (consumes only m5 + existing latexmlc), sandbox inheritance
  (latexmlc genuinely inherits E13_S03 via `parse_with_latexml`).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — Absolute repo path leaked into /parse-status JSON

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/parse_tracker.py:235
- **What:** The success path stores `html_path_str = str(render_result.output_html_path)`
  verbatim. `output_html_path` derives from `notebook_dir(slug)` →
  `NOTEBOOKS_BASE` = `REPO_ROOT/var/arxmcp/notebooks/...` where
  `REPO_ROOT = Path(__file__).resolve().parent.parent`
  (`tools/_notebook_common.py:30,33`), i.e. an absolute path like
  `/Users/chris.dare/.../var/arxmcp/notebooks/<slug>/parsed/<flat>/index.html`.
  This value is returned unredacted in the `/parse-status` JSON
  (`server/routes/notebooks.py:1245`).
- **Why it matters:** Violates the m9 path-redaction discipline. m9 introduced
  `redact_paths` in `server/ingest_tracker.py:81` specifically to scrub the
  absolute prefix down to `var/arxmcp/` before storing operator-visible strings
  (note 08 — leak of host filesystem layout / username). The parse path
  regresses that. The code comment at `server/parse_tracker.py:231-234` even
  claims it records the path "relative to repo root if possible … or absolute
  otherwise" — but the code does NEITHER relativization step; the comment is
  aspirational and contradicts the implementation.
- **Proposed fix:** In `_run_parse`, redact before storing — mirror m9: compute
  the path relative to the repo root (or scrub the prefix to `var/arxmcp/`) and
  store that. e.g. `html_path_str = _redact_to_var_arxmcp(render_result.output_html_path)`
  reusing the same regex contract as `server/ingest_tracker.py:redact_paths`.
- **Regression guard:** Add a test asserting that after a successful parse the
  stored `parsed_html_path` (read back via `get_notebook` / `/parse-status`)
  does NOT contain `/Users/` or the absolute `REPO_ROOT` prefix and DOES start
  with `var/arxmcp/`.

### F2 — Upload→schedule path is completely untested

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/routes/notebooks.py:941
- **What:** No test in `tests/test_notebook_api.py` POSTs to
  `/notebooks/{slug}/papers/upload` for a textbook notebook to exercise the
  parse-dispatch block (lines 941-982). The `client` fixture
  (`tests/test_notebook_api.py:55-87`) never sets `app.state.parse_tracker`, so
  even an upload test would silently fall into the `parse_tracker is None`
  warning branch (line 943-952) — the `update_parse_status('running')` +
  `start_parse(...)` transition (lines 964-977) has zero coverage. The tracker is
  unit-tested in isolation (`tests/test_parse_tracker.py`) but the route's
  invocation of it — argument wiring (`output_dir`, `parsed_dir`, `paper_id`),
  the `is_running` collision branch, and the pending→running transition — is not.
- **Why it matters:** The common-path wiring (upload a textbook PDF → parse gets
  scheduled → status flips to `running`) is the entire point of m6 and is
  unverified. A regression in argument names or the None-guard would pass CI.
- **Proposed fix:** Add a `TestTextbookUploadSchedulesParse` class: build a
  client whose app has a stub/mock `parse_tracker` on `app.state`; POST a
  minimal `%PDF-` body to the upload route for a textbook notebook; assert
  `start_parse` was called once with the expected kwargs and that
  `/parse-status` reports `running`. Add a second test for the
  `parse_tracker is None` branch asserting 201 + PDF on disk + status stays
  `pending` (this branch is also currently untested).
- **Regression guard:** The new test class above is itself the guard; it would
  fail on the pre-fix code if the dispatch branch were broken.

### F3 — \end{document} in MinerU markdown truncates rendered document (content loss)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:78
- **What:** `_build_latex_wrapper` does `_LATEX_ENVELOPE.replace("{body}", markdown_content)`
  with NO sanitization of the markdown body. The envelope hard-codes a closing
  `\end{document}` (line 51). If MinerU's extracted markdown contains a literal
  `\end{document}` mid-content — entirely plausible for a math/CS/LaTeX textbook
  that quotes LaTeX source, or a verbatim listing — LaTeXML treats the FIRST
  `\end{document}` as the document terminator and silently DROPS every equation
  and section after it. The same applies to an embedded `\documentclass` or
  `\begin{document}`.
- **Why it matters:** Axis 2 (math fidelity) is load-bearing (notes 01, 04). This
  is silent content loss — the parse "succeeds" (index.html is produced), the
  error-annotation count may be zero, but downstream chunking (e3) never sees the
  truncated tail. There is no detection: the renderer's only completeness check
  is "index.html exists" (line 173).
- **Proposed fix:** Either (a) neutralize the structural commands in the body
  before wrapping — e.g. reject/escape bare `\end{document}`, `\begin{document}`,
  `\documentclass` occurrences, or (b) detect them and emit a HIGH-visibility
  WARN + a `latex_error_annotations`-style quality counter so the operator knows
  the doc was truncated. Option (a) is safer: replace `\end{document}` in the
  body with a benign escaped form before the wrap.
- **Regression guard:** Add a renderer test: a markdown body containing
  `before $x$\n\\end{document}\nAFTER $y$` must NOT drop the `AFTER` content
  (assert `AFTER` survives into the .tex passed to `parse_with_latexml`, or that
  the renderer raises/warns).

### F4 — TOCTOU on concurrent same-slug uploads; documented DB fallback never wired

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/routes/notebooks.py:953
- **What:** The 409-collision guard for a second parse is `parse_tracker.is_running(slug)`
  (line 953) ONLY. There is an `await store.update_parse_status(...)` (line 964)
  between that check and `start_parse` (line 970). Two concurrent uploads for the
  same slug can both observe `is_running == False` (the first task is not created
  until line 970), then both call `start_parse`, and
  `ParseTaskTracker.start_parse` does `self._tasks[slug] = task` unconditionally
  (`server/parse_tracker.py:135`), overwriting/orphaning the first task's
  reference — a double MinerU parse plus a lost-task GC risk. Separately, the
  store's `has_running_parse` (`server/notebooks_store.py:629`) is implemented and
  tested, and `parse_tracker`'s own docstring (line 95) says it is "paired with
  `has_running_parse` as a cross-restart fallback in the handler" — but the route
  NEVER calls it. It is dead code; the documented cross-restart 409 fallback does
  not exist.
- **Why it matters:** The ingest route (its sibling, line 1098) checks BOTH
  `is_running` AND `await store.has_running_ingest(slug)`; the parse route
  dropped the DB layer. Loopback single-user deployment makes this narrow, but
  the asymmetry is a real foot-gun and the dead method is misleading.
- **Proposed fix:** Add `or await store.has_running_parse(slug)` to the collision
  check, mirroring `trigger_ingest`. Optionally collapse the check-then-schedule
  into a smaller critical section, but the DB guard is the load-bearing fix.
- **Regression guard:** Add a test that flips a notebook's `parse_status` to
  `running` in the store (no live task), POSTs an upload, and asserts the route
  refuses to schedule a second parse (relies on `has_running_parse`).

### F5 — copytree of MinerU images follows symlinks out of the notebook tree

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:170
- **What:** `shutil.copytree(mineru_images, dest_images)` is called with the
  default `symlinks=False`, which FOLLOWS symlinks and copies their target
  content. `mineru_images = result.output_dir/<pdf_stem>/auto/images` is
  attacker-influenced output (MinerU runs on an uploaded PDF). A symlink emitted
  there (e.g. `images/x -> /etc/passwd`) would copy external file content into
  the notebook's `parsed/<flat>/images/` tree.
- **Why it matters:** Defense-in-depth gap on the PDF trust boundary (note 08).
  MinerU's sandbox makes emitting such a symlink non-trivial, hence MEDIUM not
  HIGH, but the copy step itself imposes no containment.
- **Proposed fix:** Pass `symlinks=True` to preserve (not dereference) symlinks,
  OR walk the tree rejecting any entry whose resolved path escapes
  `mineru_images`, mirroring the `notebook_dir` symlink-rejection discipline
  (`tools/_notebook_common.py:104-114`).
- **Regression guard:** Add a renderer test that plants a symlink under the
  MinerU images dir pointing outside the tree and asserts the dest does not
  contain dereferenced external content (or that the copy refuses it).

### F6 — latex_error_annotations regex is brittle to LaTeXML class-string variants

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:185
- **What:** The quality metric uses `re.findall(r'class="ltx_ERROR"', html_text)`
  — an exact double-quoted, single-class string match. LaTeXML routinely emits
  multi-class attributes (e.g. `class="ltx_ERROR ltx_font_bold"`) and can apply
  the error class to a `<span>` rather than `<math>` (the docstring at line 61
  and 188 asserts `<math class="ltx_ERROR">`, which over-narrows the actual
  convention). Any of these variants makes the count silently read 0, defeating
  the "did equations degrade?" quality signal.
- **Why it matters:** Not a correctness bug for the rendered document, but the
  count is the ONLY automated quality signal m6 ships for math degradation; a
  false zero hides FM-1/FM-2 from the operator and downstream CDM eval.
- **Proposed fix:** Match the class token more robustly, e.g.
  `re.findall(r'class="[^"]*\bltx_ERROR\b[^"]*"', html_text)` (and tolerate
  single quotes if LaTeXML emits them). Update the docstrings to stop claiming
  the class only appears on `<math>`.
- **Regression guard:** Add a renderer test feeding stub HTML with
  `class="ltx_ERROR ltx_font_bold"` on a `<span>` and assert the count is 1.

### F7 — Renderer test count in implementation-summary is inaccurate

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/milestones/textbook-ingest-m6/implementation-summary.md:47
- **What:** The summary states `tests/test_textbook_renderer.py` is "14 tests,
  13 always-run + 1 requires_latexmlc". Counting the file: 3 + 4 (parametrized)
  + 1 + 7 always-run + 1 gated ≈ 16. Minor bookkeeping drift; the gated test
  count (1) is correct.
- **Why it matters:** Cosmetic — does not affect shipped behavior. Recorded for
  accuracy only.
- **Proposed fix:** Correct the count in the summary, or drop the precise number.
- **Regression guard:** None required (LOW / doc-only).

## What was done well

- latexmlc genuinely inherits the E13_S03 sandbox + process-group-kill discipline
  by delegating to `tools/arxiv_fetch.py::parse_with_latexml` rather than
  re-spawning — exactly the anti-duplication the security doc demands.
- The v3→v4 migration is correctly additive (ALTER TABLE … ADD COLUMN with
  column-level DEFAULTs), guarded by `if current_version < 4`, and the legacy
  v1→v4 path is exercised end-to-end by `TestNotebookKindMigration`
  (`tests/test_notebook_api.py:992`) including the m6-column backfill assertions.
- The orphan-recovery ordering is correct: `mark_orphaned_parses_failed` runs at
  `server/main.py:373` BEFORE `app.state.parse_tracker` is attached (line 389),
  so the unconditional `WHERE parse_status='running'` sweep cannot clobber a live
  parse — the implementer reasoned about this explicitly and the reasoning holds.
- No MCP tool-surface change: `ALL_TOOLS` and `EXPECTED_TOOL_SCHEMA_SHA256` are
  untouched, so BP1 cache byte-stability is preserved (axis 1 clean).
- `_format_parse_error` correctly truncates-then-escapes and is well-tested,
  including the multi-byte UTF-8 boundary case (`test_byte_boundary_safe`).
- `parse_status` semantics are clean: arxiv-kind backfills to `skipped`,
  textbook-kind gets the explicit `pending` route override, with both paths
  tested (`TestParseStatusInitialState`).
- All route handlers (`parse_status`, `upload_paper`, create/delete) call
  `validate_slug` at the boundary before any DB/FS access — path-traversal
  discipline preserved from m4/m6.
- The cancel-path (`_run_parse`'s `asyncio.CancelledError` handler) writes a
  terminal `failed` row before re-raising, matching the m9 FM-7 closure pattern,
  and the failure paths are tested.
- In-process `asyncio.to_thread` choice over a Python subprocess is well-justified
  (MinerU + LaTeXML already subprocess-isolate) — no networked dependency
  introduced; local-first constraint intact.

## Recommended rectification order

1. F1 (HIGH, security) — small, localized redaction fix in `_run_parse`; reuse
   the m9 `redact_paths` contract. Do first; it is self-contained.
2. F2 (HIGH, test) — add upload→schedule coverage; this will also surface F4's
   wiring gap as you build the fixture with a real `parse_tracker`.
3. F4 (MEDIUM) — add the `has_running_parse` DB guard to the upload route while
   the F2 fixture is fresh; the two share test infrastructure.
4. F3 (MEDIUM, math fidelity) — sanitize/detect structural-command injection in
   the LaTeX wrapper; standalone change in `textbook_renderer.py`.
5. F5 (MEDIUM) — `symlinks=True` (or containment walk) on the copytree; one-line
   plus a guard test.
6. F6 (MEDIUM) — broaden the `ltx_ERROR` regex and fix the docstrings.
7. F7 (LOW) — correct the summary test count if touching the doc anyway; else
   defer.

## Rectification status

- F1 (HIGH) — FIXED in `server/parse_tracker.py`: added `redact_html_path` + `_redact_path_prefix` (str-domain peer of m9's `redact_paths`); `_run_parse` now stores the `var/arxmcp/`-relative path, and `_format_parse_error` redacts absolute prefixes before escaping. Regression: `tests/test_parse_tracker.py::TestRedactHtmlPath` (4 cases) + `TestFormatParseError::test_redacts_absolute_path_in_message`.
- F2 (HIGH) — FIXED: `tests/test_notebook_api.py::TestTextbookUploadSchedulesParse` (3 tests) builds a client with a mock `parse_tracker` on `app.state` and exercises the upload→schedule path: asserts `start_parse` called with correct kwargs + `parse_status` flips to `running`; covers the `parse_tracker is None` degraded branch; covers the F4 `has_running_parse` refusal.
- F3 (MEDIUM) — FIXED in `ingest/textbook_renderer.py`: `_build_latex_wrapper` neutralizes `\end{document}` / `\begin{document}` / `\documentclass` in the body so a structural command mid-content cannot truncate the rendered document. Regression: `TestBuildLatexWrapper` (3 neutralization tests + "plain math untouched").
- F4 (MEDIUM) — FIXED in `server/routes/notebooks.py:953`: collision check now `is_running(slug) or await store.has_running_parse(slug)`, mirroring `trigger_ingest`, wiring the previously-dead `has_running_parse` and closing the TOCTOU window. Regression: `test_has_running_parse_refuses_second_schedule`.
- F5 (MEDIUM) — FIXED in `ingest/textbook_renderer.py:170`: `shutil.copytree(..., symlinks=True)` preserves (not dereferences) symlinks in MinerU's images/. Regression: `test_symlink_in_images_not_dereferenced`.
- F6 (MEDIUM) — FIXED in `ingest/textbook_renderer.py:185`: `latex_error_annotations` regex broadened to `class=["'][^"']*\bltx_ERROR\b[^"']*["']` (multi-class / single-quote / span-or-math tolerant). Regression: `test_multi_class_ltx_error_counted`.
- F7 (LOW) — FIXED: corrected the renderer test-count claim in `implementation-summary.md`.

**Invalidation rate:** 0% (all 7 findings matched the cited file:line on re-verify).

**External writes:** none required (synthesis declared zero; confirmed at the Phase-4 boundary).

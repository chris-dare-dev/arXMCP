# Critique — textbook-render-robustness-m1

**Critic:** adversary
**Generated:** 2026-06-09T02:59:23Z
**Commit range:** ba0d6e4584fc9bb53793389663d6e1dc1f1ee2bb..75dcd1982860132a7e07b9b49c915870b9ed5087
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the timeout change is clean and the orphaned-`\end{array}`
  path (the confirmed 1404.3143 failure) works; but the `_sanitize_math_balance`
  unclosed-open and residue branches can trade one LaTeXML-fatal error for
  another, and a `\end{array}` in a heading title is silently deleted.
- Counts: 0 CRITICAL, 0 HIGH, 5 MEDIUM, 2 LOW.
- Highest-risk: `ingest/textbook_renderer.py:155` (append `\n\end{array}`
  lands in text mode outside `$$` → re-introduces "close boxing group").
- A shipped docstring (`tools/arxiv_fetch.py:65`) asserts the server scan
  "does not FATAL" on the var — it DOES still raise `ValueError`. The impl
  summary's own Deviations note contradicts this docstring.
- Math-fidelity axis is the load-bearing one and is where every substantive
  finding clusters; the timeout/server/test-wiring axes are largely clean.
- Killpg / `start_new_session` Threat-3 control flow is byte-unchanged
  (`tools/arxiv_fetch.py:638-661`); only the caller-supplied timeout VALUE moved.
- Zero NEW real test failures: the 3 local failures are the documented
  Windows symlink + SQLite-operator-settings pre-existing set.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Appended `\end{array}` lands in text mode → re-creates the fatal error

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:155 (the `result += "\n\\end{array}" * depth` branch)
- **What:** For an unclosed `\begin{array}` whose enclosing `$$` block already
  closed, the depth-counter appends `\n\end{array}` at the END of the whole
  body — outside any math mode. Verified live: input
  `$$\begin{array}{c} a \\ b $$\ntrailing prose` →
  `...trailing prose\n\end{array}`. The closer now sits in TEXT mode.
- **Why it matters:** `\end{array}` in text mode is itself the
  `\@end@array Attempt to close boxing group` error this sanitizer exists to
  prevent. For the unclosed-open case the sanitizer can trade the original
  fatal error for a new one at a different location, defeating the
  "non-empty doc beats 0 chunks" goal. The confirmed failure (1404.3143)
  was orphaned-CLOSERS, which this handles correctly — but the symmetric
  open branch is exercised by `test_unclosed_begin_array_gets_closed` and
  shipped as if safe.
- **Proposed fix:** Track whether the unclosed `\begin{array}` is inside an
  open `$$`/`$` math region; if so, append the closer BEFORE the math
  delimiter closes (or, conservatively, DROP the orphaned `\begin{array}`
  opener instead of appending a closer — symmetric to the orphaned-closer
  drop, and guaranteed not to introduce a text-mode `\end{array}`). Dropping
  the opener is the lower-risk transform and keeps the function's
  "only remove provably-unbalanced tokens" discipline.
- **Regression guard:** Add a test asserting that for
  `$$\begin{array}{c} a \\ b $$\ntrailing prose` the output contains NO
  `\end{array}` after the final `$$` (i.e. no text-mode closer), OR that the
  opener was dropped.

### F2 — Orphaned-`\end{array}` drop leaves dangling `&` / `\\` alignment residue

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:144-148 (the orphaned-closer drop branch)
- **What:** Dropping the closer removes only the `\end{array}` token, leaving
  any alignment tabs (`&`) and row separators (`\\`) that belonged to the
  array body inside the surrounding `$$`. Verified live:
  `$$ a & b \\ c & d \end{array} $$` → `$$ a & b \\ c & d  $$`.
- **Why it matters:** A bare `&` in plain `$...$`/`$$...$$` math (no alignment
  environment) is a LaTeXML "Misplaced alignment tab character &" error. The
  drop can leave a body that still errors — again undercutting the degraded-
  but-renders goal. Lower impact than F1 (LaTeXML error-recovers `&` per-cell
  more gracefully than an unbalanced boxing group), hence MEDIUM not HIGH.
- **Proposed fix:** Acceptable to defer if the rectifier judges LaTeXML's
  `&` error-recovery sufficient — but at minimum add a test on a realistic
  multi-cell orphaned body so the residue behavior is PINNED rather than
  unobserved, and document the residue limitation in the docstring.
- **Regression guard:** Test `$$ a & b \\ c & d \end{array} $$` and assert the
  documented post-condition (whatever the rectifier decides — drop residue or
  accept it), so the behavior is locked.

### F3 — `\end{array}` inside a heading title is silently deleted

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:281 (sanitize is STEP 0, before heading conversion)
- **What:** `_sanitize_math_balance` runs on RAW markdown before
  `_convert_markdown_headings_to_latex`. An orphaned `\end{array}` token
  anywhere — including inside a heading title — is dropped. Verified live:
  `## The \end{array} trick` → `## The  trick`, then heading conversion
  emits `\subsection{The  trick}`.
- **Why it matters:** A math/CS textbook section titled e.g. "The array
  environment" or prose discussing `\end{array}` loses the literal text
  silently. This is content corruption of NON-math prose — the function's
  docstring promises "well-formed math is never corrupted" but says nothing
  about prose tokens that merely look like `\end{array}`. The
  `test_array_balance_composes_with_headings` test puts the orphaned token in
  a SEPARATE `$$` block, not in a heading title, so this case is uncovered.
- **Proposed fix:** This is the inherent cost of running a global token
  counter on raw markdown. Cheapest honest mitigation: document the
  limitation in the docstring ("operates on the whole document including
  prose; a literal `\end{array}` in prose/headings is treated as a math
  token"). A fuller fix would skip heading lines / verbatim during the count,
  but that is more than 30 LOC — defer the structural fix, fix the docstring.
- **Regression guard:** Add a test pinning the current behavior for
  `## The \end{array} trick` so the corruption is at least a KNOWN,
  asserted-on behavior rather than a silent surprise.

### F4 — Docstring claims server scan "does not FATAL"; it still raises ValueError

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:65 (`_parse_latexml_timeout_from_env` docstring: "does not FATAL when an operator leaves it set")
- **What:** The docstring states the `_KNOWN_INGEST_ENV_VARS` registration
  means the server's unknown-`ARXMCP_*` scan "does not FATAL". But
  `server/main.py:404` unconditionally `raise ValueError(...)` for ANY
  unknown var; the carve-out (`server/main.py:298-305`) only changes the
  HINT TEXT, not whether the scan fatals. The var is still rejected.
- **Why it matters:** "comment says X, code does Y" — an operator reading this
  docstring would expect `ARXMCP_LATEXML_TIMEOUT_S` to be tolerated by the
  server and be surprised by a FATAL startup. The implementation summary's
  own "Deviations" section correctly notes the server STILL rejects it — so
  the author knew the brief's wording was wrong yet reproduced it verbatim in
  the shipped docstring.
- **Proposed fix:** Reword `tools/arxiv_fetch.py:60-66` to match reality:
  "...registered in `_KNOWN_INGEST_ENV_VARS` so the scan emits a TAILORED
  hint (name the CLI path; tell the operator to unset it for the server) —
  the server still rejects it by design, matching `ARXMCP_CONTACT_EMAIL`."
- **Regression guard:** N/A (doc fix); but see F5 for the missing behavioral test.

### F5 — No test asserts the server rejects `ARXMCP_LATEXML_TIMEOUT_S` with its hint

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_server_startup.py:357 (`test_contact_email_env_var_rejected` exists; no peer for the new var)
- **What:** `_KNOWN_INGEST_ENV_VARS` gained a new entry
  (`server/main.py:298`) and `_format_unknown_arxmcp_env_var` will now route
  `ARXMCP_LATEXML_TIMEOUT_S` through the ingest carve-out branch. There is a
  test for the `ARXMCP_CONTACT_EMAIL` carve-out but NONE asserting the new
  var raises `ValueError` and that the message names the LaTeXML CLI path.
- **Why it matters:** The new carve-out branch (the server-side half of this
  milestone) ships with zero coverage. A future refactor of the hint table or
  the scan could silently drop/garble the new var's tailored message and no
  test would catch it. Per Axis-8 (every new code path covered).
- **Proposed fix:** Add `test_latexml_timeout_env_var_rejected` mirroring
  `test_contact_email_env_var_rejected`: set the var, build the app, assert
  `pytest.raises(ValueError, match="ARXMCP_LATEXML_TIMEOUT_S")` and assert the
  message mentions "LaTeXML" / "render".
- **Regression guard:** That test IS the guard.

### F6 — `_neutralize_structural_commands` remains dead code; sanitizer adds no parallel observability counter

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:94 (`_neutralize_structural_commands` — "has no production caller")
- **What:** Pre-existing dead helper (self-documented as having no production
  caller). The new sanitizer follows the same shape but does not emit any
  count of how many array tokens it dropped/appended, so an operator gets no
  signal that a render was silently mutated.
- **Why it matters:** Purely observability/maintenance; not a correctness bug.
  Worth noting since a "how many arrays did we mutate" counter would make
  F1/F2/F3 mutations visible to the operator instead of silent.
- **Proposed fix:** Optional — have `_sanitize_math_balance` log at DEBUG the
  count of dropped closers / appended closers when nonzero. Defer.
- **Regression guard:** N/A (LOW).

### F7 — Array regex would match `\begin{array}` inside verbatim/inline-code

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:113 (`_ARRAY_ENV_RE`)
- **What:** `_ARRAY_ENV_RE` matches `\begin{array}`/`\end{array}` anywhere,
  including inside a fenced code block or inline `` `...` `` where the token is
  literal text, not a real environment. MinerU markdown rarely emits verbatim
  LaTeX, so the practical exposure is low.
- **Why it matters:** Same class as F3 (global token scan ignores context).
  Low because MinerU output is OCR'd prose+math, not source listings, so a
  literal `\begin{array}` in a code fence is improbable on the real ingest
  path.
- **Proposed fix:** Defer; note the limitation alongside the F3 docstring
  amendment ("treats every `\begin{array}`/`\end{array}` as a real
  environment regardless of code-fence context").
- **Regression guard:** N/A (LOW).

## What was done well

- The killpg / `start_new_session=True` Threat-3 control flow
  (`tools/arxiv_fetch.py:629-661`) is byte-identical; only the caller-supplied
  `timeout` VALUE changed, so the E13_S03 security posture is intact and the
  `TestProcessGroupKill` AST test still applies unmodified.
- `_parse_latexml_timeout_from_env` mirrors the established
  `textbook_parser._parse_timeout_from_env` pattern exactly: validate-at-load,
  RuntimeError (not silent clamp) on non-int / out-of-range, empty→default.
- Module-load read uses a distinct constant name (`_CONFIGURED_LATEXML_TIMEOUT_S`,
  float) in a different module from the MinerU `_CONFIGURED_TIMEOUT_S` (int) —
  no collision, no test cross-contamination.
- The timeout-config tests call the FUNCTION (`_parse_latexml_timeout_from_env()`)
  rather than reading the frozen module constant, so they correctly exercise
  env parsing without import-order fragility.
- The threading test asserts the timeout reaches `parse_with_latexml`'s call
  kwargs (`tests/test_textbook_renderer.py:297`), and the value flows on to
  `proc.communicate(timeout=timeout)` — so the kwarg is genuinely FORWARDED to
  subprocess, not merely accepted in the signature.
- Orphaned-`\end{array}` drop (the actually-confirmed 1404.3143 failure mode)
  is correct and well-tested, including the heading-composition case.
- Nested/balanced array preservation is correct (net-zero depth → byte-for-byte
  untouched) and is explicitly tested.
- No new dependency (stdlib `re`/`os` only); no tool-schema / MCP surface /
  `tools/list` hash touched — cache byte-stability and MCP compliance axes are
  clean.
- No-fork policy clean: no submodule, no fork pin, no lifted-code header
  comments in the diff.
- Existing `fake_parse` surface mocks were correctly updated to accept the new
  `timeout` kwarg, so no test silently broke on the signature change.

## Recommended rectification order

1. F1 — highest blast radius: change the unclosed-open branch to DROP the
   orphaned opener (symmetric, guaranteed safe) instead of appending a
   text-mode `\end{array}`. Add the regression guard.
2. F4 — reword the `tools/arxiv_fetch.py` docstring to stop claiming the
   server "does not FATAL"; cheap, removes an operator-facing lie.
3. F5 — add the server-scan rejection test for the new var (mirrors the
   existing CONTACT_EMAIL test; ~15 LOC).
4. F3 — add a heading-title-`\end{array}` pin test + docstring limitation note.
5. F2 — add a multi-cell orphaned-residue test to lock the `&`/`\\` behavior.
6. F6, F7 — defer (LOW); fold the F7 context-limitation note into the F3
   docstring amendment.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

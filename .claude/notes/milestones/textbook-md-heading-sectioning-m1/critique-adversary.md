# Critique — textbook-md-heading-sectioning-m1

**Critic:** adversary
**Generated:** 2026-06-08T00:00:00Z
**Commit range:** 0be33f0a5b03b7a9280b7868a71c7c6382620994..243019fe3860d2b1a7f4b907eeb8200308afdf06
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — the heading conversion is correct on the common path and the
  even/odd parity claim holds, but an UNBALANCED / lone `$` in a heading title is
  the one math-fidelity case the milestone exists to protect and it is mishandled.
- Finding counts: 0 CRITICAL, 1 HIGH, 2 MEDIUM, 2 LOW.
- Highest-risk: `ingest/textbook_renderer.py:120` (`_MATH_SPAN_RE`) — a lone `$`
  with no closer is treated as prose, leaking a raw unescaped `$` into the
  `\section{...}` argument and silently flipping LaTeX into math mode.
- The docstring at `ingest/textbook_renderer.py:119` claims "an unbalanced `$`
  cannot swallow the whole title" — true for the regex, but FALSE for the emitted
  LaTeX: the leaked raw `$` swallows everything downstream until the next `$`.
- Test surface omits every adversarial math edge the research FM-1 named:
  unbalanced `$`, display `$$` IN a heading, and a math-ONLY title. The 8 new
  tests cover the happy path; the dangerous inputs are untested.
- Security carve-out (math spans unescaped) does leave `\input{...}` verbatim
  inside a heading `$...$`, but this is identical to non-heading math and bounded
  by the existing no-shell-escape sandbox — LOW, mechanism noted.
- Parity verified concretely: a title that STARTS or ENDS with a math span yields a
  leading/trailing empty string at an EVEN index (prose), so the carve-out parity is
  correct. No bug there. Axes 1, 4, 5, 6, 7 clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Lone/unbalanced `$` in a heading leaks raw `$` into `\section{}`

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/textbook_renderer.py:120
- **What:** `_MATH_SPAN_RE = r"(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)"` only matches a
  `$...$` span that HAS a closing `$` on the same line. A heading title with a
  lone `$` (e.g. `## Price is $5 today`, or OCR/MinerU dropping one delimiter of a
  pair) produces NO match, so `re.split` returns the whole title as a single prose
  segment. `_escape_heading_prose` escapes `# % & _ { }` and the backslash, but it
  does NOT escape `$`. Confirmed by running the real code:
  `_convert_markdown_headings_to_latex("## Price is $5 today")` →
  `\subsection{Price is $5 today}` — the raw `$` is emitted verbatim.
- **Why it matters:** A bare `$` in LaTeX opens inline math mode. Everything after
  it in the `\section{}` argument (and, depending on balance, content well past the
  heading) is reinterpreted as math by LaTeXML, corrupting the title and any prose
  until the next `$` is encountered — the exact silent-content-corruption class the
  module's structural-command guard (m6 F3) was built to prevent. A document with an
  odd number of leaked `$` flips math-mode parity for the rest of the body. This is
  reachable on a common path: textbook prose routinely contains a lone `$` (prices,
  "the $-operator", a math span MinerU split across a line). It directly contradicts
  the docstring promise at line 119 that an unbalanced `$` "cannot swallow the whole
  title".
- **Proposed fix:** In `_escape_heading_prose` (`ingest/textbook_renderer.py:143-145`),
  add `"$": "\\$"` to `_HEADING_PROSE_ESCAPE` (line 132-140). Because `re.split`
  on `_MATH_SPAN_RE` routes only NON-math segments through `_escape_heading_prose`,
  a `$` that survives into a prose segment is by definition NOT part of a balanced
  span and is safe to escape to `\$`. Balanced `$...$` / `$$...$$` spans are split
  out first and never reach the escaper, so real math is unaffected.
- **Regression guard:** Add `test_unbalanced_dollar_in_heading_escaped` asserting
  `_build_latex_wrapper("## Price is $5 today")` produces `\subsection{Price is \$5 today}`
  and `assert "{Price is $5" not in out` (no raw lone `$` inside the section arg).

### F2 — Trailing prose after an unbalanced `$` is escaped INTO a broken math context

- **Severity:** MEDIUM
- **File:** ingest/textbook_renderer.py:148
- **What:** Subset of F1's mechanism, distinct symptom. For
  `## no closing $x_i here`, the regex finds no span, so the whole string is prose;
  `_escape_heading_title` escapes the `_` → `no closing $x\_i here`. The output now
  contains a raw `$` (math-mode open) immediately followed by `\_` (a literal
  underscore command). Inside LaTeX math mode `\_` is valid but the surrounding text
  `here` is now typeset as math, and the title's intent is destroyed.
- **Why it matters:** Even after F1's `$`→`\$` fix this case becomes correct
  (`no closing \$x\_i here`), so F2 is fully subsumed by F1's fix — but it is called
  out separately because the docstring at line 119 ("non-greedy and newline-bounded so
  an unbalanced `$` cannot swallow the whole title") is making a SAFETY claim that is
  only true at the regex layer, not at the emitted-LaTeX layer. The docstring should
  be corrected in lockstep so a future reader does not re-trust the false guarantee.
- **Proposed fix:** Covered by F1's escape addition; additionally amend the comment at
  `ingest/textbook_renderer.py:118-119` to state that an unbalanced `$` in prose is
  neutralized by escaping it to `\$` (rather than implying the regex alone makes it safe).
- **Regression guard:** Same test as F1 plus an assertion on the
  `no closing $x_i here` variant (raw `$` escaped, `_` escaped).

### F3 — Test surface omits every FM-1 adversarial math edge

- **Severity:** MEDIUM
- **File:** tests/test_textbook_renderer.py:100
- **What:** The 8 new tests (`tests/test_textbook_renderer.py:102-187`) cover
  level-mapping, deep-collapse, math-in-title-not-escaped, prose-escaping,
  closed-ATX, `#hashtag`, structural-cmd-in-heading, and no-headings. None covers:
  (a) an unbalanced / lone `$` in a heading (the F1 bug — would have caught it);
  (b) display `$$...$$` math INSIDE a heading title (only tested in non-heading
  body at line 51); (c) a heading title that is ONLY a math span (`## $x_i$`),
  which exercises the leading+trailing-empty-string parity edge; (d) a title that
  STARTS with a math span then has trailing prose (parity-shift verification).
- **Why it matters:** FM-1 is named in the research as "the top risk" and "the
  highest-risk subtlety". The implementer's own docstring (line 117-120) asserts the
  parity and unbalanced-`$` behavior, but no test pins it. The parity claim happens to
  be correct (verified by this critic: `## $x_i$ leads` → `\subsection{$x_i$ leads}`,
  empties land at even indices), but it is asserted-by-comment, not asserted-by-test —
  a regression in `_MATH_SPAN_RE` or the split logic would ship silently.
- **Proposed fix:** Add `test_math_only_heading_title` (`## $x_i$` →
  `\subsection{$x_i$}`, underscore NOT escaped), `test_display_math_in_heading`
  (`## display $$\sum_i x_i$$ here` → `$$\sum_i x_i$$` byte-preserved), and the F1
  unbalanced-`$` test. ~15 LOC, no LaTeXML required.
- **Regression guard:** The three tests above are themselves the guard.

### F4 — `_neutralize_structural_commands` is dead code; its docstring now misstates where neutralization runs

- **Severity:** LOW
- **File:** ingest/textbook_renderer.py:94
- **What:** `_neutralize_structural_commands` (line 94-100) is defined but called
  from nowhere in production (`rg` confirms only test/probe references). Its
  docstring says "the actual neutralization happens in `_build_latex_wrapper` via
  the same regex" — but post-this-milestone the neutralization runs on the
  HEADING-CONVERTED body (`_STRUCTURAL_CMD_RE.sub` at line 223 operates on
  `sectioned`, line 214), whereas this counter operates on RAW markdown. Verified:
  for `# A heading with \end{document}`, the raw counter returns 1 while the wrapper
  neutralizes 0 (the `\end{document}` is now inside a heading title and was already
  rendered inert via `\textbackslash{}`/brace escaping before `_STRUCTURAL_CMD_RE`
  ever sees it). The "same regex / same count" invariant the docstring implies is
  now false.
- **Why it matters:** Pre-existing dead code (it was unused before this milestone
  too), so not introduced here — but this milestone changed the body the real
  neutralizer runs against, making the observability helper's docstring actively
  misleading for anyone who later wires it up as a metric.
- **Proposed fix:** Either delete `_neutralize_structural_commands` (it has no
  caller) or, if kept as a future metric hook, correct its docstring to note it
  measures RAW-markdown occurrences and will diverge from the wrapper's post-
  heading-conversion neutralization count.
- **Regression guard:** N/A (dead-code removal); if kept, a comment suffices.

### F5 — Heading math-span carve-out passes `\input`/`\write18` verbatim to LaTeXML

- **Severity:** LOW
- **File:** ingest/textbook_renderer.py:156
- **What:** `_escape_heading_title` deliberately leaves `$...$` spans unescaped, so
  `## See $\input{/etc/passwd}$ now` → `\subsection{See $\input{/etc/passwd}$ now}`
  (verified). A crafted heading can smuggle an arbitrary LaTeX command into the
  LaTeXML input via the math carve-out.
- **Why it matters:** This is NOT a new hole introduced by this milestone — non-
  heading body math (e.g. line 51's `$$...$$`) already passes verbatim to the same
  `parse_with_latexml` subprocess. LaTeXML does not enable `\write18` shell-escape by
  default, MinerU is invoked without `shell=True`
  (`.claude/docs/security-pdf-sandbox.md:64`), and the threat model is loopback-only,
  operator-supplied PDFs, single-user. The mechanism is worth recording but the
  residual risk is bounded by the existing sandbox posture, hence LOW.
- **Proposed fix:** No code change required for this milestone. If a future
  hardening pass wants defense-in-depth, run `latexmlc` with `--nofonts`/restricted
  paths or a `\input`/`\include` blocklist scan — but track separately; do not
  expand this milestone's scope.
- **Regression guard:** N/A (accepted posture). A note in
  `.claude/docs/security-pdf-sandbox.md` that heading math spans are an injection
  vector equal to body math would document the decision.

## What was done well

- The math-aware split-then-escape design (FM-1) is implemented correctly for the
  common balanced-`$` case; `$\mathbf{P}^2$` and `$x_i$` survive byte-for-byte and the
  subscript `_` is NOT escaped (verified by running the real code).
- The even/odd parity claim in `_escape_heading_title` is actually correct, including
  the tricky leading/trailing-math cases — `re.split` emits empty strings at EVEN
  indices, which route to prose-escaping harmlessly. This is the subtle bug the prompt
  flagged as likely; it is genuinely absent.
- Heading-conversion-BEFORE-structural-neutralization ordering (FM-5) is correct, and
  a heading containing `\end{document}` is provably made inert (the leading `\` →
  `\textbackslash{}` plus brace escaping). The envelope's single closing
  `\end{document}` is preserved, asserted at line 178.
- The docstring lockstep correction the research demanded landed: the module and
  `_build_latex_wrapper` docstrings now state heading structure is REQUIRED for the e3
  chunker to emit chunks (lines 9-19, 191-209), reversing the prior false "prose
  fidelity is irrelevant" claim that was the root cause.
- Closed-ATX trailing-`#` stripping (FM-4) and the space-required `#hashtag` guard
  (FM-2) both work and are tested (lines 148-162).
- No new dependency — stdlib `re` only, as the synthesis mandated. No tool-schema
  touch, no `EXPECTED_TOOL_SCHEMA_SHA256` impact (Axis 1 clean). No `KMP` change.
- Tests extend the existing `TestBuildLatexWrapper` class idiomatically rather than
  adding a parallel class, exactly as the brief required, and assert on the generated
  LaTeX string (fast, no LaTeXML dependency).
- The m6 structural-command neutralization (`test_plain_math_untouched_by_sanitizer`)
  is preserved un-regressed; `\begin{align}` math is not falsely neutralized.
- End-to-end proof against real LaTeXML (`1611.02087` → 21 chunks, was 0) is recorded
  in the implementation summary, demonstrating the actual root-cause fix lands.

## Recommended rectification order

1. F1 — add `"$": "\\$"` to `_HEADING_PROSE_ESCAPE` (one line; closes the only
   common-path correctness hole and subsumes F2). Highest leverage.
2. F3 — add the three missing math-edge tests (unbalanced `$`, display `$$` in
   heading, math-only title); the unbalanced-`$` test is the regression guard for F1.
3. F2 — amend the line 118-119 comment to state the unbalanced-`$` is neutralized by
   escaping, not by the regex alone (rides along with F1).
4. F4 — delete or re-document `_neutralize_structural_commands` (cheap, optional).
5. F5 — no code change; optionally document the heading-math injection-equivalence in
   the security sandbox doc. Defer.

## Rectification status

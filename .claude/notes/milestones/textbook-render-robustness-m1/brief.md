# textbook-render-robustness-m1 — Configurable LaTeXML render timeout + MinerU math-balance sanitization

## PROBLEM

Two distinct failure points in the textbook render path (`ingest/textbook_renderer.py`
→ `tools/arxiv_fetch.py::parse_with_latexml`) leave math-heavy MinerU-parsed PDFs
unchunkable. Discovered 2026-06-08 completing the bridgeland-stability-pdfs ingest:

1. **Hardcoded 300 s LaTeXML render timeout is too short for math-dense papers.**
   `tools/arxiv_fetch.py:38` `LATEXML_TIMEOUT_SECONDS = 300`. `render_mineru_to_html`
   calls `parse_with_latexml(...)` WITHOUT a timeout arg, so it always uses 300 s.
   Paper `2506.21995` (amsart): MinerU **succeeded** (2611 s, markdown cached at
   `parsed/2506.21995/2506.21995/auto/2506.21995.md`), but the LaTeXML render then
   `[FAIL]`ed with `TimeoutExpired ... timed out after 300 seconds`. The same will hit
   `hep-th/0403166` (article). So the gate is the render timeout, NOT MinerU.

2. **Unbalanced math environments in MinerU markdown abort the whole LaTeXML document.**
   Paper `1404.3143`: MinerU emitted markdown with **0 `\begin{array}` but 36
   `\end{array}`** (extraction dropped the openers). LaTeXML hits
   `Error:unexpected:\@end@array Attempt to close boxing group` +
   `Missing $ closing display math` and aborts the body → a near-empty 1872-byte
   `index.html` → 0 chunks. `$$` delimiters happen to be balanced (140, even) here, but
   the unbalanced `array` environment is fatal.

## FIX SCOPE / TASKS

**(a) Configurable LaTeXML render timeout.**
- Make the render timeout overridable via an env var (propose `ARXMCP_LATEXML_TIMEOUT_S`),
  default = existing 300 s, range-validated (mirror the MinerU timeout pattern in
  `ingest/textbook_parser.py::_parse_timeout_from_env`, bounds e.g. [60, 3600]).
- Thread it through `render_mineru_to_html` → `parse_with_latexml(..., timeout=...)`.
  Today `render_mineru_to_html` does not pass a timeout, so it pins 300 s.
- Keep the existing process-group-kill / sandbox discipline of `parse_with_latexml`
  intact (do NOT regress the E13_S03 Threat-3 timeout/killpg behavior).

**(b) MinerU-markdown math-balance sanitization.**
- Before wrapping (in `_build_latex_wrapper` or a dedicated pre-pass), neutralize
  unbalanced math constructs that abort LaTeXML so the document still renders (degraded
  regions are acceptable; a non-empty doc → chunks beats 0 chunks):
  - Orphaned `\end{array}` with no matching `\begin{array}` (the 1404.3143 case), and
    the symmetric orphaned `\begin{array}`.
  - Optionally unbalanced `$$` display delimiters (odd count) — neutralize the trailing
    lone `$$`.
  - Keep it conservative: only touch provably-unbalanced constructs; do NOT alter
    balanced math. The goal is "LaTeXML completes with degraded arrays" not "perfect
    math".
- This must compose with the existing m6 F3 structural-command neutralization and the
  textbook-md-heading-sectioning-m1 heading conversion (do not regress either).

**(c) Tests.** Pure-Python unit tests: timeout env parsing (default/override/out-of-range),
timeout threaded to `parse_with_latexml` (assert via mock/inspection), and sanitization
(orphaned `\end{array}` neutralized, balanced math untouched, unbalanced `$$` handled,
heading + structural-cmd neutralization still hold). Prefer string-level asserts (no
LaTeXML needed); a `requires_latexmlc` end-to-end (1404.3143-like input renders
non-empty) is optional/bonus.

**(d) ruff + full test suite green** (~29-66 pre-existing Windows-only failures expected;
prove zero NEW real failures). Commit per repo conventions; GPG lands unsigned (known
no-key state); never `--no-verify` / `--no-gpg-sign`.

## CONSTRAINTS / CONTEXT

- `parse_with_latexml` is security-audited (E13_S03 Threat-3: process-group kill,
  sandbox profile). Changing only the timeout VALUE (caller-supplied) is low-risk, but
  keep the kill/sandbox path intact.
- Windows-native dev; tests via `.venv/Scripts/python.exe -m pytest`. `latexmlc` at
  `C:/Strawberry/perl/site/bin/latexmlc.BAT`.
- DOWNSTREAM (after this milestone, OUTSIDE its commit scope): re-render the 3 stragglers
  from cached MinerU markdown with the longer timeout + sanitization
  (`2506.21995`, `hep-th/0403166`, `1404.3143`), then
  `tools/notebook_textbook_ingest.py` them into `bridgeland-stability-pdfs`. Operator
  work via `var/parse_pdfs.py` (gitignored), NOT part of this milestone.
- Prior related milestone: `textbook-md-heading-sectioning-m1` (same file/function area).

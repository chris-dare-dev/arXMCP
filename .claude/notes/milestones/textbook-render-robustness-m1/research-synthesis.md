# Research Synthesis — textbook-render-robustness-m1

Single-mode. Source: [research-brief-1.md](research-brief-1.md). Decisions locked below.

## (a) Configurable LaTeXML render timeout
- In `tools/arxiv_fetch.py`, mirror `ingest/textbook_parser.py::_parse_timeout_from_env`
  EXACTLY: `_parse_latexml_timeout_from_env()`, env `ARXMCP_LATEXML_TIMEOUT_S`,
  default = 300 (unchanged), bounds `[30, 1800]`, resolved at module import as
  `_CONFIGURED_LATEXML_TIMEOUT_S`. Invalid/out-of-range → RuntimeError at import.
- `render_mineru_to_html` (in `ingest/textbook_renderer.py`) must pass
  `timeout=_CONFIGURED_LATEXML_TIMEOUT_S` into its `parse_with_latexml(...)` call
  (today it passes none → pinned 300). Import the constant from `tools.arxiv_fetch`.
- **Do NOT regress the E13_S03 Threat-3 killpg/sandbox discipline** — only the timeout
  VALUE changes; `start_new_session=True` + `os.killpg` control flow stays byte-identical
  (the `TestProcessGroupKill` AST test must still pass). Do NOT re-add the `--timeout=300`
  latexmlc CLI flag (E13_S03b F3 dropped it deliberately).

## (b) Math-balance sanitization (server-scan landmine + algorithm)
- **LANDMINE:** `server/config.py` Config has `extra="forbid"` and
  `server/main.py::_scan_unknown_arxmcp_env_vars` FATALs on any `ARXMCP_*` not in
  `Config.model_fields`. `ARXMCP_LATEXML_TIMEOUT_S` is ingest/CLI-only → add it to the
  `_KNOWN_INGEST_ENV_VARS` carve-out in `server/main.py` (like `ARXMCP_CONTACT_EMAIL`),
  with an "unset for the server" hint. Do NOT make it a Config field (server never calls
  LaTeXML). (Note: `ARXMCP_MINERU_*` remain a pre-existing gap — out of scope here.)
- `_sanitize_math_balance(markdown_content) -> str` in `ingest/textbook_renderer.py`,
  called as STEP 0 in `_build_latex_wrapper`, BEFORE `_convert_markdown_headings_to_latex`
  (heading conversion escapes `\` → `\textbackslash{}`, which would hide `\end{array}`).
- **Algorithm (depth counter, scope = `array` only):** forward scan; `\begin{array}`
  → depth+1, `\end{array}` → depth-1. If a decrement would take depth below 0, that
  `\end{array}` is orphaned → drop it, keep depth at 0. After the pass, if depth > 0,
  append that many `\end{array}` so LaTeXML closes open arrays. Depth counter handles
  nesting and is balanced-safe (a balanced array nets 0 → untouched). Do NOT touch `$$`
  parity (1404.3143's `$$` was already balanced at 140; the array orphans caused the
  "Missing $ closing display math" cascade — fixing `array` resolves it).

## Tests
- `tests/test_arxiv_fetch.py` → new `TestLatexmlTimeoutConfig`: unset→300; valid override
  used; non-int→RuntimeError; out-of-range→RuntimeError. (Test the parse function;
  module-load constant is read once.)
- `tests/test_textbook_renderer.py::TestBuildLatexWrapper` → sanitization: orphaned
  `\end{array}` dropped, balanced array untouched, nested arrays correct, unclosed
  `\begin{array}` gets appended close; heading conversion + structural-cmd neutralization
  still hold; `render_mineru_to_html` passes the configured timeout (mock parse_with_latexml).
- No tool-schema touch. ruff + suite green; zero NEW real failures.

## Open questions / External writes
None / none (purely local).

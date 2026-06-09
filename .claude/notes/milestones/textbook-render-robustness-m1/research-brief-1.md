# Research Brief — textbook-render-robustness-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-06-08T00:00:00Z

## In-codebase context

### (a) Configurable LaTeXML timeout

`tools/arxiv_fetch.py` line 38 hardcodes:
```python
LATEXML_TIMEOUT_SECONDS = 300
```

`parse_with_latexml` signature:
```python
def parse_with_latexml(
    main_tex: Path,
    parsed_dir: Path,
    paper_id: str,
    timeout: float = LATEXML_TIMEOUT_SECONDS,
) -> ParseResult:
```

`render_mineru_to_html` (line 320–324) calls:
```python
parse_with_latexml(
    main_tex=main_tex,
    parsed_dir=parsed_dir,
    paper_id=flat,
)
```

**Confirmed: no `timeout=` arg is passed — always 300s.** This is the bug.

Process-group kill discipline (load-bearing, must NOT be regressed):
```python
proc = subprocess.Popen(cmd, ..., start_new_session=True)
try:
    proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    with contextlib.suppress(ProcessLookupError):
        if hasattr(os, "getpgid"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=5)
    raise
```

From `.claude/docs/security-threat-3-audit.md`: "Python-side `subprocess` timeout + `killpg` remain the load-bearing timeout discipline." The `TestProcessGroupKill` test uses AST-based static analysis to confirm `start_new_session=True` and `killpg` are both present — a refactor that moves or conditionalizes these will fail that test. The timeout parameter change must NOT alter the control flow of the killpg block.

### (b) MinerU math-balance sanitization

`_build_latex_wrapper` pipeline (lines 228–244):
1. `sectioned = _convert_markdown_headings_to_latex(markdown_content)` — ATX heading conversion FIRST
2. `safe_body = _STRUCTURAL_CMD_RE.sub(...)` — structural-cmd neutralization SECOND

`_STRUCTURAL_CMD_RE` matches only:
```python
_STRUCTURAL_CMD_RE = re.compile(
    r"\\(end|begin)\s*\{\s*document\s*\}|\\documentclass\b"
)
```
It does NOT match `\begin{array}` or `\end{array}`. The new math-balance sanitization must be inserted as step 0 (before heading conversion) or step 1.5 (after heading conversion, before structural-cmd neutralization).

**Correct placement: step 0 (before heading conversion).** Rationale: heading conversion escapes `\` in prose to `\textbackslash{}`, which would destroy any `\end{array}` inside prose before the sanitizer could detect it. The sanitization must operate on the RAW markdown, before any backslash transformations. The structural-cmd neutralization (step 2) does not touch `\begin{array}` / `\end{array}`, so the sanitizer does not compose with it — they are orthogonal.

### (c) ARXMCP_LATEXML_TIMEOUT_S env var — the server-scan landmine

`server/config.py` uses:
```python
model_config = SettingsConfigDict(
    env_prefix="ARXMCP_",
    extra="forbid",  # unknown ARXMCP_* vars are configuration errors.
)
```

`server/main.py::_scan_unknown_arxmcp_env_vars` (line 359–399):
```python
declared = frozenset(
    f"ARXMCP_{name.upper()}" for name in Config.model_fields
)
unknown = sorted(
    env_name
    for env_name in os.environ
    if env_name.startswith("ARXMCP_") and env_name not in declared
)
if not unknown:
    return
...
raise ValueError("unknown ARXMCP_* environment variables...")
```

**CRITICAL LANDMINE: `ARXMCP_LATEXML_TIMEOUT_S` is an ingest/CLI-only variable. If an operator exports it in their shell and then runs `make up`, the server scan will FATAL at startup with an "unknown ARXMCP_* env var" error.**

The existing precedent for handling this is `_KNOWN_INGEST_ENV_VARS` in `server/main.py`. `ARXMCP_MINERU_TIMEOUT_S` and `ARXMCP_MINERU_BIN` are NOT in the carve-out dict — but testing confirms they would also FATAL if set. There are two options:
1. Declare `latexml_timeout_s` as a `Config` field (with a default and range validator) — this makes it a server config var too, but the server doesn't use LaTeXML directly.
2. Add `ARXMCP_LATEXML_TIMEOUT_S` to `_KNOWN_INGEST_ENV_VARS` carve-out dict — exactly like `ARXMCP_CONTACT_EMAIL`.

**Recommendation: Option 2 — add to `_KNOWN_INGEST_ENV_VARS`.** Option 1 is wrong because the server never calls LaTeXML; a server Config field for it would be misleading. The correct analogy is `ARXMCP_CONTACT_EMAIL`: a CLI/ingest tool var that gets a tailored "unset this for the server" hint instead of a fatal.

### (d) MinerU timeout pattern to mirror exactly

From `ingest/textbook_parser.py` lines 115–145:
```python
_DEFAULT_TIMEOUT_S: int = 30 * 60
_TIMEOUT_MIN_S: int = 60
_TIMEOUT_MAX_S: int = 3600

def _parse_timeout_from_env() -> int:
    raw = os.environ.get("ARXMCP_MINERU_TIMEOUT_S", "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_S
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"ARXMCP_MINERU_TIMEOUT_S={raw!r} is not a valid integer; ..."
        ) from exc
    if value < _TIMEOUT_MIN_S or value > _TIMEOUT_MAX_S:
        raise RuntimeError(
            f"ARXMCP_MINERU_TIMEOUT_S={value} is out of range ..."
        )
    return value

#: Resolved at import time so config errors surface at server-startup, not at first PDF upload.
_CONFIGURED_TIMEOUT_S: int = _parse_timeout_from_env()
```

**Mirror this pattern exactly in `tools/arxiv_fetch.py`:** module-level `_parse_latexml_timeout_from_env()`, bounds `[30, 1800]` (LaTeXML is faster than MinerU; 30s minimum is more appropriate than 60s; 1800s = 30min cap), resolved at import time as `_CONFIGURED_LATEXML_TIMEOUT_S`. The default stays 300. Pass `timeout=_CONFIGURED_LATEXML_TIMEOUT_S` in `render_mineru_to_html`'s call to `parse_with_latexml`.

### (e) Test files

`tests/test_textbook_renderer.py` — pure-Python unit tests in `TestBuildLatexWrapper`. New tests for math-balance sanitization extend this class idiomatically. A mock-based test for the configurable timeout belongs in `tests/test_arxiv_fetch.py::TestParseWithLatexml`.

`tests/test_arxiv_fetch.py` already tests timeout kill discipline (`test_timeout_uses_killpg_when_getpgid_present`, `test_timeout_falls_back_to_proc_kill_without_getpgid`). A new `TestLatexmlTimeoutConfig` class verifies: env-unset → default 300; valid override → used; non-integer → RuntimeError; out-of-range → RuntimeError.

## Prior decisions and lessons

Recent git log shows `textbook-md-heading-sectioning-m1` landed (commit `243019f`), rectified (commit `3f88625`), and closed (commit `ba0d6e4`). The heading conversion and `_STRUCTURAL_CMD_RE` neutralization are finalized — this milestone must compose with them, not replace them.

From `.claude/docs/security-threat-3-audit.md`:
- The `TestProcessGroupKill` AST test in `tests/security/test_latexml_sandbox.py` statically verifies `start_new_session=True` and `killpg` are present. This test will NOT break if we only add a `timeout=` parameter — we are not changing control flow.
- "Python-side `subprocess` timeout + `killpg` remain the load-bearing timeout discipline." Making it configurable does not change the discipline.
- The `--timeout=300` latexmlc CLI flag was deliberately dropped (E13_S03b F3) because no live-integration test proves the flag is accepted. Do NOT re-add it.

Memory note from `MEMORY.md`: `_parse_timeout_from_env()` is the established module-load pattern. Apply it identically for `ARXMCP_LATEXML_TIMEOUT_S`.

## External sources

This milestone is purely local — no MCP spec or prompt-caching changes. No tool schema changes. No new MCP tool is added or modified. `EXPECTED_TOOL_SCHEMA_SHA256` is unchanged.

No external docs needed beyond the in-codebase analysis above.

## Recommendation

**For (a) Timeout:** Add `_parse_latexml_timeout_from_env()` to `tools/arxiv_fetch.py` mirroring the MinerU pattern exactly. Name the env var `ARXMCP_LATEXML_TIMEOUT_S`, default 300, bounds `[30, 1800]`, resolved at module import as `_CONFIGURED_LATEXML_TIMEOUT_S`. Patch `render_mineru_to_html` to pass `timeout=_CONFIGURED_LATEXML_TIMEOUT_S` through to `parse_with_latexml`. Add `ARXMCP_LATEXML_TIMEOUT_S` to `_KNOWN_INGEST_ENV_VARS` in `server/main.py` with an "ingest-tool-only" message. Do NOT add a Config field — the server never calls LaTeXML.

**For (b) Sanitization:** Add `_sanitize_math_balance(markdown_content: str) -> str` to `ingest/textbook_renderer.py`. The algorithm: single forward pass, count `\begin{array}` and `\end{array}` (and optionally `$$`). If `end_count > begin_count`, remove `(end_count - begin_count)` orphaned `\end{array}` occurrences from the END of the content (reverse scan — orphaned ones appear after their "unmatched" context). The neutralization must be conservative: only operate on demonstrably unbalanced constructs. Call this as step 0 in `_build_latex_wrapper` before `_convert_markdown_headings_to_latex`.

**Concrete sanitization algorithm:** use a two-pass approach.
1. Scan forward; maintain a counter. `\begin{array}` increments, `\end{array}` decrements. If counter goes below 0, that `\end{array}` is orphaned — remove it and reset counter to 0.
2. After the forward pass, if counter > 0, there are unclosed `\begin{array}` — append that many `\end{array}` at the end (so LaTeXML closes them). This prevents "Missing closing $ for display math" from an open array.

This handles nested arrays correctly because the counter tracks nesting depth. A balanced `$$\begin{array}...\end{array}$$` contributes +1 then -1 = net 0 regardless of being inside `$$`. Apply the same algorithm independently for other commonly unbalanced environments (e.g. `pmatrix`, `bmatrix`, `align`) — but scope this milestone to `array` only (the confirmed failure mode). `$$` unbalance can be handled by counting and appending a closing `$$` if count is odd.

## Failure-mode analysis

**(i) Balanced `\begin{array}` inside `$$...$$` miscounted.**
Trigger: content like `$$\begin{array}{cc} a & b \\ \end{array}$$` — perfectly balanced but the counter approach still counts it. 
Symptom: none — the counter increments then decrements to 0. The forward-pass counter approach is CORRECT for balanced content; it only removes `\end{array}` occurrences that drive the counter below 0. No false correction.

**(ii) Nested arrays — `\begin{array}` inside `\begin{array}`.**
Trigger: `\begin{array}{c} \begin{array}{cc} x \end{array} \end{array}` — depth-2 nesting.
Symptom if counter is a simple toggle: the inner `\end{array}` would appear to close the outer. But a depth counter handles this correctly — the second `\begin{array}` increments to 2, the first `\end{array}` decrements to 1 (not removed), the second `\end{array}` decrements to 0. Correct.

**(iii) `\end{array}` orphan inside display math `$$...$$`.**
Trigger: MinerU emits `$$ \end{array} $$` without a preceding `\begin{array}`. Counter goes to -1 at the `\end{array}`. The forward pass correctly identifies it as orphaned and removes it. LaTeXML receives a `$$ $$` (empty display math) which is benign.

**(iv) Over-correction — removing a `\end{array}` that was actually closing a `\begin{array}` from a PREVIOUS content block.**
Trigger: this cannot happen with the forward-pass counter — the counter only goes negative when a `\end` has no prior unmatched `\begin`. The counter approach is definition-correct; it will not remove a `\end{array}` that is actually balanced.

**(v) Server-scan FATAL when `ARXMCP_LATEXML_TIMEOUT_S` is set in the operator's shell.**
Trigger: operator exports `ARXMCP_LATEXML_TIMEOUT_S=600` to make re-renders faster, then runs `make up`. `_scan_unknown_arxmcp_env_vars` scans env, finds `ARXMCP_LATEXML_TIMEOUT_S` not in `Config.model_fields`, raises `ValueError` — server fails to start.
Mitigation: add entry to `_KNOWN_INGEST_ENV_VARS` with a "not a server config var; used by `ingest/textbook_renderer.py` + `tools/arxiv_fetch.py`; unset it for the server" hint. **Flag: this is the highest-risk landmine in this milestone if missed.**

**(vi) Timeout read at module-load vs per-call.**
Trigger: MinerU pattern reads at module load. If `render_mineru_to_html` is called from a process that sets `ARXMCP_LATEXML_TIMEOUT_S` AFTER importing `tools/arxiv_fetch.py`, the value will be stale (default 300).
Analysis: this matches MinerU's behavior exactly (`_CONFIGURED_TIMEOUT_S` is read at import time). It is acceptable and consistent with the established pattern. The operator must set env vars before process start. Document this in the function's docstring.

**(vii) The env-var bounds mismatch between LaTeXML and MinerU.**
MinerU bounds: `[60, 3600]`. Proposed LaTeXML bounds: `[30, 1800]`. A paper timing out at 300s on LaTeXML may need 500–600s. The 1800s upper bound is generous enough for any real case. The 30s lower bound is appropriate since LaTeXML on a small markdown file can process in 10–20s.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one design choice that could be argued: whether to scope math-balance sanitization to `array` only or also `$$` parity. Recommendation: scope to `array` only for this milestone. Unbalanced `$$` in MinerU output from a well-formed PDF source is much less likely; adding it risks over-correction on content with intentional display-math syntax. This is conservative and correct for the documented failure cases.

## External writes the implementation will require

None — this milestone is purely local.

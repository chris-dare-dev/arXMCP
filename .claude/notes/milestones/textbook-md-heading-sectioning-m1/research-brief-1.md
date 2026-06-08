# Research Brief — textbook-md-heading-sectioning-m1

**Agent:** milestone-researcher (brief-1, single-mode)
**Generated:** 2026-06-08T00:00:00Z

## In-codebase context

### Load-bearing design note conflict — FLAG

**The `_build_latex_wrapper` docstring and the m6 research synthesis contain a statement that directly conflicts with the milestone brief's root cause:**

- `ingest/textbook_renderer.py` lines 8–10 (module docstring): "markdown prose constructs (`## headers`, `**emphasis**`, `[links](urls)`, lists) render as literal characters in the HTML output — best-effort. **The chunker (e3) consumes math blocks regardless of prose-render fidelity.**"
- `_build_latex_wrapper` docstring (lines 97–99): "Prose constructs render as literal text in LaTeX — acceptable for v1 (the retrieval substrate consumes math, not prose layout)."
- m6 research-synthesis.md §D1 "Strategy A": "The textbook chunker (e3) consumes math blocks and structural metadata via `content_list.json`, NOT prose layout from `index.html`. So prose-render imperfection is invisible at the retrieval layer."

**This was wrong.** `ingest/textbook_chunker.py` (m7) calls `_extract_section_chunks(soup, ...)` which scans `_SECTION_DIV_CLASSES = ["ltx_chapter", "ltx_section", "ltx_subsection", "ltx_subsubsection", "ltx_paragraph"]`, and `_extract_chunks_from_container(root, ...)` which looks for theorem-like envs inside section divs. If LaTeXML's HTML contains NO `ltx_section` divs (because ATX headings were never converted to `\section{}`), BOTH passes return `[]`. The docstring's claim that prose-render fidelity is irrelevant was adopted without verifying the e3 chunker's actual dependency. **The fix is correct and necessary; the docstring must be updated in lockstep.**

### `_SECTION_DIV_CLASSES` (chunker.py lines 154–159)

```python
_SECTION_DIV_CLASSES = [
    "ltx_chapter",
    "ltx_section",
    "ltx_subsection",
    "ltx_subsubsection",
    "ltx_paragraph",
```

These are the exact HTML class values LaTeXML emits when it processes `\chapter`, `\section`, `\subsection`, `\subsubsection`, `\paragraph`. Without them the textbook chunker produces zero chunks.

### `_build_latex_wrapper` (textbook_renderer.py lines 94–120)

The function currently:
1. Runs `_STRUCTURAL_CMD_RE.sub(...)` to neutralize `\end{document}` / `\begin{document}` / `\documentclass` (m6 F3).
2. Wraps in `_LATEX_ENVELOPE` via string `.replace("{body}", safe_body)`.

The fix adds a heading-conversion pass **before** step 1. Order matters: heading conversion must run before the structural-command neutralization so no heading text accidentally contains `\end{document}` type content (edge case, but step ordering is correct).

### `_STRUCTURAL_CMD_RE` (textbook_renderer.py lines 80–82)

```python
_STRUCTURAL_CMD_RE = re.compile(
    r"\\(end|begin)\s*\{\s*document\s*\}|\\documentclass\b"
)
```

This pattern does NOT match `\section`, `\subsection`, or `\subsubsection` — the generated heading commands from the fix are safe from inadvertent neutralization. No conflict.

### Existing test structure (`tests/test_textbook_renderer.py`)

The file has:
- `class TestBuildLatexWrapper` — 7 pure-Python unit tests covering: envelope present, math passthrough, empty body, structural-command neutralization (F3), plain math untouched.
- `class TestFlatPaperId` — parametrized tests.
- `class TestRenderResultIsFrozen` — frozen dataclass check.
- `class TestRenderMineruToHtmlSurface` — mocked integration tests.
- `class TestRealLatexml` — gated behind `@pytest.mark.requires_latexmlc` and `skipif("shutil.which('latexmlc') is None or os.environ.get('ARXMCP_RUN_REAL_LATEXMLC') != '1'", ...)`.

**The implementer MUST extend `TestBuildLatexWrapper` idiomatically** — add new test methods to the existing class rather than a new class. The `test_plain_math_untouched_by_sanitizer` test asserts `"\\textbackslash{}" not in out` — the new heading-conversion pass must not regress this (i.e., must not call the structural-cmd sanitizer on non-structural text).

### `requires_latexmlc` marker

Registered in `pyproject.toml` markers. Gate: `@pytest.mark.requires_latexmlc` + `skipif("shutil.which('latexmlc') is None or os.environ.get('ARXMCP_RUN_REAL_LATEXMLC') != '1'", ...)`. The existing `TestRealLatexml.test_synthetic_markdown_renders` DOES NOT assert `ltx_section` in the HTML — adding a heading-aware assertion there would be high-value bonus coverage but is optional.

### No tool-schema touch

This milestone touches only `ingest/textbook_renderer.py` and tests. No MCP tool is added/modified. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning.

### `KMP_DUPLICATE_LIB_OK=TRUE` guard

`tests/conftest.py` lines 36–38 set this at module load. The fix touches only `ingest/textbook_renderer.py` — no PyTorch/faiss import paths added. Guard is safe.

---

## Prior decisions and lessons

### m6 F3: structural-command neutralization (MUST NOT regress)

The neutralization of `\end{document}` / `\begin{document}` / `\documentclass` via `_STRUCTURAL_CMD_RE` was the m6 adversary's highest-severity finding. The fix must preserve this substitution. **Correct order: heading conversion first, then structural-command neutralization.** This ensures a heading like `# \end{document}` (improbable but possible) gets converted to `\section{\textbackslash{}end{document}}` — neutralization runs on the heading-converted body, not raw markdown.

### m6 synthesis: "Strategy A prose-render is best-effort, acceptable for v1"

This justification is now **invalidated** by the evidence that e3 requires `ltx_section` divs. The docstring in `_build_latex_wrapper` must be updated to reflect the corrected understanding: heading conversion is required for the chunker to produce any output, not optional cosmetics.

### Recent git log context

The three most recent milestones (`windows-parse-path-fix-m1`, `oldstyle-id-ingest-fix-m1`, `ui-htmx-json-fix-m1`) are all focused bug fixes with the standard three-commit pattern. This milestone follows the same pattern: one focused function fix + tests.

### Windows dev environment

The platform is Windows 11 (from `CLAUDE.md` §4.5 note and git status). Test runner: `.venv/Scripts/python.exe -m pytest` per the milestone brief. `KMP_DUPLICATE_LIB_OK` is a macOS guard and is effectively a no-op on Windows but must not be removed.

---

## External sources

Not directly relevant — this milestone is a pure Python regex/string-transform fix. No MCP spec or Anthropic prompt-caching docs needed. The LaTeXML HTML class conventions (`ltx_section`, `ltx_subsection`) are already verified by the existing codebase (m7 synthesis §D, §2: "LaTeXML emits `\chapter` as `<section class="ltx_chapter">` ... verified by brief-2 against `var/arxmcp/corpus/parsed/1306.2070/index.html`"). No external fetch required.

---

## Failure-mode analysis

### FM-1: Inline math in heading title — the top risk

**Trigger:** `## The space $\mathbf{P}^2$ and its blowup`
**Symptom:** Naive escaping of `_`, `#`, `%`, `&` inside the heading title corrupts `\mathbf{P}^2` — specifically `_` in subscripts (`$x_i$`) becomes `\_` which LaTeXML may reject, and `#` in `\binom{n}{k}` becomes `\#` breaking the math.
**Mitigation (concrete recommendation — see §Recommendation):** Split the title text on math spans (`$...$`, `$$...$$`) before escaping. Escape only the non-math segments; leave math segments untouched. A regex like `re.split(r'(\$\$.*?\$\$|\$[^$\n]+?\$)', title)` (non-greedy, non-newline) alternates non-math/math spans; odd-indexed chunks are math, even-indexed are prose to escape.

### FM-2: Non-heading `#` characters

**Trigger:** `#hashtag` (no space after `#`), or `#` mid-line in a table cell (`| col | # notes |`), or `#` inside a math block (`$f\#g$` in category theory).
**Symptom:** False conversion — these are emitted as `\section{hashtag}` or corrupt math.
**Mitigation:** ATX heading detection MUST require `^#{1,6}\s+` (line-anchored, space required after `#` run). This matches CommonMark/GitHub ATX spec. A `#` without a trailing space is not a heading. Math blocks containing `#` are inside `$...$` and the non-heading detection pattern (line-anchored, start-of-line) won't match them.

### FM-3: Setext-style headings

**Trigger:** MinerU occasionally emits setext headings: a title line followed by `===` (h1) or `---` (h2) underlines.
**Symptom:** If not converted, `===`/`---` lines pass through as literal chars; the heading text itself does not become `\section{}`.
**Mitigation:** Check whether the milestone brief's proven fix on paper 1611.02087 (26 headings, yielding 21 chunks) included setext headings. Given the brief says ATX `# title` conversion was sufficient, the 26 headings were likely all ATX. However, MinerU's markdown renderer is known to produce ATX headings by default (it's the dominant mode). A setext pass is low-risk to add but not required for correctness on the proven test case.
**Decision:** Implement ATX only. Add a code comment noting setext is not handled.

### FM-4: Closed ATX headings (trailing `#`)

**Trigger:** `### The proof ###` (closed ATX style).
**Symptom:** `\subsubsection{The proof ###}` — trailing `#` chars appear literally in the LaTeX section title.
**Mitigation:** Strip trailing `#+\s*` from the matched title before conversion. The regex capturing group should be `re.sub(r'^(#{1,6})\s+(.*?)\s*#*\s*$', ...)` on each line.

### FM-5: Heading conversion interacting with structural-command neutralization order

**Trigger:** A heading title that contains `\end{document}` literally: `# Intro to \end{document} command`.
**Symptom:** If structural-command neutralization runs FIRST, the backslash is escaped before the title is wrapped in `\section{}`. Running heading conversion first is correct: `\section{Intro to \end{document} command}` is produced, THEN the structural-cmd pass converts `\end{document}` inside the `\section{}` title to `\textbackslash{}end{document}`. Result: `\section{Intro to \textbackslash{}end{document} command}` — safe.
**Mitigation:** Keep the correct order: heading conversion → structural-command neutralization.

### FM-6 (bonus): Heading text with `{` or `}` braces

**Trigger:** `## The functor $F: \mathcal{C} \to \mathcal{D}$` — braces are inside math, safe. But `## Step {n}: setup` has literal `{` / `}` outside math.
**Symptom:** LaTeXML may misparse `\section{Step {n}: setup}` due to the nested braces.
**Mitigation:** Escape `{` → `\{` and `}` → `\}` in the non-math segments. Include in the escape set alongside `#`, `%`, `&`, `_`.

---

## Recommendation

**Implement the heading conversion in `_build_latex_wrapper` as a math-aware split + escape pass.**

Concrete algorithm:
1. Process the markdown body line by line.
2. For each line, test `m = re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', line)` (line-anchored ATX heading).
3. If matched: split `m.group(2)` (the title text) into alternating non-math/math spans using `re.split(r'(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)', title_raw)`. Escape chars `#%&_{}` in non-math spans only. Reassemble. Map heading depth to LaTeX command: 1→`\section`, 2→`\subsection`, 3+→`\subsubsection`.
4. If not matched: pass through unchanged.
5. Apply structural-command neutralization to the full converted body (existing step, unchanged).

**Why this and not simpler:** A naive full-title escape is tempting but breaks math-in-heading (FM-1, the highest-risk case). The math-aware split is 4–5 lines of Python using only `re` (stdlib). It does not require `markdown-it-py` or any new dependency (the m6 synthesis explicitly ruled out adding markdown deps). It handles `$...$` and `$$...$$` correctly. A double-regex approach (first match math spans, then escape non-math) is clean and testable.

**Update the `_build_latex_wrapper` docstring** to remove the claim that prose-render fidelity is irrelevant to the chunker. The corrected statement: "Heading structure (`# title`) is required for the e3 chunker (`ingest/textbook_chunker.py`) to emit any section-grain chunks — `_extract_section_chunks` requires `ltx_section`/`ltx_chapter` divs in the LaTeXML HTML output."

---

## Open questions

No open questions — implementation can proceed on the above recommendation. The math-aware split approach is specified concretely. The test cases are well-defined. The milestone scope is narrow (one function + tests).

---

## External writes the implementation will require

None — this milestone is purely local.

All deliverables land in the working tree:
- `ingest/textbook_renderer.py` — `_build_latex_wrapper` updated + docstring corrected
- `tests/test_textbook_renderer.py` — new test methods in `TestBuildLatexWrapper`

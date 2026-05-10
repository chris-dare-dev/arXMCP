# Research Brief: E02_S02 — Preamble Extractor

**Researcher:** Agent B (independent)  
**Date:** 2026-05-07

---

## 1. In-Codebase Context

### Storage layout

Raw `.tex` files live at `var/arxmcp/corpus/raw/<paper_id>/` (extracted by `fetch_eprint` in `tools/arxiv_fetch.py`). The output destination `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` is a new directory — it does not exist yet and must be created by `extract_preamble`.

`REPO_ROOT` is defined in `ingest/chunker.py` as `Path(__file__).resolve().parent.parent`. The preamble module should use the same idiom and define `PREAMBLE_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "preamble"`.

### Root-tex heuristic

`tools/arxiv_fetch.py` implements `find_main_tex(raw_dir, paper_id)`:

> "Heuristic: `<paper_id>.tex` if present, else the unique `.tex` file, else the first .tex alphabetically. arXiv submissions occasionally bundle multiple .tex (one main, several `\input{}`-ed); the main is usually the one containing `\documentclass`."

The actual priority order in code: `<paper_id>.tex` > unique candidate > first `.tex` with `\documentclass` in the first 4096 bytes > `candidates[0]`. **The milestone brief says to use the same heuristic as `fetch_one_paper.py`** — that means importing and reusing `find_main_tex` from `tools/arxiv_fetch.py` directly. Do not reimplement.

### `preamble_ref` field in `ChunkRecord`

`ingest/chunker_types.py` already declares `preamble_ref: str | None = field(default=None)` and documents: "Reserved for E02_S02 (reference to the per-paper preamble chunk). Written as `None` by this milestone." The chunker update in this milestone populates it with `SHA-256(preamble_text)[:16]`.

### BP1 byte-identical caching

`07-multi-agent-caching.md` § BP1: "Breakpoint 1 (BP1, 1-hour TTL): end of system prompt + tool definitions block. Byte-identical across every agent role." The embedder (E03_S01) reconstructs the embedding input as `preamble_text + "\n\n" + body_text` (quoted from E03_S01 spec). The `preamble_ref` hash lets E03_S01 look up `preamble.json` and reproduce that concatenation deterministically without storing it in the chunk JSON. If `preamble_text` is not deterministic across runs, E03_S01's embedding input changes, chunk embeddings drift, and BP1 cache hits become impossible.

### Idempotency precedent (F3 closure, E02_S01)

`ingest/chunker.py` `_chunk_paper_impl` demonstrates the F3 closure pattern:
```python
for stale in out_dir.glob("*.json"):
    stale.unlink()
```
This clears stale output before writing fresh. The preamble extractor must do the equivalent: on a changed-source re-run, delete `preamble.json` before writing the new one. On an unchanged-source re-run (source hash matches), return early without touching the file.

### Per-paper exception pattern

`ingest/chunker.py` defines `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)` and logs TSV rows to `var/arxmcp/ops/parser-failures/chunk.log`. The preamble module should define an analogous `PER_PAPER_FAILURE_EXCEPTIONS` and log to a new `var/arxmcp/ops/parser-failures/preamble.log` using the same TSV format: `<paper_id>\t<status>\t<elapsed_s>\t<message>`.

### `paper_id` validation

`ingest/chunker.py` provides `_validate_paper_id` (regex `^\d{4}\.\d{4,5}(v\d+)?$|^[a-z][a-z\-]*/\d{7}(v\d+)?$`) and `InvalidPaperIDError`. Import and reuse rather than duplicating.

### E03_S01 contract

E03_S01 spec (E03-embedder.md) requires: preamble_text is read from `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` via `preamble_ref` hash. The hash is the primary key. E03_S01 will therefore call something like `load_preamble(paper_id)` and use `preamble_doc.preamble_hash` to verify the reference stored on the chunk. The `PreambleDoc` dataclass must be importable from `ingest/preamble_types.py`.

---

## 2. Prior Decisions and Lessons

### Commits examined

- **c486b26** — introduced `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)` in `fetch_seed.py`. The pattern explicitly excludes programmer bugs (`AttributeError`, `KeyError`, `TypeError`) so they propagate and surface during development.
- **01c6579** — extended the same exception isolation to `fetch_one_paper.py`, after a smoke test found `subprocess.TimeoutExpired` was not caught. Lesson: `TimeoutExpired` is a resilience-pattern exception (not a programmer bug); it should be in `PER_PAPER_FAILURE_EXCEPTIONS` for any module that runs subprocesses. The preamble extractor does not run subprocesses, so this is not immediately relevant, but the lesson is: enumerate exceptions conservatively and err toward propagating unusual cases until a smoke test surfaces them.
- **c0a7d55** / **ef66061** — chunker landed, then rectified. The rectification closed F3 (stale-output idempotency), F5 (silent truncation surfaced via `truncated` flag), F6 (character-offset slicing not encode/decode), F8 (targeted exception envelope), and F13 (recursion depth bound). The preamble extractor is simpler (no HTML parsing, no recursion), but F3 and F8 are directly applicable.

### TSV failure log convention

TSV format is established: `<paper_id>\t<status>\t<elapsed_s>\t<message>`. Fields must be sanitized via `_sanitize_log_field` (strip `\t`, `\n`, `\r`). Use `time.monotonic()` for elapsed measurement bracketing the entire `extract_preamble_impl` call.

### Contextual retrieval rejection

The milestone explicitly states the rejection rationale. The module docstring must contain: `"Anthropic contextual retrieval is rejected — preamble is deterministic; see 04-parsing-and-chunking.md § Preamble extraction."` This is a hard acceptance criterion.

---

## 3. External Sources: LaTeX Macro Syntax

### In-scope directives (Tier 0)

These are the five patterns the milestone spec names:

1. **`\newcommand{\name}[n][default]{body}`** — defines or redefines a command. Optional `[n]` (arg count, 0–9) and `[default]` (default for first arg). LaTeX2e source: `ltdefns.dtx`.
2. **`\renewcommand{\name}[n][default]{body}`** — same syntax, errors if command does not already exist.
3. **`\DeclareMathOperator{\name}{text}`** and `\DeclareMathOperator*{\name}{text}` — defines a math operator (from `amsmath`). Single argument for name, single for text.
4. **`\def\name{body}`** — plain TeX primitive; no optional argument syntax. Variants include `\edef` (expanded def), `\xdef` (globally expanded), `\gdef` (global). Recommendation: capture `\def`, `\edef`, `\gdef`, `\xdef` in the in-scope regex — they appear frequently in arXiv preprints and are semantically equivalent for preamble-context purposes.
5. **`\let\name=\other`** or `\let\name\other` — aliases a command. The `=` is optional whitespace.

**Additional command to capture:** `\providecommand{\name}[n][default]{body}` — defines a command only if it does not already exist. Extremely common in math papers. Recommend including it in scope even though the milestone brief does not explicitly name it.

### Out-of-scope (explicitly)

- Full macro expansion / body evaluation (Tier 2 per `04-parsing-and-chunking.md`).
- `\DeclareRobustCommand`, `\newenvironment`, `\renewenvironment` — environment definitions. Skip.
- `.sty` / `.cls` files — only parse the root `.tex` file.
- `\input{}` / `\include{}` chasing — do not recursively follow included files. Macros defined in included files are out of scope for Tier 0.

### Comment handling

`%` begins a comment to end-of-line. `\%` is a literal percent sign (not a comment). The strip logic must:
1. Scan left-to-right for `%`.
2. Before recording as comment-start, check that the `%` is not preceded by a backslash (`\%`). Simple approach: check `s[pos-1] != '\\'` (but beware `\\%` which IS a comment — double-backslash followed by percent). Correct approach: count consecutive preceding backslashes; if count is odd, the `%` is escaped; if even (including zero), it starts a comment.

Recommendation: use `re.sub(r'(?<!\\)%.*$', '', line, flags=re.MULTILINE)` — but note this does not handle `\\%` correctly. A simpler and correct approach for this scope: strip comments by finding the first unescaped `%` per line using a character-by-character scan. Since we are not expanding macros (Tier 2), a slightly imperfect comment stripper on exotic edge cases (`\\%`) is acceptable at Tier 0; document the limitation.

### Multi-line macro definitions

`\newcommand` bodies can span multiple lines using brace continuation. The body of `\newcommand{\foo}{long \\ definition}` is terminated at the matching closing `}` (brace-balanced). For extraction purposes, the implementer must either:

**Option A (recommended):** Scan for the opening `{` of the macro body, then track brace depth until depth returns to zero. This correctly handles nested braces. Emit the entire definition as a single normalized (whitespace-collapsed) string.

**Option B (acceptable for Tier 0, fragile):** Line-by-line scan with a heuristic "if the line ends before the braces close, continue accumulating." Fragile for deeply nested macros.

Recommendation: implement Option A using a brace-depth counter scanning character-by-character. For `\def` and `\let` (which have different syntax), fall back to greedy single-line matching — they rarely have multi-line bodies in math preprints.

### Whitespace normalization

After extracting each macro line (potentially multi-line), apply:
```python
import re
normalized = re.sub(r'\s+', ' ', raw_macro_line).strip()
```

This collapses all whitespace (including newlines from multi-line definitions) to single spaces.

---

## Open Questions

**None that block implementation.** The specification is sufficiently detailed. However, the implementer should note:

1. **`\providecommand` inclusion:** The milestone spec lists five directives but does not mention `\providecommand`, which is common in math preprints. Recommendation: include it. No spec change required — treat it as an obvious gap.

2. **`\def` variants:** `\edef`, `\gdef`, `\xdef` are not named in the spec. Recommendation: include them — they are semantically equivalent for preamble purposes and excluding them would produce incomplete preambles for a nontrivial fraction of seed papers.

3. **`\input{}`/`\include{}` chasing:** The spec says "reads the original `.tex` source from `var/arxmcp/corpus/raw/<paper_id>/`" — singular source file. Not chasing includes is the correct Tier 0 interpretation. Confirm this does not leave most macros unreachable for multi-file papers. For the seed corpus (math.AG, post-2010), the main `.tex` typically contains most macro definitions directly or via `\usepackage` (which is not in scope). Risk is LOW.

4. **`find_main_tex` import path:** `tools/arxiv_fetch.py` defines `find_main_tex`. The `ingest/` package does not currently import from `tools/`. Confirm that `from tools.arxiv_fetch import find_main_tex` works from within `ingest/preamble.py` (it should, since `REPO_ROOT` is on `sys.path` via `pyproject.toml`'s package config).

---

## External Writes the Implementation Will Require

- **`var/arxmcp/corpus/preamble/<paper_id>/preamble.json`** — one file per paper, written under the gitignored `var/arxmcp/` tree. 50 files for the seed corpus. No git commit needed.
- **`var/arxmcp/ops/parser-failures/preamble.log`** — TSV failure log, appended on per-paper errors. Under gitignored `var/arxmcp/`. No git commit needed.
- **`ingest/preamble.py`** and **`ingest/preamble_types.py`** — new source files, committed to the repo.
- **`ingest/chunker.py`** — modified to import `PreambleDoc`, call `extract_preamble`, and populate `preamble_ref`. Committed.
- **`tests/test_preamble.py`** — new test file with a fixture `.tex`. The fixture itself (`tests/fixtures/preamble/fixture.tex` or similar) must be committed.

No pushes, PRs, tickets, infra mutations, or third-party API calls are required. All writes are local filesystem or in-repo source files.

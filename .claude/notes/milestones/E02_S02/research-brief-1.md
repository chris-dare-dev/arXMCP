# Research Brief 1 — E02_S02: Preamble Extractor

## 1. In-Codebase Context

### Storage paths and contracts

The preamble extractor writes to `var/arxmcp/corpus/preamble/<paper_id>/preamble.json`.
Source is at `var/arxmcp/corpus/raw/<paper_id>/` (extracted by E01).
The downstream consumer is the embedder (E03_S01), which constructs the embedding input as:
`preamble_text + "\n\n" + body_text` (per `E03-embedder.md` E03_S01 description).
`preamble_text` is never stored in `body_text`; the stored `body_text` in chunk JSON
remains the raw chunk body (separation-of-concerns principle from `E02-chunker.md`).

### `preamble_ref` in chunker_types.py

`ChunkRecord` already has:
```python
preamble_ref: str | None = field(default=None)
```
with docstring: `"Reserved for E02_S02 (reference to the per-paper preamble chunk). Written as None by this milestone."`.

The updater to `ingest/chunker.py` must populate `preamble_ref` with
`SHA-256(preamble_text)[:16]` (16 hex chars). This reference is what
`E03_S01` uses to reconstruct the embedding input deterministically —
it looks up `preamble.json` by `paper_id`, then verifies the `preamble_hash` matches.

### BP1 byte-identical caching (08-security-observability-ops.md)

The note explicitly calls out determinism requirements throughout — dict keys sorted before
JSON serialisation, no timestamps, no random content. The preamble must be bit-for-bit
reproducible across independent runs. The design choice (sorted + deduplicated macro lines)
is the mechanism that enforces this.

### `find_main_tex` heuristic in `tools/arxiv_fetch.py`

The existing heuristic (lines 172–199) tries in order:
1. `<paper_id>.tex` by name.
2. The unique `.tex` file.
3. First `.tex` whose first 4096 bytes contain `\documentclass`.
4. `candidates[0]` (alphabetical fallback).

The preamble extractor **must replicate this exactly** (or import `find_main_tex` directly).
Importing is strongly preferred — avoids drift. The function is in `tools/arxiv_fetch.py`
and is already importable.

### Idempotency precedent (E02_S01 F3 closure)

`_chunk_paper_impl` in `chunker.py` does:
```python
for stale in out_dir.glob("*.json"):
    stale.unlink()
```
before writing any new files. The preamble extractor should follow a parallel pattern:
if `preamble.json` exists and its `source_hash` matches `SHA-256(main_tex.read_bytes())`,
return the cached `PreambleDoc` without rewriting. If `source_hash` does not match,
overwrite (clear-then-write, not partial-update), so a re-run on changed source is clean.

### E03_S01 contract

The embedder reads `preamble_text` from `preamble.json` via `preamble_ref` hash.
The `preamble_hash` field in `PreambleDoc` must equal `SHA-256(preamble_text).hexdigest()[:16]`
and must match the `preamble_ref` written into each chunk JSON — these must be identical
by construction (the extractor computes both from the same string).

---

## 2. Prior Decisions and Lessons

### PER_PAPER_FAILURE_EXCEPTIONS pattern

`ingest/chunker.py` defines:
```python
PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)
```
and catches it around `_chunk_paper_impl`. The same set should guard `extract_preamble`:
missing raw dir, unreadable `.tex`, truncated gzip bytes all fall here. Programmer bugs
(`AttributeError`, `RecursionError`) must NOT be caught so dev regressions surface.

### TSV failure log convention

`_log_chunk_failure` writes:
`<paper_id>\tfail\t<elapsed_s:.1f>\t<message>`. The preamble extractor should write to
`var/arxmcp/ops/parser-failures/preamble.log` in the same format. Sanitize `paper_id`
and `message` for embedded tabs/newlines (use `_sanitize_log_field` pattern or inline it).

### Idempotency: stale-output clearing before write

F3 (HIGH) from E02_S01 was closed by clearing stale chunk JSON before rewriting.
The preamble case is simpler — only one output file — but the same principle applies:
do NOT merge or patch an existing `preamble.json`; overwrite atomically (write to
`preamble.json.tmp`, then `rename`) or write directly if the platform guarantees atomic
file write (POSIX: `Path.write_text` is not atomic; use `tmp + rename` to avoid a
reader seeing a half-written file during a re-run).

### Source hash for idempotency check

Compute `SHA-256(main_tex.read_bytes()).hexdigest()` as `source_hash`. Compare against
the `source_hash` stored in existing `preamble.json`. If they match, return early
(no-op). If they differ or the file is absent, (re)extract and overwrite.

---

## 3. External Sources: LaTeX Macro Syntax

### In-scope directives (extract these)

The following are the macro definition forms to extract, per LaTeX2e source:

| Form | Pattern notes |
|---|---|
| `\newcommand{\name}[n][default]{body}` | Optional args `[n]` and `[default]` both optional |
| `\renewcommand{\name}[n][default]{body}` | Same syntax as `\newcommand` |
| `\providecommand{\name}[n][default]{body}` | Same syntax; milestone brief omits it but it should be included — mathematicians use it |
| `\DeclareMathOperator{\name}{text}` | From `amsmath`; may also appear as `\DeclareMathOperator*` |
| `\def\name{body}` | TeX primitive; no optional-arg syntax |
| `\let\name=\other` (or `\let\name\other`) | TeX primitive; assigns one token to another |
| `\edef\name{body}` | Expanding def; treat same as `\def` for extraction purposes |
| `\xdef\name{body}` | Global expanding def; treat same as `\def` |

### Out-of-scope directives (do not extract)

- Full macro expansion (applying macros to `body_text`) — explicitly Tier 2.
- `\DeclareRobustCommand` — rare, omit for Tier 0.
- `\newenvironment`, `\renewenvironment` — environment definitions, not notation macros.
- `\usepackage`, `\RequirePackage` — not macro definitions.
- Nested `\newcommand` inside `\newcommand` body — bodies are captured verbatim, not recursed.

### Comment stripping

LaTeX comments: `%` to end-of-line, **unless preceded by `\`** (i.e., `\%` is a literal
percent sign, not a comment). Strip from unescaped `%` to `\n`, inclusive.
Correct regex: `(?<!\\)%[^\n]*`. Note: `\\%` is backslash then `%` comment — the
look-behind must cover only a single backslash. In Python:
```python
re.sub(r'(?<!\\)%[^\n]*', '', line)
```

### Multi-line continuations

LaTeX macro bodies can span multiple lines. The body brace `{...}` is balanced —
the definition does not end until the braces balance. To extract the full body:
- After matching the opening keyword + command name + optional `[n][default]`,
  count brace depth to find the closing `}`.
- A single-pass character walk is more reliable than a regex for brace-balanced
  extraction.

**Recommendation:** Extract only directives whose opening keyword (`\newcommand`, etc.)
appears on a single line (i.e., no line-continuation before the first `{`). Capture
from the keyword to the end of the brace-balanced body, which may span multiple lines.
Strip internal newlines + collapse whitespace after extraction to produce the normalized
single-line string stored in `macros`.

### Whitespace normalization

After comment stripping and brace-balanced extraction, normalize each macro line:
`re.sub(r'\s+', ' ', macro_line).strip()`. This produces the canonical single-line form.

### Sorting and deduplication

Sort `macros` lexicographically (`sorted()`). Deduplicate with `dict.fromkeys()` (preserves
insertion order before sort, but sort is the final step). Join with `"\n"` to form
`preamble_text`.

---

## Open Questions

None that are blocking. The design is fully specified by the milestone brief and the
codebase context. One implementation choice the implementer should record explicitly:

1. **Import `find_main_tex` from `tools/arxiv_fetch.py` vs. re-implement.** Recommendation:
   import directly. If the tools/ package is not in the ingest package's import path at
   runtime, copy the function into `ingest/preamble.py` verbatim with a comment citing
   the source. Do not silently diverge.

2. **`\providecommand` inclusion.** The milestone brief lists `\newcommand`, `\renewcommand`,
   `\DeclareMathOperator`, `\def`, `\let`. Recommend including `\providecommand` anyway
   since it is semantically equivalent to `\newcommand` and appears frequently in math.AG
   papers. If the acceptance test fixture does not include it, add it to the fixture.

---

## External Writes the Implementation Will Require

- `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` — one file per seed paper
  (50 files on first full run). Within the project's gitignored `var/` area.
- `var/arxmcp/ops/parser-failures/preamble.log` — TSV failure log. Also within `var/`.
- `ingest/preamble.py` — new source file, committed to the repo.
- `ingest/preamble_types.py` — new source file, committed to the repo.
- `tests/test_preamble.py` — new test file, committed to the repo.
- Updated `ingest/chunker.py` — source modification, committed to the repo.
- A fixture `.tex` file at `tests/fixtures/preamble/` (new subdirectory, committed).

No external pushes, PRs, tickets, infra mutations, or third-party API calls are required.
All writes are local filesystem within the project.

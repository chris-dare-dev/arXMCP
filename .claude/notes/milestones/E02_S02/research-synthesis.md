# Research Synthesis — E02_S02 Preamble extractor

Both researchers converged on every load-bearing decision. No disagreements to surface.

## Load-bearing constraints

From `04-parsing-and-chunking.md` § Preamble extraction (cited by both briefs).

From `05-storage-and-indexing.md` and the chunker's existing `preamble_ref: str | None` field:
> "Reserved for E02_S02 (reference to the per-paper preamble chunk). Written as None by this milestone."

From `08-security-observability-ops.md` § BP1 byte-identical caching: every byte the embedder consumes must be reproducible bit-for-bit across runs. The preamble feeding into `embedding_input = preamble_text + "\n\n" + body_text` (per E03_S01 spec) is on this critical path.

## Architecture (consensus)

1. **Import `find_main_tex` from `tools/arxiv_fetch.py`** — do NOT reimplement. The heuristic priority is: `<paper_id>.tex` > unique `.tex` > first containing `\documentclass` (in first 4096 bytes) > `candidates[0]`.
2. **Reuse `_validate_paper_id` and `InvalidPaperIDError`** from `ingest/chunker.py` (closes F2-equivalent at this layer too — security baseline).
3. **Reuse `_sanitize_log_field`** for TSV failure log fields.
4. **Define `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)`** locally, mirroring chunker.py. Don't catch programmer bugs.
5. **TSV failure log:** `var/arxmcp/ops/parser-failures/preamble.log`. Format `<paper_id>\tfail\t<elapsed_s:.1f>\t<message>`.
6. **Atomic write:** `preamble.json.tmp` then `os.replace` to `preamble.json`. Avoids readers seeing half-written file mid-rerun.
7. **Source-hash idempotency:** compute `SHA-256(main_tex.read_bytes()).hexdigest()` as `source_hash`. If existing `preamble.json` has matching `source_hash`, return cached `PreambleDoc` (no-op). Otherwise overwrite.

## Macro syntax scope

**In-scope (extract):**

| Form | Notes |
|---|---|
| `\newcommand{\name}[n][default]{body}` | optional `[n]`, `[default]` |
| `\renewcommand{\name}[n][default]{body}` | same syntax |
| `\providecommand{\name}[n][default]{body}` | both briefs recommend including despite milestone brief omission — extremely common in math preprints |
| `\DeclareMathOperator{\name}{text}` and `\DeclareMathOperator*{...}` | from amsmath |
| `\def\name{body}`, `\edef\name{body}`, `\gdef\name{body}`, `\xdef\name{body}` | TeX primitives. Briefs recommend including all four variants. |
| `\let\name=\other` or `\let\name\other` | optional `=` |

**Out-of-scope (do not extract or follow):**

- Macro expansion / body evaluation (Tier 2)
- `\DeclareRobustCommand`, `\newenvironment`, `\renewenvironment`
- `\usepackage`, `\RequirePackage`
- `\input{}`/`\include{}` chasing — root `.tex` only at Tier 0
- `.sty`/`.cls` files
- Nested `\newcommand` inside `\newcommand` body — capture verbatim, do not recurse

## Comment stripping

`%` to end-of-line, BUT `\%` is escaped (literal percent). Counting consecutive preceding backslashes: odd → escaped, even (incl. zero) → comment. A character-by-character scan is correct; a naive `re.sub(r'(?<!\\)%.*$', ...)` mishandles `\\%` (which IS a comment). Document the limitation if using the simpler regex; both briefs note that imperfect comment stripping on exotic edge cases is acceptable at Tier 0.

## Multi-line body extraction (Option A)

Brace-depth counter scanning character-by-character. After matching the opening `{` of the macro body, increment on `{`, decrement on `}`, stop when depth returns to zero. The full multi-line body becomes a single normalized string after `re.sub(r'\s+', ' ', s).strip()`.

For `\def`/`\let` (no optional args, simpler syntax), greedy single-line matching is fine.

## Determinism

After extraction:
1. `re.sub(r'\s+', ' ', macro).strip()` per macro line.
2. `dict.fromkeys(macros)` to dedupe (preserves insertion order).
3. `sorted(...)` for canonical ordering.
4. `"\n".join(...)` to form `preamble_text`.
5. `preamble_hash = SHA-256(preamble_text.encode("utf-8")).hexdigest()[:16]`.

`preamble_ref` written into each chunk JSON equals `preamble_hash` by construction.

## Chunker integration

Modify `ingest/chunker.py` to:
1. Call `extract_preamble(paper_id)` once per paper at the top of `_chunk_paper_impl`.
2. On a `PER_PAPER_FAILURE_EXCEPTIONS` from preamble extraction OR a missing preamble doc, fall back to `preamble_ref=None` (the chunker still emits chunks, just without the preamble reference). Log at WARN level.
3. Otherwise populate `preamble_ref=preamble_doc.preamble_hash` on every emitted ChunkRecord.

## Open questions

None that block implementation. The implementer must:

1. **Confirm `from tools.arxiv_fetch import find_main_tex` resolves at runtime.** Both briefs flag this — `ingest/` doesn't currently import from `tools/`. The current `pyproject.toml` doesn't declare a `tool.setuptools.packages` (which is why E02_S01 had install issues), but `tools/` and `ingest/` are sibling top-level packages. A simple `from tools.arxiv_fetch import find_main_tex` should work given the project layout.

## External writes

| type | target | why |
|---|---|---|
| filesystem write | `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` (×50 papers) | extractor output; gitignored |
| filesystem write | `var/arxmcp/ops/parser-failures/preamble.log` | TSV failure log; gitignored |
| filesystem write | `ingest/preamble.py`, `ingest/preamble_types.py`, `tests/test_preamble.py`, `tests/fixtures/preamble/<fixture>.tex` | new source/test files; committed |
| filesystem write | `ingest/chunker.py` (modified) | wire preamble_ref into emitted chunks; committed |

No pushes, PRs, infra, or third-party API calls.

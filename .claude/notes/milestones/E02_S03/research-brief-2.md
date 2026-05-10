# Research Brief 2 — E02_S03: `body_tokens` Regex Pre-Tokenizer

**Researcher:** Agent B (parallel)
**Date:** 2026-05-07
**Project root:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422`

---

## 1. In-Codebase Context

### Input format: what `body_text` actually contains

`body_text` is produced by `ingest/chunker.py::_element_text()`, which closes
F1 (CRITICAL) by replacing every `<math alttext="...">` element with
`f"${alttext}$"` — single-dollar wrappers. The `alttext` attribute contains
verbatim LaTeX from the original source, e.g. `\mathbb{Z}[x]`. What the
tokenizer will see:

```
'Let $\mathbb{Z}[x]$ be the polynomial ring'
'By \mathrm{Spec}\, R'           # bare command outside $, no math wrapper
'$H^i(X, \mathcal{F})$ for $i > 0$'
```

The bare-command case (`\mathrm{Spec}` outside `$`) appears in the second
acceptance criterion. This is realistic: LaTeXML sometimes emits non-math
command text directly into NavigableString nodes, and the alttext wrapper
is only applied to `<math>` elements. The tokenizer must handle both
`$\cmd{arg}$` (math-wrapped) and `\cmd{arg}` (bare) uniformly.

The simplest correct approach: strip `$` delimiters and process the
resulting text with a single compiled regex sweep. Math and non-math content
have identical tokenization rules.

### The BM25 contract (E04_S04)

From `05-storage-and-indexing.md`: "BM25 over `body_tokens` using Python
`rank_bm25`. The `body_tokens` field is a space-joined token stream produced
at chunk-write time by a Python regex pre-tokenizer (E02_S03) that preserves
backslash tokens like `\Spec`, `mathrm_Pic`, etc. **Standard whitespace
split is all that BM25 needs over pre-tokenized input.**"

From `E04-vector-store.md § E04_S04`: "The `body_tokens` string for each
chunk is split on whitespace to produce the token list." This means
`tokenize_body` must emit a space-joined string — NOT a list. The
`body_tokens` column is typed `string` in the LanceDB schema (E04_S01).

E04_S04 further specifies: the BM25 query "Spec mathrm_Pic" must rank the
expected chunk first. This pinpoints the vocabulary contract: the command
root with its argument, joined by underscore, is the canonical form that
both the tokenizer and query-time tokenization must produce identically.

### `chunker_types.py` field definition

`body_tokens: list[str] | None = field(default=None)` — currently typed as
`list[str] | None`. **This is a schema mismatch with E04_S01.** The LanceDB
schema says `body_tokens` is a `string`. The milestone brief says
`tokenize_body` returns `str`. The implementation must either:

(a) Change the type hint to `str | None` in `chunker_types.py`, or
(b) Store a `str` into a `list[str]`-typed field (wrong; will fail on
    LanceDB insertion at E04_S01).

Option (a) is correct. The `to_dict()` serialization already writes
`body_tokens` as whatever `self.body_tokens` is — changing the field type
fixes it cleanly. **This is a required external write.**

### `preamble.py` module pattern (to replicate)

`ingest/preamble.py` establishes the project's module conventions:
- Module docstring with explicit rejection rationale (analogous to the
  Tantivy rejection this module must document)
- `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)`
- Module-level compiled regexes (e.g. `_BRACED_HEAD_RE`, `_LET_RE`)
- Public API as a single named function with type annotation
- No lazy imports for core logic; lazy imports only for heavyweight dependencies

`ingest/tokenizer.py` must follow this pattern. The compiled regex must be
at module level so it is compiled once and reused across all calls.

### Wire-in point in `chunker.py`

The `_chunk_paper_impl` function in `chunker.py` assembles `all_chunks`, then
stamps `preamble_ref` on each chunk (lines 810-813). The wire-in for
`body_tokens` belongs immediately after this block, before the JSON write
loop at line 824. Pattern:

```python
from ingest.tokenizer import tokenize_body
for chunk in all_chunks:
    chunk.body_tokens = tokenize_body(chunk.body_text)
```

The import must be a lazy import (inside `_chunk_paper_impl` or a helper,
not at module top level) to mirror the preamble pattern and avoid circular
imports. Alternatively, since `tokenizer.py` has no upstream dependencies,
a top-level import is safe here — implementer judgment.

---

## 2. Prior Decisions and Lessons

### H4 closure trail

From `README.md` critique-remediation matrix: "**H4** | Tantivy LaTeX
analyzer vapor → Python regex pre-tokenizer + standard BM25 | E02_S03,
E04_S04". The README is the authoritative location for this closure.

From `05-storage-and-indexing.md`: "**No Tantivy LaTeX analyzer** — Tantivy
ships no such analyzer; the approach was fictional."

The module docstring requirement is literal: "No custom Tantivy LaTeX
analyzer is used; see H4 remediation in `.claude/roadmap/README.md`." The
path `.claude/roadmap/README.md` is the exact string required; do not
paraphrase.

### BP1: byte-identical caching demands determinism

`body_tokens` is now in the chunk schema. Once populated, the JSON at
`var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json` changes. E02_S04
(content-addressable `chunk_id`) hashes `preamble_normalized + body_text`
— NOT `body_tokens`. This is load-bearing: `body_tokens` changes do not
invalidate `chunk_id`. Good design. But it means token vocabulary stability
is a concern only for BM25 index validity, not for chunk identity.

BM25 token vocabulary must be stable across re-runs of the same source text.
The regex must be deterministic (no random iteration, no set ordering). The
`' '.join(tokens)` output must be the same for the same input on any Python
version. Compiled regex `finditer` is inherently deterministic.

### F6 lesson (E02_S02): NFC normalization

`preamble.py` line 422: `tex_source = unicodedata.normalize("NFC", tex_source)`.
This was added to ensure `preamble_hash` is identical across hosts. Does
`body_text` need the same treatment?

Answer: **yes, but it is already handled upstream.** `body_text` is produced
by `_element_text()` which reads `alttext` from BeautifulSoup-parsed HTML.
BeautifulSoup decodes HTML entities but does not normalize Unicode. LaTeXML's
`alttext` preserves the original LaTeX byte sequence; if that source had
decomposed characters (unlikely in LaTeX math), they would flow through.

**Recommendation:** Apply NFC normalization to `body_text` inside
`tokenize_body` before the regex sweep. One line: `body_text =
unicodedata.normalize("NFC", body_text)`. Cost is negligible; correctness is
guaranteed.

### F2 lesson: test suite impact when `body_tokens` becomes non-null

Three tests in `tests/test_chunker.py` explicitly assert `body_tokens is None`:

- Line 162-165: `test_body_tokens_null` in `TestTwoTheoremGolden`
- Line 701: `test_to_dict_null_deferred_fields` in `TestChunkRecord`

After E02_S03 wires `tokenize_body` into `chunk_paper`, these tests will
fail. They must be updated:

- `test_body_tokens_null` → rename to `test_body_tokens_populated` and assert
  `all(chunk.body_tokens is not None for chunk in chunks)` and
  `all(isinstance(chunk.body_tokens, str) for chunk in chunks)`.
- `test_to_dict_null_deferred_fields` → this test calls `ChunkRecord`
  directly without going through `chunk_paper`, so `body_tokens` will remain
  `None` at the dataclass level. **This test does not need to change** — it
  tests the dataclass default, not the chunker wire-in.

The `chunker_version` check (`assert chunk.chunker_version == "v1.0"`) is
unaffected. If E02_S03 does not bump `chunker_version`, no changes there.
E02_S03 should NOT bump the version — that is explicitly E02_S04's job.

---

## 3. External Sources

### Python `re` performance for compiled regexes

Python's `re` module compiles patterns to a bytecode automaton at
`re.compile()` time. Repeated calls to a compiled `Pattern.finditer()` do
not recompile. On CPython 3.11+, a 2000-character `finditer` sweep with a
multi-group alternation pattern runs in approximately 0.05–0.15ms (empirically
verified: 0.095ms for a realistic 2188-char chunk, well under the 1ms target).

The `re` module is implemented in C and is fast enough for this use case
without needing `regex` (the third-party Unicode-aware replacement). Do not
add `regex` as a dependency.

**Key performance rule:** compile the master regex once at module level, not
inside `tokenize_body`. A module-level `_TOKENIZER_RE = re.compile(...)` is
re-entrant and thread-safe (Python's `re` compiled objects are thread-safe).

### Math-aware tokenization: TeX conventions for identifiers

Standard LaTeX math identifiers follow these forms (from LaTeXML alttext):

- `\mathbb{Z}`, `\mathbb{R}`, `\mathbb{Q}` — blackboard bold; argument is
  always a single letter. Canonical token: `mathbb_Z`, `mathbb_R`.
- `\mathrm{Spec}`, `\mathrm{Hom}`, `\mathrm{End}` — roman font; argument is
  often a multi-letter operator name. Canonical token: `mathrm_Spec`.
- `\mathcal{F}`, `\mathscr{L}` — calligraphic/script; argument always a
  single capital. Canonical token: `mathcal_F`.
- `H^i`, `H^{n+1}`, `H_1`, `H_{ij}` — identifiers with superscripts and
  subscripts. Canonical token: `H_i`, `H_n` (subscripts only, simple
  alphanumeric). Complex sub/superscripts like `n+1` should be tokenized as
  `H` (drop complex subscript) or `H_n_1` (tokenize each component). The
  brief says "joined with underscores"; recommend tokenizing only
  simple alphanumeric subscripts: `H_{ij}` → `H_ij`, `H^{n+1}` → `H` or
  `H_n` (implementer judgment — see Open Questions).
- `\partial`, `\nabla`, `\Delta` — standalone commands with no argument.
  Canonical token: `partial`, `nabla`, `Delta`.

### BM25 best practices for pre-tokenized input

`rank_bm25.BM25Okapi` (the library specified in E04_S04) tokenizes documents
by calling `tokenizer(doc)` where `tokenizer` defaults to `str.split`. Over
a pre-tokenized space-joined string, `split()` is exact — no stemming, no
lowercasing, no stopword removal. This is intentional per E04_S04:
"Standard English tokenization (split on whitespace, lowercase, no stemming)
is applied over the `body_tokens` field."

**Critical implication:** BM25 at E04_S04 will split on whitespace and does
NOT lowercase. If `tokenize_body` emits `Spec` (capital S), BM25 will
distinguish `Spec` from `spec`. Query tokenization at E07_S01 must apply
the same split. Recommend: do NOT lowercase in the tokenizer — preserve
case as emitted by LaTeX (e.g. `mathrm_Spec` not `mathrm_spec`). The query
path must mirror this.

Token vocabulary stability across corpus updates matters because BM25 IDF
is computed over the entire corpus vocabulary. Adding new papers shifts
IDF weights slightly but does not invalidate the index — it just needs
rebuilding (E04_S04 is idempotent on re-run). Since `body_tokens` values
are deterministic for fixed `body_text`, corpus IDF is stable for fixed
paper sets.

---

## Open Questions

1. **`\mathbb{Z}` arg extraction limit:** The arg inside `\mathbb{}` is
   always a single letter in practice. But `\mathrm{Spec}` has a multi-letter
   arg. The regex for "simple arg" must decide which args to join with
   underscore vs. drop. Recommendation: join if arg matches `[A-Za-z\d]+`
   (letters and digits only, no spaces or operators). This produces
   `mathrm_Spec` and `mathbb_Z` correctly and drops `cite_hartshorne_1977`
   (too complex) down to `cite`.

2. **Superscript handling:** `H^{n+1}` — should this emit `H` or `H_n_1`?
   The brief says subscripts and superscripts are "joined with underscores."
   But `n+1` is a math expression, not a simple identifier. Recommend: emit
   `H` alone when the superscript content is non-alphanumeric. The BM25 miss
   is acceptable; recall loss on exotic super/subscripts is in-scope per the
   risk notes.

3. **NFC normalization location:** Should `tokenize_body` apply NFC, or
   should the chunker apply NFC to `body_text` before writing it? The latter
   would also fix `body_text` for the embedder. Recommend applying NFC in
   `tokenize_body` only, to keep `body_text` byte-identical to what
   `_element_text` produced (no silent mutation of the stored field).

4. **`chunker_types.py` type fix:** `body_tokens: list[str] | None` must
   become `str | None`. Does this count as a schema change requiring a
   `chunker_version` bump? Answer: No — the JSON serialization via `to_dict()`
   is unchanged (it writes whatever the field holds). The Python type hint
   change is internal. E02_S04 handles version bumping.

5. **`\, ` handling:** LaTeX `\,` is a thin-space command. The tokenizer will
   emit `,` as `None` (not a word) and the backslash-alone form — unless the
   regex explicitly skips single-character non-alpha commands. Recommendation:
   limit command extraction to `[A-Za-z]{2,}` or `[A-Za-z]+` — the current
   spec says `[A-Za-z@]+` which would emit `,` as a token root for `\,`. The
   regex must handle `\,`, `\;`, `\!`, `\.` gracefully by either skipping
   them or emitting nothing (since they produce empty or non-alpha tokens).
   With `[A-Za-z@]+` requiring at least one letter, `\,` won't match — safe.

6. **Duplicate token emission:** `$\mathbb{Z}$ and $Z$` emits `mathbb_Z and Z`.
   The `Z` in `mathbb_Z` and the standalone `Z` are different tokens — good.
   No deduplication is needed in the token stream (BM25 handles term
   frequency naturally).

---

## External Writes the Implementation Will Require

Local file system writes only (no network, no external APIs):

1. **Create `ingest/tokenizer.py`** — new module with `tokenize_body(body_text: str) -> str`, module-level compiled regex, module docstring per spec.

2. **Edit `ingest/chunker.py`** — add `tokenize_body` import and wire-in call
   after `preamble_ref` stamping, before JSON write loop.

3. **Edit `ingest/chunker_types.py`** — change `body_tokens: list[str] | None`
   to `body_tokens: str | None` to match the LanceDB schema and milestone spec.

4. **Edit `tests/test_chunker.py`** — update `test_body_tokens_null`
   (lines 162-165) to assert non-null populated string after wire-in; leave
   `test_to_dict_null_deferred_fields` unchanged (tests the dataclass default,
   not the chunker pipeline).

5. **Create `tests/test_tokenizer.py`** — unit tests for the two acceptance
   criterion inputs plus edge cases and a performance timing assertion
   (documented in test per spec).

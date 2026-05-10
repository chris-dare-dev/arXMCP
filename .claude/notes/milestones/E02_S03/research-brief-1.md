# E02_S03 Research Brief 1 — `body_tokens` regex pre-tokenizer

**Milestone:** E02_S03  
**Researcher:** Agent A (parallel)  
**Date:** 2026-05-07  

---

## 1. In-codebase context

### The `body_tokens` field today

`chunker_types.py` declares:

```python
body_tokens: list[str] | None = field(default=None)
```

with the comment `"Reserved for E02_S03 (BM25 token list). Written as None by this milestone."` The existing test at line 162–165 of `tests/test_chunker.py` explicitly asserts `chunk.body_tokens is None` — that assertion will break the moment E02_S03 wires `tokenize_body` into the chunker. The implementer must update `test_body_tokens_null` (or replace it with a positive-content test) and must verify that `test_output_json_has_required_fields` still passes (it already lists `"body_tokens"` in `required`).

Critical schema observation: the E04_S01 schema in the roadmap lists `body_tokens` as type `string` (not `list<string>`), and E04_S04 splits `body_tokens` on whitespace at BM25-index time: `"The body_tokens string for each chunk is split on whitespace to produce the token list."` The `ChunkRecord.body_tokens` field is typed `list[str] | None`, but it is serialized as `body_tokens` via `to_dict()` — which will write a JSON array. **This is a schema mismatch**: E04_S01 and E04_S04 expect a `string` (space-joined); the Python type annotation says `list[str]`. The milestone spec says `tokenize_body(…) -> str` and "whitespace-joined token stream stored in the `body_tokens` field." The implementer must decide whether `body_tokens` on `ChunkRecord` changes to `str | None`, or whether `to_dict()` joins the list into a string before writing JSON. Downstream (E04_S04) reads the JSON field and whitespace-splits it — so either representation works at the Python level, but the on-disk JSON must be a string, not an array, to match the LanceDB column type.

### What `body_text` contains after E02_S01

E02_S01's `_element_text()` function (lines 262–282 of `chunker.py`) replaces every `<math alttext="…">` element with `$alttext$`. So `body_text` for a chunk like "Theorem 3.4. Let $X$ be..." contains verbatim LaTeX inside `$…$` delimiters, e.g.:

```
Theorem 3.4. Let $X$ be a smooth projective variety over $\mathbb{C}$...
```

The tokenizer sees `$...$`-wrapped LaTeX including command names with backslashes (`\mathbb`, `\mathrm`, `\partial`, etc.), subscript/superscript notation (`H^1`, `_n`, `\mathbb{Z}[x]`), and prose. The dollar-sign delimiters are noise that must be stripped or ignored.

### BM25 contract (E04_S04)

The BM25 consumer at E04_S04 does only `body_tokens.split()` — no further processing. Therefore whatever tokens the pre-tokenizer produces are the exact vocabulary BM25 will see. The roadmap notes test query `"Spec mathrm_Pic"` — confirming that the underscore-joined form (`mathrm_Pic`) must appear literally as a token in `body_tokens`. The `05-storage-and-indexing.md` hybrid search description says: "BM25 over `body_tokens`… The `body_tokens` field is a pre-tokenized stream (E02_S03) that preserves backslash tokens like `\Spec`, `mathrm_Pic`, etc."

Wait: the note says `\Spec` (with backslash) but also `mathrm_Pic` (without backslash). This is internally consistent with the milestone spec: backslashes are stripped from LaTeX command names, so `\mathrm{Pic}` → `mathrm_Pic`. But `\Spec` as a standalone command → `Spec`. This confirms the tokenization rule: strip the leading backslash from all command names.

### Established module patterns from `preamble.py`

`preamble.py` sets the module pattern to follow:
- Module-level docstring with explicit design rationale (including what is rejected and why)
- Constants defined at module level with a single compiled regex (pattern from `_BRACED_HEAD_RE = re.compile(...)`)
- `PER_PAPER_FAILURE_EXCEPTIONS` tuple for resilience — not needed in `tokenizer.py` (it's pure function), but the docstring pattern must be matched
- NFC normalization applied to source text before regex processing

The milestone spec mandates a module docstring stating: "No custom Tantivy LaTeX analyzer is used; see H4 remediation in `.claude/roadmap/README.md`."

---

## 2. Prior decisions and lessons

### H4 closure trail

The README.md remediation matrix records: `H4 | Tantivy LaTeX analyzer vapor → Python regex pre-tokenizer + standard BM25 | E02_S03, E04_S04`. The `05-storage-and-indexing.md` BM25 entry says: "**No Tantivy LaTeX analyzer** — Tantivy ships no such analyzer; the approach was fictional. See E02_S03 / E04_S04." H4 is fully closed only when both milestones ship — E02_S03 produces the token stream; E04_S04 indexes it. This milestone's module docstring must be the permanent record of that decision.

### BP1 and determinism

`chunker.py`'s docstring says "Output bytes are reproducible. Dict keys are sorted before JSON serialisation. No timestamps, no random content." The tokenizer must be fully deterministic — same input text, same token string, every time, on every platform. A compiled `re.compile(pattern)` at module load is both correct (deterministic) and fast. The regex must not depend on locale, Python version-specific regex extensions, or match ordering that could vary. The `re` module's `re.compile` is deterministic for a fixed pattern on a fixed CPython version — the compiled pattern is module-level state initialized once.

### NFC lesson from E02_S02 (F6)

`preamble.py` line 422: `tex_source = unicodedata.normalize("NFC", tex_source)` — applied before processing. The same normalization is needed in `tokenizer.py`. The `body_text` field that E02_S01 writes may contain Unicode characters (accented letters in author names appearing in prose, Unicode math symbols leaking through when `alttext` is absent). NFC normalization before tokenization ensures `é` (precomposed U+00E9) and `e` + combining accent (U+00E9 decomposed) produce the same token. Without NFC, two corpora built on different platforms could diverge in vocabulary — breaking BP1.

### F2 cache-corruption lesson (schema breakage)

The F2 lesson from E02_S02 was: a corrupt cache whose field type doesn't match the expected type silently produces wrong results. Here: the `body_tokens` type mismatch (`list[str]` in Python vs `string` in LanceDB schema) is the same class of risk. If the JSON is written as an array and E04_S04 tries to `body_tokens.split()` on a deserialized Python list, it will raise `AttributeError`. The fix must be deliberate: either change the `ChunkRecord` annotation to `str | None` or change `to_dict()` to join the list. The test at line 701 (`assert d["body_tokens"] is None`) must be updated.

### Existing test surface reaction to non-null `body_tokens`

The test `test_body_tokens_null` at line 162–165 asserts `None`. When the tokenizer is wired in, this test fails. The implementer must update it. The acceptance criterion "Running the chunker on all 50 seed papers produces non-null `body_tokens` on every chunk" implies a new integration-level test or a check in the existing chunker test's output-file assertion.

---

## 3. External sources

### Python `re` performance for compiled regexes

Python's `re.compile()` builds a DFA/NFA in C; compiled pattern objects cache their internal representation. On CPython 3.10+, a `re.findall` or `re.sub` over a 4 KB string (typical 512-token chunk `body_text`) runs in under 50 µs on modern hardware — well within the 1 ms budget. The key is to compile the pattern **once at module load**, not inside `tokenize_body`. The current codebase already uses this pattern correctly: `_THEOREM_CLASS_RE = re.compile(…)` in `chunker.py`, `_BRACED_HEAD_RE = re.compile(…)` in `preamble.py`. The tokenizer must follow suit.

The recommended approach for math-aware tokenization is a single `re.findall(PATTERN, text)` pass, not multiple `re.sub` calls. A `findall` with alternation is O(n) in the text length; multiple passes over the same text multiply the constant factor unnecessarily.

### Math-aware tokenization for LaTeX corpora

The standard reference for LaTeX identifier structure is the TeXBook (Knuth, 1984): control sequences are formed by a backslash followed by one or more letters (`[A-Za-z]+`), or a backslash followed by a single non-letter. For math-mode identifiers, the relevant forms are:

- `\mathbb{X}` — blackboard bold; argument is always 1–2 uppercase letters
- `\mathrm{Name}` — roman face; argument is an identifier
- `\mathcal{F}`, `\mathscr{G}`, `\mathfrak{g}` — calligraphic, script, fraktur
- `H^{i}`, `H_n`, `\pi_1(X)` — superscript/subscript on base identifiers

For the E02_S03 tokenizer, the approach recommended by the milestone spec is:
1. Match `\command{arg}` → emit `command_arg` (strip backslash, join command name and argument with underscore)
2. Match standalone `\command` → emit `command` (strip backslash)
3. Match `base_sub` or `base^sup` identifier fragments → emit `base_sub` or `base_sup`
4. Match plain Latin words (including hyphenated compounds) → emit as-is

The underscore join for `\mathrm{Spec}` → `mathrm_Spec` is confirmed by the acceptance criterion and the E04_S04 test query `"Spec mathrm_Pic"`. Note that `Spec` also appears as a standalone token — both the plain identifier and the `mathrm_Spec` compound should be emitted.

For BM25 token vocabulary stability across versions: any change to the tokenizer regex produces a different vocabulary, invalidating all existing BM25 index files. This is a `chunker_version` bump — exactly as documented in `04-parsing-and-chunking.md` § Chunker versioning. The tokenizer version should be considered part of `chunker_version`.

### BM25 best practices for pre-tokenized input

`rank_bm25.BM25Okapi` (the library named in E04_S04) expects a list of token lists. When `body_tokens` is a space-joined string, E04_S04 does `body_tokens.split()` to get the token list. This means:
- Token separators must be exactly single spaces (no tabs, no newlines in the output string)
- Duplicate tokens within a chunk are fine — BM25 weights by term frequency
- Lowercasing is **not** applied by the pre-tokenizer; E04_S04 says "no stemming" and doesn't mention lowercasing. The roadmap query `"Spec mathrm_Pic"` uses mixed case — preserving case is intentional for math identifiers (`Z` vs `z` are different objects in algebra)

---

## Open questions

1. **`list[str]` vs `str` on `ChunkRecord.body_tokens`**: The Python type annotation says `list[str]` but the LanceDB schema and E04_S04 usage requires a `string`. Should the implementer change `ChunkRecord.body_tokens` to `str | None` (cleanest) or keep `list[str]` and join in `to_dict()`? The former is cleaner and matches the function signature `tokenize_body(…) -> str`. Recommendation: change the annotation to `str | None`.

2. **Dollar-sign handling**: `body_text` contains `$...$` around math regions. Should the `$` delimiters themselves be emitted as tokens, stripped silently, or treated as token separators? Stripping silently (treating `$` as non-token punctuation) is the correct choice — dollar signs are syntax, not vocabulary.

3. **Subscript/superscript notation for multi-character scripts**: `H_1` → `H_1` is clear. What about `H_{ij}` or `T^{ab}`? The braces contain multi-char subscripts. The milestone spec says "Subscripts and superscripts are joined with underscores to preserve token identity" — so `H_{ij}` → `H_ij` (stripping braces). What about `H_{i,j}` with a comma? Emit `H_i` and `H_j` as separate tokens, or `H_i,j`? Recommend: strip braces and non-alphanumeric-underscore characters, producing `H_ij`.

4. **NFC normalization scope**: Apply NFC to `body_text` inside `tokenize_body`, or document that callers must pre-normalize? The preamble does normalization at extraction time. For the tokenizer, normalizing inside the function makes it self-contained and testable in isolation. Recommend: normalize inside `tokenize_body` at the top of the function.

5. **Token deduplication**: Should the output token stream deduplicate adjacent identical tokens? BM25 weights by term frequency, so duplicates are meaningful — do not deduplicate.

6. **Minimum token length**: Should one-character tokens like `X` or `Z` be included? Yes — in algebra, single-letter identifiers are semantically significant (`Z` = integers, `X` = variety). Do not apply a minimum-length filter.

7. **`chunker_version` bump**: Adding `body_tokens` as non-null changes chunk output. Does this require a version bump from `v1.0`? The existing `chunker_version = "v1.0"` default must be bumped (to `"v1.1"`) because the on-disk chunk JSON now has non-null `body_tokens`. This affects E02_S04's content-addressable hashing (different bytes → different hash). Decision needed from the implementer.

---

## External writes the implementation will require

1. **New file**: `ingest/tokenizer.py` — `tokenize_body(body_text: str) -> str` plus module docstring with H4 closure statement
2. **Modified file**: `ingest/chunker.py` — import `tokenize_body` from `ingest.tokenizer`, call it on `body_text` before appending to `all_chunks`, assign to `chunk.body_tokens`
3. **Modified file**: `ingest/chunker_types.py` — change `body_tokens: list[str] | None` to `body_tokens: str | None` (to match the LanceDB schema string type and function return type)
4. **New file**: `tests/test_tokenizer.py` — unit tests for known LaTeX input → expected token stream pairs (acceptance criterion pairs from the milestone spec)
5. **Modified file**: `tests/test_chunker.py` — update `test_body_tokens_null` (which currently asserts `None`) to assert non-null string after the wire-in; optionally add a content assertion to `test_output_json_has_required_fields`
6. **State file**: `.claude/notes/milestones/E02_S03/state.json` — milestone completion state

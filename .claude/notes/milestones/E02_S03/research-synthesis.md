# Research Synthesis — E02_S03 body_tokens regex pre-tokenizer

Both researchers converged. The implementation surface is unambiguous; the
disagreements are minor (one-line) and resolved below.

## Load-bearing constraints

From `05-storage-and-indexing.md` § BM25:
> "BM25 over `body_tokens` using Python `rank_bm25`. The `body_tokens` field is a space-joined token stream produced at chunk-write time by a Python regex pre-tokenizer (E02_S03) that preserves backslash tokens like `\Spec`, `mathrm_Pic`, etc. Standard whitespace split is all that BM25 needs over pre-tokenized input."

From `E04-vector-store.md § E04_S04`:
> "The `body_tokens` string for each chunk is split on whitespace to produce the token list."

The on-disk JSON `body_tokens` is therefore a **whitespace-joined string**, not a JSON array. `tokenize_body(...) -> str`.

## Schema fix required

Both briefs flagged: `chunker_types.py` declares `body_tokens: list[str] | None = field(default=None)` but the LanceDB schema (E04_S01) and the function return type are `str`. **Required edit:** change the annotation to `str | None`. The `to_dict()` serialisation is unchanged — it just writes a string instead of a list now.

## Existing test impact

`tests/test_chunker.py` has at least one explicit `assert chunk.body_tokens is None` that will break the moment the chunker wire-in lands. Rename or rewrite to `assert isinstance(chunk.body_tokens, str)`. R2's specific call-out: `test_to_dict_null_deferred_fields` constructs `ChunkRecord` directly without going through `chunk_paper`, so the dataclass-default `None` is unaffected — leave that test alone.

## Architecture (consensus)

**Module:** `ingest/tokenizer.py`. Single public function `tokenize_body(body_text: str) -> str`. Module-level compiled regex (compile once, reuse on every call). Module docstring states verbatim: `"No custom Tantivy LaTeX analyzer is used; see H4 remediation in `.claude/roadmap/README.md`."`

**Wire-in point:** `ingest/chunker.py::_chunk_paper_impl`, after the `preamble_ref` stamp loop, before the JSON write. Both briefs agree top-level import is safe (no circular dependency since `tokenizer.py` has no upstream deps).

**Tokenization rules (composite from both briefs):**

1. NFC-normalize the input (one `unicodedata.normalize("NFC", text)` at the top of `tokenize_body`). Mirrors F6 fix from E02_S02.
2. Strip `$...$` math delimiters first (treat `$` as syntax, not vocabulary).
3. Match in a single `re.findall` alternation pass:
   - `\command{arg}` where arg is `[A-Za-z0-9]+` → emit `command_arg` (strip backslash, underscore-join). Examples: `\mathbb{Z}` → `mathbb_Z`, `\mathrm{Spec}` → `mathrm_Spec`.
   - Bare `\command` (where command is `[A-Za-z@]+`) → emit `command` (strip backslash). Examples: `\partial` → `partial`, `\Spec` → `Spec`.
   - Identifier with subscript: `X_a`, `H_1`, `H_{ij}` → emit `X_a`, `H_1`, `H_ij` (strip braces, single-pass underscore join). For complex non-alphanumeric subscript content (`H^{n+1}`, `H_{i,j}`), emit just the base identifier (`H`); recall loss on exotic notation is acceptable per the milestone risk notes.
   - Plain Latin word `[A-Za-z][A-Za-z\-]*` → emit as-is (preserves hyphenated compounds).
4. Do NOT lowercase. Math identifiers are case-significant (`Z` ≠ `z`).
5. Do NOT deduplicate. BM25 weights by term frequency.
6. Do NOT apply minimum length. Single-letter math identifiers (`X`, `Z`) are semantically meaningful.
7. Skip command-name regex matches that produce empty strings (e.g. `\,`, `\;`, `\!` thin spaces); the `[A-Za-z@]+` requirement on command name handles this naturally.

The output is `" ".join(tokens)` — single spaces between tokens, no trailing newline.

## Performance

Module-level `_TOKENIZER_RE = re.compile(...)`. R2 measured 0.095ms/chunk on a realistic 2188-char input — well within the 1ms budget. Add a perf assertion in the test suite (`pytest tests/test_tokenizer.py::TestPerformance::test_under_1ms`).

## Don't bump `chunker_version`

R1 raised the question; R2 resolved it correctly: `chunker_version` bumping is **explicitly E02_S04's job**. E02_S03 only populates a previously-null field; the chunk_id placeholder format is unchanged. Keep `chunker_version = "v1.0"`.

## Open questions (resolved by synthesis above; no implementer judgment required)

- Dollar-sign handling: strip silently as syntax. ✓
- Subscript notation: simple alphanumeric (`H_ij`); drop complex (`H^{n+1}` → `H`). ✓
- NFC location: inside `tokenize_body`, top of function. ✓
- Type fix: `str | None` on `ChunkRecord.body_tokens`. ✓
- Don't lowercase. ✓
- Don't deduplicate. ✓
- No minimum length. ✓
- Don't bump chunker_version. ✓

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write | `ingest/tokenizer.py` | new module; committed |
| filesystem write | `ingest/chunker_types.py` | type annotation fix; committed |
| filesystem write | `ingest/chunker.py` | wire-in `tokenize_body` call; committed |
| filesystem write | `tests/test_tokenizer.py` | unit tests; committed |
| filesystem write | `tests/test_chunker.py` | update `test_body_tokens_null`; committed |

No pushes, no PRs, no infra mutation, no third-party API calls.

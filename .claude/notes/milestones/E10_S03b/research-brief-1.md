# Research Brief 1 — E10_S03b: Equation Extractor + embedding_eq Populator

## 1. In-codebase context

### LaTeXML HTML storage and file structure

LaTeXML output is stored at `var/arxmcp/corpus/parsed/<paper_id>/index.html`
(confirmed by `ingest/chunker.py::_chunk_paper_impl` line 816:
`parsed_html = PARSED_DIR / paper_id / "index.html"`). The seed corpus
HTML is not present in the worktree (no `var/` data committed), but the
chunker's own HTML-walking code is the ground truth for the format.

### chunker.py HTML walking

`chunk_paper` reads the full HTML via
`BeautifulSoup(html_bytes, "html.parser")` (builtin Python parser, no
lxml dependency needed). The `_element_text` function is the critical
reference for equation handling:

```python
if node.name == "math":
    alttext = node.get("alttext")
    if alttext:
        parts.append(f"${alttext}$")
        return
```

LaTeXML emits `<math alttext="...">` where the `alttext` attribute
contains the original LaTeX source (whitespace-normalized). **This
is `presentation_latex`.** The chunker already extracts it for
`body_text` embedding — the extractor just needs to capture it
as a first-class record field.

Section tracking uses `_extract_section_path(tag)` which walks
ancestors for `<section class="ltx_section">` etc. and extracts
heading text from `<h1-h6 class="ltx_title">` children.

Display equations in LaTeXML HTML5 output appear as:
- Single `\begin{equation}`: `<table class="ltx_equation ltx_eqn_table"><tr><td class="ltx_eqn_cell ltx_eqn_center_padright"><math alttext="...">...</math></td><td class="ltx_eqn_cell ltx_eqn_eqno"><span class="ltx_tag ltx_tag_equation">(3.7)</span></td></tr></table>`
- The `<span class="ltx_tag ltx_tag_equation">` carries the label string.

Inline math (`$x = y$`) also becomes `<math alttext="x = y">` but
has no surrounding equation table and no label.

### embedder.py shape

`_encode_batch(texts, chunk_ids)` is the sync batched encoder.
`EMBED_BATCH_DEFAULT = 32`. It calls `_get_model()` and `_get_tokenizer()`
(both lazy-loaded singletons). The equation embedder can reuse
`_encode_batch` directly — same batch size, same model, same L2
normalization. The embedder lives in `ingest/embedder.py` and is
importable from `ingest.embedder`. **No new model or encoder needed.**

`server/query_encoder.py::_encode_query_sync` is the single-query
async path — wrong for batch ingest. Use `_encode_batch` directly.

### store.py write pattern

`write_chunks` uses `merge_insert(on="chunk_id")` for upserts. The
equations table should follow the same `merge_insert(on="equation_id")`
pattern. `index_equations.py::open_or_create_equations_table` already
handles table creation idempotently and uses `merge_insert("equation_id")`
for tree-JSON updates. The equation embedder can reuse
`open_or_create_equations_table` and apply a second `merge_insert` pass
for `embedding_eq`. **No new write pattern needed — follow the indexer's
approach exactly.**

### identifiers.py content-address scheme

`chunk_id = "arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>"`

For `equation_id`, the natural parallel is:
`"arxiv:<paper_id>:eq:<sha256(NFC(presentation_latex))[:12]>"` or a
simpler counter-based form `"arxiv:<paper_id>:eq<N>"`. The counter form
is **recommended for v1** — display equations per paper are typically
<100, so a 0-padded sequential index within a paper suffices. This
avoids the NFC/collision discipline overhead for v1.

### EQUATIONS_SCHEMA_V1 column inventory

From `ingest/schema.py` (lines 191–208):
- `equation_id` utf8 NOT NULL
- `paper_id` utf8 NOT NULL
- `label` utf8 NULLABLE (equation label string, e.g. "(3.7)")
- `presentation_latex` utf8 NOT NULL (from `alttext`)
- `mathml` utf8 NOT NULL (inner MathML as serialized string)
- `ascii_form` utf8 NULLABLE
- `context_sentence` utf8 NULLABLE
- `parent_chunk_id` utf8 NULLABLE
- `mathml_tree_json` utf8 NULLABLE (populated by `index_equations.py`)
- `embedding_eq` list<float32>[1024] NULLABLE

### EquationIndex._dense_candidates: required change

Current (lines 453–506): the ANN pass queries `chunks.embedding_stmt`,
then joins against `equations` via `parent_chunk_id`. When `embedding_eq`
is populated on the equations table, the dense pass should query
`equations.embedding_eq` directly instead.

Required change: add a check before the ANN pass —
```python
# Check whether embedding_eq is populated
sample = self._equations.search().limit(1).to_arrow()
has_eq_embeddings = (
    sample.num_rows > 0
    and sample.column("embedding_eq").null_count < sample.num_rows
)
if has_eq_embeddings:
    # query equations.embedding_eq directly
    # retrieval_mode = "ted_fused_eq"
else:
    # legacy proxy via chunks.embedding_stmt
    # retrieval_mode = "ted_fused" (existing path)
```

### Handler dispatch: retrieval_mode taxonomy update

`server/handlers/equation.py` currently emits `"ted_fused"` (line 93).
With `embedding_eq` populated, the tag should become `"ted_fused_eq"`.
The handler gets the mode tag from the index — the cleanest approach is
for `EquationIndex.query()` to return a `retrieval_mode` alongside the
hits, or for `_dense_candidates` to return a sentinel. The simplest
approach: add a `retrieval_mode` property to `EquationIndex` that
reflects what it used.

### Tests

`tests/fixtures/equations/` contains three hand-crafted MathML fixtures:
`int_01_fxdx.mathml`, `int_ab_gtdt.mathml`, `sum_0_inf_an.mathml`.
These are used by `tests/test_equation_index.py`. The `retrieval_mode`
assertions in that file hard-pin `"ted_fused"` (line 562, 634-line context,
679) — **updating to `"ted_fused_eq"` breaks these tests when `embedding_eq`
is populated**, but when the equations table has only NULL `embedding_eq`
(the default test state) they remain `"ted_fused"`. This is the correct
graceful-degradation path.

---

## 2. Prior decisions and lessons

**`presentation_latex` is already in the DOM.** The chunker's
`_element_text` takes the `alttext` attribute of each `<math>` element and
wraps it as `$<alttext>$`. LaTeXML normalizes whitespace in `alttext` but
preserves the LaTeX source faithfully (confirmed by the chunker comment:
"Closes F1 (CRITICAL math fidelity violation)"). The extractor reads
`node.get("alttext")` directly — no additional parsing.

**`context_sentence`: use enclosing `<p>` text.** Walking up the DOM
to the first `<p>` ancestor gives the paragraph containing the equation.
`_element_text(p_tag)` then applies the same math-fidelity-preserving walk
the chunker uses, inlining other `<math>` elements as `$alttext$`. Do
NOT use a sentence tokenizer — that introduces an nltk dependency and is
overkill for v1. The whole paragraph is the right unit.

**`parent_chunk_id`: NULL at v1.** The simplest defensible position.
Computing the correct parent requires reproducing the chunker's section
tracking and then finding the closest enclosing theorem/section environment
— a full re-implementation of `_extract_chunks_from_container`. At v1
the equations table joins to the chunks table via the dense pass in
`_dense_candidates` (which already uses `embedding_stmt` on chunks as a
proxy), so `parent_chunk_id` being NULL doesn't break retrieval. The TED
fusion path in `_dense_candidates` uses `parent_chunk_id IN (...)` only
when `embedding_eq` is NOT populated; once `embedding_eq` is live, the
join is bypassed entirely.

**Idempotency pattern: mirror `index_equations.py`.** That module reads
all rows, filters `WHERE mathml_tree_json IS NULL`, processes, writes back
via `merge_insert`. The equation embedder should do the same: read all rows,
filter `WHERE embedding_eq IS NULL`, batch-encode, write back. This is
safe because `merge_insert(on="equation_id")` updates the matched row
in-place leaving all other columns (including `mathml`, `mathml_tree_json`)
untouched.

**Single-writer contract.** `store.py` module docstring (lines 44–56)
states: "The function is designed for a SINGLE writer per LanceDB dataset."
The equation extractor and embedder must be run sequentially, not in
parallel against the same table. Document this in the module docstring.

**`make ingest` stub.** The extractor and embedder should expose a
`__main__` entry point (`python -m ingest.extract_equations`,
`python -m ingest.embed_equations`) callable independently. `make ingest`
stays stub. This matches the `python -m ingest.graph_ingest` pattern.

**`assert` ban.** CLAUDE.md §4.7: "Use `if … raise RuntimeError(…)`
instead." No `assert` in the new modules.

**TOOL_SCHEMA_VERSION 4 → 5.** The `FIND_EQUATION` tool description
(line 135-145 in `server/tools.py`) currently says
`"retrieval_mode='ted_fused'"`. When `embedding_eq` is populated, the
mode tag becomes `"ted_fused_eq"`. **The description should be updated
to mention both `ted_fused` (proxy path) and `ted_fused_eq` (native
path).** This is a description change → `TOOL_SCHEMA_VERSION` 4 → 5 →
`EXPECTED_BP1_SHA256` repin + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
repin + `search_papers_result.json::version` 4 → 5.

**BeautifulSoup namespace handling.** The `html.parser` backend (already
used by the chunker) handles embedded MathML transparently — it treats
`<math>` as a regular HTML element. The `xmlns:math="..."` attribute is
ignored by `html.parser` (it does not enforce XML namespaces). MathML
child elements (`<mrow>`, `<mi>`, `<mo>`) are parsed as plain HTML tags.
This is correct for extraction purposes. For `mathml` column content
(the serialized inner MathML string), use `str(math_tag)` or
`math_tag.decode_contents()` — both work with `html.parser`.

**lxml is NOT a direct dependency.** `pyproject.toml` declares
`beautifulsoup4>=4.12` without `lxml`. The `html.parser` backend is
sufficient and avoids an optional C-extension dep.

---

## 3. External sources

**LaTeXML HTML5 output format.** LaTeXML `--format=html5` wraps each
math environment in:
- Inline math: `<math xmlns="http://www.w3.org/1998/Math/MathML" alttext="...">`
- Display equations (`\begin{equation}`): additionally wrapped in
  `<table class="ltx_equation ltx_eqn_table">` with a
  `<span class="ltx_tag ltx_tag_equation">(N.M)</span>` label cell.
- `\begin{align}` (multi-line): similar table structure with one row
  per line and one label cell per row.

The extractor should target `<table class="ltx_equation ...">` elements
for **display math only** (v1 scope). The `math_tag = table.find("math")`
gives the MathML element. The label comes from
`table.find("span", class_="ltx_tag_equation")` or
`table.find("td", class_="ltx_eqn_eqno")`.

**BeautifulSoup MathML serialization.** `str(math_tag)` or
`math_tag.decode_contents()` gives the inner HTML as a string. For the
`mathml` column, store `str(math_tag)` (includes the `<math>` wrapper
since `defusedxml.ElementTree.fromstring` in `index_equations.py` expects
a complete `<math>` root). `math_tag.decode_contents()` gives only the
inner elements — NOT what we want. Use `str(math_tag)`.

**BGE-M3 batching.** `EMBED_BATCH_DEFAULT = 32` (from `ingest/embedder.py`
line 133). Equation text (typically 20–100 chars) is shorter than
chunk text; batches of 32 are conservative but consistent with the
existing embedder discipline. Do not increase the batch size — consistency
is more important than throughput for v1.

---

## Open questions

1. **`parent_chunk_id` strategy.** Recommend NULL at v1. Rationale: the
   join is only needed for the legacy `embedding_stmt` proxy path; once
   `embedding_eq` is live, `_dense_candidates` queries the equations
   table directly and `parent_chunk_id` is irrelevant. Implementing
   section-path resolution to synthesize a `parent_chunk_id` adds
   complexity for zero retrieval benefit at the milestone's scope.

2. **`context_sentence` definition.** Recommend the entire enclosing
   `<p>` paragraph text (via `_element_text` for math fidelity), not a
   single sentence. No nltk dependency required.

3. **Display math only vs. inline math.** Recommend display math only
   (`<table class="ltx_equation ...">` elements) for v1. Inline math
   fragments are pervasive and typically sub-expressions, not
   semantically complete. The brief's examples ("structural similarity
   of integrals") all concern display equations.

4. **Order of operations.** Recommend INDEPENDENT of the chunker: the
   extractor re-parses the same `index.html` file the chunker reads,
   does its own `<table class="ltx_equation">` walk, computes its own
   section_path, and writes to the `equations` table. No dependency on
   chunk output files. The embedder runs after the extractor and after
   `index_equations.py` (so `mathml_tree_json` is already populated).

5. **`ascii_form`.** Store `""` (empty string) at v1. No LaTeX-to-ASCII
   stripping library is in scope. The column is `NULLABLE` so `None`
   would also work, but `""` is consistent with the non-null sentinel
   pattern used in `DEFINITIONS_SCHEMA_V1`.

6. **`retrieval_mode` change `"ted_fused"` → `"ted_fused_eq"`.** This
   breaks `tests/test_equation_index.py` assertions when `embedding_eq`
   is populated. The test fixture uses NULL `embedding_eq` rows
   (hand-crafted), so the tests will continue to emit `"ted_fused"` as
   long as the test fixtures do not have `embedding_eq` populated. The
   implementer must add tests that cover the `"ted_fused_eq"` path with
   synthetic non-NULL `embedding_eq` rows, and must NOT break the
   existing tests. The safe approach: keep `"ted_fused"` as the default
   in the existing code path; introduce `"ted_fused_eq"` only when
   `_dense_candidates` detects non-NULL `embedding_eq` values.

---

## External writes required

- `ingest/extract_equations.py` — new file
- `ingest/embed_equations.py` — new file
- `server/retrieval/equations.py` — update `_dense_candidates` for dual-path
- `server/handlers/equation.py` — update retrieval_mode tag
- `server/tools.py` — update `FIND_EQUATION` description + bump
  `TOOL_SCHEMA_VERSION` 4 → 5
- `tests/test_server_tool_schema.py` — repin `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
- `tests/test_equation_index.py` — add `"ted_fused_eq"` path tests
- `tests/test_extract_equations.py` — new test file
- `tests/test_embed_equations.py` — new test file
- Local LanceDB write to `var/arxmcp/index/lancedb/equations.lance/`

**No new pip dependencies required.** `beautifulsoup4`, `defusedxml`,
`lancedb`, `pyarrow`, and `numpy` are all already declared. No `lxml`,
no `nltk`, no new C-extension deps.

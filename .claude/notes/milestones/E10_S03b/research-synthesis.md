# E10_S03b — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) and
[research-brief-2.md](research-brief-2.md). Both researchers
converged sharply on the design with Researcher 2 supplying
empirically-verified LaTeXML HTML output samples.

---

## 1. Headline findings (consensus across both researchers)

| # | finding | resolution |
|---|---|---|
| 1 | The brief's preferred path (`<math>` extraction from LaTeXML HTML) works as-is. `<math alttext="..." display="block">` carries the LaTeX source in the `alttext` attribute — same source the chunker already inlines as `$...$` in `body_text`. **No new parsing needed; reuse `node.get("alttext")`.** | Use `BeautifulSoup(html, "html.parser")` (already a dep). |
| 2 | **LaTeXML strips the original `\label{eq:foo}` and replaces it with a sequential id like `S0.E1`.** Cross-references survive but the symbolic name is gone. | Use the sequential id suffix (`E1`, `E2`) as the `label` column value, NOT the human-facing `(1)` number. The sequential id is the stable key that matches `\eqref{}` href targets. |
| 3 | **`\begin{align}` produces a `<table class="ltx_equationgroup">` with one `<tbody>` per labeled row**, each `<tbody>` containing multiple `<math display="inline">` cells. The detection rule for "this is an equation atom" cannot rely on `display="block"` alone. | Detection: `<table class~="ltx_eqn_table">` OR `<tbody id="S*.E*"> inside <table class~="ltx_equationgroup">`. Stitch align-group cells by concatenating `alttext` values (space-joined) for `presentation_latex`. |
| 4 | **Of the 50 seed papers, only 2 have raw TeX**, and BOTH failed LaTeXML conversion. The seeded corpus does NOT have usable HTML to extract equations from today. | Test the extractor + embedder against **hand-crafted minimal LaTeXML HTML fixtures** under `tests/fixtures/extract_equations/`. Real-corpus end-to-end is unreachable until ingest is rebuilt — call this out in the implementation summary. |
| 5 | **Inline math (`$x$`) is high-density and semantically sub-equational.** Researcher 2 documented ~5 inline-math elements per sentence in math-heavy papers. | **Skip inline math entirely at v1.** Scope is display math only (`ltx_eqn_table` and `ltx_equationgroup`). |

---

## 2. Load-bearing quotes

### LaTeXML HTML output (Researcher 2's live `latexmlc 0.8.8` run)

```html
<!-- \begin{equation} ... \end{equation} -->
<table class="ltx_equation ltx_eqn_table" id="S0.E1">
  <tbody>
    <tr class="ltx_equation ltx_eqn_row ltx_align_baseline">
      <td class="ltx_eqn_cell ltx_align_center">
        <math alttext="e^{i\pi}+1=0" class="ltx_Math"
              display="block" id="S0.E1.m1">
          <mrow>...</mrow>
        </math>
      </td>
      <td class="ltx_eqn_cell ltx_eqn_eqno ltx_align_middle ltx_align_right">
        <span class="ltx_tag ltx_tag_equation">(1)</span>
      </td>
    </tr>
  </tbody>
</table>

<!-- \begin{align} ... \end{align} -->
<table class="ltx_equationgroup ltx_eqn_align ltx_eqn_table" id="S0.EGx1">
  <tbody id="S0.E2">
    <tr>
      <td><math alttext="\displaystyle x+y" display="inline" id="S0.E2.m1">...</math></td>
      <td><math alttext="\displaystyle=3" display="inline" id="S0.E2.m2">...</math></td>
    </tr>
  </tbody>
</table>
```

### Chunker math-fidelity quote — `ingest/chunker.py::_element_text`

```python
if node.name == "math":
    alttext = node.get("alttext")
    if alttext:
        parts.append(f"${alttext}$")
        return
```

This confirms: **`alttext` is the canonical source of `presentation_latex`**. The chunker already extracts it for body_text; the extractor captures it as a first-class column.

### EQUATIONS_SCHEMA_V1 (from `ingest/schema.py`)

```
equation_id           utf8 NOT NULL
paper_id              utf8 NOT NULL
label                 utf8 NULLABLE
presentation_latex    utf8 NOT NULL
mathml                utf8 NOT NULL
ascii_form            utf8 NULLABLE
context_sentence      utf8 NULLABLE
parent_chunk_id       utf8 NULLABLE
mathml_tree_json      utf8 NULLABLE  (populated by ingest/index_equations.py)
embedding_eq          list<float32, 1024> NULLABLE
```

The schema is unchanged by this milestone.

### BGE-M3 batch helper — `ingest/embedder.py:133`

```python
EMBED_BATCH_DEFAULT = 32

def _encode_batch(texts: list[str], chunk_ids: list[str]) -> np.ndarray:
    """L2-normalized BGE-M3 encode of a batch."""
```

Reuse this directly for equations. No new encoder.

---

## 3. Design decisions

### D1. Display-math-only scope

The extractor walks `<table class~="ltx_eqn_table">` AND
`<tbody id="S*.E*">` inside `<table class~="ltx_equationgroup">`.
Every other `<math>` element (inline math) is skipped at v1.

### D2. `label` = LaTeXML id suffix (e.g. `E1`)

Both researchers agree: the original `\label{eq:foo}` is lost in the
HTML output. The stable handle is the sequential id LaTeXML assigns
(`S0.E1`). Store the id's last `.`-delimited segment (`E1`, `E2`)
in the `label` column. The human-facing `(1)` from
`<span class="ltx_tag_equation">` is NOT used (it's display-formatted,
unstable across paper re-renders).

### D3. Align-group stitching

Each labeled `<tbody>` in a `ltx_equationgroup` table is ONE equation
atom. Concatenate the `alttext` of every `<math>` cell in that
`<tbody>` (space-joined) for `presentation_latex`. For `mathml`,
serialize the entire `<tbody>` element as a string so the TED tree
captures the structural relationship between LHS and RHS columns.

### D4. `presentation_latex = alttext` (verbatim, no normalization)

LaTeXML normalizes whitespace in `alttext`; the extractor preserves
that form. NFC normalization is not applied (consistency with the
chunker, which also doesn't normalize alttext on the body_text path).

### D5. `mathml = str(math_tag)` (or `str(tbody)` for align groups)

Includes the full `<math>` wrapper so `defusedxml.ElementTree.fromstring`
can re-parse it in the indexer pass. Researcher 1 verified
`math_tag.decode_contents()` strips the wrapper and is wrong for this
use.

### D6. `context_sentence` = enclosing paragraph, capped at 4000 chars

Walk up via `eq_table.find_previous_sibling('p')` or the enclosing
`<div class="ltx_para">`'s `<p>`. Cap the result at 4000 chars to
match the handler-side `latex_or_mathml` input cap. No sentence
tokenization (no nltk).

### D7. `parent_chunk_id = None` at v1

Researcher 1 + Researcher 2 agree: reimplementing the chunker's
section-path resolution to synthesize a `parent_chunk_id` is large
scope for zero retrieval benefit. The `_dense_candidates` join uses
`parent_chunk_id` only on the legacy `embedding_stmt` proxy path;
the new `embedding_eq` path bypasses it. Leave NULL; tests verify the
NULL path doesn't break.

### D8. `ascii_form = ""` at v1

Reserved for a future LaTeX-to-ASCII pass.

### D9. `equation_id` recipe

```python
equation_id = "arxiv:" + paper_id + ":" + hashlib.sha256(
    paper_id.encode() + b"\x00" +
    mathml.encode() + b"\x00" +
    (label or "").encode()
).hexdigest()[:16]
```

NUL separators prevent boundary collisions. Mirrors chunk_id
discipline from `ingest/identifiers.py`.

### D10. Idempotency

- **Extractor**: delete-then-insert per paper (`tbl.delete("paper_id =
  '<id>'")` then bulk `tbl.add`). Cleaner than `merge_insert` because a
  re-render of the HTML may produce a different equation count, and
  delete-then-insert leaves no orphans.
- **Embedder**: filter `embedding_eq IS NULL` before running BGE-M3.
  Never re-embed.

### D11. EquationIndex dual-path dense

Add a `_has_embedding_eq()` check inside `_dense_candidates`. If ANY
row has non-NULL `embedding_eq`, query
`equations_table.search(query_vec, vector_column_name="embedding_eq")`
directly and skip the chunks-proxy join. Otherwise fall back to the
current chunks.embedding_stmt path. The `retrieval_mode` returned is
`"ted_fused_eq"` (new) vs `"ted_fused"` (legacy), respectively.

### D12. `find_equation` description update + TOOL_SCHEMA_VERSION 4→5

The description must mention the new `ted_fused_eq` mode. The
description change is unavoidable; the version bump + hash repin
follows the established protocol (E10_S01/S02/S03 precedent). Affects:
- `TOOL_SCHEMA_VERSION` 4 → 5
- `EXPECTED_TOOL_SCHEMA_SHA256` repin via `pytest --update-tool-schema-hash`
- `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` 4 → 5 (auto-pinned)
- `EXPECTED_BP1_SHA256` manual repin (test failure tells us the new value)
- `search_papers_result.json::version` 3 → wait, it's at 4 (E10_S02 bumped 3→4). Bump to 5.

### D13. CLI entry points

Both modules expose `python -m ingest.extract_equations <paper_id>`
and `python -m ingest.embed_equations` (no args — walks every NULL
row). `make ingest` stays a stub; future ingest driver composes
these.

### D14. Tests against synthetic LaTeXML HTML

The seed corpus has no valid HTML today (Researcher 2). Tests use:
- Hand-crafted `.html` fixtures under `tests/fixtures/extract_equations/`
  matching the LaTeXML output structure (Researcher 2's empirical
  examples).
- For the embedder test: `requires_model` marker (real BGE-M3
  inference required to verify L2-normalization + row write).
- For backward-compat of existing `test_equation_index.py`: the
  existing tests stage `embedding_eq=None` and stay on the
  `ted_fused` path. New tests stage non-NULL `embedding_eq` and assert
  `ted_fused_eq`.

---

## 4. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `ingest/extract_equations.py` (NEW) | LaTeXML HTML → equation atoms | D1-D9, D10 |
| `ingest/embed_equations.py` (NEW) | NULL embedding_eq → BGE-M3 | D10 |
| `server/retrieval/equations.py` | dual-path `_dense_candidates` | D11 |
| `server/handlers/equation.py` | new retrieval_mode tag plumbing | D12 |
| `server/tools.py` | description update; `TOOL_SCHEMA_VERSION` 4→5 | D12 |
| `tests/test_server_tool_schema.py` | re-pin via `--update-tool-schema-hash` | BP1 |
| `tests/test_prompts.py` | re-pin `EXPECTED_BP1_SHA256` | BP1 |
| `server/schemas/search_papers_result.json` | bump `version` 4→5 + `$id` | snippet contract cross-check |
| `tests/test_extract_equations.py` (NEW) | parser tests against fixtures | AC1 |
| `tests/test_embed_equations.py` (NEW) | embedder tests | AC2 |
| `tests/test_equation_index.py` | new tests for `ted_fused_eq` path | AC3-AC5 |
| `tests/fixtures/extract_equations/*.html` (NEW) | LaTeXML HTML fixtures | D14 |

---

## 5. Landmines

1. `assert` banned.
2. HEREDOC commits.
3. `uv run python -m pytest`.
4. `TOOL_SCHEMA_VERSION` 4→5 via the flag.
5. `EXPECTED_BP1_SHA256` manual repin.
6. `search_papers_result.json::version` 4→5 lockstep.
7. No new MD in `server/`, `ingest/`, `tests/`.
8. **The real corpus has no usable HTML.** End-to-end tests use synthetic fixtures.
9. **Cap `context_sentence` at 4000 chars** to keep row size bounded.
10. **Skip inline math** at v1.
11. **`parent_chunk_id = None`** at v1.

---

## 6. Test surface

### AC coverage

- **AC1** (`extract_equations` writes rows). Stage a synthetic
  LaTeXML HTML fixture under `tests/fixtures/extract_equations/`,
  run the extractor against a tmp_path lancedb_path; assert rows
  have non-empty `mathml`, `presentation_latex`. Cover the
  `\begin{equation}` and `\begin{align}` cases.
- **AC2** (`embed_equations` populates non-NULL L2-normalized
  vectors). `requires_model` marker; runs real BGE-M3 over a few
  hand-staged rows; asserts column populated and ||v|| ≈ 1.0.
- **AC3** (`ted_fused_eq` mode on populated embedding_eq). Stage
  3-4 rows with synthetic unit vectors as `embedding_eq` (no BGE-M3
  needed; matches existing E10_S03 test pattern); query the handler
  via a MathML input; assert `retrieval_mode="ted_fused_eq"`.
- **AC4** (backward compat — `ted_fused` mode on NULL embedding_eq).
  Existing E10_S03 tests should stay green without modification.
- **AC5** (H5 closed). Synthetic fixture: stage `embedding_eq` such
  that an integral query ranks above a summation candidate.

### Beyond-AC tests

- `parent_chunk_id=None` path: verify `_dense_candidates` doesn't
  crash when every candidate has NULL parent.
- `embedding_eq` empty table: handler falls back to dense_only.
- Inline math `<math display="inline">` outside `ltx_eqn_table`:
  extractor skips, writes 0 rows for an HTML with only inline math.
- Idempotency: re-running extractor on the same paper leaves row
  count stable.
- HTML with zero `<math>` elements: extractor writes 0 rows, no
  error.
- Empty `alttext` attribute: skip the equation (no usable
  `presentation_latex`).
- Hash anchors stable after the description repin cycle.

---

## 7. Open questions remaining

None blocking. Resolved via D1-D14.

---

## 8. External writes required

```
| type | target | why |
|---|---|---|
| local | var/arxmcp/index/lancedb/equations.lance/ | extractor/embedder writes |
```

No `pyproject.toml` changes (all deps present). No `uv lock`
regeneration. No external API calls.

---

## 9. Suggested implementation order

1. `tests/fixtures/extract_equations/*.html` — synthetic fixtures.
2. `ingest/extract_equations.py` — parser + writer.
3. `tests/test_extract_equations.py` — fixture-driven tests.
4. `ingest/embed_equations.py` — BGE-M3 + writer.
5. `tests/test_embed_equations.py` — `requires_model` test.
6. `server/retrieval/equations.py::_dense_candidates` — dual-path.
7. `server/handlers/equation.py` — pass-through the new mode tag.
8. `tests/test_equation_index.py` — new `ted_fused_eq` test.
9. `server/tools.py` — description update + bump.
10. `pytest --update-tool-schema-hash` — repin.
11. `tests/test_prompts.py` — re-pin BP1 manually.
12. `server/schemas/search_papers_result.json` — bump version + $id.
13. `make test`; commit.

---

## 10. Done-when checklist

- [ ] All 5 ACs have verifiable tests.
- [ ] `TOOL_SCHEMA_VERSION == 5`; all three hash anchors repinned.
- [ ] Existing `test_equation_index.py` tests stay green (backward compat).
- [ ] `make test` green; ruff clean.
- [ ] Implementation summary explicitly notes:
  - H5 is **algorithmically closed** by the new dual-path dense step.
  - The seed corpus's HTML is broken (2/50 papers, both with conversion
    failures); end-to-end-against-corpus tests use synthetic fixtures.
  - A future ingest rebuild (E11) is the place where this milestone's
    new code first runs against real arXiv content.

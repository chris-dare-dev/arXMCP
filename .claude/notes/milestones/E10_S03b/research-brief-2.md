# E10_S03b Research Brief 2 — Data-layer angle

Focus: LaTeXML HTML structure (empirically verified), performance/scale,
threat surface, and cross-impact on existing tests.

---

## 1. What the actual LaTeXML HTML looks like (empirically verified)

Observation: only 2 of 50 seed papers have raw TeX in
`var/arxmcp/corpus/raw/`; one (`2605.03890`) failed LaTeXML conversion
with fatal errors (100+ errors from a `babel`/`\csname` interaction;
`latexmlc` exited non-zero, the `index.html` body is empty). The other
(`2605.03835`) failed similarly. The success check in `arxiv_fetch.py`
line 125 (`AND html contains "<math"`) would correctly mark both as
failed — `mathml_node_count=0`. **Neither paper has usable HTML today.**

To document the actual structure, a minimal TeX fixture with
`\begin{equation}`, `\begin{align}`, and `\begin{gather}` was run
through the local `latexmlc 0.8.8` binary. Concrete findings follow.

### 1a. Display vs. inline in `equation` environments

A `\begin{equation}\label{eq:euler} ... \end{equation}` block produces:

```html
<table class="ltx_equation ltx_eqn_table" id="S0.E1">
  <tbody>
    <tr class="ltx_equation ltx_eqn_row ltx_align_baseline">
      <td class="ltx_eqn_cell ltx_eqn_center_padleft"></td>
      <td class="ltx_eqn_cell ltx_align_center">
        <math alttext="e^{i\pi}+1=0" class="ltx_Math"
              display="block" id="S0.E1.m1">
          <mrow>...</mrow>
        </math>
      </td>
      <td class="ltx_eqn_cell ltx_eqn_center_padright"></td>
      <td class="ltx_eqn_cell ltx_eqn_eqno ltx_align_middle ltx_align_right"
          rowspan="1">
        <span class="ltx_tag ltx_tag_equation ltx_align_right">(1)</span>
      </td>
    </tr>
  </tbody>
</table>
```

Key observations:
- The `<table>` carries the equation number as `id="S0.E1"`.
- The `<math>` element carries `display="block"` and the equation
  number appended as `id="S0.E1.m1"`.
- The human-readable `alttext` attribute contains the **presentation
  LaTeX** — this IS `presentation_latex`. Use `el.get('alttext')`.
- The equation number `(1)` is in
  `<span class="ltx_tag ltx_tag_equation">`. This IS the `label`
  field; extract from the nearest `ltx_tag_equation` span.
- The **original `\label{eq:euler}` is NOT preserved in the HTML**.
  LaTeXML maps it to a sequential id (`S0.E1`). Cross-references
  survive (`\eqref{eq:euler}` → `<a href="#S0.E1">`), but the
  symbolic name is gone. The extractor cannot recover it. **Use
  the sequential id substring (`E1`, `E2`, …) as the label field.**

### 1b. `align` and `gather` environments — critical structural difference

An `\begin{align}` block produces a **`ltx_equationgroup` table**, not
a `ltx_equation` table:

```html
<table class="ltx_equationgroup ltx_eqn_align ltx_eqn_table" id="S0.EGx1">
  <tbody id="S0.E2">   <!-- one <tbody> per labeled row -->
    <tr class="ltx_equation ltx_eqn_row ltx_align_baseline">
      <td class="ltx_td ltx_align_right ltx_eqn_cell">
        <math alttext="\displaystyle x+y" class="ltx_Math"
              display="inline" id="S0.E2.m1">...</math>
      </td>
      <td class="ltx_td ltx_align_left ltx_eqn_cell">
        <math alttext="\displaystyle=3" class="ltx_Math"
              display="inline" id="S0.E2.m2">...</math>
      </td>
    </tr>
  </tbody>
</table>
```

**Design implication (opinionated):** Each labeled `<tbody>` row in an
align group is ONE equation atom. Concatenate the `alttext` values from
all `<math>` elements within that `<tbody>` to form `presentation_latex`
(joining with a space; the split between LHS and RHS columns is a
layout artifact). The MathML to store is the **concatenation of inner
content** of both `<math>` elements wrapped in a single synthetic
`<math display="block">`. Each column's `<math>` carries `display="inline"` — the
extractor must look at parent structure, NOT the `display` attribute
alone, to detect numbered equations. The detection rule is:

```
is_numbered_equation = (
    <table class contains "ltx_equation"> AND
    <math display="block">
) OR (
    <tbody id="S0.EN"> inside <table class contains "ltx_equationgroup">
)
```

### 1c. Inline math (`$x$`) — SKIP in v1

Inline `$x$` produces `<math display="inline" id="p1.m1">...</math>`
outside any `ltx_equation` container. The density is very high
(~5 per sentence in math-heavy papers). **Skip all inline math in v1.**
The selector `table.ltx_eqn_table` is the v1 boundary.

### 1d. Equation numbers — extraction rule

Numbered equations have a `<span class="ltx_tag ltx_tag_equation">`.
The text content (e.g., `(3)`) is the display number. For the `label`
field, use the table's `id` attribute suffix (e.g., `S0.E1` → `E1`),
NOT the human-facing `(3)`. This makes `label` a stable key that
matches `\eqref{}` cross-reference targets in the HTML.

---

## 2. Performance and scale

**Seed corpus (50 papers, math.AG).** Only 2 papers have raw TeX and
neither has a valid HTML render today. A fully-fetched seed corpus of
50 papers × ~20 numbered equations ≈ **1000 equation atoms**. At
BGE-M3 on CPU, batch size 32 (matching `EMBED_BATCH_DEFAULT` in
`ingest/embedder.py:133`): 1000 equations = ~32 batches × ~300ms each
= **~10s** to populate `embedding_eq`. Acceptable for a seed corpus.

**Tier-4 scale (200K papers × ~20 equations = 4M atoms).** Batched
BGE-M3: 4M / 32 = 125K batches × 300ms = **~10 hours on CPU**; ~45
minutes on a GPU (batch ~500ms at batch_size=256 with fp16). The
brief's §2 "Out of scope: GPU embedding" note applies; the extractor
must be restartable (idempotent per-row NULL check is sufficient).

**Storage budget per row:**
- `mathml`: ~1–3 KB (equation-group rows can be larger)
- `mathml_tree_json`: ~0.5–2 KB
- `presentation_latex`: ~50–500 B (alttext)
- `context_sentence`: up to 4000 B (must cap — see §3)
- `embedding_eq`: 1024 × 4 bytes = 4 KB

**Per-row budget: ~12 KB.** 1000 seed rows ≈ 12 MB; 4M corpus rows
≈ 48 GB. The design note does not name a storage budget; the 48 GB
figure should be documented in the implementation so E11 can plan GPU
storage accordingly. For the seed corpus the budget is immaterial.

**Idempotency contract (opinionated):**
- `ingest/extract_equations.py`: delete-then-insert PER PAPER
  (`where("paper_id = '<id>'")` delete before bulk insert). Simpler
  than merge_insert for extraction since the full set of equation atoms
  for a paper changes if the HTML is re-rendered. Use
  `merge_insert("equation_id").when_matched_update_all()
  .when_not_matched_insert_all()` as a fallback if delete is not
  exposed cleanly by the pinned LanceDB version.
- `ingest/embed_equations.py`: filter `embedding_eq IS NULL` before
  running BGE-M3. Never re-embed rows that already have a vector.

---

## 3. Threat surface and data integrity

**MathML source is local-pipeline-trusted.** The HTML comes from
`latexmlc` running locally on arXiv source we fetched. Not adversarial.
`defusedxml.ElementTree` (already in `pyproject.toml:122`) is still the
right parser for the stored MathML column — it blocks XXE and
billion-laughs on any future corpus that includes third-party HTML.

**`context_sentence` length cap — opinionated recommendation:**
LaTeXML wraps equation tables inside `<div class="ltx_para">`. The
preceding `<p class="ltx_p">` sibling is the natural context source.
Cap at **4000 characters** at extraction time. Rationale: the
`find_equation` handler's Pydantic field already caps query inputs at
4000 chars (see `handlers/equation.py:24`); the corpus-side context
should match. A paragraph in an algebraic geometry paper rarely exceeds
1000 chars; the cap is a safety floor for appendix-style paragraphs.

**`equation_id` content-addressing.** Recommended input to sha256:

```python
equation_id = "arxiv:" + paper_id + ":" + \
    sha256(
        paper_id.encode() + b"\x00" +
        mathml.encode() + b"\x00" +
        (label or "").encode()
    ).hexdigest()[:16]
```

NUL separators prevent boundary collisions (e.g., `paper_id="AB"`,
`mathml="C"` vs `paper_id="A"`, `mathml="BC"`). Mirrors
`chunk_id` discipline from `ingest/identifiers.py`.

**`parent_chunk_id` linkage:** The extractor reads HTML directly and
does not know the chunks table state. Leave `parent_chunk_id=None`
when the enclosing chunk cannot be resolved. The `parent_chunk_id`
column is `nullable=True` per `EQUATIONS_SCHEMA_V1`. Tests must
explicitly exercise the NULL path in `_dense_candidates` — the
`chunk_scores.get(parent, 0.0) if parent else 0.0` branch is already
present in `server/retrieval/equations.py:_dense_candidates`.

**Unreachable corpus case:** If `var/arxmcp/corpus/parsed/<pid>/index.html`
contains no `<math>` elements (as with the two seed papers that failed
LaTeXML conversion), the extractor writes zero rows for that paper. This
is not an error. The `mathml_node_count=0` field in the existing
`ParseResult` struct (from `arxiv_fetch.py`) is the gating signal; the
extractor should log a warning and skip rather than raising.

---

## 4. Cross-impact on existing tests

### 4a. `test_mathml_input_with_populated_table_routes_to_ted_fused`

File: `tests/test_equation_index.py:490`.

This test seeds an equations table with `embedding_eq=None` (the test
helper `_build_equations_table` sets `eq.get("embedding_eq")` which is
`None` by default). After E10_S03b changes `_dense_candidates` to query
`embedding_eq` when populated, the test still works as-is **if**
`_dense_candidates` falls back to `embedding_stmt` when ALL rows have
`embedding_eq=None`. This is the backward-compat criterion:

```python
# In _dense_candidates:
eq_arrow = self._equations.to_arrow()
embedding_eq_col = eq_arrow.column("embedding_eq")
use_embedding_eq = any(v is not None for v in embedding_eq_col.to_pylist())
if use_embedding_eq:
    # query embedding_eq directly
else:
    # legacy chunk-proxy path (current implementation)
```

With this logic:
- Existing test: `embedding_eq=None` → `use_embedding_eq=False` →
  old path → `retrieval_mode="ted_fused"` — **no change to this test**.
- New test (E10_S03b): `embedding_eq` populated → `use_embedding_eq=True`
  → new path → `retrieval_mode="ted_fused_eq"` — new test required.

**New test requirement:** a test that seeds `embedding_eq` with unit
vectors (mirroring `_unit_vec` in the test helpers) and asserts
`retrieval_mode="ted_fused_eq"`. This test does NOT need BGE-M3; the
unit vectors are computed in-test and do NOT need `@pytest.mark.requires_model`.

### 4b. TOOL_SCHEMA_VERSION bump

The `find_equation` description (currently at `TOOL_SCHEMA_VERSION=4`) must
be updated to mention `ted_fused_eq`. That is a **BP1 cache bust** because
the tool-list response must stay byte-stable per the BP1 discipline note
(`.claude/notes/07-multi-agent-caching.md:40-49`). The required changes:

1. Update description to add: `"When embedding_eq is populated, the dense
   signal switches to the equation-specific column and retrieval_mode
   becomes 'ted_fused_eq'."`
2. Bump `TOOL_SCHEMA_VERSION: int = 4` → `5` in `server/tools.py`.
3. Re-pin `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
   in `tests/test_server_tool_schema.py` via `pytest --update-tool-schema-hash`.

Three anchors to update: `EXPECTED_TOOL_SCHEMA_SHA256`,
`EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`, and `TOOL_SCHEMA_VERSION`.
The test harness enforces the version-must-change invariant before
accepting a new hash.

### 4c. Tests for `extract_equations` and `embed_equations`

Both new modules need tests. The extractor tests should NOT require
live LaTeXML — they should parse fixture HTML (the minimal HTML
generated from `latexmlc` in a temporary directory, or a committed
`.html` fixture file). The embedder test needs BGE-M3; mark it
`@pytest.mark.requires_model`.

---

## Open questions — different angles from peer

1. **Align-group MathML stitching.** The `align` environment produces
   multiple `<math display="inline">` per row. The recommended
   approach is concatenation into a single synthetic block-level
   `<math>` for the `mathml` column. An alternative is to store each
   column cell as a separate equation atom. The stitching approach is
   simpler and preserves the full equation as a unit for TED scoring.
   **Recommendation: stitch.** Implement in `extract_equations.py`.

2. **`context_sentence` — preceding paragraph is sufficient.** Use
   `eq_table.find_previous_sibling('p')` (or the first `<p>`
   in the enclosing `<div class="ltx_para">`). Cap at 4000 chars
   (matches handler input constraint). Do NOT traverse up to section
   headers — the preceding paragraph is the author's own framing.

3. **Corpus completeness vs. HTML availability.** The extractor reads
   from `var/arxmcp/corpus/parsed/<pid>/index.html`. If the HTML is
   absent or empty (LaTeXML failed), the extractor writes zero rows
   for that paper. The chunks table may be richer (the chunker has
   its own fallback path). This is acceptable: equation extraction is
   a best-effort enrichment, not a blocker. The `embedding_eq`
   NULL-check in the embed step handles the zero-row case cleanly.

4. **`parent_chunk_id` when chunks are incomplete.** Leave `None`.
   The `nullable=True` declaration on `EQUATIONS_SCHEMA_V1` explicitly
   permits this. The join in `_dense_candidates` already handles
   `parent=None` via `chunk_scores.get(parent, 0.0) if parent else 0.0`.
   Tests must verify a NULL `parent_chunk_id` row produces a valid
   (zero-scored) candidate rather than a KeyError.

5. **Embedding batch size.** Use `EMBED_BATCH_DEFAULT = 32` from
   `ingest/embedder.py:133`. Import the constant rather than
   hardcoding. Total CPU wall-clock for 1000 seed equations: ~10s.

6. **`find_equation` description update.** The phrase "equation atom
   corpus is empty (the extractor is deferred to a follow-up
   milestone)" in `server/tools.py:139-142` becomes stale once this
   milestone ships. Replace with: "When embedding_eq is populated,
   the dense signal uses equation-specific embeddings and
   retrieval_mode='ted_fused_eq'. When embedding_eq is all-NULL (pre-
   extraction corpus), retrieval_mode='ted_fused' uses the chunk-proxy
   dense path." This is the only description change; bump
   TOOL_SCHEMA_VERSION 4→5 in lockstep.

---

## External writes required

- **No new dependencies needed.** `beautifulsoup4`, `defusedxml`, and
  `lancedb` are already in `pyproject.toml`. BGE-M3 model weights are
  already downloaded. The equation schema (`EQUATIONS_SCHEMA_V1`) and
  the `open_or_create_equations_table` helper are already in
  `ingest/index_equations.py`.

- **LanceDB writes:** The extractor writes to the `equations` table
  in `var/arxmcp/index/lancedb/` (the same LanceDB directory used by
  the chunks table). The embedder updates the same table's
  `embedding_eq` column via `merge_insert("equation_id")`.

- **`server/tools.py` and `tests/test_server_tool_schema.py`** require
  the description update and hash repin (TOOL_SCHEMA_VERSION 4→5).
  This is a source-file edit, not an external write.

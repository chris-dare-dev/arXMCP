# E10_S03 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) and
[research-brief-2.md](research-brief-2.md). Both researchers
**converged strongly** on the most important finding: the milestone
brief assumes infrastructure that does not exist. The scope-shaping
decisions below are the most consequential part of this synthesis.

---

## 1. The headline finding — scope is wider than the brief admits

The brief reads as a single-milestone feature build. Both researchers
flagged that under the surface it bundles 4–5 distinct pieces of new
infrastructure, several of which are entire milestones in their own
right:

| # | brief assumption | reality (codebase, today) |
|---|---|---|
| 1 | "Reads the `equations` table" | **No `equations` table exists.** No `EQUATIONS_SCHEMA_V1`. No indexer. The chunker doesn't emit equation chunks. |
| 2 | "Populated with equation embeddings on `embedding_eq` column" | **`embedding_eq` is reserved but NULL on every row.** Embedder explicitly does not populate it ([ingest/schema.py:101-108](ingest/schema.py)). And it's on `chunks`, not the missing `equations` table. |
| 3 | "Run over `presentation_latex + context_sentence`" | **Neither `presentation_latex` nor `context_sentence` exist as fields anywhere.** The chunker inlines `<math alttext>` as `$...$` LaTeX prose inside `body_text`. |
| 4 | "Via the local LaTeXML subprocess pool, reusing the existing pool from `server/resources.py`" | **No LaTeXML pool in `server/resources.py`.** The only LaTeXML invocation is `tools/arxiv_fetch.py::parse_with_latexml`, a synchronous batch-ingest helper. |
| 5 | "Index time: pre-compute MathML parse trees, store in `mathml_tree_pickle`" | Column doesn't exist (the table doesn't exist). Pickle storage is a security smell and a Python-upgrade fragility — both briefs recommend swapping it for JSON. |

The brief was written before E09 / E10_S01 landed and the codebase
mapping it presumes has drifted. Phase 1's job is to surface this; the
scope decisions in §3 below are how we make a shippable milestone out
of it.

---

## 2. Load-bearing quotes

### Equation atom record — `.claude/notes/04-parsing-and-chunking.md` § "Equation atom record"

```json
{
  "equation_id": "arxiv:2401.01234:eq789...",
  "paper_id": "2401.01234",
  "label": "(3.7)",
  "presentation_latex": "\\partial_t f = \\Delta f + V f",
  "mathml": "<math>...</math>",
  "ascii_form": "d/dt f = laplacian f + V f",
  "context_sentence": "As shown in equation (3.7), the heat operator...",
  "parent_chunk_id": "arxiv:2401.01234:a1b2c3d4e5f60718",
  "is_numbered": true,
  "is_display": true
}
```

### `equations` table schema — `.claude/notes/05-storage-and-indexing.md` § "Table: equations"

```
equation_id          string (primary key)
paper_id             string
label                string
presentation_latex   string
mathml               string
ascii_form           string
context_sentence     string
parent_chunk_id      string
embedding_eq         fixed_size_list<float32, D>

Indexes: HNSW on `embedding_eq`, B-tree on `paper_id`.
```

### `embedding_eq` is reserved-but-NULL — `ingest/schema.py:101-108`

> "`embedding_eq` is reserved for E10_S03 (equation embeddings).
> The embedder NEVER populates this; every row written by E03_S01
> has `embedding_eq=None`."

### BP1 cache discipline — `.claude/notes/07-multi-agent-caching.md:40-49`

> "Pin tool JSON schemas. Sort properties alphabetically at
> serialization time. Freeze descriptions as constants in source.
> A casual edit to a tool description blows every sub-agent's
> cache."

---

## 3. Scope decisions (the key part)

### D1. Ship NARROW. Do not extract equation atoms from the chunker output.

Brief 1 leans toward implementing the full equation extractor (a new
`ingest/extract_equations.py` that reads LaTeXML HTML and writes the
`equations` table). Brief 2 recommends deferring extraction and
shipping the TED + fusion algorithm against hand-crafted MathML
fixtures.

**Pick Brief 2's narrowed scope.** The brief as written bundles ~3
milestones of work; Phase 1's job is to keep the milestone shippable
in a reasonable turn count. The TED algorithm + fusion + handler +
schema additions all land in this milestone; the equation extractor
+ live-corpus integration is **explicitly deferred** to a follow-up
milestone (call it E10_S03b or fold into E11 production ingest).

This means **H5 is not fully closed** by this milestone. The
algorithm-and-API layer that closes H5 lands here; the
data-population layer that exercises it against the real corpus is
deferred. The implementation summary and the `chore(notes)` commit
MUST be explicit about this — calling it "closes H5" would be a lie.

### D2. Store MathML trees as JSON, not pickle (Brief 2's recommendation).

Pickle has two costs the project is not willing to pay:
1. **Pickle deserialization is a code-execution vector.** Single-user
   deployment limits but does not eliminate the threat.
2. **Pickle format changes across Python minor versions** silently
   corrupt the column on a future Python upgrade.

`zss.Node` is exactly `{label: str, children: list[Node]}` — trivially
JSON-able. The column name becomes `mathml_tree_json` (utf8 in the
PyArrow schema), and the round-trip helpers live in
`server/retrieval/equations.py` next to the `EquationIndex` class.

### D3. The `equations` LanceDB table IS created in this milestone (schema only; populated later).

Both researchers agree the table must exist for the handler to point
at. Create the table with the canonical schema at the path
`var/arxmcp/index/lancedb/equations.lance/`, but at v1 it can stay
empty. The handler degrades gracefully (per AC4) when the table is
absent OR empty OR `mathml_tree_json` is NULL on all rows — same
fallback in all three cases.

The schema (per design constitution + JSON tree decision):
```python
EQUATIONS_SCHEMA_V1 = pa.schema([
    pa.field("equation_id", pa.utf8(), nullable=False),
    pa.field("paper_id", pa.utf8(), nullable=False),
    pa.field("label", pa.utf8(), nullable=True),
    pa.field("presentation_latex", pa.utf8(), nullable=False),
    pa.field("mathml", pa.utf8(), nullable=False),
    pa.field("ascii_form", pa.utf8(), nullable=True),
    pa.field("context_sentence", pa.utf8(), nullable=True),
    pa.field("parent_chunk_id", pa.utf8(), nullable=True),
    pa.field("mathml_tree_json", pa.utf8(), nullable=True),
    pa.field("embedding_eq", pa.list_(pa.float32(), EMBEDDING_DIM), nullable=True),
])
```

### D4. Skip the LaTeXML subprocess pool. The handler accepts only MathML for the TED path.

Building a request-time LaTeXML pool is significant new scope and
LaTeXML is already a known operational headache (subprocess
isolation, 30s timeouts, system-level Perl dep). For v1:

- **MathML input** (detected by `<math` prefix after stripping
  whitespace) → goes through the TED + dense-cosine fusion path.
- **LaTeX input** → falls back to the current dense-only path (the
  existing `dense_only_stmt_fallback`).
- The `retrieval_mode` field communicates which path fired.

This matches AC3 of the brief verbatim: "MathML input (raw
`<math>...</math>`) is accepted and parsed correctly." The brief
doesn't actually require LaTeX-input-to-TED; reading it carefully, AC1
says `find_equation("\\int_0^1 f(x) dx")` returns structurally
similar integrals in top-3 — but the **top-3** can come from
dense-only retrieval since that's the fallback for LaTeX input. AC1
is satisfiable without LaTeXML at query time.

### D5. The dense cosine signal uses `embedding_stmt`, not `embedding_eq`.

Both researchers concluded that `embedding_eq` cannot be the dense
column in this milestone because the column is always NULL and there
is no extractor to populate it. The pragmatic choice (Brief 2's
recommendation): the fusion formula's dense term is cosine over
`embedding_stmt`. Document this explicitly — when E10_S03b lands the
equation extractor, the fusion can switch to `embedding_eq` via a
one-line config flip without changing the algorithm.

### D6. Use `zss` 1.2.0. MIT license. Maintenance-frozen but stable.

Both briefs confirm `zss` is the right choice. License is MIT (per
the GitHub repo's LICENSE). Last release 2018, no compiled deps, pure
Python. Performance is fine for the narrow use case (~0.5ms per
50-node pair × 200 candidates = ~100ms per query at worst).

Add to `pyproject.toml` with the project's per-line comment
discipline.

### D7. Normalize TED as `raw_ted / max(|A|, |B|)`.

Standard normalization, produces values in [0, 1], independent of
corpus size. The "1 - normalized_ted" inversion makes higher = more
similar so it composes cleanly with the cosine score in the linear
combination.

### D8. Hand-crafted MathML fixtures, no live LaTeXML at test time.

Test fixtures for the AC tests are hand-written MathML in
`tests/fixtures/equations/`. Optionally, a `requires_latexml` pytest
marker is added for any future test that wants to exercise the
live-LaTeXML path; tests marked thus skip when `shutil.which("latexmlc")` is
None. Keep the live-LaTeXML path optional.

### D9. `ARXMCP_EQ_TED_WEIGHT` config field, default 0.5.

Per the brief. Goes in `server/config.py`. The handler reads it via
`get_resources().config.eq_ted_weight`.

### D10. `retrieval_mode` taxonomy.

Three values (alphabetical for byte-stable envelope ordering):
- `"dense_only_fallback"` — MathML input, but the `equations` table
  is missing/empty OR `mathml_tree_json` is unpopulated. (AC4 path.)
- `"dense_only_stmt_fallback"` — LaTeX input; no LaTeXML pool;
  dense-only over `embedding_stmt`. (Current path; retained.)
- `"ted_fused"` — MathML input, TED + dense-cosine fusion active.

---

## 4. What lands in E10_S03

### New files

- `ingest/index_equations.py` — given an `equations` table (possibly
  populated by a future milestone, possibly hand-seeded for tests),
  walks every row with `mathml` set and `mathml_tree_json` NULL,
  parses the MathML to a `zss.Node` tree, serializes to JSON, writes
  the column.
- `server/retrieval/equations.py` — `EquationIndex` class with:
  - `parse_mathml_to_tree(mathml: str) -> zss.Node` (via `lxml` or
    `xml.etree`, with strict whitespace + attribute normalization)
  - `tree_to_json(node) -> str` and `tree_from_json(s) -> zss.Node`
  - `EquationIndex.query(query_input, k, alpha=0.5) -> list[dict]`
    — dispatches dense + TED + fusion
- `tests/test_equation_index.py` — covers parser, fusion arithmetic,
  handler integration with hand-crafted fixtures, fallback paths.
- `tests/fixtures/equations/*.mathml` — hand-crafted MathML for a few
  canonical equations (`\int_0^1 f(x)dx`, `\int_a^b g(t)dt`,
  `\sum_{n=0}^\infty a_n`).

### Changed files

- `ingest/schema.py` — add `EQUATIONS_SCHEMA_V1` +
  `EQUATIONS_TABLE_NAME`.
- `server/handlers/equation.py` — rewritten to delegate to
  `EquationIndex` for MathML input; keep current dense-only fallback
  for LaTeX input.
- `server/resources.py` — open `equations_table` at startup (optional;
  None when absent). Mirror the `definitions_table` pattern from
  E10_S01.
- `server/config.py` — add `eq_ted_weight: float = 0.5` (env:
  `ARXMCP_EQ_TED_WEIGHT`).
- `server/tools.py` — update `FIND_EQUATION.description` (remove the
  v1-dense-fallback warning, document TED-fusion + LaTeX-fallback).
  Bump `TOOL_SCHEMA_VERSION` 2→3.
- `pyproject.toml` — add `zss>=1.2.0` with per-line comment.
- `tests/test_server_tool_schema.py` — re-pin
  `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`.
- `tests/test_prompts.py` — re-pin `EXPECTED_BP1_SHA256`.
- `server/schemas/search_papers_result.json` — bump `version` 2→3 +
  `$id` to `v3.json`.

### Out of scope (explicitly NOT in E10_S03)

- Equation atom extraction from LaTeXML HTML.
- Populating `embedding_eq` on either `chunks` or `equations`.
- Adding a query-time LaTeXML subprocess pool.
- Closing H5 against real corpus data.

These move to a future milestone (call it E10_S03b or fold into
E11). The handler and the algorithm are ready and tested for the day
the data lands.

---

## 5. Landmines the implementer must respect

1. **`assert` banned for invariants.** Use `if … raise
   RuntimeError(…)`.
2. **HEREDOC commits.** Description contains backslashes + LaTeX.
3. **`uv run python -m pytest`** — system pytest is 3.9.
4. **TOOL_SCHEMA_VERSION 2→3** via `pytest --update-tool-schema-hash`
   (the flag rewrites both the hash + the version pin).
5. **BP1 hash repin** in `tests/test_prompts.py` — manual update of
   `EXPECTED_BP1_SHA256` after the description change lands.
6. **`server/schemas/search_papers_result.json::version`** bumps 2→3
   in lockstep (snippet-contract cross-check).
7. **No new MD files in `server/`, `ingest/`, `tests/`** — only
   under `.claude/`.
8. **No `anthropic` SDK** at runtime.
9. **MathML parsing security** — use `defusedxml` OR strip
   external-entity support from `lxml`. MathML from the corpus is
   "trusted local" but XXE-as-defense-in-depth is the project's
   posture.
10. **Pickle is banned** for this milestone's tree column (D2). JSON
    only.

---

## 6. Test surface

### AC coverage

- **AC1** — `find_equation("\\int_0^1 f(x) dx")` returns
  structurally similar integrals in the top-3. **Satisfied via the
  LaTeX-input fallback path**: the seeded test corpus contains an
  integral chunk; `dense_only_stmt_fallback` retrieves it. (Note in
  the test: the TED fusion path is exercised via the MathML-input
  AC3 test, not AC1.)
- **AC2** — TED score `\int_0^1 f(x) dx` vs `\int_a^b g(t) dt` <
  TED score either vs `\sum_{n=0}^\infty a_n`. Test computes TED
  directly on the three hand-crafted MathML fixtures; no LanceDB
  required.
- **AC3** — Raw MathML input goes through the TED path. Test seeds
  an in-memory `equations` table with a few rows, queries via the
  handler with raw MathML, asserts `retrieval_mode="ted_fused"` and
  that the structural match ranks first.
- **AC4** — Graceful fallback when `mathml_tree_json` column absent
  or all NULL. Test mounts a Resources stub with `equations_table=None`,
  asserts `retrieval_mode="dense_only_fallback"`, no exception.
- **AC5** — `pytest tests/test_equation_index.py` passes.

### Beyond-AC tests

- Parser determinism — MathML round-trips through `tree_to_json` →
  `tree_from_json` → recomputed TED == original TED.
- Fusion formula correctness — known cosine + TED inputs yield
  expected final scores.
- α weight respected — `alpha=1.0` collapses to pure-TED ranking;
  `alpha=0.0` collapses to pure-cosine ranking.
- Tree size cap — pathologically deep MathML (200+ nodes) doesn't
  blow stack or take > 5 seconds.

---

## 7. Suggested implementation order

1. `ingest/schema.py` — add `EQUATIONS_SCHEMA_V1` + table-name
   constants.
2. `server/retrieval/equations.py` — write the module. JSON round-trip
   first, then `EquationIndex.query`, then the fusion math, then
   integration glue.
3. `tests/fixtures/equations/*.mathml` — hand-crafted MathML for
   three canonical equations.
4. `tests/test_equation_index.py` — parser tests + fusion tests
   first; handler integration after Step 5.
5. `server/handlers/equation.py` — rewrite to dispatch to
   `EquationIndex` for MathML; keep current dense fallback for LaTeX.
6. `server/resources.py` — open `equations_table` at startup.
7. `server/config.py` — add `eq_ted_weight`.
8. `pyproject.toml` — add `zss`. Run `uv lock`. Verify license is
   MIT.
9. `ingest/index_equations.py` — light module: walk the equations
   table, populate `mathml_tree_json`. Not driven by any production
   ingest path at v1.
10. `server/tools.py` — description update + `TOOL_SCHEMA_VERSION`
    bump.
11. Re-pin three hash anchors:
    `pytest tests/test_server_tool_schema.py --update-tool-schema-hash`
    then manual `EXPECTED_BP1_SHA256` update.
12. `server/schemas/search_papers_result.json` — bump version + $id.
13. Run `make test`; commit.

---

## 8. Open questions remaining for the implementer

1. **MathML parser choice.** `lxml` vs `xml.etree.ElementTree` vs
   `defusedxml.ElementTree`. Recommend `defusedxml.ElementTree` —
   stdlib API, XXE-safe by construction, no compiled deps. `lxml`
   would also work but adds a system dep and the project doesn't
   currently use it.
2. **MathML namespace stripping.** MathML elements may be prefixed
   `m:math`, `mml:math`, etc. The parser should strip namespaces
   before building `zss.Node` labels so the same equation in two
   different namespace serializations produces the same tree.
3. **Whitespace normalization.** Stripping `xml:space="preserve"`
   blocks and collapsing internal whitespace before tree-building.
   Recommend pre-normalize then tree-build.
4. **Attribute stripping.** MathML elements carry presentation
   attributes (`mathvariant`, `mathcolor`, `displaystyle`, etc.).
   These are presentation noise and should be dropped before
   tree-building. Recommend strip ALL attributes — node labels are
   element tag names only.
5. **Pre-condition on `presentation_latex`.** Since the field
   doesn't exist in the corpus today, the indexer's input is just
   `mathml`. The test fixtures provide MathML directly.

---

## 9. External writes required

**None require gating.** Local-only writes:

| type | target | why |
|---|---|---|
| local | `pyproject.toml` | add `zss>=1.2.0` |
| local | `uv.lock` | `uv lock` regenerates the lockfile |
| local | `var/arxmcp/index/lancedb/equations.lance/` | new LanceDB table (created lazily at first ingest call) |

The `uv lock` step touches `pypi.org` once. The user has run the
project before so `pypi.org` access is established. No new external
authorization needed.

---

## 10. Done-when checklist

- [ ] `EQUATIONS_SCHEMA_V1` + `EQUATIONS_TABLE_NAME` in
      `ingest/schema.py`; tests assert the schema bytes are stable.
- [ ] `server/retrieval/equations.py::EquationIndex` ships with
      `query`, `parse_mathml_to_tree`, `tree_to_json`, `tree_from_json`.
- [ ] All 5 AC tests pass.
- [ ] Three hash anchors re-pinned together.
- [ ] `TOOL_SCHEMA_VERSION == 3`.
- [ ] `zss` MIT license verified before the dep is committed.
- [ ] `make test` green; ruff clean.
- [ ] Implementation summary explicitly notes that **H5 is partially
      open** — algorithm/API layer closed; data-population deferred.
- [ ] `retrieval_mode` taxonomy documented in the tool description.

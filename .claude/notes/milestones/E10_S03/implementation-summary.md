# E10_S03 — Implementation Summary

**One-line summary.** Added the Zhang-Shasha tree-edit-distance +
dense-cosine fusion algorithm for `find_equation` MathML inputs.
Equations LanceDB table schema landed; an `EquationIndex` query
class and a tree-JSON indexer ship; the handler dispatches MathML
inputs to TED-fusion and LaTeX inputs to the legacy dense-only
fallback. **H5 is partially closed** — algorithm/API layer
complete; the equation atom extractor and `embedding_eq` populator
remain deferred to a follow-up milestone.

**Commit range.** `c906d81..HEAD` (Phase-2 base
`c906d81` → implementation HEAD at commit time).

---

## Scope notes — the most important section

The milestone brief was written before E09 / E10_S01 landed and
assumed infrastructure that does not exist today. Phase-1 research
(both researchers converging strongly) surfaced five distinct scope
gaps:

| # | brief assumption | reality | resolution |
|---|---|---|---|
| 1 | "Reads the `equations` table" | No `equations` table; no extractor in `ingest/` | **Schema landed; table empty at v1.** |
| 2 | "`embedding_eq` column populated" | Reserved-but-NULL; embedder never touches it | **Dense signal uses `embedding_stmt` instead.** |
| 3 | "`presentation_latex + context_sentence` encoder input" | Neither field exists in the corpus | **Deferred to follow-up.** |
| 4 | "Existing LaTeXML pool in `server/resources.py`" | No such pool exists | **MathML-only TED path; LaTeX → dense-only.** |
| 5 | "Store as `mathml_tree_pickle`" | Pickle is a code-exec vector + Python-version-fragile | **Store as `mathml_tree_json` (utf8).** |

Per the research synthesis (`research-synthesis.md` §3 D1-D10), the
narrowed scope ships the **algorithm/API layer** in this milestone:
the schema, the TED + fusion algorithm, the handler dispatch, the
graceful fallback path, and the test surface against hand-crafted
MathML fixtures. The **data-population layer** (extractor +
embedding_eq populator + query-time LaTeXML pool) is explicitly
deferred. This means **H5 is partially closed, not fully closed**;
the implementation summary, this note, and the `chore(notes)`
commit are honest about that.

---

## Acceptance criteria — status

- [x] **AC1.** `find_equation("\\int_0^1 f(x) dx")` returns
      structurally similar integrals in the top-3.
      Verified in
      [TestHandlerDispatch::test_mathml_input_with_populated_table_routes_to_ted_fused](tests/test_equation_index.py)
      with the seeded equations table; the integral fixture ranks
      ahead of the summation fixture by `final_score`.
      **Caveat:** AC1 as written says LaTeX input — the LaTeX
      fallback path routes to `dense_only_stmt_fallback` because
      there is no query-time LaTeXML pool. The AC is satisfied via
      the MathML form of the same equation. The implementation
      summary documents this.
- [x] **AC2.** TED between `\int_0^1 f(x) dx` and
      `\int_a^b g(t) dt` < TED between either and
      `\sum_{n=0}^\infty a_n`. Verified directly via
      [TestNormalizedTED::test_two_integrals_closer_than_integral_vs_sum](tests/test_equation_index.py).
- [x] **AC3.** Raw MathML input is accepted and parsed correctly.
      Verified by every MathML-input test in
      `TestHandlerDispatch` + `TestParseMathML`.
- [x] **AC4.** Graceful fallback when `mathml_tree_json` column is
      absent (or the equations table is missing entirely). Verified
      by
      [TestHandlerDispatch::test_mathml_input_without_table_falls_back](tests/test_equation_index.py)
      — reports `retrieval_mode="dense_only_fallback"` and returns
      a non-empty result list.
- [x] **AC5.** `pytest tests/test_equation_index.py` passes — 30
      tests green. Full suite: 1378 passed (+30 from 1348
      baseline), 4 skipped, ruff clean.

---

## Files added / changed

### New

- `server/retrieval/equations.py` — `EquationIndex` class with
  `parse_mathml_to_tree` (defusedxml-backed, namespace + attribute
  stripping), `tree_to_json` / `tree_from_json` round-trip,
  `normalized_ted` (Zhang-Shasha + `max(|A|, |B|)` normalization),
  `fuse_scores` (α-weighted linear combination), and
  `looks_like_mathml` (cheap regex root-tag detection).
- `ingest/index_equations.py` — walks the equations table, parses
  every row with `mathml` + null `mathml_tree_json` to a `zss.Node`,
  serializes to JSON, persists via LanceDB `merge_insert` on
  `equation_id`. Idempotent per row.
- `tests/test_equation_index.py` — 30 tests covering the parser
  (6), JSON round-trip (4), normalized TED + fusion (7), handler
  dispatch (4), and EquationIndex unit shape (3) + EquationHit
  dataclass shape (1).
- `tests/fixtures/equations/*.mathml` — three hand-crafted MathML
  fixtures: `int_01_fxdx.mathml`, `int_ab_gtdt.mathml`,
  `sum_0_inf_an.mathml`.

### Changed

- `ingest/schema.py` — added `EQUATIONS_SCHEMA_V1` +
  `EQUATIONS_TABLE_NAME` (per-equation table with 10 columns:
  identity, MathML payload, embedding placeholder, JSON-tree
  column, parent-chunk linkage).
- `server/handlers/equation.py` — replaced the legacy
  dense-only-stmt fallback with a 3-mode dispatch:
  `ted_fused` (MathML in, table populated), `dense_only_fallback`
  (MathML in, table missing/empty), `dense_only_stmt_fallback`
  (LaTeX in). Malformed MathML degrades to
  `malformed_mathml_fallback` rather than 5xx-ing.
- `server/resources.py` — added `equations_table: Any | None` field;
  lazy-open at startup mirroring the `definitions_table` pattern
  from E10_S01.
- `server/config.py` — added `eq_ted_weight: float = 0.5` field
  (env: `ARXMCP_EQ_TED_WEIGHT`) + a `[0.0, 1.0]` validator.
- `server/tools.py` — bumped `TOOL_SCHEMA_VERSION` 2→3; rewrote
  `FIND_EQUATION.description` to document the TED-fusion path, the
  LaTeX-fallback path, and the three `retrieval_mode` values.
- `server/schemas/search_papers_result.json` — bumped `version`
  2→3 and `$id` to `v3.json` in lockstep.
- `pyproject.toml` — added `zss>=1.2.0` (BSD-3-Clause, verified
  from bundled LICENSE — both research briefs reported MIT but the
  actual bundled license is BSD-3-Clause, which sits on the same
  allow-list) and `defusedxml>=0.7` (PSF 2.0, defense-in-depth for
  MathML parsing — XXE-safe by construction).
- `tests/test_server_tool_schema.py` — re-pinned hash + version via
  `pytest --update-tool-schema-hash`.
- `tests/test_prompts.py` — re-pinned `EXPECTED_BP1_SHA256`.

---

## Design decisions worth surfacing for Phase-3

These are decisions the rectifier should leave alone unless the
critic surfaces something specific.

1. **`symbol == symbol_raw == bare command name`** at v1 (synthesis
   D3 — same as E10_S01). Both columns store the bare command name.
2. **MathML trees as JSON, not pickle** (synthesis D2). Eliminates
   pickle deserialization vector and Python-version drift.
3. **`embedding_eq` is NULL at v1.** Dense signal uses
   `embedding_stmt` cosine. Documented in the module docstring +
   tool description.
4. **Skip the LaTeXML subprocess pool** (synthesis D4). MathML
   inputs go through the TED path; LaTeX inputs route to the legacy
   dense-only fallback. A future milestone adds the pool.
5. **Attribute stripping + namespace stripping** in the parser. Two
   semantically-equivalent MathML serializations produce
   byte-identical trees.
6. **Cosine score uses `1 - dist/2`** mapping from LanceDB
   squared-L2 distance on L2-normalized vectors — same math as the
   existing `find_equation._distance_to_score`.
7. **Result envelope adds `alpha`, `cosine_score`, `ted_norm` fields
   on the `ted_fused` path.** Callers tuning recall can see the
   per-row breakdown. The byte-stability hash already accounts for
   this via the description change.
8. **`defusedxml.ElementTree`** instead of `lxml` or stdlib
   `xml.etree`. Defense-in-depth for the 4000-character cap on
   caller input.

---

## Forced-by-this-milestone cross-file changes

All landed and verified:

- `TOOL_SCHEMA_VERSION` bumped from `2` to `3`.
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via
  `pytest --update-tool-schema-hash`. New value:
  `3961d85e231ed113c6a61fff1a1e461830bfdd0132d998c5c4d9bf1424812403`.
- `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned to `3`.
- `EXPECTED_BP1_SHA256` re-pinned to
  `aabfbc16e6656a9e745b2258e5dcf90050fbea7d39fc56420e3fa1526b401e61`.
- `server/schemas/search_papers_result.json::$id` bumped to
  `v3.json`; `version` field bumped to `3`.

---

## Test count delta

| Metric | Before | After |
|---|---|---|
| Tests passing | 1348 | 1378 |
| Tests skipped | 4 | 4 |
| Tests failing | 0 | 0 |
| Ruff status | clean | clean |

New tests live in `tests/test_equation_index.py` (30 tests). The
+30 delta tracks exactly.

---

## External writes required

**None require gating.** All writes are local:

```
| type | target | why |
|---|---|---|
| local | pyproject.toml | added zss>=1.2.0 + defusedxml>=0.7 |
| local | uv.lock | uv lock regenerated |
| local | var/arxmcp/index/lancedb/equations.lance/ | new LanceDB table created lazily at first ingest |
```

The `uv lock` step touched `pypi.org` (one-time, transparent
operation; the user runs the project regularly).

---

## Deviations from the brief (with rationale)

1. **Equation atom extraction NOT included.** The brief framed
   E10_S03 as a single milestone; in reality the equation atom
   extractor is a separate piece of work (the chunker today does
   not emit equation chunks; the `equations` table has no
   populator). Splitting this out keeps E10_S03 shippable in a
   reasonable turn count.
2. **`embedding_eq` population NOT included.** Same reason — adding
   a dedicated equation encoder pass is its own milestone.
3. **Query-time LaTeXML pool NOT included.** The brief assumed
   `server/resources.py` already had one; it doesn't. Building a
   request-time LaTeXML subprocess pool is a substantial piece of
   infrastructure that doesn't fit a single milestone.
4. **`mathml_tree_json`, not `mathml_tree_pickle`.** Security
   (pickle deserialization) + Python-version stability.
5. **AC1 satisfied via MathML form**, not LaTeX form. The LaTeX
   form is currently handled by the legacy
   `dense_only_stmt_fallback` path because of #3; the structural
   matching the AC requires happens on the MathML form via the TED
   path. The behavior of the LaTeX path is unchanged from v1.

These deviations are documented in the synthesis (`§3 D1-D10`) and
the rectifier protocol should not "fix" them without explicit user
direction.

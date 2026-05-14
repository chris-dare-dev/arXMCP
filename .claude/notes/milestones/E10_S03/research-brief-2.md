# E10_S03 Research Brief 2 — Integration Surface Focus

**Angle:** Concrete code reading + threat surface + external package due diligence.
Companion to Brief 1 (design notes / architecture focus).

---

## 1. Equation extraction in the chunker — what actually exists

The chunker (`ingest/chunker.py`) does NOT emit equation-level chunks. It is a
theorem/proof structural extractor. Equations appear only incidentally via
`_element_text()` (lines 282–315), which replaces each `<math alttext="...">` DOM
element with `$<alttext>$` (verbatim LaTeX, no MathML). Key implications:

- **No `presentation_latex` field exists on `ChunkRecord`.** The brief says the
  equation encoder runs over `presentation_latex + context_sentence`, but neither
  field exists in the codebase. `ChunkRecord` has `body_text` (LaTeX-interspersed
  prose) only.
- **No `equations` LanceDB table exists.** `schema.py` declares `CHUNKS_SCHEMA_V1`
  and `DEFINITIONS_SCHEMA_V1`; there is no `EQUATIONS_SCHEMA` or
  `EQUATIONS_TABLE_NAME` constant anywhere in the repo. The brief's indexer
  (`ingest/index_equations.py`) says "reads `equations` table" — but this table
  must be created from scratch by E10_S03. It is not a pre-existing artifact.
- **`embedding_eq` column is in `CHUNKS_SCHEMA_V1`** (`schema.py` line 107–114),
  always NULL, reserved for this milestone. The embedder explicitly states "never
  populates it" (embedder.py docstring line 20–21). This column is on `chunks`,
  not on a separate `equations` table.

This is a scope discrepancy: the brief describes an `equations` table as
pre-existing input to the indexer, but no such table exists. The implementation
must either (a) extract equations from the parsed HTML at ingest time and
write them to a new `equations` table, then build tree pickles from that, OR
(b) extract MathML directly from the chunker's LaTeXML HTML5 output at
index time using BeautifulSoup. Option (b) avoids the new table and is
more consistent with the existing architecture.

---

## 2. The LaTeXML subprocess pool — critical gap

The brief says "reusing the existing pool from `server/resources.py`." After
exhaustive search: **no LaTeXML subprocess pool exists in `server/resources.py`
or anywhere in the server package.**

`server/resources.py` owns: BGE-M3 embedder, LanceDB handle, BGE-reranker,
BM25Phase, ANNPhase, RerankPhase, RetrievalCache, and definitions_table. Zero
LaTeXML subprocess management.

LaTeXML exists only in `tools/arxiv_fetch.py::parse_with_latexml()`:
```python
proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
    ["latexmlc", str(main_tex.name), f"--dest={out_html}", "--format=html5"],
    cwd=main_tex.parent, capture_output=True, text=True, timeout=timeout,
)
```

This is a batch ingest function, not a request-time pool. For the
`find_equation` query path (step 1: "parse `latex_or_mathml` to MathML"), the
implementation must choose:

- **Option A (recommended):** Pre-detect whether input is MathML at the handler
  boundary (`<math` prefix check), skip LaTeXML for all inputs without it, and
  require operators to provide MathML directly for the TED path. The brief says
  "MathML input is accepted and parsed correctly" — so raw MathML input bypasses
  LaTeXML entirely. For LaTeX input, fall back to dense-only (already the current
  behavior) OR spawn `latexmlc` synchronously (BLOCKING, up to 30s timeout).
- **Option B (defer):** Build a real request-time LaTeXML pool. This is a large
  scope add: asyncio subprocess pool, warm-up on startup, pool size in config,
  process crash recovery. This is E11-scope infrastructure.

**Recommendation:** Ship with "MathML input → TED fusion; LaTeX input → dense-only
fallback + warn." The `retrieval_mode` field communicates which path was taken.
Add a `ARXMCP_LATEXML_QUERY_POOL` config stub for future E11 wiring.

---

## 3. `zss` package — due diligence

- Latest version: **1.2.0** (PyPI). Last release: **2018-03-12**.
  GitHub: `timtadh/zhang-shasha`. No license field in PyPI metadata; the
  GitHub repo license is **MIT** (confirmed from README in repo history).
- `apted`: version 1.0.3, last release 2017-11-08. MIT. Both packages are
  effectively unmaintained.

**Performance:** Zhang-Shasha is `O(|T1|·|T2|·min(L1,D1)·min(L2,D2))`. For
typical LaTeXML MathML trees of 50–150 nodes (integral: ~40 nodes; summation:
~30 nodes; complex aligned equation: ~200 nodes), a rough upper bound for
50 × 200 nodes: `200 * 200 * 100 * 100 = 400M` operations per pair —
that is a naive pessimistic bound. In practice, `zss` benchmarks show
~0.1–0.5 ms per pair for trees under 100 nodes (Python overhead dominates).
At 200 candidates × 0.5ms = 100ms per query. Acceptable for a "Tier 4" index.

**Alternative: `apted`.** APTED (Augmented PTED) is theoretically faster than
Zhang-Shasha for unbalanced trees and has better worst-case guarantees. However
its Python package (`apted` 1.0.3) is equally stale, has the same MIT license,
and would require the same Node-builder boilerplate. Stick with `zss` (the
brief specifies it by name; changing would require an explicit design decision).

**pyproject.toml dep comment** must follow the project's per-line comment
discipline:
```toml
# zss: Zhang-Shasha tree-edit distance over MathML parse trees (E10_S03).
#   MIT-licensed; last release 2018-03-12 (maintenance-frozen but stable
#   for this narrow use case). No compiled deps; pure Python. Used only
#   in ingest.index_equations (build-time) and server.retrieval.equations
#   (query-time). A compiled replacement (APTED via C extension) is a
#   future optimization.
"zss>=1.2.0",
```

---

## 4. Pickle deserialization threat + JSON tree alternative

The brief proposes `mathml_tree_pickle` — a column storing `pickle.dumps(zss.Node)`.
This is a security smell even in single-user deployment. Python pickle is a
code-execution vector if the database file were modified by a third party.
More practically: pickle format changes across Python minor versions can silently
corrupt the column on a Python upgrade (e.g. 3.11 → 3.12 pickle protocol shift).

**Recommendation: use a JSON-serializable tree representation instead.**
`zss.Node` has exactly two fields: `label: str` and `children: list[Node]`.
The recursive JSON form is:
```json
{"label": "mrow", "children": [{"label": "mi", "children": []}, ...]}
```
A round-trip is O(N) and trivial to implement:
```python
def node_to_dict(n: zss.Node) -> dict:
    return {"label": n.label, "children": [node_to_dict(c) for c in n.children]}

def dict_to_node(d: dict) -> zss.Node:
    return zss.Node(d["label"], [dict_to_node(c) for c in d["children"]])
```
Column name: `mathml_tree_json` (utf8 column, nullable). Survives Python upgrades,
is human-inspectable, and eliminates the pickle deserialization attack surface.
The LanceDB schema for the `equations` table should declare it as `pa.utf8()`.

---

## 5. Schema: equations table vs embedding_eq column

The brief conflates two separate concepts:
- The `equations` table: stores per-equation MathML + tree representation + chunk linkage.
- The `embedding_eq` column on `chunks`: stores the 1024-dim equation embedding.

These are separate concerns. The equations table is where MathML-based TED
operates. The `embedding_eq` column on `chunks` is where dense cosine operates.
The fusion algorithm needs both.

However: **the `embedding_eq` column is always NULL today.** Populating it
requires running BGE-M3 over `presentation_latex + context_sentence`. But
`presentation_latex` is not extracted by the current chunker (the alttext is
embedded in `body_text` as `$...$` prose). This is a genuine scope gap:
E10_S03 either (a) defines a new extraction pass for equations from LaTeXML HTML
that produces clean `presentation_latex`, or (b) uses `body_text` as the
equation encoder input (less clean but available). Option (b) is correct for v1
— it reuses the existing embedding infrastructure without a new extraction pass.

**Concrete implication:** the `embedding_eq` column on `chunks` should NOT be
populated by E10_S03's indexer. Instead, the dense cosine ANN pass should
reuse `embedding_stmt` (the existing behavior of the fallback handler). The
`equations` table stores MathML-derived tree JSON; the ANN pass queries
`embedding_stmt`. This means the fusion formula uses cosine over `embedding_stmt`
(not `embedding_eq`) until a dedicated equation encoder is trained (E11+).

---

## 6. TOOL_SCHEMA_VERSION bump and BP1 update

`TOOL_SCHEMA_VERSION` is currently `2` (set in E10_S01). This milestone will
change `find_equation`'s `description` string (to remove the "v1 dense-only
fallback" warning) and may change the response shape (`retrieval_mode` value).
Both changes require:
1. Bump `TOOL_SCHEMA_VERSION: int = 2` → `3` in `server/tools.py`.
2. Run `pytest tests/test_server_tool_schema.py --update-tool-schema-hash`.
   This rewrites both `EXPECTED_TOOL_SCHEMA_SHA256` and
   `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`.
3. Manually update `EXPECTED_BP1_SHA256` in `tests/test_prompts.py` if the
   `FIND_EQUATION` description string changes (BP1 byte-stability contract).

The `retrieval_mode` values need naming conventions:
- `"ted_fused"` — MathML input, TED + dense fusion active.
- `"dense_only_stmt_fallback"` — LaTeX input (no LaTeXML pool), dense over `embedding_stmt` (current).
- `"dense_only_fallback"` — MathML input but `mathml_tree_json` column absent in equations table.

---

## 7. LaTeXML deployment model

`parse_with_latexml()` calls `shutil.which("latexmlc")` at runtime and raises
`RuntimeError` if absent. LaTeXML is a system-level Perl package. The Dockerfile
(`docker/Dockerfile.server`) must install it if query-time parsing is added.
Per CLAUDE.md: "local-first, single-workstation." The operator installs LaTeXML
via `brew install latexml` (macOS) or `apt install latexml` (Debian/Ubuntu).
No Docker sidecar. The `docs/install.md` must be updated to list `latexmlc` as
a required system dependency IF query-time LaTeX parsing is added.

---

## Open questions

1. **`equations` table creation from scratch.** The indexer brief says "reads
   `equations` table" as if pre-existing. It doesn't exist. Should `ingest/index_equations.py`
   be a FROM-HTML extraction pass (reads LaTeXML-parsed HTML, extracts `<math>` elements,
   writes `equations` table) PLUS a tree-pickle/JSON builder? Recommend yes: two
   phases in one script: (1) extract + write equations table from LaTeXML HTML,
   (2) parse MathML in each row and write `mathml_tree_json`. This clarifies
   the scope boundary vs the brief.

2. **`embedding_eq` population is out of scope for E10_S03.** The column remains
   NULL. Dense cosine in the fusion formula should use `embedding_stmt` as proxy.
   This is not a regression — it is the same signal as the current dense-only
   fallback. E10_S03's value-add is exclusively the TED component. The implementor
   must be explicit in docs that `embedding_eq` is still NULL after E10_S03.

3. **Test fixture source: hand-crafted vs live LaTeXML.** For the AC test
   (`\int_0^1 f(x) dx` vs `\sum_{n=0}^\infty a_n`), use hand-crafted MathML
   fixture files in `tests/fixtures/`. Reason: live LaTeXML in tests requires
   `latexmlc` on the test runner PATH, which adds a system dep to `pytest`.
   Mark those tests `requires_latexml` (a new marker) and have them skip if
   `shutil.which("latexmlc") is None`. The TED comparison test uses
   hand-crafted MathML and has no system dep.

4. **`retrieval_mode` tag for the TED-fused path.** Use `"ted_fused"` (not
   `"ted_cosine_fusion"` or similar). Aligns with the project's short snake_case
   convention from `"dense_only_stmt_fallback"`.

5. **`assert` ban applies.** `ingest/index_equations.py` and
   `server/retrieval/equations.py` must use `if ... raise RuntimeError(...)` for
   all invariant checks. The project bans `assert` (CLAUDE.md §4.7).

6. **Pickle vs JSON is a deploy-or-skip question.** Do this in E10_S03 — not as
   a follow-on. Storing `mathml_tree_json` (utf8) costs ~3× size vs pickle
   but eliminates the Python-version-upgrade corruption vector entirely. The
   `equations` table has no existing data to migrate.

---

## External writes the implementation will require

- `pyproject.toml`: add `zss>=1.2.0` with the per-line comment from §3 above.
- `ingest/schema.py`: add `EQUATIONS_TABLE_NAME = "equations"` and `EQUATIONS_SCHEMA_V1`.
- `server/config.py`: add `ARXMCP_EQ_TED_WEIGHT: float = 0.5` config field.
- `docs/install.md`: add `latexmlc` system dep note IF query-time LaTeX parsing is scoped in.

No changes to `server/resources.py` startup sequence unless the LaTeXML pool is
added (recommended against for E10_S03 scope).

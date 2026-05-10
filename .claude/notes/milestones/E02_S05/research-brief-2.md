# Research Brief 2 — E02_S05: Chunker Fixture Suite

## 1. In-codebase context

### The corpus materialization problem

`var/arxmcp/corpus/parsed/` is not present in this worktree. Every prior E02 milestone
deferred the "50-paper integration" acceptance criterion with the same note: corpus not
materialized, requires user verification after `make ingest`. E02_S01 summary: "Running on
all 50 seed papers produces ≥300 chunks ✗ DEFERRED — Parsed corpus not materialized in
this worktree." E02_S02 summary: "Preamble extractor produces a `preamble.json` for each of
the 50 seed papers ✗ DEFERRED." E02_S04 summary: "`chunk_manifest.json` exists for every
paper after a chunker run — Pass on fixture — 50-paper integration deferred to user
verification." E02_S05 cannot break this pattern: "10 of the 50 seed papers" means
hand-crafted HTML fixtures, not live corpus papers.

### Existing fixtures and scenarios covered

Four hand-crafted fixtures exist at `tests/fixtures/chunker/<paper_id>/index.html`:

| Fixture | Scenario covered |
|---|---|
| `2307.00001` | Two-theorem golden: explicit label + display name, auto-id, 2 stmt + 2 proof |
| `2307.00002` | Multi-kind: definition, remark, lemma+proof, corollary, example, orphan proof, section chunk |
| `2307.00003` | Long-proof window splitting: placeholder text `LONG_PROOF_PLACEHOLDER` swapped at test time — the HTML is NOT self-contained for a static fixture |
| `2307.00004` | Malformed HTML graceful degradation: unclosed divs, empty proof body |

Fixture `2307.00003` is notable: `TestProofWindowSplitting` in `test_chunker.py` uses
`self._build_long_proof_html(paper_id, word_count=400)` to generate the HTML
programmatically at runtime — the on-disk `index.html` contains a literal placeholder
`LONG_PROOF_PLACEHOLDER` that is never replaced by the current `chunk_paper` path (it just
produces one short proof chunk). The multi-window scenario is tested via that programmatic
method, NOT via the 2307.00003 HTML file as a static fixture. A static golden-output fixture
for the multi-window proof scenario requires a new HTML file with actual long body text
baked in, not a placeholder.

### The `expected_chunk_ids` schema and content-addressability

The E02_S05 schema calls for:
```json
{
  "paper_id": "2307.00001",
  "chunk_count": 4,
  "kind_counts": {"stmt": 2, "proof": 2, "section": 0, "definition": 0},
  "expected_chunk_ids": ["arxiv:2307.00001:<hex16>"],
  "chunker_version": "v1.0"
}
```

The chunk_id formula (from `_compute_chunk_id`):
```python
f"arxiv:{paper_id}:{sha256((preamble_text + NFC(body_text)).encode('utf-8')).hexdigest()[:16]}"
```

A "verified expected_chunk_id" is self-bootstrapped: run the chunker once on the
hand-crafted HTML (with `_resolve_preamble_doc` returning None, so `preamble_text=""`),
record the output, commit it. The test then re-runs the chunker and asserts the recorded ids
match. This is exactly the `TestChunkIDDeterminism::test_two_runs_same_paper_identical_ids`
pattern from `test_chunker_ids.py` elevated to fixture-file form.

Because `preamble_text=""` in all hand-crafted fixtures (no `.tex` source in
`var/arxmcp/corpus/raw/` for fake paper IDs), the hash reduces to
`sha256(NFC(body_text).encode("utf-8")).hexdigest()[:16]`. Implementer must patch
`_resolve_preamble_doc` to return None when generating and when re-verifying fixture IDs,
or the hash will diverge on a machine that somehow has preamble files for these fake IDs.

### Test structure: existing class names

`test_chunker.py` contains: `TestTwoTheoremGolden`, `TestMultiKindEnvironments`,
`TestProofWindowSplitting`, `TestMalformedHTML`, `TestChunkRecord`,
`TestChunkFailureIsolation`, `TestStatementTokenBudget`, `TestF1`–`TestF13` regression
guards. `test_chunker_ids.py` contains: `TestChunkIDFormat`, `TestChunkIDDeterminism`,
`TestChunkerVersionConstant`, `TestChunkManifest`, `TestOutputFilenames`,
`TestSingleVersionDefinition`, `TestF1FailureLeavesEmptyDir`, `TestF2*`, `TestF5*`.

### CI integration

`make test` already runs `$(PYTHON) -m ruff check . && $(PYTHON) -m pytest` with no test
file filter — pytest autodiscovers `tests/test_chunker.py`. Adding `TestFixtureSuite` to
the existing `test_chunker.py` (or a new `test_chunker_fixtures.py`) is sufficient for CI.
No Makefile changes are needed.

### The `transformers` dependency

The BGE-M3 tokenizer (`_get_tokenizer()`) does a lazy `from transformers import
AutoTokenizer` — not installed in the current shell environment (`No module named
'transformers'`). Tests that call `chunk_paper` on an HTML that contains theorems
triggering `_truncate_to_token_budget` will fail in a minimal env without `transformers`.
The existing test suite passes CI only because `pyproject.toml` lists
`transformers>=4.40` as a project dependency and `make test` runs against the installed
dev environment. Golden-output fixture tests must assume the same installed env.

## 2. Prior decisions and lessons

**Empty-string preamble fallback (F3).** `_resolve_preamble_doc` returns `None` when
preamble extraction fails (E02_S02 F3). In `_chunk_paper_impl`:
```python
preamble_text = preamble_doc.preamble_text if preamble_doc is not None else ""
```
All hand-crafted fixtures use fake `2307.0000x` paper IDs with no real `.tex` source, so
`extract_preamble` will raise `FileNotFoundError` → preamble_doc = None →
`preamble_text = ""`. This is the production fallback path. Golden chunk IDs for these
fixtures are therefore `sha256(NFC(body_text))[:16]`-based.

**`*.json` cleanup glob.** The line:
```python
for stale in out_dir.glob("*.json"):
    stale.unlink()
```
runs at the TOP of `_chunk_paper_impl` before any chunk assembly (F1 closure). The fixture
test harness must not leave a `<paper_id>` directory pre-populated with stale JSON between
test parametrize runs.

**`chunk_manifest.json` schema.** Written by `_write_chunk_manifest` after all per-chunk
JSON files:
```json
{"chunker_version": "v1.0", "chunks": [{"chunk_id": "...", "kind": "..."}], "paper_id": "..."}
```
(keys sorted). The fixture `.expected.json` schema mirrors this at a coarser level
(`chunk_count`, `kind_counts`, `expected_chunk_ids`).

**E02_S04 manifest schema (F1+F2 closures).** TestChunkManifest already validates that
`chunk_manifest.json` exists, lists every emitted chunk_id, has sorted keys, and is replaced
atomically on re-run. The fixture test should NOT re-test the manifest format — only the
golden `chunk_count`, `kind_counts`, and `expected_chunk_ids` fields.

## 3. External sources

None required. This milestone is test infrastructure only; all design decisions flow from the
existing codebase.

---

## Open questions

**(a) "10 of the 50 seed papers" — expand fixtures vs. use real corpus.**
The only viable interpretation is to expand from 4 hand-crafted HTML fixtures to 10. The
corpus is not materialized. The six new fixtures should be added under
`tests/fixtures/chunker/2307.000{05,06,07,08,09,10}/index.html` with distinct LaTeXML HTML
content. Each fixture should be the minimal HTML that exercises the target scenario, not a
real paper's full parse tree. Trying to use real ar5iv HTML is risky: ar5iv parse trees
change across LaTeXML versions (the brief's "risk note: pin the LaTeXML version").

**(b) Class names: bump into a unified `TestFixtureSuite` vs. keep per-class structure.**
Recommendation: add a new `TestFixtureSuite` class that is parametrized over all 10 fixture
IDs and drives a uniform golden-output check (chunk_count, kind_counts, expected_chunk_ids).
The existing `TestTwoTheoremGolden`, `TestMultiKindEnvironments`, etc. stay as-is —
they test behavioral properties, not golden output. The new class tests the committed
expected values. This keeps existing tests stable and gives the fixture-suite its own
entry point for the CI timing requirement (< 60 s for 10 papers).

**(c) Multi-window proof fixture — is `2307.00003` sufficient?**
No. The current `tests/fixtures/chunker/2307.00003/index.html` contains a placeholder
`LONG_PROOF_PLACEHOLDER` — it is not a self-contained static fixture. A new fixture (e.g.
`2307.00007`) must have actual long text baked into the HTML (≥512 BGE-M3 tokens of proof
body) so the golden chunk_count includes multiple proof windows. The simplest approach is
to generate ~600 synthetic alphanumeric tokens inline in the HTML, identical to what
`TestProofWindowSplitting._build_long_proof_html` does but committed as a static file.

**(d) Scenario coverage for the six new fixtures.**
Minimum recommended scenarios for fixtures 5–10:
- `2307.00005`: proposition + conjecture environment kinds (exercises `ltx_theorem_proposition`, `ltx_theorem_conjecture`)
- `2307.00006`: deeply nested subsection path (section > subsection > subsubsection)
- `2307.00007`: multi-window proof (long proof body baked in; satisfies acceptance criterion)
- `2307.00008`: definition-heavy, no `ltx_proof` at all (exercises section/definition path; satisfies acceptance criterion)
- `2307.00009`: appendix section after main sections (tests section ordering)
- `2307.00010`: paper with MathML `alttext` throughout (exercises `_element_text` LaTeX preservation)

## External writes the implementation will require

All local writes only:

| Path | Why |
|---|---|
| `tests/fixtures/chunker/2307.000{05..10}/index.html` | Six new hand-crafted HTML fixtures |
| `tests/fixtures/chunker/2307.000{01..10}.expected.json` | 10 golden-output files (bootstrapped by running chunker once) |
| `tests/test_chunker.py` (or new `tests/test_chunker_fixtures.py`) | `TestFixtureSuite` parametrized class |
| `docs/chunker-fixtures.md` | Required deliverable: scenario coverage notes + regeneration procedure |

No changes to `ingest/chunker.py`, `ingest/chunker_types.py`, `Makefile`, or
`pyproject.toml` are needed (CI already runs `pytest` via `make test`).

# Research Brief — E02_S05: Chunker fixture suite

*Researcher 1 of 2 — independent brief*

---

## 1. In-codebase context

### The "10 of the 50 seed papers" problem

The milestone brief says "10 of the 50 seed papers" but `var/arxmcp/corpus/parsed/` is not materialized in this worktree. This is not a new constraint — every prior E02 milestone deferred the 50-paper integration criterion with identical wording:

> "Running on all 50 seed papers produces ≥300 chunks — DEFERRED. Parsed corpus not materialized in this worktree." (E02_S01 implementation summary)

> "Preamble extractor produces a preamble.json for each of the 50 seed papers — DEFERRED." (E02_S02 implementation summary)

> "chunk_manifest.json exists for every paper after a chunker run — Pass on fixture — 50-paper integration deferred to user verification." (E02_S04 implementation summary)

The worktree has exactly four hand-crafted HTML fixtures under `tests/fixtures/chunker/<paper_id>/index.html`. These are the only materialized parse trees. Any E02_S05 implementation must either (a) add six more hand-crafted fixtures to reach 10, or (b) defer the corpus-based approach to the user.

### Existing fixtures and scenarios covered

`tests/fixtures/chunker/2307.00001/index.html` — **Two-theorem golden.** Two `ltx_theorem_theorem` divs, each followed immediately by an `ltx_proof` sibling. Exercises: matched theorem+proof pair, custom `theorem_label` ("myresult1"), parenthetical `theorem_name` ("Riemann–Roch"), auto-id (no theorem_label), nested `ltx_subsection`. Chunk count: exactly 4 (2 stmt + 2 proof). No section prose above `MIN_SECTION_TEXT_CHARS = 80`, so no section chunks.

`tests/fixtures/chunker/2307.00002/index.html` — **Multi-kind environments.** Has `ltx_theorem_definition`, `ltx_theorem_remark`, `ltx_theorem_lemma` (with id="key-lemma" — custom label), `ltx_theorem_corollary`, `ltx_theorem_example`, an unmatched theorem (a remark between Theorem 2.1 and its proof, making the proof an orphan), and section-level prose. Exercises: definition, remark, lemma, corollary, example kinds, orphan proof, section chunk, no-explicit-proof definition path.

`tests/fixtures/chunker/2307.00003/index.html` — **Long-proof window splitting.** A single `ltx_theorem_theorem` with a paired proof that contains the literal string `LONG_PROOF_PLACEHOLDER`. This fixture is NOT self-contained: `TestProofWindowSplitting::test_proof_chunks_emitted_from_full_paper` builds its HTML inline at `paper_id = "2307.00099"` and does not use the fixture file at all. Fixture 2307.00003 as written produces only a stmt chunk with a trivial proof body — it is a stub, not a multi-window fixture in practice. (The actual multi-window test is `TestProofWindowSplitting._build_long_proof_html` which generates HTML inline for paper_id "2307.00099".)

`tests/fixtures/chunker/2307.00004/index.html` — **Malformed HTML graceful degradation.** An unclosed `<div>` and a definition with no closing tag, relying on `html.parser` auto-close. Exercises: no crash on malformed HTML, at least one chunk extracted, empty-body proof emitted.

### Scenario gaps for E02_S05 (six new fixtures needed)

Scenarios not yet covered by a fixture-backed test (only by inline HTML or `_chunks_from_html`):

1. **Multi-section document order** — currently in `TestF4SectionDocumentOrder` with inline HTML (paper_id "2307.99001"). No fixture file.
2. **Stmt truncation flag** — in `TestF5StmtTruncationFlag` with inline HTML (paper_id "2307.99005"). No fixture file.
3. **Deep recursion bound** — in `TestF13RecursionDepthBound` with inline HTML (paper_id "2307.99013"). No fixture file.
4. **Duplicate content de-dup** — in `TestF2DuplicateContentDeduped` with inline HTML (paper_id "2307.99002"). No fixture file.
5. **Proposition kind** — `_THEOREM_ENV_KINDS` maps "proposition" and "prop" to "proposition", not currently exercised by any fixture.
6. **No `\begin{proof}` at all (purely definition-heavy paper)** — Fixture 2307.00002 has definitions without proofs in Section 1, but it also has an orphan proof and a remark-blocked theorem. A cleaner fixture would have only definitions, lemmas without proofs, and section prose — zero `ltx_proof` divs — specifically to exercise the "no-proof paper" acceptance criterion.

### `expected_chunk_ids` schema and how to generate them

The milestone brief schema is:

```
{paper_id, chunk_count, kind_counts: {stmt, proof, section, definition}, expected_chunk_ids: ["arxiv:..."], chunker_version: "v1.0"}
```

The formula from `_compute_chunk_id` (chunker.py line 955):

```python
arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text)).hexdigest()[:16]>
```

For the hand-crafted fixtures, `_resolve_preamble_doc` returns None (no `.tex` file exists alongside the fixture HTML), so `preamble_text = ""`. This means:

```python
chunk_id = f"arxiv:{paper_id}:{hashlib.sha256(unicodedata.normalize('NFC', body_text).encode('utf-8')).hexdigest()[:16]}"
```

"Verified expected chunk_id" means: run `_run_no_preamble(tmp_path, paper_id)` once on the hand-crafted fixture (patching `_resolve_preamble_doc` to return None, which is what the real run also does for files with no `.tex`), record the output chunk_ids, and commit them as `expected_chunk_ids`. The chunk_ids are deterministic by construction.

### Existing test structure

`tests/test_chunker.py` has: `TestTwoTheoremGolden`, `TestMultiKindEnvironments`, `TestProofWindowSplitting`, `TestTheoremLabelExtraction`, `TestTheoremNameExtraction`, `TestSectionPathExtraction`, `TestOrphanProof`, `TestUnmatchedTheorem`, `TestMalformedHTML`, `TestChunkRecord`, `TestChunkFailureIsolation`, `TestStatementTokenBudget`, `TestF1MathMLPreservation` through `TestF13RecursionDepthBound`.

`tests/test_chunker_ids.py` has: `TestChunkIDFormat`, `TestChunkIDDeterminism`, `TestChunkerVersionConstant`, `TestChunkManifest`, `TestOutputFilenames`, `TestSingleVersionDefinition`, `TestF1FailureLeavesEmptyDir`, `TestF2DuplicateContentDeduped`, `TestF2CollisionRaises`, `TestF5FreshProcessDeterminism`.

The existing classes each have 3–15 individual test methods. The new fixture suite could be a single `TestFixtureSuite` parametrized over 10 fixture IDs, or it could add named per-paper test classes. The parametrized approach is more maintainable.

### `chunk_manifest.json` and the `*.json` cleanup glob

From `_chunk_paper_impl`:

```python
for stale in out_dir.glob("*.json"):
    stale.unlink()
for stale in out_dir.glob("*.tmp"):
    stale.unlink()
```

The `chunk_manifest.json` is swept by `*.json` on re-run, then rewritten at the end of a successful run via `_write_chunk_manifest`. The fixture tests can read `chunk_manifest.json` to verify `chunk_count` and `kind_counts` rather than parsing individual chunk JSON files — this is cleaner for the golden-output framework.

### LaTeXML version pinning

`pyproject.toml` does not currently pin a LaTeXML version (LaTeXML is not a Python package — it's a Perl tool). The risk note says "pin the LaTeXML version." For hand-crafted fixtures this risk is moot: the HTML is authored directly, not generated by LaTeXML. For any future corpus-based fixtures, the LaTeXML version would need to be recorded in `docs/chunker-fixtures.md`.

### `make test` and CI

`make test` runs `ruff check .` then `pytest`. The existing `tests/test_chunker.py` is already included in `pytest` (no explicit test path is specified — pytest autodiscovers). Adding `TestFixtureSuite` to `tests/test_chunker.py` (or creating `tests/test_chunker_fixtures.py`) will be automatically included without Makefile changes.

---

## 2. Prior decisions and lessons

### The corpus-not-materialized pattern

All four prior E02 milestones deferred 50-paper integration to "user-verifiable after `make ingest`." E02_S05 must be consistent: the fixture suite tests should be entirely self-contained in the worktree, relying on committed HTML fixtures only. The 10 fixture IDs should use the synthetic `2307.000NN` namespace already established by fixtures 2307.00001–2307.00004.

### E02_S04 `chunk_manifest.json` schema

From `_write_chunk_manifest` (implied by `TestChunkManifest`):

```json
{
  "chunks": [{"chunk_id": "...", "kind": "..."}],
  "chunker_version": "v1.0",
  "paper_id": "2307.00001"
}
```

The `kind_counts` field in the milestone brief's `expected.json` schema is NOT in `chunk_manifest.json` — it would need to be computed by the test from the manifest's `chunks` list.

### Empty-string preamble fallback

`_resolve_preamble_doc` returns `None` when preamble extraction fails. The caller then sets `preamble_text = ""`. For hand-crafted fixtures there is no `.tex` source, so this fallback always fires. The `expected_chunk_ids` values in fixture JSONs must be computed with `preamble_text = ""`.

### `preamble_ref=None` in test helpers

`_run_no_preamble` in `tests/test_chunker_ids.py` patches `ingest.chunker._resolve_preamble_doc` to return `None` explicitly, ensuring reproducibility without depending on a `.tex` source. The fixture suite should reuse this helper or an equivalent patch.

### Fixture paper_id format

The existing fixtures use `2307.000NN` which satisfies `_PAPER_ID_RE = r"^\d{4}\.\d{4,5}(v\d+)?$"` (five-digit suffix). New fixtures for scenarios 5–10 should follow the same namespace.

---

## 3. External sources

None required. This milestone is test infrastructure only, with no dependency on external APIs, LaTeXML, or corpus data.

---

## Open questions

**(a) Literally 10 real seed papers (impossible) vs. expand to 10 hand-crafted fixtures.**

The corpus is not materialized. Two options:

- *Option A (recommended):* Expand from 4 to 10 hand-crafted HTML fixtures, each in `tests/fixtures/chunker/<paper_id>/index.html`, using synthetic paper IDs 2307.00005–2307.00010. This is what every prior E02 milestone has done. The milestone brief's intent — diverse scenario coverage and deterministic chunk_ids — is fully met without materializing the corpus.
- *Option B:* Defer to "user verification after `make ingest`." But this makes the deliverable (10 committed fixture JSON files) impossible to produce in the worktree.

Option A is the only feasible path. The implementer should make this explicit in `docs/chunker-fixtures.md` and note which real-paper scenarios each hand-crafted fixture models.

**(b) Bump existing test class names into a single golden-output framework vs. add a new `TestFixtureSuite`.**

The existing classes (`TestTwoTheoremGolden`, `TestMalformedHTML`, etc.) test behavior at a granular level. Adding a new `TestFixtureSuite` that runs all 10 fixtures through a single parametrized test (`@pytest.mark.parametrize("fixture_id", [...])`) is cleaner because:

- It does not require modifying 10 existing test classes.
- The fixture JSON files drive the assertions — one assertion loop handles all 10 papers.
- The 60-second budget for `pytest tests/test_chunker.py` is easier to enforce for a single parametrized test than for scattered per-class methods.

Recommended: add `TestFixtureSuite` as a new class in `tests/test_chunker.py` (or a separate `tests/test_chunker_fixtures.py`). The class loads each `<paper_id>.expected.json`, runs `chunk_paper` with patched dirs and `_resolve_preamble_doc=None`, and asserts `chunk_count`, `kind_counts`, and that each `expected_chunk_id` appears in the chunker output.

**(c) Multi-window proof requirement — fixture 2307.00003 sufficient or expand?**

Fixture `2307.00003` contains `LONG_PROOF_PLACEHOLDER` in the proof body text. As committed, the placeholder is the literal string "LONG_PROOF_PLACEHOLDER" — far fewer than 448 tokens. `TestProofWindowSplitting::test_proof_chunks_emitted_from_full_paper` generates the actual long-proof HTML inline at paper_id "2307.00099" (not a fixture file). So fixture 2307.00003 does NOT satisfy the acceptance criterion "at least one fixture paper exercises a multi-window proof."

The implementer must either:
- Replace `LONG_PROOF_PLACEHOLDER` in `tests/fixtures/chunker/2307.00003/index.html` with ~500 words of real prose so the proof body exceeds 448 BGE-M3 tokens, OR
- Add a new fixture (e.g., 2307.00007) that contains a multi-window proof.

Replacing 2307.00003's content is cleaner and avoids changing the fixture count. However, replacing the placeholder changes the fixture HTML, which means the existing `TestProofWindowSplitting` test (which uses inline HTML anyway) is unaffected, but any test that runs `chunk_paper` on 2307.00003 will now see different chunk_ids. The safest path is to add 2307.00007 as the multi-window fixture and leave 2307.00003 as-is (it exercises proof-emission, even if not multi-window).

---

## External writes the implementation will require

| Path | Description |
|---|---|
| `tests/fixtures/chunker/2307.0000{5,6,7,8,9,10}/index.html` | Six new hand-crafted HTML fixtures covering: proposition kind, pure-definition-no-proof paper, multi-window proof (>448 tokens), multi-section document order, stmt truncation, duplicate-content de-dup |
| `tests/fixtures/chunker/2307.000{01,02,03,04,05,06,07,08,09,10}.expected.json` | 10 golden fixture JSON files with schema `{paper_id, chunk_count, kind_counts, expected_chunk_ids, chunker_version}` |
| `tests/test_chunker.py` (or new `tests/test_chunker_fixtures.py`) | New `TestFixtureSuite` class parametrized over 10 fixture IDs; reads `expected.json`, runs `chunk_paper` with patched dirs and `_resolve_preamble_doc=None`, asserts golden match |
| `docs/chunker-fixtures.md` | Brief note on which fixture covers which scenario, how to regenerate expected_chunk_ids after a chunker change, LaTeXML version note (not applicable for hand-crafted fixtures) |

No network calls, no git push, no third-party API, no corpus materialization. All writes are local to the worktree.

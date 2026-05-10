# Research Synthesis — E02_S05 Chunker fixture suite

Both researchers fully converged. No disagreements.

## Decisions (consensus)

**1. Hand-crafted HTML fixtures, not real corpus papers.**

`var/arxmcp/corpus/parsed/` is not materialized in this worktree (deferred across every prior E02 milestone). The literal "10 of the 50 seed papers" reading is impossible; the milestone's *intent* — diverse-scenario golden coverage — is fully served by 10 hand-crafted HTML fixtures.

Expand the existing 4 fixtures (`2307.0000{1..4}`) to 10 using the same `2307.000NN` synthetic-ID namespace. The `_PAPER_ID_RE` regex accepts five-digit suffixes.

**2. Fixture 2307.00003 is a stub.** The on-disk HTML contains the literal string `LONG_PROOF_PLACEHOLDER`. The actual multi-window-proof test (`TestProofWindowSplitting`) generates HTML inline via `_build_long_proof_html(word_count=400)` against paper_id `2307.00099`, NOT the fixture file. Add `2307.00007` as the proper static multi-window-proof fixture; leave `2307.00003` as-is (it covers an edge case — short-proof fallback — even if not multi-window).

**3. `expected.json` schema (per the brief, locked):**

```json
{
  "paper_id": "2307.00001",
  "chunk_count": 4,
  "kind_counts": {"stmt": 2, "proof": 2, "section": 0, "definition": 0},
  "expected_chunk_ids": ["arxiv:2307.00001:<hex16>", ...],
  "chunker_version": "v1.0"
}
```

`kind_counts` covers the canonical 4 kinds; additional kinds (lemma, corollary, remark, example, proposition, etc.) are computed from the chunk_manifest by the test, not pre-pinned.

**4. Bootstrapping `expected_chunk_ids`.** All hand-crafted fixtures use fake paper IDs with no `.tex` source, so `_resolve_preamble_doc` returns None and `preamble_text=""`. The chunk_id formula reduces to `sha256(NFC(body_text).encode("utf-8")).hexdigest()[:16]`. Process:

1. Author the HTML fixture.
2. Run `chunk_paper(paper_id)` once with `_resolve_preamble_doc` patched to None.
3. Inspect output: record `len(chunks)`, group `kind` counts, and pick at least one `chunk_id` per fixture (typically all of them — they're cheap).
4. Commit the resulting `<paper_id>.expected.json`.

The `chunk_manifest.json` written by E02_S04 IS effectively the bootstrapping source for steps 2–3 — read it, transform into the `expected.json` schema, commit.

**5. New `TestFixtureSuite` class.** Parametrized over all 10 fixture IDs via `@pytest.mark.parametrize("fixture_id", [...])`. Single body asserts:
- `chunk_count` matches
- Computed `kind_counts` (from emitted chunks) matches the pinned dict
- Every `chunk_id` in `expected_chunk_ids` appears in the chunker output
- `chunker_version` field matches the `CHUNKER_VERSION` constant

The existing per-fixture behavioral classes (`TestTwoTheoremGolden`, `TestMultiKindEnvironments`, etc.) stay as-is — they test behavioral properties, not golden output.

**6. Six new fixture scenarios (consensus):**

| Fixture | Scenario |
|---|---|
| `2307.00005` | Proposition + conjecture environment kinds (exercises `ltx_theorem_proposition`, `ltx_theorem_conjecture`) |
| `2307.00006` | Deeply nested subsection path (section > subsection > subsubsection) |
| `2307.00007` | Multi-window proof (long proof body baked in — closes the milestone's multi-window acceptance criterion) |
| `2307.00008` | Definition-heavy, NO `ltx_proof` (closes the no-proof-paper acceptance criterion) |
| `2307.00009` | Appendix section after main sections (tests section ordering, exercises F4 closure from E02_S01) |
| `2307.00010` | Paper with MathML `alttext` throughout body text (exercises `_element_text` math-preservation from F1 closure) |

**7. `docs/chunker-fixtures.md` (required deliverable per brief).** Minimal contents:
- Scenario table (the 6-row table above plus the 4 existing)
- Regeneration procedure: bump `chunker_version`, re-run `python -m pytest tests/test_chunker.py::TestFixtureSuite --regenerate` (or a manual one-shot script); commit the new `expected.json` files in the same commit as the chunker change.
- LaTeXML-version note: hand-crafted fixtures are HTML-direct, not LaTeXML-generated; LaTeXML version drift is irrelevant for this fixture suite. Real-corpus fixtures (deferred) would need LaTeXML version pinning per the brief's risk note.

**8. `make test` integration.** `make test` already runs `pytest` with autodiscovery. No Makefile changes needed.

## Open questions (resolved)

- (a) Hand-crafted fixtures, not real corpus. ✓
- (b) New `TestFixtureSuite` parametrized class, not bumping existing classes. ✓
- (c) Add `2307.00007` as a real multi-window-proof fixture; leave `2307.00003` as-is. ✓

## External writes

| type | target | why |
|---|---|---|
| filesystem write | `tests/fixtures/chunker/2307.000{05..10}/index.html` | 6 new hand-crafted HTML fixtures (committed) |
| filesystem write | `tests/fixtures/chunker/2307.000{01..10}.expected.json` | 10 golden output files (committed) |
| filesystem write | `tests/test_chunker.py` (new `TestFixtureSuite` class) | parametrized test runner (committed) |
| filesystem write | `docs/chunker-fixtures.md` | scenario notes + regeneration procedure (committed) |

No git push, PR, ticket, infra mutation, or third-party API call.

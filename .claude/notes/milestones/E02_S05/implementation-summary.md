# E02_S05 — Implementation summary

**One-line:** 10-fixture golden-output suite landed: 6 new hand-crafted HTML fixtures (2307.0000{5..10}) + 10 `<paper_id>.expected.json` files locking chunk_count, kind_counts, and content-addressable chunk_ids; new `TestFixtureSuite` parametrized class + `docs/chunker-fixtures.md` regeneration runbook.

**Implementation path:** Inline. Synthesis was unambiguous after both researchers fully converged.

**Commit range:** Single commit on top of `0528501`.

## Acceptance criteria

| Criterion | Status |
|---|---|
| 10 fixture files committed (one per paper) | Pass — `tests/fixtures/chunker/2307.000{01..10}.expected.json`, all 10 present |
| Each fixture file contains at least one `chunk_id` that can be looked up in the chunker output | Pass — `TestFixtureSuite::test_expected_chunk_ids_present` (parametrized × 10) |
| `pytest tests/test_chunker.py` passes on a clean checkout (chunk_ids reproducible byte-identically) | Pass — 156 tests green; the 42 fixture-suite parametrized cases all pass |
| At least one fixture paper exercises a multi-window proof | Pass — 2307.00007 splits into 3 proof chunks (`TestFixtureSuite::test_multi_window_proof_fixture_exists`) |
| At least one fixture paper has no explicit `\begin{proof}` | Pass — 2307.00008 emits 0 proof chunks (`TestFixtureSuite::test_no_proof_fixture_exists`) |
| `pytest tests/test_chunker.py` completes in under 60 seconds on a laptop | Pass — full chunker suite runs in ~2.5 seconds |
| CI (`make test`) includes this test suite | Pass — pytest autodiscovery picks up `TestFixtureSuite` automatically; no Makefile changes |

## "10 of the 50 seed papers" → 10 hand-crafted fixtures (deviation from the literal brief)

Both researchers independently flagged that `var/arxmcp/corpus/parsed/` is not materialized in this worktree (deferred across every prior E02 milestone). The brief's intent — diverse-scenario golden coverage — is fully satisfied by 10 hand-crafted HTML fixtures. The substitution is documented in `docs/chunker-fixtures.md` (top section) and noted in the `TestFixtureSuite` class docstring.

## New / changed files

- `tests/fixtures/chunker/2307.0000{5,6,7,8,9,10}/index.html` (6 new fixtures):
  - **2307.00005** — proposition + conjecture environment kinds
  - **2307.00006** — deeply nested section path (3 levels: section > subsection > subsubsection)
  - **2307.00007** — multi-window proof (~600-word proof body baked in; splits into 3 windows)
  - **2307.00008** — definition-heavy, NO proof environments (closes no-proof acceptance criterion)
  - **2307.00009** — appendix section after main (document-order check)
  - **2307.00010** — `<math alttext>` LaTeX preservation throughout body (exercises F1 closure from E02_S01)
- `tests/fixtures/chunker/2307.000{01..10}.expected.json` (10 new golden-output files): bootstrapped by running `chunk_paper` once on each fixture with `_resolve_preamble_doc` patched to None.
- `tests/test_chunker.py` (new `TestFixtureSuite` class, ~120 LOC): parametrized over all 10 fixture IDs; asserts `chunk_count`, `kind_counts`, every `expected_chunk_id` is present, `chunker_version` matches the constant; plus 2 dedicated tests for the multi-window-proof and no-proof acceptance criteria.
- `docs/chunker-fixtures.md` (new): scenario coverage table, `expected.json` schema, bootstrap procedure, regeneration procedure on `chunker_version` bumps, LaTeXML version note.

**Test result:** `make test PYTHON=python3.13` → 328 passed, 1 skipped (an unrelated F2 collision test from E02_S04 that requires a >1-chunk fixture), ruff clean. Full chunker test surface runs in ~2.5 seconds.

## Design choices recorded

1. **`TestFixtureSuite` is a single parametrized class**, not 10 per-paper classes. Cleaner for the 60-second budget and for the regeneration procedure (one `_FIXTURE_SUITE_IDS` list to update).
2. **`kind_counts` pins exactly 4 canonical kinds.** Other kinds (lemma, corollary, remark, example, proposition, conjecture, ...) are emitted but not pinned per-fixture — the `expected_chunk_ids` list still locks them in via byte-stability.
3. **`_resolve_preamble_doc` patched to None for all fixtures.** Synthetic paper IDs have no `.tex` source, so `preamble_text=""` is the production path for these fixtures. The chunk_id formula reduces to `sha256(NFC(body_text).encode("utf-8")).hexdigest()[:16]`.
4. **2307.00007 added as the multi-window-proof fixture.** Both researchers caught that 2307.00003 contains a literal `LONG_PROOF_PLACEHOLDER` that doesn't actually trigger window splitting; the existing `TestProofWindowSplitting` test generates HTML inline against a different paper_id ("2307.00099"). Adding a proper static fixture with ~600 words of real prose closes this gap; 2307.00003 stays as-is (it covers the short-proof-fallback edge case).
5. **2307.00008 has zero proof environments.** Closes the no-proof acceptance criterion. Definition-heavy with `definition`, `remark`, `example` kinds and 2 section chunks.

## External writes

| type | target | why |
|---|---|---|
| filesystem write | `tests/fixtures/chunker/2307.0000{5..10}/index.html` | new fixtures (committed) |
| filesystem write | `tests/fixtures/chunker/2307.000{01..10}.expected.json` | golden files (committed) |
| filesystem write | `tests/test_chunker.py` (new TestFixtureSuite) | parametrized test runner (committed) |
| filesystem write | `docs/chunker-fixtures.md` | scenario notes + regeneration procedure (committed) |

No git push, PR, ticket, infra mutation, or third-party API call.

## Out of scope (deferred to later milestones, as designed)

- Eval harness query curation (E05_S01 — references the chunk_ids this milestone locks in but curates query/relevance pairs separately).
- Embedding fixture papers (E03 scope).
- Real-corpus fixtures (would require LaTeXML version pinning per the brief's risk note; deferred until the seed corpus is materialized).

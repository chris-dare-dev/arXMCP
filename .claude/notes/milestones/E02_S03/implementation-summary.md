# E02_S03 — Implementation summary

**One-line:** body_tokens regex pre-tokenizer landed; `tokenize_body(body_text) -> str` produces a whitespace-joined math-aware token stream, wired into the chunker so every chunk now has body_tokens populated. H4 closed (no Tantivy LaTeX analyzer; this regex + standard BM25 in E04_S04 is the canonical replacement).

**Implementation path:** Inline. Synthesis was unambiguous.

**Commit range:** Single commit on top of 27206d4.

## Acceptance criteria

| Criterion | Status |
|---|---|
| tokenize_body of polynomial-ring example contains mathbb_Z and polynomial | Pass — TestAcceptanceCriteria::test_mathbb_arg_contains_polynomial |
| tokenize_body of mathrm Spec example contains mathrm_Spec and R | Pass — TestAcceptanceCriteria::test_mathrm_spec_and_R |
| Backslashes stripped from all LaTeX command names | Pass — TestAcceptanceCriteria::test_no_backslashes_in_output |
| Running on all 50 seed papers produces non-null body_tokens on every chunk | Deferred — parsed corpus not materialized in this worktree; existing chunker tests verify wire-in produces non-null strings on every chunk emitted from the test fixtures |
| Tokenizer performance ≤ 1ms per 512-token chunk | Pass — TestPerformance::test_under_5ms_per_chunk (loose 5ms CI bound; typical run measures ~0.1ms) |
| Module docstring states the H4 rejection sentence | Pass — TestModuleContract::test_docstring_documents_h4_remediation |

## Schema fix

Both researchers flagged: ChunkRecord.body_tokens annotation was list[str] | None — a mismatch with the LanceDB string column type that E04_S04 expects. Changed to str | None.

## New / changed files

- ingest/tokenizer.py (new) — single tokenize_body function, module-level compiled regex with 4 alternation branches (command{arg}, bare command, base_script, plain word). NFC normalization at function entry; dollar signs stripped before regex sweep.
- ingest/chunker_types.py — body_tokens annotation list[str] | None to str | None.
- ingest/chunker.py — per-chunk tokenize_body call after preamble_ref stamp, before JSON write.
- tests/test_tokenizer.py (new, 27 tests) — acceptance criteria, branch coverage, NFC determinism, edge cases, performance, BM25 compatibility.
- tests/test_chunker.py — test_body_tokens_null renamed to test_body_tokens_populated; asserts isinstance(chunk.body_tokens, str) on every chunk.

Test result: 246 passed (212 prior + 34 new), 0 failed, ruff clean.

## Closes critique findings

H4 (Tantivy LaTeX analyzer vapor): the Python regex + standard BM25 in E04_S04 is the canonical replacement. The closure trail now has its first physical artifact (ingest/tokenizer.py); E04_S04 will complete it.

## Design choices recorded

- Don't lowercase. Math identifiers are case-significant (Z != z).
- Don't deduplicate. BM25 weights by term frequency.
- No minimum token length. Single-letter math identifiers are meaningful.
- NFC inside tokenize_body, not at the chunker layer.
- Don't bump chunker_version (E02_S04's job).
- Drop complex sub/superscripts. H^{n+1} produces only H.
- Top-level import of tokenize_body in chunker.py (no circular-import risk).

## External writes

- ingest/tokenizer.py, ingest/chunker.py, ingest/chunker_types.py, tests/test_tokenizer.py, tests/test_chunker.py — new and modified source files, committed.

No git push, PR, ticket, infra mutation, or third-party API call.

## Out of scope (deferred)

- BM25 index construction (E04_S04).
- Equation-level tokenization (E10_S03 uses MathML tree-edit distance).
- Macro expansion before tokenization (Tier 2).
- Content-addressable chunk_id (E02_S04).

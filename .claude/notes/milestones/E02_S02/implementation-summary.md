# E02_S02 — Implementation summary

**One-line:** Per-paper preamble extractor lands: scans root .tex for `\newcommand`/`\renewcommand`/`\providecommand`/`\DeclareMathOperator{,*}`/`\def`/`\edef`/`\gdef`/`\xdef`/`\let`, normalizes + dedups + sorts, writes deterministic `preamble.json`, and the chunker now stamps every emitted chunk with `preamble_ref = SHA-256(preamble_text)[:16]`.

**Implementation path:** Inline (orchestrator). Synthesis was sufficiently specific that delegated dispatch would have been pure overhead.

**Commit range:** Single commit on top of `ef66061`.

## Acceptance criteria

| Criterion | Status | Notes |
|---|---|---|
| Preamble extractor produces a `preamble.json` for each of the 50 seed papers | ✗ DEFERRED | Parsed corpus not materialized in this worktree; the unit test on the fixture .tex covers all extraction logic. The 50-paper integration is user-verifiable via `python -c "from ingest.preamble import extract_preamble; [extract_preamble(p) for p in open('tools/seed-papers.txt').read().split() if not p.startswith('#')]"` after `make ingest`. |
| `preamble_text` deterministic across runs on same source | ✓ | `TestDeterminism` (2 tests) — same source produces same hash; macro input order does not affect output. |
| `preamble_ref` matches `SHA-256(preamble_text)[:16]` | ✓ | `TestPreambleHashContract::test_hash_matches_sha256_prefix` + `TestChunkerIntegration::test_chunker_populates_preamble_ref`. |
| Re-run on unchanged paper is no-op | ✓ | `TestIdempotency::test_unchanged_source_no_rewrite` (mtime-comparison) + `TestIdempotency::test_changed_source_triggers_rewrite`. |
| Fixture: 3 `\newcommand` + 1 `\DeclareMathOperator` → length 4 in deterministic order | ✓ | `TestExtractFixturePaper::test_macros_count_meets_milestone_floor` (richer fixture exceeds the floor; 5 \newcommand + 1 \renewcommand + 1 \providecommand + 2 DMO + 4 \def-family + 2 \let). |
| Module docstring rejects contextual retrieval | ✓ | `TestModuleContract::test_docstring_rejects_contextual_retrieval` enforces. |

## New / changed files

- `ingest/preamble.py` (~330 LOC) — `extract_preamble(paper_id)` public API; brace-depth scanner; comment stripper that honors `\%` escape; idempotent atomic write via `tmp + os.replace`
- `ingest/preamble_types.py` (~70 LOC) — `PreambleDoc` dataclass with `to_dict()`/`from_dict()` round-trip
- `tests/test_preamble.py` (~470 LOC, 46 tests) — extraction families, comment stripping, brace-balanced scan, fixture-paper acceptance, hash contract, determinism, idempotency, paper_id validation, missing source, load_preamble, chunker integration
- `tests/fixtures/preamble/sample.tex` — comprehensive fixture covering all in-scope directive families plus comment-escape edge cases and multi-line bodies
- `ingest/chunker.py` — added `_resolve_preamble_ref(paper_id)` helper and wire-in at the end of `_chunk_paper_impl` so every emitted chunk carries `preamble_ref` (or None on graceful failure)

**Test result:** `make test PYTHON=python3.13` → 198 passed, 0 failed, ruff clean.

## Closes critique findings

- **MEDIUM (contextual retrieval vs preamble overlap)**: the rejection rationale is now in code (module docstring) and enforced by `TestModuleContract`. Future reviewers can re-litigate the choice via the test file rather than re-deriving it from the notes.

## Design choices made beyond the brief

1. **Included `\providecommand` and `\def` family variants (`\edef`, `\gdef`, `\xdef`).** Both researchers independently recommended this — these directives are common in math.AG papers and the milestone brief's omission was an oversight, not a deliberate scoping decision.
2. **Imported `find_main_tex` from `tools/arxiv_fetch.py` rather than reimplementing.** Avoids drift; the existing heuristic (`<paper_id>.tex` > unique > first with `\documentclass` > alphabetical) is the canonical answer.
3. **Reused `_validate_paper_id`, `InvalidPaperIDError`, `_sanitize_log_field` from `ingest/chunker.py`.** Single source of truth for path-traversal defense (Threat 1) and TSV log sanitization. The preamble extractor inherits both guarantees automatically.
4. **Lazy import of `extract_preamble` inside `_resolve_preamble_ref`.** Keeps `ingest/chunker.py` importable in environments where `ingest/preamble.py` is missing or where the `tools/` import chain is broken — the chunker degrades gracefully to `preamble_ref=None`.

## External writes the orchestrator must authorize

| type | target | why | blocking |
|---|---|---|---|
| filesystem write | `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` | runtime extractor output; gitignored | No |
| filesystem write | `var/arxmcp/ops/parser-failures/preamble.log` | runtime TSV failure log; gitignored | No |

No git push, PR, ticket, or infra mutation. Local commits only.

## Out of scope (deferred to later milestones, as designed)

- Macro body expansion / evaluation (Tier 2 per `04-parsing-and-chunking.md`)
- `\input{}`/`\include{}` chasing — root .tex only at Tier 0
- `.sty`/`.cls` files
- `\DeclareRobustCommand`, `\newenvironment`/`\renewenvironment`
- BM25 `body_tokens` field (E02_S03)
- Content-addressable `chunk_id` SHA-256 (E02_S04)
- Embedding compute (E03_S01) — but the contract is now satisfied: `preamble_text + "\n\n" + body_text` reconstructs deterministically from any chunk's `preamble_ref` + the corresponding `preamble.json`.

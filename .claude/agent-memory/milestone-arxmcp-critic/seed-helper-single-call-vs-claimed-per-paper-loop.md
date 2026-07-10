---
name: seed-helper-single-call-vs-claimed-per-paper-loop
description: HIGH — `_seed_corpus(lancedb_path, n=N)` calls `write_chunks` ONCE with N chunks; implementations/summaries that describe it as "N per-paper write_chunks calls" are factually wrong, and tests citing the m1 multi-call cumulative-marker bug do NOT exercise that shape with this fixture.
metadata:
  type: feedback
---

When a milestone reuses `_seed_corpus` from `tests/test_corpus_count_reconciliation.py`
and claims to catch the m1 "cumulative-marker" bug (where pre-m1
`chunk_count = len(chunks)` on the LAST per-paper batch diverged from
`tbl.count_rows()` for the cumulative table), VERIFY the fixture's actual call shape.

**The actual behavior:** `_seed_corpus(lancedb_path, n=N)` builds a list of N
`ChunkRecord` instances + a SINGLE `EmbedRecord` with N vectors, then calls
`write_chunks(chunks, embeddings, ...)` **once**. Verified at
`tests/test_corpus_count_reconciliation.py:47-81` — single call site at L81.

**Why this matters:** the pre-m1 bug shape was specifically multi-call: each
per-paper `write_chunks` call wrote a marker with `chunk_count = len(<that
call's chunks>)`, so the FINAL marker reflected only the last batch. In a
single-call fixture, `len(chunks) == tbl.count_rows()` trivially — a
reintroduced buggy formula would write the same value as the table, and the
positive-path test would pass silently.

**How to apply:** when an integration test docstring or implementation summary
says "this test catches any `len(chunks)`-flavored chunk_count regression on
the write path," check (a) whether the fixture calls `write_chunks` multiple
times (cumulative path) or just once (non-cumulative path), and (b) whether
the mutation test exercises the production code path or just the
divergence-detection path. The two are separate bug classes. m3
(corpus-integrity-completion-m3 F1) shipped a single-call fixture with the
multi-call-bug-catching CLAIM — fixture mismatch is HIGH.

Related: [[regression-guard-pins-names-not-shape]] (similar shape — claim is
broader than the assertion enforces). Related: [[stale-docstring-anti-pattern]]
in the project-level constitution.

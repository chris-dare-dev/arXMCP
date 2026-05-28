# Critique — textbook-ingest-m8

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** 5639764..c72fe37
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the descope is genuinely justified on BOTH load-bearing claims (preamble + ProofNet), verified against code — this is correct engineering honesty, not work-dodging. Findings are doc-precision only.
- Finding counts: 0 CRITICAL, 0 HIGH, 2 MEDIUM, 3 LOW.
- Highest-risk item: `.claude/docs/proofnet-crossref-contract.md:86` — "needs no 22nd column" is off-by-one (CHUNKS_SCHEMA_V1 already has 22 fields; a new column would be the 23rd). Substantive claim (no new column) is correct; only the ordinal is wrong.
- Preamble descope independently confirmed: MinerU consumes a rendered PDF (`textbook_parser.py:351-357` passes `-p <pdf_path>`); `extract_preamble` is `.tex`-source-only and raises FileNotFoundError otherwise (`preamble.py:333-337`). No author macros are recoverable. CLEAN.
- ProofNet descope independently confirmed: `proofnet_id` would be permanently NULL from the chunker; adding it triggers `_migrate_chunks_schema_if_needed` (`store.py:302`) → corpus_version bump. Existing fields support the documented join. CLEAN.
- The chunker diff is genuinely comment/docstring-only: the sole statement line `preamble_text = ""` is byte-identical pre/post (only its trailing comment was removed). No version bump or golden regen required. CLEAN.
- The audit fixture is NON-trivial: the orphan proof's `theorem_name=None` is meaningful because PAIRED proofs in `two-chapter-book/expected.json` carry non-None names (`Spec Functoriality`, `Module-Sheaf Equivalence`). The contrast is real.
- Cache/schema/tool-schema all untouched; 160 tests across tool-schema + both chunker suites pass; m7 golden intact.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — ProofNet doc "22nd column" ordinal is off by one

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/docs/proofnet-crossref-contract.md:86
- **What:** The doc states `ingest/schema.py::CHUNKS_SCHEMA_V1` "needs no 22nd column", implying the current schema has 21 columns. `CHUNKS_SCHEMA_V1` (`ingest/schema.py:98-187`) actually declares exactly 22 `pa.field(...)` entries, so a new `proofnet_id` would be the 23rd column.
- **Why it matters:** The doc is the authoritative operator-facing artifact for the ProofNet join contract and is the *entire* deliverable for OQ-2. A wrong column count undermines confidence in the rest of the schema reasoning and could mislead a future implementer who trusts the doc's count when deciding whether a migration is needed. Same "doc says X, code shows Y" shape this critic has repeatedly flagged in m3/m4/m6.
- **Proposed fix:** Change `needs no 22nd column` to `needs no additional (23rd) column` or simply `needs no new column`. Optionally state the actual count (22) explicitly so it is verifiable.
- **Regression guard:** Add a one-line assertion-free note in the doc citing `len(CHUNKS_SCHEMA_V1) == 22` so a future reader can grep-verify; no test needed (doc-only change).

### F2 — e3 outcome "per-chapter preamble inheritance works" is closed by re-interpretation, not delivery — closure rationale should be pinned in the roadmap, not only in `.claude/docs/`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** plans/textbook-ingest-roadmap.md:107
- **What:** The e3 outcome literally reads "Per-chapter preamble inheritance works (textbook-shaped, not paper-shaped)." m8 closes e3 by declaring that outcome structurally inapplicable. The justification lives in `.claude/docs/textbook-preamble-decision.md` and the implementation-summary, but the roadmap line itself (`plans/textbook-ingest-roadmap.md:107`) is left unchanged — a future reader scanning the roadmap sees an outcome marked delivered that was in fact descoped.
- **Why it matters:** The descope is correct (see "What was done well"), but "documented why it's inapplicable" only counts as honest closure if the roadmap that named the outcome is updated to point at the decision. Otherwise the roadmap silently over-claims delivery — the exact "scope honesty" failure mode the milestone was told to guard against. This is a documentation-completeness gap, not a wrong technical call, hence MEDIUM not HIGH.
- **Proposed fix:** Append a one-line note to the e3 outcome at `plans/textbook-ingest-roadmap.md:107` (or its status row) — e.g. "preamble half DESCOPED at m8 as structurally inapplicable to the PDF path; see `.claude/docs/textbook-preamble-decision.md`." Keep the decision doc as the full rationale.
- **Regression guard:** None testable (roadmap prose). The cross-link itself is the guard against the over-claim.

### F3 — Preamble doc/comment §"related deferrals" anchor is stylistically inconsistent across its three citations

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/textbook_chunker.py:33
- **What:** The chunker comment cites the section three ways: module docstring `§related-deferrals` (line ~33), the page-metadata comment `§"related deferrals"` (line ~376), while the actual heading in the doc is `## Related deferrals (also NOT m8, also NOT in the e3 outcome)` (`textbook-preamble-decision.md:81`). The section exists, so this is not a dangling reference — but the three citations do not agree on the anchor string.
- **Why it matters:** Cosmetic. A reader can find the section, but inconsistent anchor naming is the kind of drift that becomes a dangling reference after a future heading rename. Pure hygiene.
- **Proposed fix:** Normalize all three citations to `§"Related deferrals"` matching the doc heading's leading word casing.
- **Regression guard:** None (LOW; deferrable).

### F4 — ProofNet doc cites two distinct upstream identifiers without noting they are the same project

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/docs/proofnet-crossref-contract.md:13
- **What:** The doc references HF dataset `hoskinson-center/proofnet` (line 13) and GitHub `github.com/zhangir-azerbayev/ProofNet` (line 102) for the same benchmark. Both are real and correct (verified: arXiv:2302.12433, Azerbayev et al., 371 examples, Lean 3), but a reader may wonder whether these are two different artifacts.
- **Why it matters:** Minor reader confusion only. The factual content (371 entries, Lean 3, undergraduate textbooks, the arXiv id) is all accurate.
- **Proposed fix:** Add a half-sentence noting the HF dataset is the canonical mirror of the GitHub benchmark, or pick one canonical pointer.
- **Regression guard:** None (LOW; deferrable).

### F5 — `test_matches_golden` uses bare list-equality assertion with no diff aid for a 4-dict comparison

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_textbook_chunker.py:454
- **What:** `assert actual == expected` compares two 4-element lists of ~17-key dicts. On failure pytest's default repr for nested dict-lists is hard to read; the structural sibling tests (`test_four_chunks_emitted`, `test_proof_is_orphan_not_paired`) provide the human-readable signal, so the golden test's failure ergonomics are a minor gap. (`assert` in a test file is allowed — this is NOT an invariant-assert ban violation.)
- **Why it matters:** Test ergonomics only. The golden assertion is correct and independent coverage exists; this just makes a future failure slower to diagnose.
- **Proposed fix:** Optional — add a per-chunk loop or `assertpy`-style message, or rely on the existing structural tests. Defer.
- **Regression guard:** None (LOW; deferrable).

## What was done well

- Independently-verifiable descope: the preamble claim holds against code — `textbook_parser.py:351-357` confirms MinerU's input is a rendered PDF (`-p <pdf_path>`), and `preamble.py:313-358` confirms `extract_preamble` is `.tex`-source-only, raising FileNotFoundError when the raw tree is absent. There is genuinely nothing to inherit.
- The embedder-fallback claim is accurate: `embedder.py:1012-1015` + `_build_embed_input` (`embedder.py:371-386`) return `body_text` alone when `load_preamble` yields `None`, so textbook chunks embed correctly with no preamble — exactly as the decision doc claims.
- The comment-only diff is disciplined: the only statement line (`textbook_chunker.py` `preamble_text = ""`) is byte-identical pre/post; only its trailing `# TODO(m8)` comment was retired. No silent logic change, correctly no version bump.
- Version discipline is correct: `TEXTBOOK_CHUNKER_VERSION` stays `tv0.1` and m7's `two-chapter-book/expected.json` is untouched in the diff (`git diff --name-only` confirms) — no spurious corpus_version rotation.
- The audit fixture is non-trivial: orphan-proof `theorem_name=None` is a real signal because paired proofs in `two-chapter-book` DO carry non-None names (`Spec Functoriality`, `Module-Sheaf Equivalence`); the theorem-remark-proof fixture genuinely exercises `_is_structural_sibling` terminating pairing at the interposed `ltx_theorem_remark` div.
- ProofNet factual claims check out: arXiv:2302.12433, Azerbayev et al., 371 entries (185+186), Lean 3, undergraduate textbooks — all verified.
- The auto-id caveat is technically precise: the doc's example `S1.Thmtheorem1` actually matches `_AUTO_ID_RE` (→ `theorem_label=None`) and `exercise_1_1a` does not — confirming the doc's "low fidelity for PDF" reasoning against the real regex (`chunker.py:101,406-418`).
- Cache/schema discipline: no changes to `server/`, `ingest/schema.py`, `ingest/chunker_types.py`, `ALL_TOOLS`, or any tool result envelope; the tool-schema hash test passes — BP1 byte-stability preserved.
- Doc placement is correct: both new docs are under `.claude/docs/`; no markdown leaked into `ingest/` or `tests/`.
- Cross-references resolve: `_migrate_chunks_schema_if_needed` (`store.py:302`), the ProofNet mention in `01-mission-and-context.md:108`, and the roadmap e3 outcome (`plans/textbook-ingest-roadmap.md:107`) all exist as cited; `assert` is absent from the production diff.

## Recommended rectification order

1. F1 — fix the "22nd column" ordinal in the ProofNet doc (one-word edit; highest-leverage because it is the only factual error in a doc that IS the deliverable).
2. F2 — add the descope cross-link to the e3 roadmap outcome (closes the scope-honesty gap; one line).
3. F3 — normalize the three §"related deferrals" anchor citations (cosmetic; bundle with F1/F2 doc pass).
4. F4 — note the HF/GitHub identifier relationship (cosmetic; bundle).
5. F5 — defer (test ergonomics only).

## Rectification status

- F1 (MEDIUM) — **INVALIDATED as stated, then HARDENED.** Re-verify (`len(CHUNKS_SCHEMA_V1) == 21`, live) shows the adversary MISCOUNTED: the schema has 21 fields, not 22, so the doc's "needs no 22nd column" was CORRECT (a new column would be the 22nd) and the proposed "23rd" fix would have introduced an error. The adversary's underlying concern (brittle relative ordinal) is fair, so the doc was reworded to drop the ordinal and state the verifiable absolute count: "needs no new column (verify: `len(CHUNKS_SCHEMA_V1) == 21`)". `.claude/docs/proofnet-crossref-contract.md:86`.
- F2 (MEDIUM) — FIXED in `plans/textbook-ingest-roadmap.md:107`: appended a CLOSED-at-m7+m8 note to the e3 outcome cross-linking both descope decision docs, so the roadmap no longer silently over-claims the preamble outcome as delivered.
- F3 (LOW) — FIXED: normalized both chunker citations to `§"Related deferrals"` matching the doc heading (`ingest/textbook_chunker.py:39,377`).
- F4 (LOW) — FIXED in `.claude/docs/proofnet-crossref-contract.md:11`: noted the GitHub repo and the HF dataset are the same project.
- F5 (LOW) — DEFERRED (golden-diff test ergonomics; structural sibling tests already give human-readable failure signal).

**Invalidation note:** F1 invalidated-as-stated (adversary miscounted schema fields at 22; live count is 21). Zero CRITICAL+HIGH findings, so the 40% critic-prompt-broken threshold does not apply; recorded for calibration. F1 still yielded a doc hardening.

**Central verdict upheld:** the descope (preamble + ProofNet) was independently verified CORRECT — not work-dodging. No code logic changed; `TEXTBOOK_CHUNKER_VERSION` stays `tv0.1`; m7 golden fixture untouched.

**External writes:** none required.

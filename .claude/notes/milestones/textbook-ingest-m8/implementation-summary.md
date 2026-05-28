# Implementation Summary — textbook-ingest-m8

**Summary:** Closes the textbook-ingest-e3 epic. m8 is a deliberate **descope** — research (both briefs, confidently) resolved that the roadmap's "per-chapter preamble inheritance" is structurally inapplicable to the PDF→MinerU ingest path, and that ProofNet mapping needs no schema column. m8 therefore ships documented decisions + a theorem-pairing audit fixture rather than unwired infrastructure.

**Commit range:** `5639764..HEAD` (single feat commit + this summary).

## Acceptance criteria status

### OQ-1 — Per-chapter preamble inheritance: DESCOPED (documented decision)
- [x] Resolved (reading a): the PDF→MinerU→markdown→LaTeXML path produces no author macros (MinerU emits already-expanded math; there is no `.tex` preamble). Per-chapter inheritance is structurally inapplicable, not a gap.
- [x] Replaced the misleading `# TODO(m8): per-chapter preamble inheritance` in `ingest/textbook_chunker.py` (impl + module docstring) with a permanent documented decision (`preamble_text=""` / `preamble_ref=None` is correct steady state; a future `.tex`-source path would call `extract_preamble`).
- [x] New design note `.claude/docs/textbook-preamble-decision.md` with the full evidence chain + the related page-column deferral.
- [x] Built NO preamble extractor (FM-1 dead-infrastructure risk foreclosed).

### OQ-2 — ProofNet metadata schema mapping: documented contract, no schema column
- [x] Resolved: existing ChunkRecord fields (`textbook_slug`, `chapter`, `theorem_name`, `theorem_label`) already enable cross-referencing to a ProofNet entry (`{TextbookName}|{exercise_id}`). No `proofnet_id` column (would be permanently NULL from the chunker → schema bloat + corpus_version rotation for zero data gain — FM-2/FM-5).
- [x] New contract doc `.claude/docs/proofnet-crossref-contract.md` with the join key, the authoritative ProofNet schema (arXiv:2302.12433 / HF `hoskinson-center/proofnet`), AND the load-bearing fidelity caveat: `theorem_label` is unreliable for PDF textbooks (MinerU never sees `\label{}` keys; LaTeXML emits auto-ids), so matching is best-effort + manual-overlay, not a reliable automatic join.
- [x] NO ChunkRecord field, NO schema migration, NO hash re-pin.

### Theorem-pairing polish: audited, no code fix needed
- [x] Audited the reused pairing primitives against a textbook-shaped structure m7's fixture did not cover — theorem→remark→proof (intervening remark). New fixture `tests/fixtures/textbook_chunker/theorem-remark-proof/`.
- [x] Confirmed correct non-pairing: the orphan proof has `theorem_name=None`/`theorem_label=None`, whereas a paired proof (m7 two-chapter fixture) inherits the theorem's name+label. The intervening remark correctly terminates the pairing scan — inherited verbatim from the arXiv-tested `_is_structural_sibling` logic.
- [x] NO change to `ingest/chunker.py` (the shared primitive) — arXiv chunker tests stay green (FM-4).

### Version + hygiene
- [x] `TEXTBOOK_CHUNKER_VERSION` NOT bumped (still `tv0.1`) — m8 changed no textbook chunk CONTENT (preamble was already `""`; the new fixture is additive). m7's `expected.json` unchanged.
- [x] No BP1 / MCP tool-schema change (ingest + docs only). Three-copy paper_id lock untouched.

## Files changed
- `ingest/textbook_chunker.py` (comment/docstring edits — preamble decision; no logic change)
- `.claude/docs/textbook-preamble-decision.md` (NEW)
- `.claude/docs/proofnet-crossref-contract.md` (NEW)
- `tests/fixtures/textbook_chunker/theorem-remark-proof/{index.html,expected.json}` (NEW)
- `tests/test_textbook_chunker.py` (+1 test class, 4 tests: `TestTheoremRemarkProofPairingAudit`)

## External writes required
None — purely local.

## Test counts
- `make test`: **3046 passed, 29 skipped, 1 xfailed, 3 pre-existing failures** (latexmlc SIGABRT + Kùzu graph DB path — unchanged). +4 m8 audit tests; m7's 30 textbook-chunker tests still green (golden fixture unchanged).

## Deviations from the brief
- The brief was written anticipating a possible descope; research confirmed it. This is NOT a deviation — it is the brief's "milestone honesty" clause executed: the RIGHT m8 is documented decisions + a pairing audit, NOT a `.tex`-preamble extractor for a path that cannot feed it, nor a NULL `proofnet_id` column. Both researchers independently reached this; the synthesis adopted it.
- No `feat`-worthy production logic landed (the chunker logic is unchanged from m7). The commit type is still `feat` per the milestone-pipeline 3-commit pattern, but the substance is documentation + test coverage + a code-comment correction. This is the honest shape of an epic-closing refinement milestone whose named scope research invalidated.

## e3 status
**textbook-ingest-e3 is CLOSED** at m8 completion (m7 spine + m8 refinements/decisions), per the two-milestone decomposition the operator approved.

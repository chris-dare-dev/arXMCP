# Research Synthesis — textbook-ingest-m8

**Orchestrator merge** of `research-brief-1.md` (in-codebase) and `research-brief-2.md` (external + failure-mode). The two briefs CONVERGE on both blocking questions; brief-2 adds a sharper ProofNet-fidelity caveat that the synthesis adopts.

## Headline: m8 DESCOPES per the brief's anticipated honest outcome

Both researchers independently resolved the two BLOCKING open questions to the same answers. The roadmap's e3 outcome ("Per-chapter preamble inheritance works") was written before the PDF-vs-`.tex` tension was understood; research confirms the preamble half is **structurally inapplicable** to the shipped ingest path. m8 becomes a slim **hygiene + documentation** milestone — NOT a build of unwired infrastructure.

## OQ-1 (BLOCKING) — RESOLVED: reading (a), descope the preamble half

**Both briefs, confident.** The PDF → MinerU → markdown → LaTeXML path produces NO author macros:
- `ingest/preamble.py::extract_preamble` is exclusively `.tex`-source-driven: it reads `var/arxmcp/corpus/raw/<paper_id>/` (the arXiv raw tree) and raises FileNotFoundError if absent. The textbook tree (`var/arxmcp/notebooks/<slug>/`) has no `.tex` source.
- m6's `textbook_renderer.py` writes a throwaway `main.tex` envelope (`\usepackage{amsmath,amssymb}` + MinerU's already-expanded markdown) — it has NO `\newcommand`/`\def` author macros. MinerU emits rendered math (`\mathbb{F}`, not `\F`); macros are expanded at the PDF-render level, before MinerU ever sees them.
- `ingest/embedder.py` already falls back to `preamble_text=""` when `load_preamble` returns `None` — textbook chunks embed without a preamble prepend, which is CORRECT because their math is already in canonical expanded form (the preamble lever in `04-parsing-and-chunking.md` exists to expand UNEXPANDED author macros; textbook PDFs have none).
- Reading (c) (synthesized notation preamble) is rejected: non-deterministic → violates BP1 byte-stability (`07-multi-agent-caching.md`); the constitution explicitly rejects contextual-retrieval-style synthesis.

**Delivery:** Replace the misleading `# TODO(m8): per-chapter preamble inheritance` at `ingest/textbook_chunker.py` with a permanent documented decision (empty preamble is correct for PDF-sourced textbooks; `preamble_ref` stays `None`; a future `.tex`-source path — separate epic — would call `extract_preamble`). Write `.claude/docs/textbook-preamble-decision.md`. **Build NO preamble extractor** (FM-1: the central dead-infrastructure risk).

## OQ-2 (BLOCKING) — RESOLVED: documented cross-reference contract, NO schema column

**Both briefs converge on "no `proofnet_id` column"; brief-2 supplies the authoritative ProofNet schema + the load-bearing fidelity caveat.**

ProofNet (arXiv:2302.12433; HF `hoskinson-center/proofnet`) — 371 entries, 5 fields each: `id` (`{Textbook}|{exercise_N}`, e.g. `Rudin|exercise_1_1a`), `nl_statement`, `nl_proof`, `formal_statement`, `src_header`. The id maps to `(textbook, exercise-number)`.

- A textbook chunk cross-references a ProofNet entry by `(textbook_slug -> TextbookName, theorem_label -> exercise id)`. The existing `ChunkRecord` fields (`textbook_slug`, `chapter`, `theorem_name`, `theorem_label`) already carry this — **no new field needed**.
- **CRITICAL caveat (brief-2):** `theorem_label` fidelity is LOW for PDF-sourced textbooks. `\label{exercise_1_1a}` keys are NOT printed in the rendered PDF, so MinerU never sees them; LaTeXML emits auto-generated structural ids (`S1.Thmtheorem1`), not author labels. So automated `theorem_label -> exercise_1_1a` matching will usually FAIL for the PDF path. The cross-reference contract must document this explicitly: matching is best-effort by `(textbook_slug, theorem_name)` + manual annotation, NOT a reliable automatic `theorem_label` join.
- A `proofnet_id` LanceDB column is rejected: it would be permanently NULL from the chunker (no auto-population mechanism), and adding it triggers `_migrate_chunks_schema_if_needed` -> a corpus_version bump that rotates the retrieval cache key (FM-5) for zero data gain.

**Delivery:** Write `.claude/docs/proofnet-crossref-contract.md` documenting the join key + the low-fidelity caveat + the future-`.tex`-path note. NO ChunkRecord field, NO schema migration, NO hash re-pin. This satisfies "ProofNet metadata schema mapping preserved" as a documented contract at zero schema cost.

## Theorem-pairing polish — audit + one textbook fixture; no code fix expected

Both briefs assess m7's reuse of the shared pairing primitives as SUFFICIENT for textbook input — the primitives (`_extract_chunks_from_container`, `_is_structural_sibling`) are CSS-class-based and arXiv-neutral. `_is_structural_sibling` correctly terminates pairing at a new `<section>` (incl. `ltx_chapter`) OR another theorem-like div. The theorem-remark-proof intervening case (proof does NOT pair when a remark sits between) is already tested for arXiv (`tests/fixtures/chunker/2307.00002`).

**Delivery:** Add ONE textbook golden fixture exercising a textbook-shaped structure m7's two-chapter fixture does NOT cover — a theorem followed by an intervening remark followed by a proof inside a chapter — and assert the textbook chunker inherits the correct behavior (theorem emitted as unmatched `stmt`, proof as orphan, NO false pairing). This is defense-in-depth proof that the textbook path inherits the arXiv-tested termination logic. **No code fix to `ingest/chunker.py`** unless this fixture reveals a real gap (it should not — FM-4 guards arXiv regression). If a code fix WERE needed, it must keep `tests/test_chunker.py` green.

## Orchestrator synthesis note — final scope (CONFIRMED reduced)

1. **Preamble decision (OQ-1):** Edit `ingest/textbook_chunker.py` — replace the `# TODO(m8)` with a permanent documented decision comment. New doc `.claude/docs/textbook-preamble-decision.md`.
2. **ProofNet cross-reference contract (OQ-2):** New doc `.claude/docs/proofnet-crossref-contract.md`. NO schema/ChunkRecord change.
3. **Theorem-pairing audit:** New textbook golden fixture (theorem-remark-proof) + test asserting correct non-pairing. Documented audit conclusion. No `ingest/chunker.py` change expected.
4. **Version:** Bump `TEXTBOOK_CHUNKER_VERSION` to `tv0.2` ONLY if textbook chunk CONTENT changes. The preamble-comment edit does NOT change chunk content (preamble was already `""`); a new fixture does NOT change existing chunk content. **Expected: NO version bump, NO regeneration of m7's `expected.json`.**
5. **No BP1 / MCP tool-schema change** (ingest-side; both confirm). Three-copy paper_id lock untouched.
6. **e3 closes at m8 completion.**

## Failure modes carried forward (brief-2, all mitigated by the reduced scope)

| FM | Risk | Mitigation in m8 |
|---|---|---|
| FM-1 | Dead `.tex`-preamble extractor | OQ-1(a) forecloses — build nothing |
| FM-2 | `proofnet_id` column always NULL | OQ-2 — no column, doc contract instead |
| FM-3 | `TEXTBOOK_CHUNKER_VERSION` bump forgotten | No chunk-content change -> no bump; if audit fixture forces one, bump + regenerate |
| FM-4 | Shared-primitive fix regresses arXiv | No code fix planned; if forced, `tests/test_chunker.py` is the guard |
| FM-5 | Schema-hash perturbation / corpus_version bump | No schema change -> no perturbation |
| FM-6 | Non-deterministic synthesized preamble | Reading (c) rejected |
| FM-7 | `theorem_label` cross-ref breaks for PDF | Documented explicitly in the crossref contract (low-fidelity caveat) |

## Open questions (after synthesis)

None block implementation. OQ-1 + OQ-2 resolved. The implementer should run the theorem-pairing audit fixture and confirm no real gap before claiming that AC met — expected outcome: "no code fix, fixture proves coverage."

## External writes the implementation will require

| type | target | why | blocking? |
|---|---|---|---|
| (none) | | | |

Purely local. Deliverables: 2 new `.claude/docs/` files, a comment edit in `ingest/textbook_chunker.py`, 1 new test fixture + test in `tests/`. No git push, no GH issue, no infra mutation, no MCP surface change.

## Size + path

~Docs-heavy: 2 doc files (~120 LOC), 1 comment edit (~8 LOC), 1 fixture + ~5 tests (~120 LOC). **~250 LOC, ~5 files. INLINE.** This is the smallest milestone of the textbook-ingest series — appropriate, because research correctly descoped the unwired half rather than manufacturing work.

# Research Brief — textbook-ingest-m8

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T05:15:00Z

---

## In-codebase context

### Load-bearing constraints from the design constitution

From `04-parsing-and-chunking.md` (via `ingest/preamble.py` module docstring, verbatim):
> "Anthropic contextual retrieval is rejected — preamble is deterministic; see 04-parsing-and-chunking.md § Preamble extraction. The notes explicitly call out determinism as load-bearing for BP1 byte-identical caching across multi-agent fan-out."

From `ingest/preamble.py` lines 2-8 (verbatim):
> "Reads the root .tex file under `var/arxmcp/corpus/raw/<paper_id>/` and extracts every macro-definition directive into a deterministic `preamble.json` under `var/arxmcp/corpus/preamble/<paper_id>/`."

The preamble extractor is **exclusively `.tex`-source-driven**. Its entire path-resolution chain (`_select_root_tex`, `find_main_tex`, `RAW_DIR = .../corpus/raw`) targets the arXiv raw-source tree. No analogous mechanism exists or can exist for the MinerU PDF-to-markdown-to-LaTeXML pipeline (m5/m6).

From `ingest/textbook_chunker.py` lines 380-381 (verbatim):
> `preamble_text = ""  # TODO(m8): per-chapter preamble inheritance`

From `ingest/textbook_chunker.py` lines 31-32 (verbatim):
> "Does NOT call `_resolve_preamble_doc` — it resolves the arXiv preamble store (wrong tree; the `:` is an invalid path byte). v0 uses an empty preamble. (TODO m8: per-chapter preamble inheritance.)"

**Schema cross-check (OQ-2):** `ingest/chunker_types.py` ChunkRecord has these relevant fields: `theorem_name`, `theorem_label`, `chapter`, `textbook_slug`, `source_kind`, `preamble_ref`. There is **no** `proofnet_id` field. `ingest/schema.py` CHUNKS_SCHEMA_V1 has 21 columns — no ProofNet column. The schema migration system in `ingest/store.py::_migrate_chunks_schema_if_needed` is additive per-column; adding a nullable `proofnet_id` column would not perturb existing arXiv rows' data values.

**TEXTBOOK_CHUNKER_VERSION = "tv0.1"** in `ingest/textbook_chunker.py` line 84. This is correctly separate from `chunker_types.CHUNKER_VERSION = "v1.1"`. Any m8 content change to textbook chunks requires bumping to `"tv0.2"` and regenerating golden fixtures — NOT bumping the arXiv version.

No ProofNet references exist anywhere in the codebase (`grep` returned empty).

---

## Prior decisions and lessons

From MEMORY.md (auto-injected):
- `ChunkRecord` already has ALL textbook-ingest-m2 columns — no dataclass extension needed for fields that exist. Adding `proofnet_id` would be the first new field since m2.
- `TEXTBOOK_CHUNKER_VERSION` is SEPARATE from `CHUNKER_VERSION` by design (2026-05-28 memory entry).
- `page_start`/`page_end` stay NULL in v0 per documented design decision; m8 brief mentions correlating `content_list.json` page_idx as a TODO — this is a minor scoped item, not a blocker.

Git log shows m7 shipped in commit `1656ec6` (hierarchical textbook chunker) and closed 5 adversary findings in `21ad433`. The `feat → rect → chore` triple is mandatory for m8.

No prior m8 research brief exists in `.claude/notes/milestones/textbook-ingest-m8/` (only `state.json`).

**Banned patterns check:**
- This milestone is ingest-only — no `server/` changes, no MCP tool-schema change. `EXPECTED_TOOL_SCHEMA_SHA256` re-pin is NOT required.
- No `assert` for invariants risk identified in the m7 source reviewed — pattern not introduced.
- No `BaseHTTPMiddleware`, no `anthropic` SDK runtime import in scope.
- `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` untouched.

---

## External sources

### OQ-2: ProofNet dataset schema (authoritative)

Source: Hugging Face dataset card `hoskinson-center/proofnet` (primary, authoritative).
Source: arXiv:2302.12433 (Azerbayev et al., "ProofNet: Autoformalizing and Formally Proving Undergraduate Mathematics").

ProofNet has exactly **5 fields per entry** (371 total examples — 185 validation, 186 test):

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Stable identifier, pattern: `Textbook\|Exercise_Number` |
| `nl_statement` | string | Natural-language theorem statement |
| `nl_proof` | string | Natural-language proof in LaTeX |
| `formal_statement` | string | Lean 3 formal statement |
| `src_header` | string | File header with imports/namespaces for the Lean statement |

**Stable `id` examples** (from HuggingFace dataset card):
- `Rudin|exercise_1_1a`
- `Munkres|exercise_13_1`
- `Axler|exercise_1_3`
- `Ireland-Rosen|exercise_1_27`

The `id` scheme is `{TextbookName}|{exercise_N_Ma}`. The `src_header` has 10 distinct classes representing the source textbooks.

**Implication for OQ-2:** A textbook chunk can be cross-referenced to a ProofNet entry by `(textbook_slug, theorem_label)` — not by an explicit `proofnet_id`. The ProofNet id `Rudin|exercise_1_1a` maps to `textbook_slug="rudin-principles"` + `theorem_label="exercise_1_1a"`. The existing `ChunkRecord.theorem_label` field carries the LaTeXML-extracted `\label{}` key; `ChunkRecord.textbook_slug` carries the notebook slug. A downstream eval script can join on `(slug→TextbookName, theorem_label→exercise_id)` **without** adding a `proofnet_id` column — IF `theorem_label` fidelity is sufficient.

Critical assessment: `theorem_label` fidelity from MinerU+LaTeXML is uncertain. MinerU extracts rendered text from PDF; `\label{}` keys are not printed in the rendered PDF in most textbooks. LaTeXML can emit `id` attributes from structural numbering (e.g. `id="S1.Thmthm1"`) but these are auto-generated, not the author's `\label{exercise_1_1a}`. Therefore for PDF-sourced textbooks, `theorem_label` will almost always be `None` or an auto-generated LaTeXML id, not `exercise_1_1a`.

**This means OQ-2 reading (c) (theorem-name/label fidelity) is INSUFFICIENT for PDF-sourced textbooks.** Reading (a) (schema-carry of a nullable `proofnet_id`) is the correct delivery vehicle — but that field must be populated manually or by a separate annotation pass, not automatically by the chunker.

### OQ-1: Per-chapter preamble in LaTeX textbooks

For `.tex`-source textbooks (e.g. Stacks Project): macros are typically book-global, in a single master `preamble.tex` or at the top of `main.tex`. Per-chapter `\input{}` files define section content only, not macros. This is standard practice: LaTeX compilation requires all macros to be defined before their first use, and chapter files are `\input`'d sequentially. Per-chapter preamble inheritance is a non-problem for well-structured textbooks — there is one preamble per book.

**Does MinerU preserve macro information?** No. MinerU processes the rendered PDF output: `\F` is already rendered as `𝔽` (or `\mathbb{F}`) in the glyph layer; MinerU emits the expanded form, never the author macro. This is confirmed by m5 design decisions (the m5 brief explicitly states "MinerU extracts math from a rendered PDF — macros are already expanded"). The m6 LaTeXML render of MinerU's markdown output produces LaTeXML-normalized MathML, not author-macro LaTeX.

**OQ-1 resolution:** Reading **(a) wins unconditionally** for the PDF→MinerU path. There is no `.tex` preamble to extract; no mechanism by which author macros survive the PDF render → MinerU → markdown → LaTeXML pipeline. Preamble inheritance for PDF-sourced textbooks is a structural impossibility, not a gap to close.

---

## Failure-mode analysis

Grounded in `08-security-observability-ops.md` and codebase structure:

**FM-1: Dead `.tex`-preamble extractor (the central risk).** If the implementer builds `extract_textbook_preamble()` targeting the MinerU pipeline, it has zero callers that can produce `.tex` input. The function may even shadow or confuse `ingest/preamble.py::extract_preamble` (which is arXiv-specific). Risk: dead code path, test overhead for infrastructure that is never exercised in production. Brief explicitly warns: "Do NOT build a `.tex`-preamble extractor for a path that cannot produce `.tex`." Mitigation: OQ-1 reading (a) forecloses this entirely.

**FM-2: `proofnet_id` column added but never populated.** If a `proofnet_id` pa.field is added to CHUNKS_SCHEMA_V1 and ChunkRecord, it is always NULL for every textbook chunk produced by the chunker (the chunker has no mechanism to assign ProofNet ids). The column becomes schema bloat. Additionally, adding a 22nd column to CHUNKS_SCHEMA_V1 triggers the migration system in `store.py::_migrate_chunks_schema_if_needed`, which runs `add_columns` per-column — adding a new nullable column is idempotent and does not perturb arXiv row data values, but it does add schema complexity. Mitigation: do NOT add `proofnet_id` to the LanceDB schema or ChunkRecord at m8. Instead, document the cross-reference contract (textbook_slug + theorem_label → ProofNet id lookup) in `.claude/docs/`.

**FM-3: `TEXTBOOK_CHUNKER_VERSION` bump forgotten.** If any change to `_compute_textbook_chunk_id` or chunk content (body_text composition, preamble handling) is made without bumping `TEXTBOOK_CHUNKER_VERSION` from `"tv0.1"` to `"tv0.2"`, existing golden fixtures (`tests/fixtures/textbook_chunker/`) will fail silently or generate stale chunk manifests. Mitigation: the test suite has a version-freeze guard; any golden-fixture regeneration must be accompanied by the version bump.

**FM-4: Shared primitive fix for theorem pairing regresses arXiv chunking.** m8 audits `_extract_chunks_from_container` and `_extract_section_chunks` (shared primitives in `ingest/chunker.py`) against textbook-shaped input. If a fix is applied to handle textbook-specific structures (e.g. theorem-across-page-boundary), it must not change the output for arXiv-shaped HTML. The guard is `tests/test_chunker.py` (arXiv chunker tests must stay green). Risk: the shared primitives are battle-tested for arXiv; textbook structure differs in chapter nesting depth and numbered-environment naming. Any fix must be bracketed by a conditional or a textbook-specific code path, NOT a general alteration.

**FM-5: LanceDB schema hash perturbation for existing arXiv rows.** If a new nullable column is added to CHUNKS_SCHEMA_V1, `store.py::_migrate_chunks_schema_if_needed` will add it to the on-disk table via `tbl.add_columns(...)`. For arXiv rows, the new column is NULL. The LanceDB MVCC version increments (each `add_columns` is its own version). This is safe and expected per the m2 migration design — but it means any schema addition triggers a corpus version bump that forces cache invalidation (see `07-multi-agent-caching.md` Property 2). If m8 adds a ProofNet column, the retrieval cache's corpus_version key rotates, warming cost applies.

**FM-6: Non-deterministic preamble text for reading (c).** If reading (c) ("synthesized notation preamble") were pursued, any LLM-generated or frequency-heuristic synthesized preamble introduces byte instability across runs (different MinerU versions, different notation frequency orderings). The design constitution explicitly rejects this: "Anthropic contextual retrieval is rejected — preamble is deterministic." Mitigation: reading (a) wins; this FM is only live if reading (c) is pursued despite OQ-1 evidence.

**FM-7: `theorem_label` cross-reference assumption breaks for PDF textbooks.** If the ProofNet cross-reference plan relies on `theorem_label` matching ProofNet ids like `exercise_1_1a`, it fails for PDF-sourced textbooks where `\label{}` keys are not in the rendered output. MinerU/LaTeXML emits auto-generated ids (e.g., `ltx:theorem:1` or `S2.Thmthm3`), not author exercise labels. Any cross-reference tooling must document this limitation clearly.

---

## Recommendation

**Descope the preamble half of m8 cleanly. Deliver ProofNet as a cross-reference contract document, not a schema column. Focus implementation effort on theorem-pairing polish and the explicit TODO closure.**

Concrete scope:
1. **Preamble (OQ-1 reading a):** Replace the `# TODO(m8)` comment in `textbook_chunker.py` line 380 with a documented decision constant or comment block: PDF-sourced textbooks have no author preamble; `preamble_ref` stays `None`; a future `.tex`-source path (separate epic) would call `extract_preamble`. Remove the misleading TODO. Do NOT build any preamble extractor.
2. **ProofNet (OQ-2 reading c, lightly):** Do NOT add `proofnet_id` to the schema or ChunkRecord — the field would be permanently NULL from the chunker. Instead, write a `.claude/docs/proofnet-crossref-contract.md` documenting the join key: `(textbook_slug → ProofNet TextbookName, theorem_label → exercise id)` with explicit caveat that `theorem_label` fidelity is LOW for PDF-sourced textbooks. This satisfies "ProofNet metadata schema mapping preserved" as a documented contract without schema bloat.
3. **Theorem-pairing polish:** Audit `_extract_chunks_from_container` against textbook golden fixtures. Add fixture coverage for textbook-specific structures. Fix only if arXiv tests stay green.
4. **TEXTBOOK_CHUNKER_VERSION bump to `"tv0.2"`** if any chunk content changes (only if pairing polish changes output). Not required for the preamble-decision-comment or the ProofNet doc.

Reasoning: Building a `.tex`-preamble extractor for a path that cannot produce `.tex` is explicitly flagged as the central risk in the brief. Adding a `proofnet_id` schema column that is always NULL from the chunker is schema bloat without value. The cross-reference contract document satisfies the roadmap outcome at zero schema cost.

---

## Open questions

**OQ-1 resolution (CONFIDENT):** Reading **(a)** wins. The PDF→MinerU path cannot produce author macros. Per-chapter preamble inheritance is inapplicable. The `# TODO(m8)` comment should be replaced with a decision note. No preamble infrastructure needed.

**OQ-2 resolution (CONFIDENT):** Reading **(c)** partially wins, but with an important caveat: `theorem_label` fidelity is LOW for PDF-sourced textbooks (auto-generated LaTeXML ids, not author labels). Deliver as a documented cross-reference contract in `.claude/docs/` — no `proofnet_id` schema column. If a future `.tex`-source path is added, the schema extension can happen then with real label data available.

**Remaining question for implementer:** Is there any textbook-specific theorem structure (e.g., `ltx_numberedmath`, `ltx_theorem_remark` variants, or multi-part theorem environments spanning `ltx_chapter` boundaries) where the current shared pairing primitives produce empty or mismatched chunks? This requires running the chunker against a real textbook golden fixture and inspecting output. The implementer should audit this before claiming the pairing AC is met.

No open questions that block implementation start.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no ticket, no infra mutation required. The three-commit pattern (feat → rect → chore) lands on `main` directly per CLAUDE.md §4.1.

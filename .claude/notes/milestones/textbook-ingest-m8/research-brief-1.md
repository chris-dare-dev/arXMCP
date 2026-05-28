# Research Brief — textbook-ingest-m8

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T05:10:00Z

## In-codebase context

### OQ-1 VERDICT: Reading (a) — Preamble inheritance is INAPPLICABLE to the PDF path. DESCOPE the preamble half.

**Evidence chain:**

1. `ingest/preamble.py::extract_preamble` requires a physical `.tex` file. Its first action after validating `paper_id` is:
   ```
   raw_paper_dir = RAW_DIR / paper_id
   if not raw_paper_dir.exists():
       raise FileNotFoundError(...)
   main_tex = _select_root_tex(raw_paper_dir, paper_id)
   ```
   `RAW_DIR = var/arxmcp/corpus/raw/<paper_id>/`. The textbook path places files under `var/arxmcp/notebooks/<slug>/`, not `corpus/raw/`. There is no `.tex` file in the textbook tree.

2. `ingest/textbook_renderer.py::render_mineru_to_html` writes a `work_dir/main.tex` (line 189) that is the `_LATEX_ENVELOPE` wrapper — a throwaway structural envelope containing only `\usepackage{amsmath,amssymb}` and MinerU's already-expanded markdown as body. The envelope has **no author macros** (`\newcommand`, `\def`, etc.) whatsoever — MinerU receives a PDF and emits markdown where macros are already expanded to their rendered Unicode/LaTeX form (e.g., `\mathbb{F}`, not `\F`). The `main.tex` is an inert rendering wrapper, not a preamble source.

3. `ingest/textbook_chunker.py` line 380 is explicit:
   ```python
   preamble_text = ""  # TODO(m8): per-chapter preamble inheritance
   ```
   The `# TODO(m8)` was written before the PDF-vs-.tex tension was understood. The textbook path is `PDF → MinerU → markdown → LaTeXML`; macros are expanded by MinerU at the PDF-render level. There is no `.tex` preamble to inherit.

4. `ingest/embedder.py` (lines 1012–1027): the embedder calls `load_preamble(paper_id)` and gracefully falls back to `preamble_text = ""` when it returns `None`. Textbook chunks will embed without a preamble prepend — which is the correct behavior because the math notation in MinerU markdown is already in its expanded, canonical form. The preamble mechanism for arXiv exists to expand author-local macros that are NOT pre-expanded; textbook PDFs have no unexpanded macros.

5. Reading (b) (`.tex`-source path) is explicitly out of scope per the milestone brief. Reading (c) ("synthesized preamble from recurring notation") has no implementation precedent and no clear benefit — MinerU already emits canonical math; a synthesized recurring-symbol list would be redundant and non-deterministic (violating BP1 byte-stability rules from `07-multi-agent-caching.md`).

**What m8 SHOULD deliver instead of building unwired infrastructure:**
- Remove the `# TODO(m8)` comment from `ingest/textbook_chunker.py` line 380.
- Add a docstring/comment documenting the design decision: "PDF-sourced textbooks have no `.tex` preamble; MinerU expands macros at render time. `preamble_text` is permanently `""` and `preamble_ref` stays `None` for PDF-sourced chunks. A `.tex`-source textbook path (deferred to a future epic) would enable preamble extraction."
- Optionally add a design note to `.claude/docs/textbook-preamble-decision.md` documenting this explicitly.

### OQ-2 VERDICT: Reading (c) — existing ChunkRecord fields are SUFFICIENT. No schema change needed.

**Evidence chain:**

1. `ingest/chunker_types.py::ChunkRecord` already carries all fields needed to cross-reference a chunk to a ProofNet entry by (textbook, theorem-number):
   - `textbook_slug` — identifies which textbook (e.g., `"rudin-pma"`)
   - `chapter` — populated by the m7 chapter-label extractor
   - `theorem_name` — the parenthetical name from the theorem heading (e.g., `"Cauchy-Schwarz"`)
   - `theorem_label` — the `\label{}` key from LaTeXML (e.g., `"thm:1.35"`)
   - `section_path` — full breadcrumb path
   - `kind` — `"stmt"` for theorem statements

   A downstream ProofNet eval can match a chunk to a ProofNet entry using `(textbook_slug, chapter, theorem_label/theorem_name)`. This satisfies the cross-reference intent.

2. `ingest/schema.py::CHUNKS_SCHEMA_V1` is a 21-column PyArrow schema with all textbook-ingest-m2 columns already present. Adding a `proofnet_id` column would require: (a) a new ChunkRecord field, (b) a new nullable column in `CHUNKS_SCHEMA_V1`, (c) schema migration via `_migrate_chunks_schema_if_needed`, and (d) a hash re-pin in `tests/test_store.py`. The gain is minimal — ProofNet data cannot be auto-populated from a PDF (textbook PDFs do not carry ProofNet IDs), so the field would be NULL for all current textbook chunks. A NULL field in the schema buys nothing over a documented cross-reference contract.

3. `01-mission-and-context.md` §Benchmarks: "ProofNet (undergraduate textbook theorems): standard test for autoformalization." The project wants to eventually **run a ProofNet eval**, not ingest ProofNet data. The eval step reads chunks and matches them to ProofNet entries by (textbook, theorem-number). The fields already present make this feasible; a new nullable column adds friction (migration, hash re-pin) with zero data gain at this stage.

**What m8 SHOULD deliver:**
- A documented cross-reference contract in `.claude/docs/proofnet-cross-reference.md` specifying: "A chunk can be mapped to ProofNet entry by `(textbook_slug, chapter, theorem_label or theorem_name)`. ProofNet entries carry `(textbook, theorem-number)`; the resolver must handle name-vs-label ambiguity."
- Ensure the m7 chunker preserves `theorem_name` and `theorem_label` correctly for ProofNet-covered textbooks. This is a fidelity audit, not a schema change.
- No new ChunkRecord field. No schema migration. No hash re-pin.

### Theorem-pairing primitives: textbook-shaped structures

`ingest/chunker.py::_is_structural_sibling` (line 353–367):
```python
def _is_structural_sibling(tag: Tag) -> bool:
    classes = _get_classes(tag)
    for cls in classes:
        if _THEOREM_CLASS_RE.match(cls):
            return True
    return tag.name in {"section"}
```

The pairing scan advances through siblings looking for `ltx_proof`, and stops when it hits `_is_structural_sibling` — another theorem-like div OR a `<section>` tag. This works identically for textbook HTML5 because LaTeXML emits the same `ltx_theorem_*` + `ltx_proof` class structure for textbook environments.

**Textbook-specific pairing concern identified:** LaTeXML emits chapters as `<section class="ltx_chapter">` (not `<section class="ltx_section">`). The `_SECTION_DIV_CLASSES` list (line 154–161) includes `ltx_chapter`. The `_is_structural_sibling` check uses `tag.name in {"section"}` which catches ALL `<section>` elements including chapters. A theorem at the END of a chapter whose proof is at the START of the next chapter would be correctly NOT paired (the section boundary intervenes). This is correct behavior — no fix needed.

**Identical-chapter-title collision (m7 F2):** The `_collect_chapter_titles` function uses a `set[str]` so two chapters with the same title text collapse. Documented as a v0 limitation in m7. **Not a pairing bug** — chunk_ids remain unique (content-addressed). The chapter label fidelity issue is low priority. No fix needed for m8.

**Conclusion:** m7's reuse of the shared pairing primitives is sufficient for textbook-shaped inputs. The shared primitives are structure-class-based, not arXiv-specific. No pairing fixes needed.

### Design notes applicable to m8

- **`04-parsing-and-chunking.md` §Rule 2** (load-bearing): "Extract `\newcommand` definitions and 'throughout this paper, $X$ denotes...' prose from the introduction. Prepend this as a header to every chunk from the paper before embedding. **This is the single biggest retrieval-quality lever after macro expansion.**" This rule applies to the arXiv path; for PDF-sourced textbooks it is structurally inapplicable because MinerU already expands macros. The design note does NOT conflict with OQ-1 reading (a) — the preamble benefit is real but requires a `.tex` source.

- **`07-multi-agent-caching.md`** (BP1 byte-stability): Any synthesized preamble from recurring notation (OQ-1 reading (c)) would violate BP1 because the recurring-symbol extraction would be non-deterministic across runs. Reading (a) avoids this constraint entirely.

## Prior decisions and lessons

- **m7 state** (`textbook-ingest-m7/state.json`, phase `complete`): m7 shipped with `preamble_text = ""` and `preamble_ref = None` as a stated v0 limitation with a `# TODO(m8)` marker. The adversary found 0 CRITICAL / 0 HIGH / 3 MEDIUM / 2 LOW findings; all 5 were fixed in the rect commit. None touched the preamble or ProofNet scope.

- **m7 implementation commit `1656ec6`**: "hierarchical textbook chunker (textbook-ingest-m7)". Established `TEXTBOOK_CHUNKER_VERSION = "tv0.1"` as a separate constant from `CHUNKER_VERSION = "v1.1"`. If m8 changes any textbook chunk content (e.g., theorem_name/theorem_label fidelity), it MUST bump `TEXTBOOK_CHUNKER_VERSION` to `tv0.2` — NOT `CHUNKER_VERSION` (arXiv must not re-embed).

- **Memory: `CHUNK_ID_RE-uses-dollar-not-Z-anchor`** — `is_valid_chunk_id` uses `$` not `\Z`. This bug exists in adjacent code. m8 does NOT touch `CHUNK_ID_RE` or `identifiers.py`, so no risk here, but note it if m8 adds any identifier validation.

- **Memory: `ChunkRecord-has-all-m2-fields-no-gap`** — confirmed: ChunkRecord has all needed textbook fields. No extension needed for OQ-2.

- **Memory: `textbook-chunker-needs-own-version-constant`** — already addressed in m7 via `TEXTBOOK_CHUNKER_VERSION = "tv0.1"`.

**No conflicts found between milestone brief constraints and the codebase.** The brief explicitly anticipated reading (a) as the likely outcome and pre-authorized descoping the preamble half. The OQ-2 reading (c) conclusion (existing fields sufficient) is consistent with the brief's permission to deliver a "documented provenance contract" rather than a schema change.

## External sources

No external sources were required. The milestone is purely ingest-side with no MCP tool surface changes and no vendor API dependencies. The ProofNet benchmark is referenced at `01-mission-and-context.md` (project design note, already read) and `10-references-and-prior-art.md` (bibliographic entry for arXiv:2302.12433). No MCP spec or Anthropic prompt-caching docs are relevant — this milestone adds no new tools and does not touch the server surface.

## Recommendation

**Implement m8 as a slim hygiene + documentation milestone.** Specifically:

1. **OQ-1 (preamble):** Remove the `# TODO(m8)` from `ingest/textbook_chunker.py` line 380. Replace it with a permanent comment documenting the design decision: PDF-sourced textbooks have no `.tex` preamble; `preamble_text = ""` and `preamble_ref = None` are the correct permanent values for the `mineru+latexml` parser path. Write a one-page design note at `.claude/docs/textbook-preamble-decision.md`.

2. **OQ-2 (ProofNet):** Write a cross-reference contract at `.claude/docs/proofnet-cross-reference.md` specifying how `(textbook_slug, chapter, theorem_label/theorem_name)` maps to ProofNet entries. No new ChunkRecord field. No schema migration. No hash re-pin.

3. **Theorem-pairing:** Audit the m7 golden fixtures for any theorem/proof pairing gaps with textbook-shaped inputs (the brief requires this). If no gaps: document the audit result. If gaps: fix in `ingest/chunker.py` only if arXiv-safe (existing tests green). My assessment is that no fixes are needed — the primitives are class-based and arXiv-neutral — but the audit should produce a golden fixture for a textbook chapter containing a theorem + proof pair to prove the coverage.

4. Bump `TEXTBOOK_CHUNKER_VERSION` to `tv0.2` ONLY if any textbook chunk content changes (e.g., from a pairing fix or theorem-name extraction improvement). If the preamble `""` decision leaves chunk content identical and no pairing fixes land, do NOT bump.

This approach closes e3 cleanly with zero infrastructure debt and zero schema risk.

## Open questions

**OQ-1: RESOLVED.** Reading (a) — preamble inheritance is inapplicable to the PDF path. Descope. Replace `# TODO(m8)` with a documented permanent decision.

**OQ-2: RESOLVED.** Reading (c) — existing ChunkRecord fields (`textbook_slug`, `chapter`, `theorem_name`, `theorem_label`) are sufficient for ProofNet cross-reference. No schema change. Deliver a documented cross-reference contract.

**New OQ-3 (low-stakes, resolve during implementation):** The `_collect_chapter_titles` set-based collision (m7 F2 deferred: two chapters with identical titles collapse) is noted as a v0 limitation. Does the m8 brief require disambiguating identical chapter titles by ordinal? My reading: no — the brief says "pairing polish," not "chapter-title disambiguation." Defer to a future milestone unless a golden fixture reveals a concrete regression.

No open questions block implementation. All three OQs have clear resolutions.

## External writes the implementation will require

None — this milestone is purely local.

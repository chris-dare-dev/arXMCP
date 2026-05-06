# E03 — Macro Normalization & Deterministic Canonical IR (Tier 1b)

**Epic dependencies:** E02.

**Goal:** turn the raw parser output (LaTeXML HTML5+MathML) into a deterministic, macro-expanded, canonically-normalized intermediate representation that the chunker (E04) and embedder (E05–E06) can consume. This is "Correction 2" from `02-architecture-overview.md` — without it, retrieval quality on math papers is structurally broken. Every change here is a chunker version bump.

**Effort:** ~1 week.

**References:** `02-architecture-overview.md` § Correction 2; `04-parsing-and-chunking.md` § Macro normalization (the make-or-break step), § Per-paper preamble; `05-storage-and-indexing.md` § Definitions table (target schema).

---

### E03_S01 — `\newcommand` and `\renewcommand` resolver

**Description.** LaTeXML expands most macros, but partial expansions and `\renewcommand` chains slip through. Implement a post-LaTeXML pass that walks MathML and HTML, detects unresolved author-local macro tokens, and substitutes their definitions per `04-parsing-and-chunking.md` § Macro normalization step 1. Build the per-paper notation table along the way.

**Acceptance criteria.**
- [ ] `ingest/normalize/macros.py::resolve(parsed: ParsedPaper) -> NormalizedPaper`.
- [ ] Walks the parsed HTML/MathML and detects unresolved `\<name>` tokens.
- [ ] Looks up author definitions extracted from preamble (`\newcommand`, `\renewcommand`, `\def`, `\DeclareMathOperator`).
- [ ] Substitutes definitions inline; preserves the raw form in a sidecar field for raw-LaTeX retrieval.
- [ ] Bounded recursion (max depth 50; reuse the guard from E02_S08).
- [ ] Per-paper definitions captured as `[{symbol_canonical, symbol_raw, expansion, scope}]`.
- [ ] Unit test: a fixture paper with `\newcommand{\AA}{\mathcal{A}}` used 3× returns body containing `\mathcal{A}` and a notation entry mapping `\AA` → `\mathcal{A}`.

**Dependencies.** none within E03 (uses E02_S09 parsed IR).

**Complexity.** L.

**Labels.** `area:parser`, `kind:feature`, `risk:high`.

---

### E03_S02 — Notation-variant canonicalization table

**Description.** Implement the variant-merging rules from `04-parsing-and-chunking.md` § Macro normalization step 2: `\Bbb{R}`, `\mathbb{R}`, `\R` (custom) all map to `\mathbb{R}`; `\acute{e}tale`, `\'etale`, `\mathrm{\'et}` all map to "étale"; `\cF`, `\mathcal{F}`, `\mathscr{F}` all map to `\mathcal{F}`. The table is checked-in and versioned; changes bump chunker version.

**Acceptance criteria.**
- [ ] `ingest/normalize/canonical_variants.yaml` lists at minimum 30 well-known variant groups (number-system blackboard bolds, common script/cal/frak conflicts, accented Latin letters in math mode).
- [ ] `ingest/normalize/canonicalize.py` applies the table to a parsed body and returns the canonical form alongside the original.
- [ ] The original form is preserved in a `body_raw_latex` sidecar (per chunk schema in `04-parsing-and-chunking.md`).
- [ ] Loss is documented per row (some merges are lossy — `\cF` vs `\mathscr{F}` in differential geometry contexts).
- [ ] Bumping the YAML triggers `chunker_version` bump (test enforces this via a hash check).

**Dependencies.** E03_S01.

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`.

---

### E03_S03 — Per-paper preamble extractor

**Description.** Per `04-parsing-and-chunking.md` Rule 2 — "Per-paper preamble prepended to every chunk" — extract `\newcommand` definitions plus prose like "Throughout this paper, $X$ denotes..." from the introduction and synthesize a stable `preamble` field that will be prepended to every chunk's `embedding_text`. This is the single biggest retrieval-quality lever after macro expansion.

**Acceptance criteria.**
- [ ] `ingest/normalize/preamble.py::extract(parsed: ParsedPaper) -> Preamble`.
- [ ] Concatenates: (a) all author macro definitions (rendered in canonical form), (b) "throughout this paper" / "we let X denote" sentences from the introduction (heuristic regex + section-tag check).
- [ ] Output is bounded to 1024 tokens; longer preambles are truncated by token count, never mid-sentence.
- [ ] Output is deterministic — given the same parsed input, the preamble bytes are identical.
- [ ] Unit test: fixture introduction with three "denote" sentences and four `\newcommand`s yields the expected concatenation in the documented order (macros then prose).

**Dependencies.** E03_S01.

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`.

---

### E03_S04 — Cross-reference resolution

**Description.** Per `04-parsing-and-chunking.md` Rule 4 — "Cross-references resolved into chunks" — replace `(see Lemma 3.4)` references with an inline expansion that includes the actual statement of Lemma 3.4 in a "referenced statements" appendix. LaTeXML emits cross-reference targets; this pass walks them and extracts the linked content.

**Acceptance criteria.**
- [ ] `ingest/normalize/xref.py::resolve(parsed: ParsedPaper) -> ParsedPaper` (mutates references in place into the appendix).
- [ ] Each chunk that mentions another labelled environment gets a `referenced_chunks` list populated with target IDs (resolved later in E04 once chunk IDs exist).
- [ ] Inline references are kept (the agent may want them) but a structured "Referenced statements" trailer is appended.
- [ ] Cross-paper references (`\cite{}`) are NOT resolved here — that goes through INSPIRE/OpenAlex in E09. Per `04-parsing-and-chunking.md` § Failure modes "`\cite{}` key resolves to nothing → drop reference rather than dangling text."
- [ ] Test: fixture paper with `\ref{lem:flat}` produces a trailer containing the lemma statement.

**Dependencies.** E03_S01.

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`.

---

### E03_S05 — Determinism contract for normalized output

**Description.** Per `02-architecture-overview.md` § Determinism contract — every byte of normalizer output must be reproducible bit-for-bit given the same input. Add a property test that runs the normalizer twice on the same parsed paper and asserts byte-equal output, plus a CI check that runs on every PR.

**Acceptance criteria.**
- [ ] Property test in `tests/normalize/test_determinism.py` runs the full normalize pipeline on 5 fixture papers and asserts identical SHA-256 across two runs.
- [ ] No `time.time()`, `random.*`, or `dict()` iteration order dependencies in normalize code (lint rule).
- [ ] All YAML/JSON outputs use sorted-key serialization.
- [ ] `chunker_version` field appears on the normalized output and increments only with deliberate changes (validated via a frozen-hash test).
- [ ] CI runs the determinism test on every PR.

**Dependencies.** E03_S01, E03_S02, E03_S03, E03_S04.

**Complexity.** S.

**Labels.** `area:parser`, `area:cache`, `kind:infra`.

---

### E03_S06 — Notation-table emission for downstream `definitions` index

**Description.** The notation table built in E03_S01 is the v1 source for the `definitions` LanceDB table (`05-storage-and-indexing.md` § Table: definitions) and the `get_definitions` MCP tool (`06-mcp-server-design.md`). Emit it as `var/arxmcp/corpus/normalized/<paper_id>.notation.json` so E05 can load it directly.

**Acceptance criteria.**
- [ ] `ingest/normalize/notation_emit.py::write(paper_id, NormalizedPaper)` writes a notation JSON file.
- [ ] Schema matches the `definitions` table layout: `[{definition_id, paper_id, symbol, symbol_raw, expansion, defining_chunk_id (placeholder until E04), scope}]`.
- [ ] `definition_id` is content-addressable: `arxiv:<paper_id>:def:<sha256(symbol_raw + expansion)[:16]>`.
- [ ] File is sorted by `symbol` for determinism.
- [ ] Test: round-trip read/write returns identical bytes.

**Dependencies.** E03_S01.

**Complexity.** S.

**Labels.** `area:parser`, `area:storage`.

---

### E03_S07 — `chunker_version` propagation hook

**Description.** Every output of E03 carries `chunker_version` so the index version pin in `02-architecture-overview.md` § Versioning works correctly. Define the version constant, the bumping rules, and the tests that enforce it.

**Acceptance criteria.**
- [ ] `ingest/normalize/version.py::CHUNKER_VERSION = "v1.0-normalize"`.
- [ ] Every emitted record includes the version field.
- [ ] A frozen-hash test asserts the SHA-256 of the canonicalization YAML equals an expected constant; bumping the YAML requires updating both the YAML and the constant.
- [ ] Documented bump procedure in `docs/chunker-versioning.md` per the rules in `04-parsing-and-chunking.md` § Chunker versioning.
- [ ] Old normalized files for a previous chunker version are NOT overwritten in place (E11 handles re-normalization in a new corpus version).

**Dependencies.** E03_S05.

**Complexity.** S.

**Labels.** `area:parser`, `kind:infra`.

---

### E03_S08 — Re-normalize the seed corpus

**Description.** Apply the new normalizer to the 50-paper seed corpus from E01_S03 / E02_S10 and replace the stub output. Compare retrieval-relevant statistics (preamble length distribution, definitions per paper, cross-references resolved per paper) to baseline.

**Acceptance criteria.**
- [ ] All 50 seed papers re-normalized; output written under `var/arxmcp/corpus/normalized/`.
- [ ] Stats summary in `var/arxmcp/ops/seed-normalize-stats.json`: median preamble length in tokens, median notation entries per paper, total cross-references resolved.
- [ ] At least 30 of the 50 papers have ≥5 notation entries (math papers typically do).
- [ ] No determinism failures across two runs.
- [ ] Sample-diff in `docs/tier-1b-normalize-sample.md` shows before/after for one chunk on one paper.

**Dependencies.** E03_S07, E02_S10.

**Complexity.** S.

**Labels.** `area:parser`, `kind:research`.

---

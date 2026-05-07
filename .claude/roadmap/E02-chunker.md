# E02 — Chunker (NEW)

**Epic dependencies:** E01 (50-paper seed corpus staged at `var/arxmcp/corpus/raw/` and `var/arxmcp/corpus/parsed/`).

**Goal:** Replace the superseded naive section chunker (E01_S04) with a theorem-aware structural chunker that emits two content-addressable chunks per theorem+proof pair — one for the statement (`embedding_stmt`) and one for the proof window (`embedding_proof`) — each within the 512-token budget required by BGE-M3. The chunker version is stamped on every chunk so that downstream MVCC (E04_S02) and re-embed logic (E03_S02) can detect staleness deterministically. The preamble extractor (E02_S02) provides the deterministic context that replaces any LLM-generated contextual retrieval. The `body_tokens` pre-tokenizer (E02_S03) produces the field that BM25 will index in E04_S04.

**Effort:** ~2 weeks calendar (L+M+M+S+M across five milestones).

**References:** `04-parsing-and-chunking.md` (master spec for theorem/proof pairing, preamble extraction, token budgets), `05-storage-and-indexing.md` § Embedding strategy (512-tok dual-column contract), `08-security-observability-ops.md` (BP1 byte-identical caching requires deterministic chunk content), `09-feature-priorities.md` (Tier 0 chunker requirements).

---

### E02_S01 — Theorem-aware structural chunker

**Status:** NEW
**Tier:** 0
**Effort:** L
**Dependencies:** E01_S03

**Description.** The core chunker walks the LaTeXML HTML5 parse tree for each paper (input from `var/arxmcp/corpus/parsed/<paper_id>/`) and pairs `\begin{theorem}...\end{theorem}` environments with their immediately following `\begin{proof}...\end{proof}`. Each matched pair yields two chunks: a statement chunk (`kind="stmt"`) containing the theorem statement and a proof-window chunk (`kind="proof"`) containing the proof body. Unmatched environments (definitions, lemmas, corollaries, remarks, standalone sections) are emitted as single chunks with appropriate `kind` values (`"definition"`, `"section"`, etc.).

Token counting targets the BGE-M3 maximum of 512 tokens per embedding input. Statement chunks include the preamble text prepended in the embedding-input view (see E02_S02) and must not exceed 512 tokens after prepend. Proof chunks are windowed: if the proof body after preamble prepend + 64-token statement header exceeds 512 tokens, the proof is split into overlapping windows of 512 tokens with 64-token overlap between consecutive windows, each emitted as a separate `kind="proof"` chunk. Tokenization for budget purposes uses the BGE-M3 tokenizer (HuggingFace `AutoTokenizer`); the chunker imports the tokenizer but does NOT load the full model — just the vocab for counting.

Output is written as JSON files at `var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json`. Each file contains the fields defined in the schema below. The `body_tokens` and `preamble_ref` fields are deferred to E02_S03 and E02_S02 respectively; the chunker writes them as `null` initially and they are populated by those milestones. The `chunk_id` field is deferred to E02_S04 (content-addressable hash); the chunker writes a monotonic placeholder `arxiv:<paper_id>:idx<chunk_idx>` until E02_S04 lands.

This milestone must emit enough metadata per chunk — including `theorem_name`, `theorem_label`, and `section_path` — to support theorem-name deduplication in E10_S02 (Sonnet B). Specifically: if a theorem has a `\label{}`, emit it as `theorem_label`; if it has a display name (e.g. `Theorem 3.1 (Riemann–Roch)`), parse and emit the name as `theorem_name`. This metadata is not deduplicated here; that is explicitly E10_S02's scope.

**Deliverables.**
- `ingest/chunker.py` — main chunker module; public API: `chunk_paper(paper_id: str) -> list[ChunkRecord]`
- `ingest/chunker_types.py` — `ChunkRecord` dataclass with all fields
- `var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json` — output schema:
  ```json
  {
    "chunk_id": "arxiv:<paper_id>:idx<N>",
    "paper_id": "<paper_id>",
    "kind": "stmt|proof|section|definition",
    "section_path": ["Introduction", "§2 Main Results"],
    "theorem_name": "Riemann–Roch Theorem",
    "theorem_label": "thm:rr",
    "body_text": "...",
    "body_tokens": null,
    "preamble_ref": null,
    "chunker_version": "v1.0"
  }
  ```
- `pytest tests/test_chunker.py` — golden-output fixture test

**Acceptance criteria.**
- [ ] Chunker produces two chunks (`kind="stmt"` + `kind="proof"`) for each matched theorem+proof pair.
- [ ] No single chunk's embedding-input view (preamble + body) exceeds 512 BGE-M3 tokens.
- [ ] Proof windows use 64-token overlap when proof body exceeds budget.
- [ ] `chunker_version: "v1.0"` is present on every emitted chunk.
- [ ] `theorem_label` and `theorem_name` are emitted when extractable from LaTeXML markup.
- [ ] Running on all 50 seed papers produces at least 300 total chunks (theorem-aware chunking is finer-grained than section-only).
- [ ] Unit test: two-theorem fixture paper emits exactly 4 chunks (2 stmt + 2 proof) with expected `kind` and `section_path` values.
- [ ] Output files written only under `var/arxmcp/corpus/chunks/`; no other side effects.

**Out of scope.** Content-addressable `chunk_id` hashing (E02_S04); `body_tokens` BM25 field (E02_S03); preamble prepend (E02_S02); theorem-name deduplication (E10_S02).

**Risk notes.**
- **Closes H3** (dual 512-tok columns): by emitting separate `stmt` and `proof` chunks each budget-capped at 512 tokens, the chunker enforces that neither embedding input can overflow BGE-M3. This is where the H3 fix originates; E03_S01 and E04_S01 carry it forward.
- Theorem-name and label metadata emitted here prevents a second parse pass in E10_S02 (MEDIUM: theorem-name dedup naive). The dedup logic itself is out of scope here.
- LaTeXML parse quality varies; the chunker should log warnings (not raise) on unparseable environments and continue to the next paper, consistent with the resilience pattern in `01c6579`.

**Labels.** `area:parser`, `kind:feature`, `tier:0`.

---

### E02_S02 — Preamble extractor

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E02_S01

**Description.** The preamble extractor reads the original `.tex` source from `var/arxmcp/corpus/raw/<paper_id>/` and extracts all macro-definition lines: `\newcommand`, `\renewcommand`, `\DeclareMathOperator`, `\def`, and `\let` directives. These are normalized (whitespace collapsed, comments stripped) and written to `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` as a list of strings. A deterministic preamble text is also written: the sorted, deduplicated macro lines joined by newlines. This preamble text is prepended to each chunk's `body_text` in the embedding-input view — it is not merged into `body_text` itself, so the stored `body_text` remains the raw chunk content.

The chunker from E02_S01 is updated to read `preamble.json` and populate the `preamble_ref` field of each chunk with the SHA-256 hash of the normalized preamble text (16 hex chars). This reference lets the embedder (E03_S01) reconstruct the embedding input deterministically from `body_text` + the referenced preamble — supporting BP1 byte-identical caching per `08-security-observability-ops.md`.

This milestone explicitly rejects Anthropic's Contextual Retrieval approach (generating an LLM-written context paragraph per chunk). Contextual retrieval is non-deterministic (LLM output varies across runs), breaks BP1 byte-identical caching, adds latency and cost proportional to corpus size, and introduces a circular dependency on the Anthropic API during ingestion. The preamble-prepend approach is deterministic, free, and math-domain-appropriate: the macro definitions are exactly the context that downstream chunk consumers (math-proof agents) need.

The extractor is designed to be idempotent: re-running on a paper whose `preamble.json` already exists is a no-op unless the raw `.tex` has changed (detected by comparing a hash of the source file against a `source_hash` field in `preamble.json`).

**Deliverables.**
- `ingest/preamble.py` — public API: `extract_preamble(paper_id: str) -> PreambleDoc`
- `ingest/preamble_types.py` — `PreambleDoc` dataclass: `{paper_id, source_hash, macros: list[str], preamble_text: str, preamble_hash: str}`
- `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` — serialized output
- Updated `ingest/chunker.py` — reads `preamble.json` and populates `preamble_ref`
- `pytest tests/test_preamble.py` — tests extraction against a fixture `.tex` file

**Acceptance criteria.**
- [ ] Preamble extractor produces a `preamble.json` for each of the 50 seed papers.
- [ ] `preamble_text` is deterministic across runs on the same source file (sorted, deduplicated, whitespace-normalized).
- [ ] `preamble_ref` in chunk JSON matches `SHA-256(preamble_text)[:16]`.
- [ ] Re-running the extractor on an unchanged paper is a no-op (output unchanged, `source_hash` matches).
- [ ] Unit test: a fixture `.tex` with 3 `\newcommand` and 1 `\DeclareMathOperator` produces a `macros` list of length 4 in deterministic order.
- [ ] Module docstring explicitly states: "Anthropic contextual retrieval is rejected — preamble is deterministic; see `04-parsing-and-chunking.md` § Preamble extraction."

**Out of scope.** Full macro expansion / normalization (applying macros to transform `body_text`) — that is a Tier 2 concern per `04-parsing-and-chunking.md`. This milestone only extracts and stores the raw macro definitions.

**Risk notes.**
- **Closes MEDIUM: contextual retrieval vs preamble overlap.** The design choice is recorded here with explicit rationale so it is not re-litigated in future reviews.
- Papers with multiple `.tex` files require choosing the "root" file; the extractor should use the same heuristic as `fetch_one_paper.py` (largest `.tex` by byte count, or the one `\documentclass` appears in).

**Labels.** `area:parser`, `kind:feature`, `tier:0`.

---

### E02_S03 — `body_tokens` regex pre-tokenizer

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E02_S01

**Description.** At chunk-write time, a Python regex pass over `body_text` produces a whitespace-joined token stream stored in the `body_tokens` field of each chunk JSON. The tokenizer is a simple but math-aware regex: it extracts Latin words (including hyphenated compound terms), strips backslashes from LaTeX command names and emits the command root (e.g. `\mathrm` → `mathrm`, `\partial` → `partial`), and extracts identifier-like fragments from math mode (e.g. `H_1` → `H_1`, `\mathbb{Z}` → `mathbb_Z`). Subscripts and superscripts are joined with underscores to preserve token identity. The result is a string like `"Spec mathrm_Pic partial_t H_1 coherent sheaf"`.

This `body_tokens` string is the field that BM25 will index in E04_S04. Using a Python regex pre-tokenizer (rather than a fictional custom Tantivy LaTeX analyzer) is a deliberate design decision: it is self-contained, testable, deterministic, and ships without any dependency on Rust or a custom analyzer that does not exist. The approach is documented in the module docstring.

The tokenizer is exposed as a standalone function `tokenize_body(body_text: str) -> str` in `ingest/tokenizer.py` so it can be unit-tested independently and reused by the BM25 indexer in E04_S04. It is also wired into `ingest/chunker.py` so that every chunk emitted after this milestone has `body_tokens` populated (not `null`).

Performance target: tokenization of a 512-token chunk should complete in under 1ms on a 2020-era laptop CPU. The regex is compiled once at module load.

**Deliverables.**
- `ingest/tokenizer.py` — `tokenize_body(body_text: str) -> str`
- Updated `ingest/chunker.py` — calls `tokenize_body` and writes result to `body_tokens`
- `pytest tests/test_tokenizer.py` — unit tests for known LaTeX input → expected token stream pairs
- Updated chunk JSON schema: `body_tokens` field populated with token string

**Acceptance criteria.**
- [ ] `tokenize_body("Let $\\mathbb{Z}[x]$ be the polynomial ring")` returns a string containing `mathbb_Z` and `polynomial`.
- [ ] `tokenize_body("By \\mathrm{Spec}\\, R")` returns a string containing `mathrm_Spec` and `R`.
- [ ] Backslashes are stripped from all LaTeX command names in the token stream.
- [ ] Running the chunker on all 50 seed papers with this milestone active produces non-null `body_tokens` on every chunk.
- [ ] Tokenizer performance: ≤ 1ms per 512-token chunk on a reference machine (documented in test).
- [ ] Module docstring states: "No custom Tantivy LaTeX analyzer is used; see H4 remediation in `.claude/roadmap/README.md`."

**Out of scope.** BM25 index construction (E04_S04). Equation-level tokenization for the equation index (E10_S03 — that epic uses MathML tree-edit distance, not BM25). Full macro expansion before tokenization (Tier 2).

**Risk notes.**
- **Closes H4** (regex pre-tokenizer replaces fictional Tantivy LaTeX analyzer). The BM25 index in E04_S04 operates over this field with standard English BM25 — no custom analyzer required. The closure is recorded here so reviewers know where to look.
- The regex approach trades recall on exotic LaTeX for simplicity and determinism. At Tier-0 corpus scale (50 papers), recall loss is acceptable. A smarter tokenizer can be swapped in later without schema changes (only `body_tokens` values change, which triggers a version bump and re-index via E04_S02 MVCC).

**Labels.** `area:parser`, `kind:feature`, `tier:0`.

---

### E02_S04 — Chunker version stamping and content-addressable `chunk_id`

**Status:** NEW
**Tier:** 0
**Effort:** S
**Dependencies:** E02_S01, E02_S02, E02_S03

**Description.** This milestone replaces the monotonic placeholder `chunk_id` from E02_S01 with a content-addressable identifier and stamps every chunk with a `chunker_version` that downstream systems use to detect staleness. The `chunk_id` format is `arxiv:<paper_id>:<sha256(preamble_normalized + body_text)[:16]>` — the hash is computed over the concatenation of the normalized preamble text (from `preamble.json`) and the raw `body_text`. This makes `chunk_id` stable across re-runs of the chunker on the same paper, as long as the preamble and body content are unchanged, and it changes deterministically when either changes.

The `chunker_version` field is set to the string `"v1.0"`. Bumping this value (to `"v1.1"` etc.) is the signal to the LanceDB MVCC writer (E04_S02) and the re-embedder (E03_S02) that existing rows are stale and must be replaced. The version string is defined as a module-level constant in `ingest/chunker.py` so it appears in exactly one place.

This milestone also adds a `chunk_manifest.json` file per paper at `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` listing all `chunk_id`s emitted for that paper, their `kind`, and the `chunker_version`. The manifest is used by the eval harness (E05_S01) to validate that curated `chunk_id` references in `tests/eval/fixtures/queries.json` still exist after a re-chunk.

**Deliverables.**
- Updated `ingest/chunker.py` — `chunk_id` computed from preamble + body hash; `chunker_version = "v1.0"` constant
- `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` — per-paper manifest
- `pytest tests/test_chunker_ids.py` — asserts that re-running chunker on same paper yields identical `chunk_id`s

**Acceptance criteria.**
- [ ] `chunk_id` matches `arxiv:<paper_id>:<sha256(preamble_normalized + body_text)[:16]>` exactly.
- [ ] Re-running chunker on an unchanged paper produces byte-identical `chunk_id`s.
- [ ] Modifying `body_text` (simulated in test by changing a word) produces a different `chunk_id`.
- [ ] `chunker_version: "v1.0"` appears on every chunk; it is defined as a single constant in `chunker.py`.
- [ ] `chunk_manifest.json` exists for every paper in the seed corpus after a full chunker run.
- [ ] `CHUNKER_VERSION` constant is the only place the version string `"v1.0"` is defined.

**Out of scope.** MVCC version bump handling (E04_S02). Re-embed skip logic (E03_S02). Eval harness query fixture curation (E05_S01).

**Risk notes.**
- The content-addressable `chunk_id` is the linchpin of BP1 byte-identical caching (`08-security-observability-ops.md` § Caching). If the hash input is not fully deterministic (e.g. dict key ordering), cache hits will be missed. The test must simulate a fresh Python process to catch any non-determinism from object ordering.

**Labels.** `area:parser`, `kind:feature`, `tier:0`.

---

### E02_S05 — Chunker fixture suite

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E02_S01, E02_S02, E02_S03, E02_S04

**Description.** A golden-output fixture suite that locks in the chunker's behavior against 10 of the 50 seed papers. For each fixture paper, the expected outputs are hand-curated: expected chunk count, expected `kind` distribution (e.g. 12 stmt + 12 proof + 4 section + 2 definition), and at least one expected `chunk_id` per paper verified by running the finalized chunker and recording its output. These fixtures are committed to the repository and must pass on every CI run.

The fixture suite serves two purposes. First, it provides regression protection: if a chunker change breaks determinism or theorem-pairing logic, `pytest tests/test_chunker.py` fails with a diff showing which paper's output changed and how. Second, it bootstraps the eval harness in E05_S01: because the eval harness references specific `chunk_id`s in `tests/eval/fixtures/queries.json`, those IDs must be stable — this fixture suite proves they are stable by construction.

The 10 fixture papers should be chosen to exercise diverse scenarios: papers with many theorems, papers with appendix-only proofs, papers with no explicit proof environments (definition-heavy), and at least one paper with a multi-window proof (a proof that exceeds 512 tokens and is split into overlapping windows). Hand-curation of expected chunk counts requires running the chunker once and then reviewing the output for correctness before committing.

The fixture files are stored at `tests/fixtures/chunker/<paper_id>.expected.json` with schema `{paper_id, chunk_count, kind_counts: {stmt, proof, section, definition}, expected_chunk_ids: ["arxiv:..."], chunker_version: "v1.0"}`.

**Deliverables.**
- `tests/fixtures/chunker/<paper_id>.expected.json` — 10 fixture files
- `pytest tests/test_chunker.py` — runs chunker against all 10 fixtures, asserts golden output match
- CI integration: `make test` runs `pytest tests/test_chunker.py`
- `docs/chunker-fixtures.md` — brief notes on which papers cover which scenarios and why they were chosen

**Acceptance criteria.**
- [ ] 10 fixture files committed, one per paper.
- [ ] Each fixture file contains at least one `chunk_id` that can be looked up in the chunker output.
- [ ] `pytest tests/test_chunker.py` passes on a clean checkout (i.e., chunk IDs are reproducible byte-identically).
- [ ] At least one fixture paper exercises a multi-window proof (proof body > 512 BGE-M3 tokens).
- [ ] At least one fixture paper has no explicit `\begin{proof}` (exercises the section/definition path).
- [ ] `pytest tests/test_chunker.py` completes in under 60 seconds on a laptop (chunking 10 papers is fast).
- [ ] CI (`make test`) includes this test suite.

**Out of scope.** Eval harness query curation (E05_S01 — references these `chunk_id`s but curates the query–relevance pairs separately). Embedding fixture papers (E03 scope).

**Risk notes.**
- These fixtures are the ground truth that E05_S01 depends on. If a later chunker change legitimately alters `chunk_id`s (e.g. a `chunker_version` bump), the fixture files must be regenerated and the eval fixture queries updated in lockstep. Document this update procedure in `docs/chunker-fixtures.md`.
- Papers where LaTeXML output differs between LaTeXML versions may produce non-deterministic parse trees. Pin the LaTeXML version in `pyproject.toml` or the fixture notes.

**Labels.** `area:parser`, `kind:test`, `tier:0`.

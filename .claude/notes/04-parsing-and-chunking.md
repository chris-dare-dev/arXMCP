# 04 — Parsing and Chunking

## The parser fallback chain

Every paper in our corpus must be turned into a structured, macro-expanded
representation before it can be chunked and embedded. Tools, in priority order:

1. **ar5iv HTML cache (primary path).** Fetch
   `https://ar5iv.labs.arxiv.org/html/<arxiv_id>` (or its successor at
   `https://arxiv.org/html/<arxiv_id>`). This is pre-rendered LaTeXML output:
   HTML5 with MathML, macros expanded, cross-references resolved. Coverage is
   roughly 90%+ post-2007. **Use ar5iv as a cache, not a fallback.** This saves
   weeks of CPU time on initial corpus ingestion.

2. **Local LaTeXML on `/e-print/` source (cache-miss path).**
   `https://github.com/brucemiller/LaTeXML`. The most complete LaTeX→XML/HTML5+MathML
   converter in existence. Slow (5–60 seconds per paper). It expands `\newcommand`
   macros, resolves `\input`/`\include` chains, and emits MathML you can normalize
   downstream. Coverage on hep-th drops to ~80% because of exotic `.sty` files;
   for math.AG it's closer to 95%.

3. **Nougat (Meta) on the PDF (last-resort path).**
   `https://github.com/facebookresearch/nougat`. Vision transformer that converts
   PDF pages to markdown+LaTeX. Originally trained on arXiv. Equation fidelity is
   acceptable on clean papers (~85%), much worse on dense hep-th preprints with
   long display equations or non-standard fonts. Slow (~5–30s per page on GPU).
   **Largely unmaintained as of late 2024.** Use only when 1 and 2 both fail.

4. **Skip.** Log to `ops/parser-failures/` and surface in a weekly degraded-coverage
   report. Don't silently feed the agent low-confidence content.

## Tools we considered and rejected

- **TeX4ht / plastex**: worse macro coverage than LaTeXML in 2026. Don't bother.
- **pylatexenc**: tokenizer/walker, not a renderer. **Useful for chunk segmentation**
  (finding theorem environments, splitting at section boundaries) once LaTeXML has
  produced expanded output. Not a primary parser.
- **Pandoc**: surprisingly reasonable for clean math papers, surprisingly bad on
  physicist macros. Don't make it primary.
- **Marker** (`https://github.com/VikParuchuri/marker`): faster than Nougat,
  similar quality tradeoffs. Keep on hand as Nougat alternative if Nougat
  installation breaks; otherwise skip.
- **GROBID**: strong for metadata and reference extraction; equation extraction
  is weak (emits MathML approximations). Only useful if we wanted citation
  extraction from PDF — but we get that from INSPIRE/OpenAlex anyway.
- **Pure pypdf / pymupdf / pdfplumber**: mangle math. **Banned from the parser
  chain.** Useful only for low-stakes metadata fallback.

## Macro normalization (the make-or-break step)

After the parser produces HTML5 + MathML, we run a normalization pass that:

1. **Resolves all author-local `\newcommand` and `\renewcommand`** by walking the
   MathML and substituting expansion. LaTeXML does most of this for us; we
   re-validate.
2. **Maps common notation variants to a canonical form.** Examples:
   - `\acute{e}tale`, `\'etale`, `\mathrm{\'et}` → "étale"
   - `\Bbb{R}`, `\mathbb{R}`, `\R` (custom) → `\mathbb{R}`
   - `\Z`, `\mathbb{Z}` → `\mathbb{Z}`
   - `\cF`, `\mathcal{F}`, `\mathscr{F}` → `\mathcal{F}` (lossy but useful for
     retrieval; preserve original in raw chunk text)
3. **Builds a per-paper notation table** at parse time:
   `definitions[paper_id] = [{symbol, expansion, defining_chunk_id, scope}]`.
   This becomes a first-class index (see
   [05-storage-and-indexing.md](05-storage-and-indexing.md), `get_definitions`
   tool).

The normalization layer must be **deterministic and versioned**. A change to the
normalizer is a chunker version bump.

## Chunking strategy for research-math papers

Naive section/subsection chunking destroys retrieval quality. Six rules:

### Rule 1: Theorem + proof are one chunk

A bare theorem statement ("Lemma 4.2: $X$ is flat") is a retrieval black hole —
the embedder has no semantic content to anchor on. Pair `theorem`, `lemma`,
`proposition`, `corollary` environments with their *following* `proof` environment
into a single chunk. If the proof is long (>2000 tokens), keep the statement
chunk separately *and* prepend it as a header to each proof sub-chunk.

### Rule 2: Per-paper preamble prepended to every chunk

Extract `\newcommand` definitions and "throughout this paper, $X$ denotes..."
prose from the introduction. Prepend this as a header to every chunk from the
paper before embedding. **This is the single biggest retrieval-quality lever
after macro expansion.** Two papers using `X` to mean different things now embed
differently because their preambles differ.

### Rule 3: Display equations are first-class atoms

Each numbered display equation gets its own retrievable record with:
- The equation in canonical form (macro-expanded MathML + presentation LaTeX).
- The surrounding sentence ("As shown in equation (3.7), ...") as context.
- A back-reference to the parent theorem or section chunk.

The autoformalizer's most common query is "find me the paper with an equation
that looks like this." A flat chunk store can't answer that; equation atoms can.

### Rule 4: Cross-references resolved into chunks

`(see Lemma 3.4)` should be resolved during chunking — append the actual statement
of Lemma 3.4 as a "referenced statements" appendix at the end of the chunk. LaTeXML
gives us the cross-reference targets; we expand them inline.

### Rule 5: Three-level hierarchical index

Index every paper at three levels:

| Level | Granularity | Used by |
|---|---|---|
| **paper** | abstract + section list + key terms | Sketcher (broad survey) |
| **section** | section summary (1–2 paragraphs) + chunk pointers | Autoformalizer (mid-grain context) |
| **theorem** | theorem statement + proof + per-paper preamble | Tactician (fine-grained retrieval) |

Different agent roles query different levels. The MCP tool surface exposes a
`level` parameter on the search tool.

### Rule 6: Stable chunk IDs are content-addressable

Chunk ID format: `arxiv:<paper_id>:<sha256(canonical_chunk_bytes)[:16]>`.

**Rationale:**
- Editing a chunk produces a new ID. Old retrieval results pointing to the old ID
  remain reproducible against an old corpus version.
- Two papers that quote each other verbatim get *the same* sub-chunk ID for the
  shared text. Useful for deduplication and citation tracing.
- Cache keys at every layer (retrieval cache, prompt cache) become stable.

The `paper_id` portion is the canonical arXiv ID (e.g. `2401.01234`), without
version suffix; version is a separate field. Two versions of the same paper give
two distinct chunk IDs because the canonical bytes differ.

## What gets stored per chunk

```json
{
  "chunk_id": "arxiv:2401.01234:a1b2c3d4e5f60718",
  "paper_id": "2401.01234",
  "version": 3,
  "level": "theorem",
  "kind": "theorem_with_proof",
  "section_path": ["3. Main results", "3.2 The flat case"],
  "label": "Theorem 3.4",
  "title_in_paper": null,
  "preamble": "Throughout this paper, $X$ denotes a smooth projective variety over $\\mathbb{C}$. \\newcommand{\\AA}{\\mathcal{A}}...",
  "body_canonical": "Theorem 3.4. Let $X$ be a smooth projective variety...",
  "body_raw_latex": "...",
  "mathml": "<math>...</math>",
  "referenced_chunks": ["arxiv:2401.01234:def123...", "arxiv:1812.04567:thm456..."],
  "equation_atoms": ["arxiv:2401.01234:eq789..."],
  "char_offsets": {"start": 12345, "end": 14512},
  "embedding_text": "...",  // what the embedder sees: preamble + body_canonical
  "chunker_version": "v1.1",
  "embed_model": "bge-m3@2024-08"
}
```

The `embedding_text` field is what the embedder consumes. It is deterministic
and reproducible from `(preamble, body_canonical)` plus a fixed template — never
include timestamps or random content here.

## Equation atom record

```json
{
  "equation_id": "arxiv:2401.01234:eq789...",
  "paper_id": "2401.01234",
  "label": "(3.7)",
  "presentation_latex": "\\partial_t f = \\Delta f + V f",
  "mathml": "<math>...</math>",
  "ascii_form": "d/dt f = laplacian f + V f",
  "context_sentence": "As shown in equation (3.7), the heat operator...",
  "parent_chunk_id": "arxiv:2401.01234:a1b2c3d4e5f60718",
  "is_numbered": true,
  "is_display": true
}
```

ASCII form is for keyword/BM25 fallback. MathML is the canonical form.
Presentation LaTeX is for human-readable display in tool results.

## Chunker versioning

Every chunk carries `chunker_version`. When we change chunking strategy:

1. Bump version (e.g. `v1.0` → `v1.1`, as in `embedder-truncation-m1`).
2. Re-chunk affected papers in a new corpus version.
3. Re-embed chunks with the same embedding model (no need to re-train embedder).
4. Atomic-swap the LanceDB version alias the MCP server reads.
5. Keep the old version online for N=7 days for rollback.

### Token budget (embedder-truncation-m1, 2026-05-27)

| Constant | Old | New |
|---|---:|---:|
| `BGE_M3_MAX_TOKENS` | 512 | **2048** |
| `STMT_MAX_TOKENS`   | 512 | **1920** (128-token preamble headroom) |
| `PROOF_MAX_TOKENS`  | 448 | **1856** (192-token headroom; proofs re-embed inline stmt) |
| `EMBED_BATCH_DEFAULT` | 32 | **8** (CPU O(n²) attention guard) |

The 2048-token budget is within BGE-M3's native 8192-token capability —
no model swap, no new dependency. The cap was raised because 70% of
chunker-truncated chunks were statement-class (`stmt`/`lemma`/`def`/
`prop`); a truncated theorem statement is a direct math-fidelity hazard
per Rule 1 of this note ("Theorem + proof are one chunk"). Post-bump
B-1 canary on 1902.08184: 0.5% truncation rate on stmt-class chunks
(down from ~30% at the old budget).

## Failure modes during parsing

| Failure | Action |
|---|---|
| ar5iv 404 | Fall through to local LaTeXML |
| LaTeXML build error (missing class file) | Log; try Nougat |
| LaTeXML hang (>5 min) | Subprocess kill; mark as parser-failure |
| Nougat hallucinated equation indices | Heuristic detection (equation count vs PDF page count); demote confidence |
| `\cite{}` key resolves to nothing | Drop reference rather than dangling text |
| Macro expansion infinite loop | Bounded recursion (max depth 50); log; mark as degraded |
| Source tarball corrupt | Re-fetch once; if persistent, mark as parser-failure |

Every failure mode has a log line and a `parser-failures/` artifact. Weekly
human review of failures drives parser improvements.

## Non-goals for parsing v1

- Figure / image extraction. (See [09-feature-priorities.md](09-feature-priorities.md);
  TikZ-cd diagrams in math.AG are interesting but v2.)
- OCR of scanned pre-2007 papers.
- Translation of non-English papers (we filter by English at OAI-PMH harvest time).
- Proof-skeleton classification (induction / contradiction / etc.) — v2 feature.

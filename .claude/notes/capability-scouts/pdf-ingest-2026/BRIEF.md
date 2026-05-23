# Scout Brief — pdf-ingest-2026

**Scope:** Investigate the 2026 landscape for ingesting math/physics PDFs
(especially textbooks like Hartshorne, Griffiths-Harris, Bourbaki,
Polchinski, plus lecture-notes-as-PDF like Milne/Caraiani) into a
local-first MCP server that already has a deep math-fidelity contract
built on LaTeXML + HTML5 + MathML over ar5iv-rendered arXiv source.

## Context (read first; do not duplicate)

- **Internal deep dive:** `.claude/notes/pdf-capability-deep-dive.md`
  concludes (a) zero PDF capability today; (b) constitutional ban on
  pypdf/pymupdf/pdfplumber as primary parsers; (c) recommended Path B
  (source-first .tex fetcher, S, 1 milestone) → Path A
  (Marker→LaTeXML, M, 2-3 milestones) → Path C (full parallel
  textbook corpus, XL, defer).

## arXMCP-specific constraints the scout MUST treat as load-bearing

- **Math fidelity over coverage** (`CLAUDE.md`,
  `.claude/notes/01-mission-and-context.md`): equations ARE the
  content for math.AG / math.NT / hep-th / math-ph; any pipeline that
  flattens math to glyphs is disqualified for the primary path.
- **Local-first / single-workstation deployment** (`CLAUDE.md §4.1`,
  `.claude/notes/08-security-observability-ops.md`): no hosted-API
  primary dependencies; subprocess isolation for GPL-licensed tools
  (Marker is GPL-3, would need this).
- **No-fork policy** (`CLAUDE.md §4.7`): use ideas not code;
  existing arxiv-MCP servers that use pypdf are
  read-the-surface-not-import targets.
- **7-tool MCP surface is intentional**
  (`.claude/notes/06-mcp-server-design.md` H6): adding parallel
  `search_textbooks` / `get_textbook_chapter` / `get_exercise` tools
  threatens tool-block bloat — must be justified explicitly.
- **Per-notebook isolation pattern (m6)**: the existing
  `var/arxmcp/notebooks/<slug>/lancedb/` blast radius is the
  natural home for a textbook-only corpus; do NOT propose changes
  that pollute the global arXiv corpus.
- **Chunk-id contract** is anchored on arXiv-ID regex
  (`ingest/identifiers.py`); textbooks would need
  `textbook:<slug>:<sha>` or similar; this is a schema migration
  concern.
- **Existing chunker is theorem-aware** (theorem/lemma/proposition +
  proof pairing); textbooks need chapter/section/exercise/definition
  awareness — significantly different chunking unit.
- **Threat model** (`.claude/notes/08-security-observability-ops.md`):
  PDF inputs have NO current threat carve-out; would need Threat 3.5
  / Threat 8 (PDF-bomb, embedded JS, polyglot, glyph forgery,
  decompression bombs).

## Specific scout questions

### 1. COMPETITIVE
How do other research-math-paper MCP servers, paper-management tools
(Zotero, Mendeley, Citavi), and academic-PDF tools (paper-qa,
PDFTalk, Adobe Acrobat AI Assistant, Semantic Scholar's PDF reader,
NotebookLM, MathPix Snip+Notebooks) handle textbook-scale PDFs with
math content? What are they doing better than the local-first /
LaTeXML-fidelity stack? What are they doing worse?

### 2. MATH-RESEARCH
What does the 2025-2026 research literature say about retrieval over
math textbooks vs research papers? Has anyone published an empirical
comparison of (a) Marker→LaTeXML vs (b) Nougat vs (c) MathPix vs
(d) pure source-fetcher pipelines on math-content fidelity? What
about textbook-aware chunking strategies — chapter/section/exercise
vs theorem/proof? Has the autoformalization research community
(LeanDojo, miniF2F, DeepSeek-Prover, AlphaProof) settled on a
canonical textbook ingest pipeline, or is everyone still doing
ad-hoc parsing?

### 3. OSS-TRENDS
What's the actual 18-month maintenance trajectory of Marker
(vikparuchuri/marker) — release cadence, issue close rate,
breaking-change frequency? Are there 2026 successor projects that
have eclipsed it? What about Datalab's other tools (surya, etc.)?
What's the current state of MathML output in PDF→Markdown converters?
Are there any new options that emit MathML directly (rather than
LaTeX-for-LaTeXML)? Specifically check: ContextLab, Anyparser,
MinerU (PDF-Extract-Kit), Docling (IBM Research, 2024 release),
DocLayoutXY. Note license + math fidelity for each.

### 4. MULTI-AGENT
What sketcher → autoformalizer → tactician → fixer pipelines have
integrated textbook-as-source in 2025-2026 (vs papers-only)? Are
there documented cases where textbook ingestion meaningfully
improved theorem-proof retrieval quality (vs simply expanding the
corpus)? Are there new agent-orchestration patterns specific to
textbook-grain content (vs paper-grain) — e.g., chapter-walks,
exercise-as-retrieval-target, definition-graph extraction?

### 5. ADVERSARY
Stress-test the deep-dive's recommendation chain (Path B → Path A
→ defer Path C). What's the case AGAINST Path B (source-first)?
E.g., is the .tex source for course-notes-as-PDF actually as
reliably-published as the dive assumes (manual sample of 10 random
notes from arxiv-listed authors)? What's the case AGAINST Path A —
does the Marker-GPL-3 subprocess boundary actually hold in
litigation-style scrutiny? Are there mathematical-content-fidelity
failure modes that the dive missed (e.g., commutative diagrams via
TikZ-cd, marginalia, footnoted definitions)? Is there a CRITICAL
existing alternative the dive didn't consider?

## Expected output

Per `phase-prioritize.md`: a RICE-ranked list of capability
candidates with effort + impact + confidence + reach, ready to feed
`/roadmap` (probable next-step invocation:
`roadmap pdf-textbook-ingest --brief ...`).

## Survey mode

**standard** (5 scouts). Not `--deep` (Sonnet adversary is
sufficient for this scope; Opus would be over-investment for a
sub-S scope question).

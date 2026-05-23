# Synthesis — pdf-ingest-2026

**Phase 2 of 4.** Unified opportunity catalog merged from the 5 Phase-1
scout briefs (competitive, math-research, oss-trends, multi-agent,
adversary).

---

## 1. Executive summary

The 5 scouts converged on three claims with high triangulation
strength: (a) **the deep dive's Marker recommendation is stale —
MinerU and Docling are now stronger Path-A candidates** with cleaner
licenses, post-dating the dive's snapshot (4 briefs agree); (b)
**every modern parser emits LaTeX-in-Markdown, never MathML directly**,
so the dive's LaTeXML round-trip is structurally unavoidable but the
front-end parser is hot-swappable (3 briefs); (c) **definition-graph
extension over the existing Kùzu graph beats new MCP tools** for
textbook retrieval, both on retrieval-quality grounds and BP1 cache
discipline (3 briefs). The strongest disagreement is around **Path B's
empirical viability**: the adversary catches that the dive's single
named-author evidence (Milne) is empirically wrong — Milne's source is
NOT publicly published for most expository notes — which collapses
Path B's "shimura backlog is solved" claim. **17 deduplicated
candidates** across the 7-category taxonomy, of which 6 have ≥3-brief
triangulation. The top cross-cutting tension is **scope discipline vs.
schema-migration spread**: a credible textbook ingest milestone needs
parser + chunker + schema + threat-model + eval + citation-graph
extensions, each of which is independently scope-justifiable; the
challenger in Phase 3 must call whether the bundle holds together or
fractures.

---

## 2. Triangulation strength

| Evidence-source count | # candidates | Note |
|---|---|---|
| 5 briefs | 0 | (no single capability surfaced in every scout) |
| 4 briefs | 2 | Strong consensus; Phase-3 challenger has the weakest hand here |
| 3 briefs | 4 | High signal — usually a real opportunity |
| 2 briefs | 6 | Worth carrying forward; challenger may invalidate |
| 1 brief | 5 | Weak signal — Phase-3 should re-verify or downgrade |

(Same-scout multiple mentions count once.)

---

## 3. Candidate catalog

Ordered: high-triangulation-first within each category, then by t-shirt
size ascending.

### Category: Corpus / ingest

#### CAND-1 — Replace Marker with MinerU 2.5 OR Docling as Path-A primary parser

**Category:** Corpus / ingest
**Size:** M (parser-swap is the easy part; the harder part is
empirical bake-off + the schema bump for `parser_used` enum)
**Evidence triangulation:** 4 briefs (competitive ✓, math-research ✓,
oss-trends ✓, adversary ✓)

**What it is:** The dive picked Marker (GPL-3) as the recommended
Path-A primary parser circa 2024-cutoff knowledge. Three credible
2025-2026 successors have eclipsed it: **MinerU 2.5** (Apache-2.0-base,
64.5k stars, 96.4 CDM on SCE per OmniDocBench, monthly releases),
**Docling** (IBM Research, MIT, 60.2k stars, 100+ releases since
Aug 2025, ships **Granite-Docling-258M** which is the only candidate
that emits MathML in HTML export natively), and **olmOCR 2** (Allen
AI, Apache-2.0, RLVR-trained, requires 12GB+ VRAM). The choice is
parser-side; downstream chunker / embedder / LanceDB chain stays
unchanged.

**Why it matters:** Marker's GPL-3 subprocess boundary is the dive's
"confirm with operator" caveat that — per adversary F-A1 — should
block the recommendation rather than annotate it. MinerU and Docling
eliminate that concern. Docling's MathML emission *might* skip the
LaTeXML pass entirely (1-day spike to verify) — savings compound over
every textbook ingested.

**Sources:**
- Competitive scout: §2 candidates C3 (Granite-Docling), C4 (MinerU 2.5)
- Math-research scout: §2 candidates 2.1 (MinerU 2.5), 2.2 (olmOCR 2),
  2.3 (Docling/Granite-Docling)
- OSS-trends scout: C1 (MinerU), C2 (Docling), C3 (olmOCR), theme 1
  ("the 2026 successor wave to Marker is real and license-friendly")
- Adversary scout: F-A1 (CRITICAL, GPL boundary), Alt-5 (Docling
  missed), Alt-6 (MinerU missed)

**Closest arXMCP analog (today):** `ingest/bulk_ingest.py:41` —
implicit "ar5iv → LaTeXML → skip-and-log" ladder; no Marker / MinerU /
Docling integration. Schema-side: `parser_used` enum at
`05-storage-and-indexing.md:140` documents `{ar5iv, latexml_local,
nougat}`; would need `mineru_latexml`, `docling`, `marker_latexml`
values added.

**Sketch:** Subprocess invocation pattern (mirrors `latexmlc`).
1-day spike: take 5 sample pages from Hartshorne / Griffiths-Harris /
Bourbaki + 1 page from a known-clean math.AG arxiv paper for control.
Run all three parsers (MinerU, Docling, Marker). Compute CDM per
page (see CAND-7). Pick the winner; document the bake-off in
`.claude/docs/textbook-parser-bakeoff.md`. The downstream LaTeXML
re-pass stays unchanged unless Docling's MathML path is good enough
to skip it. `ingest/pdf_<parser>.py` driver follows the existing
`ingest/ar5iv_fetch.py` shape.

**Open questions:**
- Does Granite-Docling's MathML output pass arXMCP's chunker
  unmodified? Spike-blocked.
- Which scout's recommendation wins the bake-off? Genuinely
  uncertain; depends on textbook layout class (single-column vs
  multi-column vs marginalia-heavy).

---

#### CAND-2 — Per-notebook PDF upload gate with pdfid pre-scan + threat-model carve-out

**Category:** Corpus / ingest
**Size:** S (pdfid is ~500 LOC vendored, BSD-style; the carve-out
docs are larger than the code)
**Evidence triangulation:** 3 briefs (oss-trends ✓, adversary ✓,
math-research implicit via threat-model reference)

**What it is:** Before any PDF reaches the parser, a fast surface-scan
gate using **Didier Stevens' pdfid.py** (~500 LOC, BSD-style, CERT-
recommended, shipped in Kali Linux + REMnux). Catches PDF-bomb
warning signs (object counts > N, embedded JavaScript flag, AcroForm
flag, polyglot indicators) before the parser sees the bytes. Pair
with a Threat 3.5 / Threat 8 doc extension in
`.claude/notes/08-security-observability-ops.md`.

**Why it matters:** The dive scopes "PDF-bomb detection (refuse if
uncompressed pages > 5000 or any object > 50 MB)" as part of the Path
A threat-model extension but doesn't quantify the work. OSS-trends
shows the work is **smaller than the dive implied** — vendoring pdfid
solves the surface-scan layer cheaply. Combined with raising the
upload cap to 200 MB for textbooks (adversary F-A6 flags this as a
footprint risk if not paired with hardening), this is the
defense-in-depth the dive's Path A requires before the parser cap
even matters.

**Sources:**
- OSS-trends scout: C8 (pdfid + peepdf), theme 4 ("PDF-safety is
  solvable with small audited tools")
- Adversary scout: F-A6 (cap-raise sequence), F-G6 (restic retention,
  non-OA carve-out)

**Closest arXMCP analog (today):** `server/routes/notebooks.py:483`
(`_is_html_bytes` magic-byte sniff); `server/routes/notebooks.py:127`
(`_arxiv_url_to_paper_id` rejects `/pdf/` URLs). The pattern exists;
PDF acceptance is the inverse direction.

**Sketch:** Vendor `tools/security/pdfid_vendored.py` (with full BSD
attribution). Add `_pdfid_safety_scan(bytes)` to the upload route
that runs ALL of: magic-byte check, pdfid surface scan, configurable
size cap (per-notebook), refuse-on-JavaScript-flag default. Threat
3.5 doc extension covers polyglot + decompression-bomb + glyph
forgery (the last is NOT solved by pdfid — explicit scope caveat).
Per-notebook upload cap raised from 10 MB to 200 MB ONLY for
`notebook_kind: "textbook"`; arXiv path unchanged.

**Open questions:**
- Glyph-forgery (embedded fonts that mis-map symbols) is the one
  threat pdfid doesn't catch. Accept the gap or add a separate
  module? Recommend acceptance with explicit documentation; the
  threat is theoretical for math content.

---

#### CAND-3 — Textbook-aware hierarchical chunker (book/chapter/section/exercise/definition)

**Category:** Corpus / ingest
**Size:** L (the chunker is the largest single component; ProofNet
schema is the template but the implementation is custom)
**Evidence triangulation:** 4 briefs (competitive ✓, math-research ✓,
multi-agent ✓, adversary ✓)

**What it is:** Parallel to the existing theorem-aware chunker
(`ingest/chunker.py`), a `ingest/textbook_chunker.py` that emits
hierarchical chunks at book / chapter / section / theorem / exercise /
definition granularity. Schema bump: `chunks.level` enum extends from
`{paper, section, theorem}` to add `{book, chapter, exercise,
definition}`. Per-chapter preamble inheritance (textbook-shaped,
not paper-shaped — adversary F-M6).

**Why it matters:** Every competitor reviewed chunks textbook PDFs
by **page**, not by structure (competitive theme 2: "no one ships
textbook-aware chunking"). arXMCP's existing theorem-aware chunker
is already ahead of the field for papers; extending to textbooks
would be SOTA. Multi-agent scout's strongest finding: **ProofNet's
`(theorem_label, chapter, source)` schema is the reusable template
for textbook chunk metadata**, and the autoformalization research
(NaturalProver, ProofNet) shows "retrieve chapter intro before the
target theorem" is decisively higher quality than naive retrieval.

**Sources:**
- Competitive scout: theme 2 ("textbook-aware chunking is uncontested
  territory")
- Math-research scout: §2.9 (HiChunk / HiCBench hierarchical chunking
  reference), §2.5 (Late Chunking complement for textbook context),
  theme c
- Multi-agent scout: §2.4 (NaturalProver / ProofNet schema lift),
  architectural alignment recommendation
- Adversary scout: F-M2 (marginalia gap), F-M3 (multi-column),
  F-M5 (inline-vs-display lost), F-M6 (per-chapter preamble — explicit
  call-out that the dive's "downstream chunker is untouched" promise
  doesn't hold)

**Closest arXMCP analog (today):** `ingest/chunker.py` — theorem-aware
but paper-shaped. `ingest/preamble.py` — paper-grade single-block
preamble extraction. The textbook case needs per-chapter +
per-section preamble inheritance. Schema:
`.claude/notes/04-parsing-and-chunking.md` rules 1-3.

**Sketch:** New `ingest/textbook_chunker.py` that consumes
Marker/MinerU/Docling output. Emits chunks tagged with
`level: {book, chapter, section, theorem, definition, exercise}`,
`chapter`, `section`, `exercise_number`, `textbook_slug`. Reuses
chunker_version pattern from `04-parsing-and-chunking.md:186-193`;
new version `v2.0` reserved for "textbook-aware". Per-chapter preamble
extractor inherits from per-section, which inherits from per-book.
ProofNet metadata schema mapped 1:1.

**Open questions:**
- How aggressively to chunk exercises? Per-exercise is high-cardinality
  but matches miniF2F/ProofNet retrieval target shape. Recommend
  per-exercise.
- TOC discovery: 95% of publisher textbooks have PDF bookmarks; most
  lecture-notes-as-PDF don't. Heuristic fallback over heading
  detection is needed (competitive C1 PDF-specific note).
- Does the per-chapter preamble inheritance affect the existing
  embedder's preamble-prepended pattern? Likely yes — separate
  chunker_version handles this safely.

---

#### CAND-4 — Late chunking for textbook-scale long-context embedding (Jina, Sep 2024)

**Category:** Corpus / ingest
**Size:** S (~50 LOC additional preprocessing in `ingest/embedder.py`)
**Evidence triangulation:** 1 brief (math-research ✓)

**What it is:** Encode the entire long document (chapter or book)
through a long-context embedder ONCE, then mean-pool token embeddings
within chunk boundaries. Each chunk's embedding "knows about" the
surrounding sentences (especially preambles, definitions introduced
earlier in the document) without the chunk text itself having to
repeat them. Jina-V3 reference impl; BGE-M3 (8k context) is
compatible. arXiv:2409.04701.

**Why it matters:** Direct alternative / complement to arXMCP's
existing "preamble prepended to every chunk" pattern
(`04-parsing-and-chunking.md` Rule 2) for the textbook case where the
"preamble" effectively spans the entire prior text. Particularly
attractive for textbooks because a textbook is a single
contextually-coherent document, unlike the arXiv paper corpus where
each paper is its own context. Net throughput is lower (long forward
= O(n²) attention) but quality is higher per Jina's benchmarks.

**Sources:**
- Math-research scout: §2.5 (Late Chunking), theme d (complement to
  preamble-prepend)

**Closest arXMCP analog (today):** `ingest/embedder.py` BGE-M3
dual-column encoder. The per-paper-preamble logic in
`ingest/preamble.py`. Late chunking is a method-extension to the
embedder, not a replacement.

**Sketch:** New embedding-method `late_chunked_v1` (cache-stable
tag). Gated behind `chunker_version` bump. Wire into
`ingest/embedder.py` as an opt-in mode triggered by
`notebook_kind: "textbook"`. Existing per-paper-preamble logic
preserved for arXiv path. Apache-2.0 reference impl at
`jinaai/late-chunking`.

**Open questions:**
- Worth the throughput hit? Spike answer: per-chapter forward pass on
  a 30-page chapter (~20k tokens) is ~2-3 seconds on M2 Max BGE-M3;
  acceptable.

---

### Category: Citation graph

#### CAND-5 — Add `defines` / `defined_by` edge to Kùzu graph + extend `cite_neighbors` enum

**Category:** Citation graph
**Size:** M (schema bump + graph queries + tool-schema additions;
~200 LOC + tests)
**Evidence triangulation:** 3 briefs (math-research ✓, multi-agent ✓,
adversary ✓)

**What it is:** Today the Kùzu graph carries `CITES` and `PROVES`
edges. Add a new `defines` / `defined_by` edge between definitions
and concepts they introduce or invoke. Extend the `cite_neighbors`
tool's `direction` enum from `{cites, cited_by, proves, proven_by}`
to add `{defines, defined_by}`. This is the "definition-graph
expansion at autoformalizer-tool-call time" pattern that
research literature (arXiv:2502.12065 "Autoformalization in the Wild",
arXiv:2510.23637 graph-augmented premise selection) shows is a
+16-43% retrieval lever. **The most-cited single capability across
the 5 briefs.**

**Why it matters:** Multi-agent scout's load-bearing conclusion:
"the textbook surface should be **definition-graph extension** (low
risk, high leverage), NOT chapter-walk (cache-hostile) and NOT new
MCP tools (BP1 byte-stability discipline)." Math-research scout's
§2.6 + §2.7 surface two independent papers (LemmaBench, graph-
augmented premise selection) that argue for the same capability.
Adversary F-G3 flags that `cite_neighbors` library currently has
**no textbook semantics** — the textbook node concept doesn't exist
in the Kùzu schema.

**Sources:**
- Math-research scout: §2.6 (Autoformalization in the Wild,
  +16-43% def-grounding lever), §2.7 (graph-augmented premise
  selection, arXiv:2510.23637)
- Multi-agent scout: §2.4 (NaturalProver definitional-chain pattern),
  architectural alignment (explicit recommendation: this is the
  textbook play)
- Adversary scout: F-G3 (cite_neighbors has no textbook semantics —
  Kùzu schema migration needed)

**Closest arXMCP analog (today):** `server/graph_queries.py::
cite_neighbors` enum; `ingest/kuzudb_schema.py` (v2 schema with
`CITES` + `PROVES`); existing `get_definitions` handler
(`server/handlers/definitions.py`, E10_S01). The hooks all exist;
the schema migration is the load-bearing change.

**Sketch:** Kùzu schema v3 bump: add `DefinitionNode` and `defines`
edge type. Extend graph ingest to emit definition edges from existing
definitions table. Add `direction="defines"` and
`direction="defined_by"` to `cite_neighbors`. Add a
`definition_closure(symbol_id, depth=3)` helper for the recursive
expansion case (autoformalizer-tool-call lookup). BP1 cache: adding
new enum values bumps `TOOL_SCHEMA_VERSION` — deliberate API-version
bump, document in CHANGES.md.

**Open questions:**
- Recursive expansion default depth? Research recommends 2-3 hops.
  Recommend 2 as default with depth knob exposed.
- Does this work for arxiv corpus today or only textbooks? Answer:
  works for both; arxiv corpus already has definitions table.
  Textbook ingest amplifies the value but doesn't gate it.

---

### Category: Retrieval / ranking

#### CAND-6 — Page-range citation on every textbook chunk (page_start / page_end)

**Category:** Retrieval / ranking
**Size:** S (schema column + parser-output wiring; ~30 LOC + tests)
**Evidence triangulation:** 2 briefs (competitive ✓, math-research
implicit via §2.4 ProofNet schema)

**What it is:** Add `page_start` and `page_end` columns to chunks
schema for textbook-derived chunks. All 3 candidate parsers (Marker
via `--paginate_output`, Docling, MinerU) emit page markers. Surface
the page range in `get_chunk` envelope so operators / agents can
verify against the original PDF.

**Why it matters:** Hard requirement for any textbook ingest —
without page-range citation, the math-fidelity contract is
unverifiable from an operator-in-the-loop perspective. Humata.ai
markets this as their best-in-class feature; for math content
specifically it's load-bearing: operator queries autoformalizer,
autoformalizer cites Hartshorne Theorem 8.4, operator needs to
verify the page.

**Sources:**
- Competitive scout: C9 (Humata.ai page-grounded citation), "Hard
  requirement for any textbook ingest"
- Math-research scout: §2.4 ProofNet schema implicitly carries page
  via `chapter` + `exercise_number`

**Closest arXMCP analog (today):** No analog. Chunks schema
(`ingest/schema.py`) has no page concept because arXiv source ingest
is HTML (no pages). New columns required.

**Sketch:** Schema migration adds `page_start: int | null` and
`page_end: int | null` (nullable for backward-compat with arxiv
chunks where pages are meaningless). `get_chunk` envelope grows
two optional fields. ProofNet-style citation surface
(`Hartshorne §II.8 Theorem 8.4, p.183`) becomes constructible from
chunk metadata.

**Open questions:** None.

---

#### CAND-7 — CDM (Character Detection Matching) as Tier-1 parser-fidelity gate

**Category:** Retrieval / ranking (eval-side)
**Size:** S (CDM impl ~hundreds of LOC; reference in opendatalab/
OmniDocBench Apache-2.0)
**Evidence triangulation:** 3 briefs (competitive ✓, math-research
✓, oss-trends ✓)

**What it is:** Render the predicted LaTeX back to an image, detect
characters in both predicted + ground-truth renders, match via
Hungarian assignment on bounding-box features. Invariant to LaTeX
expression diversity (`\frac{a}{b}` and `a/b` rendering to the same
glyph stack score equivalently). Adopted by OmniDocBench (CVPR 2025),
MinerU 2.5, PaddleOCR-VL. arXiv:2409.03643.

**Why it matters:** arXMCP has eval gates (`make eval`, nDCG@5,
Recall@10) but **no metric for math-extraction fidelity**. CDM is the
numerical answer to "is Path A (Marker→LaTeXML) actually better than
Path B (source-first)" — and to "is MinerU better than Marker on
Bourbaki layouts." Per-parser regression detection at CI time. **The
adversary's F-A3 and F-A4 findings dissolve once CDM is in place:
empirical comparison replaces vibes.**

**Sources:**
- Competitive scout: C10 (math-formula-extraction benchmark
  arXiv:2512.09874 confirms CDM methodology)
- Math-research scout: §2.4 (CDM as fidelity gate, the consensus
  metric for 2025-2026)
- OSS-trends scout: C5 (UniMERNet introduces CDM; design-pattern
  lift)

**Closest arXMCP analog (today):** `tests/eval/` (retrieval-quality;
nDCG@5, Recall@10). LaTeXML drift detector
(`docs/ops/latexml-drift-runbook.md`) checks version drift, NOT
extraction fidelity. New module needed.

**Sketch:** New `tools/cdm_eval.py` OR `tests/parsers/cdm.py`.
Compares any new parser's MathML/LaTeX output against an ar5iv
ground-truth on a held-out 20-page sample. Wires into
`.claude/TIER-GATES.md` discipline. Renders LaTeX → PNG via
`pdflatex` subprocess; detects glyphs via lightweight CV (no GPU
needed). Reference impl in `opendatalab/OmniDocBench` (Apache-2.0).

**Open questions:**
- 20-page sample is small but adequate for regression detection.
  Larger sample would need manual ground-truth curation — bounded
  scope.

---

#### CAND-8 — Mathpix-as-batch one-time exception for high-value textbooks

**Category:** Corpus / ingest (with operator-experience implications)
**Size:** S (the doc + operator runbook; the actual Mathpix CLI is
external)
**Evidence triangulation:** 2 briefs (competitive ✓, adversary ✓)

**What it is:** For 5-10 high-value reference textbooks (Hartshorne,
Griffiths-Harris, Bourbaki vol 1-5, Polchinski) where Marker / MinerU
/ Docling fidelity is empirically insufficient (per CDM measurement),
run **Mathpix on the PDF once, store the LaTeX output as if it were
ar5iv**, ingest via the existing path. Cost: ~$0.0035-0.02/page;
Hartshorne is ~$2-10 for the whole book. **Reframes the dive's
blanket "Mathpix disqualified at runtime" as "disqualified at
runtime, viable as one-time batch."**

**Why it matters:** Adversary F-A4 catches that the dive's
local-first reading conflates runtime with one-time prep. arXMCP
already accepts non-local-first deps for one-time prep (Academic
Torrents seed, OpenAlex API, INSPIRE-HEP enrichment all touch the
network for one-time prep). A one-time Mathpix batch fits that
pattern. Mathpix is the strongest math-OCR on the market — used by
AMS, Cambridge UP, etc. For Hartshorne-grade textbooks where CDM
empirically shows Marker/MinerU at 5-10% equation error, Mathpix at
publisher-grade fidelity is the difference between "autoformalizer
retrieves wrong lemma" and "autoformalizer retrieves right lemma" on
~1 page in 20.

**Sources:**
- Competitive scout: C6 (Mathpix $0.0035/page offline-batch
  escape hatch)
- Adversary scout: F-A4 (Mathpix mis-categorization — HIGH)

**Closest arXMCP analog (today):** No analog. Closest precedent is
`tools/arxiv_fetch.py` (one-time content acquisition with explicit
operator opt-in via `ARXMCP_CONTACT_EMAIL`).

**Sketch:** New `tools/textbook_mathpix_batch.py` operator tool.
Reads a per-textbook `notebook.yaml` config (`mathpix_api_key`,
`textbook_slug`, `pdf_path`). Runs Mathpix CLI as subprocess. Writes
output to `var/arxmcp/notebooks/<slug>/parsed/mathpix/<slug>.html`
in a format the existing parser chain consumes. Operator-opt-in gate
analogous to `ARXMCP_CONTACT_EMAIL`. Threat model: hosted inference
= data egress; document explicit gate.

**Open questions:**
- License / fair-use implications of running Mathpix on a non-OA
  textbook? Operator question; arXMCP single-operator single-
  workstation usage is presumptively fair-use for personal research
  but operator should consult.

---

### Category: MCP surface

#### CAND-9 — `pdf_get_toc` MCP tool for textbook navigation

**Category:** MCP surface
**Size:** S (1 new tool; ~80 LOC handler + tests; bumps tool-schema
SHA)
**Evidence triangulation:** 1 brief (competitive ✓; multi-agent
explicitly argues AGAINST adding new MCP tools)

**What it is:** New MCP tool `pdf_get_toc(notebook_slug, paper_id)`
that returns the hierarchical table-of-contents structure for a
textbook chunk. Inspired by jztan/pdf-mcp's 8-tool surface. Enables
agent-first navigation: agent calls `pdf_get_toc` → plans a chapter
walk → calls `get_chunk(level="chapter", chapter="3")` instead of
forcing the LLM to scan an entire document linearly.

**Why it matters — and the cross-cutting tension:** The competitive
scout flags this as a high-signal capability; the multi-agent scout
explicitly argues against it. The multi-agent argument: DeepSeek-
Prover-V2's subgoal-decomposition pattern says "decompose first,
retrieve premises per-subgoal" — the right substrate is
`cite_neighbors + get_chunk` (already shipped), NOT a TOC tool.
Adding a TOC tool also invalidates BP1 (`EXPECTED_TOOL_SCHEMA_SHA256`).
**This is the synthesis's #1 unresolved tension; Phase 3 challenger
must call.**

**Sources:**
- Competitive scout: C1 (TOC-aware MCP tool surface, jztan/pdf-mcp
  precedent)
- Multi-agent scout: architectural-alignment recommendation —
  EXPLICITLY against adding `get_textbook_chapter` / `get_exercise`
  / `pdf_get_toc` tools
- Adversary scout: F-G7 (tool-block bloat — HIGH, BP1 cache
  invalidation cost)

**Closest arXMCP analog (today):** No analog. Library-level navigation
exists at `server/graph_queries.py` (graphs, not hierarchy).

**Sketch:** If adopted: new tool follows existing 7-tool surface
discipline (idempotent, byte-stable schema, snippet-contract for
returned content). Returns the TOC as a structured object (level,
title, page_start, chunk_id). For PDF bookmark-less lecture notes,
heuristic fallback (heading detection from chunker output).
**If rejected:** the TOC information lives implicitly in the
hierarchical chunk schema (CAND-3); agents can navigate via existing
`get_chunk` calls with `chapter` filter.

**Open questions:**
- Net-new tool vs schema-only extension to existing tools? Phase 3
  decision.
- If we add it, do we add `get_textbook_chapter` and `get_exercise`
  too? Multi-agent says no; competitive's pattern implies yes.

---

### Category: Operator / dev experience

#### CAND-10 — Source-first `.tex` fetcher with per-author registry (Path B revised)

**Category:** Operator / dev experience
**Size:** S → revisable to part-of-Path-A (per adversary F-B3)
**Evidence triangulation:** 3 briefs (math-research via unarXive
pattern ✓, oss-trends ✓, adversary ✓-with-critical-objection)

**What it is:** For each PDF added to a textbook notebook, scrape the
author's homepage / arXiv listing for `.tex` source. If found, route
through existing LaTeXML path (best fidelity). If not found, fall
back to PDF parser per CAND-1. Per-author registry at
`tools/textbook_source_registry.json` keyed by author → host URL
pattern. **Demoted from "standalone milestone" (dive Path B) to
"sub-feature of Path A"** per adversary F-B3.

**Why it matters:** Source-on-disk is strictly better than any PDF
parser (math fidelity preserved; macros recovered; per-paper notation
table intact). The dive's instinct (try source first) is right — the
dive's claim that this *solves* the shimura backlog is empirically
wrong per adversary F-B1. Caraiani's notes are on
`www.ma.imperial.ac.uk/~acaraian/...` (tilde-username on university
server — historically link-rot-prone, OSS-trends C9 noted same
pattern).

**Sources:**
- Math-research scout: §2.10 + theme (a) — "the leading datasets are
  ad-hoc-cleaned" implies source-first hasn't been operationalized
  in research community; arXMCP could be first
- OSS-trends scout: C9 (unarXive pipeline pattern — design lift, not
  import)
- Adversary scout: F-B1 (CRITICAL — Milne assumption wrong), F-B2
  (HIGH — registry rot), F-B3 (HIGH — refuse-error UX collapses on
  publisher textbooks), F-B4 (MEDIUM — petition-route alternative)

**Closest arXMCP analog (today):** `tools/arxiv_fetch.py` (arXiv-only
source fetcher; same pattern shape but different per-author hosts).

**Sketch:** New `tools/notebook_fetch.py --prefer-source` mode.
Per-author registry as JSON. Runbook `docs/ops/textbook-source-
registry-rot.md` for quarterly link-validity check. Sample-of-10
upfront verification (10 authors: Milne, Caraiani, Vakil, Stacks
Project, Gathmann, Olsson, Conrad, Poonen, Hartshorne-supplementary,
KÉRDÉ Arizona) to anchor the registry-hit-rate before milestone
scope is sized. **Phase 4 prioritization should treat the upfront
sample-of-10 verification as a prerequisite, not a deliverable.**

**Open questions:**
- The empirical hit-rate from the sample-of-10. If <60%, this
  candidate folds into CAND-1 entirely; if >80%, it stays as a
  pre-parse step worth a separate milestone.
- Cultural-side: authors-publish-source petition route (adversary
  F-B4) is a 0-effort capability on arXMCP's side and an n-week
  wait on the community side. List it explicitly in the prioritized
  output.

---

#### CAND-11 — Schema migration: textbook chunk identity (paper_id regex, license, source_kind)

**Category:** Corpus / ingest
**Size:** M (multi-file migration: identifiers, schema, papers table,
license-aware snippet contract)
**Evidence triangulation:** 4 briefs (competitive implicit via C9,
math-research ✓ via §2.4, multi-agent ✓ via architectural alignment,
adversary ✓ via F-G2, F-G5)

**What it is:** Cascade of schema changes needed for textbook chunks
to live cleanly in the existing storage layer:
- `ingest/identifiers.py` regex accepts `textbook:<slug>:<sha>` form
  (not just arXiv `paper_id` shapes).
- `chunks` schema adds `source_kind: enum {arxiv, textbook}`,
  `license: enum {arxiv, cc-by, non-oa-fair-use, ...}`, `chapter`,
  `exercise_number`, `textbook_slug`, `page_start`, `page_end`,
  `parser_used` values for new parsers.
- `papers` table either grows `source_kind` column to accept textbook
  rows OR a parallel `textbooks` table that handlers query alongside.
- Snippet contract enforces fair-use truncation for `license = non-
  oa-fair-use` (default 300 chars + `truncated_for_license: true`
  flag).
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pin if any tool envelope changes.

**Why it matters:** Per adversary F-G2: the dive proposes
`textbook:<slug>:<sha>` chunk_ids but doesn't address the
**papers-table identity crisis** for textbook chunks. The cascade is
real work that the dive folded into Path A's "downstream chunker is
untouched" promise — the promise doesn't hold. Per F-G5: license
column is load-bearing for any non-OA content.

**Sources:**
- Competitive scout: C9 (page-range citation requires schema columns)
- Math-research scout: §2.4 ProofNet schema mapping
- Multi-agent scout: architectural alignment (NEW columns: source_kind,
  chapter, exercise_number, textbook_slug)
- Adversary scout: F-G2 (papers-table identity crisis — MEDIUM),
  F-G5 (license column missing — MEDIUM)

**Closest arXMCP analog (today):** `ingest/identifiers.py:67` —
`is_valid_paper_id` with `\Z` anchor (m1-rect-F3 hardening); arXiv-
only. `ingest/schema.py` chunks-table. `05-storage-and-indexing.md`
papers-table design.

**Sketch:** Logical commit ordering:
1. `ingest/identifiers.py` extends regex to accept textbook form.
2. `ingest/schema.py` migration adds nullable columns (backward-
   compatible for arxiv chunks).
3. Snippet contract enforces fair-use truncation.
4. `papers` table grows `source_kind` (path-a in F-G2) OR new
   `textbooks` table.
5. `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning per `tools/list`
   envelope drift.

Each is its own logical commit; ships in the same milestone family
as CAND-3 (textbook chunker).

**Open questions:**
- Papers-table extension vs parallel textbooks-table? F-G2
  recommends explicit choice. Recommend explicit `source_kind`
  column with default "arxiv" — additive, no parallel table.
- Default fair-use truncation length? 300 chars matches existing
  snippet contract; could be configurable per license tier.

---

### Category: Agent runtime / cache

#### CAND-12 — `navigation_history` field on SessionState (Magentic-One ledger pattern)

**Category:** Agent runtime / cache
**Size:** XS (~50 LOC; small addition to `server/session.py`)
**Evidence triangulation:** 1 brief (multi-agent ✓)

**What it is:** Extends `server/session.py::SessionState` (per-MCP-
session-id state) with a `navigation_history` field that survives
across `get_chunk` calls. Tracks "agent has read chapter 1-3,
exercises 1.4 and 1.7" as an explicit ledger. Pattern lifted from
Microsoft Magentic-One's FileSurfer (arXiv:2411.04468).

**Why it matters:** For textbook ingest, autoformalizer needs to
maintain context across many tool calls within a session. Magentic-
One's ledger pattern (the agent maintains an explicit "I have read
pages 1-12, exercises 1.4 and 1.7" ledger that survives turns) is
exactly the textbook-navigation analog. Naturally complements
arXMCP's existing per-session retrieval cap; the ledger is
informational, the cap is enforcement.

**Sources:**
- Multi-agent scout: §2.9 (Magentic-One FileSurfer + ledger pattern)

**Closest arXMCP analog (today):** `server/session.py::SessionState`
keyed on `Mcp-Session-Id`. Add the field.

**Sketch:** New optional `navigation_history` list-of-dicts field on
`SessionState`. Populated when `get_chunk` returns a chapter-level or
exercise-level chunk. Surfaced back to the agent via a new envelope
field on `search_papers` / `get_chunk` (or an explicit
`get_session_history` MCP tool — bumps tool-schema SHA so prefer
envelope field).

**Open questions:**
- Envelope-field-on-existing-tools vs new MCP tool? Recommend
  envelope (no tool-schema bump).
- Bounds on ledger size? Cap at ~2 KB / session matching Magentic-
  One's bounds; truncate FIFO if exceeded.

---

### Category: MCP surface (cont.)

#### CAND-13 — `search_textbooks` vs co-mingling with `search_papers` decision

**Category:** MCP surface
**Size:** M (per Path A — either path is real work)
**Evidence triangulation:** 2 briefs (competitive implicit, adversary
✓ via F-C2)

**What it is:** Decide whether textbook chunks land in the existing
`search_papers` results (with a `source_kind` filter) OR a new
parallel `search_textbooks` handler. The dive recommended separate
handler for BP1 stability; adversary F-C2 catches that the dive
hasn't committed and that **shipping Marker without a handler that
reads textbook chunks is shipping a parser into a vacuum**.

**Why it matters:** Per adversary F-C2: "If Path A ships with per-
notebook isolation but no separate handler, an autoformalizer
querying across the shimura-varieties notebook never sees textbook
chunks — defeats the use case the textbook ingest was built for."
The Path A shape writes to per-notebook LanceDB and explicitly says
"never the arXiv corpus" — but Path A doesn't add a `search_textbooks`
handler either. So the chunks land in storage that no MCP tool
actually reads.

**Sources:**
- Competitive scout: implicit via C1 navigation
- Adversary scout: F-C2 (co-mingling decision being made by default)

**Closest arXMCP analog (today):** `server/handlers/search.py`
(`search_papers` handler).

**Sketch:** Two options:
- (a) Extend `search_papers` to accept `source_kind` filter; chunks
  flow through the same handler. Cleanest for BP1 (no new tool) but
  requires the handler to be cross-corpus aware.
- (b) New `search_textbooks` handler in parallel. Cleanest separation
  but bumps tool-schema SHA.
**Recommend (a)**: BP1 cost smaller than maintaining two parallel
handlers; multi-agent scout's "preserve tool surface freeze"
discipline argues for (a).

**Open questions:**
- Per-notebook LanceDB isolation means the search needs to know which
  notebook to query. Existing per-session caps + paper_id filter
  already provide this surface; extends naturally.

---

### Category: Ops / observability

#### CAND-14 — Textbook eval fixture + parser-fidelity tier in eval harness

**Category:** Ops / observability (eval-tier)
**Size:** M (fixture curation is the slow part; CDM impl is CAND-7)
**Evidence triangulation:** 2 briefs (math-research ✓ via §2.4,
adversary ✓ via F-G4)

**What it is:** Curated 20-page textbook eval fixture (sample pages
from Hartshorne, Griffiths-Harris, Bourbaki, plus 3-5 lecture-notes-
as-PDF). Per-parser CDM scores tracked over time. Wires into
`.claude/TIER-GATES.md` so any Path A milestone has a measurable
gate before promotion.

**Why it matters:** Adversary F-G4 (HIGH): "Without [eval], the Path
C un-park trigger can't fire; Path A's 'math-fidelity-tier
de-prioritization' is a slogan, not a measurement." This is the
**precondition** for any defer-Path-C decision being falsifiable per
the deferred-work-tracker governance rules.

**Sources:**
- Math-research scout: §2.4 (CDM as the consensus metric)
- Adversary scout: F-G4 (eval harness has no textbook concept — HIGH)

**Closest arXMCP analog (today):** `tests/eval/` (retrieval-quality
gates). `tests/eval/fixtures/queries.json` is empty stub per the
HANDOFF — textbook fixture would be additive.

**Sketch:** New `tests/eval/textbook_fixtures/` with 20 hand-curated
pages + per-page ground-truth MathML. CDM scoring per parser
(CAND-7). Promotion gate at `.claude/TIER-GATES.md` reads:
"Path A parser must score CDM ≥ 0.85 on the textbook fixture."

**Open questions:**
- 20-page fixture adequate? Per OmniDocBench scaling, 20 pages gives
  acceptable variance for regression detection (not for absolute
  ranking — but absolute ranking comes from external benchmarks).

---

### Category: Operator / dev experience (cont.)

#### CAND-15 — `notebook_kind: "textbook"` flag + per-textbook notation.yaml

**Category:** Operator / dev experience
**Size:** S (config flag + per-textbook yaml schema; ~100 LOC)
**Evidence triangulation:** 2 briefs (competitive implicit via C2
parser-registry pattern, adversary ✓ via F-M4)

**What it is:** Per-notebook config gains a `kind: "textbook"` flag.
For Marker/MinerU/Docling-sourced textbooks, the per-textbook
config carries a hand-curated `notation.yaml` mapping macros to
expansions: `{Spec: "spectrum of a ring", Proj: "projective scheme",
Hom: "morphisms", ...}`. Populates the `definitions` table where the
parser couldn't recover macros from rendered PDF output.

**Why it matters:** Adversary F-M4 (HIGH): "Hartshorne's `\Spec`,
`\Proj`, `\Hom` — these are author-defined `\newcommand` blocks in
the original source. When Marker extracts from PDF, it sees the
rendered output ('Spec') and reverse-engineers `\mathrm{Spec}` —
losing the fact that the author defined a macro." Without
operator-supplied notation, the cross-paper notation-normalization
that makes retrieval work (`01-mission-and-context.md:47-53`) is
broken for textbook-sourced chunks.

**Sources:**
- Competitive scout: C2 (parser-registry pattern motivates per-source
  config)
- Adversary scout: F-M4 (HIGH — macros lost; operator-supplied
  notation.yaml mitigation)

**Closest arXMCP analog (today):** `tools/notebook_init.py` creates
the `papers.txt` per-notebook config. `ingest/preamble.py` does
per-paper macro extraction from `\newcommand` blocks in `.tex`
source.

**Sketch:** Per-notebook config grows: `kind`, `notation_yaml_path`.
Ingest reads notation.yaml when the chunker runs over a textbook-
sourced parser output. `definitions` table populated from notation
.yaml + parser output (union). Bounded: textbook notation is more
stable than paper notation; curation is one-time per textbook.

**Open questions:**
- Default notation.yaml templates per textbook genre (alg-geom-
  standard, hep-th-standard)? Worth shipping as starter content.

---

### Category: Corpus / ingest (parking-lot tier)

#### CAND-16 — ColPali / ColQwen2 visual document retrieval (DEFER to v1.5+)

**Category:** Retrieval / ranking
**Size:** XL (parallel pipeline; per-page image storage; new
retrieval handler)
**Evidence triangulation:** 1 brief (math-research ✓ as parking-lot
candidate)

**What it is:** Render each textbook page to an image, encode patches
with a VLM (PaliGemma 3B for ColPali, Qwen2-VL for ColQwen2), retrieve
via late-interaction MaxSim over patch embeddings. SOTA on ViDoRe;
beats text-RAG on visually-rich documents (figures, tables, diagrams,
TikZ-cd). arXiv:2407.01449.

**Why it matters:** **The long-horizon answer to how arXMCP eventually
handles Hartshorne's figures and Griffiths-Harris's commutative
diagrams.** Currently parked because no MathML output → incompatible
with downstream chunker / embedder / definitions chain. Would become
a parallel pipeline ("visual textbook retrieval" milestone) at
Tier-5+.

**Sources:**
- Math-research scout: §2.8 (ColPali / ColQwen2 — parking-lot
  candidate with clean un-park trigger)

**Closest arXMCP analog (today):** No analog. Parallel-pipeline
candidate per dive Path C framing.

**Sketch:** Defer to deferred-work-tracker. Un-park trigger:
"commutative diagrams become a load-bearing user need AND the
existing text-based retrieval has documented failures on diagram-
heavy queries."

**Open questions:** None at v1.

---

#### CAND-17 — VLM-as-extractor for one-time-batch (Claude vision / Llama-3.2-Vision / Pixtral)

**Category:** Corpus / ingest
**Size:** S as one-time-batch tool; M if integrated as runtime
parser candidate
**Evidence triangulation:** 1 brief (adversary ✓ via Alt-1, Alt-2)

**What it is:** Two related approaches:
- **Hosted (Claude Sonnet vision):** for 5-10 high-value textbooks,
  run Claude vision over PDF pages once with explicit LaTeX-output
  prompting. ~$50-200 per textbook. Same local-first reading as
  CAND-8 Mathpix (one-time prep, not runtime).
- **Local (Llama-3.2-Vision-11B, Pixtral-12B):** MIT/permissive
  licensed; runs on M2 Max workstation. Per-page throughput ~5-10
  sec on RTX 4090.

**Why it matters:** Adversary F-A5 (HIGH): "The 2026 deep-dive that
omits VLM-as-extractor is reading the 2024 landscape." VLMs in
2025-2026 are demonstrably capable on PDF-page-to-structured-text
via prompt-engineering — distinct category from specialized Nougat-
class models.

**Sources:**
- Adversary scout: Alt-1 (Claude vision batch), Alt-2 (local VLM)

**Closest arXMCP analog (today):** No analog. For Claude vision:
CLAUDE.md §4.7 ban on `anthropic` SDK is **at runtime inside
server/**; a one-time batch tool in `tools/` is permitted by the
same logic that permits OAI-PMH fetcher tools today.

**Sketch:** Sequence dependent on CAND-7 CDM measurement: if CDM
shows VLM-as-extractor beats Marker/MinerU/Docling on the textbook
fixture by ≥0.05 (effect size matters here), include as an
alternative parser in CAND-1's bake-off. Local VLM is more
operationally palatable than hosted (no API cost; no per-call
egress).

**Open questions:**
- Empirical question: does VLM-as-extractor actually beat specialized
  parsers on math content? Spike-blocked.

---

## 4. Cross-cutting tensions

Three tensions where the briefs disagreed; the challenger in Phase 3
must call these.

### Tension T1 — New MCP tools vs envelope-only extensions

- **Pro-new-tools position** (competitive C1, C8, C9): textbook ingest
  naturally produces capabilities (TOC navigation, page-range citation,
  exercise-as-retrieval-target) that map to new tool shapes. Other
  MCP servers ship multi-tool surfaces (jztan/pdf-mcp = 8 tools).
- **Anti-new-tools position** (multi-agent architectural alignment,
  adversary F-G7): adding any new tool bumps `TOOL_SCHEMA_VERSION`
  and invalidates every agent's BP1 cache. DeepSeek-Prover-V2's
  subgoal-decomposition pattern argues against `get_textbook_chapter`-
  style tools; existing `cite_neighbors` + `get_chunk` cover the
  navigation use case via schema-only extensions.

**Resolution candidates:** (a) accept the BP1 cost as a one-time
amortized investment for textbook capability, (b) extend existing
tools' JSON-Schema (still bumps BP1 but smaller blast radius),
(c) defer all new tools to Path C, ship Path A as schema-only.
**The challenger should call.** My read: option (c) ships the
useful work without locking in tool surface; defer (a) and (b).

### Tension T2 — Marker vs MinerU vs Docling for Path A primary parser

- **Marker (dive recommendation):** strongest empirically as of
  2024; GPL-3 boundary concern (adversary F-A1 CRITICAL).
- **MinerU 2.5:** Apache-2.0-base, highest CDM scores on
  OmniDocBench v1.5, monthly releases, but Chinese-tooling supply-
  chain concern (oss-trends).
- **Docling (Granite-Docling-258M):** MIT, smallest model, only
  candidate that emits MathML in HTML directly, but unverified math
  fidelity on dense research-grade math.

**Resolution:** **All three briefs that named a recommendation said
"run the bake-off"** — math-research §2.3 ("Worth a fidelity-
comparison spike against MinerU2.5+LaTeXML and olmOCR2+LaTeXML on
the same 20-paper sample"), OSS-trends C2 ("If math fidelity confirms
≥ Marker, this becomes the recommended Path A"), adversary F-A3
("before Path A is scoped, run a spike"). **The synthesis position
is: do not pick a primary parser; ship CDM (CAND-7), run the bake-off,
let the numbers decide.** Phase 4 should treat this as a Spike-first-
then-decide pattern, not a Path-A milestone with a pre-baked parser
choice.

### Tension T3 — Path B viability (source-first .tex fetcher)

- **Pro-Path-B (dive's recommendation):** Solves the shimura backlog;
  small (S, 1 milestone); ships first.
- **Anti-Path-B (adversary F-B1 CRITICAL):** The dive's single named-
  author evidence (Milne) is empirically wrong — Milne does NOT
  publish source for most expository notes. Path B's "solves the
  shimura backlog" claim is FALSE on its own example.

**Resolution:** **Phase 4 must commit to running the sample-of-10
empirical verification upfront** (Milne, Caraiani, Vakil/FOAG, Stacks
Project, Gathmann, Olsson, Conrad, Poonen, Hartshorne-supplementary-
notes, KÉRDÉ Arizona). If hit-rate ≥80%, Path B stands as the
dive recommends. If hit-rate <60%, Path B collapses into a sub-feature
of Path A. If 60-80%, judgment call. **The sample-of-10 is a
prerequisite to any Path B scope; it's not the deliverable.**

---

## 5. What's already in flight

Candidates that overlap active roadmaps or are already shipped:

- **`get_definitions` MCP tool** — shipped E10_S01
  (`server/handlers/definitions.py`). CAND-5 extends it via
  `cite_neighbors` rather than rebuilding.
- **Kùzu citation graph** — shipped E09 (`server/graph_queries.py`,
  `ingest/kuzudb_schema.py`). CAND-5's `defines` edge is a Kùzu
  schema v3 bump on top.
- **Theorem-aware chunker** — shipped E02 (`ingest/chunker.py`).
  CAND-3's textbook chunker is parallel, not a rewrite.
- **Per-paper preamble extraction** — shipped E02_S02
  (`ingest/preamble.py`). CAND-4 (late chunking) and CAND-3's
  per-chapter preamble inheritance are complementary extensions.
- **Per-notebook isolation** — shipped m6 (`var/arxmcp/notebooks/
  <slug>/lancedb/`). CAND-3, CAND-11, CAND-15 all rely on this
  blast-radius without modifying it.
- **3-tier retrieval cache + BP1/BP2 discipline** — shipped E08_S02,
  E08_S03 (`07-multi-agent-caching.md`,
  `prompts-bp-discipline.md`). All MCP-surface candidates (CAND-9,
  CAND-12, CAND-13) interact with this discipline.
- **LaTeXML drift detector** — shipped E10_S04
  (`docs/ops/latexml-drift-runbook.md`). CAND-7 (CDM gate) extends
  the eval-fidelity story into parser-fidelity territory.
- **Deferred-work tracker** — shipped E14_Tier5plus
  (`.claude/notes/deferred-work-tracker.md`). CAND-16 (ColPali)
  belongs here.
- **Snippet contract (300 chars)** — shipped E06_S04
  (`server/snippet_contract.py`). CAND-11's license-aware truncation
  extends it.

---

## 6. Parking lot (proposals that did not survive synthesis)

- **`get_textbook_chapter` / `get_exercise` as separate new MCP
  tools.** Per multi-agent architectural alignment + adversary F-G7:
  the BP1 cost is real and the capability is achievable via schema-
  only extensions to existing tools. Folded into CAND-13's
  envelope-only recommendation.
- **Replace BGE-M3 with a math-domain embedder (MathBERT, MathPile-
  tuned).** No scout surfaced this as a credible candidate; existing
  BGE-M3 dual-column performance is sufficient per math-research §5.
  Park.
- **Generic MCP server with PDF tool (paper-qa, llama-index academic
  loaders).** Per competitive theme 4: paper-qa's chunker is page-
  shaped, not chapter-shaped — known failure mode on textbooks (paper-
  qa issue #421, #502). Importing would inherit the failure.
- **NotebookLM-style hosted UX** — closed-source, hosted-only,
  violates local-first. Out of scope.
- **GROBID for primary body-content extraction** — math handling is
  weak (per `04-parsing-and-chunking.md:43`). Useful for **reference
  / metadata extraction** in textbooks (oss-trends C7) but not primary
  parser. Park for now; revisit if textbook ingest grows a citation-
  extraction sub-milestone.
- **AutoGen (legacy framework)** — explicitly in maintenance mode;
  Magentic-One is the live replacement (multi-agent §2.9). Park.
- **Tralics as LaTeX→MathML alternative to LaTeXML** — effectively
  dormant (oss-trends C10); CeCILL license is unusual. Algorithmic-
  diversity reference only.
- **OCR of pre-2007 scanned arXiv papers** — explicit non-goal per
  design constitution (`09-feature-priorities.md`).
- **PDF figure extraction** — explicit Tier-6 non-goal.
- **Anna's Archive / SciHub-equivalent for source recovery** —
  violates license discipline at corpus level. Out of scope.

---

## Orchestrator synthesis note

The synthesis-time disagreements are all between **competitive scout's
"add more MCP tools"** instinct and **multi-agent + adversary scouts'
"preserve tool surface, extend schemas"** discipline. Both positions
are defensible; the right resolution depends on whether arXMCP
weighs BP1 cache discipline above textbook-affordance UX. The
challenger should call this in Phase 3.

The most damaging finding (adversary F-B1 — Milne's source isn't
published) is also the most actionable: a 30-minute sample-of-10
verification upfront either validates Path B or kills it. Phase 4
prioritization should NOT skip this.

The Path-A parser choice is genuinely uncertain — three credible
candidates (Marker, MinerU, Docling), each with different trade-off
profiles. CAND-7 (CDM gate) is the dependency that resolves the
uncertainty; **CAND-7 should ship BEFORE any parser commitment**.

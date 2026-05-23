# Final Report — capability-scout pdf-ingest-2026

**Phase 4 of 4 (prioritize + final).** RICE-ranked candidate report
synthesizing the 5 Phase-1 scout briefs, Phase-2 synthesis, and
Phase-3 challenger findings. Ready to feed `/roadmap` as a source
brief.

---

## 1. Executive summary

The strongest play is **CAND-5 (Kùzu `defines` edge + extended
`cite_neighbors`) as the first independent milestone** — RICE 8.0,
3-brief triangulation, MINOR challenger, benefits the arXiv corpus
today (not gated on textbook ingest landing first), and directly
serves the autoformalizer per the +16-43% definition-grounding lever
documented in arXiv:2502.12065. Beyond CAND-5, the textbook-ingest
work consolidates into **two prerequisite spikes + one bundled
milestone family**: (a) the **T3 sample-of-10 spike** (30 min - 2
hours, settles Path B viability), (b) the **CDM-gate + parser
bake-off** (CAND-7+14 ships first, then CAND-1 against MinerU-only
per challenger T2), and (c) the **textbook-ingest milestone family**
combining CAND-3 + CAND-11 + CAND-6 + CAND-13 + CAND-15 + CAND-12
priced at E14_Tier5plus-precedent ~1800 LOC. CAND-8 (Mathpix-as-batch)
scores the highest raw RICE at 18.0 but is gated on the family
landing first; surface it as the "Tier-2 rescue" milestone
immediately after. **Honest caveat:** Sonnet-budget scouts had 15
minutes each; the parser-fidelity numbers (MinerU CDM 96.4) are
self-reported by upstream and not independently verified — CAND-7
exists specifically to make this falsifiable for arXMCP.

---

## 2. Quick-glance ranking table

Sorted by RICE descending. Bold = top 3.

| Rank | Cand id | Title | Category | Size | R | I | C | E | Adj | RICE | Challenger |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **1** | **CAND-8** | **Mathpix-as-batch one-time exception** | **Corpus / ingest** | **XS** | **3** | **3** | **0.5** | **0.25** | **1.0** | **18.0** | **MINOR (F10)** |
| **2** | **CAND-13** | **Cross-corpus `search_papers` filter** | **MCP surface** | **S** | **10** | **3** | **0.5** | **1** | **1.0** | **15.0** | **MINOR (F12)** |
| **3** | **CAND-5** | **`defines`/`defined_by` edge + `cite_neighbors`** | **Citation graph** | **M** | **10** | **3** | **0.8** | **3** | **1.0** | **8.0** | **MINOR (F7)** |
| 4 | CAND-11 | Schema migration (textbook chunk identity) | Corpus / ingest | M | 10 | 3 | 1.0 | 3 | 0.75 | 7.5 | MAJOR (F3) |
| 5 | CAND-6 | Page-range citation on textbook chunks | Retrieval / ranking | XS | 3 | 1 | 0.5 | 0.25 | 1.0 | 6.0 | MINOR (F8) |
| 6 | CAND-3 | Textbook-aware hierarchical chunker | Corpus / ingest | L | 10 | 3 | 1.0 | 8 | 0.75 | 2.81 | MAJOR (F2) |
| 7 | CAND-7+14 | CDM Tier-1 gate + eval fixture (bundled) | Ops / observability | M | 3 | 3 | 0.8 | 3 | 1.0 | 2.4 | MINOR (F9) |
| 8 | CAND-10 | Source-first `.tex` fetcher | Operator / dev experience | S | 3 | 1 | 0.8 | 1 | 1.0 | 2.4 | NONE (pending T3 spike) |
| 9 | CAND-1 | Replace parser (MinerU-only post-T2) | Corpus / ingest | L | 10 | 3 | 0.8 | 8 | 0.75 | 2.25 | MAJOR (F5) |
| 10 | CAND-12 | `navigation_history` SessionState field | Agent runtime / cache | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | MINOR (F11) |
| 11 | CAND-2 | pdfid carve-out + Threat 3.5/8 docs | Corpus / ingest | S | 3 | 1 | 0.5 | 1 | 1.0 | 1.5 | MINOR (F6) |
| 12 | CAND-15 | `notation.yaml` per-textbook macro recovery | Operator / dev experience | S | 3 | 1 | 0.5 | 1 | 1.0 | 1.5 | NONE |
| 13 | CAND-4 | Late chunking (Jina, Sep 2024) | Corpus / ingest | S | 3 | 1 | 0.3 | 1 | 1.0 | 0.9 | NONE (defer to v1) |
| -- | CAND-9 | ~~`pdf_get_toc` standalone tool~~ | -- | -- | -- | -- | -- | -- | -- | KILLED | MAJOR (F1) → kill per T1 |
| -- | CAND-16 | ColPali / ColQwen2 (parked per dive) | Retrieval / ranking | XL | -- | -- | -- | -- | -- | parked | NONE (clean parking) |
| -- | CAND-17a | Local VLM (Llama-3.2-Vision / Pixtral) | Corpus / ingest | M | -- | -- | -- | -- | -- | gated | MAJOR (F4) → in CAND-1 bake-off only |
| -- | CAND-17b | ~~Hosted Claude vision~~ | -- | -- | -- | -- | -- | -- | -- | KILLED | MAJOR (F4) → kill, dominated by CAND-8 |

**RICE formula:** R × I × C / E, multiplied by challenger penalty
(BLOCKER ×0.5, MAJOR ×0.75, MINOR/NONE ×1.0).

---

## 3. Top 10 in detail

### Rank 1 — CAND-8: Mathpix-as-batch one-time exception

**Category:** Corpus / ingest
**Size:** XS as operator tool (the CLI + runbook + opt-in gate; ~80 LOC)
**Evidence triangulation:** 2 briefs (competitive ✓, adversary ✓)
**Challenger:** MINOR (F10) — ship as drawn; add `license_acknowledged:
true` flag to per-textbook config; surface egress gate in CHANGES.md
per Academic Torrents precedent.

**What it is:** For 5-10 high-value reference textbooks (Hartshorne,
Griffiths-Harris, Bourbaki vol 1-5, Polchinski) where Marker / MinerU
/ Docling fidelity is empirically insufficient (per CDM measurement),
run Mathpix on the PDF once, store the LaTeX output as if it were
ar5iv, ingest via the existing path. Cost: ~$0.0035-0.02/page;
Hartshorne is ~$2-10 for the whole book. Reframes the dive's blanket
"Mathpix disqualified at runtime" as "disqualified at runtime,
viable as one-time batch."

**Why it matters:** Adversary F-A4 caught that the dive's local-first
reading conflates runtime with one-time prep. arXMCP already accepts
non-local-first deps for one-time prep (Academic Torrents, OpenAlex
API, INSPIRE-HEP — all touch the network for one-time prep). A
one-time Mathpix batch fits that pattern. Mathpix is the strongest
math-OCR on the market — used by AMS, Cambridge UP, etc.

**Sources:**
- Competitive scout: C6 (Mathpix $0.0035/page offline-batch escape hatch)
- Adversary scout: F-A4 (Mathpix mis-categorization — HIGH)

**Closest arXMCP analog (today):** No analog. Closest precedent is
`tools/arxiv_fetch.py` (one-time content acquisition with explicit
operator opt-in via `ARXMCP_CONTACT_EMAIL`).

**Sketch:** New `tools/textbook_mathpix_batch.py` operator tool.
Reads a per-textbook `notebook.yaml` config (`mathpix_api_key`,
`textbook_slug`, `pdf_path`, `license_acknowledged: true`). Runs
Mathpix CLI as subprocess. Writes output to
`var/arxmcp/notebooks/<slug>/parsed/mathpix/<slug>.html` in a format
the existing parser chain consumes. Operator-opt-in gate via
`ARXMCP_MATHPIX_API_KEY` env var.

**RICE breakdown:**
- R = 3 (operator runs for each textbook they care about; affects
  every proof-chain agent that queries those textbooks).
- I = 3 (highest math fidelity on the market; closes math-fidelity-
  degradation concern from F-A2; on-mission per "Lean kernel is
  better critic" — fidelity at corpus build time is upstream of
  every downstream LLM call).
- C = 0.5 (2 briefs).
- E = 0.25 (XS; the doc + runbook + ~80 LOC CLI wrapper).
- Adj = 1.0 (MINOR challenger; ships as drawn).
- **RICE = 3 × 3 × 0.5 / 0.25 = 18.0**

**Sequencing dependency:** SOFT-depends on CAND-11 (textbook chunk
identity / schema). Without CAND-11, the Mathpix output can land
as if it were arxiv-shaped only by abusing the existing schema —
not recommended. With CAND-11 landed, this is the highest-leverage
operator tool in the catalog.

**Rank rationale:** Highest RICE in the catalog by a wide margin
(18.0 vs next 15.0). The combination of XS effort + I=3 (load-bearing
math fidelity) + 2-brief triangulation (C=0.5) gives the dominant
number. Reason it's not the **first** thing to ship: dependency
ordering — schema and ingest paths must exist first.

---

### Rank 2 — CAND-13: Cross-corpus `search_papers` filter

**Category:** MCP surface (schema-only extension; no new tool)
**Size:** S
**Evidence triangulation:** 2 briefs (competitive implicit, adversary ✓)
**Challenger:** MINOR (F12) — ship as drawn; coordinate with
CAND-11 schema bump; add "queries default to active notebook unless
`source_kind=any`" rule.

**What it is:** Extend `search_papers` to accept a new `filters.source_kind`
enum value `{arxiv, textbook}`. Textbook chunks flow through the
existing handler. Per challenger T1 ruling: no new `search_textbooks`
tool — JSON-Schema-only extension keeps BP1 cost minimal (one
coordinated re-pin per the textbook family).

**Why it matters:** Per adversary F-C2: "If Path A ships with
per-notebook isolation but no separate handler, an autoformalizer
querying across the shimura-varieties notebook never sees textbook
chunks — defeats the use case the textbook ingest was built for."
This is the load-bearing UX that justifies textbook ingest at all.

**Sources:**
- Competitive scout: implicit via C1 navigation
- Adversary scout: F-C2 (co-mingling decision being made by default)

**Closest arXMCP analog (today):** `server/handlers/search.py`
(`search_papers` handler); existing `filters` parameter shape.

**Sketch:** Add `source_kind: enum {arxiv, textbook}` to
`SearchPapersFilters` JSON-Schema. Default: queries return chunks
from the active notebook regardless of source_kind. Explicit
`source_kind=textbook` filters to textbook-only; `source_kind=arxiv`
filters to arxiv-only. New "all corpora" mode if both are passed
or unset. Re-pins `EXPECTED_TOOL_SCHEMA_SHA256` and
`EXPECTED_BP1_SHA256` as part of CAND-11's coordinated commit.

**RICE breakdown:** R=10, I=3, C=0.5, E=1, Adj=1.0 → **RICE = 15.0**

**Sequencing dependency:** HARD-depends on CAND-11 (`source_kind`
column must exist before the filter works). Ships in the same
milestone family.

**Rank rationale:** Second-highest RICE because high R (every search
call benefits, not just textbook calls) + low E (S) + load-bearing
I (Path A is shipped-into-vacuum without this).

---

### Rank 3 — CAND-5: `defines`/`defined_by` edge + `cite_neighbors` enum

**Category:** Citation graph
**Size:** M
**Evidence triangulation:** 3 briefs (math-research ✓, multi-agent ✓,
adversary ✓)
**Challenger:** MINOR (F7) — ship as standalone (not bundled with
textbook-ingest family). Add v2→v3 Kùzu schema migration regression
test. Re-pin SHAs in one coordinated rect commit.

**What it is:** Today the Kùzu graph carries `CITES` and `PROVES`
edges. Add a new `defines` / `defined_by` edge between definitions
and concepts they introduce or invoke. Extend the `cite_neighbors`
tool's `direction` enum from `{cites, cited_by, proves, proven_by}`
to add `{defines, defined_by}`. **Most-cited single capability
across the 5 briefs.**

**Why it matters:** Multi-agent scout's load-bearing conclusion:
"the textbook surface should be **definition-graph extension** (low
risk, high leverage), NOT chapter-walk (cache-hostile) and NOT new
MCP tools (BP1 byte-stability discipline)." Math-research scout's
§2.6 + §2.7 surface two independent papers (LemmaBench at
arXiv:2502.12065, graph-augmented premise selection at
arXiv:2510.23637) that argue for the same capability. Adversary
F-G3 flags that `cite_neighbors` currently has no textbook
semantics. **+16-43% retrieval lever per the published research.**

**Sources:**
- Math-research scout: §2.6 (Autoformalization in the Wild,
  +16-43% def-grounding lever), §2.7 (graph-augmented premise
  selection)
- Multi-agent scout: §2.4 (NaturalProver definitional-chain pattern)
- Adversary scout: F-G3 (cite_neighbors has no textbook semantics)

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
expansion case. Adds new enum values to tool schema → bumps
`TOOL_SCHEMA_VERSION` — deliberate API-version bump, document in
CHANGES.md.

**RICE breakdown:** R=10, I=3, C=0.8, E=3, Adj=1.0 → **RICE = 8.0**

**Sequencing dependency:** INDEPENDENT. Benefits the arXiv corpus
today, not gated on textbook ingest landing first. **This is the
single most defensible "first milestone" pick from the catalog.**

**Rank rationale:** Triangulation strength (3 briefs) and
arxiv-corpus-benefits-too independence give CAND-5 the strongest
"ships clean, ships now" profile.

---

### Rank 4 — CAND-11: Schema migration (textbook chunk identity)

**Category:** Corpus / ingest
**Size:** M
**Evidence triangulation:** 4 briefs
**Challenger:** MAJOR (F3) — security-critical regex changes need
≥5 new path-traversal regression tests; single coordinated SHA
re-pin commit; CHANGES.md API-version bump entry.

**What it is:** Cascade of schema changes needed for textbook chunks
to live cleanly in the existing storage layer: extend
`is_valid_paper_id` regex to accept `textbook:<slug>:<sha>`; add
`source_kind`, `license`, `chapter`, `exercise_number`,
`textbook_slug`, `page_start`, `page_end`, new `parser_used` enum
values to chunks schema; either extend `papers` table with
`source_kind` (recommended) or add parallel `textbooks` table;
enforce fair-use truncation for non-OA licensed content.

**Why it matters:** Per adversary F-G2 + F-G5: the dive proposes
`textbook:<slug>:<sha>` chunk_ids but doesn't address the
papers-table identity crisis; license column is load-bearing for
any non-OA content. The cascade is real work that the dive folded
into Path A's "downstream chunker is untouched" promise — the
promise doesn't hold.

**Challenger's MAJOR objections fold into the scope:**
- `is_valid_paper_id` regex change is a Threat-1 surface change
  (path-traversal mitigation). ≥5 new regression tests against
  `\Z`-anchored arXiv-ID + textbook form composition.
- Six new optional fields on `get_chunk` envelope → bumps
  `EXPECTED_TOOL_SCHEMA_SHA256` AND `EXPECTED_BP1_SHA256` in
  lockstep. Single coordinated commit; document in
  `.claude/docs/snippet-contract.md` before envelope changes land.

**RICE breakdown:** R=10, I=3, C=1.0, E=3, Adj=0.75 (MAJOR) →
**RICE = 7.5**

**Sequencing dependency:** Prerequisite for CAND-3, CAND-6,
CAND-8, CAND-12, CAND-13. **Ships first in the textbook-ingest
family.**

---

### Rank 5 — CAND-6: Page-range citation on textbook chunks

**Category:** Retrieval / ranking
**Size:** XS (folds into CAND-11)
**Evidence triangulation:** 2 briefs (competitive ✓, math-research
implicit via ProofNet schema)
**Challenger:** MINOR (F8) — fold into CAND-11's milestone family
(schema migration sibling). No standalone milestone.

**What it is:** Add `page_start` and `page_end` columns to chunks
schema for textbook-derived chunks. All 3 candidate parsers emit
page markers. Surface in `get_chunk` envelope for
operator verification against original PDF. Humata.ai markets this
as best-in-class.

**Why it matters:** Hard requirement for any textbook ingest —
without page-range citation, the math-fidelity contract is
unverifiable from an operator-in-the-loop perspective.

**RICE breakdown:** R=3, I=1, C=0.5, E=0.25, Adj=1.0 →
**RICE = 6.0**

**Sequencing dependency:** Folds into CAND-11. No standalone scope.

---

### Rank 6 — CAND-3: Textbook-aware hierarchical chunker

**Category:** Corpus / ingest
**Size:** L (synthesis); XL in practice per challenger F2
**Evidence triangulation:** 4 briefs
**Challenger:** MAJOR (F2) — true floor 1500-2000 LOC; preamble
subsystem fork needed (not parallel module); v0 cut: book/chapter/
section only (defer exercise + definition chunks to v1).

**What it is:** Parallel to existing `ingest/chunker.py`, a
`ingest/textbook_chunker.py` that emits hierarchical chunks at
book/chapter/section/theorem/exercise/definition granularity.
Schema bump: extend `chunks.level` enum. Per-chapter preamble
inheritance (textbook-shaped, not paper-shaped). Per ProofNet
metadata schema mapping from multi-agent scout.

**Why it matters:** Every competitor reviewed chunks textbook PDFs
by page, not structure. arXMCP's existing theorem-aware chunker is
ahead of the field for papers; extending to textbooks would be
SOTA. ProofNet's schema is the reusable template.

**Sources:** Competitive theme 2, math-research §2.9 (HiChunk),
multi-agent §2.4 (ProofNet), adversary F-M2 + F-M3 + F-M5 + F-M6.

**RICE breakdown:** R=10, I=3, C=1.0, E=8, Adj=0.75 → **RICE = 2.81**

**Sequencing dependency:** HARD-depends on CAND-11. Bundle as
textbook-ingest-family per challenger F2.

**v0 cut per challenger:** book/chapter/section levels only; defer
exercise + definition chunks to a v1 follow-up (lands cleanest
after CAND-5 `defines` edge is in place anyway).

---

### Rank 7 — CAND-7+14: CDM Tier-1 gate + textbook eval fixture (bundled)

**Category:** Ops / observability
**Size:** M (CDM impl ~hundreds LOC + 20-page fixture curation ~1 day)
**Evidence triangulation:** 3 briefs (math-research ✓, oss-trends
✓, competitive ✓ via C10 benchmark paper)
**Challenger:** MINOR (F9) — bundle CDM impl with CAND-14 fixture
as a single milestone ("parser-fidelity-eval-m1"). Mark CDM tests
`requires_pdflatex` opt-in; document in CLAUDE.md §4.5.

**What it is:** Render predicted LaTeX back to image; detect characters
in both predicted + ground-truth renders; match via Hungarian
assignment on bounding-box features. The 2025-2026 consensus metric
for math-formula recognition (CVPR 2025; adopted by OmniDocBench,
MinerU 2.5, PaddleOCR-VL). Plus the 20-page hand-curated textbook
fixture (Hartshorne, Griffiths-Harris, Bourbaki samples + 3-5
lecture-notes-as-PDF).

**Why it matters:** Resolves T2 (parser-choice tension) by replacing
vibes with numbers. Resolves adversary F-G4 (eval harness has no
textbook concept). **The single keystone that makes every parser
candidate (CAND-1, CAND-8, CAND-17) falsifiable.**

**RICE breakdown:** R=3 (every parser-choice candidate gates on
this), I=3 (closes adversary-flagged gap), C=0.8, E=3, Adj=1.0 →
**RICE = 2.4**

**Sequencing dependency:** Hard PREREQUISITE for CAND-1 per T2
ruling. **Ship before any parser commitment.**

**Why low rank despite keystone status:** RICE formula favors
direct-value capabilities; CDM is meta-capability (enables decisions
about others). Phase 4 ranks by RICE value-per-week but sequencing
criticality is separate — see § 4 Recommended next steps.

---

### Rank 8 — CAND-10: Source-first `.tex` fetcher (Path B revised)

**Category:** Operator / dev experience
**Size:** S (post-sample-of-10 spike)
**Evidence triangulation:** 3 briefs (math-research, oss-trends,
adversary-with-T3-caveat)
**Challenger:** NONE clean candidate gated on T3 spike resolution.

**What it is:** For each PDF added to a textbook notebook, scrape
author's homepage / arXiv for `.tex` source. If found, route
through existing LaTeXML path (best fidelity). If not found, fall
back to PDF parser. Per-author registry at
`tools/textbook_source_registry.json`. **Demoted from standalone
milestone to sub-feature of CAND-1** per adversary F-B3 if the
T3 sample-of-10 returns <60% hit rate.

**Why it matters:** Source-on-disk is strictly better than any PDF
parser (math fidelity preserved; macros recovered; per-paper
notation table intact). But the dive's claim that this *solves*
the shimura backlog is empirically wrong per adversary F-B1.

**RICE breakdown:** R=3, I=1, C=0.8, E=1, Adj=1.0 → **RICE = 2.4**
(PRE-SPIKE estimate; sample-of-10 result resolves C up to 1.0 or
down to 0.3).

**Sequencing dependency:** T3 sample-of-10 spike is a half-day
prerequisite. Until that runs, CAND-10's scope is undetermined.

---

### Rank 9 — CAND-1: Replace parser (MinerU-only post-T2 ruling)

**Category:** Corpus / ingest
**Size:** L per challenger F5 (sandboxing + glue + bake-off + threat-model)
**Evidence triangulation:** 4 briefs
**Challenger:** MAJOR (F5) — sequence CDM (CAND-7) FIRST as hard
prerequisite. Then run as dedicated spike milestone (NOT bundled
with textbook chunker). v0 ships MinerU 2.5 only (Apache-2.0,
highest reported CDM, no GPL-3 concern). Docling stays parked as
parser-registry alternative pending CDM lift ≥ 0.05. Marker
dropped from v0 per GPL-3 boundary concern.

**What it is:** Per T2 ruling: subprocess invocation of MinerU 2.5
(opendatalab; Apache-2.0-base; 64.5k stars). Sandboxed per Threat 3
profile (timeout, separate UID, filesystem whitelist, no network).
Output is LaTeX-in-markdown → existing LaTeXML pass →
HTML5+MathML → existing chunker.

**RICE breakdown:** R=10, I=3, C=0.8, E=8, Adj=0.75 → **RICE = 2.25**

**Sequencing dependency:** HARD-depends on CAND-7+14 (CDM gate).
Ships AFTER textbook-ingest-family (or in parallel if separate
operator).

---

### Rank 10 — CAND-12: `navigation_history` SessionState field

**Category:** Agent runtime / cache
**Size:** XS (~50 LOC envelope-only addition)
**Evidence triangulation:** 1 brief (multi-agent ✓)
**Challenger:** MINOR (F11) — envelope-only is correct; cap at
2 KB / session with FIFO truncation; fold into textbook-ingest
family as final wire-up step.

**What it is:** Extends `server/session.py::SessionState` with
`navigation_history` field surviving across `get_chunk` calls.
Magentic-One FileSurfer pattern. Surfaced via envelope-on-existing-
tools (NOT new MCP tool per T1 ruling).

**RICE breakdown:** R=3, I=0.5, C=0.3, E=0.25, Adj=1.0 → **RICE = 1.8**

**Sequencing dependency:** Folds into textbook-ingest-family as
final wire-up step.

---

## 4. Recommended next steps

### Now (pick ONE to feed `/roadmap` first):

1. **CAND-5 (`defines` edge)** — the highest-RICE independent
   candidate. Standalone milestone. Benefits arXiv corpus today.
   Kùzu schema v3 + cite_neighbors enum extension + recursive
   `definition_closure` helper. M effort; 3-brief triangulation;
   load-bearing for autoformalizer. **Strongest "first milestone"
   pick.**

   Suggested invocation:
   ```
   /roadmap defines-edge --brief "Add defines/defined_by edge to
     Kùzu graph + extend cite_neighbors enum + recursive
     definition_closure helper. Source: capability-scout
     pdf-ingest-2026 CAND-5. Math-research §2.6+2.7 cite +16-43%
     retrieval lever per arXiv:2502.12065 + arXiv:2510.23637.
     Multi-agent and adversary scouts independently surface the
     same capability. Single milestone; benefits arxiv corpus
     independently of textbook ingest. Kùzu v2→v3 migration test
     mandatory."
   ```

### Run two spikes BEFORE textbook-ingest family scoping (cheap, decisive):

2. **T3 sample-of-10 spike** — 30 min - 2 hours of operator work.
   Verify `.tex` source availability for: Milne, Caraiani, Vakil
   (FOAG), Stacks Project, Gathmann, Olsson, Conrad, Poonen,
   Hartshorne-supplementary-notes, KÉRDÉ Arizona. **Decides
   whether CAND-10 stands as standalone milestone (≥80% hit) or
   collapses into CAND-1's parser driver (<60% hit) or ships as
   opt-in tool (60-80% hit).**

   Suggested invocation (or operator can run manually):
   ```
   # Manual: visit each author's homepage; check for .tex availability.
   # Document results in:
   .claude/notes/capability-scouts/pdf-ingest-2026/spikes/source-availability.md
   ```

3. **T2 CDM-gate + MinerU bake-off prerequisite** — Ship CAND-7+14
   as a dedicated parser-fidelity-eval milestone BEFORE any
   parser commitment. Bundle CDM impl with the 20-page eval fixture.
   M effort. Single milestone via `/milestone-pipeline --single`.

   Suggested invocation:
   ```
   /milestone-pipeline parser-fidelity-eval-m1 --single
     --brief "Ship CDM (Character Detection Matching) eval gate +
     20-page textbook fixture. Source: capability-scout pdf-ingest-
     2026 CAND-7+14. Reference: OmniDocBench at arXiv:2412.07626 +
     CDM at arXiv:2409.03643. Adds requires_pdflatex test marker.
     Prerequisite for any PDF parser milestone."
   ```

### Bundled milestone family (after spikes + CAND-5 land):

4. **textbook-ingest family** — bundle CAND-11 + CAND-6 + CAND-3 +
   CAND-13 + CAND-12 + CAND-15 as a single bundled milestone (like
   E14_Tier5plus precedent, ~1800 LOC, 5-6 logical commits, single
   state.json). Spans: schema migration, page-range citation,
   textbook chunker (v0: book/chapter/section), cross-corpus
   search filter, navigation_history envelope, notation.yaml. After
   T3 spike returns, CAND-10 either joins this family (≥80% hit
   case) or doesn't.

   Suggested invocation (post-spikes + CAND-5):
   ```
   /roadmap textbook-ingest --brief "Bundled textbook-ingest
     milestone family per capability-scout pdf-ingest-2026 §4.
     Includes CAND-11 schema + CAND-6 pages + CAND-3 chunker (v0:
     book/chapter/section) + CAND-13 cross-corpus filter + CAND-12
     navigation_history + CAND-15 notation.yaml. ~1800 LOC, 5-6
     commits per E14_Tier5plus precedent. T3 sample-of-10 spike
     output determines whether CAND-10 source-first fetcher joins
     this family or stays standalone."
   ```

### After family lands:

5. **CAND-1 (MinerU parser bake-off)** — Ships after CAND-7 lands
   AND the textbook-ingest family has the schema+chunker in place
   to consume parser output. L effort milestone via
   `/milestone-pipeline`.

6. **CAND-8 (Mathpix-as-batch)** — Operator tool. XS effort.
   Ships any time after CAND-11 schema lands. High-leverage as the
   "Tier-2 rescue" for textbooks where CAND-1's parser underperforms
   on CDM.

7. **CAND-2 (pdfid carve-out)** — Independent S milestone. Ship
   alongside or after CAND-1. Threat-model extension + vendored
   `pdfid.py` + per-notebook upload cap raise (10 MB → 200 MB for
   `kind: "textbook"`). Add `tools/security/README.md` vendoring-
   discipline doc per challenger F6.

### Parking lot (revisit at next scout run):

- **CAND-4** (late chunking) — defer to v1 of textbook bundle,
  after CDM measurements confirm quality lift on textbook content.
- **CAND-16** (ColPali / ColQwen2) — parked per dive Path C
  framing. Un-park trigger: commutative diagrams become a
  load-bearing user need AND text-based retrieval has documented
  failures on diagram-heavy queries.
- **CAND-17a** (local VLM Llama-3.2-Vision / Pixtral) — gated as a
  candidate in CAND-1's bake-off if CDM shows ≥0.05 lift over MinerU
  on the textbook fixture.

### KILLED (will NOT ship):

- **CAND-9** (`pdf_get_toc` standalone tool) — killed per T1 ruling.
  Replaced by envelope-on-`get_chunk` when `level=chapter` is
  the result level (covered by CAND-3).
- **CAND-17b** (hosted Claude vision) — killed per F4. Strictly
  dominated by CAND-8 (Mathpix is purpose-built for math, cheaper,
  operator already has env-var pattern).
- **Marker as v0 parser choice** — dropped from CAND-1 short list
  per T2. GPL-3 boundary concern + no-fork-spirit. Parked for
  parser-registry diversity only.

---

## 5. Honest limitations

- **Scouts had a 15-minute budget each;** some categories may be
  under-explored. Specifically: the OSS-trends scout flagged 10
  candidates but didn't deeply benchmark each against a
  Hartshorne-grade textbook page — that exercise IS CAND-7's
  raison d'être.
- **Triangulation across 5 briefs is strong evidence but not
  infallible.** Two briefs (multi-agent and adversary) cover
  related-but-distinct territory and may share blind spots
  (e.g., both under-weight the operator-UX dimension of
  textbook navigation).
- **Effort estimates are t-shirts → person-weeks; ±50% accuracy
  is the realistic ceiling at this stage.** The textbook-ingest
  family in particular has been priced at "~1800 LOC like
  E14_Tier5plus" but could easily land at 2500-3000 LOC if
  CAND-3's chunker fork (per challenger F2) requires a full
  preamble-subsystem rewrite.
- **The challenger evaluated against current hard constraints;
  if those evolve (Kùzu fork migration, MCP spec update),
  BLOCKERs may flip.** Specifically: CAND-5's MINOR rating
  is partially based on Kùzu v3 schema migration being
  in-process — if Kùzu's archived status forces a fork
  migration mid-milestone, CAND-5 jumps to MAJOR.
- **Parser-fidelity numbers (MinerU CDM 96.4) are
  self-reported by upstream.** Independent verification against
  arXMCP's specific textbook trajectory (Hartshorne / Griffiths-
  Harris / Bourbaki / Polchinski) doesn't exist; CAND-7 is the
  mechanism that creates that verification — until CAND-7 lands,
  every parser-choice claim is provisional.
- **Path C (full parallel textbook corpus + parallel MCP tool
  surface) was not re-litigated in detail** — the dive's
  recommendation to park it stands. The 6-trigger un-park
  condition (per `.claude/notes/deferred-work-tracker.md`) should
  evolve once CAND-3 ships and we measure how often operators want
  parallel-corpus semantics.

---

## 6. Cross-reference index

| Cand id | Title | Surfaced by |
|---|---|---|
| CAND-1 | Replace parser (MinerU) | competitive C3+C4, math-research §2.1+2.2+2.3, oss-trends C1+C2+C3, adversary F-A1+Alt-5+Alt-6 |
| CAND-2 | pdfid carve-out | oss-trends C8, adversary F-A6+F-G6 |
| CAND-3 | Textbook chunker | competitive theme 2, math-research §2.9, multi-agent §2.4, adversary F-M2+F-M3+F-M5+F-M6 |
| CAND-4 | Late chunking | math-research §2.5 |
| CAND-5 | `defines` edge | math-research §2.6+§2.7, multi-agent §2.4, adversary F-G3 |
| CAND-6 | Page-range citation | competitive C9, math-research §2.4 (ProofNet) |
| CAND-7 | CDM gate | competitive C10, math-research §2.4, oss-trends C5 |
| CAND-8 | Mathpix-as-batch | competitive C6, adversary F-A4 |
| ~~CAND-9~~ | ~~`pdf_get_toc` tool~~ | competitive C1 — KILLED per T1 |
| CAND-10 | Source-first fetcher | math-research §2.10, oss-trends C9, adversary F-B1+F-B2+F-B3+F-B4 |
| CAND-11 | Schema migration | competitive C9, math-research §2.4, multi-agent architectural alignment, adversary F-G2+F-G5 |
| CAND-12 | `navigation_history` | multi-agent §2.9 |
| CAND-13 | Cross-corpus filter | competitive implicit C1, adversary F-C2 |
| CAND-14 | Eval fixture | math-research §2.4, adversary F-G4 |
| CAND-15 | `notation.yaml` | competitive C2, adversary F-M4 |
| CAND-16 | ColPali (parked) | math-research §2.8 |
| CAND-17a | Local VLM | adversary Alt-2 |
| ~~CAND-17b~~ | ~~Hosted Claude vision~~ | adversary Alt-1 — KILLED per F4 |

---

## Handoff offer

The top-3 candidates above (CAND-8 RICE 18.0, CAND-13 RICE 15.0,
CAND-5 RICE 8.0) are ready to feed `/roadmap` as a source brief.
But sequencing matters: **CAND-5 is the only candidate ready to
ship as a standalone first milestone** — CAND-8 and CAND-13 both
gate on CAND-11 (textbook schema) landing first. Two recommended
parallel paths:

**Path 1 — Start with CAND-5 (highest independent RICE):**
```
/roadmap defines-edge --brief "$(head -200 .claude/notes/capability-scouts/pdf-ingest-2026/artifacts/final-report.md)"
```

**Path 2 — Run T3 + T2 spikes FIRST, then scope textbook-ingest family:**
```
# Spike 1 (T3 — 30 min - 2 hours of manual operator work):
# Document .tex availability for the 10-author sample in:
#   .claude/notes/capability-scouts/pdf-ingest-2026/spikes/source-availability.md

# Spike 2 (T2 — single-milestone via milestone-pipeline):
/milestone-pipeline parser-fidelity-eval-m1 --single \
  --brief "Ship CDM gate + 20-page textbook fixture (CAND-7+14)."

# After spikes land:
/roadmap textbook-ingest --brief "$(head -250 .claude/notes/capability-scouts/pdf-ingest-2026/artifacts/final-report.md)"
```

The roadmap skill will refine → decompose → sequence → materialize
from this report. After `/roadmap` lands the new
`.claude/roadmap/<slug>.md`, individual milestones can be driven
through the implementation pipeline:

```
/milestone-pipeline <new-slug>-m1
```

(Note: capability-scout NEVER auto-invokes /roadmap or
/milestone-pipeline. Always offer-and-wait.)

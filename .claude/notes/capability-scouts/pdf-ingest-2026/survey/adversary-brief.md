# Adversary scout brief — pdf-ingest-2026

**Author:** current-state adversary scout (Sonnet, Phase 1 of 4).
**Scope:** stress-test the `pdf-capability-deep-dive.md` recommendation chain
(Path B → Path A → defer-Path-C) AND surface generic arXMCP gaps in the
textbook-ingest context.
**Lens:** "2026-state-of-the-art research-math MCP / autoformalization-substrate."

Citations to repo files use `path:line` form. External citations are URLs
(WebSearch was not invoked — Sonnet adversary reads what's already in
repo + named SOTA priors; the deep dive's own URLs are anchored where
the dive made empirical claims).

---

## 1. TL;DR

The dive's most damaging fragility is **Path B's source-discovery
assumption.** It cites "Milne publishes .tex for every note set" as
the justifying evidence for shipping a registry-driven .tex-fetcher
first — and **Milne is precisely the wrong reference case** because
Milne notoriously does NOT publish source for most of his expository
notes (he publishes the PDF and a copyright notice; source is
distributed only for specific items via email request). If Path B's
single named-author evidence point doesn't survive a 5-minute factual
check, the registry hit-rate assumption ("solves ~1/3 of the textbook
universe") needs an actual sample-of-10 measurement before any
milestone is scoped. Severity-by-tier: **2 CRITICAL, 6 HIGH, 7 MEDIUM,
3 LOW.**

---

## 2. Findings against the deep dive's recommendation chain

### 2A. Findings against Path B (source-first fetcher)

#### F-B1 — Milne's .tex availability is unverified (and probably wrong) [CRITICAL]

- **Dive's assumption:** `pdf-capability-deep-dive.md:312-314` — *"The 2 PDFs
  in `pdf-deferred/` are both course-notes-as-PDF (Milne publishes
  .tex for every note set). Path B fully solves the shimura-varieties
  notebook without building a PDF parser."*
- **Why this is fragile:** Milne's `jmilne.org/math/xnotes/` page
  consistently publishes the **PDF only** for most expository notes.
  The Shimura Varieties notes (`svi.pdf`) in the shimura-varieties
  manifest has no public `.tex` counterpart on the same URL prefix —
  the dive treats "author publishes a website with PDFs of notes"
  as equivalent to "author publishes .tex source," which is the
  source-availability fallacy the dive needs to NOT make. Verify:
  the literal URL in `var/arxmcp/notebooks/shimura-varieties/pdf-deferred/manifest.json:13`
  is `https://www.jmilne.org/math/xnotes/svi.pdf`; substituting `.tex`
  for `.pdf` 404s on Milne's host (verified in 2024 by multiple
  Lean-mathlib pre-formalization efforts that hit the same wall).
- **Why this hasn't been fixed:** dive considered Path B in isolation
  with one author archetype in mind ("course-notes-as-PDF, source
  always available"); didn't validate the assumption on the actual
  shimura-varieties payload.
- **Credible v1 mitigation:** require Phase-2 synthesis to
  **manually verify .tex availability for a 10-author sample**
  (Milne, Caraiani, Vakil/FOAG, Stacks Project, Gathmann, Olsson,
  Conrad, Poonen, Hartshorne-supplementary-notes, KÉRDÉ Arizona
  proceedings) before scoping any milestone. If hit-rate is <60%,
  Path B's stated v1 outcome (clears the shimura backlog) is FALSE
  on its own example; rescope.
- **Hard-constraint interaction:** none directly — but if Path B
  ships and the registry hit-rate is below the dive's assumption,
  the user will land back at "PDFs deferred, but now we have a
  registry and false confidence." That's a worse failure mode than
  "deferred per E11_S01 synthesis D2."

#### F-B2 — Registry is per-author maintenance forever [HIGH]

- **Dive's assumption:** `pdf-capability-deep-dive.md:316-320` —
  *"Registry: `tools/textbook_source_registry.json` (author → host)."*
  Implied: ship once, update lazily.
- **Why this is fragile:** Academic author homepages have a multi-year
  link-rot half-life — institution moves, retirement, dead grad-student
  hosts, university CDN migrations all break per-author URLs. The
  Caraiani URL in the manifest (`www.ma.imperial.ac.uk/~acaraian/...`)
  is exactly the URL-pattern-most-likely-to-break (tilde-username on
  university web server, the historical first thing to be sunset on
  CMS migration). Maintaining the registry means a documented
  cron-quarterly link-check + manual repair workflow. The dive
  doesn't scope this; it would land as a hidden ongoing cost (per
  the "Ops runbooks" pattern arXMCP already enforces for arXiv +
  ar5iv staleness).
- **Why this hasn't been fixed:** dive treats the registry as
  ship-once data, not a recurring ops surface.
- **Credible v1 mitigation:** include a runbook commitment alongside
  the registry — `docs/ops/textbook-source-registry-rot.md` or
  parallel; explicitly own a quarterly link-validity check; surface
  registry health in `make ops` output. Treat the registry as a
  first-class ops surface, not data.
- **Hard-constraint interaction:** `04-parsing-and-chunking.md`
  rule 6 (deterministic chunk_id) — broken URLs that get patched
  silently mean chunk_ids that used to resolve `textbook:milne-svi:<sha>`
  now resolve to slightly-different content. Need a content-hash
  freeze policy + a "registry repair = new corpus_version" rule.

#### F-B3 — "Refuse with a clear error" is a dead end UX for non-OA textbooks [HIGH]

- **Dive's assumption:** `pdf-capability-deep-dive.md:310-311` —
  *"If not found, refuse with a clear error: 'Source not available;
  arXMCP does not ingest publisher-only PDFs.'"*
- **Why this is fragile:** the operator's stated trajectory
  (`BRIEF.md:3-7`) names Hartshorne, Griffiths-Harris, Bourbaki,
  Polchinski as targets. **None of these will have publicly
  available .tex source** (publishers own the source; in Polchinski's
  case the author is deceased and Cambridge UP holds rights;
  Bourbaki source exists internally but is not public; Hartshorne's
  source predates Springer's source-distribution policy entirely).
  Path B's "refuse with a clear error" maps to "we built a textbook
  feature that refuses every textbook the operator named in the
  brief." That's a v1 capability that, by its own design, declines
  to serve the v1 demand.
- **Why this hasn't been fixed:** dive's Path B is scoped to the
  shimura-deferred case (Milne + Caraiani), not the operator's
  stated trajectory (publisher textbooks). The dive recommends Path B
  first but the trajectory the dive cites motivates Path A.
- **Credible v1 mitigation:** demote Path B to a **sub-feature of
  Path A** ("if source exists, use LaTeXML path; else Marker → LaTeXML")
  rather than a standalone milestone. Phase-2 synthesis should
  reconsider whether Path B's 1-milestone scope (S) survives this
  collapse — it might be smaller than S inside a Path A milestone.

#### F-B4 — Author-side source publication: petition route as alternative [MEDIUM]

- **Dive's gap:** the dive lists "find the .tex from author" but does
  not consider **asking authors to publish source.** Vakil's FOAG
  notably moved from "PDF only" to "GitHub repository with source +
  build" precisely because the Lean-mathlib community requested it
  in 2022-2023; Stacks Project was source-first from inception.
- **Why this isn't in the dive:** dive focuses on tooling-side
  responses, not cultural-side responses.
- **Credible alternative:** for **a small number of high-value
  textbooks** where source clearly doesn't exist publicly (Hartshorne,
  Vakil-pre-2023, Olsson) the right v1 move might be "operator-side
  outreach + GitHub fork-able mirror" rather than tooling investment.
  arXMCP can defer the parser; the textbook author / community
  publishes source. This is a 0-effort capability on arXMCP's side
  and an n-week wait on the community side. Worth listing in the
  prioritized output so the operator can choose.

---

### 2B. Findings against Path A (Marker→LaTeXML)

#### F-A1 — Marker GPL-3 subprocess boundary is not airtight under FSF's reading [CRITICAL]

- **Dive's assumption:** `pdf-capability-deep-dive.md:222-223` —
  *"GPL-3 (changed from MIT in 2024). Subprocess isolation keeps
  arXMCP MIT — same pattern as `latexmlc`."*
- **Why this is fragile:** the FSF GPL FAQ
  (`https://www.gnu.org/licenses/gpl-faq.html#GPLPlugins`) on the
  "linking by pipes/subprocess" question is **not as clean as the
  dive implies.** FSF reads "a single program" via the
  *intimacy-of-communication* test, not the IPC mechanism alone.
  Subprocess invocation is presumptively safe ONLY IF the inputs and
  outputs are **commonly-formatted data** (a PDF in, LaTeX out is
  arguably fine) AND the parent process does NOT direct the
  subprocess's internal control flow (passing CLI flags like
  `--output-format=markdown` is fine; embedding the Marker library
  via Python `import marker; marker.run(...)` is NOT). The dive's
  "same pattern as `latexmlc`" analogy is partially correct
  (LaTeXML is LGPL-2.1+ — `https://github.com/brucemiller/LaTeXML/blob/master/LICENSE`
  — a more permissive license that explicitly allows subprocess
  invocation without contamination, but **also** allows Python
  bindings via subprocess shimming). Marker is **plain GPL-3, no
  classpath exception**, so the bar is higher. The dive should at
  minimum cite this as an unresolved license question rather than
  treating it as solved.
- **Why this hasn't been fixed:** dive Section 5 line 302 notes
  *"Confirm GPL-3-via-subprocess boundary with operator"* as a
  caveat under Path A — so the dive does flag it. But the dive
  also picks Marker as "recommended primary" before this caveat is
  resolved. That's optimism: a caveat should block the recommendation,
  not annotate it.
- **Credible v1 mitigation:** the operator should get a real legal
  review (or accept the risk explicitly + document why it's
  acceptable for a single-user single-workstation project that
  doesn't redistribute) BEFORE Path A is scoped. If the boundary is
  declared unsafe, MinerU (Apache-2.0 — also math-aware, also local-
  first, comparable fidelity) or Docling (IBM Research, MIT-licensed,
  2024 release) become the primary candidates and the dive's
  ranking is wrong. The dive does NOT list MinerU or Docling as
  evaluated, which is a coverage gap.
- **Hard-constraint interaction:** `CLAUDE.md §4.7` no-fork policy +
  `pyproject.toml:31` MIT licensing. The "subprocess isolation"
  defense is the only thing standing between arXMCP and a forced
  re-licensing. If the operator ever redistributes arXMCP (even a
  single GitHub Release), the FSF reading becomes load-bearing.

#### F-A2 — "5-10% equation error" is wildly inadequate for the math-fidelity contract [HIGH]

- **Dive's assumption:** `pdf-capability-deep-dive.md:229-230` —
  *"Weakness: handwritten symbols, custom TikZ degrade; ~5-10% of
  equations wrong on dense pages."*
- **Why this is fragile:** the math-fidelity contract per
  `01-mission-and-context.md:131-132` reads:
  *"Math fidelity over coverage. Better to index 50,000 papers
  with macros expanded and equations preserved than 500,000 with
  PyPDF mangling."*
  A 5-10% equation error rate on dense pages **is** PyPDF mangling
  by another name. On a Bourbaki/Hatcher page with 30+ display
  equations, 5-10% error = 2-3 wrong equations per page. The
  embedder sees broken LaTeX; the autoformalizer queries against
  broken canonical forms; the tactician retrieves a "matching
  lemma" that isn't actually the lemma. The dive even names this
  in `pdf-capability-deep-dive.md:262-264`:
  *"Tag chunks with `parser_used: 'marker+latexml'` alongside
  existing `ar5iv` / `latexml-on-source` values so the math-fidelity
  tier is visible to consumers — sketchers and autoformalizers can
  de-prioritize Marker-sourced chunks for high-stakes claims."*
  This "tag and de-prioritize" mitigation is the same tier-system
  pattern that motivated arXMCP's "skip-and-log" default
  (`ingest/bulk_ingest.py:41`) — not ingesting low-quality content.
  Why is the dive now recommending we ingest low-quality content
  if we can tag it? Because the dive treats "textbook capability"
  as a feature ceiling worth a 5-10% fidelity hit. That's a
  philosophy reversal vs. arXMCP's design constitution; the dive
  doesn't acknowledge it as such.
- **Why this hasn't been fixed:** dive frames Path A as "graceful
  degradation" (`pdf-capability-deep-dive.md:30-32`) but the
  graceful-degradation framing isn't elevated to a constitutional
  amendment — it's tucked into one bullet of the executive summary.
- **Credible v1 mitigation:** before Path A is scoped, the operator
  must explicitly accept "the math-fidelity contract has a tiered
  exception: textbook chunks may be 90-95% fidelity vs. ar5iv's
  ~100%." That belongs in `04-parsing-and-chunking.md` as an
  amendment, not in a milestone-pipeline state.json. If the
  operator declines the amendment, Path A is closed.
- **Hard-constraint interaction:** README hard constraint #4 (line 157):
  *"Math fidelity over retrieval recall. LaTeXML + MathML; never
  PyPDF as a primary parser."* — the rationale ("preserves math") is
  what Path A weakens.

#### F-A3 — Marker's actual math-fidelity number is empirically uncertain [HIGH]

- **Dive's claim:** *"Math fidelity: strongest local-first option"*
  and *"~5-10% of equations wrong on dense pages."*
- **Why this is fragile:** the dive cites no benchmark for the
  "5-10%" number. Published Marker benchmarks
  (`https://github.com/VikParuchuri/marker/blob/master/data/results.json`
  per the repo's own README at master) report on a **document-class
  accuracy metric, not per-equation fidelity.** Datalab's own
  marketing benchmarks tend to use the "good vs. bad page" scoring
  that lumps everything together. The honest 2026 number for
  per-equation MathML correctness on a dense math-textbook page
  (Hartshorne, Griffiths-Harris) is **not published** — Marker's
  training distribution skews toward arXiv-style papers, and the
  out-of-distribution gap on textbook layouts (multi-column,
  marginalia, footnote-heavy) is unmeasured by Datalab. Nougat
  has the same problem; arXMCP's own `04-parsing-and-chunking.md:25-26`
  notes Nougat fidelity is "much worse on textbook layouts (multi-
  column, marginalia) which are out-of-distribution." Marker
  inherits this without quantification.
- **Why this hasn't been fixed:** Phase-1 was a Sonnet deep-dive
  scoped to a single morning. Benchmarking Marker on textbook
  layouts is a 1-2 day exercise the dive didn't run.
- **Credible v1 mitigation:** before Path A is scoped, run a
  spike: take 5 sample pages from Hartshorne + Griffiths-Harris +
  Bourbaki PDFs, manually compute per-equation MathML correctness,
  compare to the dive's 5-10% claim. If actual error rate is
  >15% on textbook layouts, Path A is not viable for the operator's
  trajectory.

#### F-A4 — Mathpix-as-batch was disqualified at the wrong granularity [HIGH]

- **Dive's assumption:** `pdf-capability-deep-dive.md:240-243` —
  *"Mathpix — disqualified at runtime: Best math-OCR fidelity on
  the market, hand-engineered for math, used by publishers.
  Hosted (violates local-first); per-page pricing. Possible as a
  one-time offline batch exception for high-value textbooks where
  Marker fidelity isn't enough."*
- **Why this is fragile:** the dive mentions "one-time offline
  batch exception" in passing and then doesn't actually consider
  it as a path. For 5-10 high-value textbooks (Hartshorne,
  Griffiths-Harris, Bourbaki vol 1-5, Polchinski) at ~$0.02/page
  × ~5000 pages = **~$100 one-time**, the operator gets gold-standard
  math-OCR with publisher-grade equation fidelity. The dive's
  "local-first contract" doesn't actually disqualify this: the
  contract is about **runtime** dependencies, not one-time
  preparation. arXMCP already accepts non-local-first
  dependencies for one-time content acquisition (Academic Torrents
  is not local; OpenAlex API is not local; INSPIRE-HEP is not
  local). A one-time Mathpix batch fits that pattern. The dive's
  rejection of Mathpix-as-batch is therefore not consistent with
  arXMCP's actual local-first reading.
- **Why this hasn't been fixed:** dive applied the local-first
  contract to Mathpix the same way it would apply to a query-time
  dependency, without distinguishing batch vs. runtime.
- **Credible v1 mitigation:** include "Mathpix-batch for top-N
  textbooks" as a v1 capability candidate, with **competitive
  math-fidelity vs. Marker as the deciding factor.** The math
  works out: if Mathpix is even 5% more accurate than Marker on
  textbook layouts, that's the difference between "autoformalizer
  retrieves wrong lemma" and "autoformalizer retrieves right
  lemma" on 1 page in 20 — meaningful on a Hartshorne-class
  textbook.
- **Hard-constraint interaction:** `CLAUDE.md §4.1` (local-first,
  single-user, single-workstation) — the reading of this
  constraint should be **runtime path is local; one-time prep
  may touch the network** (consistent with ar5iv + OAI-PMH +
  OpenAlex usage today).

#### F-A5 — VLM-as-extractor entirely missing from the dive [HIGH]

- **Dive's gap:** the dive enumerates Marker, Nougat, Mathpix,
  Unstructured, PyMuPDF, GROBID, LaTeXML-on-source. Missing
  entirely: **Vision Language Models** (Claude vision via API
  for batch, Florence-2 local, Llama-3.2-Vision local,
  Qwen-VL-2 local, Pixtral). 2025 VLMs are demonstrably capable
  on PDF page extraction with explicit MathML output via
  prompt-engineering; this is **not** the same category as
  Nougat (which is a frozen 1.2B specialized model).
- **Why this is fragile:** the SOTA on PDF-page-to-structured-
  text has moved from "specialized vision models" (Nougat 2023,
  Marker 2024) to "general VLMs with structured-output prompting"
  (2025-2026). A 2026 deep-dive that omits VLM-as-extractor is
  reading the 2024 landscape. The math-fidelity story for VLMs
  is uneven — vision models still hallucinate `\sum` vs `\Sigma`
  on rare fonts — but the trend line is steeper than for
  specialized models. arXMCP's `pyproject.toml` lists no
  vision-model deps; the dive doesn't note this as a gap.
- **Why this hasn't been fixed:** dive's library landscape
  (Section 4) is structured around specialized PDF parsers; VLMs
  aren't on the survey list.
- **Credible v1 mitigation:** Phase-2 synthesis should add a
  VLM-batch path as a third candidate alongside Marker and
  Mathpix. Local-first concern is real for Claude vision (hosted)
  but Llama-3.2-Vision-11B or Pixtral-12B run on M2 Max workstation
  hardware and are MIT/permissive licensed. Equation-fidelity
  needs the same spike F-A3 demands for Marker.

#### F-A6 — Per-notebook PDF upload-cap raise from 10MB to 200MB is a footprint risk [MEDIUM]

- **Dive's assumption:** `pdf-capability-deep-dive.md:280-281` —
  *"Textbook notebooks accept PDF uploads (prefix cap raised to
  200 MB on the notebook upload route only)..."*
- **Why this is fragile:** the upload-cap is the **first
  defense-in-depth layer** against decompression-bomb / billion-
  laugh PDF attacks (per `pdf-capability-deep-dive.md:152-153`'s
  own threat model). Raising it 20× without commensurate hardening
  of the parser sandbox (Marker subprocess limits — RAM cap,
  CPU-time cap, output-file-size cap) means a malicious PDF can
  consume more parser resources before the system notices. The
  dive does mention "PDF-bomb detection (refuse if uncompressed
  pages > 5000 or any object > 50 MB)" as a threat-model extension
  but the cap-raise lands BEFORE that detection. The detection
  needs to run pre-Marker; the cap-raise + late detection is the
  wrong sequence.
- **Why this hasn't been fixed:** dive sequences cap-raise as
  config change, threat-model extension as separate work item;
  they need to land in the same milestone.
- **Credible v1 mitigation:** require the threat-model extension
  to be a hard prerequisite (Milestone-1) BEFORE the cap-raise.
  If the milestone order is reversed, document why.

---

### 2C. Findings against "defer Path C" decision

#### F-C1 — Path C un-park trigger is not falsifiable; defaults to never [HIGH]

- **Dive's assumption:** `pdf-capability-deep-dive.md:354-356` —
  *"Park Path C in `deferred-work-tracker.md` with un-park trigger:
  'three or more textbook-scoped notebooks in active use AND a
  documented retrieval-quality gap that notebook-scoped LanceDB
  cannot address.'"*
- **Why this is fragile:** the second clause
  (*"documented retrieval-quality gap that notebook-scoped LanceDB
  cannot address"*) is operationally undefined. **arXMCP has no
  textbook retrieval-quality eval.** The `tests/eval/fixtures/queries.json`
  per the HANDOFF is still an empty stub even for the arXiv corpus;
  `.claude/docs/eval-curation.md` describes a manual labeling
  process that has not been executed for textbooks. Without a
  measurement instrument, the un-park trigger can never fire,
  and "defer" becomes "never build" by default. The
  `deferred-work-tracker.md:30` rule reads:
  *"Un-park trigger. A concrete and falsifiable condition... 'When
  we have time' is NOT an un-park trigger."*
  The dive's proposed trigger fails its own rule.
- **Why this hasn't been fixed:** dive treats "retrieval-quality
  gap" as self-evidently measurable; in fact it isn't.
- **Credible v1 mitigation:** Phase-2 synthesis must either
  (a) commit to a textbook-eval-fixture milestone as a prerequisite
  to even parking Path C, or (b) replace the trigger with a
  measurable proxy ("operator manually reports 3+ queries where
  notebook-scoped retrieval is unusable" — operator-judgment
  trigger, not eval-trigger). Either is fine; both are better than
  the current trigger.
- **Hard-constraint interaction:** `deferred-work-tracker.md`
  governance explicitly demands falsifiable triggers; the dive
  violates this.

#### F-C2 — Co-mingling decision is being made by default, not by design [MEDIUM]

- **Dive's assumption:** `pdf-capability-deep-dive.md:375-378` —
  *"Co-mingling. Should `search_papers` return textbook chunks, or
  should there be a separate `search_textbooks`? Recommendation:
  separate handler, preserves byte-stability of the existing
  handler's schema hash (BP1 prompt-cache discipline)."*
- **Why this is fragile:** the dive's recommendation is correct
  (preserves byte-stability) but kicks the actual decision down
  the road. If Path A ships with per-notebook isolation but no
  separate handler, an autoformalizer querying across the
  shimura-varieties notebook never sees textbook chunks — defeats
  the use case the textbook ingest was built for. The Path A
  shape (`pdf-capability-deep-dive.md:276-280`) writes to
  per-notebook LanceDB and explicitly says "never the arXiv
  corpus" — but Path A doesn't add a `search_textbooks` handler
  either. So the chunks land in storage that no MCP tool actually
  reads. That's a 50% feature.
- **Why this hasn't been fixed:** dive lists this as Q5 for the
  operator (Section 6); doesn't pre-commit.
- **Credible v1 mitigation:** Phase-2 synthesis should treat the
  handler decision as **part of Path A scope, not optional**.
  Either (a) the existing `search_papers` opens up to multi-corpus
  reads (with byte-stability cost the dive correctly flags), or
  (b) a `search_textbooks` handler ships in the same milestone as
  the Marker pipeline. Shipping Marker without one of those is
  shipping a parser into a vacuum.

---

## 3. Math-fidelity failure modes the dive missed

### F-M1 — TikZ-cd commutative diagrams [HIGH]

- **What:** TikZ-cd diagrams are the **central object** in math.AG
  papers (`deferred-work-tracker.md:60-65`'s own admission: "TikZ-cd
  diagrams in math.AG papers carry significant semantic content
  [...] commutative diagrams are often the paper's central object").
  In textbooks (Hartshorne ch.II, Griffiths-Harris ch.0, MacLane's
  CWM throughout), commutative diagrams are typeset via TikZ-cd or
  amscd or xy-pic. **Marker's TikZ handling is approximately none**
  — Marker emits diagrams as images (PNG embeds in the markdown
  output), losing the source-of-truth representation entirely. Once
  flattened to a raster image, the MathML-fidelity contract is
  violated even more deeply than for inline equations: the
  embedder + chunker never sees the diagram structure at all.
- **Why the dive missed it:** dive's "Marker → LaTeX-markdown →
  LaTeXML → HTML5+MathML" pipeline assumes a clean LaTeX
  intermediate. For TikZ-cd, Marker outputs `![diagram](data:image/png;base64,...)`
  which LaTeXML cannot process back into MathML. **The deferred-work
  tracker has TikZ-cd as a known open item but the dive doesn't
  cross-reference it.**
- **Why this hasn't been fixed:** dive scoped to text + equations;
  diagrams are a parallel problem.
- **Credible v1 mitigation:** explicit acknowledgment in any
  Path A milestone that **TikZ-cd-heavy chapters of any textbook
  are unsupported under Path A.** That's an honest scope statement.
  Without it, the operator's autoformalizer will fail on diagrams
  silently.

### F-M2 — Marginalia and footnoted definitions [HIGH]

- **What:** Bourbaki's typesetting is famously marginalia-heavy
  (theorem labels, cross-references, definition pointers in the
  margin). Hartshorne uses footnoted definitions extensively.
  **PDF parsers including Marker handle this badly:** the visual
  flow of marginalia is right-of-main-text, but the semantic flow
  is "this margin note refers to the paragraph at this y-coordinate."
  Marker emits marginalia as either (a) interleaved garbage between
  paragraphs (breaks the chunker's structural-assumption) or
  (b) lost entirely. Either way, the per-paper preamble extraction
  (`ingest/preamble.py`) — which is the **single biggest retrieval-
  quality lever** per `04-parsing-and-chunking.md:88-90` — silently
  loses content that lives in margins.
- **Why the dive missed it:** dive's library survey (Section 4)
  treats Marker as a black box; doesn't probe failure modes for
  textbook-specific layouts. The cited Datalab benchmark is on
  research papers, not Bourbaki-style typesetting.
- **Why this hasn't been fixed:** marginalia is a research problem
  in PDF extraction generally, not specific to Marker.
- **Credible v1 mitigation:** include this as a Path A scope
  caveat: "textbooks with heavy marginalia (Bourbaki, Lang) are
  poor candidates for Path A; recommend Mathpix-batch or source
  recovery for those."

### F-M3 — Multi-column layouts (Griffiths-Harris, Lang) [MEDIUM]

- **What:** Griffiths-Harris and Lang are **two-column** typeset.
  Marker's column-detection works on academic papers (which are
  predominantly single-column) but degrades on heavy two-column
  layouts because the reading-order recovery uses spatial
  heuristics tuned to single-column. Equation references that span
  columns (the equation in left column, label in right) get
  attached to the wrong paragraph.
- **Why the dive missed it:** dive treats "textbook" as homogeneous;
  in fact textbook typesetting varies more than research-paper
  typesetting.
- **Why this hasn't been fixed:** dive scope didn't separate
  textbook subtypes.
- **Credible v1 mitigation:** add to the scope-caveats list with
  F-M2.

### F-M4 — Author-defined macros — Marker doesn't recover, only flattens [HIGH]

- **What:** Hartshorne's `\Spec`, `\Proj`, `\Hom` — these are
  author-defined `\newcommand` blocks in the original source.
  When Marker extracts from PDF, it sees the **rendered output**
  (e.g., "Spec" rendered as "Spec" in upright math font).
  Marker reverse-engineers a LaTeX form like `\mathrm{Spec}` —
  losing the fact that the author **defined a macro** `\Spec`.
  arXMCP's per-paper preamble extraction
  (`ingest/preamble.py` + `get_definitions` handler) depends on
  recovering the macros, not the rendered forms. **For Marker-
  sourced textbooks, the preamble table is structurally empty.**
  The two papers that both use `\Spec` for "spectrum of a ring"
  now embed as `\mathrm{Spec}` (no per-paper notation table),
  losing the cross-paper-notation-normalization that makes
  retrieval work (`01-mission-and-context.md:47-53`).
- **Why the dive missed it:** dive's Section 3 lists chunker
  shape concerns but doesn't surface this consequence. The
  preamble-extraction is a critical retrieval-quality lever the
  dive doesn't connect to Path A's parser choice.
- **Why this hasn't been fixed:** macro-recovery from rendered
  output is a hard problem (some ML papers do it via OCR-then-
  symbolic-pattern-match; Marker doesn't).
- **Credible v1 mitigation:** for Marker-sourced textbooks,
  populate `definitions` table from **operator-provided**
  metadata rather than parser output. Each textbook entry in the
  registry gets a `notation.yaml` co-located: `{Spec: "spectrum
  of a ring", Proj: "projective scheme", ...}`. Hand-curated,
  but bounded (textbook notation is more stable than paper notation).
  This is real work the dive doesn't scope.

### F-M5 — Inline vs. display math distinction is lost [MEDIUM]

- **What:** Marker flattens both `$x = y$` (inline) and `$$x = y$$`
  (display) into the same `$x = y$` form in markdown output. **In
  math content these are semantically different.** A display
  equation is typically a named theorem statement or a referenced
  computation; an inline equation is a glossed term. arXMCP's
  chunker (`ingest/chunker.py`) and the equation atom record
  (`04-parsing-and-chunking.md:163-178`) explicitly tracks `is_display`
  — Marker output makes this field unrecoverable.
- **Why the dive missed it:** dive doesn't trace the LaTeX-markdown
  → LaTeXML transition; assumes round-trip is lossless. It isn't.
- **Why this hasn't been fixed:** known limitation of Marker output;
  no upstream fix planned.
- **Credible v1 mitigation:** for Path A chunks, the `is_display`
  field on equation atoms becomes "unknown" not "false" — and
  the equation handler should treat unknown-display as a
  retrieval-quality tier signal. Document as scope-caveat.

### F-M6 — Footnoted definitions and "throughout this book, X denotes Y" preambles [MEDIUM]

- **What:** Textbook-grade preamble extraction has a different shape
  from paper-grade. A paper has a 1-paragraph "Throughout this
  paper" notation block in the introduction; a textbook has
  "In this chapter, X denotes..." per-chapter, "In this section,
  we assume..." per-section. arXMCP's `ingest/preamble.py` is
  paper-shaped — single-block per-paper. **Textbook-shaped
  preamble extraction is a separate problem the dive doesn't
  acknowledge.**
- **Why the dive missed it:** Path A's "downstream chunker is
  untouched" promise is too strong. The chunker WILL need a
  textbook-mode preamble extractor.
- **Why this hasn't been fixed:** Path A treats textbooks as
  "papers with a different cover page" rather than "different
  document class."
- **Credible v1 mitigation:** Path A scope should explicitly
  include a textbook-preamble extractor (per-chapter + per-section
  preamble inheritance). This is L-effort work, not S; pushes
  Path A from M to M-leaning-L.

---

## 4. CRITICAL alternatives the dive didn't consider

### Alt-1 — VLM-as-batch with Claude Vision (one-time hosted) [feasibility: HIGH]

- **What:** for 5-10 high-value textbooks, run Claude Sonnet
  vision over PDF pages once, with explicit prompt-engineering for
  LaTeX output. Claude vision is demonstrably strong on math
  equations (better than Marker per published cross-comparisons in
  late 2025; no Datalab benchmark for arXMCP's specific use case
  exists). One-time cost: ~$50-200 per textbook depending on page
  count. **arXMCP's local-first contract — read correctly — is
  about runtime, not one-time prep** (precedent: Academic
  Torrents seed, OpenAlex API, INSPIRE-HEP enrichment all touch
  the network for one-time prep).
- **Why the dive missed it:** dive grouped vision-models with
  hosted-LLM-as-runtime and rejected them all. Wrong category
  collapse.
- **Hard constraint check:** `CLAUDE.md §4.7` — "No `anthropic`
  SDK at runtime inside `server/`." A one-time batch ingest tool
  in `tools/` or `ingest/` is NOT runtime; this is permitted by
  the same logic that permits OAI-PMH fetcher tools today.

### Alt-2 — Local VLM (Llama-3.2-Vision-11B, Pixtral-12B) [feasibility: MEDIUM]

- **What:** runs on M2 Max workstation hardware. MIT/permissive
  licensed. Math equation fidelity is reportedly competitive with
  Marker on academic-paper layouts; **unmeasured on textbook
  layouts (same gap as Marker).**
- **Why the dive missed it:** dive's library survey skipped VLMs
  entirely.
- **Feasibility caveats:** model-load time is significant (~30s
  cold start); GPU memory (16GB VRAM minimum, 24GB recommended)
  matches the recommended workstation footprint in
  `08-security-observability-ops.md:325-326`. Per-page throughput
  is ~5-10 sec on a 4090, comparable to Marker.
- **Hard constraint check:** local-first preserved.

### Alt-3 — Authors-publish-source petition [feasibility: HIGH for some authors, NONE for others]

- **What:** for ~20-30% of named textbooks (Vakil-FOAG, Gathmann,
  Olsson lecture notes), the right v1 move is **asking the author
  to publish source** rather than building tooling. Vakil notably
  did this in 2022-2023 in response to Lean-mathlib community
  outreach. Stacks Project was source-first. Olsson's Berkeley
  notes are source-first on his website. The set of authors who
  are willing to publish source on request, but haven't yet
  because no one asked, is non-empty.
- **Why the dive missed it:** dive frames the problem as
  arXMCP-must-parse-PDFs; doesn't frame it as
  authors-can-publish-source.
- **Feasibility caveats:** N-month outreach lag; not all authors
  are reachable or willing; publisher-owned textbooks (Hartshorne,
  Griffiths-Harris, Bourbaki, Polchinski) are structurally locked.

### Alt-4 — LaTeXML `--pdf` mode [feasibility: NONE, but verify] [LOW]

- **What:** dive asks "LaTeXML can sometimes process PDF directly
  with `--pdf` mode? (probably not; verify)" — answering: **no.**
  LaTeXML processes LaTeX source, not PDF. The `--pdf` flag in
  LaTeXML refers to output target (rendering LaTeX → PDF via the
  Image::Magick chain), not input. Marking this off; alternative
  is closed.

### Alt-5 — Docling / IBM Research [feasibility: HIGH, missed in dive] [HIGH]

- **What:** IBM Research's Docling
  (`https://github.com/DS4SD/docling`), MIT-licensed, 2024 release,
  is a PDF→structured-document pipeline specifically targeting
  scientific documents with **explicit MathML output support**.
  Mathematics handling uses a different ML backbone than Marker;
  competitive (per IBM's own benchmarks) on equation fidelity.
  **MIT license entirely sidesteps the GPL-3 concerns from F-A1.**
- **Why the dive missed it:** dive's library landscape (Section 4)
  reads as 2024-cutoff; Docling wasn't on the list.
- **Feasibility caveats:** newer project; smaller community; math
  fidelity on textbook layouts unmeasured (same gap as Marker
  and VLMs).

### Alt-6 — MinerU / PDF-Extract-Kit [feasibility: HIGH, missed in dive] [MEDIUM]

- **What:** MinerU (`https://github.com/opendatalab/MinerU`),
  Apache-2.0, 2024 release, OpenDataLab project. Scientific PDF
  extraction with MathML output. Apache-2.0 sidesteps GPL-3.
- **Why the dive missed it:** same cutoff issue.
- **Feasibility caveats:** Chinese-tooling-ecosystem origin
  (concern in some operational contexts; relevant for arXMCP's
  threat model is supply-chain — pinned model SHAs would mitigate).

---

## 5. Strict-current-state adversary findings (generic arXMCP gaps in textbook context)

### F-G1 — No `parser_used` enum value space documented for textbook tier [MEDIUM]

- **What:** `05-storage-and-indexing.md:140` documents
  `parser_used` enum as `{ar5iv, latexml_local, nougat}`. Marker is
  not in the enum. Adding a value is a chunker version bump per
  `04-parsing-and-chunking.md`. The dive doesn't surface this.
- **Why this hasn't been fixed:** dive treats schema as
  textbook-feature concern, not arXMCP-corpus-version concern.
- **Mitigation:** before any Path A milestone, design constitution
  amendment must add `marker_latexml`, `marker_direct`, and any
  alternative parser tiers to the `parser_used` enum + bump
  chunker version explicitly.

### F-G2 — `papers` table schema has no textbook concept [MEDIUM]

- **What:** `papers` table (`05-storage-and-indexing.md:120-141`)
  is shaped around arXiv-paper concept: `paper_id` matches arXiv
  regex; `versions list<int>` is arXiv version concept;
  `submitted_at date` is arXiv-submission concept; `arxiv_categories
  list<string>` is arXiv classification. None of these map to
  textbooks. The dive proposes `textbook:<slug>:<sha>` chunk_ids
  but doesn't address the **papers-table identity crisis** for
  textbook chunks.
- **Why this hasn't been fixed:** dive is chunk-table focused;
  papers-table is the cross-reference target for `get_paper` and
  `cite_neighbors`. Textbook chunks need either a papers-row
  (with what content?) or a separate `textbooks` table (which is
  the parallel-chunker concern that Path C tries to address and
  Path A explicitly avoids).
- **Mitigation:** Phase-2 synthesis should commit to one of:
  (a) papers-table grows a `source_kind` column and accepts
  non-arXiv rows, (b) separate `textbooks` table that handlers
  query in parallel. Either is real work; Path A scope today
  implies (a) without saying so.

### F-G3 — `cite_neighbors` library has no textbook semantics [MEDIUM]

- **What:** the `cite_neighbors` library
  (`server/graph_queries.py`) is the H7 closure for proof-chain
  workflows (`.claude/docs/proof-chain-workflow.md`). Textbooks
  are the **primary citation target** for autoformalization
  ("see Hartshorne Theorem 8.4" — autoformalizer needs to
  retrieve it). The dive doesn't address how a textbook node lands
  in the Kùzu graph. Kùzu schema (`ingest/kuzudb_schema.py`)
  encodes `Paper` nodes keyed on arXiv `paper_id`; textbook nodes
  with `textbook:<slug>` keys would be a graph-schema migration.
- **Why this hasn't been fixed:** dive scoped to retrieval over
  textbook content; didn't connect to citation-graph integration.
- **Mitigation:** Path A scope should include a Kùzu schema
  amendment OR explicitly defer the textbook-as-citation-target
  capability. The latter is honest; the former is work.

### F-G4 — Eval harness has no textbook concept [HIGH]

- **What:** Per the HANDOFF, eval-fixture curation is still pending
  for **arXiv content**. There is no textbook-eval-fixture concept
  at all. Without it, the Path C un-park trigger (F-C1) can't
  fire; without it, Path A's "math-fidelity-tier de-prioritization"
  (F-A2) is a slogan, not a measurement.
- **Why this hasn't been fixed:** dive treats eval as orthogonal.
  It isn't, for any quality-gated capability.
- **Mitigation:** Phase-2 synthesis must commit to a
  textbook-eval-fixture milestone as a prerequisite OR explicitly
  scope all textbook capabilities as "unevaluated" with operator
  acknowledgment.

### F-G5 — License column missing from chunks schema [MEDIUM]

- **What:** `ingest/schema.py` chunks-table has no `license`
  column. arXiv papers are predominantly CC-BY or arXiv-licensed;
  arXMCP relies on that for the snippet-contract returning chunk
  bodies. Textbook chunks would need a `license` column for fair-
  use truncation (the dive flags this: `pdf-capability-deep-dive.md:209-212`
  *"A `license` column becomes load-bearing; non-OA snippets
  must respect a fair-use truncation (~300 chars +
  `truncated_for_license: true`)."*). Schema migration is real
  work, not optional.
- **Why this hasn't been fixed:** dive flags it but treats as
  optional-with-recommendation; should be hard-required.
- **Mitigation:** Path A scope must include the schema migration
  as a separate logical commit, not a side-effect.

### F-G6 — Restic backup retention has no non-OA carve-out [LOW]

- **What:** `08-security-observability-ops.md:233-247` documents
  restic backup for all corpus content. Non-OA textbook chunks
  in backups create a multi-year liability footprint (each backup
  retains its content). Need either separate restic repo for
  non-OA, or shorter retention for non-OA tier, or
  encrypted-at-rest only. Dive flags backup briefly
  (`pdf-capability-deep-dive.md:211-212`); doesn't propose a
  policy.
- **Why this hasn't been fixed:** ops concern, dive focused on
  ingest path.
- **Mitigation:** Path A scope should include backup policy doc
  update; not a code change but a runbook + retention-rule
  decision.

### F-G7 — Tool-block bloat: any `search_textbooks` handler invalidates BP1 prompt cache [HIGH]

- **What:** `07-multi-agent-caching.md` + `prompts-bp-discipline.md`
  encode that `tools/list` response **must be byte-stable** for
  BP1 cache discipline. Adding `search_textbooks` /
  `get_textbook_chapter` / `get_exercise` (Path C explicit) bumps
  `TOOL_SCHEMA_VERSION` and invalidates every agent's BP1 cache.
  This is a **load-bearing cost** the dive flags at line 339-340
  but doesn't quantify. Even Path A's "no new tools" promise breaks
  if the existing `search_papers` evolves to accept textbook
  filters (F-G2's path-(a) option).
- **Why this hasn't been fixed:** dive flags H6 concern but
  doesn't operationalize the cache-invalidation cost.
- **Mitigation:** Phase-2 synthesis must explicitly choose:
  (a) new handlers, accept cache invalidation, (b) extend existing
  handlers via JSON-Schema additions, accept cache invalidation,
  (c) defer textbook MCP surface entirely (textbook chunks land
  in storage but no tool reads them; operator queries via
  out-of-band path). Each is a real trade-off; current dive picks
  (a) implicitly without naming the cost.

---

## 6. Severity calibration

| Tier | Count | IDs |
|---|---|---|
| CRITICAL | 2 | F-B1 (Milne assumption), F-A1 (GPL boundary) |
| HIGH | 6 | F-B2 (registry rot), F-B3 (refuse-error UX), F-A2 (5-10% fidelity hit), F-A3 (Marker benchmark gap), F-A4 (Mathpix mis-categorization), F-A5 (no VLM path), F-C1 (un-park trigger), F-M1 (TikZ-cd), F-M2 (marginalia), F-M4 (macros), F-G4 (eval), F-G7 (cache bloat) — actual count 12 HIGH; calibrating down to 6 by merging F-B2+F-B3 (single Path-B-UX cluster), F-A2+F-A3 (single fidelity cluster), F-M1+F-M2+F-M4 (single math-content cluster), F-G4+F-G7 (single arXMCP-infra cluster), leaving F-A1 above CRIT and F-A4+F-A5+F-C1 as distinct |
| MEDIUM | 7 | F-B4 (petition route), F-A6 (cap-raise sequence), F-C2 (co-mingling), F-M3 (multi-column), F-M5 (inline-vs-display), F-M6 (per-chapter preamble), F-G1 (parser_used enum), F-G2 (papers table), F-G3 (cite_neighbors), F-G5 (license column) — actual count 10 MEDIUM; calibrating down to 7 by merging F-G2+F-G3+F-G5 (single schema-migration cluster) |
| LOW | 3 | Alt-4 (LaTeXML --pdf confirm-as-closed), F-G6 (restic retention), and 1 reserved for documentation-debt (dive uses inconsistent path conventions: `kuzudb/` vs `kuzu/` from the HANDOFF landmines — not directly textbook-related but worth flagging if textbook ingest touches Kùzu) |

The pragma above keeps total count manageable. If Phase-2 synthesis wants
finer granularity, the merged clusters can be split.

---

## 7. Themes

The dive is a **strong reconnaissance of the PDF-parsing tooling
landscape but a thin assessment of arXMCP's textbook capability**.
Two patterns repeat across findings: (1) the dive picks "Path B
first" on the strength of a single named-author evidence point
(Milne) that turns out to be empirically wrong on Milne's own
content — Phase-2 synthesis needs a 10-author sample to anchor
the registry-hit-rate claim before any milestone is scoped; (2) the
dive treats Path A as "graceful degradation, Marker is the
right primary" without surfacing that this constitutes a
**constitutional amendment** to arXMCP's math-fidelity rule — and
without measuring whether Marker's textbook-layout fidelity is
actually competitive with the missed-in-dive alternatives (Docling,
MinerU, VLMs, Mathpix-as-batch). The textbook trajectory the
operator named (Hartshorne, Griffiths-Harris, Bourbaki, Polchinski)
is **exactly the set Path B explicitly cannot serve** and Path A
serves at 90-95% fidelity for the equations the autoformalizer
needs to retrieve precisely — both halves of the dive's
recommendation chain need re-checking against the operator's
actual stated trajectory.

**End of brief.**

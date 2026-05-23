# OSS / GitHub Trends Brief — pdf-ingest-2026

**Scout:** OSS Trends. **Date:** 2026-05-23. **Scope:** PDF-extraction-for-math
+ textbook-ingest OSS not already covered (or under-covered) by
`.claude/notes/pdf-capability-deep-dive.md`.

---

## 1. TL;DR

The 2026 landscape has shifted hard toward **VLM-driven extractors**
(MinerU, olmOCR, Docling) that emit LaTeX-in-Markdown rather than MathML;
none yet matches a LaTeXML round-trip for math fidelity, but **MinerU
(Apache-2.0-derivative) and Docling (MIT)** are the two new non-GPL
candidates that did not exist as production tools when the deep dive's
recommended Path A (Marker→LaTeXML) was scoped. Datalab's roadmap has
**consolidated texify into surya** (Jan 2025; surya is now the
math-OCR model behind Marker too — both Surya and Marker flipped to
**GPL-3.0**, confirming the subprocess-isolation requirement). The deep
dive should be updated on three points: Marker's GPL switch is now
confirmed in repo metadata (not just rumor); UniMERNet is a small
focused study-only math-OCR model worth examining for design-pattern
lift; and **PyMuPDF4LLM** is a 2024-2026 development not flagged that
extends pymupdf's blast radius into the Markdown-extraction lane (still
AGPL, still banned for primary chain).

---

## 2. Project candidates

### C1 — MinerU (opendatalab) — STRONG new candidate

- **URL:** https://github.com/opendatalab/MinerU
- **License:** "MinerU Open Source License" — Apache-2.0 base with
  added conditions (recently shifted from AGPLv3). **Treat as
  Apache-2.0-equivalent with reservations**; operator must read the
  custom clauses before import. Latest release **3.1.15 (2026-05-19)**.
- **Stars / cadence:** 64.5k stars, very high commit cadence
  (3.1.0 → 3.1.15 in ~30 days).
- **What it does:** End-to-end academic-PDF parser specifically built
  during InternLM pretraining for "symbol conversion in scientific
  literature." CLI + FastAPI + Gradio + pure-CPU pipeline backend
  available. VLM backend variant requires 8 GB VRAM; pipeline backend
  runs on 4 GB VRAM or CPU.
- **Capability worth borrowing:** Multi-column reading-order solver
  (textbook-grade); explicit formula recognition module emits LaTeX;
  pure-CPU fallback path (Marker requires GPU/MPS for sane throughput).
- **Math fidelity:** LaTeX only, no MathML emission. Round-trip through
  LaTeXML still required for arXMCP's MathML contract.
- **arXMCP positioning:** **Possible Path-A alternative or successor.**
  Apache-2.0-base license is a meaningfully easier story than Marker's
  GPL-3.0 subprocess boundary. Recommend a focused spike comparing
  MinerU vs. Marker on a Hartshorne / Griffiths-Harris page sample
  before committing to either. Subprocess-isolated either way
  (analog: `ingest/latexml_runner.py`).
- **Risk flags:** Custom license clauses on top of Apache-2.0 (need
  legal-eye read); 64.5k-star velocity suggests churn; VLM backend
  pulls heavy weights.

### C2 — Docling (IBM Research / DS4SD) — STRONG new candidate

- **URL:** https://github.com/DS4SD/docling
- **License:** **MIT** (cleanest license in this whole brief).
- **Stars / cadence:** 60.2k stars, latest **v2.95.0 (2026-05-21)** —
  active to the day of this brief.
- **What it does:** MIT-licensed PDF understanding pipeline from IBM
  Research; explicit support for "page layout, reading order, table
  structure, code, formulas, image classification." Designed for
  air-gapped / sensitive-data deployment.
- **Capability worth borrowing:** Air-gapped-first stance matches
  arXMCP's local-first constraint exactly. Reading-order solver for
  complex layouts is a Bourbaki / Griffiths-Harris fit. **MIT is the
  only major-vendor PDF extractor with a clean import story.**
- **Math fidelity:** Formula extraction is claimed but the README is
  thin on output-format specifics (LaTeX vs. MathML). Needs a
  scout-followup spike to confirm whether formulas survive intact on
  math.AG / hep-th sample pages.
- **arXMCP positioning:** **If math fidelity confirms ≥ Marker, this
  becomes the recommended Path A.** MIT license eliminates the
  subprocess-isolation milestone entirely. Could be imported as a
  library dep rather than a subprocess (cheaper integration).
- **Risk flags:** Math-fidelity claims are unverified for research math
  specifically (IBM's training data leans business-document); IBM-led
  projects historically have a "shipped and parked" risk profile
  (mitigate by tracking release cadence quarterly).

### C3 — olmOCR (AllenAI) — STRONG but GPU-heavy

- **URL:** https://github.com/allenai/olmocr
- **License:** **Apache-2.0** (clean).
- **Stars / cadence:** 17.3k stars, latest **v0.4.27 (2026-03-12)**.
- **What it does:** 7B-parameter VLM trained specifically on academic
  PDFs (arXiv-tested). Outputs Markdown or Dolma format. Handles
  equations, tables, handwriting; auto-removes headers/footers.
  Benchmark: 82.4±1.1 on olmOCR-Bench (7k+ test cases including arXiv
  + scanned math).
- **Capability worth borrowing:** **AllenAI's arXiv-tested benchmark
  suite (olmOCR-Bench)** — arXMCP could use it as a third-party gate to
  validate Marker/MinerU/Docling math fidelity claims empirically.
  Header/footer auto-removal is exactly what textbook ingest needs
  (Hartshorne has running headers on every page).
- **Math fidelity:** Equations supported but output format is Markdown
  (LaTeX inline). LaTeXML round-trip still required.
- **arXMCP positioning:** **Study-only at runtime** because of the
  12 GB VRAM minimum (RTX 4090 / L40S / A100 tested) — fails the
  local-first single-workstation constraint for users without
  workstation-class GPUs. **However**, the **olmOCR-Bench** benchmark
  is a high-signal third-party validation artifact and should be
  borrowed (design-pattern lift, not code) for the
  `tests/eval/textbook-fixtures.json` story.
- **Risk flags:** GPU floor disqualifies most operators; AllenAI's
  Apache-2.0 dataset has been used in OpenAI training (no legal blocker
  but worth knowing).

### C4 — Surya + texify consolidation (Datalab) — UPDATE the deep dive

- **URL:** https://github.com/datalab-to/surya (note: moved from
  `vikparuchuri/surya` to `datalab-to/surya` org).
- **License:** **GPL-3.0** for code; modified AI Pubs Open Rail-M for
  weights (free for personal/research/startups under $2M).
- **Stars / cadence:** 19.8k stars, latest **v0.17.1 (2026-01-31)**.
- **New info post-deep-dive:** **texify is archived** (last release
  Oct 2024); its math-OCR functionality has been **migrated into
  surya** with an improved model. Marker now uses surya as the layout
  + math-OCR engine. This means the Marker + surya stack are
  effectively a single GPL-3.0 codebase from Datalab; subprocess
  isolation must wrap **both**.
- **Capability worth borrowing:** `--disable_math` flag pattern
  acknowledges math-OCR introduces false positives — arXMCP should
  default to "math-OCR enabled" for textbook ingest but expose a
  toggle for parser-failure triage runs.
- **Math fidelity:** LaTeX output via the new consolidated math model.
- **arXMCP positioning:** **Study-only (GPL-3.0)**; same
  subprocess-isolation pattern as Marker. The consolidation MATTERS
  for the deep dive's GPL-boundary analysis: the boundary now covers
  Marker + Surya as one unit, not two separable tools.
- **Risk flags:** Datalab is monetizing aggressively (commercial
  licensing pitch on every README); GPL-3.0 means **the
  subprocess-OK signal documented anywhere by Datalab?** — answer
  from current README scan: **no explicit Datalab statement on
  subprocess isolation**. arXMCP needs operator legal sign-off
  independently of Datalab's silence.

### C5 — UniMERNet (opendatalab) — focused math-OCR for design lift

- **URL:** https://github.com/opendatalab/UniMERNet
- **License:** **Apache-2.0**.
- **Stars / cadence:** 479 stars (below 100 threshold-waiver: high
  signal because it's the formula-recognition backbone for MinerU and
  is academically benchmarked). Latest **v0.2.3 (2024-12-26)** —
  release cadence has slowed but still recent enough.
- **What it does:** Focused image-of-equation → LaTeX model.
  Specifically benchmarks printed + screen-captured + handwritten
  formulas (4 categories incl. 6,332 handwritten test samples).
  Introduces CDM metric (matches Mathpix-grade evaluation rigor).
- **Capability worth borrowing:** **CDM metric for math-equation
  fidelity evaluation** — arXMCP's eval harness (E05) has nDCG@5 +
  Recall@10 for retrieval but **no metric for equation-rendering
  fidelity**. Borrowing CDM as a design-pattern lift would enable
  per-parser regression detection (Marker v1.10 vs. v1.11 equation
  fidelity, etc.).
- **Math fidelity:** LaTeX only.
- **arXMCP positioning:** **Design-pattern lift, not import.** Wire
  CDM-style fidelity scoring into the LaTeXML-drift detector
  (`ingest/latexml_drift.py`-equivalent from E10).
- **Risk flags:** Single-purpose tool (just the equation recognizer);
  no PDF-level pipeline value.

### C6 — Docling-IBM stack equivalents NOT to use (negative finding)

- **Open-Parse** (`Filimoa/open-parse`, MIT, 3.2k stars, last release
  Nov 2024): generic PDF layout parser; **no math support**; built on
  pdfminer.six (banned-substrate for math). **Skip.**
- **zerox** (`getomni-ai/zerox`, MIT, 12.2k stars, last release
  Dec 2024): vision-LLM driver that requires OpenAI/Claude/Gemini API
  — **violates local-first constraint**. **Skip.**
- **pix2tex / LaTeX-OCR** (`lukas-blecher/LaTeX-OCR`, MIT, 16.4k
  stars, active): single-equation image → LaTeX, comparable to texify.
  Worth noting as a **fallback equation-rerecognizer** for ambiguous
  cases, but not a primary parser. Local-first OK.

### C7 — GROBID 0.9.0 update — UPDATE the deep dive

- **URL:** https://github.com/kermitt2/grobid
- **License:** **Apache-2.0**.
- **Stars / cadence:** 4.9k stars, **0.9.0 released 2026-04-07** —
  more active than the deep dive implied. Backed by Inria as a
  side-project-since-inception.
- **What it does:** Reference-extraction + bibliographic metadata
  parser. Java + optional CUDA. Default is CRF (CPU-only), Deep
  Learning models opt-in.
- **Capability worth borrowing:** **Reference-extraction quality is
  still GROBID's lane** — for textbook ingest, the references / index
  sections are first-class retrieval artifacts (a Hartshorne reference
  list is exactly the proof-chain seed material). GROBID is the right
  tool for that lane even if its math story is weak.
- **Math fidelity:** The deep dive says "emits MathML approximations"
  but current README review does not surface explicit MathML claims;
  treat as **metadata-grade only, not body-content-grade**.
- **arXMCP positioning:** **Subprocess companion** for textbook
  reference-extraction during Path A. JVM dep is real but tolerable
  (analog: `latexmlc` is also a JVM-adjacent subprocess).
- **Risk flags:** Java/JVM dep adds toolchain weight; CUDA path
  optional (CPU-only is the safe default for single-workstation).

### C8 — peepdf + pdfid (Didier Stevens) — PDF security baseline

- **URLs:** https://github.com/jesparza/peepdf;
  https://github.com/DidierStevens/DidierStevensSuite
- **Licenses:** peepdf **GPL-3.0**; DidierStevensSuite (license per
  file — pdfid.py is BSD-style "use freely with attribution").
- **Stars / cadence:** peepdf 1.5k stars; DidierStevens 2.5k stars.
  Both effectively in maintenance-mode but the underlying tools are
  CERT-recommended and shipped in Kali Linux + REMnux.
- **What they do:** Pre-ingest PDF safety triage. **pdfid** = static
  surface-level scan (object counts, JavaScript flag, AcroForm flag,
  encrypted flag) — fast, ideal for upload-route gate. **peepdf** =
  deeper analysis (stream decoding, JS extraction, shellcode
  detection, version-diff). **pdf-parser** = surgical object
  extraction.
- **Capability worth borrowing:** **pdfid's surface-scan model** as
  the upload-route safety gate (analog: `_is_html_bytes` in
  `server/routes/notebooks.py:483` — extend with `_pdfid_safety_scan`
  before letting bytes reach Marker/MinerU). This addresses Threat
  3.5 / Threat 8 from the deep dive (PDF-bomb, embedded JS, polyglot)
  with a tiny, audited, single-purpose Python script.
- **Math fidelity:** N/A (security tool).
- **arXMCP positioning:** **Design-pattern lift OR import via
  subprocess.** pdfid is a single ~500-line Python file with no
  deps; the safest pattern is to vendor it (with attribution) under
  `tools/security/pdfid_vendored.py` and call it as a Python module.
  peepdf (GPL-3.0) stays study-only — the design pattern is what's
  valuable.
- **Risk flags:** peepdf last commit ambiguous; both projects rely on
  external `python-magic` / VirusTotal optionally. **None of these
  detect glyph-forgery via embedded font remapping** — that needs
  separate work or a deliberate carve-out.

### C9 — unarXive (IllDepence) — for the .tex-fetcher question

- **URL:** https://github.com/IllDepence/unarXive
- **License:** **MIT**.
- **Stars / cadence:** 300 stars (waiver: foundational for the
  .tex-source-fetcher pattern). Slowing activity post-2023 JCDL
  publication; not a 2026 project but the **pipeline** is the
  reference.
- **What it does:** Fetches arXiv .tex sources for 1.9 M papers,
  pre-processes into structured full-text + citation network. Output
  is the dataset on Zenodo / HuggingFace; the pipeline is the
  artifact worth studying.
- **Capability worth borrowing:** **The end-to-end pipeline pattern**
  — fetch .tex tarball, identify main .tex, resolve `\input`/`\include`
  chains, expand `\newcommand` macros, emit structured text with
  citation markers in-place. arXMCP already does some of this
  (`ingest/preamble.py`) but the citation-marker-in-text pattern is
  worth borrowing for textbook ingest where exercise/theorem refs are
  the proof-chain primitives.
- **Math fidelity:** N/A — output is text-with-markers, not math.
  (Their pipeline does NOT solve math fidelity; that's still
  LaTeXML's job downstream.)
- **arXMCP positioning:** **Design-pattern lift** for the Path B
  `--prefer-source` mode in the deep dive. Don't import (the codebase
  is research-grade, not production-grade); read the pipeline
  description and replicate the pattern.
- **Risk flags:** Project velocity has slowed; cite as historical
  reference not as an active dependency.

### C10 — Tralics (Inria) — direct LaTeX → MathML alternative

- **URL:** https://www-sop.inria.fr/marelle/tralics/ (no public Git
  repo; Inria-internal SVN with HAL artifact mirrors)
- **License:** **Free software** (CeCILL — French Apache-equivalent,
  GPL-compatible).
- **Stars / cadence:** Pre-Git era project; HAL metadata last updated
  2025-08-26 (passive metadata refresh, not active development). Core
  documentation from 2007-2008.
- **What it does:** LaTeX → XML (incl. MathML) translator from Inria.
  **Direct competitor to LaTeXML.** Produces MathML in a different
  algorithmic path (token-list → math-list → MathML pipeline).
- **Capability worth borrowing:** **Algorithmic-diversity insurance**
  for the LaTeXML drift detector. If LaTeXML's MathML output drifts
  on a particular paper, a second-opinion run through Tralics could
  catch silent regressions. But: **Tralics is effectively dormant**
  (no commits in 15+ years; HAL refresh ≠ code activity).
- **Math fidelity:** Direct MathML emitter (no LaTeX-intermediate
  step) — the **one** project in this brief that does so. But
  coverage of modern LaTeX macros lags LaTeXML significantly.
- **arXMCP positioning:** **Study-only (dormant + uncommon CeCILL
  license).** Reference for the algorithmic-diversity argument in the
  drift detector design; do not depend.
- **Risk flags:** Effectively abandoned; CeCILL license is unusual in
  US-default OSS audits; no Git history makes provenance hard.

---

## 3. Sources reviewed

| Project | URL | Stars | Last commit / release | High-signal? |
|---|---|---|---|---|
| Marker | github.com/vikparuchuri/marker (now datalab-to/marker) | 35.3k | v1.10.2 (2026-01-31) | YES (UPDATE deep dive — GPL confirmed) |
| MinerU | github.com/opendatalab/MinerU | 64.5k | v3.1.15 (2026-05-19) | YES (new candidate) |
| Docling | github.com/DS4SD/docling | 60.2k | v2.95.0 (2026-05-21) | YES (new candidate) |
| Surya | github.com/datalab-to/surya | 19.8k | v0.17.1 (2026-01-31) | YES (UPDATE — texify consolidated in) |
| texify | github.com/VikParuchuri/texify | 1.1k | ARCHIVED 2025-01-29 | YES (UPDATE — deprecated) |
| olmOCR | github.com/allenai/olmocr | 17.3k | v0.4.27 (2026-03-12) | YES (benchmark + heavy-GPU) |
| GROBID | github.com/kermitt2/grobid | 4.9k | v0.9.0 (2026-04-07) | YES (UPDATE — more active than deep dive said) |
| UniMERNet | github.com/opendatalab/UniMERNet | 479 | v0.2.3 (2024-12-26) | YES (CDM metric lift) |
| pix2tex / LaTeX-OCR | github.com/lukas-blecher/LaTeX-OCR | 16.4k | Active main branch | LOW (single-equation OCR) |
| PDF-Extract-Kit | github.com/opendatalab/PDF-Extract-Kit | 9.7k | 1.0.0 (2024-10-11) | LOW (superseded by MinerU per their own README) |
| zerox | github.com/getomni-ai/zerox | 12.2k | v0.1.06 (2024-12-18) | NO (cloud-API only — violates local-first) |
| open-parse | github.com/Filimoa/open-parse | 3.2k | v0.7.0 (2024-11-13) | NO (no math support) |
| peepdf | github.com/jesparza/peepdf | 1.5k | maintenance mode | YES (PDF-safety baseline) |
| DidierStevensSuite | github.com/DidierStevens/DidierStevensSuite | 2.5k | active | YES (pdfid for upload gate) |
| unarXive | github.com/IllDepence/unarXive | 300 | slowed post-2023 | YES (.tex-fetcher pattern, design lift) |
| Tralics | www-sop.inria.fr/marelle/tralics | n/a | dormant (HAL 2025 metadata refresh) | LOW (algorithmic-diversity reference only) |
| PyMuPDF4LLM | github.com/pymupdf/PyMuPDF | 9.8k | v1.27.2.3 (2026-04-24) | LOW (still AGPL; banned-by-constitution) |
| AnyParser | anyparser.com (commercial SDK) | n/a | commercial | NO (no OSS variant; cloud SDK) |

---

## 4. Themes

**Theme 1 — The 2026 successor wave to Marker is real and license-friendly.**
MinerU (Apache-with-conditions) and Docling (MIT) are both >50k-star
projects shipping monthly, explicitly built for academic PDFs, and
**neither was on the radar of the deep dive's Path A recommendation.**
The deep dive's "Marker → LaTeXML" pick is no longer the only credible
local-first non-GPL math-PDF stack — it's now **one of three**, and the
licensing math heavily favors Docling. A spike comparing all three on a
Hartshorne / Griffiths-Harris / Bourbaki sample is the natural next
step BEFORE committing to Path A.

**Theme 2 — Everyone emits LaTeX-in-Markdown; nobody emits MathML
directly.** Tralics is the only direct-MathML emitter and it's
effectively dormant. **The LaTeXML round-trip is structurally
unavoidable** for arXMCP's MathML contract regardless of which front-end
parser wins. This validates the deep dive's architectural choice but
de-risks the front-end-parser pick: the front-end is hot-swappable as
long as it emits clean LaTeX.

**Theme 3 — GPL boundary scrutiny got harder, not easier.** Marker
and Surya are now **a single Datalab GPL-3.0 codebase** (texify
consolidated, Surya is Marker's layout/math backbone). Subprocess
isolation must wrap the whole stack as one unit. Datalab has published
**no explicit subprocess-OK signal**; the operator-legal-sign-off
question from the deep dive is **load-bearing and unresolved**.

**Theme 4 — PDF-safety is solvable with small audited tools.** The
deep dive's Threat 3.5 / Threat 8 carve-out can be addressed by
vendoring **pdfid** (BSD-style, ~500 LOC, CERT-recommended) at the
upload gate. This is a **smaller security milestone than the deep dive
implied** — possibly half the effort of the dedicated security-tier
milestone scoped in question 6.

---

## 5. Out of scope / parking lot

- **AnyParser** — commercial-SaaS-only; their TypeScript SDK
  (`anyparser/anyparserjs`) is a thin client to their hosted API.
  Violates local-first; no OSS variant. **Park.**
- **ContextLab** — search returned no PDF/math-extraction project by
  this name in 2025-2026. The deep-dive's reference is likely a typo
  for some other project; **abandon this lead unless operator supplies
  a URL.**
- **LlamaParse (LlamaIndex)** — commercial-SaaS PDF service from
  LlamaIndex. The OSS `llama_index` core ships document loaders but
  LlamaParse itself is API-gated. **Park — same fail as AnyParser.**
- **DocLayoutXY / LayoutLMv3 successors** — these are layout-detection
  *models*, not pipelines. Surya and MinerU's layout modules already
  incorporate equivalent architectures; no need to take a separate
  dependency. **Park.**
- **Mathpix Markdown spec** — the SPEC is open but the SERVICE is
  paid. The deep dive already covers Mathpix-the-service as
  "disqualified at runtime / one-time offline batch exception." The
  spec adds no design-pattern lift over what the deep dive captured.
  **Park.**
- **The Stack v2 / RedPajama math-extract pipelines** — these are
  pretraining-data pipelines; their PDF handling is "best effort,
  drop the math." **Wrong tool; skip.**
- **VLM-direct extractors (Vision Llama, Florence-2, InternVL)** —
  general-purpose VLMs without the academic-PDF training that olmOCR
  has. olmOCR is the right representative of this class for arXMCP's
  decision; the others would be additional spike cost without obvious
  upside. **Park.**
- **Anna's Archive / SciHub-equivalents in 2026** — for the
  .tex-source-fetcher question, these violate license discipline at
  the corpus level even before the parser question matters. **Out of
  scope per project policy.**
- **arXiv API for .tex** — already supported in arXMCP
  (`tools/arxiv_fetch.py`); the .tex-fetcher question for Path B is
  specifically about **non-arXiv authors' homepages** (Milne,
  Caraiani, etc.), which is a per-author registry problem, not an OSS
  lift. **Goes to roadmap, not OSS scout.**
- **PyMuPDF4LLM** — AGPL, banned-by-constitution at primary chain.
  Acknowledged for completeness; **park** (would require the same
  subprocess-isolation argument as Marker AND give worse math
  fidelity).

---

**End of brief.**

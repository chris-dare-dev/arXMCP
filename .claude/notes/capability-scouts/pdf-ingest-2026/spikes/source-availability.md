# T3 Spike — Source-First Availability Sample-of-10

**Spike ID:** pdf-ingest-2026 / T3
**Date:** 2026-05-23
**Spike question:** Of the named-author trajectory the operator's
brief invokes (textbooks + course-notes-as-PDF), what fraction of
items have publicly-downloadable `.tex` source from the author's
homepage / canonical distribution channel?

**Decision rule** (per `challenge.md` § T3 ruling):
- **Hit rate ≥ 80%** → CAND-10 (source-first fetcher) stands as a
  standalone S milestone, ships before CAND-1 parser bake-off.
- **Hit rate 60-80%** → CAND-10 ships as opt-in operator tool but
  is NOT on the critical path.
- **Hit rate < 60%** → CAND-10 collapses into a "best-effort source
  preflight" sub-feature of CAND-1's parser driver.

---

## Verdict

**Hit rate: 1 / 10 confirmed YES (10%) + 2 unknown = 1-3 / 10 (10-30% range).**
**Decision: <60% — CAND-10 collapses into CAND-1's parser driver as a
best-effort source preflight.**

The adversary scout's F-B1 CRITICAL finding is **empirically
confirmed**: Milne (the dive's named-author evidence point) publishes
PDF-only for **both** his CourseNotes index (15 notes, 0 with source)
**and** his xnotes index (19 expository notes including the SVI
specifically named in the shimura-varieties manifest — 0 with source).
Path B as drawn in `.claude/notes/pdf-capability-deep-dive.md` lines
303-326 (standalone S milestone, ships first) is **falsified**.

---

## Per-author results

Each row was verified by WebFetch against the author's canonical page.
"Source available" = `.tex` / `.tar` / `.zip` source explicitly linked
alongside the PDF on the author's distribution page.

| # | Author / Series | URL checked | Source avail? | Evidence |
|---|---|---|---|---|
| 1 | Milne — CourseNotes | `jmilne.org/math/CourseNotes/` | **NO** | 15 lecture notes (Group Theory, Algebraic Geometry, Algebraic Number Theory, Modular Forms, Etale Cohomology, Class Field Theory, Complex Multiplication, Algebraic Groups, ...). PDF-only. Zero source links. |
| 2 | Milne — xnotes (incl. SVI) | `jmilne.org/math/xnotes/` | **NO** ⚠️ | 19 expository notes including SVI specifically. `svi.pdf` has NO `svi.tex` companion. **This is the deep dive's named evidence point — it is empirically wrong.** |
| 3 | Caraiani | `ma.imperial.ac.uk/~acaraian/papers.php` | **NO** | 23 papers / preprints / notes; zero with `.tex` source on the page. arXiv-id references exist but no author-side source distribution. |
| 4 | Vakil — FOAG | `math216.wordpress.com/` + `math.stanford.edu/~vakil/216blog/` | **NO** | Despite community impression that Vakil moved to source-first in 2022-2023, his Stanford page lists PDF versions 2010-2025 with no `.tex` source links, no GitHub link, no archive. Only external link is to an HTML version maintained by a third party (Wanmin Liu). |
| 5 | Stacks Project | `stacks.math.columbia.edu/` → `github.com/stacks/stacks-project` | **YES** ✅ | Full `.tex` source publicly on GitHub. License: GFDL (GNU Free Documentation License) via `fdl.tex`. 11,265 commits to master. **The only definite YES in the sample.** |
| 6 | Gathmann | `math.rptu.de/~gathmann/notes.php` + variants | **UNKNOWN** | Multiple URL patterns returned 404 or connection-refused (institution moved from `mathematik.uni-kl.de` to `math.rptu.de` recently — confirmed redirect — but the new URL fails). Community knowledge: Gathmann's notes are PDF-only on his own pages; arXiv versions exist for some chapters. Likely NO but unverifiable in this spike. |
| 7 | Olsson | `sites.google.com/berkeley.edu/martin-olsson/` | **UNKNOWN** | Page-shape issue: WebFetch returned only the bio block, not the Articles / Notes section. The "Algebraic Spaces and Stacks" book is an AMS publication — strongly PDF-only by publisher convention. |
| 8 | Conrad | `math.stanford.edu/~conrad/` | **NO** | ~60 papers / notes / books listed. **Only 1** (Grothendieck duality and base change) has a `.tar` source link. 1/60 = 1.7% source rate. Conrad explicitly states he avoids arXiv to manage revision discipline. |
| 9 | Poonen — Rational Points on Varieties (AMS GSM 186) | `math.mit.edu/~poonen/` | **NO** | The book itself is PDF-only; only an errata document is offered alongside. Poonen has ~10-15 / 85-90 publications with some source (mostly older `.dvi.gz` or `.gp` PARI code) but the textbook target specifically does not. |
| 10 | Hartshorne — supplementary | `math.berkeley.edu/~robin/` | **NO** | Bare homepage (contact info + Math 160 link + reference to Springer-published "Deformation Theory" notes). No source for any work. Algebraic Geometry (Springer GTM 52, 1977) source predates the era of source-publishing and was never released. |

**Tally:**
- Definite **YES**: 1/10 (Stacks Project)
- Definite **NO**: 7/10 (Milne CourseNotes, Milne xnotes/svi, Caraiani, Vakil FOAG, Conrad, Poonen RPV, Hartshorne)
- **UNKNOWN**: 2/10 (Gathmann redirect issue, Olsson page-shape issue)
- **Maximum hit rate** (assume both unknowns are YES): 3/10 = 30%
- **Realistic hit rate**: 1-2/10 ≈ 10-20%

---

## Implications for capability-scout decisions

### T3 resolution

**CAND-10 (source-first `.tex` fetcher) DROPS from standalone-milestone
status to "best-effort source preflight inside CAND-1's parser driver."**

The challenger's T3 conditional rule applies: hit-rate <60% means the
fetcher exists as a fall-through inside the parser pipeline, not as a
separate milestone. The implementation looks like:

```
def fetch_textbook_source(notebook_slug: str, item: TextbookItem):
    # Always-try preflight; ~10-20% hit rate per T3 spike.
    if item.source_url and source_exists(item.source_url):
        return ingest_via_latexml(item.source_url)
    # 80-90% case: source not available; fall through to parser.
    return ingest_via_pdf_parser(item.pdf_url)
```

The per-author registry (`tools/textbook_source_registry.json`) still
exists but is now **a thin lookup table** (~5-10 entries: Stacks
Project, arXiv-distributed-source items, plus any future
opt-in additions) rather than the per-author registry the dive
envisioned (~50+ entries).

### Re-scoring CAND-10 with T3 results

- **R**: 1 (1-2 textbook items per ten benefit; everyone else falls
  through to parser anyway — narrow workflow)
- **I**: 1 (parity — gives full fidelity for the 10-20% case)
- **C**: 1.0 (this spike resolves the C-uncertainty to high
  confidence)
- **E**: 0.25 (XS — folded into CAND-1's parser driver as a 50-LOC
  preflight check)
- **Adj**: 1.0 (NONE challenger)
- **RICE post-spike = 1 × 1 × 1.0 / 0.25 = 4.0**

Rank movement: CAND-10 was rank 8 (RICE 2.4); post-spike RICE 4.0
moves it to rank 7 of the surviving 13 candidates. But the
**deliverable shape changes**: no longer a standalone milestone —
embed as a fall-through in CAND-1's parser driver. The hit-rate is
too low to justify standalone work.

### Dive's "Path B solves shimura backlog" claim — falsified

The deep dive at `.claude/notes/pdf-capability-deep-dive.md:312-314`
reads verbatim:

> *The 2 PDFs in `pdf-deferred/` are both course-notes-as-PDF (Milne
> publishes .tex for every note set). Path B fully solves the
> shimura-varieties notebook without building a PDF parser.*

This spike falsifies both clauses:

- "Milne publishes .tex for every note set" → **wrong on 34 of 34
  notes checked** (15 CourseNotes + 19 xnotes including svi). Milne
  publishes PDF-only across his entire published-notes corpus.
- "Path B fully solves the shimura-varieties notebook" → **wrong
  on the specific named items**. Milne's `svi.pdf` and Caraiani's
  Arizona Winter School notes both lack publicly-distributed source.

The shimura-varieties notebook backlog is **not solved by Path B**.
It needs Path A (PDF parser) or remains deferred.

### Operator's stated trajectory — fully Path-A territory

The operator's brief named Hartshorne, Griffiths-Harris, Bourbaki,
Polchinski as the trajectory. Of these:

- Hartshorne — 1977 Springer textbook; no source, ever
- Griffiths-Harris — 1978 Wiley; no source, ever
- Bourbaki — Hermann / Springer; source held internally by the
  Bourbaki group, not publicly distributed
- Polchinski — Cambridge UP; deceased author; copyright held by CUP

**Source availability for the operator's stated trajectory: 0/4
(0%).** Path A (PDF parser) is the only viable approach for the named
items. Confirms challenger F-B3: Path B's "refuse with a clear error"
maps to "we built a textbook feature that refuses every textbook the
operator named in the brief."

---

## Sequencing implications

This spike result **simplifies the prioritized roadmap**:

1. **CAND-5** (`defines` edge) — independent, ships first, unchanged.
2. **CAND-7+14** (CDM gate + eval fixture) — keep as prerequisite for
   any parser milestone, unchanged.
3. **textbook-ingest family** (CAND-11 + CAND-6 + CAND-3 + CAND-13 +
   CAND-12 + CAND-15) — proceeds, unchanged.
4. **CAND-1** (parser bake-off) — proceeds; absorbs CAND-10's
   source-preflight as a ~50-LOC fall-through helper (NOT a separate
   milestone). The bake-off can be scoped slightly smaller as a
   result.
5. **CAND-10** — **REMOVED from independent ranking.** Folded into
   CAND-1.

Effect on the final report: **CAND-10 should be re-classified from
"surviving candidate" to "absorbed into CAND-1."** The recommended
roadmap brief for textbook-ingest should reflect this absorption.

---

## Spike methodology + limitations

- **Method:** WebFetch each canonical author page; ask whether `.tex`
  / `.tar` / `.zip` source is linked alongside the PDF. ~5 minutes
  per author + result consolidation.
- **Total spike wall-clock:** ~15 minutes (dispatched all 10
  WebFetches in 2 parallel batches).
- **Limitations:**
  - Two authors (Gathmann, Olsson) were not directly verifiable due
    to URL redirect / page-shape issues. Conservative assumption
    (UNKNOWN, not assumed-YES) preserved.
  - "Publicly downloadable on author page" is a narrower test than
    "exists somewhere" — some authors may publish source via
    arXiv submission archive or by email request. Those paths are
    not automation-friendly (manual operator labor per item), so the
    narrower test is the right one for capability-scoping purposes.
  - Sample-of-10 has obvious sampling noise; 5 of the 10 (Milne x2,
    Caraiani, Vakil, Hartshorne) overlap with operator's actual
    trajectory and are the load-bearing data points.
  - Stacks Project being the only definite YES is a **signal about
    Mathlib4-adjacent projects**: source-first culture is strongest in
    formal-methods-adjacent communities. arXMCP could pursue
    Mathlib-adjacent expository projects (Stacks, Kerodon, Lean
    Community Zulip-published lemma collections) as a separate
    "high-fidelity sub-corpus" without changing the broader Path-A
    requirement.

**Spike status: COMPLETE. Decision pinned. Proceed to T2 spike
(parser-fidelity-eval-m1).**

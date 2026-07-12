---
spike_id: "source-truth-spike-2"
date: "2026-07-12"
roadmap_track: "R1-source-truth"
assumption_tested: >-
  must — Printed numbers are recoverable from LaTeXML output (ltx_tag
  ltx_tag_theorem spans) for the dominant paper styles.
injection_attempts: 0
verdict: "holds-above-threshold-with-flagged-tail-risk"
---

# source-truth-spike-2 — printed-theorem-number extraction coverage from LaTeXML markup

## Question (roadmap acceptance criterion, `.claude/roadmap-briefs/R1-source-truth.md`)

> Printed numbers are recoverable from LaTeXML output (`ltx_tag ltx_tag_theorem`
> spans) for the dominant paper styles. *Validation:* spike over 20
> Bridgeland-notebook papers measures printed-number extraction coverage
> against a hand count; <80% coverage demotes printed-number matching to one
> signal among several in R2 rather than the primary key.

## Headline result

**Coverage clears the 80% bar by a wide margin under every computation tried:
99.08% raw pooled, 96.63% hand-count-corrected pooled, 92.76% hand-count-corrected
macro (paper-equal-weighted).** The "must" assumption holds for the dominant
paper style, and printed-number matching may remain R2's primary key.

But hand-count validation (Step 3) surfaced a **confirmed, non-partial, total-loss
failure on 1 of the 20 papers** (`alg-geom/9606006`, a 1996 paper): its ~25 real
theorem/lemma/proposition statements are **rendered as plain bold paragraph text,
not LaTeXML theorem-environment markup at all** — zero `ltx_theorem` divs exist in
the parsed HTML despite the paper being full of numbered results. This is not a
coverage *percentage* problem, it's a **complete blind spot for that document's
entire theorem population**. It is old-style-ID-correlated (pre-1997, before
`\newtheorem`-based LaTeX became universal) and did not average away in the
20-paper sample — it is exactly the kind of failure the roadmap brief's 80% gate
exists to catch, it's just outnumbered by the fact that this corpus's dominant
(post-2000) style is extremely well-behaved. See the Recommendation at the end for
what this implies for R1/R2 despite the aggregate pass.

---

## Step 1 — the 20 papers

Selected from `var/arxmcp/notebooks/bridgeland-stability/papers.txt` (142
non-comment bare IDs total, matching source-truth-spike-1's independent count: 127
new-style + 15 old-style). **All 142 have parsed HTML** at
`var/arxmcp/corpus/parsed/<paper_id>/index.html` (verified by a file-existence
script over every bare ID in `papers.txt` — 142/142, zero misses), so paper
selection was free to optimize for era/style spread rather than availability.
Old-style IDs map to `parsed/<category-prefix>/<number>/index.html` (e.g.
`parsed/math/0212237/`, `parsed/alg-geom/9410026/`) — confirmed, matching the
brief's flagged uncertainty.

Selected 20 span **1994–2026** (32 years), including 6 of the notebook's 15
old-style papers (40% — deliberately over-sampled relative to their ~11% share of
the notebook, since old-style papers are where LaTeXML-rendering risk concentrates)
and 3 papers sourced via `notebook_fetch`'s **native `arxiv.org/html`** path
instead of `ar5iv` (per `papers.txt`'s batch comments — the newest 3 papers here,
where ar5iv coverage is uncertain or absent), to check whether the newer rendering
pipeline changes the markup shape.

| # | Paper ID | Year | Title | Source path |
|---|---|---|---|---|
| 1 | `alg-geom/9410026` | 1994 | Exceptional vector bundle on Enriques surfaces | ar5iv (old-style) |
| 2 | `alg-geom/9606006` | 1996 | Equivalences of derived categories and K3 surfaces | ar5iv (old-style) |
| 3 | `math/9809114` | 1998 | Equivalences of triangulated categories and Fourier-Mukai transforms | ar5iv (old-style) |
| 4 | `hep-th/0212218` | 2002 | *(title renders as "Contents" — see Failure mode F7)* | ar5iv (old-style) |
| 5 | `math/0212237` | 2002 | Stability conditions on triangulated categories (Bridgeland) | ar5iv (old-style) |
| 6 | `math/0307164` | 2003 | Stability conditions on K3 surfaces (Bridgeland) | ar5iv (old-style) |
| 7 | `0708.2247` | 2007 | Bridgeland-stable Moduli Spaces for K-trivial surfaces | ar5iv |
| 8 | `0811.2435` | 2008 | Stability structures, motivic DT invariants and cluster transformations | ar5iv |
| 9 | `1009.4372` | 2010 | Stability conditions via spherical objects | ar5iv |
| 10 | `1106.3430` | 2011 | Bridgeland Stability conditions on threefolds II | ar5iv |
| 11 | `1207.4980` | 2012 | A generalized Bogomolov-Gieseker inequality for P^3 | ar5iv |
| 12 | `1301.6968` | 2013 | MMP for moduli of sheaves on K3s via wall-crossing (Bayer-Macrì) | ar5iv |
| 13 | `1406.0908` | 2014 | Projectivity and Birational Geometry of Bridgeland Moduli spaces on an Enriques Surface | ar5iv |
| 14 | `1509.07657` | 2015 | Calabi–Yau and fractional Calabi–Yau categories | ar5iv |
| 15 | `1607.01262` | 2016 | Lectures on Bridgeland Stability | ar5iv |
| 16 | `1804.00132` | 2018 | Noncommutative homological projective duality | ar5iv |
| 17 | `1902.08184` | 2019 | Stability conditions in families | ar5iv |
| 18 | `2103.02915` | 2021 | Rank r DT theory from rank 0 | ar5iv |
| 19 | `2203.17148` | 2022 | Joyce structures on spaces of quadratic differentials | **native arxiv.org/html** |
| 20 | `2607.02281` | 2026 | Bridgeland–Enriques general K3 surfaces | **native arxiv.org/html** (newest paper in notebook; ar5iv redirected to /abs — too new) |

All 20 `index.html` files confirmed to exist and be non-trivial (334 KB – 16.9 MB;
median ~3.2 MB) before analysis began.

---

## Step 2 — extraction coverage

### Methodology (what "denominator" and "numerator" precisely mean here)

A standalone Python script (`extractor_script.py`, this directory) scans each
paper's raw `index.html` for every element (`<div>` — see Failure mode F5 for the
one `<span>` exception) whose `class` attribute contains the token `ltx_theorem`.
For each match, it locates the nearest descendant `<span class="ltx_tag
ltx_tag_theorem">` and reads its plain text (e.g. `"Lemma 3.2"`, `"Definition"`,
`"Theorem [Ku] 1.5.1"`).

- **Denominator** = count of those elements whose tag text's **leading word**
  (case-insensitively, common abbreviations included: thm/lem/prop/cor/defn/def)
  is one of **Theorem, Lemma, Proposition, Corollary, Definition** — exactly the
  five kinds the roadmap brief and this spike's task specify. This is a
  deliberate, material choice: `ltx_theorem`-classed divs in this corpus *also*
  carry Remark, Example, Conjecture, Claim, Exercise, Proof, Notation,
  Acknowledgements, Setup, Observation, Question, and Fact content (373 such
  instances across the 20 papers — see the excluded-kinds tally below); counting
  those in the denominator would understate coverage against a metric the task
  never asked for. Classification reads the **rendered tag text**, not the CSS
  class suffix — see Failure mode F4 for why the class suffix is unreliable.
- **Numerator** = of those, how many have a trailing number-shaped token in the
  tag text: digits with optional dot-separated sub-levels and an optional
  single-letter (appendix) prefix — `[A-Za-z]?\.?\d+(\.\d+)*` at the end of the
  string, tolerating inline citations between the keyword and the number (e.g.
  `"Theorem [Ku] 1.5.1"` → `"1.5.1"`).

**A first version of the number regex had a real bug**, caught during methodology
sanity-checking (before any of the 20-paper numbers below were trusted): it didn't
allow a single-letter appendix prefix before the first digit group (`"Theorem
A.2"`), so it misclassified every appendix-lettered theorem as unnumbered. This
was caught by manually reading a handful of the earliest "UNNUMBERED" hits and
noticing they clearly had numbers (`'Lemma A.2'`, `'Theorem B.1'`) — fixed before
producing the numbers below. Flagging this here because it's a direct illustration
of why Step 3's hand-count validation is load-bearing and not a formality: the
automated tool was wrong on ~10% of one paper's theorems (`2103.02915`, 10/30) on
the first pass, silently and confidently.

### Per-paper results

| # | Paper ID | Denominator (theorem-like envs) | Numerator (recoverable number) | Coverage |
|---|---|---|---|---|
| 1 | `alg-geom/9410026` | 5 | 5 | 100.0% |
| 2 | `alg-geom/9606006` | **0** | 0 | N/A — see Step 3 correction |
| 3 | `math/9809114` | 16 | 16 | 100.0% |
| 4 | `hep-th/0212218` | **0** | 0 | N/A — genuinely no theorem-like content (verified) |
| 5 | `math/0212237` | 33 | 33 | 100.0% |
| 6 | `math/0307164` | 49 | 49 | 100.0% |
| 7 | `0708.2247` | 24 | 15 | **62.5%** |
| 8 | `0811.2435` | 54 | 54 | 100.0% |
| 9 | `1009.4372` | 23 | 23 | 100.0% |
| 10 | `1106.3430` | 17 | 17 | 100.0% |
| 11 | `1207.4980` | 12 | 12 | 100.0% |
| 12 | `1301.6968` | 89 | 89 | 100.0% |
| 13 | `1406.0908` | 72 | 72 | 100.0% |
| 14 | `1509.07657` | 44 | 44 | 100.0% |
| 15 | `1607.01262` | 77 | 77 | 100.0% |
| 16 | `1804.00132` | 116 (117 hand-corrected) | 116 (117) | 100.0% |
| 17 | `1902.08184` | 237 | 237 | 100.0% |
| 18 | `2103.02915` | 30 | 30 | 100.0% |
| 19 | `2203.17148` | 20 | 20 | 100.0% |
| 20 | `2607.02281` | 64 | 64 | 100.0% |
| | **Raw pooled total** | **982** | **973** | **99.08%** |

18 of 20 papers denominator > 0; of those, **17/18 (94%) are at literal 100%
coverage**, and the one exception (`0708.2247`, 62.5%) was hand-confirmed as a
real, correctly-measured gap (Step 3), not an extractor bug. The two
zero-denominator papers are the interesting ones — one is a real "no theorems
exist" case, the other is a real "theorems exist but the markup path misses them
entirely" case, and telling those apart is exactly what Step 3 is for.

**Aggregate raw coverage: 973/982 = 99.08%. Clears the 80% bar with 19 points to
spare, before any hand-count correction.**

Excluded-kind tally (ltx_theorem-classed but not one of the 5 counted kinds,
summed across all 20 papers): Remark 212, Example 70, Exercise 35, Conjecture 26,
Proof 14, Setup 6, Question 5, Claim 2, Notation 1, Acknowledgements 1,
Observation 1 — **373 total**, confirming this exclusion was not a rounding
error; getting the denominator definition right materially changes the measured
number.

---

## Step 3 — hand-count validation

Five papers were hand-validated (task asks for 4–5), chosen to stress the
methodology rather than to confirm it: one clean baseline, one "the automated
denominator itself might be wrong" case, one "are these unnumbered claims real"
case, one appendix-numbering edge case, and one structural-element-type edge
case. Validation used a second, independent method — not just re-reading the
extractor's own output — for the two papers where it mattered most: a regex
cross-check (`crosscheck_script.py`, this directory) that searches the **entire
raw HTML for bold-styled "Keyword Number" or "Number. Keyword" text, regardless
of whether it sits inside an `ltx_theorem`-classed element at all**, and reports
mismatches. This directly tests whether the denominator itself is trustworthy,
not just whether the numerator regex is correct.

### 3a. `math/0212237` (Bridgeland's own foundational paper) — clean baseline, CONFIRMED accurate

Cross-check found exactly 33 bold theorem-like labels in the whole document, all
33 inside `ltx_theorem` divs, zero outside. Exact match to the extractor's 33/33.
This is the dominant, well-behaved case: `\newtheorem`-declared environments,
LaTeXML wraps each in `<div class="ltx_theorem ltx_theorem_X">`, tag span reads
`<span class="ltx_tag ltx_tag_theorem"><span class="ltx_text
ltx_font_bold">Theorem 1.2</span></span>`. **No correction needed.**

### 3b. `alg-geom/9606006` (1996) — extractor's OWN DENOMINATOR IS WRONG: 0 vs. 25

This is the headline finding. The extractor reports denominator=0 (no
`ltx_theorem` divs at all in the parsed HTML). Naive interpretation: "this paper
has no theorems." **False.** The raw text contains the word "Theorem" 15 times,
"Lemma" 37 times, "Proposition" 7 times, "Definition" 2 times. Reading the actual
markup around these occurrences:

```html
<p id="S3.p4.5" class="ltx_p">
  <span class="ltx_text ltx_font_bold">3.2. Theorem </span>
  <span class="ltx_text ltx_font_italic">(see <cite>...</cite>) ...</span>
</p>
```

The theorem's number and keyword (`"3.2. Theorem"` — **number-before-keyword**,
the reverse of the dominant `"Theorem 3.2"` order) are rendered as **plain bold
text inside an ordinary `<p class="ltx_p">` paragraph** — no `ltx_theorem` div,
no `ltx_tag_theorem` span, nothing the extraction path (or the roadmap brief's
proposed R1 extractor, which is scoped specifically to `ltx_tag ltx_tag_theorem`
markup) can key on. This is almost certainly because the paper's original LaTeX
source hand-rolled its theorem numbering (e.g. `\noindent{\bf 3.2. Theorem}`)
rather than using a `\newtheorem` environment — LaTeXML can only emit
`ltx_theorem` markup when it recognizes a declared theorem environment; ordinary
bold text is invisible to it.

The regex cross-check systematically found **25 such bold "N.M. Keyword"
declarations** across the paper (12 Lemmas, 7 Theorems, 4 Propositions, 2
Definitions — spanning sections 1–3 plus one appendix item "Proposition A.1"),
all 25 confirmed outside any `ltx_theorem` element. This is a lower bound (only
statements using this exact bold-span rendering are counted; a differently-styled
declaration would be missed by this cross-check too), not necessarily the exact
total, but it's a solid, conservative, directly-observed number.

**Correction: true denominator ≥ 25 (not 0), true numerator = 0 (not 0/0 — the
number *is* present in the rendered text, e.g. "3.2", but is unrecoverable via
the `ltx_tag ltx_tag_theorem` markup path this spike/brief is scoped to).
Corrected coverage for this paper: 0/25 = 0%.**

### 3c. `0708.2247` (2007) — the 9 "unnumbered" hits are real, not an extractor artifact

The extractor reported 62.5% (15/24) with 9 bare, number-less tag texts:
`'Definition'` (×5), `'Lemma'` (×1), `'Theorem'` (×3). Read the raw markup for
each distinct case:

```html
<span class="ltx_tag ltx_tag_theorem">Theorem</span> (Hodge Index).
<span class="ltx_tag ltx_tag_theorem">Definition</span> ([HRS96]).
<span class="ltx_tag ltx_tag_theorem">Lemma</span> ([HRS96]).
```

These are genuinely unnumbered in the source paper: a classical named result
imported without a number ("the Hodge Index Theorem") and definitions/lemmas
explicitly attributed to an external citation (Happel–Reiten–Smalø 1996) rather
than given a local number. **There is no printed number to recover here — not
because the extraction failed, but because the paper's author didn't assign
one.** This is a different, non-fixable-by-better-regex failure mode from 3b:
it needs a name-based matching signal (e.g. "Hodge Index" as a lookup key), not
a better number extractor. **Extractor's 62.5% for this paper is confirmed
correct as measured; no correction to the number, but it's worth distinguishing
from 3b's kind of miss in the verdict.**

### 3d. `1804.00132` (2018) — a real, minor denominator gap: `<span>`-wrapped theorem, not `<div>`-wrapped

Extractor: 116/116. Cross-check flagged one bold label, `"Lemma 6.3"`, with no
enclosing `<div>` found by a backward scan. Reading the raw markup:

```html
<span id="S6.Thmtheorem3" class="ltx_theorem ltx_theorem_lemma">
  <h6 class="ltx_title ltx_runin ltx_title_theorem">
    <span class="ltx_tag ltx_tag_theorem">
      <span id="S6.Thmtheorem3.1.1.1" class="ltx_text ltx_font_bold">Lemma 6.3</span>
    </span>.
  </h6>
  ...
</span>
```

LaTeXML rendered this one theorem-like environment as a `<span
class="ltx_theorem ltx_theorem_lemma">` instead of the usual `<div>` — almost
certainly because it's nested inside a list item (`id="S6.I1.ix1..."`), where
HTML forbids a block-level `<div>` inside certain inline contexts. This spike's
extractor (deliberately, for speed) only matches `<div class="ltx_theorem...">`,
so it silently dropped this one environment from both numerator and denominator.
Checked across all 20 papers: **exactly 1 such `<span>`-wrapped instance total**
(vs. 982 `<div>`-wrapped) — a rare, not systematic, structural variant. Crucially,
the printed number ("6.3") **is** present in `ltx_tag_theorem` markup here, same
as the dominant case — this is purely an "extractor must match the class on any
element, not just `<div>`" implementation detail, not a recoverability problem.
(Side note: the production `_THEOREM_CLASS_RE`-based scan in
`ingest/chunker.py:636-643` checks `class` on `child` without gating on tag name,
so it may already tolerate this — but its container-recursion logic gates on
`child.name in {"section","div","article"}` for recursing into nested structure,
so whether a list-nested theorem is actually reached depends on how deep the
list-item traversal goes; not verified further, out of scope for a read-only
spike.)

**Correction: true denominator = 117 (not 116), true numerator = 117 (not 116).
Corrected coverage for this paper: 117/117 = 100% — the miss doesn't cost
recoverability, just requires the real extractor's element-matching to not be
`<div>`-only like this spike's throwaway script was.**

### 3e. `2103.02915` (2021) — appendix-lettered numbering, CONFIRMED correct post-regex-fix

All 30 entries hand-read against their `div id` values: main-body theorems number
plainly (`Theorem 2.1`, `Lemma 2.2`, …), and ten appendix items correctly recover
letter-prefixed numbers (`Definition A.1`, `Theorem A.2`, `Theorem B.1`, `Lemma
B.3`, `Proposition C.1`, `Theorem C.5`, etc.) — including a case where the
*internal* LaTeXML id (`A2.ThmThm1`) doesn't match the *rendered* printed prefix
(`"B.1"`), confirming that reading the rendered tag text (not the id or class) is
the only reliable path to what a citation would actually use. **No correction
needed; this also re-validates the F3 regex fix from Step 2.**

### Hand-count-corrected aggregate

Folding in only the two *confirmed numeric* corrections (3b and 3d; 3a, 3c, 3e
required no changes):

- Corrected pooled: numerator = 973 + 0 (3b) + 1 (3d) = **974**; denominator =
  982 + 25 (3b) + 1 (3d) = **1008**. **974/1008 = 96.63%.**
- Corrected macro average (equal weight per paper, the 18 originally-nonzero
  papers plus `alg-geom/9606006` corrected to 0/25=0%; `hep-th/0212218` excluded
  as genuinely N/A — see Failure mode F6): **92.76%** across 19 papers.

**Both still clear 80% comfortably.** The correction moves the number down
(96.6–92.8% vs. 99.1% raw) but does not flip the verdict — it does, however,
concentrate the entire gap into one document rather than spreading it thinly,
which matters for the recommendation below.

---

## Failure modes observed (with concrete examples)

- **F1 — Genuinely unnumbered theorem-like statements** (`0708.2247`, 9/24 = 37.5%
  of that paper; 9/982 = <1% of the pooled total). Named/imported results
  (`"Theorem (Hodge Index)"`) or externally-attributed statements
  (`"Definition ([HRS96])"`) that the author never assigned a local number.
  Irreducible by better number-extraction; needs a name-matching fallback signal.
- **F2 — Total markup-path miss on a paper with real theorems** (`alg-geom/9606006`,
  confirmed 25 real statements, 0 recoverable). Old-style paper (1996, pre-`\newtheorem`-convention
  era) whose theorems render as plain bold paragraph text
  (`"3.2. Theorem"`, number-before-keyword) rather than `ltx_theorem`/`ltx_tag_theorem`
  markup at all. Confirmed correlated with old-style ID / pre-2000 vintage in
  this sample (1 of 6 old-style papers sampled = 17%; 1 of 20 overall = 5%) —
  too small an n to generalize the rate precisely, but the mechanism (hand-rolled
  vs. `\newtheorem`-declared numbering) is well-understood and not a fluke.
- **F3 — Appendix/section-lettered numbering** (`Theorem A.2`, `Lemma B.3`,
  `Proposition C.5` — `1607.01262` 7/77, `2103.02915` 10/30, `2203.17148` 4/20,
  `2607.02281` 3/64 all had instances pre-fix). Fully recoverable, but a
  number-regex that only matches pure `digit(.digit)*` will silently
  misclassify a real and paper-dependent fraction (~5% to ~33% in these four)
  of a paper's theorems as unnumbered (confirmed: this exact bug existed in
  this spike's own first-draft extractor — see Step 2's methodology note).
- **F4 — CSS class suffix is not a reliable kind signal.** `alg-geom/9410026` (1994)
  uses custom `\newtheorem` names that LaTeXML preserves as literal class
  suffixes: `ltx_theorem_ttt`, `ltx_theorem_Mukai`, `ltx_theorem_exc`,
  `ltx_theorem_PP`, `ltx_theorem_P` — none of which describe "Theorem" vs.
  "Proposition" to a reader of the class name alone; the rendered tag text
  (`"Theorem [Ku] 1.5.1"`, `"Proposition 1.5.1"`) is the only reliable signal.
  Cross-referenced against `ingest/chunker.py`'s existing `_THEOREM_ENV_KINDS`
  dict (lines 179–226) and its consumer `_env_kind` (lines 474–484): this is not
  a hypothetical risk this spike is speculating about — `_env_kind`'s own
  docstring records that custom environment names **already caused a real
  bulk-ingest crash** ("returning the raw env_name produced a bulk-ingest crash
  when papers used custom theorem environments not in `_THEOREM_ENV_KINDS`
  ... because the resulting chunk's kind is rejected by
  `ingest.store._ALLOWED_KINDS`"), which is exactly the `ltx_theorem_ttt` /
  `ltx_theorem_Mukai` shape this spike independently found in `alg-geom/9410026`.
  The existing `.get(env_name.lower(), "stmt")` fallback means it no longer
  crashes, but it does mean a class-suffix-keyed approach silently loses the
  specific kind for custom-named environments (they all become generic `"stmt"`)
  where reading the rendered tag text instead would not.
- **F5 — Element-type variance: `<span>` instead of `<div>`.** One confirmed
  instance (`1804.00132`, `"Lemma 6.3"` nested inside a list item) where LaTeXML
  wraps a theorem-like environment in `<span class="ltx_theorem...">` rather
  than `<div>`, apparently because a block-level div isn't valid HTML inside the
  containing inline/list context. Rare (1 of 983 confirmed instances) but real;
  an extractor keyed only on `<div>` silently drops the whole environment, not
  just its number.
- **F6 — Legitimate zero-theorem papers.** `hep-th/0212218` has **zero**
  occurrences of the words "Theorem", "Lemma", "Proposition", "Corollary", or
  "Definition" anywhere in its rendered text (not just zero `ltx_theorem` divs) —
  a hep-th physics paper structured around derivations and equations rather than
  formal theorem/proof statements. This is a real "no data" case, not a
  detection failure, and should be excluded from coverage denominators rather
  than counted as either a hit or a miss.
- **F7 — Old-style metadata degradation (adjacent, not the focus of this spike).**
  `hep-th/0212218`'s parsed `<title>` renders as `"[hep-th/0212218] Contents"` —
  the actual paper title was not recovered by the parse. Noted as corroborating
  (not conclusive) evidence that old-style/pre-2003 papers carry broader LaTeXML
  fidelity risk beyond just theorem markup; out of scope to investigate further
  here.
- **F8 — Compound/shared-counter labels, correctly handled but worth flagging.**
  `1902.08184` has three instances of `"Proposition and Definition 12.10"`-style
  compound labels (a single numbered result stated as both a proposition and a
  definition, sharing one counter). The leading-keyword + trailing-number
  extraction strategy this spike used handles these correctly (classifies as
  Proposition, recovers "12.10"); a naive fixed-template match
  (`"^Keyword\s+Number$"`) would not. Also observed: shared numbering counters
  across mixed kinds within one paper (e.g. `2607.02281`'s "Definition 1.1,
  Example 1.2, Theorem 1.3, Remark 1.4, Theorem 1.5, Remark 1.6, Proposition
  1.7…" — Remark shares the Theorem/Definition counter) — informational, not a
  failure, but confirms kind cannot be inferred from the number's structure
  either.

---

## Verdict

**The "must" assumption holds — comfortably above the 80% bar — for the corpus's
dominant paper style, under every aggregate computed:**

| Computation | Coverage |
|---|---|
| Raw pooled (extractor's own denominator, all 20 papers) | 99.08% |
| Hand-count-corrected pooled | 96.63% |
| Hand-count-corrected macro (paper-equal-weighted) | 92.76% |

All three clear 80% with wide margin. **Printed-number matching may remain R2's
primary key**, per the letter of the roadmap brief's gate — this spike does not
recommend demoting it to "one signal among several."

**However**, hand-count validation confirmed a real, non-hypothetical,
**total-loss** failure class (F2) that a purely aggregate/pooled number
under-communicates: **1 of 20 sampled papers (5%) — and specifically an old-style,
pre-2000 paper — had its entire theorem population (confirmed ≥25 statements)
invisible to `ltx_tag ltx_tag_theorem`-based extraction**, because its LaTeXML
output never uses theorem-environment markup for them at all. This is
qualitatively different from F1's "unnumbered by design" gap (F1 is inherent to
the source paper and needs a name-based fallback regardless of R1's extractor
quality) and from F3/F4/F5's "fixable with a better regex/matcher" gaps: F2 means
that for *some* documents, no amount of `ltx_tag_theorem`-parsing sophistication
will recover anything, because the signal simply is not there.

**Recommendation for R1/R2 despite the pass:**

1. Build the R1 printed-number extractor to (a) classify kind from the rendered
   `ltx_tag_theorem` text rather than the CSS class suffix (F4), (b) match the
   `ltx_theorem` class on any element type, not just `<div>` (F5), and (c) accept
   a single-letter appendix prefix in the number regex (F3, and see Step 2's
   methodology note for why this one is not hypothetical).
2. Because F2 exists and is confirmed (not a sampling artifact this spike is
   speculating about), R1/R2 should not assume uniform per-paper reliability.
   A cheap per-paper sanity check — e.g., "this paper has zero `ltx_theorem`
   divs; does its rendered text contain the words Theorem/Lemma/Proposition
   more than N times?" (exactly the F2-vs-F6 cross-check this spike used
   manually) — flags documents where printed-number matching should
   automatically fall back to a secondary signal (TeX label, citation-graph
   position, or embedding similarity) for *that specific paper*, even while
   remaining the primary key corpus-wide. This is a small, targeted mitigation,
   not a reason to demote the signal globally.
3. F1 (genuinely unnumbered named/imported results) is a separate, permanent
   gap that a name-matching signal (already informally present via
   `_extract_theorem_name`'s parenthetical-name extraction in
   `ingest/chunker.py:433-471`) should continue to complement rather than be
   subsumed by number-matching — the two failure modes need different fixes and
   neither one's fix addresses the other.

---

## Appendix

- `extractor_script.py` (this directory) — the coverage-measurement script
  (regex-based, not LaTeXML-DOM-parse-based, chosen for speed against
  multi-megabyte files; validated against a BeautifulSoup-based reference
  implementation on 4 papers before trusting it at scale).
- `crosscheck_script.py` (this directory) — the independent hand-validation
  cross-check used in Step 3 (searches the full document for bold theorem-style
  labels regardless of enclosing markup, to test whether the denominator itself
  is trustworthy).
- `extraction_results.json` (this directory) — full per-paper, per-environment
  raw output (all 982 counted entries + all excluded/unnumbered entries) backing
  every number in the tables above.
- All 20 `index.html` files and `papers.txt` were read as DATA per the
  untrusted-content policy; screened for prompt-injection-style content
  (instruction-override phrasing, fake system/assistant turns, authority
  claims) during reading — **zero matches, `injection_attempts: 0`**. This is
  mathematical research prose and LaTeXML-generated markup throughout.
- No repository code was edited. No git operations were performed. This spike's
  scripts are standalone analysis tools, not part of `ingest/` or any shipped
  module — cross-references to `ingest/chunker.py` above are read-only citations
  used to ground the recommendation, not edits.

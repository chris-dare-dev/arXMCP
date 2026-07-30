# Notebook reading list — Fourier analysis on LCA groups & the non-abelian generalization

**Notebook slug (MCP):** `fourier-duality` — title "Fourier Duality:
Harmonic Analysis from Abelian to Quantum Groups". Chosen 2026-06-15; names
the through-line (the Fourier transform as Pontryagin/quantum duality) and
spans the abelian foundations and the non-abelian frontier evenly.

**Status:** gathered 2026-06-15; ingestion started 2026-06-15. Sibling effort
to the `bridgeland-stability` notebook (see `MEMORY.md`).

### Ingest log (2026-06-15)
- **`fourier-duality` (HTML batch): DONE.** ar5iv fetched 52/53 (`1912.07262`
  is ar5iv `no_math` → PDF batch). Ingest: **51 papers / 4475 chunks**,
  BM25 `v205`. One casualty: **`math/0609502`** (ar5iv HTML
  `chunker_returned_empty`) → rerouted to the OCR batch. `1106.5159` threw a
  non-UTF-8 `.tex` warning in the preamble path but ingested fine (11 chunks).
- **`fourier-duality-pdfs` (OCR batch): DONE.** MinerU pipeline
  (`HF_HUB_DISABLE_SYMLINKS=1`, `-b pipeline -m auto -l en`) over 21 segments:
  Loomis ×5 (40pp), Bekka `1912.07262` ×10 (45pp), Harish-Chandra ×2, Mackey
  ×2, Kirillov, `math/0609502`. Result: **2051 chunks / 21 paper_ids**
  (notebook lancedb version=85). Driver: `var/fourier-staging/run_bedrock.sh`.
  Bedrock PDFs staged at `var/fourier-staging/bedrock/` (gitignored). OCR ran
  ~18:18–22:53 (~4.5h); ~30s/page scanned. No BM25 (textbook notebooks are
  dense-only).

**Corpus total: 6526 chunks (4475 HTML + 2051 OCR) across 72 paper-segments.**

**Theme:** the Fourier transform as a transformation between locally compact
abelian (LCA) groups (Pontryagin duality, Haar measure, Plancherel), the
representation-theoretic backbone needed to read it, and the modern research
that generalizes it past the abelian case (non-commutative harmonic analysis,
locally compact quantum groups, operator-algebraic duality, hypergroups, and
the live 2021–2026 frontier).

**Verification:** every arXiv ID below was confirmed by fetching its
`arxiv.org/abs/<ID>` page during gathering. No unverified IDs are listed.
`HTML` = ar5iv renders it (prefer for ingest); `PDF-only` = ar5iv conversion
failed (use the PDF/markdown-chunker path). Where the gathering pass could not
re-confirm ar5iv, the entry is marked `HTML?` — re-check at ingest time.

**Corpus-category caveat:** the project's native ingest categories are
`math.AG, math.NT, math-ph, hep-th`. This subject lives mostly in `math.OA /
math.FA / math.RT / math.QA / math.GR`. Ingestion is by arXiv ID (as in the
bridgeland notebook), so this is informational, not a blocker — only the
adelic entries (F8, F9) and the `math-ph` items overlap the native domains.

---

## Section 1 — Foundations: LCA groups, Haar measure, Pontryagin duality, Fourier/Plancherel

| # | arXiv | Title | Authors | Yr | Cat | Fmt |
|---|---|---|---|---|---|---|
| F1 | 2006.10956 | Haar Measures | Tornier | 2020 | math.GR | HTML |
| F2 | 2309.07644 | Haar measure for non-Hausdorff locally compact groups | Valentini | 2023 | math.GR | HTML |
| F3 | 0911.1734 | Continuous and Pontryagin duality of topological groups | Beattie, Butzmann | 2009 | math.GR | HTML |
| F4 | 1911.11718 | Abstract harmonic analysis on locally compact right topological groups | Loliencar | 2019 | math.FA | HTML |
| F5 | 0903.3845 | Harmonic Analysis Lecture Notes | Laugesen | 2009 | math.CA | HTML |
| F6 | 1709.03377 | Notes on Harmonic Analysis Part I: The Fourier Transform | Zhou, Siadat | 2017 | math.CA | HTML? |
| F7 | 1912.07262 | Unitary representations of groups, duals, and characters | Bekka, de la Harpe | 2019 | math.GR | PDF-only |
| F8 | 1803.01964 | Harmonic Analysis on the Adèle Ring of Q | Aguilar-Arteaga, Cruz-López, Estala-Arias | 2018 | math.CA | HTML |
| F9 | 1409.6128 | Gordon's Conjectures: Pontryagin–van Kampen duality and the Fourier transform in hyperfinite setting | Zlatoš | 2014 | math.CA | HTML? |
| F10 | 2308.02078 | Quantum Harmonic Analysis on locally compact abelian groups | Fulsche, Galke | 2023 | math.FA | HTML |
| F11 | 1210.5231 | Completely positive definite functions and Bochner's theorem for locally compact quantum groups | Daws et al. | 2012 | math.OA | HTML? |

**Book gaps (NOT on arXiv — flagged so they're not hunted for as preprints):**
Rudin *Fourier Analysis on Groups*; Folland *A Course in Abstract Harmonic
Analysis*; Hewitt–Ross *Abstract Harmonic Analysis* I–II; Loomis *Abstract
Harmonic Analysis*; Ramakrishnan–Valenza *Fourier Analysis on Number Fields*.
Best arXiv stand-ins: F1 (Haar), F5 (classical Fourier), F7 (duals/characters),
F8 (adelic, ≈ Ramakrishnan–Valenza companion).

## Section 2 — Non-abelian classical harmonic analysis (representation-theory backbone)

| # | arXiv | Title | Authors | Yr | Cat | Fmt |
|---|---|---|---|---|---|---|
| N1 | math-ph/0005032 | An Elementary Introduction to Groups and Representations | Hall | 2000 | math-ph | HTML |
| N2 | math/0311369 | An introduction to harmonic analysis on the infinite symmetric group | Olshanski | 2003 | math.RT | HTML |
| N3 | math/0206041 | Abstract harmonic analysis, homological algebra, and operator spaces | Runde | 2002 | math.FA | HTML |
| N4 | 2401.01446 | Representations of Lie groups | Etingof | 2024 | math.RT | HTML |
| N5 | 0906.4915 | The Orbit Method for Compact Connected Lie Groups | Peter | 2009 | math.RT | HTML |
| N6 | 0809.4942 | Unitary Representations of the inhomogeneous Lorentz Group… (Wigner–Mackey) | Straumann | 2008 | math-ph | HTML |
| N7 | 2003.08519 | Sobolev spaces on Gelfand pairs | Krukowski | 2020 | math.FA | HTML |
| N8 | math/0308259 | Tannaka–Krein duality for compact groupoids I | Amini | 2003 | math.OA | HTML |
| N9 | 1404.5535 | Abstract Harmonic Analysis on the General Linear Group GL(n,R) | El-Hussein | 2014 | math.RT | HTML |
| N10 | 1707.05725 | Topological aspects of group C*-algebras (Fell topology, unitary dual) | Beltiță, Beltiță | 2017 | math.OA | HTML |
| N11 | 2302.13630 | A Peter–Weyl theorem for compact group bundles… | Edeko, Jamneshan, Kreidler | 2023 | math.DS | HTML? |
| N12 | 2603.07105 | A Note on the Peter–Weyl Theorem | Bavuma, Stevenson, Russo | 2026 | math.RT | HTML? |

Also relevant here and listed under §1: **F7** (Bekka–de la Harpe, unitary reps/duals/characters).

**Book gaps:** Harish-Chandra Plancherel papers, Mackey imprimitivity, Kirillov
*Lectures on the Orbit Method* (AMS GSM 64), original Peter–Weyl / Tannaka–Krein.
Substitutes above: N4/N9 (Harish-Chandra direction), N6/F7 (Mackey), N5 (Kirillov), N8/N11/N12 (Peter–Weyl & Tannaka–Krein).

## Section 3 — Modern generalization: quantum groups & operator-algebraic duality

| # | arXiv | Title | Authors | Yr | Cat | Fmt |
|---|---|---|---|---|---|---|
| Q1 | math/0602212 | Locally Compact Quantum Groups. A von Neumann Algebra Approach | Van Daele | 2006 | math.OA | HTML |
| Q2 | math/9902015 | Locally compact quantum groups in the universal setting | Kustermans | 1999 | math.OA | HTML |
| Q3 | math/0309338 | A C*-algebraic framework for quantum groups (MNW) | Masuda, Nakagami, Woronowicz | 2003 | math.QA | HTML |
| Q4 | math/0205284 | The multiplicative unitary as a basis for duality | Maes, Van Daele | 2002 | math.OA | HTML |
| Q5 | 1404.5384 | The Drinfeld double for C*-algebraic quantum groups | Roy | 2014 | math.OA | HTML |
| Q6 | math/9803122 | Notes on Compact Quantum Groups | Maes, Van Daele | 1998 | math.FA | HTML |
| Q7 | 2512.12350 | Discrete quantum groups and their duals | Van Daele | 2025 | math.QA | HTML? |
| Q8 | 1803.05227 | Lecture notes on the co-representation theory of SU_q(2) | Giselsson | 2018 | math.QA | HTML |
| Q11 | 1901.04328 | From Hopf algebras to topological quantum groups | Van Daele | 2019 | math.QA | HTML |
| Q12 | 2507.00900 | Lecture Notes on Operator Algebras and QFT (Tomita–Takesaki) | Verch | 2025 | math-ph | HTML |

## Section 4 — The Fourier transform on quantum groups (on-theme core)

| # | arXiv | Title | Authors | Yr | Cat | Fmt |
|---|---|---|---|---|---|---|
| Q9 | 0708.3055 | Fourier transform on locally compact quantum groups | Kahng | 2007 | math.OA | HTML |
| Q10 | math/0609502 | The Fourier transform in quantum group theory | Van Daele | 2006 | math.RA | HTML |

## Section 5 — Adjacent generalization: hypergroups

| # | arXiv | Title | Authors | Yr | Cat | Fmt |
|---|---|---|---|---|---|---|
| Q13 | 1106.5159 | Integral geometry, hypergroups, and I.M. Gelfand's question | Graev, Litvinov | 2011 | math.FA | HTML |
| Q14 | 1709.01196 | On Fourier algebra of a hypergroup constructed from a conditional expectation… | Kalyuzhnyi, Podkolzin, Chapovsky | 2017 | math.FA | HTML? |

## Section 6 — Recent research frontier (2021–2026)

| # | arXiv | Title | Authors | Yr | Cat | Fmt | Thread |
|---|---|---|---|---|---|---|---|
| R1 | 2305.04894 | The approximation property for locally compact quantum groups | Daws, Krajczok, Voigt | 2023 | math.OA | HTML | LCQG approx. property |
| R2 | 2312.13626 | Averaging multipliers on locally compact quantum groups | Daws, Krajczok, Voigt | 2023 | math.OA | HTML | LCQG multipliers |
| R3 | 2309.10046 | Separation properties for positive-definite functions on LCQG… | Krajczok, Skalski | 2023 | math.OA | HTML | duality/amenability |
| R4 | 2503.23316 | Twisted Fourier transforms on non-Kac compact quantum groups | Youn | 2025 | math.OA | HTML | non-Kac twisted Fourier |
| R5 | 2408.13519 | A Khintchine inequality for central Fourier series on non-Kac CQG | Youn | 2024 | math.OA | HTML | non-Kac twisted Fourier |
| R6 | 2201.08346 | Lp-Lq Fourier multipliers on locally compact quantum groups | Zhang | 2022 | math.OA | HTML | quantum-group multipliers |
| R7 | 2402.17353 | Hörmander type Fourier multiplier theorem… on quantum tori | Ruzhansky, Shaimardan, Tulenov | 2024 | math.FA | HTML | quantum-tori HA |
| R8 | 2312.00657 | Lp–Lq boundedness of Fourier multipliers on quantum Euclidean spaces | Ruzhansky, Shaimardan, Tulenov | 2023 | math.FA | HTML | quantum-tori HA |
| R9 | 2506.18320 | Proper cocycles, measure equivalence and Lp-Fourier multipliers | Wang, Xia, Yao | 2025 | math.FA | HTML | noncommutative Lp |
| R10 | 2206.00549 | Multilinear transference of Fourier and Schur multipliers on NC Lp | Caspers, Krishnaswamy-Usha, Vos | 2022 | math.FA | HTML | Schur/Fourier transference |
| R11 | 2210.08314 | Quantum harmonic analysis on locally compact groups | Halvdansson | 2022 | math.FA | HTML | quantum harmonic analysis |
| R13 | 2405.10910 | Harmonic operators on convolution quantum group algebras | Nemati, Soltani Renani | 2024 | math.OA | HTML | LCQG harmonic operators |
| R14 | 2502.03331 | An overview of dualities in non-commutative harmonic analysis | Kuznetsova | 2025 | math.FA | HTML | **survey / state-of-field** |
| R15 | 2008.12019 | Quantum information theory and Fourier multipliers on quantum groups | Arhancet | 2020 | math.OA | HTML | QIT bridge |
| R16 | 2410.17476 | Non-Abelian Fourier Transforms and Normalized Intertwining Operators… over Finite Fields | Slipper | 2024 | math.RT | HTML? | rep-theoretic Fourier |
| R17 | 2408.00075 | Highly-efficient quantum Fourier transformations for some nonabelian groups | Murairi et al. | 2024 | quant-ph | HTML? | computational QFT |

Also a recent foundation item, listed under §1: **F10** (Fulsche–Galke, QHA on LCA, 2023).

---

## Suggested entry points for a first reader

- **Orientation / survey:** R14 (Kuznetsova 2025, dualities in NCHA) — the single best "where is the field" read.
- **Abelian foundations:** F1 (Haar) → F5 (classical Fourier) → F3 (Pontryagin duality) → F8 (adelic, the canonical self-dual LCA group).
- **Bridge to non-abelian:** N1 (Hall, groups & reps) → Q6 (compact quantum groups) → Q8 (SU_q(2) worked example).
- **The duality completion:** Q4 (multiplicative unitary) → Q1 (Kustermans–Vaes vN approach) → Q9/Q10 (Fourier transform on quantum groups).

## Section 7 — Bedrock sources NOT on arXiv (free-source status, verified 2026-06-15)

These are the foundational books/papers that predate or sit outside arXiv.
Links below were each fetched and confirmed. **All are scanned-image PDFs →
require OCR (MinerU path) before chunking, not the ar5iv-HTML path.**

### Books

| Book | Free status | Source |
|---|---|---|
| Loomis, *An Introduction to Abstract Harmonic Analysis* (1953) | ✅ FULL free PDF/EPUB — **ingestible** | archive.org `introductiontoab031610mbp` + people.math.harvard.edu/~shlomo/212a/loomis.pdf |
| Rudin, *Fourier Analysis on Groups* (1962) | ⚠️ controlled lending only (no bulk download) | archive.org `fourieranalysiso0000rudi` |
| Hewitt–Ross, *Abstract Harmonic Analysis* I & II | ⚠️ controlled lending only | archive.org `abstractharmonic0001edwi` |
| Folland, *A Course in Abstract Harmonic Analysis* | ❌ none (errata only on author page) | paywalled (Routledge) |
| Ramakrishnan–Valenza, *Fourier Analysis on Number Fields* (GTM 186) | ❌ none | paywalled (Springer) |

### Original papers (5 free / legal)

| Paper | Free source |
|---|---|
| Harish-Chandra, *Invariant eigendistributions on a semisimple Lie algebra*, IHÉS 27 (1965) | numdam.org/item/10.1007/BF02684374.pdf |
| Harish-Chandra, *Invariant eigendistributions on a semisimple Lie group*, TAMS 119 (1965) | ams.org/journals/tran/1965-119-03/S0002-9947-1965-0180631-0/...pdf |
| Mackey, *Imprimitivity for reps of locally compact groups I*, PNAS 35 (1949) | pnas.org/doi/pdf/10.1073/pnas.35.9.537 |
| Mackey, *Unitary representations of group extensions I*, Acta Math 99 (1958) | archive.ymsc.tsinghua.edu.cn/pacm_download/117/5878-11511_2006_Article_BF02392428.pdf (3rd-party mirror — judgment call) |
| Kirillov, *Unitary representations of nilpotent Lie groups* (1962) — founding orbit-method paper | mathnet.ru getFT rm/6513 (English translation) |

**Paywalled, no legal free copy found:** Harish-Chandra *Discrete Series* I & II
(Acta 113/116) and *Harmonic Analysis on Real Reductive Groups* I & II
(JFA 19 / Invent. 36); Mackey *Induced Representations I* (Annals 1952, JSTOR).

**Correction to an earlier assumption:** Acta Mathematica back-volumes are NOT
open access via Project Euclid (verified subscriber-only). The Mackey 1958 Acta
paper is free only via the independent Tsinghua YMSC mirror.

---

## Counts

53 unique verified papers (arXiv) + 1 freely-ingestible bedrock book (Loomis)
+ 5 freely-available classic papers. Two appear in two themes each (F7 ↔ §2; F10 ↔ §6)
and are listed once with a cross-reference. ar5iv `HTML` confirmed for the
majority; `HTML?`/`PDF-only` entries to re-check at ingest. Distribution:
math.OA 17, math.FA 13, math.QA 5, math.RT 5, math.GR 4, math.CA 4, math-ph 3,
math.RA 1, math.DS 1, quant-ph 1.

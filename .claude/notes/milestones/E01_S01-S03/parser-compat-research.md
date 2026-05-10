# Parser Compatibility Research: LaTeXML 0.8.8 + texlive 2026 babel.sty

**Date:** 2026-05-06  
**Scope:** LaTeXML/babel incompatibility blocking Tier-0 seed corpus ingestion  

---

## 1. Is there a newer LaTeXML that fixes this?

**Short answer: Yes — 0.8.9 and a pre-release v0.9 both exist, but neither contains
a targeted babel/csname fix.**

### Release landscape (as of 2026-05-06)

| Version | Date | Available via |
|---------|------|---------------|
| 0.8.8 | 2024-02-29 | Homebrew, CPAN, apt, choco |
| 0.8.9 | 2024-Winter (undated) | git HEAD / CPAN (not yet Homebrew) |
| v0.9 (preview) | In progress, CI updated Dec 2025 | git HEAD only |

Sources:
- Tags page: `github.com/brucemiller/LaTeXML/tags` — only v0.8.8 and older
  have formal tags; 0.8.9 exists in `Changes` only.
- Commit `4175d31` (2025-12-04): "updated CI for v0.9 release in 2025."
- CPAN metacpan.org still shows 0.8.8 as the published dist.

### babel in the changelog

The `Changes` file at `github.com/brucemiller/LaTeXML/blob/master/Changes`:
- 0.8.9 entry is two sentences; **no mention of babel**.
- Recent master commits (shallow clone, last 50): zero commits with "babel"
  in the message. The closest is `5082b03` ("kernel upgrades for CI in
  texlive 2025", 2026-03-09), which fixes `\special_relax`, natbib, and
  `\romannumeral` — not babel/csname.

### Issue #2517

Filed 2025-02-18 by alekhe, closed as **duplicate**.  
Error: `Fatal:too_many_errors` from babel 25.1 / LaTeXML 0.8.8.  
The specific `\<` between `\csname...\endcsname` pattern matches exactly the
2025 babel refactor (see `github.com/brucemiller/LaTeXML/issues/2517`).  
The parent issue was not linked in the closed issue, and no fix commit was
found by grepping master.

### Issue #2429

"Greek babel broken on texlive 2023" — closed 2025-09-11, fixed in PR #2634
targeting master. The fix added `\IfFormatAtLeastTF` (a LaTeX3 kernel
guard that newer babel uses). This is **related** but does not cover the
`\<` csname-guard pattern from babel 25.x used by the two failing papers.

**Conclusion:** git HEAD (`github.com/brucemiller/LaTeXML`, master) has
incremental improvements but no targeted fix for the `\< between csname`
error from babel >= 25.0. The error remains unfixed as of 2026-05-06.

**Install path for git HEAD:**
```
git clone https://github.com/brucemiller/LaTeXML.git
cd LaTeXML && perl Makefile.PL && make && sudo make install
```
This is the `brucemiller/LaTeXML` master, not the arXiv fork.

---

## 2. Can we configure LaTeXML to bypass babel?

**Short answer: Not cleanly. The ltxml stub exists but uses `noltxml=>1`,
which is the source of the problem.**

LaTeXML ships `lib/LaTeXML/Package/babel.sty.ltxml` (last modified
2015-02-11, per commit history at
`github.com/brucemiller/LaTeXML/commits/master/lib/LaTeXML/Package/babel.sty.ltxml`).

The stub calls:
```perl
InputDefinitions('babel', type => 'sty', noltxml => 1)
```
`noltxml => 1` tells LaTeXML to load the *raw TeX* babel.sty directly from
the texlive installation — i.e., the *actual* babel 25.x that contains the
incompatible macros. This is why the error appears even though a `.ltxml`
exists.

### `--preload` and `--includestyles`

Per the manual at `math.nist.gov/~BMiller/LaTeXML/manual/commands/latexml.html`:
- `--preload=module` adds optional modules **before** document processing.
  There is no `--nopreload` or package-suppression flag.
- `--includestyles` makes LaTeXML process raw `.sty` files it would
  otherwise ignore. For babel this would be counterproductive (more raw
  babel TeX = more errors).

**There is no documented flag to replace or stub a specific `\usepackage`
call.** The only workaround would be to write a replacement `babel.sty.ltxml`
that stubs all language macros without invoking raw babel — a non-trivial
binding task not present in master.

---

## 3. Docker-pinned LaTeXML + texlive

**Official image from the LaTeXML project:** `latexml/ar5ivist` on Docker Hub
(`hub.docker.com/u/latexml`). This is maintained by Deyan Ginev (arXiv HTML
lead) and is the same pipeline arXiv uses.

| Docker tag | LaTeXML version | TeX Live | Notes |
|------------|----------------|----------|-------|
| `latexml/ar5ivist:2402.29` | 0.8.8 | 2024 | Last stable |
| `latexml/ar5ivist:2509.16` | v0.9 RC | Ubuntu 24.04 (TL 2023) | RC, not final |
| `latexml/ar5ivist:2512.17` | v0.9 preview-3 | Ubuntu 24.04 (TL 2023) | Latest, ~Dec 2025 |

Sources: `github.com/dginev/ar5ivist/releases` and
`hub.docker.com/r/latexml/ar5ivist/tags`.

The `ar5ivist-base` Dockerfile (Ubuntu 24.04) installs TeX Live from Ubuntu
apt (which ships TL **2023**, per `launchpad.net/ubuntu/noble/+package/texlive`),
then installs LaTeXML from a pinned commit of `github.com/arXiv/LaTeXML` —
an arXiv-internal fork distinct from `brucemiller/LaTeXML`.

**Key finding:** Ubuntu 24.04 pins TeX Live 2023 (not 2026). The TL 2023
version of babel predates the 25.x refactor that triggers the `\<` error.
So `latexml/ar5ivist:2512.17` would likely avoid the immediate issue —
not because the LaTeXML babel binding was fixed, but because the pinned
TeX Live is old enough that babel.sty's csname guards aren't present.

**No `ghcr.io/arxiv/latexml` image was found.** Confirmed: there is no
official GitHub Container Registry image from the `arxiv` org. The only
official images are at `hub.docker.com/u/latexml`.

---

## 4. Is ar5iv still the safest path?

**Yes — for paper 2605.03890; not yet for 2605.03835.**

| Paper | `arxiv.org/html/<id>` | `ar5iv.labs.arxiv.org/html/<id>` |
|-------|-----------------------|-----------------------------------|
| 2605.03890 | **200 OK**, full HTML rendered | Redirects (307) to `arxiv.org/abs/` |
| 2605.03835 | **404** | Redirects (307) to `arxiv.org/abs/` |

Notes:
- `arxiv.org/html/2605.03890` loads with "HTML (experimental)" badge. The
  abstract page shows an explicit "HTML (experimental)" link alongside PDF.
- `arxiv.org/html/2605.03835` returns 404. The abstract page for 2605.03835
  shows only PDF + TeX source — no HTML link. ArXiv's LaTeXML conversion
  for this paper either failed or has not run yet.
- `ar5iv.labs.arxiv.org` no longer serves independent content for recent
  papers; it 307-redirects to `arxiv.org/abs/<id>`. The ar5iv site covers
  "up to end of March 2026" according to the ar5iv homepage.

**Correct entrypoint as of mid-2026:** `https://arxiv.org/html/<id>` is the
canonical HTML URL. `ar5iv.labs.arxiv.org` is legacy/redirecting.

**Coverage rate:** ArXiv's info page states ~97% of papers convert, ~3%
totally fail. Paper 2605.03835 is in the failing 3%. Any seed corpus
strategy using `arxiv.org/html/` must handle 404 gracefully.

---

## 5. LaTeXML-friendly smoke-test paper set

**Heuristic:** Pick pre-2024 math.AG papers using `\documentclass{amsart}`,
standard AMS packages only, no babel, no expl3-heavy stacks. Papers from
2019 are safe — babel's csname-guard refactor happened in late 2024/2025.

### Verified candidates

**1904.00179** — Francis Brown, "From the Deligne-Ihara conjecture to
Multiple Modular Values"  
- Category: math.AG + math.NT  
- documentclass: `\documentclass[11pt]{amsart}`  
- Packages: graphicx, amssymb, amsfonts, amsmath, amsthm, color, enumitem,
  fancyhdr, xy — **no babel**  
- Source verified by downloading `/e-print/1904.00179` and grepping

**1904.00175** — Keiji Oguiso and Xun Yu, "Coble's question and complex
dynamics of inertia groups on surfaces"  
- Category: math.AG  
- documentclass: `\documentclass[11pt]{amsart}`  
- **No babel** (verified from source)

**1904.00115** — "Cohomology of Grassmannian / Yoneda product" (raw tex name
`DF_COHOMOLOGY_GR_YONEDA_PROD.tex`)  
- Category: math.AG (April 2019 listing)  
- Single-file gzip; `\documentclass[11pt]{article}` — no babel

Any paper from `arxiv.org/list/math.AG/2019-04` through `2019-12` using
`amsart` is a good bet. Avoid papers with `\usepackage{jheppub}`,
`\usepackage{revtex4}`, or anything citing `\usepackage{babel}` or
`\usepackage{polyglossia}`.

---

## 6. Decision tree: path forward

### Option (a) — Switch to `arxiv.org/html/` first (RECOMMENDED)

Fetch `https://arxiv.org/html/<id>` with a HEAD request. If 200: parse the
pre-rendered HTML directly. If 404: fall back to options below.

**Effort:** ~30 LOC change to the fetcher. This is E02 work pulled forward.  
**Risk:** ~3% miss rate on new papers; 2605.03835 already fails. Need a
fallback for 404s.  
**Why it wins:** arXiv's own LaTeXML pipeline runs on the arXiv fork
(`github.com/arXiv/LaTeXML`) + TeX Live 2023, a combination verified to
handle the current corpus. You get math-faithful MathML with zero local
LaTeXML setup. The Tier-0 "run LaTeXML locally" goal was a means to an end;
ar5iv-first achieves the same corpus quality faster and with maintained
infrastructure.

### Option (b) — Docker-pinned `latexml/ar5ivist:2512.17`

Pin to `latexml/ar5ivist:2512.17` (LaTeXML v0.9 preview + TL 2023).  
**Effort:** Dockerfile + wrapper script, ~1-2 hours to wire up.  
**Risk:** v0.9 is a preview; TL 2023 pins babel pre-25.x so the current
crash is avoided, but the pinned TL drifts from what authors tested against.
The image is 2.3 GB. This solves the local-parse path correctly but adds
infrastructure overhead before you've proven the corpus is worth it.

### Option (c) — Pre-2024 paper subset

Restrict seed list to 50 pre-2024 math.AG papers (suggested IDs above).  
**Effort:** Swap the 50 IDs; run the existing local LaTeXML immediately.  
**Risk:** The seed list no longer reflects current math.AG output. Papers
from JHEP, conference proceedings, or multi-author collaborations
(even pre-2024) may hit other issues. You fix the babel problem but
discover the next problem in the same run.

### Recommendation: **(a)**

Switch the seed corpus fetcher to `arxiv.org/html/<id>` first, with a 404
fallback that logs and skips (not a 4-hour hang). This is a 30-LOC change,
uses the production-grade arXiv LaTeXML pipeline, and is consistent with
the design constitution's parser fallback chain (ar5iv-first was always
Tier-1 in `.claude/notes/04-parsing-and-chunking.md`; pulling it to Tier-0
is the right call given the compatibility evidence). Reserve the local
LaTeXML smoke test for E02 where you can also pin the Docker image properly.

The local LaTeXML path is not dead — use `latexml/ar5ivist:2512.17` when
you return to it — but burning 4 hours on a texlive-2026 + LaTeXML-0.8.8
run against current papers will fail on babel before you learn anything
useful about the rest of the pipeline.

---

## Primary sources cited

- `github.com/brucemiller/LaTeXML/releases` — release history
- `github.com/brucemiller/LaTeXML/tags` — tag list (v0.8.8 is latest tag)
- `github.com/brucemiller/LaTeXML/blob/master/Changes` — 0.8.9 changelog
- `github.com/brucemiller/LaTeXML/issues/2517` — duplicate babel/csname issue
- `github.com/brucemiller/LaTeXML/issues/2429` — greek babel TL2023 fix
- `math.nist.gov/~BMiller/LaTeXML/manual/commands/latexml.html` — CLI manual
- `math.nist.gov/~BMiller/LaTeXML/manual/localization/babel/` — babel section
- `github.com/brucemiller/LaTeXML/commits/master/lib/LaTeXML/Package/babel.sty.ltxml` — stub history
- `hub.docker.com/r/latexml/ar5ivist/tags` — Docker image tags
- `github.com/dginev/ar5ivist/releases` — ar5ivist release notes
- `launchpad.net/ubuntu/noble/+package/texlive` — Ubuntu 24.04 = TL 2023
- `info.arxiv.org/about/accessible_HTML.html` — arxiv HTML coverage
- `arxiv.org/html/2605.03890` — confirmed HTML load (200 OK)
- `arxiv.org/html/2605.03835` — confirmed 404 (no HTML version)

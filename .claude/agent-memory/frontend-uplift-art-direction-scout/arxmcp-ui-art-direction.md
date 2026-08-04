---
name: arxmcp-ui-art-direction
description: arXMCP /ui/ is not Tailwind/shadcn — its generic feel traces to a documented GitHub-Primer palette clone; the 2026q3 run's thesis and recommended direction
metadata:
  type: project
---

The arXMCP `/ui/` operator console has **no Tailwind, no shadcn, no Node, no build chain** (CLAUDE.md
§4.7 forbids them). When it is described as having "the standard tailwind + shadcn feel," the
perception is right and the diagnosis is wrong — the generic read traces to three measurable facts:
a **dark palette that is an explicitly self-documented GitHub-Primer clone** (the in-file comment says
"GitHub-Primer-anchored values"; the values are GitHub's exact ones), **one effective type step**
(h2→body is 1.10x, hierarchy carried by weight alone), and **one container primitive** (`.card`)
doing every structural job.

**Why:** the 2026q3-ui-uplift art-direction pass scored it 6/13 on the frontend-design-language §10
cookie-cutter rubric, with BAN-15 (same-silhouette / borrowed identity) landing on the Primer clone
specifically. The §14 DQS half scored far worse (~1.4 mean vs a 3.0 bar) — the real gap is the
positive half, not the anti-pattern half.

**How to apply:** the run's thesis is "the bench record of a one-person mathematics lab — corpus
before machinery"; the recommended direction is **D-1 "The Ledger Sheet"** (retire `.card`, carry all
structure with a graded hairline rule ladder) because it needs no font file, no new JS, no CSP change,
and no widening of the open UI security audit `chris-dare-dev/arXMCP#9`. Two hard gates any future
visual change must clear: (1) light-mode `--border #d8d8d8` on `--bg #f8f8f8` is only **1.34:1**, so
it cannot become the sole structural device without darkening; (2) any palette change must re-run the
overlay §4 contrast table — the tightest pair (dark `--danger` on `--card-bg`) has 0.66 of headroom
above 4.5:1.

Full frame: `.claude/notes/frontend-uplifts/2026q3-ui-uplift/discover/art-direction-scout-brief.md`.
House thesis it sharpens: `.claude/references/frontend-uplift/arxmcp-design-system.md` §9.

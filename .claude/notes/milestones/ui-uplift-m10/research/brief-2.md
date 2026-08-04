---
milestone_id: "ui-uplift-m10"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://info.arxiv.org/help/api/user-manual.html"
    sha256: "14579fd2abb6d7c1aa0fe01af75754ea283852d4b8f63c3072ae31ebeb04b445"
    takeaway: "The arXiv Atom response carries NO relevance score, rank, weight, or per-entry match explanation in either the atom: or arxiv: namespace; sortBy accepts only relevance | lastUpdatedDate | submittedDate."
  - url: "https://developer.mozilla.org/en-US/docs/Web/CSS/-webkit-line-clamp"
    sha256: "f75fef84430b0a344f02ba03e63045eb482e2607a4341f1697aa15cd72da0380"
    takeaway: "-webkit-line-clamp is deprecated-but-permanently-supported and its three-property co-dependency (display:-webkit-box + -webkit-box-orient:vertical + overflow:hidden) is fully specified in CSS Overflow 4; the page's Baseline banner reflects the unprefixed standard property, not the prefixed form."
  - url: "https://web-platform-dx.github.io/web-features-explorer/features/line-clamp/"
    sha256: "151a7f915d0b6fb4b5f194725f8d775616a096f71949a76ee3e592b4ff64a99e"
    takeaway: "The web-features `line-clamp` entry is Limited availability with every major engine marked unsupported — that verdict is about the UNPREFIXED property; the same entry states the -webkit- prefixed form is widely supported."
  - url: "https://developer.mozilla.org/en-US/docs/Web/CSS/text-wrap-style"
    sha256: "584354a714b61e7e299f363268622e65be3110ef11cd61b03a2368f1d1e87391"
    takeaway: "text-wrap-style (pretty and balance) is Baseline NEWLY available since October 2024 — not Widely Available; pretty additionally carries an MDN-documented performance penalty."
  - url: "https://developer.mozilla.org/en-US/docs/Web/CSS/hanging-punctuation"
    sha256: "9f5212c580c7033c9f5b49ece224ea68d843dd0ae9018818ed5ad89118f95e56"
    takeaway: "hanging-punctuation is NOT Baseline (Limited availability) — Safari-only in practice; unusable under this repo's rule."
  - url: "https://apastyle.apa.org/style-grammar-guidelines/paper-format/reference-list"
    sha256: "8eb1d7c5b3fdbf09293610c34490a1252fe571a00d6e2bf529626db4c9c902f3"
    takeaway: "The canonical reference-list mechanism is a 0.5in HANGING indent — first line flush left, subsequent lines indented — with no extra space between entries; separation comes from the indent, not from rules or gaps."
injection_attempts: 0
---

# Research brief (general) — ui-uplift-m10

Scope: external context + the external-writes list. All repo line references were
read in this worktree snapshot; `app.css` is **498 lines** here.

---

## 0. Two things in the roadmap brief are factually wrong today — read this first

Both are the m7-shaped failure the dispatch asked me to look for, and both are
cheap to walk into.

### 0.1 AC#8's line-cap numbers are stale by a whole revision

The roadmap says: *"app.css grows past the line cap asserted in test_ui_m3/m4/m5
(480 at 2026-08-04, with app.css already at 460)"*.

Measured:

| | Roadmap claims | Actually is |
|---|---|---|
| cap in the three sibling tests | 480 | **520** |
| `app.css` length | 460 | **498** |
| headroom | 20 | **22** |

`ui-uplift-m7`'s **rectify** raised 480 → 520 in lockstep across
`tests/test_ui_m3_dark_and_htmx_feedback.py`,
`tests/test_ui_m4_in_place_add_paper.py:721` and
`tests/test_ui_m5_create_remove_in_place.py:831`. An implementer who follows AC#8
literally and greps for `480` in those files finds nothing to edit, or worse,
edits the wrong number in the surrounding rationale comment. The headroom
conclusion survives (20 ≈ 22) but the instruction does not.

`test_ui_m4_in_place_add_paper.py:700-720` also records that **the split escape
hatch has been spent** — m7 already moved the token blocks to `tokens.css`, so a
future raise "argues for a raise on the merits" and cannot buy room by splitting
again. If m10 needs > 22 lines, that argument is m10's to make, in the commit.

### 0.2 AC#5 is already satisfied verbatim — and the finding behind it is not fixed

AC#5: *"then `.status-badge__remediation` has a CSS rule in app.css"*.

It already does, twice:

- `app.css:222` — `time, code, .status-badge, .status-badge__remediation, dl.meta dd, pre.error, …` (tabular-nums)
- `app.css:245` — `.status-badge__remediation { font-size: var(--text-meta); }`

Consequently the class is **not** in `_KNOWN_UNSTYLED`, which holds **8** entries
(3 `topic-*` + 5 `discover-*`), not the 9 the roadmap summary and the test's own
docstring both still say. `ui-uplift-m7`'s rectify removed it —
`.claude/notes/milestones/ui-uplift-m7/rectify/summary.md:144` records the
self-cleaning list catching it — and that landed after `ui-uplift-m9`'s rectify,
which is why m9's finding M8 (`.../ui-uplift-m9/critique/dedup.md:285-295`) named
four classes and the roadmap inherited that count.

**The trap:** AC#5 as written passes on a `grep`, the coverage test is already
green on it, and an implementer can tick it without doing anything. The *actual*
open defect is discovery finding **H1**
(`discover/current-state-critic-brief.md:54-79`): the remediation `<small>` still
has no `display: block`, so it renders as a **491×22px run-on line** concatenated
onto the pill instead of a caption beneath it. H1's fill-in is `display: block`, a
size step down, a muted colour, and top margin/line-height. Only the size step
shipped. **Treat AC#5 as "close H1", not as "a selector exists".**

### 0.3 The decoy: two other documents define a different UPL-9

`ui-attractive-polish-roadmap.md:495` carries a fully-formed, imperative,
still-unchecked `- [ ] **UPL-9**` that says to replace `filter: brightness(1.08)`
with `color-mix()`. `2026-05-ui-polish/artifacts/final-report.md:59` ranks
"UPL-9 | `color-mix()` derived shades". Both are the **2026-05 run's** numbering
and are unrelated to this milestone. `grep -rn "UPL-9"` surfaces them above the
right one. **This milestone's UPL-9 is the 2026q3 run's** —
`2026q3-ui-uplift/artifacts/{synthesis,challenge,final-report}.md`.

---

## 1. The design-language contract already committed to

**The discovery DID author specific values, and the roadmap dropped every one of
them** — the same shape as m7's dropped `clamp()`. The roadmap says only
"bibliography-style title/meta/abstract hierarchy". The authored anatomy is at
`discover/current-state-critic-brief.md:130-136` (finding H3, "what a credible v1
fill-in looks like"):

```css
.discover-list      { list-style: none; padding: 0 }
.discover-candidate { border-bottom: 1px solid var(--border); padding: 0.75rem 0 }
.discover-title     { font-weight: 600 }
.discover-meta      { color: <muted grey — H4 proposes tokenizing it>;
                      font-family: var(--mono); font-size: 0.8rem }
.discover-abstract  { font-size: 0.875rem; color: var(--fg) }
```

Three notes on carrying it forward rather than pasting it:

1. **The muted grey it depends on was never minted.** `tokens.css` has exactly
   `--fg --bg --card-bg --border --accent --danger --error-bg` plus type/duration
   tokens. There is **no secondary-text token**. Today's muted text is hard-coded
   hex — `.card .hint { color: #555 }` (`app.css:65`), `.card .empty { color: #666 }`
   (`:71`), `#9ba1a8` in the dark block (`:381`) — which is exactly the hand-typed
   value m6 existed to eliminate. Three honest options, pick one deliberately:
   `color-mix(in oklab, var(--fg) 70%, var(--bg))` (the §6 four-step text ladder,
   and the `color-mix(in oklab, …)` idiom already ships at `app.css:132` and `:177`);
   reuse the existing hex for consistency-with-siblings; or mint the token. Option 1
   is the only one that needs no dark-mode counterpart line — relevant at 22 lines
   of headroom.
2. **`0.8rem` / `0.875rem` are pre-m7 raw values.** The type scale now exists:
   `--text-meta: 0.6875rem` (11px), `--text-small: 0.8125rem` (13px),
   `--text-body: 1rem`. Ship tokens, not the sketch's raw rem.
3. **AC#2 is nearly free already.** The meta line emits
   `<code>{pid}</code> · <time>{date}</time>` (`server/routes/notebooks.py:733`), and
   `app.css:200` already gives `code, time { font-family: var(--mono); font-size:
   var(--text-small) }` with `app.css:222` adding `tabular-nums` to both. What is
   *not* covered is the `·` separator and the `<p>` box itself. Setting
   `font-family: var(--mono)` on `.discover-meta` is one line and makes AC#2 true of
   the element rather than only of its children.

**Conflict to record:** the synthesis assigns `[MOT-1 fade-in]` to this candidate
(`synthesis.md:462`, and `:950` lists it in the motion-primitive table). The
challenger overturned that (`challenge.md:596-604`) and the roadmap's AC#3 encodes
the overturn. **AC#3 is right and the synthesis is stale** — verified at source:
`base.html:59` sets `htmx.config.globalViewTransitions` (reduced-motion-gated), and
`app.css:478-481` caps `::view-transition-old/new(root)` at `var(--dur-fast)` =
**200ms**, inside `@media (prefers-reduced-motion: no-preference)`. Do not
resurrect the fade from the synthesis.

---

## 2. D-1 "Ledger Sheet" and the ban list on a results surface

Chosen direction, `final-report.md:52` / `art-direction-scout-brief.md:158-194`:
*"The console is one continuous record of account, not a stack of panels. Rules
carry every structure; the box is deleted."* Current cookie-cutter score **6/13**
(band edge, BLOCKER); challenger-projected end state **2/13**.

Which bans actually bear on a search-results list, and the verdict for each:

| Ban | Bearing on Discover results | Verdict |
|---|---|---|
| **BAN-2** (grid of equal cards) | Up to 10 candidates is precisely where "render each result as a card" takes over | **The single largest threat.** D-1 deletes the box; candidates must be rule-separated rows |
| **BAN-5** (equal weight, no lede) | The current bare `<ul>` *is* BAN-5 — id, date and abstract at identical weight | This is the defect being fixed; the hierarchy is the fix |
| **BAN-7** (badge soup) | `_arxiv_api.Candidate` carries `primary_category`; a category chip or a "NEW" pill per row is one small step away | **Live threat.** BAN-7 is a **per-view** threshold of ~5, not per-row (`challenge.md:377-388`) — 10 candidates × 1 chip is 10 |
| **BAN-3** (icon decoration) | An "Add" icon button, or a status glyph per row | The product has **zero icons today and the synthesis names that as an asset** (§0.4); do not mint the first one here |
| **BAN-14** (uniform density) | A results list is a scan surface and should be authored compact | Choose compact deliberately and say so |
| **BAN-8** (glow/glass) | A hover raise on a candidate row | Hairline is D-1's sole elevation method; `tbody tr:hover` at `app.css:177` is the house precedent — a background tint, not a shadow |

**Direct answer to the dispatch's question about a similar threat here:** yes, and
the discovery flagged both shapes it warns about, in this exact register.
`challenge.md:879` scores tell 7 as *"**0** — **1** if UPL-20 ships as a chip"* —
i.e. one coloured chip anywhere is enough to move the projected score. And
`final-report.md:407` records **UPL-24, the state-history strip, as KILLED** from
the catalog. A Discover row is the most natural home in the whole console for both
(a category chip; a "seen before / new since last run" strip), so this milestone
is where the killed pattern gets accidentally reintroduced.

For the topic classes: `.topic-category` already emits its value inside `<code>`
(`notebooks.py:622`, mirrored at `notebook_detail.html:117`), so it is already an
identifier surface with `--mono` + tabular-nums. Style it as a labelled meta row,
not as a chip — that is both the D-1-coherent and the BAN-7-safe reading.

---

## 3. Bibliography / citation typography as a real discipline

What actual reference lists do, and what transfers to a 10-row scan surface:

- **Hanging indent is the separation mechanism.** APA: *"Apply a 0.5-in. hanging
  indent to the whole reference list, which keeps the first line of each reference
  flush left and indents any subsequent lines 0.5 in."* And explicitly: *"Do not add
  extra space between references."* Separation comes from the indent, not from
  gaps or rules. In CSS this is `padding-left: 2rem; text-indent: -2rem` — two
  properties, universally supported since forever, no Baseline question.
- **The element order is fixed and answers four questions.** APA's basic-principles
  page states the four elements as author, date, title, source — *who, when, what,
  where* — each closed by a period. The discover fragment currently emits title →
  (id · date) → abstract. That is the same skeleton with `who` absent, because
  `DiscoveryCandidate` carries no authors field.
- **Metadata volume.** A reference entry stops at what is needed to *find and
  identify* the work. Everything past that is noise on a scan surface. The
  fragment's three facts (title, id, date) are already at that line — the
  discovery's H3 explicitly wants them *distinguished*, not augmented.
- **Title distinction is by weight/style, not by size.** Reference lists use
  italics or sentence-case-plus-position, not a type-size jump — which is why H3's
  sketch says `font-weight: 600` and nothing about `font-size` on `.discover-title`.
  On a ruled ledger surface, weight is also the D-1-coherent lever.
- **Abstract truncation happens server-side already.** The field is literally named
  `abstract_head` (`tools/_arxiv_api.py:87`) — it is a head, not a full abstract.
  A CSS line-clamp would be truncating twice.

**Recommended anatomy** (hanging indent as the D-1-native, Baseline-free
separator, with a hairline only if rows still read as merged):

```
[flush left]    Title in --text-body, weight 600
[indented]      2604.12345 · 2026-08-01          <- --mono, tabular-nums, muted
[indented]      Abstract head in --text-small, muted-ish
[indented]      [Add]
```

This satisfies AC#1 ("typographically distinguished, candidates separated"),
matches the scholarly register the corpus is in, and reads as a ledger rather than
a card stack. `border-bottom` per H3's sketch also works and is more literally
D-1's rule ladder; the indent is cheaper in lines and needs no `:last-child`
cleanup. Either is defensible — pick one and say why.

---

## 4. Baseline verdicts, plainly

CLAUDE.md's standing bar (the rule m6 used to refuse `light-dark()` and m7 to
refuse `text-wrap: balance`) is **Widely Available or don't ship it**.

| Feature | Baseline status | Date | Verdict for m10 |
|---|---|---|---|
| `line-clamp` (unprefixed) | **Limited availability** — web-features shows every major engine unsupported | — | **DO NOT SHIP** |
| `-webkit-line-clamp` (+ `display:-webkit-box`, `-webkit-box-orient:vertical`) | Not a Baseline feature id of its own; MDN: prefixed form is "widely supported", Chrome 14+/Firefox 68+/Safari 5+, deprecated but the 3-property co-dependency is *fully specified* and "will continue to be supported" | — | **Available, but don't reach for it** — `abstract_head` is already truncated server-side, and it costs 3–4 lines of a 22-line budget for a second truncation |
| `text-wrap: pretty` / `text-wrap-style` | **Newly available** | **October 2024** | **DO NOT SHIP** — same refusal m7 issued for `balance`. MDN also documents a performance cost on `pretty` |
| `text-wrap: balance` | Newly available | October 2024 | **DO NOT SHIP** — already refused by m7; do not re-litigate |
| `hanging-punctuation` | **Limited availability** (not Baseline) — Safari-only in practice | — | **DO NOT SHIP** |
| `:has()` | **Widely Available** | ~June 2026 (Firefox 121 last holdout) — `library-scout-brief.md:76` | Available. Genuinely fresh; no job here needs it |
| `@container` (size) | **Widely Available** | ~Aug 2025 (30-month clock closed) — `library-scout-brief.md:50` | Available. Overkill for a single-column list |
| `text-indent` (negative) / `padding-left` | Universal, pre-Baseline | — | **The hanging indent is free.** Use this |
| `list-style: none` + `padding: 0` | Universal | — | Free |
| `color-mix(in oklab, …)` | Widely Available; already shipping at `app.css:132`, `:177` | — | Use for the muted grey |
| `font-variant-numeric: tabular-nums` | Widely Available; already at `app.css:222` | — | Already applies to `code`/`time` |

**Net:** the entire bibliography anatomy is buildable from properties that predate
the Baseline programme. Nothing in this milestone needs a waiver — which is the
right answer for a milestone whose job is closing debt.

---

## 5. AC#4 — the arXiv Atom driver supplies no relevance basis

**Verdict: AC#4 forbids a relevance line. Do not ship one.** Three independent
confirmations:

1. **The API returns no score.** The arXiv user manual's entry-element list is
   `title`, `id`, `published`, `updated`, `summary`, `author/name`, `link`,
   `category`, plus `arxiv:primary_category`, `arxiv:comment`,
   `arxiv:affiliation`, `arxiv:journal_ref`, `arxiv:doi`. There is **no score, no
   rank, no weight, and no per-result match explanation** anywhere in either
   namespace.
2. **This deployment does not even request relevance ordering.**
   `tools/_arxiv_api.py:156-157` pins `"sortBy": "submittedDate"`,
   `"sortOrder": "descending"`. `sortBy` accepts `relevance`, `lastUpdatedDate`, or
   `submittedDate`; this driver chose the third. The list is **reverse-chronological,
   not ranked** — so even a positional claim ("top match") would be false, and
   `discover_for_notebook.py:12` documents that order as load-bearing for
   determinism.
3. **The dataclass has nowhere to put one.** `DiscoveryCandidate`
   (`tools/discover_for_notebook.py:49-52`) is exactly `paper_id`, `title`,
   `abstract_head`, `submitted_date`. Emitting a reason string would mean
   synthesising it in the fragment builder from nothing.

The one thing that *is* honest and is worth noticing: the query is
`cat:{discovery_category} AND abs:"{description}"`
(`_arxiv_api.py:142-150`, driven from the notebook's own topic fields at
`discover_for_notebook.py:87-94`). So a match basis exists — but it is the
operator's own query, **identical for every candidate in a run**, which makes it
per-candidate meaningless. Rendering it per row would be theatre.

**Constructive alternative, if the panel wants provenance** (offered, not
required by any AC): state the query once at the group level, next to the existing
`"N new candidate(s) — results are not saved"` hint —
*"cat:math.AG AND abs:\"stability conditions\" · newest first"*. That is a
**query disclosure**, not a relevance claim: every byte is something the operator
supplied or the driver pinned, and it makes the reverse-chronological ordering
legible instead of leaving it to be misread as ranking. This is the CLAUDE.md §4.9
posture — say what you measured, don't infer one axis from another. The
NotebookLM pattern the inspiration scout lifted (`P5`,
`inspiration-scout-brief.md:119-143`) ships annotated relevance because
NotebookLM's backend produces it; arXMCP's does not, and copying the *shape*
without the *substrate* is precisely the manufactured evidence §4.9 exists to
prevent.

---

## 6. External writes required

Derived from this repo's CLAUDE.md, not imported:

```yaml
external_writes_required:
  - "git push origin main"
```

That is the complete list. §4.1 lands all work on `main` with no PR, no CI, no
review handoff. The diff is CSS + tests + `_KNOWN_UNSTYLED` bookkeeping: no
package publish, no deploy, no mutating API call, no `pyproject.toml` change (so no
`make wheel-check` gate and no `docker/Dockerfile.server` `COPY` pairing —
`app.css` is already covered by `[tool.setuptools.package-data]`). §4.4 makes the
push **per-event authorized**: a previous "yes, push" does not carry, and the
orchestrator must re-ask at the Phase-4 boundary. Never `--force`, never
`--no-verify`, never `--no-gpg-sign`.

---

## Acceptance criteria the implementer must meet

Traced to the roadmap item's `acceptance` list; 5–7 merged into one closure
criterion to stay inside the seven-item contract.

1. **(roadmap AC1)** A rendered discovery run distinguishes title, meta and
   abstract typographically and separates candidates — via hanging indent
   (`padding-left` + negative `text-indent`) or a `--border` hairline rule, chosen
   deliberately. **Not** as cards (BAN-2), **not** with a per-row chip (BAN-7),
   **not** with an icon (BAN-3 — the product has zero icons and that is an asset).
2. **(roadmap AC2)** `.discover-meta` carries `font-family: var(--mono)` on the
   element itself so the `·` separator joins the data voice; `<code>` and `<time>`
   already inherit `--mono` + `tabular-nums` from `app.css:200` and `:222`. Sizes
   come from `--text-meta`/`--text-small`/`--text-body`, never raw rem.
3. **(roadmap AC3)** No `@keyframes` and no `animation` is added to
   `.discover-list`/`.discover-candidate`. Verified basis:
   `app.css:478-481` caps `::view-transition-old/new(root)` at `var(--dur-fast)`
   = 200ms inside the reduced-motion-gated block, and `base.html:59` enables
   `globalViewTransitions`. Ignore `synthesis.md:462`'s `[MOT-1 fade-in]` — the
   challenger overturned it.
4. **(roadmap AC4)** **No relevance line ships.** The Atom feed carries no score
   or rank, the driver pins `sortBy=submittedDate&sortOrder=descending`, and
   `DiscoveryCandidate` has no field to hold one. If provenance is wanted, a
   **group-level query disclosure** is the only honest form.
5. **(roadmap AC5)** `.status-badge__remediation` is treated as *closing discovery
   finding H1*, not as "a selector exists" — it already has rules at `app.css:222`
   and `:245`. The missing half is `display: block` plus caption spacing so it stops
   rendering as a 491×22px run-on line concatenated onto the pill.
6. **(roadmap AC6 + AC7)** `.topic-block`, `.topic-category` and
   `.topic-description` each gain a real rule, and `_KNOWN_UNSTYLED` in
   `tests/test_ui_class_css_coverage.py` ends **empty** — it holds **8** entries
   today (3 `topic-*` + 5 `discover-*`), not 9. `TestKnownUnstyledDebtIsSelfCleaning`
   fails the moment an entry gains a rule, so entries must be deleted in the same
   commit. Fix the stale "9 classes … 400-line soft cap" docstring at
   `test_ui_class_css_coverage.py:35-37` and the stale comment at `:90` while there.
7. **(roadmap AC8)** If `app.css` exceeds the cap, the raise is argued on the
   merits and applied in lockstep to all three sibling tests. The cap is **520**
   (`test_ui_m3_dark_and_htmx_feedback.py`,
   `test_ui_m4_in_place_add_paper.py:721`, `test_ui_m5_create_remove_in_place.py:831`)
   and `app.css` is at **498** — **not** 480/460 as the roadmap says. m7 already
   spent the tokens-split escape hatch, so splitting is not available as a workaround.

---

## Risks and open questions

1. **Riskiest assumption: 22 lines is enough.** Eight classes plus H1's caption fix
   is ~9–11 rule lines *before* this file's mandatory provenance comments, which run
   3–8 lines per block throughout `app.css` (the m6/m7 discipline that every value
   record which ratio and which ground it was solved for). At 498/520 the budget is
   almost certainly short, and AC#8 already anticipates the raise — but names a
   number that does not exist. **Concrete alternative if the raise is refused:** ship
   the hanging-indent anatomy instead of the `border-bottom` one (no `:last-child`
   cleanup line), use `color-mix(in oklab, var(--fg) 70%, var(--bg))` for the muted
   grey (no dark-mode counterpart line), and group `.topic-category`/`.topic-description`
   into one selector list. That lands the same design in roughly half the lines.
2. **AC#5 is tickable without doing the work.** A `grep` passes, the coverage test is
   already green, and the operator-facing defect stays shipped. Phase 3 should verify
   H1's *rendered* outcome, not the selector's existence.
3. **`.hint` and `.empty` inside the discover fragment are `.card`-scoped.**
   `app.css:65` and `:71` are `.card .hint` / `.card .empty`, and the discover
   fragment emits both. The Ledger Sheet milestone deletes `.card` outright. m10 runs
   first (2026-08-20 vs 2026-09-01) so nothing breaks now, but **do not add new
   `.card`-descendant selectors here** — they are scheduled demolition.
4. **The `topic-*` classes are emitted from two places.** `notebooks.py:621-623`
   (the htmx fragment) and `notebook_detail.html:117` (the Jinja initial render). The
   coverage test only scans `server/routes/`, so only the fragment is gated — but the
   CSS covers both, and the two must not visually diverge after a topic PATCH swap.
5. **Open question — hanging indent vs. hairline rule.** Both satisfy AC#1 and both
   are D-1-defensible (indent is the bibliography-native mechanism and cheaper in
   lines; the rule ladder is more literally D-1's stated device). I have no evidence
   favouring one and the discovery authored the rule version. Whichever ships, the
   commit should say which and why, because the next milestone in the track will
   inherit it as precedent.

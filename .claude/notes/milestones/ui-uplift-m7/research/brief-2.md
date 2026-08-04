---
milestone_id: "ui-uplift-m7"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://api.webstatus.dev/v1/features/min-max-clamp"
    sha256: "f78e537919e954b67a2ff3986f75081b19479554293c93fe618a441a9e38fa40"
    takeaway: "min()/max()/clamp() is Baseline WIDELY available — low 2020-07-28, high 2023-01-28 — so the title clamp() is safe to ship under the repo's Widely-only bar."
  - url: "https://api.webstatus.dev/v1/features/font-variant-caps"
    sha256: "60a37383be3dfdf2f0bcbeafd11f8157d0c332c4434a50ceb17f2d721f0225fd"
    takeaway: "font-variant-caps is Baseline WIDELY available — low 2020-01-15, high 2022-07-15, every engine since Edge 79 — so small-caps is an available alternative to text-transform."
  - url: "https://api.webstatus.dev/v1/features/text-wrap-balance"
    sha256: "c584bd76e63311262bd29c6eb27ca43487a5d294f1e436ab89dd47e152d61ba7"
    takeaway: "text-wrap: balance is Baseline NEWLY available (low 2024-05-13); Widely lands 2026-11-13, which is AFTER this milestone's 2026-08-22 target end — it must not ship in m7."
  - url: "https://api.webstatus.dev/v1/features/text-wrap-pretty"
    sha256: "8237052ab01470f908ef1536b4fed4be64c65f8227855d387383aff01c44c4e1"
    takeaway: "text-wrap: pretty is Baseline LIMITED — Firefox has not shipped it at all (WPT score 0.0 on both channels) — a harder ban than balance."
  - url: "https://www.smashingmagazine.com/2023/11/addressing-accessibility-concerns-fluid-type/"
    sha256: "3098da1cebbe521ff42b9629d4cdfb75d20b458209dda9b88bc17ac9a7394283"
    takeaway: "A vw-only preferred term fails WCAG SC 1.4.4 because browsers do not scale viewport units on zoom; the fix is a non-viewport term in the preferred value plus max <= 2.5x min."
  - url: "https://www.stefanjudis.com/today-i-learned/text-transforms-affects-screen-readers-too/"
    sha256: "435af8b9cb08a1b48d00e287aa760ee2187cefad9fe91fe9566e9eb9e50a0559"
    takeaway: "text-transform: uppercase changes what VoiceOver announces in Chrome — a button reading 'add' becomes 'A.D.D.' — because the transformed string reaches the accessibility tree."
injection_attempts: 0
---

# Research brief (general) — ui-uplift-m7

## External sources

Six sources, all pinned above. Four are `api.webstatus.dev` feature records
(the machine-readable Baseline source behind the MDN Baseline banners); two
are articles. A seventh query — `font-variant-numeric` — was run against the
same API and is reported inline in §2.4 rather than pinned, to stay inside the
six-source budget: it returns `status: "widely"`, `low_date 2020-01-15`,
`high_date 2022-07-15`, i.e. byte-identical Baseline dates to
`font-variant-caps`.

**Note on `www.w3.org`:** per this agent's prior `ui-uplift-m6` lesson, W3C
hosts return HTTP 403 to non-interactive `curl`, so WCAG SC text cannot be
independently hash-pinned. No WCAG quote below depends on a w3.org fetch —
the SC numbers are cited by identifier only, and the substantive claims come
from the two hashed articles plus the hashed Baseline records.

---

## 1. The design-language contract this repo already committed to

### 1.1 Where the roadmap's numbers actually came from

The `11 / 13 / 16 / 20 + clamp` scale and the `+0.06em` tracking are **not**
invented by the roadmap. They trace to the 2026q3 uplift discovery run, and
the chain is intact:

| Artifact | Line | What it says |
|---|---|---|
| `.claude/notes/frontend-uplifts/2026q3-ui-uplift/discover/art-direction-scout-brief.md` | 492-495 | The origin. Full scale + `clamp(1.5rem, 4vw + .5rem, 2.25rem)`; direction **C3 `two-voice-type-scale`** |
| same file | 180 | "Tracked micro-caps column meta — 11px, `letter-spacing: 0.06em`, uppercase, muted: the first authored `letter-spacing`" |
| `.../artifacts/synthesis.md` | 264-290 | UPL-3 promoted **[DIRECTION-DEFINING] [FOUNDATIONAL]**; repeats the scale verbatim |
| `.../artifacts/challenge.md` | 809-810 | Challenger clears it: "0 bytes, both voices system stacks, tokens extend the existing `:root`" |
| `.../artifacts/final-report.md` | 192-197 | Ranked **#1 of the whole catalog** (score 19.5, `S–M`, blockers `NONE`) |

### 1.2 CONFLICT #1 — the roadmap dropped the clamp values

**The roadmap summary says only "title on a clamp." It carries no numbers.**
Every other value in the scale (11/13/16/20, +0.06em) survived into
`plans/ui-uplift/roadmap.yaml:307-309`; the clamp's three terms did not.

The authored value exists in exactly three places, all in the discovery tree,
all identical:

```
clamp(1.5rem, 4vw + .5rem, 2.25rem)      /* = clamp(24px, 4vw + 8px, 36px) */
```

`art-direction-scout-brief.md:493` · `synthesis.md:270` · `final-report.md:193`

**Implementer consequence:** do not invent a clamp. Read it from the discovery
artifact. Roadmap AC#3 only constrains it negatively ("scales via `clamp()`
rather than staying fixed at 32px"), so an invented value would pass the AC
while silently discarding the authored art direction.

### 1.3 CONFLICT #2 — the clamp minimum sits below the canon's own title floor

The current-state critic records the canon's stated ranges
(`synthesis.md:282`): **meta 11-12 · body 14-16 · section 20-24 · title
28-40**. Checking the chosen values against those ranges:

| Role | Canon range | Chosen | Verdict |
|---|---|---|---|
| meta | 11-12 | 11 | in range (floor) |
| body | 14-16 | 16 | in range (ceiling) |
| section | 20-24 | 20 | in range (floor) |
| title | 28-40 | **24 → 36** | **min is 4px BELOW the canon floor**; max is inside |

At a 390px viewport the title renders at the clamp minimum, **24px — below the
canon's 28px title floor.** This is a real discrepancy, not a rounding
artifact. It is defensible (the canon range plausibly describes the desktop
title, and 24px on a 390px screen is a reasonable mobile size), but it is
undeclared, and Phase 3 will find it. Either raise the min to `1.75rem`
(28px) or record the deviation explicitly in the CSS rationale comment. See
Risk R3.

### 1.4 No ratio, no modular scale — the values are hand-picked

Direct answer to the question: **no discovery artifact specifies a ratio or a
modular scale.** `grep -rn "modular\|ratio"` across the 2026q3 discovery tree
returns nothing typographic. The scale is a set of hand-picked round numbers
that *approximate* a 1.2 (minor-third) ramp without being one:

```
11 → 13 → 16 → 20      steps: 1.182x, 1.231x, 1.250x     (a true 1.2 scale from 11 would be 11 → 13.2 → 15.84 → 19.0)
```

Do not "regularise" these into a computed scale. They are round px values
chosen for crisp rendering on a system stack; a generated 1.2 ramp would
produce 13.2px/15.84px and lose exactly that property.

### 1.5 The one thing the discovery attached to UPL-3 that must NOT ship

`final-report.md:492` lists, in the "native platform API" table, the row:

| `text-wrap: balance` | headline-balancing JS | Newly Available → Widely 2026-11-13 | **UPL-3** |

`text-wrap: balance` is attached to **this milestone**. It is Baseline
**Newly**, not Widely (pinned source #3: `low_date 2024-05-13`; Widely =
low + 30 months = **2026-11-13**, which is after the 2026-08-22 target end).
Under the same rule `ui-uplift-m6` used to refuse `light-dark()`, it is
**barred from m7**. See §2.5.

---

## 2. Current best practice for a system-font two-voice scale (2026)

### 2.1 `clamp()` for fluid type — the accessibility trap and the exact form

**The trap is real and the mechanism is precise.** Per pinned source #5:

> "Unlike `rem` and `px` values, browsers do not scale viewport-based units
> when zooming the page."

So a `clamp()` whose preferred term is *only* `vw` produces text that does not
grow at all under page zoom — the article notes such text "could potentially
fail to scale to two times their original size ... even at 500%." That is a
WCAG SC 1.4.4 (Resize Text, AA) failure.

**Two distinct hazards, commonly conflated — keep them separate:**

1. **Page zoom** (Cmd/Ctrl-+). Zoom halves the CSS-px viewport, so `vw` shrinks
   in CSS px and cancels the zoom. Fixed by having a **non-viewport term in the
   preferred value** and by bounding the max/min ratio.
2. **User default font size / text-only zoom.** `vw` *and* `px` both ignore
   this entirely; only `rem`/`em` respond. Fixed by making the min, the max,
   **and** the non-viewport term of the preferred value all `rem`.

Source #5's own examples satisfy (1) with `px + vw`
(`clamp(16px, 5.33px + 3.33vw, 48px)`) and therefore do **not** satisfy (2).
Use `rem` throughout — that is the stricter and correct choice.

**The numeric rule.** Source #5 states it plainly:

> "The maximum value must be less than or equal to 2.5 times the minimum
> value."

**Verdict on the authored value — it already passes both.**

```css
font-size: clamp(1.5rem, 4vw + 0.5rem, 2.25rem);
```

- min `1.5rem` and max `2.25rem` are `rem` → hazard (2) covered.
- preferred carries a `0.5rem` term alongside the `4vw` → hazard (1) covered.
- max/min = `2.25 / 1.5` = **1.5x**, comfortably inside the 2.5x ceiling.

**Ship the authored value unchanged.** Recommended form, for the record:

```css
/* min and max in rem; preferred = rem term + vw term, never vw alone. */
h1 { font-size: clamp(1.5rem, 4vw + 0.5rem, 2.25rem); }
```

Two mechanical notes: the arithmetic needs **no `calc()`** — `min()`/`max()`/
`clamp()` arguments are themselves math expressions per CSS Values 4 (pinned
source #1 links `drafts.csswg.org/css-values-4/#comp-func`). And the ramp is
narrow: solving `0.04W + 8` against the bounds, the title is pinned at 24px
below **W = 400px** and pinned at 36px above **W = 700px**, so it is fully
maxed on every desktop viewport. That is a characterisation, not a defect.

### 2.2 Uppercase + letter-spacing — what is actually safe

**`text-transform: uppercase` changes what a screen reader says.** Pinned
source #6 is a direct observation:

> "VoiceOver treats the button differently depending on the `text-transform`
> property. It reads out loud 'add' and 'A.D.D.' for the uppercase version."

The mechanism is that the *transformed* string reaches the accessibility tree,
so a short uppercase word is re-interpreted as an initialism and spelled out.
This is a Chrome + VoiceOver interaction, not universal — but arXMCP is
operated from a Mac (`darwin`), so it is the live configuration, not a
theoretical one.

**`font-variant-caps` does not have this failure mode.** The CSSWG discussion
of `text-transform`'s design (issue #3775) records that font-variant styles
"do not get exposed the same way in the accessibility tree" — because
`font-variant-caps` is a *rendering* instruction over unchanged text, whereas
`text-transform` rewrites the string. The DOM text stays lowercase, so the AT
announces the real word.

**Recommendation, in order of safety:**

1. **Best — `font-variant-caps: all-small-caps`** on labels authored in normal
   case. AT-safe, Baseline **Widely** since 2022-07-15 (pinned source #2).
   Caveat: no system UI font in this repo's stack ships true small-cap glyphs,
   so browsers **synthesize** them by scaling capitals; the result is lighter
   and slightly shorter than true caps, and differs between SF Pro and Segoe
   UI. Visually this is *not* the same as the art direction's "micro-caps."
2. **Acceptable — `text-transform: uppercase`**, which is what the art
   direction literally specifies, provided the label text is a real word the
   AT can pronounce and is not a 2-4 letter token. arXMCP's meta labels are
   words (`CREATED`, `PAPERS`, `STATUS`, `SLUG`) — the risk concentrates on
   short ones like `ID`.
3. **Never** hard-code capitals in the Jinja2 template. That makes the
   initialism reading unconditional across every AT and removes the CSS escape
   hatch.

**The 11px size is the sharper legibility concern, independent of AT.**
All-caps removes ascender/descender word-shape cues, which is precisely why the
art direction pairs it with positive tracking — `+0.06em` at 11px is `0.66px`,
the standard and correct mitigation. Keep the two together: 11px uppercase
*without* the tracking would be worse than either alone.

**On WCAG SC 1.4.12 (Text Spacing):** authoring `0.06em` is not itself capped —
1.4.12 governs whether content survives a *user* forcing `0.12em`. The one
place in this stylesheet where that could bite is `.status-badge { min-width:
14ch }` (`app.css:219`) — but it is a `min-width`, so the pill grows rather
than clipping. No action needed; noted so Phase 3 does not re-derive it.

### 2.3 `font-variant-numeric: tabular-nums` — where it belongs

It belongs on **any surface whose digits change in place**, so columns do not
jitter on swap. The repo already reasoned this out correctly at
`app.css:183-191`, and its comment is worth preserving:

> "The OpenType tnum feature is shipped by every system-ui font in the body
> stack (SF Pro, Segoe UI, Noto Sans), so the high-level CSS property
> suffices — no font-feature-settings fallback needed."

The existing scope is `time, .status-badge, dl.meta dd, td code`. AC#2 requires
identifier surfaces to *inherit* this scope, which means **extending this one
rule's selector list, not writing a second `tabular-nums` declaration.** See
Risk R2 for the test that makes this trickier than it looks.

### 2.4 Baseline verdicts — plainly, which ship and which do not

Every value below is from a hashed `api.webstatus.dev` record, read today
(2026-08-04).

| Feature | Baseline | Low / High date | **Ship in m7?** |
|---|---|---|---|
| `min()`/`max()`/`clamp()` | **widely** | 2020-07-28 / 2023-01-28 | **YES** — already used at `app.css:69` |
| `font-variant-caps` | **widely** | 2020-01-15 / 2022-07-15 | **YES** |
| `font-variant-numeric` | **widely** | 2020-01-15 / 2022-07-15 | **YES** — already used at `app.css:190` |
| `letter-spacing` | pre-Baseline (CSS1) | — | **YES** |
| `text-wrap: balance` | **newly** | 2024-05-13 / *2026-11-13* | **NO** — Widely lands after this milestone ends |
| `text-wrap: pretty` | **limited** | — | **NO** — Firefox has not shipped it (WPT 0.0) |

### 2.5 The `text-wrap: balance` decision, stated for the record

`final-report.md:492` attaches `text-wrap: balance` to UPL-3, so an implementer
reading the discovery output will reach for it. It must be refused:

- Baseline **Newly**, `low_date 2024-05-13`. Widely = **2026-11-13**.
- Today is **2026-08-04**; the milestone's target end is **2026-08-22**. It is
  Newly for the entire milestone window and for ~3 months after.
- This is the identical basis on which `ui-uplift-m6` refused `light-dark()` —
  and `app.css:29-32` already carries that refusal in a rationale comment.

The failure mode is benign (unsupporting engines just wrap normally), which is
*why* it is tempting. Refuse it anyway and say so in a comment, consistent with
m6. `text-wrap: pretty` is a harder no: Baseline **limited**, Firefox absent.

---

## 3. The 16px body claim — does it silently rescale the console?

### Short answer: **No. It changes nothing — because body already computes to 16px.**

This was worth checking and the check is conclusive.

**There is no `font-size` declaration on `html`, `:root`, or `body` anywhere in
the product.** All 14 `font-size` declarations in `app.css` are on descendant
selectors (`header .subtitle`, `.card h2`, `.card .hint`, `label`,
`input[...]`, `select, textarea`, `button`, `th, td`, `table code`,
`pre.error`, `.status-badge`, `.card .note`, `.card .display-name`,
`.breadcrumb`). `app.css` is the only stylesheet in the product
(`server/frontend/static/` contains it and the vendored `htmx.min.js`; the
three Jinja2 templates carry no `<style>` block).

Therefore:

1. **Body's computed font-size is the UA default `medium` = 16px.** The
   discovery's own live measurement agrees: `visual-manifest.md:54-66` records
   body at 16px and the h2/body step at 1.10x.
2. **`rem` resolves against the root element (`html`), not `body`.** Nothing
   `body { font-size: … }` can do reaches a single `rem` declaration in this
   file. This is the crux — the feared "silent whole-console rescale" is
   mechanically impossible for `rem`, and this stylesheet is 100% `rem`.
3. **The `em` values are all scoped to their own element**, not to body:
   `pre.error { min-height: 1.2em }` (resolves against `pre.error`'s own
   `0.8rem`), and the spinner `::after`'s `0.8em/0.8em/0.5em` (resolves against
   the button's `0.875rem`). Body is not in either chain's font-size
   inheritance for those computations.
4. **The one thing that *does* inherit from body is UA-default heading sizing.**
   `h1` has no CSS rule, so it renders at the UA's `2em` — `2 × 16px = 32px`,
   which is exactly the "fixed at 32px" that AC#3 names. `.card h2` overrides
   to `1.1rem` (17.6px), which is exactly the measured 1.10x step AC#1 names.
   Since body is *already* 16px, declaring 16px leaves these untouched too.

**So the correct framing for the implementer: "body 16px" in the roadmap
summary is DESCRIPTIVE, not a change.** It names the size the token must
codify, not a migration to perform. The token is a no-op on rendering and
should be added anyway, so the scale is complete and `:root`-resident per AC#4.

### The one way to get this wrong

**Write it as `1rem`, never as `16px`.**

`--text-body: 16px` would be numerically identical today *and* would override
the user's browser font-size preference — converting a currently-compliant
surface into a WCAG SC 1.4.4 problem, in the same milestone that fixes the
title's zoom behaviour. The same applies to the whole scale. Express every
size in `rem`:

```css
--text-meta:    0.6875rem;   /* 11px @ default root */
--text-small:   0.8125rem;   /* 13px */
--text-body:    1rem;        /* 16px — matches today's computed value exactly */
--text-section: 1.25rem;     /* 20px */
--text-title:   clamp(1.5rem, 4vw + 0.5rem, 2.25rem);
--tracking-meta: 0.06em;
```

These render byte-identically to the px values at default settings and scale
correctly when the user changes their default. Note `0.06em` is correctly `em`
(not `rem`) — tracking must scale with *its own* element's size, which is the
whole point at 11px.

---

## 4. `external_writes_required`

```yaml
external_writes_required:
  - "git push origin main"
```

Derivation, from **this** repo's `CLAUDE.md` (not imported from elsewhere):

- §4.1 — "All work lands on `main` directly. No feature branches, no pull
  requests." So the branch is `main`, and there is no PR-creation write.
- §4.4 — "**Push is per-event authorization.** A user 'yes, push' once does NOT
  authorize future pushes. Re-ask each time." The push is therefore a Phase-4
  gate the orchestrator must put to the user for *this* milestone specifically,
  even if a push was approved earlier in the same session.
- §4.1 — "No CI / GitHub Actions blocking merges" → no CI-triggered external
  effect follows the push.

**Nothing else.** This milestone edits one CSS file, at most three Jinja2
templates, and test files. It publishes no package (no `pyproject.toml`
change → no `make wheel-check-full`, no release), deploys nothing, calls no
mutating API, and touches no `var/` corpus state. `git push origin main` is
the complete list.

---

## Acceptance criteria the implementer must meet

1. **The h2-to-body step is no longer 1.10x, and size (not weight alone)
   carries hierarchy.** `.card h2` moves from `1.1rem` (17.6px) to the section
   token `1.25rem` (20px), giving a **1.25x** step against the 16px body.
   *(roadmap AC#1)*
2. **Every identifier surface uses `--mono` and is inside the existing
   `tabular-nums` rule.** Today `--mono` reaches `<code>` **only inside
   tables** (`app.css:167 table code`), so the slug in
   `notebook_detail.html:9`, the LanceDB **path** at `:49`, the discovery
   category at `:110`, and the prose paths in `base.html:64,81` all render in
   the *browser default* monospace, not `--mono`. `<time>` is in the
   `tabular-nums` rule but is **not** `--mono` at all. Both gaps must close,
   and the `tabular-nums` scope must be extended **in place** — one rule, not a
   second declaration. *(roadmap AC#2)*
3. **At 390px the page title scales via `clamp()`.** Ship the authored
   `clamp(1.5rem, 4vw + 0.5rem, 2.25rem)` from the discovery artifact (§1.2) —
   not an invented value. It renders 24px at 390px, replacing today's fixed
   32px UA `2em`. Verified compliant against SC 1.4.4 in §2.1. *(roadmap AC#3)*
4. **All type tokens extend the existing `:root` at `app.css:4-51`; no second
   token set.** Sizes in `rem`, tracking in `em` (§3). *(roadmap AC#4)*
5. **The tracked micro-caps label uses CSS, not template capitals**, and pairs
   `+0.06em` tracking with the 11px size in the same rule (§2.2). If
   `text-transform: uppercase` is chosen over `font-variant-caps`, the choice
   and its VoiceOver trade-off must be stated in the rationale comment.
6. **No `text-wrap: balance` and no `text-wrap: pretty`**, despite
   `final-report.md:492` attaching `balance` to UPL-3 — Newly and Limited
   respectively (§2.4-2.5). Record the refusal in a comment, matching the
   `light-dark()` refusal already at `app.css:29-32`.
7. **The 480-line `app.css` cap is respected, or raised in all three test files
   in one commit.** The file is at **471 of 480 lines** — a 9-line budget (see
   Risk R1).

## Risks and open questions

**R1 — The line budget is the binding constraint, and it is nearly exhausted.**
`app.css` is **471 lines against a hard 480-line cap** asserted in *three*
separate test files — `tests/test_ui_m3_dark_and_htmx_feedback.py:571`,
`tests/test_ui_m4_in_place_add_paper.py:695`,
`tests/test_ui_m5_create_remove_in_place.py:816` — each of which says the three
"MUST move in lockstep." Nine lines cannot hold 6 tokens + a `code, time`
`--mono` rule + a title clamp + a meta-label rule + the derivation comment that
m6 established as the deliverable ("a bare `oklch()` triple with no target is
exactly the un-rederivable hand-typed value m6 exists to eliminate").
**Expect to raise the cap to ~520-540 and edit all three files in the same
commit.** The m3 test's own message names the alternative escape hatch:
splitting into `tokens.css + app.css`. That is a larger change than m7 should
carry — recommend the lockstep cap raise.

**R2 — The `tabular-nums` test reads a fixed 300-character window and will
break silently on a longer selector list.**
`tests/test_ui_m2_polish.py:110-116` locates
`font-variant-numeric: tabular-nums`, then slices `APP_CSS[idx-300 : idx]` and
requires `time`, `.status-badge`, `dl.meta dd`, `td code` all to appear in it.
The rule's preceding comment is already ~430 chars, so the window today
captures only the comment's tail plus the selector list. AC#2 requires adding
identifier selectors to exactly this list — and any selector pushed further
than 300 chars back from the declaration **drops out of the window and fails an
assertion that has nothing to do with the change**. Mitigation: append new
selectors *after* the four pinned ones, keep the total selector text short, and
re-run `tests/test_ui_m2_polish.py` specifically. Do not "fix" this by
splitting into a second `tabular-nums` declaration — that violates AC#2's
"inherits the existing scope."

**R3 — Open question: the clamp minimum is below the canon's title floor.**
24px at 390px vs the canon's stated 28-40 title range (§1.3). Not resolvable
from the artifacts — the canon range appears to describe the desktop title and
predates the clamp. Recommend shipping the authored `1.5rem` min and recording
the deviation in the rationale comment; the alternative (`1.75rem` = 28px min)
narrows the fluid ramp to 400-700px → 28-36px, a 1.29x range that barely
justifies a clamp at all.

**R4 — `font-variant-caps: all-small-caps` will not look like the art
direction.** No font in `-apple-system, system-ui, BlinkMacSystemFont,
"Segoe UI", Helvetica, Arial` ships true small-cap glyphs, so browsers
synthesize them by scaling capitals — lighter, shorter, and inconsistent
between macOS and Windows. The AT-safe option and the visually-faithful option
are genuinely different here; this is a judgement call the implementer must
make explicitly rather than discover.

**R5 — Riskiest assumption + the alternative path.** The riskiest assumption in
this brief is **R1's**: that the cap can simply be raised. If Phase 3 rules the
cap sacred, m7 cannot ship its rationale comments, and a scale shipped without
recorded derivation is exactly the hand-typed-values anti-pattern m6 was run to
eliminate — it would be a regression in kind while passing every AC.
**Concrete alternative:** extract the `:root` token block (currently
`app.css:4-51`, 48 lines, already the largest single block) into
`server/frontend/static/tokens.css`, linked ahead of `app.css` in `base.html`.
This is the escape hatch the m3 cap test explicitly names, it drops `app.css`
to ~423 lines and restores real headroom for m8's rule ladder, and it gives the
type + colour tokens one home — directly serving AC#4's "do not parallel-define
a second token set." **The packaging half of this is already free — verified,
not assumed:** `pyproject.toml:76` declares
`"server.frontend.static" = ["*.css", "*.js", "*.svg", "*.md"]`, so a new
`tokens.css` is matched by the existing glob, and `docker/Dockerfile.server`
copies the tree wholesale via `COPY server/ ./server/` (lines 62 and 140) with
an explicit comment that console assets "need no COPY of their own." So
CLAUDE.md §4.5b's two pairing rules are **already satisfied** — no
`pyproject.toml` edit, no `Dockerfile` edit. **Remaining costs:** one extra
`<link>` in `base.html`, a second HTTP request on the loopback console
(negligible), and updating the `APP_CSS` fixture in the ~7 test modules that
read the file — that last item is the real cost, and it is why the lockstep
cap raise is still the cheaper path. Take the split only if the raise is
refused.

---

## Prompt-injection report

`injection_attempts: 0`.

Six web sources were fetched. None contained text directed at the agent, no
instruction-shaped content appeared in any fetched page, and no fetched
content was treated as authorization for any action. All web content above is
recorded as data. The one adversarial-shaped thing encountered was internal,
not external, and is not an injection: `final-report.md:492` recommends a
feature (`text-wrap: balance`) that the repo's own Baseline rule forbids —
handled in §2.5 by refusing it, not by deferring to the document.

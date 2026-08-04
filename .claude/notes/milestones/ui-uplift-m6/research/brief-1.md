---
milestone_id: "ui-uplift-m6"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — ui-uplift-m6

## 1. `app.css` token system (read end-to-end, 398 lines)

**File:** `server/frontend/static/app.css`. **Current length: 398 lines** (confirmed via both
`wc -l` and the test suite's own counting formula — `text.count("\n") + (0 if endswith "\n" else 1)`).
Cap is 400 (see §6). **Only 2 lines of headroom.**

**The 8 `:root` tokens** (`app.css:4-19`), plus `color-scheme` which is explicitly NOT a token:

```
10  color-scheme: light dark;   <- load-bearing (AC #6), NOT re-derived, do not touch
11  --fg: #1a1a1a;
12  --bg: #f8f8f8;
13  --card-bg: #fff;
14  --border: #d8d8d8;
15  --accent: #1e5b8a;
16  --danger: #a3271a;
17  --error-bg: #fff4f2;
18  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
```

**Dark redeclaration** at `app.css:267-280` (`@media (prefers-color-scheme: dark) { :root { … } }`):
7 of 8 tokens re-declared (`--mono` stays — it's a font stack, not a color):
`--fg:#e8e8e8 --bg:#0d1117 --card-bg:#161b22 --border:#6e7681 --accent:#58a6ff --danger:#f85149 --error-bg:#2a1a18`.
The comment at `:270` literally says `/* Primer canvas.default */` and `:276` says `/* Primer accent.fg */` —
this is the "self-documented GitHub-Primer clone" the roadmap brief refers to; it is the strongest
in-repo evidence for AC #1 ("no value is a GitHub Primer literal").

## 2. Full hardcoded-literal inventory (bypasses the token system)

Every occurrence below is a color literal NOT expressed as `var(--token)`. Grep pattern used:
`#[0-9a-fA-F]{3,6}` across the whole file, then classified by hand against the `:root` blocks.

### Light mode (undecorated selectors)

| Line | Selector | Literal | Renders on |
|---|---|---|---|
| 45 | `header .subtitle` | `color: #555` | `--bg` (header is not inside `.card`) |
| 47 | `footer` | `color: #666` | `--bg` |
| 48 | `footer a` | `color: #666` | `--bg` |
| 62 | `.card .hint` | `color: #555` | `--card-bg` |
| 65 | `.card .note` | `color: #6f6f6f` | `--card-bg` (UPL-27-fixed 2026-08-03, was `#777`) |
| 66 | `.card .empty` | `color: #666` | `--card-bg` |
| 67 | `.card .display-name` | `color: #444` | `--card-bg` |
| 84 | `input[type=text\|url\|file]` | `background: #fff` | text is inherited `var(--fg)` (no `color:` on this rule) |
| 101 | `textarea` | `background: #fff` | same — inherited `var(--fg)` text |
| 108 | `button, .button` | `color: #fff` | `var(--accent)` (background, same rule) — **accent role #1** |
| 127 | `dl.meta dt` | `color: #555` | `--card-bg` |
| 132 | `th` | `background: #f0f0f0` | text is inherited `var(--fg)`; the background itself sits on `--card-bg` at only **1.14:1** (design-overlay §4 note) — a non-text/UI-boundary contrast, not a text pair |
| 190-192 | `.status-badge--{ok,warn,ops-warn}` | 3 full `{bg,color,border-color}` literal triples | self-contained (bg = ground) |
| 218 | `.skip-link:focus-visible` | `color: #fff` | `var(--accent)` (background, same rule) — **accent role #4** |

Note `.status-badge--down` (`:193`) already uses `var(--error-bg)` / `var(--danger)` — it is NOT a
literal. So light mode has **3** literal pill triples, not 4.

### Dark mode (`@media (prefers-color-scheme: dark)` block)

| Line | Selector | Literal | Renders on |
|---|---|---|---|
| 285 | `button, .button` | `color: #0d1117` | `var(--accent)` dark — the hand-patched compensation (see §4) |
| 298-299 | `header .subtitle, footer, footer a, .card .hint, dl.meta dt` | `color: #b3b9c0` | **splits into 2 distinct pairs**: on `--bg` dark (header/footer/footer a) and on `--card-bg` dark (.card .hint, dl.meta dt) — the single declaration must not be treated as one pair |
| 300 | `.card .note, .card .empty` | `color: #9ba1a8` | `--card-bg` dark |
| 301 | `.card .display-name` | `color: #c9d1d9` | `--card-bg` dark |
| 314-317 | `.status-badge--{ok,warn,ops-warn,down}` | 4 full triples | self-contained |
| 318 | `th` | `background: #161b22` | equals `--card-bg` dark's value numerically, but is a literal, not `var(--card-bg)` |

Dark mode has **4** literal pill triples (unlike light mode, `--down` is ALSO hardcoded here:
`background:#3d1216` — and that value is **NOT** equal to `--error-bg` dark `#2a1a18`, even though
`color`/`border-color` `#f85149` does equal `--danger` dark. So the dark "down" pill's background
has already silently diverged from its own token — pre-existing, not introduced by this milestone.)

**Total non-token color declarations: 13 light-mode lines + 5 dark-mode lines = 18 declaration
sites** (some cover multiple selectors). The brief's "~12 greys plus 8 status-pill values" undercounts
slightly once `#fff` (inputs/textarea/button/skip-link) and `th`'s background are folded in — use
this table as the ground truth, not the approximate figure.

### Outside `app.css` entirely

`server/frontend/static/favicon.svg:2` hardcodes `fill="#1e5b8a"` — **the exact current light
`--accent` value**. SVG favicons render in browser-tab chrome and do NOT inherit page CSS custom
properties (confirmed by this repo's own comment at `base.html:11-13`: *"the fill color is hardcoded
#1e5b8a (matching --accent) because favicons render in browser-tab context and don't inherit page
CSS variables"*). **If light `--accent` is re-derived away from `#1e5b8a`, the favicon silently goes
stale** — not referenced anywhere in the roadmap item's `links.code` list (which cites only `app.css`
lines). No other file in `server/frontend/static/` (`htmx.min.js`, `json-enc.js`, `VENDORED.md`)
carries a color literal. Grepped every Jinja2 template and every HTML-fragment builder in
`server/routes/{ui,notebooks}.py` for `style=` attributes and hex literals — **zero hits**; all
color comes from CSS classes, confirming app.css is the single source of truth for anything CSS-side.

## 3. Duration literals

Four sites, three distinct values, ALL hardcoded (no duration tokens exist anywhere today):

| Line | Rule | Value | Gate |
|---|---|---|---|
| 358 | `@keyframes spin` consumer: `animation: spin 0.6s linear infinite;` (button in-flight spinner) | `0.6s` (600ms) | `prefers-reduced-motion: no-preference` |
| 374 | `.status-badge.htmx-settling { animation: badge-flash 400ms ease-out; }` | `400ms` | same |
| 382 | `::view-transition-old(root), ::view-transition-new(root) { animation-duration: 200ms; }` | `200ms` | same |
| 392 | `tr.htmx-swapping { animation: row-fade-out 200ms ease-out forwards; }` | `200ms` | same — **MUST stay numerically in sync** with `index.html:110`'s `hx-swap="outerHTML swap:200ms"` modifier (a comment at `:389-390` states this explicitly) |

All four already live inside the `@media (prefers-reduced-motion: no-preference)` block, so the
reduced-motion gate itself is not at risk from this milestone — only the literal-vs-token question is.

## 4. `--accent`'s five roles — exact sites

1. **Button ground** — `button, .button { background: var(--accent); ... color: #fff; }`
   (`:103-114`, bg at `:107`, text at `:108`) + dark override `button, .button { color: #0d1117; }`
   (`:285`). The hover state `color-mix(in oklab, var(--accent) 88%, white)` (`:122`) is token-driven
   and needs no separate literal fix.
2. **Focus ring** — `outline: 2px solid var(--accent);` (`:234`), applied to
   `button/.button/input/a/select/textarea/[tabindex]:focus-visible`. Confirmed BOTH grounds are
   genuinely exercised by real rendered elements, not hypothetically: `header h1 a`,
   `footer a[href=/healthz]`, `footer a[href=/readyz]` render on `--bg` (outside any `.card`);
   every form `button`/`input`/`select`/`textarea` renders on `--card-bg` (inside a `.card` section).
   `button.danger:focus-visible { outline-color: var(--danger); outline-offset: 3px; }` (`:238`) is
   the sibling danger-ring rule — not one of the 5 named accent roles, but the SAME vs-both-grounds
   constraint applies to `--danger` and is worth carrying into the same table.
3. **Link colour** — `.breadcrumb a { color: var(--accent); }` (`:51`). This is the ONLY generic-link
   use of `--accent` — `header h1 a` uses `var(--fg)`, not accent. Verified in
   `notebook_detail.html:6`: `<nav class="breadcrumb">` sits BEFORE the first `<section class="card">`,
   so it renders on `--bg`, not `--card-bg`.
4. **Skip-link ground** — `.skip-link:focus-visible { background: var(--accent); color: #fff; }`
   (`:217-218`) — same white-text-on-accent shape as role #1, but a distinct rendered element/rule
   that needs its own contrast-table row (identical value today, not guaranteed to stay identical
   post-re-derivation if the two `color: #fff` sites are edited independently).
5. **`badge-flash` tint** — `@keyframes badge-flash { from { background: color-mix(in oklab,
   var(--accent) 30%, transparent); } }` (`:377`), inside `.status-badge.htmx-settling`. A transient
   30%-opacity overlay on top of whatever status-pill color is already showing — hard to pin as a
   single static contrast pair; flag it qualitatively in the artifact rather than forcing a ratio.

**The hand-patched compensation** (quoted verbatim, `app.css:282-285`):
```
  /* synthesis §2 C2: white text on #58a6ff is only ~3.1:1 — fails SC
     1.4.3 for 14px button text. Dark text on the lighter dark-mode
     --accent gives ~7.2:1. Restore contrast. */
  button, .button { color: #0d1117; }
```
Any OKLCH re-derivation of dark `--accent` must reproduce this reasoning (verify whichever new
value is chosen still needs — or no longer needs — a forced button-text override), not silently
inherit the `#0d1117` literal.

## 5. Which pairs actually render (cross-referenced against templates + routes)

Reading `server/frontend/templates/{base,index,notebook_detail}.html` and the HTML-fragment
builders in `server/routes/{ui,notebooks}.py` (`_display_name_fragment`, `_topic_fragment`,
`_discover_results_fragment`, `_paper_row_html`, `_notebook_row_html`, `_ingest_status_fragment`,
`ui_status_badge` / `_build_remediation_block`) confirms every class emitted server-side has a
matching CSS rule (no orphans) and surfaces one pair the design-overlay §4 table structurally
cannot contain: **`<small class="status-badge__remediation">`** (`server/routes/ui.py:336`) has
**no CSS rule of its own** — it inherits `color` from whichever `.status-badge--{ok,warn,ops-warn,down}`
modifier is active on its parent `<span>`, on that same modifier's `background`. Not a NEW ratio (it
reuses the pill's own already-computed pair) but it IS a second rendered site for that ratio, and
`ui-uplift-m9` (BAN-R2 derived-test milestone, not this one) is what will eventually assert every
emitted class has a rule — don't let m6 be blocked by that gap, just don't miss the pair.

**Rough total distinct rendered fg/bg (or ring/ground) pairs across both modes, once you count
text pairs AND non-text pairs (borders, focus rings) AND both grounds where relevant: approximately
30-40**, not the 12 cells (6 tokens × 2 grounds) the design-overlay §4 table carries and not the
"8" the roadmap's shorthand references. Concretely, beyond the 12 token cells, at minimum: `--danger`
on `--error-bg` (both modes, `pre.error` — dark is the CURRENT tightest rendered pair, measured
**4.974:1**, 0.47 of headroom, by the challenger's independent recomputation), `--border` on both
grounds in both modes (non-text, SC 1.4.11 — light is the ALREADY-FAILING pair AC #4 exists to fix,
computed today at **1.342:1** against `--bg`), the 2 button-text pairs, the 2 skip-link-text pairs,
the 4 non-text focus-ring pairs (accent vs both grounds × 2 modes), the danger-ring equivalent, all
18 non-token literal sites from §2 (each against its correct ground, not a guessed one), and the 7
already-hardcoded-but-unverified-in-one-place pill triples. **A partial inventory here is exactly
how the two AA failures fixed in `3a7d626` survived in shipped code — do not let the "8 tokens"
framing in the milestone title narrow the artifact's actual coverage.**

## 6. Tests that will gate this change

**Three files pin the app.css 400-line soft cap and MUST move in lockstep** (a `m4/m5` cross-file
rule the tests themselves assert): `tests/test_ui_m3_dark_and_htmx_feedback.py:462-493`
(`test_app_css_under_soft_cap`), `tests/test_ui_m4_in_place_add_paper.py:~665-672`
(`test_app_css_under_m4_cap` — grep-confirmed, not fully read), `tests/test_ui_m5_create_remove_in_place.py:795-805`
(`test_app_css_under_m5_cap`). All three do `line_count = APP_CSS.count("\n") + (1 if not
APP_CSS.endswith("\n") else 0); assert line_count <= 400`. **At 398/400 today, adding even the 3
new `--dur-*` custom properties (plus any explanatory comment, which this codebase's convention
runs 3-10 lines per token decision) will almost certainly exceed 400** — expect a 4th consecutive
cap-raise (400 → 4XX) across these exact three files, or comment-trimming elsewhere to make room.

**Two tests hard-pin exact hex literals on the SAME tokens this milestone re-derives — they WILL
break and MUST be updated, not just "might":**
- `tests/test_ui_m3_dark_and_htmx_feedback.py::TestUPL8DarkModeBlock::test_dark_border_uses_corrected_hex_not_primer_canonical`
  (`:92-108`) — asserts `"#6e7681" in block` AND `"#30363d" not in block` inside the dark `:root`
  block. Any OKLCH re-derivation of dark `--border` away from `#6e7681` fails this immediately.
- `tests/test_ui_m3_dark_and_htmx_feedback.py::TestUPL8DarkModeBlock::test_dark_block_corrects_button_text_color`
  (`:200-223`) — regex-asserts `button\s*,\s*\.button\s*\{[^}]*color:\s*#0d1117[^}]*\}` inside the
  dark block. Breaks if the button-text compensation literal changes (likely, since it currently
  equals dark `--bg`'s exact value).

**Structurally safe (no literal pins, will keep passing through a value change) in the same file:**
`test_dark_block_redeclares_all_seven_color_tokens` (checks token NAMES only),
`test_color_scheme_declared_on_root` (checks the string `color-scheme: light dark`, matching AC #6
exactly), `test_dark_block_redeclares_text_input_for_visibility` (checks `var(--card-bg)`/`var(--fg)`
references, not hex), `test_dark_block_remaps_tertiary_text_greys` (checks selector-token presence
only).

**The load-bearing precedent for the contrast-table artifact itself:**
`tests/test_ui_m5_create_remove_in_place.py:518-631` (`TestUPL8V1DarkModePillContrast`) is the
**only place in this repo that programmatically computes WCAG 2.1 contrast** — `_hex_to_rgb` /
`_relative_luminance` / `_contrast_ratio` (`:518-538`, the exact W3C relative-luminance formula,
`0.2126/0.7152/0.0722` coefficients) followed by parametrized `>= 4.5` / `>= 3.0` assertions
(`:585-606`). **This is the pattern to reuse or extend for m6's own contrast table/tests — not a
hand-computed table that a future agent has to trust.** One landmine inside it:
`test_pill_text_color_also_visible_on_canvas` (`:596-606`) hardcodes `canvas = "#0d1117"` (`:600`,
today's dark `--bg` value) rather than reading it from the CSS file. If dark `--bg` changes, this
test keeps silently checking against the OLD canvas color — it will not fail loudly, it will just
be checking the wrong thing. Needs updating in lockstep with any dark `--bg` change, or refactoring
to parse `--bg` from `APP_CSS` dynamically.

No test anywhere else in the repo computes contrast ratios (grepped `relative_luminance|contrast_ratio|
0\.2126` repo-wide) — the design-overlay §4 table and every other contrast claim in this codebase's
history (UPL-27, the m3/m5 dark-mode work) was **hand-computed and hand-verified live in a browser**,
per the `3a7d626` commit message's own words ("computed styles and rendered fragment output, not
just source assertions"). That manual-verification gap is the root cause the roadmap's key result
("a full RENDERED-pair contrast table ships as a milestone artifact") exists to close.

## 7. Prior art + doc placement

The design overlay's token table is `.claude/references/frontend-uplift/arxmcp-design-system.md`
§"4. CSS variables" (`:142-186`) — 8 tokens, a 12-cell (6 rows × 2 grounds) contrast table, and the
line "Re-run these before any colour change — a token tweak that drops a pair below 4.5:1 is a
Phase-3 BLOCKER." That doc was last verified 2026-07-10 and is itself already stale in at least one
place challenge.md caught (its "24 aria-live regions" claim counts doc comments; the real number is
12) — treat it as directional, re-verify every number it states rather than citing it as current.

**Format precedent for a data/measurement artifact that future work cites:**
`.claude/docs/retrieval-quality-report.md` — title, a `**Status:**` line naming what was measured
and when, a headline Markdown table, a bolded one-line finding, then supporting detail. This is the
closest existing shape to "a full rendered-pair contrast table."

**Placement recommendation:** the roadmap's own `key_results` line calls it "a milestone artifact,"
and CLAUDE.md §5 shows `.claude/notes/milestones/<ID>/` as the per-milestone research/critique/
implementation home — that argues for `.claude/notes/milestones/ui-uplift-m6/implement/contrast-table.md`.
But this table is explicitly load-bearing for LATER milestones in the same epic: `ui-uplift-m8`
(the rule-ladder) depends on m6's re-derived `--border` clearing 3:1, and the roadmap's own
`assumptions` block states the dependency numerically. A milestone-scoped artifact buried in
`implement/` is easy for a future agent to miss; `.claude/docs/` (per CLAUDE.md §1, "per-feature
internal references") is where cross-milestone-cited data currently lives (`retrieval-quality-report.md`,
`eval-curation.md`). Recommend `.claude/docs/ui-contrast-table.md`, cited from both the milestone's
own implementation notes and (going forward) from m8's research brief.

## 8. v0/v1 scope boundary — confirmed identical across three independent sources

The roadmap acceptance criteria (`plans/ui-uplift/roadmap.yaml`, `ui-uplift-m6` item),
`final-report.md:229-230`, and `challenge.md:169-178` (the challenger's own "Suggested scope
adjustment" for UPL-4) all agree on the SAME split:

- **v0 (this milestone):** re-derive the 8 EXISTING token names only (no new token names besides
  `--dur-fast/normal/slow`), in OKLCH, from one hue, both modes. Ship the full rendered-pair
  contrast table. `light-dark()` explicitly OUT (AC #7) — it is Newly Available, not Widely
  Available (lands 2026-11-13, after this milestone's window), and inside a custom property an
  unsupporting engine fails at *substitution* (not a graceful CSS fallback) per `challenge.md:147-155`.
- **v1 (a DIFFERENT, not-yet-scheduled milestone):** fold the ~12 grey literals and the pill
  literals from §2 into the token system. **The roadmap (`plans/ui-uplift/roadmap.yaml`) does not
  yet list a v1 milestone id** — m7 through m23 cover type scale, card retirement, and interaction
  polish, none of them the grey/pill folding. Do not let m6 quietly absorb that work; it is out of
  this milestone's acceptance criteria (which say nothing about the §2 literal sites) and doing it
  would also consume line-cap headroom (§6) that the duration tokens already threaten.
- **v2 (future, after 2026-11-13):** `light-dark()` collapse, behind `@supports`.

**"The rule token" in AC #4 is `--border`, not a new token name.** The roadmap's own `assumptions`
block states it explicitly: *"The light-mode --border token can be darkened enough to carry
structure alone... it computes to 1.342:1 on --bg today."* `ui-uplift-m8`'s acceptance criteria
also call it "the rule token" while linking `app.css:53-59` (the `.card` rule, not a new selector).
No new `--rule` or `--rule-section` custom property is in scope for m6 — that migration (moving
`th`'s header-separation duty onto a rule weight) is explicitly `ui-uplift-m8`'s job per
`final-report.md:210-211`.

## 9. Duration-token value ambiguity (not resolvable from the repo alone — flagged for Phase 2/3)

`.claude/references/frontend-uplift-motion-vocabulary.md` §9 ("Token discipline — CHALLENGER USES
THIS") names a canonical 4-tier scale: `duration-fast (100ms)` / `duration-normal (200ms)` /
`duration-slow (300ms)` / `duration-brand (500ms)`. `challenge.md:950` proposes the exact CSS
custom-property spelling the milestone brief uses: `--dur-fast: 100ms; --dur-normal: 200ms;
--dur-slow: 300ms;` (3 of the canon's 4 tiers — `--dur-brand` is not named in this milestone's
scope). **None of these three values equals the existing `400ms` (badge-flash) or `0.6s`/`600ms`
(spin) literals from §3** — only the two `200ms` sites map cleanly onto `--dur-normal`. The
milestone summary says the tokens are needed "because... the stylesheet hard-codes 0.6s / 400ms /
200ms with no duration tokens" (implying those three literals should end up token-referenced), but
no acceptance criterion states whether existing durations must be RE-TIMED to fit the 3-tier scale
(changing visual behavior: spin 2× faster if retimed to 300ms, badge-flash 25% faster if retimed to
300ms) or whether the tokens should be introduced without touching the 400ms/600ms sites (leaving
"the motion canon requires token-referenced durations" only half-satisfied). This is a real decision
point, not a research gap — flagging for Phase 2/3 rather than resolving it here.

## 10. Diff-size / file-count estimate

**Files almost certain to change:**
1. `server/frontend/static/app.css` — 8 token value edits (light) + 7 (dark) + 3 new `--dur-*`
   properties + rationale comments (this codebase's convention runs long per decision — see the
   UPL-8/UPL-27 comment blocks already in the file). Estimate 30-70 changed/added lines.
2. `tests/test_ui_m3_dark_and_htmx_feedback.py` — at minimum the 2 hex-pinned tests from §6 (border,
   button-text). Estimate 10-20 changed lines.
3. `tests/test_ui_m5_create_remove_in_place.py` — the `canvas = "#0d1117"` literal (§6) if dark
   `--bg` changes. Estimate 1-5 changed lines.
4. Line-cap raise across the 3 files named in §6 (small, ~2 lines × 3 files).
5. A new contrast-table artifact (§7) — given the ~30-40-pair count in §5, expect 100-250 new lines
   of Markdown.

**Files that may change, pending Phase-2/3 decisions:**
6. `server/frontend/static/favicon.svg` (§2) — 1 line, if the implementer chooses to keep it synced
   with the new light `--accent` rather than accepting the drift.
7. A new or extended test module generalizing `TestUPL8V1DarkModePillContrast`'s WCAG helpers
   (§6) to cover the full pair set from §5, rather than duplicating the hex-arithmetic by hand.

**Not expected to change:** the three Jinja2 templates and the `server/routes/{ui,notebooks}.py`
fragment builders — m6 is a pure `:root`-token re-derivation; no class names, no markup, no new
selectors are implied by any of its 7 acceptance criteria.

**Net estimate: 5-7 files, roughly 150-350 changed/added lines**, dominated by the new contrast-
table artifact. This is a medium milestone (matches the roadmap's own `size: M` on the parent epic
and the challenger's "M" sizing for UPL-4) — the WCAG arithmetic across ~30-40 pairs plus the
lockstep test/cap updates argue for delegating Phase 2 to `milestone-implementer` rather than an
inline fix, given the file count and the correctness-sensitive nature of the hard gate (AC #5).

## Acceptance criteria the implementer must meet

(Verbatim from `plans/ui-uplift/roadmap.yaml`, item `ui-uplift-m6` — identical to the brief passed
to this researcher.)

1. Given the token block, when re-derived, then both light and dark modes come from ONE hue
   decision and no value is a GitHub Primer literal.
2. Given the milestone artifact, then it ships a contrast table covering EVERY rendered
   foreground/background pair — not the 8 (really 12-cell) token-on-ground pairs the overlay
   tabulates, which is how two AA failures survived in shipped code (see §5-6 for the real count
   and the existing WCAG-calculator precedent to reuse).
3. Given `--accent`, when re-derived, then it satisfies all five of its roles simultaneously (§4):
   button ground ≥4.5:1 against its own text, focus ring ≥3:1 against BOTH `--bg` and `--card-bg`,
   link, skip-link ground, badge-flash tint.
4. Given the light-mode rule token (= `--border`, §8), when computed, then it clears 3:1 against
   `--bg` (today: 1.342:1) so `ui-uplift-m8` is unblocked.
5. Given any pair, when it computes below 4.5:1, then the milestone does not ship — hard gate.
   Note the tightest KNOWN rendered pair today (dark `--danger` on `--error-bg`, `pre.error`) is
   already at 4.974:1 (0.47 headroom) BEFORE any re-derivation — re-verify it does not drop further.
6. Given `color-scheme: light dark` (`app.css:10`), then it is preserved unchanged — load-bearing
   for UA control internals, not itself a token.
7. Given `light-dark()`, then it is NOT used in v0 (§8) — Newly Available, not Widely (lands
   2026-11-13); inside a custom property an unsupporting engine fails at substitution, not gracefully.

## Risks and open questions

1. **Two tests hard-pin exact hex literals on tokens this milestone re-derives and WILL fail, not
   might** — `test_dark_border_uses_corrected_hex_not_primer_canonical` (pins dark `--border` =
   `#6e7681`) and `test_dark_block_corrects_button_text_color` (pins the button-text compensation =
   `#0d1117`), both in `tests/test_ui_m3_dark_and_htmx_feedback.py`. These are required edits, not
   incidental fallout — budget for them explicitly rather than discovering them at `make test` time.
2. **The one existing programmatic WCAG checker hardcodes a stale-prone assumption.**
   `tests/test_ui_m5_create_remove_in_place.py:600`'s `canvas = "#0d1117"` (dark `--bg`'s current
   value, duplicated as a Python string) will not fail loudly if dark `--bg` changes — it will
   silently validate against the wrong ground. Either update it in lockstep or refactor it to parse
   `--bg` from `APP_CSS` directly, and prefer extending `_hex_to_rgb`/`_relative_luminance`/
   `_contrast_ratio` (`:518-538`) for the new contrast-table's own tests over re-implementing the
   formula a second time.
3. **Duration-token values don't cover the existing literals.** The canon's `--dur-fast/normal/slow`
   (100/200/300ms) leaves `400ms` (badge-flash) and `600ms` (spin) unmapped (§9) — whether to retime
   those two rules (a visible behavior change no AC currently authorizes) or leave them un-tokenized
   (leaving the summary's stated motivation half-satisfied) is an open decision for Phase 2/3, not
   something this research can resolve from the repo alone.
4. **`favicon.svg`'s hardcoded `fill="#1e5b8a"` will silently drift from a re-derived light
   `--accent`** (§2) — SVG favicons don't inherit CSS custom properties (this repo's own past
   lesson), so the browser tab would keep showing the OLD brand color after a successful re-
   derivation. Not named in the roadmap item's `links.code`. Needs an explicit decision either way.
5. **The line-cap will almost certainly need a 4th consecutive raise.** At 398/400 lines with only
   the 3 new `--dur-*` properties still to add (before any rationale comments, which this file's
   convention runs long on), the cap in the 3 lockstep test files (§6) will likely need to move
   again — plan for touching all three together, as the tests themselves require.

Note: the v0/v1 scope boundary (§8) and "rule token = `--border`" naming (§8) are NOT listed as
risks above because they are fully resolved by cross-referencing the roadmap, final-report.md, and
challenge.md — treat §8 as settled fact, not an open question.

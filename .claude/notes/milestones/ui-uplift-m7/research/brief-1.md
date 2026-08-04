---
milestone_id: "ui-uplift-m7"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — ui-uplift-m7

Codebase half only. Every claim below is cited at `file:line` against the
working tree at the time of research (worktree snapshot byte-identical to
`/Users/chris.dare/Personal/SourceCode/arXMCP` for `app.css`, verified with
`diff -q`). No web research; no files modified outside this brief.

**Headline for the implementer, before anything else:**
`app.css` is **471 lines** against a **480-line cap** asserted by three test
files in lockstep. This milestone has **9 lines of headroom**. A realistic m7
diff (7–10 tokens + m6-style per-token rationale + ~8 rule edits) is 40–80
lines. **A coordinated cap raise across all three files is not optional — it
is step one.**

---

## 1. Every font-bearing declaration in `server/frontend/static/app.css`

The file is 471 lines and is the **only** stylesheet in the product
(`server/frontend/static/` contains `app.css`, `favicon.svg`, `htmx.min.js`,
`json-enc.js`, `VENDORED.md` — no second CSS file).

### 1a. `font-family` — 9 declarations, 2 voices, one of them untokenised

| # | `app.css:` | Selector | Value | Note |
|---|---|---|---|---|
| 1 | `:40` | `:root` | `--mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace` | the **only** font token that exists today |
| 2 | `:56-57` | `body` | `-apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif` | **the sans voice is an inline literal, NOT a token.** AC#4 implies this becomes `--font-sans` (or similar) in `:root` |
| 3 | `:119` | `input[type="text"], input[type="url"], input[type="file"]` | `inherit` | |
| 4 | `:121` | `input[type="text"], input[type="url"]` | `var(--mono)` | overrides #3 for the two text inputs; `file` stays sans |
| 5 | `:132` | `select, textarea` | `inherit` | `--mono` deliberately NOT extended here — comment at `:129` says "topic text is prose, not an identifier". Keep that decision. |
| 6 | `:147` | `button, .button` | `inherit` | |
| 7 | `:167` | `table code` | `var(--mono)` | **descendant-of-table only** |
| 8 | `:199` | `pre.error` | `var(--mono)` | |
| 9 | `:213` | `.status-badge` | `var(--mono)` | load-bearing: `:219`'s `min-width: 14ch` comment says *"Font-family is --mono so ch is predictable"* — **do not change `.status-badge`'s family or size without re-deriving `14ch`** |

**`--mono` is applied at exactly four sites: `:121`, `:167`, `:199`, `:213`.**
Everything else that reads as an identifier falls back to the UA generic
`monospace` (every `<code>` outside a `<table>`) or to the sans body font
(every `<time>`, and every bare-text state token in the fragment builders).
Those `<code>` elements carry no explicit `font-size` either, so their rendered
size is the browser's default fixed-width size rather than the inherited 16px
— worth eyeballing in a browser during implementation rather than assuming.

### 1b. `font-size` — 14 declarations, all `rem`, none tokenised

Computed px assumes the root font-size is the UA default `16px` (nothing in
`app.css` sets `html { font-size }`).

| `app.css:` | Selector | Authored | px | Renders |
|---|---|---|---|---|
| `:77` | `header .subtitle` | `0.9rem` | 14.4 | the one-line strapline under the title |
| `:82` | `.breadcrumb` | `0.9rem` | 14.4 | "← All notebooks" on the detail page |
| `:93` | `.card h2` | `1.1rem` | **17.6** | **all nine `<h2>` in the product** |
| `:94` | `.card .hint` | `0.875rem` | 14 | every explanatory paragraph |
| `:99` | `.card .note` | `0.8rem` | 12.8 | italic captions |
| `:101` | `.card .display-name` | `1rem` | 16 | notebook display name |
| `:106` | `label` | `0.875rem` | 14 | every form label |
| `:114` | `input[type=text|url|file]` | `0.95rem` | 15.2 | |
| `:132` | `select, textarea` | `0.95rem` | 15.2 | |
| `:140` | `button, .button` | `0.875rem` | 14 | |
| `:165` | `th, td` | `0.9rem` | 14.4 | both data tables |
| `:167` | `table code` | `0.85rem` | 13.6 | slugs + paper ids in tables |
| `:200` | `pre.error` | `0.8rem` | 12.8 | |
| `:212` | `.status-badge` | `0.75rem` | 12 | smallest text shipped today |

Elements with **no** `font-size` rule, i.e. UA defaults:

- `body` → `medium` = **16px**.
- `header h1` → UA `h1 { font-size: 2em; font-weight: bold }` = **32px / 700**.
  `app.css:75` overrides *margin only*; `:76` overrides colour + decoration on
  `header h1 a`. **This is the "fixed at 32px" AC#3 targets.**
- `<code>`, `<time>`, `<small>`, `<dt>`, `<dd>` — all inherit.

### 1c. `font-weight` — 4 declarations

| `app.css:` | Selector | Value |
|---|---|---|
| `:107` | `label` | `500` |
| `:161` | `dl.meta dt` | `500` |
| `:166` | `th` | `600` |
| `:214` | `.status-badge` | `600` |

Plus two **implicit** UA weights that carry the entire heading hierarchy:
`header h1` = `bold` (700) and every `<h2>` = `bold` (700), neither declared
anywhere in `app.css`.

### 1d. `line-height` — exactly one declaration

`app.css:62` — `body { line-height: 1.5 }`. Nothing else in the file sets it.
A 20px section heading inheriting 1.5 gives 30px leading, which is loose for a
heading; if m7 authors a heading line-height it is the file's **second ever**.

### 1e. `letter-spacing` / `text-transform` — ZERO occurrences

Verified by `grep -rn "letter-spacing\|text-transform" server/ tests/` → no
hits anywhere in the repo. **The roadmap's claim that this milestone
introduces the product's first letter-spacing declaration is accurate.**
`font-variant-numeric` has exactly one occurrence (`:190`); no
`font-feature-settings` anywhere.

### 1f. **AC#1 — the measured h2→body step is 1.10x. The roadmap is right.**

```
.card h2  = 1.1rem = 17.60px   (app.css:93)
body      = UA medium = 16.00px (no declaration)
ratio     = 17.60 / 16.00 = 1.100x   exactly
```

Two facts that sharpen AC#1:

1. **`.card h2` governs every heading below the title.** All nine `<h2>` live
   inside `<section class="card">` (`index.html:7,66`;
   `notebook_detail.html:9,95,148,182,222,252,301`), so the bare UA
   `h2 { font-size: 1.5em }` = 24px rule is **never reached**. Adding a bare
   `h2 { font-size: var(--text-section) }` rule will NOT take effect —
   `.card h2` has specificity (0,1,1) and wins. **The `:93` declaration must
   be edited, not shadowed.**
2. **Hierarchy today IS carried by weight alone at the h2 level.** 17.6px vs
   16px is a 1.6px step — below the just-noticeable threshold at reading
   distance. What actually distinguishes an h2 is the inherited UA `bold`.
   That is precisely the AC#1 complaint, and it is literally true rather than
   rhetorical.
3. Other current steps, for the scale author: `header h1` 32px → `.card h2`
   17.6px = **1.818x**; `header h1` → body = **2.000x**. The roadmap's target
   (section 20 / body 16) is **1.25x**.

---

## 2. Complete identifier-surface inventory (AC#2)

AC#2 names six identifier classes: paper id, slug, path, timestamp, corpus
version, state token. Below is **every** render site across the three
templates and both fragment builders — not a sample. "mono today" means
`var(--mono)` specifically (UA generic `monospace` is called out as such,
because it is a different font and a different size).

### 2a. Jinja2 templates

| # | Identifier | Site | Markup | `--mono` today | tabular-nums today |
|---|---|---|---|---|---|
| 1 | slug | `index.html:90` | `<td><code>` | **YES** (`table code`, `:167`) | YES (`td code`, `:189`) |
| 2 | timestamp `created_at` | `index.html:92` | `<td><time>` | NO | YES (`time`) |
| 3 | slug | `index.html:89,107,111` | `data-slug` attr, `hx-delete` URL, `hx-confirm` prose | n/a (not rendered text) | n/a |
| 4 | path (prose) | `index.html:10` | `<code>tools/_notebook_common.SLUG_RE</code>` | NO — UA `monospace` | NO |
| 5 | slug | `notebook_detail.html:9` | `<h2><code>` | NO — UA `monospace` | NO |
| 6 | **path** `lancedb_path` | `notebook_detail.html:49` | `<dd><code>` | NO — UA `monospace` | YES (`dl.meta dd`) |
| 7 | timestamp `created_at` | `notebook_detail.html:50` | `<dd><time>` | NO | YES (both `time` and `dl.meta dd`) |
| 8 | **state token** `parse_status` | `notebook_detail.html:59` | `<span class="status-badge status-badge--…">` | **YES** (`:213`) | YES (`.status-badge`) |
| 9 | timestamp `finished_at`/`started_at` | `notebook_detail.html:70` | `<time>` inside `<dd>` | NO | YES |
| 10 | **state token** `latest_run.status` | `notebook_detail.html:71` | `<span class="hint">` — plain text `(ingest success)` | NO | NO |
| 11 | category code | `notebook_detail.html:110` | `<p class="topic-category"><code>` | NO — UA `monospace` | NO |
| 12 | slug | `notebook_detail.html:32,84,86,120,166,203,230,263,292,335,348,350` | hx-* URLs + `hx-confirm` prose | n/a | n/a |
| 13 | **paper id** | `notebook_detail.html:325` | `<td><code>` | **YES** | YES |
| 14 | timestamp `added_at` | `notebook_detail.html:326` | `<td><time>` | NO | YES |
| 15 | path + slug (prose) | `notebook_detail.html:256` | `<code>python -m tools.notebook_ingest {{ slug }}</code>` | NO — UA `monospace` | NO |
| 16 | paths / URLs (prose) | `base.html:64,81`; `notebook_detail.html:184,185,224,226,255,260` | `<code>` | NO — UA `monospace` | NO |
| 17 | slug | `notebook_detail.html:3` | `<title>` | n/a (browser chrome) | n/a |

### 2b. HTML-fragment builders — `server/routes/`

| # | Identifier | Site | Markup | `--mono` today | tabular-nums today |
|---|---|---|---|---|---|
| 18 | **corpus version** + notebook count + state label | `ui.py:288-293` (string composed at `health.py:606`, `"{LABEL} | corpus v{N} | {M} notebooks"`) | `<span class="status-badge status-badge--{css}">` | **YES** | YES |
| 19 | check names + `make` commands | `ui.py:335-336` | `<small class="status-badge__remediation">` | inherits `.status-badge` | inherits | in `_KNOWN_UNSTYLED` — see §4c |
| 20 | **paper id** | `notebooks.py:2023` — `f'<td>{html.escape(paper_id)}</td>'` | **bare `<td>`, no `<code>`** | **NO** | **NO** |
| 21 | timestamp `added_at` | `notebooks.py:2024` — `f'<td>{html.escape(added_at)}</td>'` | **bare `<td>`, no `<time>`** | **NO** | **NO** |
| 22 | slug + paper id | `notebooks.py:2005-2006,2021-2022` | attrs + preview href | n/a | n/a |
| 23 | slug | `notebooks.py:2081` | `<td><code>` | **YES** | YES |
| 24 | timestamp `created_at` | `notebooks.py:2083` | `<td><time>` | NO | YES |
| 25 | category code | `notebooks.py:622` | `<p class="topic-category"><code>` | NO — UA `monospace` | NO |
| 26 | **paper id** (discover candidate) | `notebooks.py:733` | `<p class="discover-meta"><code>` — **not in a table** | **NO** | NO |
| 27 | timestamp `submitted_date` | `notebooks.py:734` | `<time>` inside `.discover-meta` | NO | YES (`time`) |
| 28 | **state token** `Status: none/running/success/failed` | `notebooks.py:2352,2362,2371,2391` | bare text in `<div id="ingest-status">` | **NO** | **NO** |
| 29 | timestamps `Started …` / `Finished …` | `notebooks.py:2363,2372` | **bare text, no `<time>`** | **NO** | **NO** |
| 30 | run id `Run #{run_id}` | `notebooks.py:2364,2373,2393` | bare text | NO | NO |
| 31 | exit code `Exit {code}` | `notebooks.py:2392` | bare text | NO | NO |
| 32 | stderr tail | `notebooks.py:2386` | `<pre class="error">` | **YES** (`:199`) | NO |
| 33 | display name (**NOT** an identifier — prose) | `notebooks.py:556`; `notebook_detail.html:20` | `.display-name` | NO — **correct, leave it** | — |

### 2c. The live divergence AC#2 will surface (highest-value single find)

`_paper_row_html` (`server/routes/notebooks.py:2023-2024`) emits

```python
f'<td>{html.escape(paper_id)}</td>'
f'<td>{html.escape(added_at)}</td>'
```

while the template that renders the **same table** on page load emits
`<td><code>…</code></td>` and `<td><time>…</time></td>`
(`notebook_detail.html:325-326`). So today, adding a paper by URL-paste or
upload appends a row whose id and timestamp render in the **sans** font with
**proportional** figures, next to identical rows that render mono + tabular —
until the operator reloads. `_notebook_row_html` (`:2081,:2083`) got this
right; `_paper_row_html` did not. Fixing it is 2 lines and no existing test
breaks (see §4d).

### 2d. What "inherits the existing tabular-nums scope" means concretely

The scope is one rule, `app.css:189-191`:

```css
time, .status-badge, dl.meta dd, td code {
  font-variant-numeric: tabular-nums;
}
```

Preceded by its rationale comment at `:183-188`, which states the OpenType
`tnum` feature ships in every system-ui font in the body stack so the
high-level property suffices — **no `font-feature-settings` fallback exists or
is needed**. There is no other `font-variant-numeric` or
`font-feature-settings` declaration anywhere in the repo.

So "inherits the existing tabular-nums scope" operationally = every surface
m7 gives `--mono` must either already match one of those four selectors, or
be added to that selector list. From §2a/§2b, the surfaces that would need
adding are: `code` (generic, to catch every non-table `<code>`), the ingest
status div, `.discover-meta`, and whatever wrapper the m7 "meta" role uses.

---

## 3. The `:root` block after ui-uplift-m6 (AC#4)

`app.css:4-51`. Contents, in file order:

| `app.css:` | Token | Value | Kind |
|---|---|---|---|
| `:10` | `color-scheme` | `light dark` | **not a token** — load-bearing for UA control internals; do not disturb |
| `:33` | `--fg` | `oklch(22.842% 0.014 250)` | colour, `/* solved: 16.0:1 on --bg */` |
| `:34` | `--bg` | `oklch(98% 0.004 250)` | colour, `/* anchor: page canvas */` |
| `:35` | `--card-bg` | `oklch(99% 0.004 250)` | colour, anchor |
| `:36` | `--border` | `oklch(62.984% 0.018 250)` | colour, `/* solved: 3.30:1 on --bg (SC 1.4.11) */` |
| `:37` | `--accent` | `oklch(47.863% 0.115 250)` | colour, solved 6.20:1 |
| `:38` | `--danger` | `oklch(52.018% 0.165 28)` | colour, solved 5.30:1 |
| `:39` | `--error-bg` | `oklch(96% 0.015 28)` | colour, anchor |
| `:40` | `--mono` | system mono stack | **non-colour** |
| `:48` | `--dur-fast` | `200ms` | **non-colour** |
| `:49` | `--dur-normal` | `400ms` | **non-colour** |
| `:50` | `--dur-slow` | `600ms` | **non-colour** |

Dark override: `app.css:314-330` re-declares 7 colour tokens only; `--mono`
and `--dur-*` deliberately fall through (`:329` says so explicitly).

**Conventions m6 established that m7 must match:**

1. **Per-token derivation comment on the same line.** Every colour carries
   either `/* solved: <ratio> on <ground> */` or `/* anchor: <role> */`. The
   m4 cap-test rationale (`test_ui_m4_in_place_add_paper.py:690-692`) calls
   that provenance *"the deliverable"*. The type-scale analogue is naming the
   ratio each step is derived from and what it renders, not a bare `13px`.
2. **A block comment above the family stating the method** (`:11-32` for
   colour, `:41-47` for duration), including why rejected alternatives were
   rejected.
3. **Non-colour-scheme-dependent tokens are declared once, in the base
   `:root` only, and NOT re-declared in the dark block.** Type tokens are in
   that class. `test_ui_contrast.py::test_duration_tokens_declared_once_in_base_root`
   is the precedent that enforces this for `--dur-*`; an equivalent guard for
   the type tokens would be idiomatic.
4. **Cross-file numeric couplings are flagged in the comment.** `:46-47`
   pins `--dur-fast` to `index.html`'s `hx-swap="…swap:200ms"`. The m7
   analogue is `.status-badge`'s `min-width: 14ch` at `:216-219`, which is
   coupled to that rule's font-family AND font-size.

**AC#4 is not a stylistic preference — there is a test that will hard-fail.**
See §4b.

---

## 4. The constraints that will bite

### 4a. The 480-line cap — 9 lines of headroom, three files in lockstep

`app.css` is **471 lines** (`wc -l`; the tests compute
`APP_CSS.count("\n") + (1 if not endswith("\n") else 0)` = 471, since the file
ends with a newline). Cap = 480. **Headroom = 9 lines.**

Three test functions assert it, and all three carry comments saying they MUST
move together:

| Test | File | Line |
|---|---|---|
| `TestCrossMilestoneSafety::test_app_css_under_soft_cap` | `tests/test_ui_m3_dark_and_htmx_feedback.py` | 542 (assert at 570) |
| `TestCrossMilestoneSafety::test_app_css_under_revised_soft_cap` | `tests/test_ui_m4_in_place_add_paper.py` | 673 (assert at 694) |
| `TestCrossMilestoneSafety::test_app_css_under_m5_cap` | `tests/test_ui_m5_create_remove_in_place.py` | 807 (assert at 815) |

Documented trajectory: `m1=190 → m2=216 → m3-feat=287 → m3-rect=330 → m4=335
→ m5=370 → 2026q3-ui-uplift=400 → ui-uplift-m6=480`. Every raise edited all
three literals *and* added a one-line rationale to each comment block. The m3
message text also names the documented escape hatch: **split into
`tokens.css` + `app.css`**.

If the split is taken: `pyproject.toml:76` already globs
`"server.frontend.static" = ["*.css", …]` so a second file packages
automatically; `docker/Dockerfile.server:62,140` copy `server/` wholesale so
no `COPY` change is needed; CSP `style-src 'self' 'unsafe-inline'`
(`server/middleware.py:173`) already allows a second same-origin stylesheet
link in `base.html:7`. **But** `tests/_ui_color.py:36` hard-codes
`APP_CSS_PATH = server/frontend/static/app.css` and parses the `:root` blocks
out of *that file*, so moving `:root` to `tokens.css` breaks the entire
contrast gate. If splitting, split the **rules** out and leave `:root` in
`app.css` — or update `_ui_color.py` in the same commit.

### 4b. `test_all_colour_tokens_are_oklch_on_one_of_two_hues` — the hard blocker on AC#4

`tests/test_ui_contrast.py:427-448`. It iterates **every** raw token in both
`:root` blocks and skips only two names:

```python
if name in ("--mono",) or name.startswith("--dur-"):
    continue
m = hue_re.fullmatch(value.strip())
assert m is not None, f"{label} {name} = {value!r} is not an oklch() value"
```

**Any new non-colour token added to `:root` — `--text-body: 16px`,
`--font-sans: …`, `--tracking-meta: 0.06em` — fails this assertion
immediately.** AC#4 mandates extending `:root`, so this test MUST be updated
in the same commit. The minimal correct fix is to widen the skip predicate to
the m7 token prefixes (mirroring how `--dur-` is handled), NOT to loosen the
oklch regex.

Related but *safe*: `tests/_ui_color.py:236-241`'s `colors()` filter silently
drops any token that is neither a hex nor an `oklch()`, so `load_tokens()`
and the whole `PAIRS` registry are unaffected by new type tokens.
`test_no_token_is_a_primer_literal` (`:411`) does substring matching against
seven hex literals and will not false-positive on font values.

### 4c. Every other test that constrains a font, heading, or class

| Test | File:line | What it pins | Risk to m7 |
|---|---|---|---|
| `TestUPL10TabularNums::test_tabular_nums_covers_required_selectors` | `tests/test_ui_m2_polish.py:106` | takes `APP_CSS.index("font-variant-numeric: tabular-nums")` and requires `time`, `.status-badge`, `dl.meta dd`, `td code` to appear in the **300 chars preceding it** | **BREAKS if m7 adds a second `font-variant-numeric: tabular-nums` declaration earlier in the file** (`.index()` finds the first). Also breaks if the extended selector list grows past ~300 chars. Note the window is over the *raw* CSS incl. comments, and the comment at `:183-188` already contains the strings "status-badge" and "time" — so 2 of the 4 assertions are satisfiable by comment text alone. Weaker than it looks; treat it as a tripwire, not a guarantee. |
| `TestUPL10TabularNums::test_tabular_nums_rule_present` | `tests/test_ui_m2_polish.py:103` | literal `font-variant-numeric: tabular-nums` present | safe |
| `test_body_max_width_uses_v1_clamp` | `tests/test_ui_m2_polish.py:156` | regex `body { … max-width: clamp(640px, 92vw, 1400px) … }` over the comment-stripped CSS, plus a negative check that `max-width: 980px` is gone from the body block | **Sensitive.** The regex is `body\s*\{[^}]*max-width:…[^}]*\}` — `[^}]*` means it still matches if m7 adds `font-size` / `line-height` declarations inside the `body` rule, so adding to `body` is fine. It would break only if the `max-width` line itself is touched. |
| `TestUPL19V1BodyClamp::test_body_max_width_uses_clamp` | `tests/test_ui_m5_create_remove_in_place.py:644` | same clamp, second copy | same |
| `test_duration_tokens_declared_once_in_base_root` | `tests/test_ui_contrast.py:470` | `--dur-*` values + absent from dark block | safe; the pattern to copy |
| `test_color_scheme_light_dark_preserved` | `tests/test_ui_contrast.py:450` | `color-scheme: light dark` inside the base `:root` | safe as long as `:10` survives |
| `test_favicon_tracks_light_accent` | `tests/test_ui_contrast.py:516` | favicon `<rect fill>` == light `--accent` | safe |
| `test_published_region_is_current` | `tests/test_ui_contrast.py:753` | three generated regions of `.claude/docs/ui-contrast-table.md` must equal the renderers' output | **fires if any `PAIRS` row or floor changes** (see §5). Fix = `python -m tests.test_ui_contrast --update`. |
| `test_no_ratio_is_typed_outside_a_generated_region` | `tests/test_ui_contrast.py:670` | regex `\d+\.\d{2,3}:1` outside the markers, minus an allow-list | The existing prose "4.5:1" / "3:1" does **not** match (needs ≥2 decimals). Only fires if m7 types a new 2–3-decimal ratio into the doc's narrative. |
| `TestKnownUnstyledDebtIsSelfCleaning::test_known_unstyled_entries_are_still_actually_unstyled` | `tests/test_ui_class_css_coverage.py:560` | the 9 classes in `_KNOWN_UNSTYLED` (`:93-103`) must still have **zero** CSS rules | **BREAKS the moment m7 writes a rule for any of: `status-badge__remediation`, `topic-block`, `topic-category`, `topic-description`, `discover-candidate`, `discover-title`, `discover-meta`, `discover-abstract`, `discover-list`.** Two of those (`topic-category`, `discover-meta`) are natural m7 targets — they wrap identifiers. Fix = delete the entry from the dict in the same commit; the test is designed to make the list shrink. |
| `test_every_emitted_class_has_a_rule_or_reasoned_exemption` | `tests/test_ui_class_css_coverage.py:445` | any new `class="…"` literal in a fragment builder needs a rule or an allow-list entry | fires only if m7 adds a class in `server/routes/` |
| `test_every_faded_css_rule_has_a_registry_row` | `tests/test_ui_contrast.py:713` | every `opacity: 0.x` has a composited `PAIRS` row | m7 adds no opacity; safe |
| cap tests ×3 | see §4a | 480 lines | **will fire** |

`tests/test_ui_a11y_baselines.py` reads `app.css` but asserts only
reduced-motion, `:focus-visible` and `.skip-link` rules — **no font
assertions**. `tests/test_ui_html_pages.py` touches `app.css` only as a
static-route fetch. `tests/test_constitution_ui_claims.py` has no font
assertions. `tests/test_wheel_packaging.py:222` asserts `app.css` is
package-data (a filename check, size-agnostic).

### 4d. Fragment-builder tests that do *not* block the §2c fix

`_paper_row_html` is exercised by `tests/test_ui_m4_in_place_add_paper.py:113-175`
and `tests/test_ui_m5_create_remove_in_place.py:798-806`. Their assertions are
`'<a href="…/preview"' in out`, `'<span class="hint"' in out`,
`"<td>added</td>" in out`, and escaping checks (`&quot;`, `&lt;`, `&gt;`,
`&amp;` present). **None asserts the bare `<td>{paper_id}</td>` shape**, so
wrapping the id in `<code>` and the timestamp in `<time>` passes every
existing test unchanged.

---

## 5. `header h1`'s large-text status under a `clamp()` (AC#3)

### What is recorded today

- `.claude/docs/ui-contrast-table.md:93` — floors table:
  `| 3:1 | SC 1.4.3 large-text exception | header h1 a only — it inherits the
  UA h1 rule (2em **and** bold) |`
- `.claude/docs/ui-contrast-table.md:95-98` — *"Nothing else in this
  stylesheet reaches the large-text threshold: buttons are 14px, badges 12px,
  table cells 14.4px, card hints/notes 12.8–14.4px. `th` at
  `font-weight:600`/14.4px is far below the 18.7px bold threshold and is held
  to the full 4.5:1."*
- `tests/test_ui_contrast.py:23` (module docstring) — *"…for large text
  (>=24px, or >=18.7px bold — in this stylesheet only a bare `header h1`)."*
- `tests/test_ui_contrast.py:121` — the registry row:
  `_p(_m, "header h1 a (large text)", "--fg", "--bg", LARGE)` where
  `LARGE = 3.0` (`:57`). **It is the only consumer of the `LARGE` constant.**

### What actually happens when the clamp lands — precisely

**The contrast gate does not fail.** Measured ratios for that pair are
**16.032:1** light and **13.931:1** dark (`ui-contrast-table.md:214,227`).
Both clear the 4.5:1 text floor with an order of magnitude of headroom, so
re-registering the row at `TEXT` still passes. **AC#3 is not blocked by the
gate.**

**What breaks is the record, in four places:**

1. **The registered floor becomes wrong.** `render_table`
   (`tests/test_ui_contrast.py:544`) prints the SC column as
   `"1.4.3" if floor == TEXT else "1.4.11 / large text"`. If the clamp's
   rendered size at some viewport is below the large-text threshold, the
   artifact keeps publishing `3.0:1 | 1.4.11 / large text` for a pair that no
   longer qualifies. An unstated wrong exemption and an oversight look
   identical from the artifact — which is the exact critique-H3 principle the
   m6 registry was rebuilt around.
2. **The prose claim "it inherits the UA `h1` rule (2em and bold)" becomes
   false the moment `header h1` gets an authored `font-size`** — regardless of
   what the clamp's bounds are. That sentence is hand-written prose *outside*
   the generated markers, so **no test will catch it.**
3. **`ui-contrast-table.md:95-98` enumerates the px size of every other text
   surface.** m7 changes all of them (meta 11, small 13, body 16, section 20).
   Also hand-written, also outside the markers, also uncaught.
4. **`tests/test_ui_contrast.py:23`'s "only a bare `header h1`" clause** goes
   stale, and may become factually wrong in the other direction — see below.

### The threshold arithmetic the implementer needs

WCAG 2.1 "large scale" = **≥24px**, or **≥18.66px when bold (≥700)**. At a
390px viewport a `clamp(lo, Nvw, hi)` renders at `lo` (assuming the `vw` term
is below `lo` there — which is the point of the lower bound). So:

| clamp lower bound | `header h1` weight | Large text at 390px? |
|---|---|---|
| ≥ 24px | any | **yes** — exemption survives unchanged |
| 18.66–23.99px | bold (700, the UA default, if m7 leaves it) | **yes** via the bold branch |
| 18.66–23.99px | < 700 (if m7 authors a lighter title weight) | **no** — row must move to `TEXT` |
| < 18.66px | any | **no** — row must move to `TEXT` |

**Second-order effect nobody has flagged yet:** the roadmap puts sections at
**20px**, and every `<h2>` inherits UA `bold` (700). 20px bold ≥ 18.66px bold,
so **`.card h2` would newly qualify for the large-text exception** — making
`tests/test_ui_contrast.py:23`'s "only a bare `header h1`" wrong in the
*opposite* direction. No pair currently registered for `.card h2` text, so
nothing fails; but the inventory claim ("EVERY rendered pair") degrades.

### Recommended posture (for the implementer to weigh, not a decision)

Register `header h1 a` at `TEXT` (4.5) rather than `LARGE`. It is the
conservative floor that holds at **every** viewport, it still passes with
16:1 / 13.9:1, and it removes a viewport-dependent claim from a
viewport-agnostic registry. If `LARGE` is kept instead, it needs a companion
guard test asserting the clamp's lower bound ≥ 24px (or ≥ 18.7px with an
explicit bold weight on `header h1`), or the exemption is unbacked. Either
way, `.claude/docs/ui-contrast-table.md` must be regenerated
(`python -m tests.test_ui_contrast --update`) **and** its lines 91–98 prose
hand-updated in the same commit.

---

## 6. Files this milestone will touch

| Path | Role | Expected change |
|---|---|---|
| `server/frontend/static/app.css` | the only stylesheet | `:root` type tokens + `body`/`header h1`/`.card h2`/`--mono` scope/tabular-nums scope edits |
| `tests/test_ui_m3_dark_and_htmx_feedback.py` | cap test #1 | raise 480 → N, add rationale line |
| `tests/test_ui_m4_in_place_add_paper.py` | cap test #2 | same literal, lockstep |
| `tests/test_ui_m5_create_remove_in_place.py` | cap test #3 | same literal, lockstep |
| `tests/test_ui_contrast.py` | WCAG gate + artifact generator | widen the oklch skip predicate (`:434`); re-floor the `header h1 a` row (`:121`) if the clamp drops below threshold; refresh the `:23` docstring |
| `.claude/docs/ui-contrast-table.md` | published artifact | regenerate the 3 marked regions; hand-update the floors prose at `:91-98` |
| `server/routes/notebooks.py` | fragment builders | `_paper_row_html:2023-2024` `<code>`/`<time>` parity; optionally `<time>` for the ingest fragment's `Started`/`Finished` (`:2363,:2372`) |
| `tests/test_ui_class_css_coverage.py` | class-coverage gate | delete `_KNOWN_UNSTYLED` entries for any class m7 styles (`:93-103`) |
| `tests/test_ui_m2_polish.py` | tabular-nums pin | only if the tabular-nums rule is restructured (`:106`) |
| new `tests/test_ui_m7_type_scale.py` | m7's own regression suite | AC#1 ratio, AC#2 inventory, AC#3 clamp, AC#4 single-token-set |
| `.claude/references/frontend-uplift/arxmcp-design-system.md` | design inventory | §4's token table already went stale at m6 (it still lists the pre-OKLCH hexes at `:153-161`); m7 adds a whole token family it does not describe. Out of strict scope, but the drift is now two milestones deep |

Deliberately **not** touched: `base.html` / `index.html` / `notebook_detail.html`
need no edit for AC#1/#3/#4; AC#2 may want `<code>`/`<time>` wrappers, but the
template side is already correct at every site — the gap is in the Python
fragment builders (§2c).

---

## Acceptance criteria the implementer must meet

Traced 1:1 to `plans/ui-uplift/roadmap.yaml:313-317`.

1. **(roadmap AC#1)** The h2→body step is no longer 1.10x, and heading
   hierarchy is not carried by weight alone. **Edit `app.css:93` (`.card h2`)
   directly** — a bare `h2` rule is shadowed by that descendant selector, and
   all nine `<h2>` in the product are inside `.card`. Measured baseline:
   17.60px / 16.00px = 1.100x, with the entire perceived difference coming
   from the *inherited* UA `bold`.
2. **(roadmap AC#2)** Every identifier surface takes `var(--mono)` and sits
   in the tabular-nums scope (`app.css:189-191`). The complete inventory is
   §2 — 33 sites. Already compliant: 4 (`index.html:90`,
   `notebook_detail.html:59,325`, `ui.py:288`, plus `notebooks.py:2081`).
   Highest-value single fix: `notebooks.py:2023-2024`, where the htmx-appended
   paper row diverges from the template that renders the same table.
3. **(roadmap AC#3)** `header h1` scales via `clamp()` instead of the UA
   `2em` = 32px. `header h1` today has **no** `font-size` declaration
   (`app.css:75` sets margin only). Whatever bounds are chosen, resolve the
   large-text question in §5 in the same commit: either keep the lower bound
   ≥24px (or ≥18.7px with bold retained) and add a guard, or re-floor
   `tests/test_ui_contrast.py:121` to `TEXT` and regenerate the artifact.
4. **(roadmap AC#4)** Type tokens extend the existing `:root` at
   `app.css:4-51`; no second token set. This is gated by real code:
   `tests/test_ui_contrast.py:434` will hard-fail on any non-oklch token whose
   name is not `--mono` or `--dur-*`, so that skip predicate must be widened
   in the same commit. Follow the m6 conventions in §3: per-token derivation
   comment, family-level rationale block, base-`:root`-only declaration, and
   flag the `.status-badge` `14ch` coupling (`app.css:216-219`).
5. **(operational, derived from the cap tests)** Raise the 480-line cap in all
   three files together (`test_ui_m3…:570`, `test_ui_m4…:694`,
   `test_ui_m5…:815`), each with a one-line rationale appended to its comment
   block, or take the documented `tokens.css` split — in which case `:root`
   must stay in `app.css` or `tests/_ui_color.py:36` moves with it.

---

## Risks and open questions

1. **9 lines of headroom is the binding constraint on the whole milestone.**
   `app.css` is at 471/480. If the cap raise is treated as an afterthought,
   the implementer will either write an under-commented token family (which
   violates the m6 provenance convention that the cap comments themselves call
   "the deliverable") or discover the failure at the end. Decide the new cap
   *before* authoring, and budget for the rationale comments explicitly.

2. **The `header h1` large-text exemption is a record-correctness risk, not a
   gate failure — which makes it easy to miss.** The pair measures 16:1 /
   13.9:1, so no test turns red no matter what the clamp does. The wrong
   outcome here is a published artifact asserting a 3:1 exemption for an
   element that no longer qualifies, plus two blocks of hand-written prose
   (`ui-contrast-table.md:91-98`) that no test covers going silently stale.

3. **The `--mono` scope is far narrower than it reads.** `--mono` is applied
   at four selectors only. Every `<code>` outside a `<table>` — including the
   notebook slug in the detail-page `<h2>`, the LanceDB path, the discovery
   category, and the discover-candidate paper id — resolves to the UA generic
   `monospace`, a different face at a browser-default size. An implementer who
   assumes "`<code>` already means mono" will under-scope AC#2 by ~10 sites.
   Verify in a real browser, not by reading the CSS.

4. **Open question — does AC#2's "path" include prose paths?** Nine `<code>`
   spans wrap literal paths and URLs in explanatory copy (`base.html:64,81`;
   `index.html:10`; `notebook_detail.html:184,185,224,226,255,260`). They are
   documentation, not data the operator acts on. A blanket `code { font-family:
   var(--mono) }` catches them all for one line and is probably right; the
   alternative (scoping mono to data-bearing `<code>` only) needs a class the
   templates do not have. The brief does not say which. Recommend the blanket
   rule and note it.

5. **Open question — 11px meta would be the smallest text ever shipped
   here.** The current floor is `.status-badge` at 12px (`app.css:212`).
   WCAG imposes no additional floor below 24px, so nothing fails; but 11px
   uppercase at `+0.06em` on a loopback console read daily by one operator is
   a legibility judgement, not a compliance one. Worth a deliberate decision
   rather than inheriting the roadmap number unexamined. Related: `.card .note`
   at 12.8px is already the second-tightest gated text pair in the sweep
   (`app.css:95-98`), so any grey applied to an 11px meta role should be
   checked against 4.5:1 rather than assumed safe.

# Critique — ui-uplift-m10 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 216aff062f78d44d314b7b33f72d6b836192e0ee..9444a4cf0cb6b17eae8d0e7b2793032eea0e05ec
**Diff stats:** 14 files, 1974 LOC (1841 insertions, 133 deletions); code+test subset 8 files, +334/−132
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The `--fg-muted` derivation is independently re-verified and correct — I re-derived OKLCH→sRGB→WCAG from scratch and got 7.004:1 / 7.015:1 on `--card-bg` and 5.429:1 at the tightest pill (dark `--warn`), matching the published table to within 8-bit quantisation, with every ground the token actually renders on registered at the right floor and none omitted. No axis shows a security, MCP-spec, cache-byte-stability, local-first or no-fork problem, and the packaging boundary already covers both stylesheets. What is left is one reachable common-path defect on the milestone's own headline surface (the abstract is clipped with zero affordance and no route to the full text), a token whose derivation ground the roadmap has already scheduled for retirement, and a coverage predicate that still cannot distinguish a rule from a gesture — the exact failure mode this milestone was chartered to close.

## Executive summary

- [HIGH] `.discover-abstract` clips 40–85% of the operator's decision evidence with no ellipsis, fade, expand control, or link to the paper — and there is no other place in the console showing that abstract.
- [MEDIUM] `--fg-muted` is solved to 7.00:1 against `--card-bg`; `ui-uplift-m8` (unblocked, lane `next`) explicitly re-roles `--card-bg` away from panel ground, which silently moves every `--fg-muted` consumer onto an unregistered `--bg` pair.
- [MEDIUM] Nothing asserts a single declaration in the nine new rules. `_css_defines_class` matches a `.token` anywhere in the CSS text, so an empty `.foo { }` satisfies AC1 — the m7 bare-`font-size` precedent is unguarded against.
- [MEDIUM] The Discover panel names no ordering basis; the new hairline ladder renders reverse-chronological results in a form that reads as ranked. AC#4 removed the false string but left the implied precedence.
- [MEDIUM] `tokens.css:47` states in the past tense that the product "carried eleven hand-typed greys"; none was migrated, so the product now carries twelve muted values and the shipped comment overstates.
- [MEDIUM] Five `plans/ui-uplift/roadmap.yaml` `links.code` anchors are invalidated by the +77/+22-line growth — third re-anchor needed today. Not fixable from Phase 4 (one-writer rule); route to `/roadmap`.
- [LOW] `.discover-list { list-style: none }` drops list semantics under Safari/VoiceOver; the markup has no compensating `role="list"`.
- [NOTE — not a finding] Gate re-run on this box: **8 failures**, but a different set than the dispatch baseline — 6 × latexml sandbox, 1 × `WindowsPath`, and `test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` (`graph_status` `unavailable` vs `absent`; `var/arxmcp/index/kuzu` is a bootstrapped empty directory). The HuggingFace one passed. Zero relation to this diff; the baseline is 9 environment-bound, not 8.

## Findings

**H1 — Discover abstract clipped with no affordance and no route to full text** (HIGH)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-abstract { margin: 0.25rem 0 0`
**What:** `max-height: 4.5em; overflow: hidden` hard-clips the abstract at three line boxes with no ellipsis, gradient, `<details>`, scroll container or link to the paper, and the candidate's `paper_id` renders as bare `<code>` (`server/routes/notebooks.py:733`) rather than an anchor — so the console offers no way to read the rest.
**Why it matters:** `abstract_head` is the FULL abstract (`tools/_arxiv_api.py:210` is `" ".join(summary.split())`, 800–1500 chars); three lines at `--text-small` holds ~240 chars at a 640px viewport and ~540 at the 1400px ceiling, so 40–85% of the evidence backing the operator's irreversible "Add" click is invisible with nothing signalling that it was cut — a page that presents partial evidence as if it were whole, on the one surface this milestone exists to make trustworthy (CLAUDE.md §4.9's manufactured-impression standard).
**Proposed fix:** Keep the clamp, add the affordance. Cheapest correct pair, both inside the m10 line budget: (a) a fade mask on the clipped box — `.discover-abstract { -webkit-mask-image: linear-gradient(#000 70%, transparent); mask-image: linear-gradient(#000 70%, transparent); }` (Baseline Widely Available, unlike `line-clamp`, so it clears the same bar m6/m7 applied); and (b) make the identifier a real exit — in `_discover_results_fragment`, `<code><a href="https://arxiv.org/abs/{pid}" rel="noreferrer noopener" target="_blank">{pid}</a></code>` (the URL is already built one line below at `:740`). If the fragment builder is judged out of scope for a CSS milestone, ship (a) alone and file (b).
**Regression-guard:** `tests/test_ui_class_css_coverage.py` (or a new `test_ui_m10_discover.py`) asserting the `.discover-abstract` rule body contains a `mask-image` (or other cue) declaration alongside `overflow: hidden`, so a future edit cannot re-open the silent clip; plus a `test_notebook_api.py` assertion that `_discover_results_fragment` emits an `arxiv.org/abs/` anchor per candidate.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface / trust language (CLAUDE.md §4.9)

**M1 — `--fg-muted` derived against a ground ui-uplift-m8 is scheduled to retire** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:66`
**Anchor:** `--fg-muted: oklch(45.706% 0.014 250);`
**What:** The token's 7.00:1 target, its only two canvas-ground registry rows, and the explicit refusal to register a `--bg` pair are all pinned to `--card-bg` as *panel* ground, but `plans/ui-uplift/roadmap.yaml:327-352` (`ui-uplift-m8`, lane `next`, `depends_on: [m6, m7]` — both shipped) deletes `.card` and states as AC#2 that `--card-bg`'s successor role is "control ground for inputs and table headers, **not panel ground** — because three dark-mode rules still depend on it."
**Why it matters:** The day m8 lands, `.discover-meta` and `.topic-description` render on `--bg` with no registry row for that pair, which is precisely the binding-ground omission `.claude/docs/ui-contrast-table.md` was built to prevent — and m10 has written into both `tokens.css:55-57` and the published artifact that no such row exists *because the pair does not render*, so the omission will read as deliberate rather than stale. (I measured the post-m8 ratios: 6.804:1 light, 7.688:1 dark — no AA failure, so nothing will fail loudly; the record just goes quietly wrong. m8's "three dark-mode rules" count is now four.)
**Proposed fix:** One comment line in `tokens.css` beneath the GROUND paragraph naming the coupling explicitly — "`ui-uplift-m8` re-roles `--card-bg` off panel ground; when it lands, `--fg-muted`'s consumers move to `--bg` (measured 6.80:1 light / 7.69:1 dark, still AAA-adjacent) and the registry needs the `--fg-muted on --bg` rows added, not the card rows edited." Optionally add the two `--bg` rows now as m8-forward pairs with that reason in the Site column, which the registry's Site-column convention already supports.
**Regression-guard:** N/A (documentation coupling); the durable guard belongs in `ui-uplift-m8`'s acceptance criteria — add "`--fg-muted`'s registry rows are re-grounded" to m8's AC#2 list via `/roadmap`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing / math fidelity

**M2 — BAN-R2's predicate still cannot tell a rule from a gesture** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:119`
**Anchor:** `_KNOWN_UNSTYLED: dict[str, str] = {}`
**What:** With the deferral list emptied, AC1 is advertised as binding "unconditionally", but the predicate behind it is unchanged: `_css_defines_class` (`:311`) is `re.compile(r"\." + classname + r"(?![\w-])")` over comment-stripped text, so `.foo { }` — or `.foo` inside any declaration value — satisfies it, and I confirmed by grep that **no test in the suite asserts any declaration** for the nine classes m10 landed (`display`, `max-height`, `color`, `font-family` all unpinned).
**Why it matters:** m7 shipped `.status-badge__remediation` as a bare `font-size` pin that satisfied AC#5's letter while leaving discovery H1's inline run-on defect on screen for a full milestone — that is the documented precedent, and emptying the list makes the predicate the *only* remaining check, so the same class of gesture now passes with no deferral entry to make it visible. Concretely, `display: block` at `:317` is the single declaration that fixes H1 and nothing would fail if it were deleted; `.topic-block` at `:241` is one `margin` declaration and would pass identically as `{}`.
**Proposed fix:** Add a small derived companion in the same test module: for each token in `_all_emissions()`, locate its rule body in the comment-stripped CSS and assert the body is non-empty and contains at least one declaration outside `{margin, padding}` — plus a per-class pin for the two load-bearing declarations this milestone shipped (`.status-badge__remediation` contains `display: block`; `.discover-meta` contains `var(--fg-muted)`). ~25 LOC, no new file.
**Regression-guard:** `tests/test_ui_class_css_coverage.py::TestEveryEmittedClassHasARuleOrExemption::test_every_rule_is_substantive` — asserts `.status-badge__remediation`'s body contains `display: block`, and fails on an empty or margin-only body for any emitted class.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M3 — Discover panel discloses no ordering basis; the styled ladder reads as ranked** (MEDIUM)

**Where:** `server/routes/notebooks.py:746`
**Anchor:** `f'<p class="hint">{len(candidates)} new`
**What:** The results are strictly reverse-chronological (`tools/_arxiv_api.py:156` pins `sortBy=submittedDate&sortOrder=descending`), but neither the panel hint nor the fragment says so; m10 then rendered them as a top-to-bottom hairline ladder, which is the visual form a ranked list takes.
**Why it matters:** AC#4's deliverable was the *absence* of a manufactured relevance claim, and the string was correctly refused — but an unlabelled ordered list carries the same implication structurally, and CLAUDE.md §4.9 treats a manufactured impression as the same defect as a manufactured string. An operator who reads the first candidate as the best match is reading a submission date. (The CSS itself is clean here — no `:first-child` privilege, no ordinal, no chip, no "top results" heading, no aria-label implying rank; verified.)
**Proposed fix:** Six words in the string m10's own fragment already builds: `f'<p class="hint">{len(candidates)} new candidate(s), newest first — results are not saved; click Discover to re-run.</p>'`. This is the honest half of the "panel-level query disclosure" the implement synthesis deferred, at one line rather than a query-echo redesign.
**Regression-guard:** `tests/test_notebook_api.py` — assert the discover fragment's hint contains an ordering disclosure ("newest first") and, negatively, contains none of `relevan`, `match score`, `rank`, `best`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust language (CLAUDE.md §4.9)

**M4 — Token comment claims a grey migration that did not happen** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:47`
**Anchor:** `token, so the product carried eleven han`
**What:** The comment justifies `--fg-muted` in the past tense — "the product **carried** eleven hand-typed greys (#555/#666/#6f6f6f/#444 …) — the exact hand-picked-value stitch m6 existed to end" — and `.claude/docs/ui-contrast-table.md:174` repeats "the eleven hand-typed greys it exists to replace"; none was migrated. All eleven are still live at `app.css:42, 44, 45, 65, 70, 71, 72, 141` and the dark remaps at `:457-459`.
**Why it matters:** The product now carries twelve muted values instead of eleven, and the two places a future author reads the derivation both imply the stitch is closed. The implement synthesis discloses the deferral honestly, but the synthesis is not what ships — `tokens.css` is. A supporting claim is also false as written: "`#555` on the light card is 7.25:1, so nothing gets lighter" — `--fg-muted` measures 7.004:1, so the two `#555` consumers and `#444` (9.471:1) would all get lighter on migration.
**Proposed fix:** Two clauses in the same comment: change "carried" to "carries", and append "— NOT yet migrated onto this token; the eleven literals at `app.css:42/44/45/65/70/71/72/141` and the dark remaps at `:457-459` are a tracked follow-up, so today the product carries twelve muted values, not one." Same edit in the contrast-table paragraph. Drop or correct the "nothing gets lighter" clause.
**Regression-guard:** Optional. A derived check would be `test_ui_contrast.py` asserting the count of distinct achromatic hex literals in `app.css` is non-increasing across milestones.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity (derivation record accuracy)

**M5 — Five roadmap `links.code` anchors invalidated by the stylesheet growth** (MEDIUM)

**Where:** `plans/ui-uplift/roadmap.yaml:190`
**Anchor:** `code: ["server/frontend/static/app.css:6`
**What:** `app.css` grew 498 → 575 (a 58-line block inserted at 187, a 19-line block at ~302) and `tokens.css` 157 → 179 (+21 at 46, +1 at 162), so five anchors now resolve to unrelated text. Verified line-by-line against `216aff0`: `app.css:267-270` (line 190) was the UPL-27 `.status-badge--ok` note, now mid-comment about `<time>`/`tnum`; `app.css:412-436` (line 532) was the `.htmx-request` in-flight rule, now the `prefers-reduced-motion` reset; `app.css:478-481` (line 572) was the `::view-transition-old/new(root)` duration override, now the four dark pill literals; `tokens.css:132-157` (lines 118 and 301) was the dark `:root` block, now the type-scale comment tail (the block is 153-179).
**Why it matters:** This is the third re-anchor needed today, and three of the five now point at *plausible-looking but wrong* CSS rather than at nothing — a reader following `app.css:478-481` for a view-transition claim lands on status pills and cannot tell the anchor rotted.
**Proposed fix:** Re-anchor via `/roadmap`: `app.css:267-270`→`344-347`, `app.css:412-436`→`412-436` re-derived (the `.htmx-request` rule is now at `489-513`), `app.css:478-481`→`555-558`, `tokens.css:45-62`→`45-72`, `tokens.css:132-157`→`153-179`. **Not fixable in Phase 4** — the one-writer rule reserves `plans/ui-uplift/roadmap.yaml` to `/roadmap`; record this as a `/roadmap` hand-off in the rectify summary rather than editing the file.
**Regression-guard:** N/A (planning artifact, external writer). The durable fix is line-free anchors (`server/frontend/static/app.css` + a selector name), which the m10 row itself already uses.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**L1 — `list-style: none` drops list semantics under Safari/VoiceOver** (LOW)

**Where:** `server/frontend/static/app.css:209`
**Anchor:** `.discover-list { list-style: none; margin`
**What:** WebKit removes list semantics from a `<ul>` whose `list-style` is `none`, so VoiceOver stops announcing "list, N items" and item position; the emitted markup (`server/routes/notebooks.py:748`) carries no compensating `role="list"`.
**Why it matters:** A screen-reader operator loses the candidate count and position cues on the one surface that presents external content for judgement — a regression relative to the UA-bulleted list m10 replaced. No WCAG SC is failed, hence LOW.
**Proposed fix:** `<ul class="discover-list" role="list">` in `_discover_results_fragment`. One attribute; no CSS change.
**Regression-guard:** Optional — `tests/test_notebook_api.py` asserting `role="list"` on the discover `<ul>`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

- **The contrast math is right and I could not break it.** Re-deriving OKLCH→OKLab→linear sRGB→WCAG independently gives 7.004:1 (light) and 7.015:1 (dark) on `--card-bg` against the claimed 7.00 target, and every pill ground clears the 4.5:1 text floor: light warn 6.552, ops-warn 6.409, down 6.384; dark warn 5.429 (the claimed tightest), ops-warn 6.300, down 6.418. The 5.43-vs-5.45 gap is 8-bit quantisation, not an error.
- **Every ground the token renders on is registered, and no ground that does not render was padded in.** I traced all three consumers to their DOM ancestry — `.discover-meta` and `.topic-description` are inside `<section class="card">` on both emitters, and `_classify_status_badge` provably returns only `{ok, warn, ops-warn, down}` so the remediation caption can never land on a background-less base badge. The `ok` pill is correctly excluded because `_build_remediation_block` returns `""` for it. The refusal to register a non-rendering `--bg` pair is the correct discipline, not an omission.
- **The `4.5em` = three line boxes claim holds exactly.** `body { line-height: 1.5 }` is unitless (`app.css:23`), so it resolves against `.discover-abstract`'s own `--text-small`; nothing between `body` and the `<p>` re-sets it. The clamp lands on a line boundary as claimed.
- **AC#4 was refused for the right reason and the reasoning was written into the artifact that ships.** The Atom feed carries no rank in either namespace, the driver pins `sortBy=submittedDate`, and `DiscoveryCandidate` has nowhere to hold a score — three independent checks, all of which I re-verified. The CSS itself adds no `:first-child` privilege, no ordinal, no chip, no icon and no rank-implying label.
- **Three m9 doc-drift findings closed in place rather than deferred**, and the corrected premise for `_css_defines_class` is the true one: the file really does mix bare, compound, element-qualified, comma-grouped and `@media`-nested selectors, and I confirmed comment stripping is sound (zero residual `/*`, comment-only tokens absent, all nine classes matching real rules).
- **The cap raise was done the way the cap tests ask for it** — 520→600 in all three siblings in one commit, historical rationale byte-preserved, merits argued once and cross-referenced, landing at 575 with a 25-line margin instead of m7's 2.
- **Packaging, local-first and no-fork are clean and stayed clean.** No `@font-face`, no `@import`, no `url()`, no CDN, no network fetch anywhere in the diff; the CSP and `_CSP_UI_PREFIXES` are untouched; `pyproject.toml`'s `"server.frontend.static" = ["*.css", ...]` glob plus `tests/test_wheel_packaging.py:222/231` and `tools/wheel_install_check.py:119/125` already cover both stylesheets by name, so the growth ships.
- **Cache byte-stability is untouched by construction** — `server/tools.py`, `server/prompts.py`, every handler and the whole MCP surface are outside the diff, and nothing in the repo hashes or byte-compares the served static asset set, so there is no re-pin obligation.
- **The implement synthesis under-claims rather than over-claims.** It flags its own diff overrun instead of rounding it down, names the browser render as unverified, and lists the unmigrated greys and the missing AC#3 guard as deferrals — three of my findings are sharpened versions of things it disclosed rather than things it hid.

Severity counts: C0 H1 M5 L1

## Recommended rectification order

H1, M3, M2, M4, M1, M5, L1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>

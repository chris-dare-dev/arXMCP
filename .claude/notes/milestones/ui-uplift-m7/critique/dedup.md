# Critique (merged) — ui-uplift-m7

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-frontend-ux
**Commit range:** 2c6588446351f5d947d5c1dc366a036c661f6dc0..a825898616dd8368b57c57adc4802d01cc72baa3
**Diff stats:** 23 files, 2934 LOC (2745 insertions / 189 deletions; code-only 1127 LOC across 13 files, notes 1807 across 10)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H3, H2->H4, M1->M5, M2->M6, M3->M7, M4->M8, M5->M9, M6->M10, L1->L4, L2->L5, L3->L6, L4->L7, L5->L8, L6->L9
> - `milestone-frontend-ux` (frontend.md): H1->H5, H2->H6, M1->M11, M2->M12, M3->M13, M4->M14, M5->M15, L1->L10, L2->L11

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The tokens.css split (D1) is sound — the token parsers fail
loud on a missing or empty `:root` rather than returning a wrong table, both
consuming templates inherit `base.html`'s ordered links, and the packaging
claim was verified against the real glob rather than trusted. The two HIGHs
are both AC misses the diff itself introduced or left: the new
`code, time { font-size: var(--text-small) }` rule renders the detail page's
primary heading at 13px (smaller than body), and brief-1's inventory site 10
— a state token — never got the mono voice. Everything else is doc/comment
drift in the exact hand-written-prose class m6's critique H2 named.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The tokens.css split is executed cleanly — both token parsers fail loud rather than
returning a partial table, packaging is covered, `text-wrap` was correctly refused, and
the 480-line cap was honoured instead of raised a fourth time. But the new
`code, time { font-size: var(--text-small) }` rule pins the notebook-detail page's only
`<h2>` to 13px in the same commit that raised `.card h2` to 20px "so size carries the
hierarchy," which is AC#1 contradicted on the console's main page. Two AC#2 identifier
surfaces the milestone's own research brief enumerated were left uncovered and
undeclared, and the split introduced a cross-file `var()` reference that no committed
test verifies.

### milestone-frontend-ux — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The scale itself is well-authored — the tokens are `rem`, the micro-caps rule is scoped
correctly, the Baseline refusals held, and `tokens.css` is the most honestly-commented
file in the product. But the new `code, time` rule sets an **absolute** font-size, and on
`notebook_detail.html:9` that makes the page's own subject render at 13px inside a 20px
heading — the detail page's title is now smaller than its table body text, which inverts
the exact hierarchy AC#1 exists to create. That plus one enumerated inventory site left
in the wrong voice are cheap, surgical fixes; nothing here argues against the milestone's
direction.

## Executive summary — milestone-adversary-critic

- [HIGH] `notebook_detail.html:9` is `<h2><code>{{ slug }}</code></h2>`; the new bare-`code` size rule drops that heading's only text from 17.6px to 13px — below body — inverting AC#1 on the page whose h2 *is* the slug.
- [HIGH] AC#2 inventory gap: brief-1 site 10 (`(ingest {{ latest_run.status }})`, `notebook_detail.html:71`) is a state token still in the sans voice with no tabular-nums. 32 of 33 sites landed; the implement synthesis enumerates the closed ones and site 10 appears in none of them.
- [MEDIUM] `tests/test_ui_m3_dark_and_htmx_feedback.py:588` states the split "dropped app.css from 471 to ~400". It is **478 of 480** — two lines of headroom, and the same comment declares the escape hatch spent. The implement synthesis records the correct 471→478, so the checked-in comment contradicts its own author.
- [MEDIUM] The published reason for re-flooring `header h1 a` to 4.5:1 is wrong on the facts: `header h1` is UA **bold**, so the large-text threshold is 18.7px and the clamp's 24px minimum clears it at *every* viewport. The doc contradicts itself two paragraphs later by granting the bold branch to 20px `.card h2`.
- [MEDIUM] `.status-badge` 12px → 11px also shrinks the unstyled `<small class="status-badge__remediation">` nested inside it to ~9.2px — the console's only operator-actionable troubleshooting text. Neither the rule comment nor any test considers the nested element.
- [MEDIUM] `ui-contrast-table.md:111` hand-types "small 13px (… controls …)"; `input[type=text|url|file]`, `select` and `textarea` are all `--text-body` (16px). Wrong fact, outside a generated marker, in the document that exists to stop exactly that.
- [INFO] **The mandatory >400-LOC auto-finding is deliberately NOT filed.** `state.json` carries `allow_large_diff: true` (orchestrator-recorded), the same waiver mechanism used at ui-uplift-m6. Stated here so the omission is auditable rather than silent.
- [INFO] Baseline verified independently: the full suite gives **exactly 8** failures — 6 × macOS `sandbox-exec` latexml, 1 × `WindowsPath` on darwin, 1 × `test_cite_neighbors_wired`. The implementer's "7" is explained: its box had the HuggingFace artifact cached. **Zero new failures.** `ruff check .` clean.

## Executive summary — milestone-arxmcp-critic

- [HIGH] `app.css:195` gives every `<code>` a 13px size; `notebook_detail.html:9` is `<h2><code>{{ slug }}</code></h2>`, so the detail page's primary heading now renders SMALLER than body text and at 0.65× its sibling `<h2>`s — AC#1 inverted on the common path.
- [HIGH] The diff is 2934 LOC against a ~400-insertion tripwire the implementer declared and deliberately did not honour.
- [MEDIUM] Inventory site 10 (`notebook_detail.html:71`, `(ingest {{ latest_run.status }})`) still renders a state token in the sans voice, on the same page where `_ingest_status_fragment` now renders the identical datum as `<code>`. Neither Built nor Deferred in the synthesis.
- [MEDIUM] The split makes every `var(--x)` in `app.css` a cross-file reference to `tokens.css`, and no committed test checks the correspondence — the implementer verified it once by hand ("17/17") and did not commit the check. Verified clean today (0 undeclared, 0 unused).
- [MEDIUM] No test fetches `/ui/static/tokens.css` over HTTP; `test_ui_html_pages.py::test_css_served` still covers `app.css` alone, and m7's own new guard only stats the file on disk.
- [MEDIUM] The file move invalidated the `links.code` anchors in `plans/ui-uplift/roadmap.yaml` for `ui-uplift-m8` and five other milestones — m8's `.card` anchor now points into the `input` rule. One-writer rule: this is a `/roadmap` fix, not a Phase-4 one.
- [MEDIUM] `.claude/docs/ui-contrast-table.md:97`'s stated reason for dropping the large-text exception is factually wrong — `header h1` is UA-bold and the clamp's minimum is 24px, so the ≥18.66px-bold branch holds at every viewport.
- [MEDIUM] AC#2's "inherits the tabular-nums scope" half is enforced by a four-name hand-list; `pre.error` and the two `--mono` inputs sit outside the rule, which brief-1 §2b row 32 named as exactly this gap.

## Executive summary — milestone-frontend-ux

- [HIGH] `code, time { font-size: var(--text-small) }` is an absolute value, so the
  `<h2><code>slug</code></h2>` on the notebook detail page renders at **13px inside a
  20px heading** — the page subject is now smaller than the body text around it, and
  smaller than it was before m7.
- [HIGH] `latest_run.status` at `notebook_detail.html:71` is a state token still in the
  sans voice. brief-1's own inventory lists it as site #10; m7 fixed sites 28–31 (the
  same token in the ingest fragment) and left this one, so the identical value renders in
  two different voices ~200px apart on one page.
- [MEDIUM] The fluid title lands only on the constant site wordmark ("arXMCP notebooks",
  every page). The largest step in the scale is spent on boilerplate while the page
  subject sits at 20px — discovery's BAN-5 "no focal element" is not removed.
- [MEDIUM] `.status-badge__remediation` is a UA `<small>` nested inside the badge; m7
  shrank the badge 12px → 11px, dragging operator remediation text to roughly 9px — the
  smallest text in the product, on the recovery path.
- [MEDIUM] Prose in mono: `input[type="text"]` puts the `display_name` field in `--mono`,
  contradicting m7's own textarea reasoning ("topic text is prose, not an identifier").
- [MEDIUM] The discover-results panel gets no hierarchy at all — candidate title and
  abstract both render at 16px, typographically identical.
- [MEDIUM] This agent's trigger definition can never fire in this repo, leaving the most
  visual milestone track without a UX gate by default.
- [LOW] Two text surfaces remain off the token scale entirely (`.card .empty`, `footer >
  small`), and the SC 1.4.4 comment overstates the mid-band case.

## Findings

**H1 — `<h2><code>slug</code></h2>` now renders at 13px, under body** (HIGH)

**Where:** `server/frontend/static/app.css:195`
**Anchor:** `code, time { font-family: var(--mono); f`
**What:** The new rule sets an unconditional `font-size: var(--text-small)` (13px) on every `<code>`, and `notebook_detail.html:9` is `<h2><code>{{ notebook.slug }}</code></h2>` — the detail page's primary heading, whose entire text content is that `<code>`, so the heading renders at 13px inside a 20px box while `.card h2 { font-size: var(--text-section) }` styles nothing visible.
**Why it matters:** AC#1 requires the section step to carry hierarchy by size; on this page the rendered step is 13/16 = **0.81×** — the heading is now *smaller* than body text and only 2px above the 11px micro-caps floor — and it is a regression from the 17.6px it inherited pre-m7 (the `.card h2` 1.1rem length reset Blink's keyword-derived monospace-size quirk, so the pre-m7 `<code>` inherited the full heading size).
**Proposed fix:** Add a single scoped override next to the `code, time` rule, e.g. `.card h2 code { font-size: inherit; }` (or `h1 code, h2 code { font-size: inherit; }` to cover any future heading identifier). `font-family: var(--mono)` and the tabular-nums scope both still apply, so AC#2 is unaffected; only the size is restored. Two lines, and app.css has exactly two lines of headroom under the 480 cap — see M1, which should be resolved first or in the same pass.
**Regression-guard:** In `tests/test_ui_m7_type_scale.py::TestAC1HeadingStep`, add a test that scans both templates for `<code>` inside an `<h1>`/`<h2>` and asserts app.css carries a matching `font-size: inherit` (or a `--text-section`-or-larger step) for that context — i.e. no identifier element inside a heading may resolve to a step below `--text-body`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H2 — AC#2 inventory site 10: the `latest_run.status` state token is still sans** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:71`
**Anchor:** `<span class="hint">(ingest {{ latest_run.s`
**What:** brief-1 §2a row 10 lists this state token as `mono today: NO / tabular-nums today: NO`; the diff wrapped the state tokens in `_ingest_status_fragment` (sites 28–31) and every `<code>`/`<time>` surface, but left this one bare — it takes neither `--mono` nor the tabular-nums scope.
**Why it matters:** AC#2 is verbatim "Given any identifier surface (paper id, slug, path, timestamp, corpus version, **state token**), when rendered, then it uses `--mono` and inherits the existing tabular-nums scope" — one enumerated site unmet makes the criterion unmet, and a partial inventory is this track's documented recurring failure (it is how three AA failures shipped and what ui-uplift-m6 critique H3 caught).
**Proposed fix:** Wrap the value only, leaving the prose sans, exactly as `_ingest_status_fragment` now does: `<span class="hint">(ingest <code>{{ latest_run.status }}</code>)</span>`. One line; `code` already carries both `--mono` and tabular-nums, so no CSS change is needed. Note the template also loses the size step to H1's 13px `code` rule inside a 13px `.hint`, which is a no-op here.
**Regression-guard:** Extend `tests/test_ui_m7_type_scale.py::TestAC2IdentifierSurfaces` with a template scan asserting that no Jinja expression whose name matches `*status*` / `*state*` renders outside a `<code>`/`.status-badge` wrapper in `notebook_detail.html` and `index.html`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H3 — `<h2><code>` slug heading renders at 13px, inverting AC#1** (HIGH)

**Where:** `server/frontend/static/app.css:195`
**Anchor:** `code, time { font-family: var(--mono); f`
**What:** The new `code, time { font-size: var(--text-small) }` rule sets an explicit 13px on the `<code>` element, and `server/frontend/templates/notebook_detail.html:9` is `<h2><code>{{ notebook.slug }}</code></h2>` inside `<section class="card">`, so the notebook-detail page's primary heading renders at 13px — smaller than the 16px body and 0.65× the 20px sibling `<h2>`s ("Topic & discovery", "Ingest", "Papers in this notebook") on the same page.
**Why it matters:** AC#1's stated purpose is that "size carries the hierarchy"; this commit raised `.card h2` to `--text-section` (20px) and in the same commit authored a rule that overrides it to the smallest step on the one heading that names the notebook, so the milestone's headline criterion is contradicted on the console's main page. `.card h2` sets font-size on the `<h2>`; the `code` rule sets it on the `<code>` child, so the inherited 20px never applies — no specificity contest is involved. Pre-m7 the `<code>` carried no author font-size (`table code` was table-scoped), so the discrepancy is authored here, not inherited.
**Proposed fix:** Add one rule after `:195` restoring inheritance for headings, e.g. `h1 code, h2 code { font-size: inherit; }` — 1 line, inside the 480-line cap, and it leaves every other `<code>` on the 13px step. The alternative (making the mono step relative, `font-size: 0.8125em`) also fixes it but silently rescales `<code>` inside `dl.meta dd` and `td`, so the heading-scoped override is the smaller change.
**Regression-guard:** In `tests/test_ui_m7_type_scale.py::TestAC1HeadingStep`, add a test that reads `notebook_detail.html`, asserts the detail-page `<h2>` wraps its slug in `<code>`, and asserts `app.css` carries a heading-scoped `code { font-size: inherit }` (or equivalently that no rule sets a smaller absolute size on a `<code>` inside a heading). It fails on the current tree.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H4 — Diff is 7× the declared scope tripwire and the abort branch was declined** (HIGH)

**Where:** no specific file
**What:** The implement dispatch set a ~400-insertion / ~14-file tripwire with an explicit "stop, commit `partial — scope exceeded`, and return" branch; the landed range is 2745 insertions / 189 deletions across 23 files (code-only ≈987+/140- across 13 files, plus 636 new-file lines that do not appear as diff insertions), and the implementer declared the overrun and proceeded anyway.
**Why it matters:** Per the critique format's own calibration anchor, a diff over 400 LOC is a HIGH; a diff at this size defeats the per-hunk review the Phase-3 critics exist to perform, which is visible in this critique — H1 is a two-token interaction between a CSS rule and a template line that a 400-line diff would have surfaced immediately.
**Proposed fix:** Nothing to change in the code. Record the overrun on `state.json` and, for the next UI milestone, split the mechanical file move (tokens.css + the six test-module re-pointings) from the behavioural type-scale change so each lands under its own tripwire.
**Regression-guard:** The orchestrator's diff-size gate at Phase 2 exit; no test change.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H5 — Mono `<code>` shrinks the detail page's own heading to 13px** (HIGH)

**Where:** `server/frontend/static/app.css:195`
**Anchor:** `code, time { font-family: var(--mono); f`
**What:** The new rule sets an absolute `font-size: var(--text-small)` (13px), and because `notebook_detail.html:9` is `<h2><code>{{ notebook.slug }}</code></h2>`, the `<code>` child overrides the inherited 20px `.card h2` size and renders the notebook identity — the page's entire subject — at 13px, smaller than the 13px table text it sits above and smaller than the ~15px it rendered at before m7 (when it fell through to UA generic monospace at ~0.85em of a 17.6px heading).
**Why it matters:** The milestone's headline claim is that "size carries the hierarchy"; on the console's primary working page the size signal now points the wrong way, so the operator's first eye-stop is the boilerplate wordmark rather than which notebook they are looking at.
**Proposed fix:** Make the identifier step relative rather than absolute so it composes with whatever context it lands in, or add one contextual override. Cheapest correct patch is a single extra rule after `:195`: `.card h2 code { font-size: inherit; }` — the heading keeps `--text-section`, the mono *face* still marks it as an identifier, and every other `<code>` in the product is unaffected. The more general alternative is `code, time { font-size: 0.8125em }` (em, not rem), which self-scales in every context but re-opens the "monospace renders smaller" quirk the m7 comment at `:188-191` was closing — prefer the scoped override.
**Regression-guard:** Extend `tests/test_ui_m7_type_scale.py::TestAC2IdentifierSurfaces` with a test asserting that no rule gives a `<code>` inside a heading a smaller computed size than its heading — concretely, assert an `h2 code`-scoped rule exists whose `font-size` is `inherit`/`1em`, and pair it with a negative assertion that `.card h2` still carries `var(--text-section)` so the two cannot silently diverge.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**H6 — State token `latest_run.status` left in the sans voice** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:71`
**Anchor:** `<span class="hint">(ingest {{ latest_run`
**What:** AC#2 requires `--mono` on every id, path, slug, timestamp, corpus version and state token; this renders the ingest run's state token as bare prose inside `<span class="hint">`, so it stays sans at 13px while m7 wrapped the identical values (`running` / `success` / `failed`) in `<code>` in `_ingest_status_fragment` further down the same page.
**Why it matters:** brief-1 §2 enumerates this as inventory site #10 with "`--mono` today: NO", so it is a known-and-skipped site rather than an oversight the inventory missed — and the result is one value class rendering in two voices on one screen, which is precisely the inconsistency the two-voice split exists to end.
**Proposed fix:** Wrap the interpolation in `<code>`, matching the fragment builder: `<span class="hint">(ingest <code>{{ latest_run.status }}</code>)</span>`. The surrounding "(ingest …)" prose stays sans, which is the same split `_ingest_status_fragment` already implements. One line; no CSS change, since `code` already carries `--mono` and tabular-nums.
**Regression-guard:** Add a test asserting the template and `_ingest_status_fragment` agree on the wrapper for the run-state token — the same "fragment and template must agree" invariant `test_paper_row_fragment_agrees_with_the_template_it_appends_to` already encodes for D4, applied to the status token.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**M1 — Cap comment says app.css "471 to ~400"; it is 478 of 480** (MEDIUM)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:588`
**Anchor:** `# which dropped app.css from 471 to ~400`
**What:** `wc -l server/frontend/static/app.css` is 478; the split removed ~47 token lines and the milestone added ~54 rule/comment lines, so the file moved 471 → 478, which is what the implement synthesis itself records ("app.css went 471 → 478").
**Why it matters:** The same comment block declares the tokens.css split "spent" as a future escape hatch, so the next reader is told there are ~80 lines of headroom when there are **2** — and H1's fix needs one of them. A wrong number here is the same class of defect as m6 critique H2 (hand-typed facts outside a generated region), just inside a test file instead of a doc.
**Proposed fix:** Replace "~400" with the real 478 in all three cap-test comment blocks that mention it (m3 is the long one; m4/m5 carry the short form), and state the residual headroom explicitly — e.g. "471 → 478, i.e. the type scale fit inside the existing ceiling with 2 lines to spare; the next milestone raises the cap on the merits." Consider raising to 500 in the same pass so H1 is not blocked on a 2-line budget.
**Regression-guard:** Optional — a `test_cap_comment_quotes_the_real_line_count` that greps the three comment blocks for a number and asserts it equals the measured count would make this class self-checking.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M2 — Re-floor rationale for `header h1 a` is wrong: the title is bold** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:102`
**Anchor:** `viewport-dependent: 24px at a 390px view`
**What:** The stated reason for dropping `header h1 a` from the 3:1 large-text floor to 4.5:1 is that a clamp makes the size viewport-dependent — but `header h1` inherits the UA `font-weight: bold` (brief-1 §1c), so the applicable threshold is 18.7px, and the clamp's minimum is 24px, which clears it at every viewport width.
**Why it matters:** The document contradicts itself eleven lines later by granting that 20px bold `.card h2` "*would* qualify for the ≥18.7px-bold branch"; a canonical accessibility record that reasons incorrectly about which SC applies is the thing this file exists to prevent, and the same wrong rationale is duplicated in `tests/test_ui_contrast.py`'s module docstring and the `LARGE`-removal comment. (The *outcome* is safe and should stand — a stricter floor is never wrong — and there is a correct reason available: a `rem`-based minimum shrinks with a reduced root font size, so 1.5rem at a 12px root is 18px, under the bold threshold. That is root-size dependence, not viewport dependence.)
**Proposed fix:** Amend the three sites to the real mechanism: keep the 4.5:1 floor, but say the exception is declined because the clamp's minimum is expressed in `rem` and therefore not guaranteed above 18.7px under a non-default root font size — not because it varies with viewport width. Two-sentence edit in the doc plus the mirrored comments in `tests/test_ui_contrast.py:20-30` and `:71-80`.
**Regression-guard:** Not required (prose correction).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M3 — 11px badge shrinks its nested remediation `<small>` to ~9.2px** (MEDIUM)

**Where:** `server/frontend/static/app.css:232`
**Anchor:** `  font-size: var(--text-meta);`
**What:** `.status-badge` moves 0.75rem (12px) → `--text-meta` (11px), and `server/routes/ui.py:335` emits `<small class="status-badge__remediation">` **inside** that span; the class has no CSS rule (it is in `_KNOWN_UNSTYLED`), so the UA `small { font-size: smaller }` puts the remediation lines at roughly 0.83 × 11px ≈ 9.2px, down from ~10px.
**Why it matters:** That block is the console's only operator-actionable troubleshooting text (failing check name + the `make` command to heal it), it renders precisely when something is wrong, and the milestone's own rule comment reasons only about the `14ch` coupling — the nested element is not considered anywhere in the diff, the tests, or the synthesis. WCAG sets no minimum font size, so this is legibility rather than a conformance failure; flagged at MEDIUM on that basis, not higher.
**Proposed fix:** Give the class an explicit step rather than letting `smaller` compound: `.status-badge__remediation { font-size: var(--text-meta); }` (11px, matching the badge) — one line, and it also removes one of `_KNOWN_UNSTYLED`'s nine entries.
**Regression-guard:** Optional — assert in `tests/test_ui_m7_type_scale.py` that no rule nests a `--text-meta` element inside another `--text-meta` element without an explicit size, or simply pin the new declaration.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M4 — Contrast doc hand-types the wrong size for form controls** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:111`
**Anchor:** `small 13px (labels, captions, controls, `
**What:** The m7 size enumeration lists "controls" under the 13px step, but only `button, .button` is `--text-small`; `input[type="text"|"url"|"file"]`, `select` and `textarea` are all `--text-body` (16px) after this diff — and they were 0.95rem (15.2px) before it, so the milestone moved them *up*, not down.
**Why it matters:** This is newly-written prose outside all three generated markers, in the document whose stated purpose is that no fact about the stylesheet is hand-typed; `test_published_region_is_current` cannot see it. It is the same failure mode as the two claims the orchestrator already had to fix post-merge in this file, which is why it should be assumed there are more rather than fewer.
**Proposed fix:** Split the clause: "small 13px (labels, captions, buttons, table cells, and every identifier in `code`/`time`), body 16px (**text/URL/file inputs, `select`, `textarea`**, `.display-name`)". While there, the enumeration also omits `header .subtitle` and `.breadcrumb`, both 13px.
**Regression-guard:** Not required (prose correction).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M5 — Identifier inventory site 10 left in the sans voice, undeclared** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:71`
**Anchor:** `        <span class="hint">(ingest {{ la`
**What:** `(ingest {{ latest_run.status }})` renders the ingest state token as bare prose in the sans voice; brief-1 §2b lists it as inventory row 10 with `--mono` NO and tabular-nums NO, and the implement synthesis names sites 20–21 and 28–31 as closed while never mentioning site 10 in either "Built" or "Deferred".
**Why it matters:** AC#2 is "every identifier surface uses `--mono`", and this is the same `latest_run.status` value that `_ingest_status_fragment` now renders as `Status: <code>success</code>` — both are visible simultaneously on the notebook-detail page, so the milestone created a second same-datum-two-voices site of exactly the class D4 existed to eliminate.
**Proposed fix:** Wrap the interpolation: `(ingest <code>{{ latest_run.status }}</code>)`. One template edit; `code` already carries `--mono` and the tabular-nums scope.
**Regression-guard:** Extend `tests/test_ui_m7_type_scale.py::TestAC2IdentifierSurfaces` with an assertion that `notebook_detail.html` renders `latest_run.status` inside `<code>`, mirroring `test_ingest_status_fragment_wraps_its_identifiers`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M6 — Cross-file `var()`↔token correspondence has no committed guard** (MEDIUM)

**Where:** `tests/test_ui_m7_type_scale.py:444`
**Anchor:** `    def test_every_stylesheet_base_html_l`
**What:** After the split, every `var(--x)` in `app.css` resolves against a declaration in a different file, and nothing in the suite checks the correspondence in either direction; the implement synthesis reports the check as a one-off "CSS structural check … every token declared is used and every token used is declared (17/17)" that was run by hand and not committed.
**Why it matters:** An undeclared `var(--text-sektion)` typo or a token rename in `tokens.css` degrades silently to the property's initial value — no CSS error, no test failure, and the source checkout renders the same as production. `test_no_font_size_literal_survives_in_the_rule_sheet` only asserts a value starts with `var(`, so a typo'd name passes it; the milestone's own comment identifies exactly this failure mode ("renders every var() as its initial value") and then guards only the packaging half of it.
**Proposed fix:** Commit the check the implementer already ran, in `TestTokensCssSplit`: parse `(--[\w-]+)\s*:` out of comment-stripped `tokens.css` and `var\((--[\w-]+)\)` out of both files, then assert `used - declared == set()` and `declared - used == set()`. Both are empty on the current tree (verified), so it lands green.
**Regression-guard:** The test above, `tests/test_ui_m7_type_scale.py::TestTokensCssSplit::test_every_var_resolves_to_a_declared_token`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M7 — `tokens.css` is never fetched over HTTP by any test** (MEDIUM)

**Where:** `tests/test_ui_html_pages.py:218`
**Anchor:** `    def test_css_served(self, client: Te`
**What:** `TestStaticAssets::test_css_served` fetches `/ui/static/app.css` and asserts 200 + `text/css`; no sibling exists for `tokens.css`, and m7's new `test_every_stylesheet_base_html_links_actually_exists` only asserts the file is present on disk under `server/frontend/static/`.
**Why it matters:** The milestone's own rationale for the packaging work is that a missing token sheet produces "a 404 whose only symptom is that every var() silently falls back to its initial value" — the route-level half of that failure mode is now the only stylesheet delivery path with no assertion behind it, and the synthesis explicitly decided this file needed "no change".
**Proposed fix:** Parameterise the existing test over the two hrefs, or add four lines: `r = client.get("/ui/static/tokens.css"); assert r.status_code == 200; assert "text/css" in r.headers["content-type"]; assert ":root" in r.text`.
**Regression-guard:** `tests/test_ui_html_pages.py::TestStaticAssets::test_tokens_css_served`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M8 — The file move invalidated six `links.code` anchors in the ui-uplift roadmap** (MEDIUM)

**Where:** `plans/ui-uplift/roadmap.yaml:351`
**Anchor:** `      code: ["server/frontend/static/ap`
**What:** Moving ~180 lines of `:root` out of the top of `app.css` and adding derivation comments below shifted every line in the file, so the `links.code` anchors re-derived by the last `/roadmap` pass no longer point at what they name. Measured against the post-diff file: `ui-uplift-m8`'s `app.css:85-91` was `.card { … }` (now at `:50-56`) and is now the middle of the `input` rule; its `app.css:110-120` was the `input` rule (now `:81-91`) and is now `button, .button`. The same shift breaks `ui-uplift-e1` (`33-50`, `85-91`), `ui-uplift-m11` (`:100`, was `.card .empty`, now at `:71`), `ui-uplift-m15` (`385-409`), `ui-uplift-m16` (`110-120`) and `ui-uplift-m17` (`451-454`, was the `::view-transition` rule, now at `:458-461`).
**Why it matters:** `ui-uplift-m8` is the immediate successor (`depends_on: [ui-uplift-m6, ui-uplift-m7]`, lane `next`) and its whole subject is retiring `.card`; its two anchors now name neither `.card` nor anything m8 touches, so the next implementer's first read lands on the wrong rules. m8's substantive preconditions DO still hold — light `--border` on `--bg` is 3.312:1 (≥3:1, `test_light_border_clears_three_to_one_on_bg` green) and the m7 type scale has shipped — so this is anchor drift, not a sequencing block.
**Proposed fix:** Not fixable from Phase 4 — the pipeline's one-writer rule forbids editing `plans/*/roadmap.yaml` from a milestone. Hand this to `/roadmap` to re-derive all six anchor sets against the post-m7 `app.css`, and consider anchoring by selector text rather than line range so a file move stops invalidating them.
**Regression-guard:** Optional (MEDIUM). A `/roadmap` validator that resolves each `links.code` line range and warns when the cited range contains no selector named in the milestone's summary would close the class.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M9 — The large-text-exception rationale in the canonical contrast doc is wrong** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:97`
**Anchor:** `**No row claims WCAG's large-text excep`
**What:** The doc justifies re-flooring `header h1 a` from 3:1 to 4.5:1 on the grounds that "a viewport-agnostic registry cannot honestly carry a floor that holds only at some widths" — but `header h1` inherits the UA `font-weight: bold` and the clamp's minimum term is `1.5rem` = 24px, so WCAG's large-scale branch (≥18.66px bold) is satisfied at **every** viewport, not merely some. The same reasoning is reproduced verbatim in `tests/test_ui_contrast.py:24-32` and in the `LARGE` constant's replacement comment at `:71-81`.
**Why it matters:** §4.9 binds every arXMCP planning/analysis document, and this is the canonical accessibility record consulted by `ui-uplift-m8`; a stated reason that does not survive checking is the same defect class m6's critique closed when it found 9 of 12 hand-typed ratios wrong. The outcome is conservative and safe — the row passes at 16.032:1 / 13.931:1 against the stricter floor — so nothing measured is wrong, only the reason given for measuring it that way.
**Proposed fix:** Replace the false premise with the true one in all three places: the exception still applies at every viewport (24px minimum, UA bold), and the row is held to 4.5:1 anyway because a registry that keys a floor off a rendered size it does not itself compute cannot verify the precondition — which is the same argument the `LARGE` comment already makes ("an exemption whose precondition nothing checks is unbacked"). Text-only edits; no generated region moves.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M10 — AC#2's tabular-nums half is spot-checked, and three `--mono` surfaces are outside it** (MEDIUM)

**Where:** `server/frontend/static/app.css:208`
**Anchor:** `time, code, .status-badge, dl.meta dd {`
**What:** `pre.error` (`app.css:218`, `font-family: var(--mono)`) and `input[type="text"], input[type="url"]` (`app.css:92`, same) carry the mono voice but are not in the single tabular-nums rule. brief-1 §2d defines the criterion operationally — "every surface m7 gives `--mono` must either already match one of those four selectors, or be added to that selector list" — and brief-1 §2b row 32 names `<pre class="error">` as mono-YES / tabular-NO. The only guard, `test_tabular_scope_is_one_rule_covering_code_and_time`, asserts four selector names are present and cannot see a fifth mono surface appearing outside the rule.
**Why it matters:** AC#2 as written is not fully met, and nothing would catch the next mono surface that lands outside the scope — the same "partial inventory" failure mode `test_ui_contrast.py`'s docstring warns about for `PAIRS`. The rendering impact is near zero (all three sites use a monospace stack, whose digits already have uniform advance), which is why this is MEDIUM and not HIGH — but that fact is nowhere recorded, so a later reader cannot tell a considered omission from an oversight.
**Proposed fix:** Either add `pre.error, input[type="text"], input[type="url"]` to the `:208` selector list, or — better, since the property is a no-op on a monospace stack — record that reasoning in the rule's comment and add a derived guard: collect every selector in `app.css` whose block contains `font-family: var(--mono)` and assert each is either in the tabular-nums selector list or in an explicit, commented allow-list.
**Regression-guard:** `tests/test_ui_m7_type_scale.py::TestAC2IdentifierSurfaces::test_every_mono_surface_is_in_or_allow_listed_out_of_the_tabular_scope`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M11 — The fluid title is spent on the constant site wordmark** (MEDIUM)

**Where:** `server/frontend/templates/base.html:72`
**Anchor:** `<h1><a href="/ui/">arXMCP notebooks</a><`
**What:** `--text-title` (24→36px, the scale's largest step) is applied only to `header h1`, which is the string "arXMCP notebooks" on *every* page; no page's actual subject ever receives it, so on `notebook_detail.html` a 36px boilerplate wordmark sits above a 20px `<h2>` (13px in practice — see H1) carrying the notebook identity.
**Why it matters:** The discovery listed BAN-5 "no focal element" under "must be removed" and adopted D-1, whose thesis is that the console shows the corpus first; making the brand the single largest element on every page leaves BAN-5 in place and reads as the "default stack" tell the milestone is meant to retire.
**Proposed fix:** Give `base.html` a `{% block page_title %}` inside `<header>` that defaults to the wordmark and is overridden on the detail page with the notebook slug, then move `--text-title` onto that block and drop `header h1` to `--text-section`. If restructuring the header is out of appetite for this milestone, the minimum honest alternative is to state in `tokens.css` that `--text-title` is a brand step rather than a page-title step, so the canon-deviation note is not describing a role the token does not actually play.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**M12 — Badge remediation text drops to roughly 9px** (MEDIUM)

**Where:** `server/routes/ui.py:336`
**Anchor:** `f'<small class="status-badge__remediatio`
**What:** The remediation block is a `<small>` nested inside `<span class="status-badge">`; the badge carries an absolute `--text-meta` (11px) and `.status-badge__remediation` has no CSS rule of its own, so the UA's `small { font-size: smaller }` computes it to roughly 8.8–9.2px — and m7 moved the badge from `0.75rem` (12px) to `--text-meta` (11px), so this diff made it about 0.8px smaller than it was.
**Why it matters:** This block names the failing check and the `make` command to heal it — it is the text an operator reads specifically when the system is degraded, and it is now the smallest text in the product, set below the scale's own floor by a UA rule rather than by any authored decision.
**Proposed fix:** Give the class an explicit step so it stops riding the UA `smaller` keyword — `.status-badge__remediation { font-size: var(--text-small); display: block; }` puts it at 13px on the scale and stacks it under the badge label instead of inline. Note this requires deleting `status-badge__remediation` from `_KNOWN_UNSTYLED` in `tests/test_ui_class_css_coverage.py` in the same commit, which is exactly the shrink that list is designed for.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

**M13 — Prose rendered in the mono voice on the display-name inputs** (MEDIUM)

**Where:** `server/frontend/static/app.css:92`
**Anchor:** `input[type="text"], input[type="url"] { f`
**What:** The selector is too coarse for the two-voice rule: it correctly puts `name="slug"` and `name="paper_id"` in `--mono`, but it also catches `name="display_name"` on `index.html:36` and `notebook_detail.html:41`, which is free prose ("Bridgeland stability conditions") typed and read in monospace.
**Why it matters:** This is the second failure direction the two-voice split is supposed to close, and m7 explicitly reasoned about it in the other case — `app.css:100` justifies excluding `textarea` because "topic text is prose, not an identifier" — so the same value class is being treated two different ways within one stylesheet.
**Proposed fix:** Scope the mono voice to the identifier inputs by name rather than by type: replace the selector with `input[name="slug"], input[name="paper_id"], input[type="url"]` and let `display_name` inherit the sans body font. The rule pre-dates m7, but AC#2 is the audit that owns it.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**M14 — The discover-results panel receives no hierarchy from the scale** (MEDIUM)

**Where:** `server/routes/notebooks.py:732`
**Anchor:** `f'<p class="discover-title">{html.escape`
**What:** A discovered candidate's title and its abstract are both bare `<p>` elements with no styled class, so both render at the 16px body step and are typographically indistinguishable; only `.discover-meta`'s inner `<code>`/`<time>` pick up anything from m7, via the element rules.
**Why it matters:** This is the one surface in the console that is a list of *content* rather than a list of records, so it is where a type scale should be most visible — and it is the clearest answer to "where does the page still look uniform" after this milestone.
**Proposed fix:** When `ui-uplift-m10` picks up the `discover-*` half of the BAN-R2 debt, it should consume this scale rather than author sizes: `.discover-title { font-size: var(--text-section); line-height: 1.25; }` and `.discover-abstract { font-size: var(--text-small); }`. Recorded here so m10 inherits the constraint; m7 correctly left the classes alone rather than colliding with `_KNOWN_UNSTYLED`.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**M15 — This critic's trigger definition can never fire in this repo** (MEDIUM)

**Where:** `.claude/agents/milestone-frontend-ux.md:6`
**Anchor:** `  a \`.tsx\`, \`.jsx\`, \`.vue\`, or \`.svelte\` fi`
**What:** The frontmatter fires only on `.tsx` / `.jsx` / `.vue` / `.svelte` component files, and Step 0 instructs the agent to return `not-applicable` when the diff contains none — but CLAUDE.md §4.7 bars Node and any build chain, so this repo has zero such files by construction and will never have one.
**Why it matters:** Taken literally the gate is unreachable here, so every frontend milestone in the `ui-uplift` / `ui-attractive-polish` track would ship with no UX review unless an orchestrator overrides the trigger by hand, as happened for this dispatch.
**Proposed fix:** Widen the trigger to include server-rendered frontend surfaces — add `.css`, and `.html` / `.jinja` / `.j2` under a `frontend/` or `templates/` path prefix — and amend the Step 0 exit-fast check to match, so the "do not manufacture findings" guard still holds for genuinely backend diffs. Keeping the path-prefix requirement preserves the original intent of not firing on unrelated `.html` fixtures or docs.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L1 — The font-size / letter-spacing guards need a trailing semicolon** (LOW)

**Where:** `tests/test_ui_m7_type_scale.py:124`
**Anchor:** `for v in _re.findall(r"font-size:\s*([^`
**What:** Both `test_no_font_size_literal_survives_in_the_rule_sheet` and `test_letter_spacing_only_appears_via_the_token` match `<prop>:\s*([^;]+);`, so a declaration that is last in its block and omits the optional trailing `;` (valid CSS) escapes the scan entirely, as does the `font:` shorthand.
**Why it matters:** These two are the whole mechanical enforcement of AC#4's "everything is on the scale" and of keeping tracking tokenised; a hand-typed `th { …; font-size: 11px }` would pass today.
**Proposed fix:** Change the pattern to `<prop>:\s*([^;}]+)` and add `\bfont:\s` to a companion refusal assertion.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**L2 — UPL-27 pill comment still names the pre-m7 badge size** (LOW)

**Where:** `server/frontend/static/app.css:247`
**Anchor:** `/* UPL-27: #1a7f37 on #e6f4ea is 4.472:1`
**What:** The comment reads "under SC 1.4.3 at 0.75rem/600", but this diff moved `.status-badge` from `0.75rem` to `--text-meta` (11px); the sibling `.card .note` comment WAS de-sized in the same commit ("at italic caption size"), so the file is now inconsistent about it.
**Why it matters:** A comment naming a size the stylesheet no longer declares invites a future reader to re-derive against the wrong number; the SC verdict is unchanged (11px is still below every large-text threshold), so this is drift, not a contrast error.
**Proposed fix:** Apply the same treatment the `.card .note` comment got — replace "at 0.75rem/600" with "at badge size / 600".
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L3 — Contrast-test docstring still claims 67 pairs; the register says 91** (LOW)

**Where:** `tests/test_ui_contrast.py:19`
**Anchor:** `cells; this one covers 67 rendered pairs.`
**What:** The generated headline in `.claude/docs/ui-contrast-table.md:34` reports 91 pairs (48 light, 43 dark); the module docstring three lines above prose m7 rewrote still says 67.
**Why it matters:** Pre-existing (the count grew during m6's rectify), but m7 edited the immediately-following paragraph of the same docstring and left it — the cheapest possible moment to fix it passed, and a stale count in the gate's own docstring undercuts the "the inventory is small, reviewable, and reviewed" claim this module rests on.
**Proposed fix:** Replace "67" with "91", or better, drop the number and point at the generated Headline so it cannot drift again.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L4 — Vacuous sub-assertion in the canon-deviation test** (LOW)

**Where:** `tests/test_ui_m7_type_scale.py:256`
**Anchor:** `            assert block is not None`
**What:** `block = _re.search(r"--text-title:.*", TOKENS_CSS)` can only be `None` if `--text-title:` is absent from the file, which line 253's `BASE_TOKENS["--text-title"]` would already have raised `KeyError` on — so the assertion cannot fail, and `block` is never used afterwards.
**Why it matters:** This is the `vacuous-test-kept-as-documentation` family the repo has recorded before (m6's favicon test that passed on an XML comment); a reader counting assertions over-estimates the guard's strength.
**Proposed fix:** Delete lines 255–256 and keep only the `"DECLARED DEVIATION" in TOKENS_CSS` assertion, which is the real check.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L5 — `test_time_elements_take_the_mono_voice` never checks `--mono`** (LOW)

**Where:** `tests/test_ui_m7_type_scale.py:289`
**Anchor:** `    def test_time_elements_take_the_mono`
**What:** The test asserts only that a `code, time {` selector exists; it never inspects the rule body, so it is a strict subset of `test_mono_is_applied_by_element_not_by_table_position` two methods above and would pass on `code, time { color: red }`.
**Why it matters:** Its name and docstring claim to guard the "`<time>` was never `--mono` at all" fix, and it does not.
**Proposed fix:** Either assert `"var(--mono)"` in the captured block, or delete the test and let the sibling carry the guarantee.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L6 — Empty `<time></time>` emitted when `started_at` is unset** (LOW)

**Where:** `server/routes/notebooks.py:2371`
**Anchor:** `            f" · Started <time>{html.esc`
**What:** `started_at or ''` can yield `<time></time>`; a `<time>` element with no `datetime` attribute must have machine-readable text content, so the empty case is invalid HTML. Pre-m7 the same branch emitted bare text and had no such constraint.
**Why it matters:** Minor validity regression introduced by the identifier wrapping; the rendered output is a stray "Started ·" with nothing after it either way.
**Proposed fix:** Emit the `<time>` wrapper only when the value is truthy, or add `datetime="{escaped}"` alongside the text so the element is well-formed in both branches.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L7 — The per-surface size enumeration omits three 13px surfaces** (LOW)

**Where:** `.claude/docs/ui-contrast-table.md:110`
**Anchor:** `Sizes under the m7 scale, for the record`
**What:** "small 13px (labels, captions, controls, table cells, and every identifier in `code`/`time`)" does not account for `header .subtitle` (`app.css:42`), `.breadcrumb` (`:47`) or `pre.error` (`:219`), all of which also land on `--text-small`.
**Why it matters:** The paragraph is the doc's record of which WCAG floor applies to which rendered size; an incomplete enumeration in the artifact whose thesis is "a partial inventory is how three AA failures shipped" is the same shape of gap, even though no floor changes here (all three are already registered pairs at 4.5:1).
**Proposed fix:** Add the three surfaces to the parenthetical, or restate the sentence as "every surface not named above" so it cannot go stale by omission.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**L8 — The new `REQUIRED_INSTALLED_FILES` entry was never executed** (LOW)

**Where:** `tools/wheel_install_check.py:125`
**Anchor:** `    "server/frontend/static/tokens.css",`
**What:** This list is reached only through `make wheel-check` or the `requires_wheel_build`-marked `TestCleanEnvironmentInstall`, both opt-in; the implementer explicitly skipped `make wheel-check`, so the entry has never run. The implement synthesis states the opposite — "the two static packaging assertions (glob match + `REQUIRED_FILES`) run in the default suite" — which is true of the `pyproject` glob assertion in `TestPackageDataCoversEveryDataFile` and false of this one.
**Why it matters:** CLAUDE.md §4.5b calls this the invisible-from-source class and m7 added a new shipped data file; the residual risk is small because the glob half IS covered in the default suite and now names `tokens.css`, but the synthesis's gate claim is inaccurate.
**Proposed fix:** Run `make wheel-check` (~10 s per §4.5b) once and record the result, and correct the synthesis sentence to name only the assertion that actually runs by default.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability

**L9 — Post-split naming drift in the contrast artifact and its generator** (LOW)

**Where:** `.claude/docs/ui-contrast-table.md:1`
**Anchor:** `# UI contrast table — ui-uplift-m6`
**What:** The artifact's title still reads "— ui-uplift-m6" although its body, floors table and cross-references were all rewritten for m7, and `tests/test_ui_contrast.py:1`'s module docstring still calls itself "the WCAG gate over EVERY rendered pair in **app.css**" now that the tokens it parses live in `tokens.css`.
**Why it matters:** Both are the entry point a future reader hits first, and both now name the wrong milestone / wrong file.
**Proposed fix:** Retitle to "UI contrast table — ui-uplift-m6/m7" (or drop the milestone suffix, since the doc is now cumulative) and change the generator docstring's "in app.css" to "in the operator console's stylesheets".
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**L10 — Two text surfaces remain off the token scale** (LOW)

**Where:** `server/frontend/static/app.css:71`
**Anchor:** `.card .empty { color: #666; font-style:`
**What:** `.card .empty` has no `font-size` at all, so the empty-state line renders at the 16px body step — larger than the 13px `.hint` above it and the 13px table rows it replaces; `footer > small` in `base.html:83` likewise has no authored size and rides the UA `small` keyword to ~12.8px.
**Why it matters:** The milestone's claim is that all 19 previously-untokenised `font-size` declarations now reference a token, which is true — but these two surfaces are sized by the UA rather than by a *declaration*, so they sit outside both the claim and the guard `test_no_font_size_literal_survives_in_the_rule_sheet` provides.
**Proposed fix:** Add `font-size: var(--text-small)` to `.card .empty` so an empty table reads as quieter than a full one rather than louder, and add a `footer { font-size: var(--text-small) }` rule so the footer stops depending on UA `small` scaling. Both are one-line additions inside the existing 480-line cap.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L11 — The SC 1.4.4 comment is stronger than the mid-band behaviour** (LOW)

**Where:** `server/frontend/static/tokens.css:90`
**Anchor:** `     viewport and at 36px above 700px. I`
**What:** The comment states the clamp "clears SC 1.4.4 on both counts"; that is accurate wherever the clamp is pinned to its `rem` min or max (below 400px and above 700px, which is every real operator viewport), but in the 400–700px band the preferred term governs and a 200% text-size request yields roughly 1.29× growth, not 2×.
**Why it matters:** The construction is the correct and commonly-recommended mitigation, and `test_clamp_satisfies_the_resize_text_criterion` checks exactly the right structural properties — but the unqualified prose will be trusted verbatim by the next reader, and this token block is otherwise scrupulous about stating where a claim stops.
**Proposed fix:** Qualify the sentence — note that the guarantee is carried by the `rem` bounds, which govern at every viewport outside the 400–700px fluid band, and that inside that band the `0.5rem` term supplies partial rather than full scaling. No value change; the number is right.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

## What was done well

### From milestone-adversary-critic

- **D1's failure modes were closed, not just its happy path.** `load_tokens` / `load_raw_tokens` raise `RuntimeError` naming `tokens.css` when either `:root` block is absent, and a missing file raises at `read_text` — the "silently returns an empty table while the AA gate stays green" scenario the dispatch flagged as highest-risk cannot occur. `_BASE_ROOT_RE` is column-anchored (`^:root`), so the indented dark block cannot be mistaken for the base one.
- **The split was given a structural guard, not just a line cap.** `test_tokens_css_declares_only_root_blocks` strips the two `:root` blocks and their `@media` wrapper and asserts no `{` survives — that is the property that actually keeps tokens.css from becoming a second stylesheet, and it is stronger than the 200-line bound beside it.
- **Packaging was verified rather than assumed, and the verification found a real hole.** The `*.css` glob and the wholesale `COPY server/` were both checked by running the match; `tokens.css` was independently confirmed missing from `wheel_install_check.py`'s `REQUIRED_INSTALLED_FILES` and added. Both halves of §4.5b's pairing are now named in `tests/test_wheel_packaging.py`. `.dockerignore` excludes nothing under `server/frontend/static/`.
- **Load order is guarded from the template, not from a literal.** `test_every_stylesheet_base_html_links_actually_exists` derives the hrefs from `base.html` and asserts each resolves on disk — the one failure mode a token split introduces whose only symptom is silent `initial`-value rendering. Both `index.html` and `notebook_detail.html` extend `base.html`, and the only other HTML-producing route (`ui_paper_preview`) serves untrusted ar5iv under its own CSP and never loaded app.css, so there is no un-tokenised console page.
- **The `LARGE` constant was removed rather than left dangling,** with the reason recorded (a float-derived SC column conflates two criteria) and a precondition for re-introducing it correctly. No dead reference remains outside the explanatory comments.
- **The oklch guard was widened by an explicit closed allow-list plus a dead-entry test,** not by a "skip anything that isn't a colour" predicate — which would have silently retired m6's AC#1 guarantee the first time someone wrote `--fg: #444`.
- **Two tests were rewritten to their original intent with the old assertion recorded,** and each gained a *stronger* companion (`count(...) == 1` on the tabular-nums scope; an explicit "the slash is not escaped" assertion) rather than being weakened to pass.
- **The D4 fragment/template divergence was fixed with an agreement test, not a shape pin** — asserting that `_paper_row_html` and `notebook_detail.html` emit the same wrappers is the actual invariant, and it is what broke.
- **The clamp arithmetic checks out independently:** at 390px `4vw + 0.5rem` = 23.6px → clamped to the 24px minimum; at 400px exactly 24px; at 700px exactly 36px. max/min = 1.5×. The authored value was taken over the `current-state-critic-brief.md:324` decoy and the test docstring says why, so the next grep cannot pick the wrong one.
- **The canon deviation is declared and the declaration is enforced conditionally** — `test_the_canon_deviation_is_declared_not_silent` only demands the note *while* the minimum is under 28px, so it self-retires rather than becoming a stale requirement.

### From milestone-arxmcp-critic

- **AC#5 holds: re-measured independently at the head of the range on this workstation, `ruff check .` exits 0 ("All checks passed!") and the full suite shows exactly the 8 environment-bound failures the dispatch named — 6 × `tests/security/test_latexml_sandbox.py` (macOS `sandbox-exec`), 1 × `test_arxiv_fetch.py::…::test_win32_bat_invoked_via_perl` (`WindowsPath` on darwin), 1 × `test_tools_all.py::…::test_cite_neighbors_wired`. Zero new failures.** On the 7-vs-8 discrepancy: the implementer's count of 7 was honest but cache-dependent — `test_cite_neighbors_wired` fails here with `httpx.RemoteProtocolError: Server disconnected without sending a response` from the HuggingFace fetch, i.e. it is network-bound, not m7-bound, and passes only when the artifact is already cached. The dispatch's 8 is the right baseline for this box; nothing about the discrepancy implicates the diff.
- **The token parsers fail LOUD, not partial.** `load_tokens` raises separately on a missing base block and a missing dark block, and `load_raw_tokens` raises on either — so pointing them at `app.css` (which now has no `:root` at all) errors instead of returning an empty or half-populated table. The error strings were updated to name `tokens.css`, which is what makes a mis-pointed parse diagnosable rather than mysterious. The dark-block partial case is separately covered by `test_dark_block_redeclares_all_seven_color_tokens`.
- **`text-wrap` was correctly refused.** `final-report.md:492` attaches `balance` to UPL-3 by name; the only occurrence anywhere in `server/` is the REFUSED note in `tokens.css:101-106`, and `TestBaselineRefusals::test_text_wrap_is_not_used` searches comment-STRIPPED text, so the refusal note cannot satisfy its own guard. Verified against the shipped tree.
- **The 480-line cap was spent honestly, not raised.** All three lockstep cap tests keep reading `app.css`, each records that m7 took the escape hatch the comments had named since m3, and `test_tokens_css_declares_only_root_blocks` gives the new file a structural bound ("no `{` outside `:root`") that is stronger than the line cap it complements.
- **Packaging was verified rather than assumed.** The `*.css` glob match and the wholesale `COPY server/` were checked by running the match; `tools/wheel_install_check.py` was found to be genuinely missing an entry that neither research brief flagged; and `tokens.css` was added to the named-casualty list in `test_wheel_packaging.py`, which does run by default.
- **Two rewritten tests kept their original intent instead of being re-pinned to the new shape.** `test_tabular_nums_covers_required_selectors` gained a "exactly ONE tabular-nums rule" assertion it never had, and `test_old_style_paper_id_through_html_branch` gained an explicit negative that the slash is not HTML-escaped — both strictly stronger than what they replaced.
- **The oklch guard was widened with a closed allow-list plus a dead-entry check.** `NON_COLOUR_TOKEN_PREFIXES` is explicit rather than "skip anything that does not parse as a colour", and `test_the_non_colour_allow_list_has_no_dead_entries` stops a stale prefix pre-authorising a namespace — exactly the right shape for a guard that had to be loosened.
- **The base.html reduced-motion line references were re-derived and are correct.** `app.css:314`, `:418` and `:445` are the `reduce` block and the two `no-preference` blocks respectively, verified against the shipped file.
- **Local-first and CSP are untouched.** Both voices are pure system stacks; there is no `@font-face`, no `url()`, no `@import` and no external host anywhere in `server/frontend/static/*.css`. `tokens.css` is served by the same `StaticFiles` mount at `/ui/static/` and is covered by the existing `style-src 'self' 'unsafe-inline'`, so the base.html comment's "no middleware change was needed" is accurate.
- **The declared deviations are real declarations.** The 24px clamp minimum below the canon's 28px floor, the `text-transform: uppercase` accessibility-tree cost, the `LARGE`-constant removal and the `min-width: 14ch` coupling are each recorded with their reasoning at the site, and three of the four carry a test that keeps the note mandatory.

### From milestone-frontend-ux

- **The 11px micro-caps constraint holds exactly as specified.** `text-transform:
  uppercase` appears exactly once in the product, on the `th` rule, and every `<th>` in
  both templates is an authored column label ("Slug", "Display name", "Created", "Paper
  ID", "Added", "Preview"). I checked every `<th>` render site in the templates and both
  fragment builders: no identifier, slug, path, timestamp, corpus version, state token or
  operator-supplied string is uppercased anywhere. The VoiceOver initialism cost is
  recorded inline rather than discovered later, `dl.meta dt` was deliberately excluded
  with a stated reason, and `test_micro_caps_role_never_lands_on_an_identifier` enforces
  the constraint structurally rather than by convention. This is the axis I expected to
  produce a finding and it produced none.
- **The tracking ships with the size, not as decoration.** `--tracking-meta: 0.06em` is
  correctly `em` rather than `rem` — it scales with its own element, which is the whole
  point at 11px — and the comment states the actual reason positive tracking is required
  (all-caps removes the ascender/descender word-shape cues), rather than treating it as
  style.
- **The Baseline refusals held under direct temptation.** `text-wrap: balance` is
  attached to UPL-3 by name at `final-report.md:492` and is the obvious reach for a fluid
  title; it appears in the CSS only as a refusal comment citing its 2026-11-13 Widely
  date, on the same basis m6 refused `light-dark()`. `font-variant-caps` was likewise
  considered and rejected for a stated technical reason. Neither feature is declared
  anywhere.
- **Every new size token is `rem`, and the reasoning is right for the right reason.**
  `--text-body: 1rem` is byte-identical to the previous rendering, so writing `16px`
  would have passed every test — the comment explicitly names why `px` would still have
  been wrong (it would override the reader's preference in the milestone whose point is
  that type responds to the reader). Nothing sets a `font-size` on `html`/`:root`/`body`
  beyond the token.
- **The clamp is built correctly for both zoom modes.** Min and max are `rem` so text-only
  zoom and a raised default font size scale them, and the preferred term carries a
  `0.5rem` beside the `4vw` so page zoom does not cancel itself — the pure-`vw` trap that
  breaks SC 1.4.4 is avoided, and the 2.5× max/min ceiling is checked by a test.
- **The canon deviation is declared honestly and guarded.** The 24px minimum sits 4px
  below the canon's own 28px title floor; `tokens.css` states that plainly, states what
  the alternative would cost, and `test_the_canon_deviation_is_declared_not_silent` makes
  the note mandatory *while* the minimum is under 28px — so the declaration cannot be
  quietly dropped without either raising the value or failing.
- **D4 is a genuine bug fix, and the test asserts the right invariant.** `_paper_row_html`
  emitted bare `<td>` while the template rendering the same table emitted
  `<td><code>`/`<td><time>`, so htmx-appended rows rendered sans + proportional beside
  mono + tabular rows until reload. The regression test pins the *agreement* between
  fragment and template rather than either shape alone, which is the invariant that
  actually broke.
- **tabular-nums was extended in place rather than forked.** `td code` widened to bare
  `code` — a strict superset — inside the single existing declaration, with a positive
  assertion that the scope stays exactly one rule. Columns of paper IDs, timestamps, run
  ids and exit codes all align.
- **No information is conveyed by type treatment alone.** The mono voice marks
  machine-addressable values, but in every case the meaning is still carried by the word
  itself or by an adjacent label — the state badge pairs colour with a text label, and
  the ingest fragment keeps "Status:" / "Run #" / "Exit" prose beside the tokens.
- **The implement synthesis declares its own gaps rather than papering over them** — the
  scope overrun, the branching constraint, the corrected 7-vs-8 failure baseline, and
  most relevantly "No browser verification … the 11px `th` micro-caps and the 13px
  identifier step are legibility judgements that deserve one real look on a real screen."
  That last line is correct and is the single most valuable sentence in the artifact.

Severity counts: C0 H6 M15 L11


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **H1, H3, H5** at `server/frontend/static/app.css:195-195` (HIGH): `<h2><code>slug</code></h2>` now renders at 13px, under body; `<h2><code>` slug heading renders at 13px, inverting AC#1; Mono `<code>` shrinks the detail page's own heading to 13px
- **H2, H6, M5** at `server/frontend/templates/notebook_detail.html:71-71` (HIGH): AC#2 inventory site 10: the `latest_run.status` state token is still sans; State token `latest_run.status` left in the sans voice; Identifier inventory site 10 left in the sans voice, undeclared
- **M9, M2** at `.claude/docs/ui-contrast-table.md:97-102` (MEDIUM): The large-text-exception rationale in the canonical contrast doc is wrong; Re-floor rationale for `header h1 a` is wrong: the title is bold
- **L7, M4** at `.claude/docs/ui-contrast-table.md:110-111` (MEDIUM): The per-surface size enumeration omits three 13px surfaces; Contrast doc hand-types the wrong size for form controls

## Recommended rectification order

H1, H2, H3, H4, H5, H6, M1, M3, M2, M4, M5, M6, M7, M10, M9, M8, M12, M13, M11, M15, M14, L2, L1, L3, L4, L5, L6, L7, L8, L9, L10, L11

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

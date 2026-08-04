# Critique — ui-uplift-m7 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 2c6588446351f5d947d5c1dc366a036c661f6dc0..a825898616dd8368b57c57adc4802d01cc72baa3
**Diff stats:** 23 files, 2934 LOC (2745 insertions / 189 deletions)
**Critique format version:** 1.0

## Verdict

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

## Executive summary

- [HIGH] `app.css:195` gives every `<code>` a 13px size; `notebook_detail.html:9` is `<h2><code>{{ slug }}</code></h2>`, so the detail page's primary heading now renders SMALLER than body text and at 0.65× its sibling `<h2>`s — AC#1 inverted on the common path.
- [HIGH] The diff is 2934 LOC against a ~400-insertion tripwire the implementer declared and deliberately did not honour.
- [MEDIUM] Inventory site 10 (`notebook_detail.html:71`, `(ingest {{ latest_run.status }})`) still renders a state token in the sans voice, on the same page where `_ingest_status_fragment` now renders the identical datum as `<code>`. Neither Built nor Deferred in the synthesis.
- [MEDIUM] The split makes every `var(--x)` in `app.css` a cross-file reference to `tokens.css`, and no committed test checks the correspondence — the implementer verified it once by hand ("17/17") and did not commit the check. Verified clean today (0 undeclared, 0 unused).
- [MEDIUM] No test fetches `/ui/static/tokens.css` over HTTP; `test_ui_html_pages.py::test_css_served` still covers `app.css` alone, and m7's own new guard only stats the file on disk.
- [MEDIUM] The file move invalidated the `links.code` anchors in `plans/ui-uplift/roadmap.yaml` for `ui-uplift-m8` and five other milestones — m8's `.card` anchor now points into the `input` rule. One-writer rule: this is a `/roadmap` fix, not a Phase-4 one.
- [MEDIUM] `.claude/docs/ui-contrast-table.md:97`'s stated reason for dropping the large-text exception is factually wrong — `header h1` is UA-bold and the clamp's minimum is 24px, so the ≥18.66px-bold branch holds at every viewport.
- [MEDIUM] AC#2's "inherits the tabular-nums scope" half is enforced by a four-name hand-list; `pre.error` and the two `--mono` inputs sit outside the rule, which brief-1 §2b row 32 named as exactly this gap.

## Findings

**H1 — `<h2><code>` slug heading renders at 13px, inverting AC#1** (HIGH)

**Where:** `server/frontend/static/app.css:195`
**Anchor:** `code, time { font-family: var(--mono); f`
**What:** The new `code, time { font-size: var(--text-small) }` rule sets an explicit 13px on the `<code>` element, and `server/frontend/templates/notebook_detail.html:9` is `<h2><code>{{ notebook.slug }}</code></h2>` inside `<section class="card">`, so the notebook-detail page's primary heading renders at 13px — smaller than the 16px body and 0.65× the 20px sibling `<h2>`s ("Topic & discovery", "Ingest", "Papers in this notebook") on the same page.
**Why it matters:** AC#1's stated purpose is that "size carries the hierarchy"; this commit raised `.card h2` to `--text-section` (20px) and in the same commit authored a rule that overrides it to the smallest step on the one heading that names the notebook, so the milestone's headline criterion is contradicted on the console's main page. `.card h2` sets font-size on the `<h2>`; the `code` rule sets it on the `<code>` child, so the inherited 20px never applies — no specificity contest is involved. Pre-m7 the `<code>` carried no author font-size (`table code` was table-scoped), so the discrepancy is authored here, not inherited.
**Proposed fix:** Add one rule after `:195` restoring inheritance for headings, e.g. `h1 code, h2 code { font-size: inherit; }` — 1 line, inside the 480-line cap, and it leaves every other `<code>` on the 13px step. The alternative (making the mono step relative, `font-size: 0.8125em`) also fixes it but silently rescales `<code>` inside `dl.meta dd` and `td`, so the heading-scoped override is the smaller change.
**Regression-guard:** In `tests/test_ui_m7_type_scale.py::TestAC1HeadingStep`, add a test that reads `notebook_detail.html`, asserts the detail-page `<h2>` wraps its slug in `<code>`, and asserts `app.css` carries a heading-scoped `code { font-size: inherit }` (or equivalently that no rule sets a smaller absolute size on a `<code>` inside a heading). It fails on the current tree.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H2 — Diff is 7× the declared scope tripwire and the abort branch was declined** (HIGH)

**Where:** no specific file
**What:** The implement dispatch set a ~400-insertion / ~14-file tripwire with an explicit "stop, commit `partial — scope exceeded`, and return" branch; the landed range is 2745 insertions / 189 deletions across 23 files (code-only ≈987+/140- across 13 files, plus 636 new-file lines that do not appear as diff insertions), and the implementer declared the overrun and proceeded anyway.
**Why it matters:** Per the critique format's own calibration anchor, a diff over 400 LOC is a HIGH; a diff at this size defeats the per-hunk review the Phase-3 critics exist to perform, which is visible in this critique — H1 is a two-token interaction between a CSS rule and a template line that a 400-line diff would have surfaced immediately.
**Proposed fix:** Nothing to change in the code. Record the overrun on `state.json` and, for the next UI milestone, split the mechanical file move (tokens.css + the six test-module re-pointings) from the behavioural type-scale change so each lands under its own tripwire.
**Regression-guard:** The orchestrator's diff-size gate at Phase 2 exit; no test change.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M1 — Identifier inventory site 10 left in the sans voice, undeclared** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:71`
**Anchor:** `        <span class="hint">(ingest {{ la`
**What:** `(ingest {{ latest_run.status }})` renders the ingest state token as bare prose in the sans voice; brief-1 §2b lists it as inventory row 10 with `--mono` NO and tabular-nums NO, and the implement synthesis names sites 20–21 and 28–31 as closed while never mentioning site 10 in either "Built" or "Deferred".
**Why it matters:** AC#2 is "every identifier surface uses `--mono`", and this is the same `latest_run.status` value that `_ingest_status_fragment` now renders as `Status: <code>success</code>` — both are visible simultaneously on the notebook-detail page, so the milestone created a second same-datum-two-voices site of exactly the class D4 existed to eliminate.
**Proposed fix:** Wrap the interpolation: `(ingest <code>{{ latest_run.status }}</code>)`. One template edit; `code` already carries `--mono` and the tabular-nums scope.
**Regression-guard:** Extend `tests/test_ui_m7_type_scale.py::TestAC2IdentifierSurfaces` with an assertion that `notebook_detail.html` renders `latest_run.status` inside `<code>`, mirroring `test_ingest_status_fragment_wraps_its_identifiers`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M2 — Cross-file `var()`↔token correspondence has no committed guard** (MEDIUM)

**Where:** `tests/test_ui_m7_type_scale.py:444`
**Anchor:** `    def test_every_stylesheet_base_html_l`
**What:** After the split, every `var(--x)` in `app.css` resolves against a declaration in a different file, and nothing in the suite checks the correspondence in either direction; the implement synthesis reports the check as a one-off "CSS structural check … every token declared is used and every token used is declared (17/17)" that was run by hand and not committed.
**Why it matters:** An undeclared `var(--text-sektion)` typo or a token rename in `tokens.css` degrades silently to the property's initial value — no CSS error, no test failure, and the source checkout renders the same as production. `test_no_font_size_literal_survives_in_the_rule_sheet` only asserts a value starts with `var(`, so a typo'd name passes it; the milestone's own comment identifies exactly this failure mode ("renders every var() as its initial value") and then guards only the packaging half of it.
**Proposed fix:** Commit the check the implementer already ran, in `TestTokensCssSplit`: parse `(--[\w-]+)\s*:` out of comment-stripped `tokens.css` and `var\((--[\w-]+)\)` out of both files, then assert `used - declared == set()` and `declared - used == set()`. Both are empty on the current tree (verified), so it lands green.
**Regression-guard:** The test above, `tests/test_ui_m7_type_scale.py::TestTokensCssSplit::test_every_var_resolves_to_a_declared_token`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M3 — `tokens.css` is never fetched over HTTP by any test** (MEDIUM)

**Where:** `tests/test_ui_html_pages.py:218`
**Anchor:** `    def test_css_served(self, client: Te`
**What:** `TestStaticAssets::test_css_served` fetches `/ui/static/app.css` and asserts 200 + `text/css`; no sibling exists for `tokens.css`, and m7's new `test_every_stylesheet_base_html_links_actually_exists` only asserts the file is present on disk under `server/frontend/static/`.
**Why it matters:** The milestone's own rationale for the packaging work is that a missing token sheet produces "a 404 whose only symptom is that every var() silently falls back to its initial value" — the route-level half of that failure mode is now the only stylesheet delivery path with no assertion behind it, and the synthesis explicitly decided this file needed "no change".
**Proposed fix:** Parameterise the existing test over the two hrefs, or add four lines: `r = client.get("/ui/static/tokens.css"); assert r.status_code == 200; assert "text/css" in r.headers["content-type"]; assert ":root" in r.text`.
**Regression-guard:** `tests/test_ui_html_pages.py::TestStaticAssets::test_tokens_css_served`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M4 — The file move invalidated six `links.code` anchors in the ui-uplift roadmap** (MEDIUM)

**Where:** `plans/ui-uplift/roadmap.yaml:351`
**Anchor:** `      code: ["server/frontend/static/ap`
**What:** Moving ~180 lines of `:root` out of the top of `app.css` and adding derivation comments below shifted every line in the file, so the `links.code` anchors re-derived by the last `/roadmap` pass no longer point at what they name. Measured against the post-diff file: `ui-uplift-m8`'s `app.css:85-91` was `.card { … }` (now at `:50-56`) and is now the middle of the `input` rule; its `app.css:110-120` was the `input` rule (now `:81-91`) and is now `button, .button`. The same shift breaks `ui-uplift-e1` (`33-50`, `85-91`), `ui-uplift-m11` (`:100`, was `.card .empty`, now at `:71`), `ui-uplift-m15` (`385-409`), `ui-uplift-m16` (`110-120`) and `ui-uplift-m17` (`451-454`, was the `::view-transition` rule, now at `:458-461`).
**Why it matters:** `ui-uplift-m8` is the immediate successor (`depends_on: [ui-uplift-m6, ui-uplift-m7]`, lane `next`) and its whole subject is retiring `.card`; its two anchors now name neither `.card` nor anything m8 touches, so the next implementer's first read lands on the wrong rules. m8's substantive preconditions DO still hold — light `--border` on `--bg` is 3.312:1 (≥3:1, `test_light_border_clears_three_to_one_on_bg` green) and the m7 type scale has shipped — so this is anchor drift, not a sequencing block.
**Proposed fix:** Not fixable from Phase 4 — the pipeline's one-writer rule forbids editing `plans/*/roadmap.yaml` from a milestone. Hand this to `/roadmap` to re-derive all six anchor sets against the post-m7 `app.css`, and consider anchoring by selector text rather than line range so a file move stops invalidating them.
**Regression-guard:** Optional (MEDIUM). A `/roadmap` validator that resolves each `links.code` line range and warns when the cited range contains no selector named in the milestone's summary would close the class.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M5 — The large-text-exception rationale in the canonical contrast doc is wrong** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:97`
**Anchor:** `**No row claims WCAG's large-text excep`
**What:** The doc justifies re-flooring `header h1 a` from 3:1 to 4.5:1 on the grounds that "a viewport-agnostic registry cannot honestly carry a floor that holds only at some widths" — but `header h1` inherits the UA `font-weight: bold` and the clamp's minimum term is `1.5rem` = 24px, so WCAG's large-scale branch (≥18.66px bold) is satisfied at **every** viewport, not merely some. The same reasoning is reproduced verbatim in `tests/test_ui_contrast.py:24-32` and in the `LARGE` constant's replacement comment at `:71-81`.
**Why it matters:** §4.9 binds every arXMCP planning/analysis document, and this is the canonical accessibility record consulted by `ui-uplift-m8`; a stated reason that does not survive checking is the same defect class m6's critique closed when it found 9 of 12 hand-typed ratios wrong. The outcome is conservative and safe — the row passes at 16.032:1 / 13.931:1 against the stricter floor — so nothing measured is wrong, only the reason given for measuring it that way.
**Proposed fix:** Replace the false premise with the true one in all three places: the exception still applies at every viewport (24px minimum, UA bold), and the row is held to 4.5:1 anyway because a registry that keys a floor off a rendered size it does not itself compute cannot verify the precondition — which is the same argument the `LARGE` comment already makes ("an exemption whose precondition nothing checks is unbacked"). Text-only edits; no generated region moves.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M6 — AC#2's tabular-nums half is spot-checked, and three `--mono` surfaces are outside it** (MEDIUM)

**Where:** `server/frontend/static/app.css:208`
**Anchor:** `time, code, .status-badge, dl.meta dd {`
**What:** `pre.error` (`app.css:218`, `font-family: var(--mono)`) and `input[type="text"], input[type="url"]` (`app.css:92`, same) carry the mono voice but are not in the single tabular-nums rule. brief-1 §2d defines the criterion operationally — "every surface m7 gives `--mono` must either already match one of those four selectors, or be added to that selector list" — and brief-1 §2b row 32 names `<pre class="error">` as mono-YES / tabular-NO. The only guard, `test_tabular_scope_is_one_rule_covering_code_and_time`, asserts four selector names are present and cannot see a fifth mono surface appearing outside the rule.
**Why it matters:** AC#2 as written is not fully met, and nothing would catch the next mono surface that lands outside the scope — the same "partial inventory" failure mode `test_ui_contrast.py`'s docstring warns about for `PAIRS`. The rendering impact is near zero (all three sites use a monospace stack, whose digits already have uniform advance), which is why this is MEDIUM and not HIGH — but that fact is nowhere recorded, so a later reader cannot tell a considered omission from an oversight.
**Proposed fix:** Either add `pre.error, input[type="text"], input[type="url"]` to the `:208` selector list, or — better, since the property is a no-op on a monospace stack — record that reasoning in the rule's comment and add a derived guard: collect every selector in `app.css` whose block contains `font-family: var(--mono)` and assert each is either in the tabular-nums selector list or in an explicit, commented allow-list.
**Regression-guard:** `tests/test_ui_m7_type_scale.py::TestAC2IdentifierSurfaces::test_every_mono_surface_is_in_or_allow_listed_out_of_the_tabular_scope`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L1 — Vacuous sub-assertion in the canon-deviation test** (LOW)

**Where:** `tests/test_ui_m7_type_scale.py:256`
**Anchor:** `            assert block is not None`
**What:** `block = _re.search(r"--text-title:.*", TOKENS_CSS)` can only be `None` if `--text-title:` is absent from the file, which line 253's `BASE_TOKENS["--text-title"]` would already have raised `KeyError` on — so the assertion cannot fail, and `block` is never used afterwards.
**Why it matters:** This is the `vacuous-test-kept-as-documentation` family the repo has recorded before (m6's favicon test that passed on an XML comment); a reader counting assertions over-estimates the guard's strength.
**Proposed fix:** Delete lines 255–256 and keep only the `"DECLARED DEVIATION" in TOKENS_CSS` assertion, which is the real check.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L2 — `test_time_elements_take_the_mono_voice` never checks `--mono`** (LOW)

**Where:** `tests/test_ui_m7_type_scale.py:289`
**Anchor:** `    def test_time_elements_take_the_mono`
**What:** The test asserts only that a `code, time {` selector exists; it never inspects the rule body, so it is a strict subset of `test_mono_is_applied_by_element_not_by_table_position` two methods above and would pass on `code, time { color: red }`.
**Why it matters:** Its name and docstring claim to guard the "`<time>` was never `--mono` at all" fix, and it does not.
**Proposed fix:** Either assert `"var(--mono)"` in the captured block, or delete the test and let the sibling carry the guarantee.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L3 — Empty `<time></time>` emitted when `started_at` is unset** (LOW)

**Where:** `server/routes/notebooks.py:2371`
**Anchor:** `            f" · Started <time>{html.esc`
**What:** `started_at or ''` can yield `<time></time>`; a `<time>` element with no `datetime` attribute must have machine-readable text content, so the empty case is invalid HTML. Pre-m7 the same branch emitted bare text and had no such constraint.
**Why it matters:** Minor validity regression introduced by the identifier wrapping; the rendered output is a stray "Started ·" with nothing after it either way.
**Proposed fix:** Emit the `<time>` wrapper only when the value is truthy, or add `datetime="{escaped}"` alongside the text so the element is well-formed in both branches.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L4 — The per-surface size enumeration omits three 13px surfaces** (LOW)

**Where:** `.claude/docs/ui-contrast-table.md:110`
**Anchor:** `Sizes under the m7 scale, for the record`
**What:** "small 13px (labels, captions, controls, table cells, and every identifier in `code`/`time`)" does not account for `header .subtitle` (`app.css:42`), `.breadcrumb` (`:47`) or `pre.error` (`:219`), all of which also land on `--text-small`.
**Why it matters:** The paragraph is the doc's record of which WCAG floor applies to which rendered size; an incomplete enumeration in the artifact whose thesis is "a partial inventory is how three AA failures shipped" is the same shape of gap, even though no floor changes here (all three are already registered pairs at 4.5:1).
**Proposed fix:** Add the three surfaces to the parenthetical, or restate the sentence as "every surface not named above" so it cannot go stale by omission.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**L5 — The new `REQUIRED_INSTALLED_FILES` entry was never executed** (LOW)

**Where:** `tools/wheel_install_check.py:125`
**Anchor:** `    "server/frontend/static/tokens.css",`
**What:** This list is reached only through `make wheel-check` or the `requires_wheel_build`-marked `TestCleanEnvironmentInstall`, both opt-in; the implementer explicitly skipped `make wheel-check`, so the entry has never run. The implement synthesis states the opposite — "the two static packaging assertions (glob match + `REQUIRED_FILES`) run in the default suite" — which is true of the `pyproject` glob assertion in `TestPackageDataCoversEveryDataFile` and false of this one.
**Why it matters:** CLAUDE.md §4.5b calls this the invisible-from-source class and m7 added a new shipped data file; the residual risk is small because the glob half IS covered in the default suite and now names `tokens.css`, but the synthesis's gate claim is inaccurate.
**Proposed fix:** Run `make wheel-check` (~10 s per §4.5b) once and record the result, and correct the synthesis sentence to name only the assertion that actually runs by default.
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability

**L6 — Post-split naming drift in the contrast artifact and its generator** (LOW)

**Where:** `.claude/docs/ui-contrast-table.md:1`
**Anchor:** `# UI contrast table — ui-uplift-m6`
**What:** The artifact's title still reads "— ui-uplift-m6" although its body, floors table and cross-references were all rewritten for m7, and `tests/test_ui_contrast.py:1`'s module docstring still calls itself "the WCAG gate over EVERY rendered pair in **app.css**" now that the tokens it parses live in `tokens.css`.
**Why it matters:** Both are the entry point a future reader hits first, and both now name the wrong milestone / wrong file.
**Proposed fix:** Retitle to "UI contrast table — ui-uplift-m6/m7" (or drop the milestone suffix, since the doc is now cumulative) and change the generator docstring's "in app.css" to "in the operator console's stylesheets".
**Regression-guard:** —
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

## What was done well

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

Severity counts: C0 H2 M6 L6

## Recommended rectification order

H1, M1, M2, M3, M6, M5, L1, L2, L3, L4, L5, L6, H2, M4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>

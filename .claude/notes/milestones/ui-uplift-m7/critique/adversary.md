# Critique — ui-uplift-m7 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 2c6588446351f5d947d5c1dc366a036c661f6dc0..a825898616dd8368b57c57adc4802d01cc72baa3
**Diff stats:** 23 files, 2934 LOC (2745 insertions / 189 deletions; code-only 1127 LOC across 13 files, notes 1807 across 10)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The tokens.css split (D1) is sound — the token parsers fail
loud on a missing or empty `:root` rather than returning a wrong table, both
consuming templates inherit `base.html`'s ordered links, and the packaging
claim was verified against the real glob rather than trusted. The two HIGHs
are both AC misses the diff itself introduced or left: the new
`code, time { font-size: var(--text-small) }` rule renders the detail page's
primary heading at 13px (smaller than body), and brief-1's inventory site 10
— a state token — never got the mono voice. Everything else is doc/comment
drift in the exact hand-written-prose class m6's critique H2 named.

## Executive summary

- [HIGH] `notebook_detail.html:9` is `<h2><code>{{ slug }}</code></h2>`; the new bare-`code` size rule drops that heading's only text from 17.6px to 13px — below body — inverting AC#1 on the page whose h2 *is* the slug.
- [HIGH] AC#2 inventory gap: brief-1 site 10 (`(ingest {{ latest_run.status }})`, `notebook_detail.html:71`) is a state token still in the sans voice with no tabular-nums. 32 of 33 sites landed; the implement synthesis enumerates the closed ones and site 10 appears in none of them.
- [MEDIUM] `tests/test_ui_m3_dark_and_htmx_feedback.py:588` states the split "dropped app.css from 471 to ~400". It is **478 of 480** — two lines of headroom, and the same comment declares the escape hatch spent. The implement synthesis records the correct 471→478, so the checked-in comment contradicts its own author.
- [MEDIUM] The published reason for re-flooring `header h1 a` to 4.5:1 is wrong on the facts: `header h1` is UA **bold**, so the large-text threshold is 18.7px and the clamp's 24px minimum clears it at *every* viewport. The doc contradicts itself two paragraphs later by granting the bold branch to 20px `.card h2`.
- [MEDIUM] `.status-badge` 12px → 11px also shrinks the unstyled `<small class="status-badge__remediation">` nested inside it to ~9.2px — the console's only operator-actionable troubleshooting text. Neither the rule comment nor any test considers the nested element.
- [MEDIUM] `ui-contrast-table.md:111` hand-types "small 13px (… controls …)"; `input[type=text|url|file]`, `select` and `textarea` are all `--text-body` (16px). Wrong fact, outside a generated marker, in the document that exists to stop exactly that.
- [INFO] **The mandatory >400-LOC auto-finding is deliberately NOT filed.** `state.json` carries `allow_large_diff: true` (orchestrator-recorded), the same waiver mechanism used at ui-uplift-m6. Stated here so the omission is auditable rather than silent.
- [INFO] Baseline verified independently: the full suite gives **exactly 8** failures — 6 × macOS `sandbox-exec` latexml, 1 × `WindowsPath` on darwin, 1 × `test_cite_neighbors_wired`. The implementer's "7" is explained: its box had the HuggingFace artifact cached. **Zero new failures.** `ruff check .` clean.

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

## What was done well

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

Severity counts: C0 H2 M4 L3

## Recommended rectification order

M1, H1, H2, M3, M2, M4, L2, L1, L3

(M1 first because H1's fix needs a line of budget under the 480 cap and M1 is
where the real count gets recorded. H1 and H2 are the two AC misses. M3 is a
one-line CSS addition in the same file. The remaining four are prose.)

# Critique — ui-uplift-m11 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 8d98848..3338b43
**Diff stats:** 14 files, 437 LOC (356 insertions, 81 deletions)
**Critique format version:** 1.0

## Verdict

DO-NOT-SHIP

Placing a second, byte-identical-endpoint `<form>` EARLIER in document order than
the real Add-by-URL form silently retargeted five guards across three milestones'
test files onto the new form, and a mutation that makes every add wipe the papers
table now survives the entire UI suite. The premise the AC narrowing, the m12 M13
guard relaxation and the second form's whole existence rest on — "no other
reachable control" — is false on the only page the empty state renders on, because
the Manage disclosure renders `open` for every notebook with no successful ingest
run. The milestone's headline mechanism (`#papers-empty:has(~ tr)`) has zero
covering assertions and can be deleted with the suite green.

## Executive summary

- [CRITICAL] The empty-state form sits before the disclosure's Add-by-URL form in
  document order, so every `re.search`/`matches[0]` guard for "the add-paper form"
  in m4, m12 and the JSON contract now inspects m11's form. Changing the real
  form's `hx-swap` to `innerHTML` — every add wipes the table — leaves 518 UI tests
  green.
- [HIGH] `<details class="manage-disclosure" … open>` renders on every first-run
  notebook, so the disclosure's Add-by-URL form is visible on exactly the page the
  empty state shows. "The action is genuinely unreachable" is false, and the
  BAN-9 asymmetry against the index and discover empty states is unjustified.
- [HIGH] `<tr id="papers-empty">` has no `{% if not papers %}`; a notebook with two
  papers serves the row, the form, and "Nothing indexed yet — this notebook has no
  papers." The m12 M13 guard's `if rows:` branch is unreachable under its fixture
  AND fails when fed a populated page.
- [HIGH] `hx-on::htmx:response-error` registers a listener for
  `htmx:htmx:response-error`, an event the shipped bundle never dispatches.
  `#papers-empty-error` can never be filled and the form never resets.
- [HIGH] Deleting all three CSS rules m11 added — including the `:has()` clearing
  rule the entire bug-fix rests on — leaves the whole UI suite green.
- [MEDIUM] `#papers-tbody` is never `:empty` any more, so m8's M16 rectification
  (`table:has(tbody:empty) thead th`) is dead code on the page it was written for.
- [MEDIUM] The "strictly stronger" JSON-contract helper accepts any `hx-ext` value;
  `hx-ext="morph"` on the real form leaves that module green where the pre-m11
  topology failed twice.
- [MEDIUM] `<output id="papers-empty-error">` is a live region nested inside
  `#papers-tbody[aria-live="polite"]` — the defect class m13 exists to remove, and
  m13's nesting guard is scoped to `#ingest-live` only.

## Findings

**C1 — Second form on the same endpoint silently retargeted five guards** (CRITICAL)

**Where:** `server/frontend/templates/notebook_detail.html:238`
**Anchor:** `          <form class="empty-action"`
**What:** m11 added a second `<form hx-post=".../papers">` at template line 238, which is EARLIER in document order than the disclosure's Add-by-URL form at line 512. Every guard that locates "the add-paper form" by first match — `tests/test_ui_m4_in_place_add_paper.py:358` and `:392`, `tests/test_ui_m12_corpus_before_machinery.py:609`, and `_form_tag_containing`'s `return matches[0]` feeding `tests/test_ui_htmx_json_contract.py:207` and `:357` — now asserts against m11's new form. The real Add-by-URL form, the one operators use once a notebook has papers, is no longer covered by any of them.
**Why it matters:** Five deliberate, milestone-authored guards became decorative in one commit without a single test turning red. I mutated the real form's `hx-swap` from `beforeend show:#papers-tbody:bottom` to `innerHTML` — which makes every successful add REPLACE the entire papers table with one row, destroying the corpus view and repealing m12 AC#4's "invisible success" fix — and the whole UI suite stayed green. The commit message claims each guard "was reconciled deliberately, not blanket-updated"; this collapse was not noticed by any of the four reconciliations.
**Reproduced:**
```
$ python3 - <<'PY'   # mutate ONLY the disclosure Add-by-URL form
p='server/frontend/templates/notebook_detail.html'; s=open(p).read()
s=s.replace('    hx-swap="beforeend show:#papers-tbody:bottom"\n    hx-on::htmx:after-request="if(event.detail.successful) this.reset()"\n    hx-on::htmx:response-error="document.getElementById(\'paste-error\')',
            '    hx-swap="innerHTML"\n    hx-on::htmx:after-request="if(event.detail.successful) this.reset()"\n    hx-on::htmx:response-error="document.getElementById(\'paste-error\')')
open(p,'w').write(s)
PY
$ uv run python -m pytest tests/ -k "ui" --tb=line -q -p no:warnings | tail -3
...............................................................s..ss
..............                                                     [100%]
```
Zero failures. For contrast, mutating the EMPTY-STATE form's `hx-target`/`hx-swap` the same way fails 3 tests — the guards fire, they are just pointed at the wrong form now.
**Proposed fix:** Stop keying guards on first match. Give the two forms distinguishable identity (e.g. `id="add-paper-form"` on the disclosure form, `id="papers-empty-form"` on the new one) and change `tests/test_ui_m4_in_place_add_paper.py:358`/`:392`, `tests/test_ui_m12_corpus_before_machinery.py:609` and `_form_tag_containing` to resolve by id — or, in `_form_tag_containing`, apply every caller assertion to EVERY match rather than returning `matches[0]`. The simplest structural alternative is to not ship a second form at all (see H1).
**Regression-guard:** `tests/test_ui_m11_empty_states.py::test_both_papers_forms_are_individually_pinned` — parametrize the existing hx-target/hx-swap/json-enc assertions over BOTH forms resolved by id, and assert `DETAIL.count('hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers"') == 2` so a third arrival is a decision.
**Source critic:** milestone-adversary-critic
**Source axis:** The guard reconciliations

---

**H1 — "No other reachable control" is false on the only page this renders on** (HIGH)

**Where:** `plans/ui-uplift/roadmap.yaml:441`
**Anchor:** `      # adjacent visible control, which BAN-9 ("multiple primary CTAs per`
**What:** The AC narrowing, the m12 M13 guard relaxation (`tests/test_ui_m12_corpus_before_machinery.py:883-889`) and the second form's existence all rest on one asserted fact: "ui-uplift-m12 moved every mutation form behind the Manage disclosure, so its copy could ONLY point", and "In the EMPTY state there is no table to duplicate beside and no other reachable control." `server/frontend/templates/notebook_detail.html:387` renders `<details … {% if not latest_run or latest_run.status != 'success' %} open{% endif %}>`. A brand-new notebook has `latest_run = None`, so the disclosure is OPEN and the Add-by-URL form is expanded and visible on precisely the page the empty state renders on.
**Why it matters:** The refusals for the index and discover-results empty states were argued on "the control is directly above this table, visible, on the same page". The papers control is directly below the table, visible, on the same page, in an open disclosure — the same situation, decided the opposite way. So either BAN-9 was misapplied to refuse two controls, or it was ignored to ship one; both cannot hold. And m12's M13 guard was relaxed to admit a form whose justification does not survive reading the `open` predicate three hundred lines below it in the same file.
**Reproduced:**
```
$ uv run python scratchpad/repro_populated.py   # renders a fresh notebook via the real routers
$ python3 -c "import re;h=open('empty-nb.html').read();print(re.search(r'<details\b[^>]*>',h).group(0))"
<details class="manage-disclosure" id="manage" aria-labelledby="manage-summary" open>
$ python3 -c "import re;h=open('empty-nb.html').read();print([m.start() for m in re.finditer(r'<form[^>]*hx-post=\"/ui/api/notebooks/empty-nb/papers\"',h,re.S)])"
[5735, 9746]
```
Both Add-by-URL forms are in the served DOM of a first-run notebook and neither is collapsed. `tests/test_ui_m12_corpus_before_machinery.py` `OPEN_STATES = ("none", "running", "failed")` pins this behaviour deliberately.
**Proposed fix:** Pick one and record it against the real fact. Either (a) drop the second form and give the papers empty state the same cause-only treatment as the other two, since its control IS reachable and visible; or (b) keep the control and re-argue AC#1's narrowing on grounds that survive the `open` predicate — e.g. "the empty state's control is the ONLY one above the fold on a first-run page" — and measure that claim rather than asserting it. Either way, correct the three places that currently state the false premise: `plans/ui-uplift/roadmap.yaml:441-449`, `.claude/notes/milestones/ui-uplift-m11/research/synthesis.md`, and the guard comment at `tests/test_ui_m12_corpus_before_machinery.py:883-889`.
**Regression-guard:** `tests/test_ui_m11_empty_states.py::test_the_empty_state_premise_still_holds` — assert that when the papers empty row renders, the Manage disclosure's `open` state and the Add-by-URL form's visibility match whatever the AC finally claims, so the next change to the `open` predicate fails here instead of silently invalidating the AC.
**Source critic:** milestone-adversary-critic
**Source axis:** The roadmap amendment

---

**H2 — The empty state ships inside every populated page; the m12 populated branch is unreachable and false** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:235`
**Anchor:** `      <tr id="papers-empty">`
**What:** The row carries no `{% if not papers %}`. A notebook with two papers serves `<tr id="papers-empty">`, its `<td class="empty">`, the sentence "Nothing indexed yet — this notebook has no papers.", a full duplicate Add-by-URL form and an `<output>` — all present in the DOM, hidden only by one CSS declaration. The consequence for the guard: `tests/test_ui_m12_corpus_before_machinery.py:876` `if rows:` never executes, because `_render` (line 222) creates a notebook and seeds only an ingest-run row, never a paper — so `rows` is always `[]`. Fed a genuinely populated page, that branch FAILS.
**Why it matters:** The reconciliation is presented as narrowing a guard while preserving the populated case. The populated case is not preserved: it is unreachable under the fixture, and it is factually wrong about the page it claims to describe, so it is a claim that can never be true and never be tested. Meanwhile the false copy and the duplicate control are one stylesheet failure away from being visible — if `app.css` 404s, is cached stale, or is stripped by a strict CSP, every populated notebook renders "Nothing indexed yet — this notebook has no papers." above its own papers, which is a strictly louder version of the bug m11 exists to fix.
**Reproduced:**
```
$ uv run python scratchpad/repro_populated.py       # full-nb seeded with 2 papers
$ uv run python scratchpad/repro_m12_guard.py       # runs the guard body verbatim
empty-nb: rows=0 forms=1
  empty branch: PASS (1 form)
full-nb: rows=2 forms=1
  populated branch: **FAIL** -> the POPULATED papers section carries 1 form(s)
```
And the served markup for the 2-paper notebook contains `<tr id="papers-empty">` with `<p class="empty-cause">Nothing indexed yet — this notebook has no papers.</p>` immediately above `<tr data-slug="full-nb" data-paper-id="2604.26205">`.
**Proposed fix:** Restore the server-side truth and keep the CSS as the htmx-append handler, which is what actually needs it: wrap the row in `{% if not papers %}…{% endif %}`. First paint is then correct without a stylesheet, and `#papers-empty:has(~ tr) { display: none }` still covers the three in-place add paths, which is the only case it was ever needed for. Then add papers to a `_render` variant in the m12 fixture so `if rows:` is actually exercised.
**Regression-guard:** `tests/test_ui_m11_empty_states.py::test_the_empty_row_is_absent_from_a_populated_page` — render a notebook with one paper via the real routers and assert `'id="papers-empty"' not in body`; plus a populated-page parametrization of `TestRegionThreeIsNamedAndReachable`.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness of the `:has()` clearing rule / the guard reconciliations

---

**H3 — The empty-state form's error output and reset hook are bound to an event htmx never fires** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:245`
**Anchor:** `            hx-on::htmx:response-error="document.getElementById('papers-`
**What:** `hx-on::htmx:response-error` is a doubled prefix. htmx's `hx-on` name normaliser strips `hx-on`, sees a leading `:`, and prepends `htmx`, producing the event name `htmx:htmx:response-error`. The shipped bundle dispatches `htmx:responseError` and its kebab alias `htmx:response-error`; the string `htmx:htmx` does not occur anywhere in `server/frontend/static/htmx.min.js`. The correct spellings are `hx-on::response-error` or `hx-on:htmx:response-error`. The sibling `hx-on::htmx:after-request` (line 244) is dead the same way, so `this.reset()` never runs either.
**Why it matters:** m11's own AC#1 control ships an error surface that can never display an error. The m13 guard reconciliation adds `papers-empty-error` to `ERROR_BLOCK_IDS` and claims it "got the `<output>` treatment on arrival" — the element exists and is correctly an `<output>`, and nothing will ever write to it, so a 409 duplicate or a 422 malformed-URL from the first-paper form is silently swallowed. The pattern is pre-existing across the page (`paste-error`, `upload-error`, `ingest-error`, the Remove button's row-removal hook at `notebook_detail.html:288`, and `index.html:38` — which is the "per-form JS hook" the synthesis credits the index with, and which is therefore also dead), but m11 added a new instance and asserted it works.
**Reproduced:** the verbatim `Pt()` function was extracted from the shipped bundle and executed with stubs:
```
$ node -e '…eval(ptSrc)… Pt({attributes:[…]})'
--- registered event names ---
hx-on::htmx:after-request    ->   htmx:htmx:after-request
hx-on::htmx:response-error   ->   htmx:htmx:response-error
hx-on::after-request         ->   htmx:after-request
hx-on:htmx:after-request     ->   htmx:after-request
$ grep -c "htmx:htmx" server/frontend/static/htmx.min.js
0
```
**Proposed fix:** Rewrite the two attributes on the empty-state form as `hx-on::response-error` and `hx-on::after-request`. This is repo-wide, not m11-local — fix all nine occurrences in one pass, and note that fixing `notebook_detail.html:288` is what makes the Remove path actually remove the row, which is the path `#papers-empty:has(~ tr)` depends on to bring the empty state back.
**Regression-guard:** `tests/test_ui_htmx_json_contract.py::test_no_hx_on_attribute_uses_the_doubled_prefix` — assert `re.search(r'hx-on::htmx:', html)` is None across `index.html` and `notebook_detail.html`; the shape is checkable statically and needs no browser.
**Source critic:** milestone-adversary-critic
**Source axis:** The second form

---

**H4 — The milestone's headline mechanism has zero covering assertions** (HIGH)

**Where:** `server/frontend/static/app.css:131`
**Anchor:** `#papers-empty:has(~ tr) { display: none; }`
**What:** m11 shipped no test file of its own. Nothing anywhere in `tests/` references `#papers-empty` (only `papers-empty-error`), `.empty-cause` or `.empty-action`. The CSS rule that constitutes the entire fix for the "unfiled bug in the surface m11 owns" is unpinned, as are both anatomy rules.
**Why it matters:** The commit's central claim is that the empty state now clears itself "no JS, every add path, including ones not written yet". A future stylesheet edit — an app.css split into `tokens.css`, a `:has()` audit, a line-cap-driven comment strip — can delete the rule and every test still passes, at which point the bug the milestone was written to fix is back, now with a duplicate form attached to it.
**Reproduced:**
```
$ python3 - <<'PY'
s=open('server/frontend/static/app.css').read()
s=s.replace('#papers-empty:has(~ tr) { display: none; }\n','')
s=s.replace('.empty > .empty-cause { margin: 0 0 0.75rem 0; }\n.empty > .empty-action { font-style: normal; text-align: left; max-width: 32rem; margin-inline: auto; }\n','')
open('server/frontend/static/app.css','w').write(s)
PY
$ uv run python -m pytest tests/ -k "ui" --tb=line -q -p no:warnings | tail -3
...............................................................s..ss
..............                                                     [100%]
```
All three rules deleted, zero failures.
**Proposed fix:** Add `tests/test_ui_m11_empty_states.py` asserting, over the comment-stripped `app.css`: the exact selector `#papers-empty:has(~ tr)` exists and its body declares `display: none`; `.empty > .empty-cause` and `.empty > .empty-action` both exist; and that the id/classes the rules key on are the ones the template actually emits (derive both sides from disk, do not hand-list).
**Regression-guard:** `tests/test_ui_m11_empty_states.py::test_the_clearing_rule_exists_and_hides` and `::test_the_anatomy_classes_have_rules`.
**Source critic:** milestone-adversary-critic
**Source axis:** Missing guards

---

**M1 — m8's empty-tbody rule is now dead on the table it was written for** (MEDIUM)

**Where:** `server/frontend/static/app.css:226`
**What:** `table:has(tbody:empty) thead th { border-block-end: var(--rule-row); }` is m8's M16 rectification: with no rows below it, the header drops from the section rung to the row rung because there is nothing to separate from. `#papers-tbody` now always contains `<tr id="papers-empty">`, so `tbody:empty` can never match and the papers header keeps the heavy `--rule-section` rule over what is visually an empty table.
**Why it matters:** A previously-shipped rectification was reverted in effect by an unrelated milestone, with no test noticing, and the m11 CSS comment cites that very rule as precedent for using `:has()` while breaking it two hundred lines above. `tests/test_ui_m8_rule_ladder.py:682` only asserts the selector exists in the stylesheet with a declared cue kind; it never checks the selector matches any rendered page, so the rule is now a permanently-false branch that the guard reports as healthy.
**Reproduced:** the rendered first-run page's tbody is `<tbody id="papers-tbody" aria-live="polite">` followed immediately by `<tr id="papers-empty">`; `#papers-tbody` contains an element child in every state. Confirmed against `scratchpad/empty-nb.html` and `full-nb.html`.
**Proposed fix:** Fixing H2 (`{% if not papers %}` around the row) restores `tbody:empty` for the papers table and this finding closes with it. If the row stays unconditional, either retarget the m8 rule (`table:has(#papers-empty:not(:has(~ tr))) thead th`) or delete it and record that m8 M16 no longer applies.
**Regression-guard:** extend `tests/test_ui_m8_rule_ladder.py` so each `TINTED_SITES` selector with cue kind `DEGENERATE` must MATCH at least one rendered page state, not merely exist in the file.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness of the `:has()` clearing rule

---

**M2 — The "strictly stronger" JSON-contract helper accepts any hx-ext value** (MEDIUM)

**Where:** `tests/test_ui_htmx_json_contract.py:89`
**What:** The replacement loop is `if "hx-ext" not in tag and "hx-encoding" not in tag: raise`. That is substring presence, not the contract. `hx-ext="morph"` passes. `hx-encoding="multipart/form-data"` on a JSON endpoint — literally Bug 1, the empty-body 422 this module exists for — passes. The real assertion, `'hx-ext="json-enc"' in tag`, still runs against `matches[0]` only.
**Why it matters:** The commit calls this "strictly stronger". It is strictly weaker for every match after the first, and the first is now m11's own form (C1). The module's own coverage of the real Add-by-URL form's encoding is gone.
**Reproduced:**
```
$ # mutate the DISCLOSURE form: hx-ext="json-enc" -> hx-ext="morph"
$ uv run python -m pytest tests/test_ui_htmx_json_contract.py -q -p no:warnings | tail -1
...........................                                        [100%]     27 passed

$ # same mutation with the m11 empty-state row removed (pre-m11 topology)
$ uv run python -m pytest tests/test_ui_htmx_json_contract.py -q -p no:warnings | tail -3
FAILED …::TestPerFormHxExt::test_add_paper_form_opts_in
FAILED …::TestServedHtmlHxExt::test_detail_json_forms_carry_hx_ext_in_served_html
```
**Proposed fix:** Make the helper return the full list and have every caller assert over all of it, e.g. `def _form_tags_containing(html, needle) -> list[str]` with callers doing `for tag in tags: assert 'hx-ext="json-enc"' in tag`. Drop the weak substring loop entirely — it adds nothing the callers' own assertions would not do correctly.
**Regression-guard:** the rewritten `TestPerFormHxExt` / `TestServedHtmlHxExt` over all matches; re-run the `hx-ext="morph"` mutation and require ≥1 failure.
**Source critic:** milestone-adversary-critic
**Source axis:** The guard reconciliations

---

**M3 — A live region is now nested inside the papers tbody's live region** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:253`
**What:** `<output id="papers-empty-error" class="error">` has an implicit `role="status"` / `aria-live="polite"` — `tests/test_ui_m13_live_region_hygiene.py:70` says so in `IMPLICIT_LIVE_TAGS`. It is rendered inside `<tbody id="papers-tbody" aria-live="polite">` (line 201). Every other block in `ERROR_BLOCK_IDS` sits outside any live region. m13's only nesting guard, `TestLiveRegionCensus::test_the_detail_page_announces_from_one_polled_surface`, is scoped to `#ingest-live` and does not look at `#papers-tbody`.
**Why it matters:** m13's own stated rule — "Nesting one restores the per-tick announcement on the inner node… the wrapper is the only announcing surface" — is violated on a different wrapper one milestone later, and its guard cannot see it. Practically, writing to the inner `<output>` is also a text mutation inside the outer polite region, so an add-paper error is a candidate for double announcement.
**Reproduced:** `_live_regions()` from the m13 module over the rendered page places the `<output>` inside the `aria-live="polite"` tbody; the served markup is `<tbody id="papers-tbody" aria-live="polite"> … <output id="papers-empty-error" class="error"></output> … </tbody>`. The m13 census test passes because it counts (7 == 7) and checks nesting only under `#ingest-live`.
**Proposed fix:** Move the empty-state error surface out of the live tbody — render `<output id="papers-empty-error">` as a sibling of the table rather than inside a `<td>`, with the form's handler targeting it by id as it already does. Then generalise the m13 nesting guard from `#ingest-live` to "no live region is nested inside any other live region on the page".
**Regression-guard:** `tests/test_ui_m13_live_region_hygiene.py::test_no_live_region_is_nested_in_another` — derive both sides via `_live_regions()` and `contains()`.
**Source critic:** milestone-adversary-critic
**Source axis:** The second form

---

**M4 — A successful first add destroys the element that has focus** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:252`
**What:** The submit button lives inside `#papers-empty`. On a successful add the new `<tr>` appends, `#papers-empty:has(~ tr)` starts matching, and the whole subtree — form, input, focused button — goes `display: none`. A `display: none` element is not focusable and is removed from the accessibility tree, so focus falls back to `<body>`.
**Why it matters:** Every other add path leaves its form in place (the disclosure form persists and `this.reset()`s — or would, see H3), so the keyboard user stays where they were. Here, adding the first paper drops focus to the top of the document and resets the screen-reader virtual cursor, on the one interaction a first-run user is most likely to perform. The empty state is also the ONLY route by which the papers table can transition from empty to populated in-place, so this fires on every first add through m11's control.
**Reproduced:** structurally, from the two facts established above — the button at `notebook_detail.html:252` is inside `<tr id="papers-empty">` (line 235), and `app.css:131` sets `display: none` on that row the moment any `<tr>` follows it, which the `beforeend` swap into `#papers-tbody` guarantees. I could not observe the focus transition itself; no browser or JS runtime is driven by this suite.
**Proposed fix:** Move focus explicitly on success — add `hx-on::after-request="if(event.detail.successful){document.querySelector('#papers-tbody tr:last-child a,#papers-tbody tr:last-child button')?.focus()}"` (correct prefix per H3), or keep the control outside the row that gets hidden.
**Regression-guard:** template assertion that the empty-state form carries an explicit post-success focus handler; behavioural verification needs a browser and is out of this suite's reach.
**Source critic:** milestone-adversary-critic
**Source axis:** The second form

---

**M5 — The epic's own standing rule does not cover template-emitted classes** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:279`
**What:** `ui-uplift-e2` exists to make "every server-emitted class ships with its CSS rule" a derived test. `_route_files()` globs `server/routes/*.py` only. m11's two new classes, `.empty-cause` and `.empty-action`, are emitted by `notebook_detail.html`, so BAN-R2 never sees them.
**Why it matters:** m11 is a child of that epic and shipped two classes into precisely the blind spot the epic was chartered to close. Deleting both rules from `app.css` leaves `tests/test_ui_class_css_coverage.py` at 16 passed.
**Reproduced:**
```
$ # both anatomy rules deleted from app.css
$ uv run python -m pytest tests/test_ui_class_css_coverage.py -q -p no:warnings | tail -1
................                                                   [100%]
```
**Proposed fix:** Extend the emission scan to `server/frontend/templates/*.html` with the same `class="…"` extraction, Jinja-comment-stripped. That is a genuinely larger change than m11 should absorb; the minimum here is to file it and pin the two new classes directly (H4's guard).
**Regression-guard:** `tests/test_ui_class_css_coverage.py::test_template_emitted_classes_have_rules`.
**Source critic:** milestone-adversary-critic
**Source axis:** Missing guards

---

**L1 — `.empty-action` takes back the type voice but not the colour** (LOW)

**Where:** `server/frontend/static/app.css:138`
**What:** The rule resets `font-style` and `text-align` but leaves `color`, so the form's `<label>` inherits `.empty`'s `#666` (light) / `#9ba1a8` (dark) from `app.css:122` and the dark block. The CSS comment one line above says "the control is a real form and takes the ordinary control voice back"; the colour is half of that voice and it does not come back.
**Why it matters:** Cosmetic only — both values are already enumerated and passing in `tests/test_ui_contrast.py:265` and `:272`, so this is not an SC 1.4.3 issue. It is a stated-intent/implementation mismatch in a rule whose whole justification is the intent.
**Reproduced:** `app.css:138` declares `font-style`, `text-align`, `max-width`, `margin-inline` and no `color`; the dark block declares `.empty { color: #9ba1a8 }` and nothing for `.empty-action`.
**Proposed fix:** Add `color: var(--fg);` to `.empty > .empty-action`, or drop the "ordinary control voice" clause from the comment.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic

---

**L2 — m11's roadmap `links.code` never gained the file it actually changed** (LOW)

**Where:** `plans/ui-uplift/roadmap.yaml:464`
**What:** `code: ['server/frontend/static/app.css#.empty', 'server/frontend/templates/index.html#id="notebooks-empty"']`. The milestone's principal surface is `server/frontend/templates/notebook_detail.html` and its second is `server/routes/notebooks.py::_discover_results_fragment`; neither is listed. Both cited anchors still resolve, so `tests/test_roadmap_links_resolve.py` stays green while the list is now incomplete rather than wrong.
**Why it matters:** The links list is how a later reader finds the surface. It now points at the two empty states m11 only rewrote copy on and omits the one it restructured.
**Reproduced:** read `plans/ui-uplift/roadmap.yaml:463-464`; `git show 3338b43 --stat` lists `notebook_detail.html` (+65/-10) and `notebooks.py` (+15/-2).
**Proposed fix:** Append `'server/frontend/templates/notebook_detail.html#id="papers-empty"'` and `'server/routes/notebooks.py#_discover_results_fragment'`.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic

---

**L3 — The app.css cap raise gave 13x the previous headroom** (LOW)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:666`
**What:** The file went 678 → 694 lines (+16) and the cap went 680 → 720 (+40). Headroom was 2 lines before this commit and is 26 after. Every prior raise in the recorded history was to accommodate a specific landed cost; this one is 2.5x the cost it was raised for.
**Why it matters:** The cap is a budget whose value is that it forces an argument. 26 lines of slack is roughly one more undocumented rule block that never has to be argued for. Minor, and the raise itself is legitimate.
**Reproduced:**
```
$ git show 3338b43^:server/frontend/static/app.css | wc -l
     678
$ wc -l < server/frontend/static/app.css
     694
```
**Proposed fix:** 700 covers the landed cost with the customary margin. Applies to all three files (`test_ui_m3:666`, `test_ui_m4:747`, `test_ui_m5:861`).
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic

---

**L4 — The milestone's own state.json still says "four"** (LOW)

**Where:** `.claude/notes/milestones/ui-uplift-m11/state.json:32`
**What:** `milestone_brief` was written in this same commit and still carries "Author the four empty states", "The four empty states are italic centred grey text", and the un-narrowed AC#1 ("Given any of the four empty states"). The roadmap was corrected in the same commit; the snapshot was not.
**Why it matters:** The brief is what a resumed pipeline session reads first. A Phase-4 run starting from this state.json will be handed the count and the AC the commit exists to correct.
**Reproduced:** `grep -n "four empty states" .claude/notes/milestones/ui-uplift-m11/state.json` → line 32, three occurrences within the field.
**Proposed fix:** Re-derive `milestone_brief` from the amended roadmap entry during rectify.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic

## What was done well

- The diagnosis is real and was previously unfiled: nothing removed the papers empty
  state, and all three add paths do append into `#papers-tbody`, verified — a
  CSS-structural fix genuinely does cover paths not written yet, where the index's
  per-form hook does not.
- Choosing to record the AC narrowing in `plans/ui-uplift/roadmap.yaml` rather than
  only at the implementation site is the right instinct and is the m12 AC#1 lesson
  correctly applied; the problem is the premise, not the placement.
- Refusing to add the product's first icon rather than drifting into it (AC#3) is a
  correct read of BAN-3 and of the roadmap's escalation requirement.
- The count correction was verified against the discovery-era commit `0c95720`
  rather than asserted, and the roadmap carries the evidence inline.
- The m12 M6 nesting guard change (`_find(root, …)` → `_find(details, …)`,
  `tests/test_ui_m12_corpus_before_machinery.py:769`) is a genuine strengthening —
  it resolves inside the disclosure instead of taking document order, which is the
  one reconciliation of the four that got the failure mode right.
- The discover-results copy rewrite is a real improvement: "No new candidates" was
  ambiguous between "the feed returned nothing" and "everything is already here",
  and the new sentence names the common case and the useful next action.
- `#papers-empty-error` was correctly given its own id rather than reusing
  `paste-error`; the served page has zero duplicate ids in both empty and populated
  states (verified).
- `hx-disabled-elt="find button"` is the correct m3 C4 form-shaped value on the new
  control, and the four guard reconciliations were each argued individually in the
  commit body rather than blanket-bumped.

Severity counts: C1 H4 M5 L4

## Recommended rectification order

C1, H2, H1, H3, H4, M2, M1, M3, M5, M4, L1, L2, L4, L3

## What I could not check and why

- **No browser, and this suite drives none.** Every `:has()` and `display: none`
  claim in this report is derived from the served markup plus the CSS cascade as
  specified, not observed rendering. I could not confirm that the clearing rule
  visually fires after a real htmx swap, could not observe the M4 focus transition,
  and could not measure BAN-9's "per viewport" for H1 — I argued H1 on
  reachability and visibility, which are page facts, not on viewport occupancy,
  which is not.
- **No JS execution against a live page.** H3 is proven by extracting htmx's own
  `Pt()` normaliser from the shipped bundle and executing it verbatim in node with
  stubs, plus `grep -c "htmx:htmx"` returning 0. That establishes the listener is
  registered under a name the bundle never dispatches. I did not load the real page
  in a browser and watch a 409 fail to render, so the end-to-end symptom is
  inferred from two verified halves.
- **The 8 failures' provenance.** `pytest tests/` on a verified-clean tree returns
  exactly 8 failures — six in `tests/security/test_latexml_sandbox.py`, plus
  `test_arxiv_fetch.py::test_win32_bat_invoked_via_perl` and
  `test_tools_all.py::test_cite_neighbors_wired` — which matches the commit's claim
  in count and is consistent with "environment-bound" (container sandbox, a Windows
  path, a missing index). None is in the UI tree and none is plausibly m11's. I did
  NOT verify against a pre-m11 baseline that these are the *same* 8, nor confirm
  each is genuinely environment-bound rather than a standing defect.
- **`:empty` whitespace semantics.** M1 does not depend on it — `#papers-tbody`
  contains an element child in every state, so `tbody:empty` cannot match under
  either the Selectors-3 or Selectors-4 reading. I did not determine which reading
  the target browsers implement, and did not check whether the papers table was the
  only consumer of m8's rule (the index tbody appears to have had the same problem
  before m11, which would mean m8 M16 was already partly dead — I did not chase it).
- **Real-notebook data.** All rendering was against `TestClient` with papers seeded
  directly through `store.add_paper`, never through the live `POST .../papers`
  handler, which fetches arXiv. Nothing in this report depends on the fetch path.
- **The rectify and implement note directories** are empty; there is no
  implementation plan artifact to check the diff against, so "did it build what it
  planned" was assessed against `research/synthesis.md` and the commit body only.

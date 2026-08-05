# ui-uplift-m11 (UPL-21) — frontend-UX / accessibility critique

Subject: commit `3338b43`, "author the three empty states".
Environment: no browser. Every finding below was reproduced by reading the
shipped file, running the repo's own colour math, rendering the Jinja template,
or executing htmx's own attribute-parsing code against the vendored bundle.
Anything I could not reproduce is in the last section and is NOT a finding.

**Counts: 1 CRITICAL · 4 HIGH · 5 MEDIUM · 3 LOW (13 total).**

---

**F1 — the new `<output>` can never receive text: both of m11's `hx-on` handlers are dead** (CRITICAL)

**Where:** `server/frontend/templates/notebook_detail.html:244` and `:245`
(app-wide siblings: `index.html:38,39`; `notebook_detail.html:92,161,285,422,469,517,518,548,582`)

**What:** m11 shipped
`hx-on::htmx:response-error="document.getElementById('papers-empty-error').textContent = …"`.
That attribute name mixes htmx's two mutually exclusive spellings. The `::`
shorthand *already means* `htmx:`; writing `htmx:` again after it makes htmx
register a listener for the event **`htmx:htmx:response-error`**, which htmx
never dispatches. The correct forms are `hx-on::response-error` or
`hx-on:htmx:response-error`. The same defect is on m11's
`hx-on::htmx:after-request` (line 244), so `this.reset()` never runs either.

**Why it matters:** `#papers-empty-error` is the entire error surface of the
control m11 exists to add. AC#1 asks for "one actual control"; the control has
no failure path at all. A 409 (paper already in notebook) or a 422 (malformed
arXiv URL) produces **no visible change and no announcement whatsoever** — the
button re-enables, the input keeps its text, nothing appears. It also means the
`<output>` is a live region that is guaranteed to stay empty forever, which is
the opposite of what m13 built the `<output>` migration for. The pattern is
pre-existing and repo-wide (10 attributes, 4 distinct names), so m11 did not
invent it — but m11 is the milestone that added a brand-new live region whose
only writer is this dead handler, and it shipped one milestone after m13
audited exactly this machinery.

**Reproduced:**

htmx's own expansion code, lifted verbatim from the vendored bundle
(`server/frontend/static/htmx.min.js`, function `Pt`:
`const o=n.indexOf("-on")+3;const i=n.slice(o,o+1);if(i==="-"||i===":"){let e=n.slice(o+1);if(l(e,":")){e="htmx"+e}…`
where `l(e,t)` is `e.substring(0,t.length)===t`), run over every `hx-on`
attribute in the product and checked against the set of names htmx can actually
dispatch (`ae()` dispatches `t` and its kebab alias `Bt(t)` only):

```
$ .venv/bin/python - <<'PY'   # full script re-runnable; abridged here
  … expand each hx-on attr with htmx's algorithm, compare to the 46 "htmx:*"
  … string literals in htmx.min.js plus their kebab aliases (84 names)
PY
htmx dispatches 46 distinct event names (+kebab aliases) = 84 listenable names

DEAD  index.html             hx-on::htmx:after-request          -> htmx:htmx:after-request
DEAD  index.html             hx-on::htmx:response-error         -> htmx:htmx:response-error
DEAD  notebook_detail.html   hx-on::htmx:after-request          -> htmx:htmx:after-request
DEAD  notebook_detail.html   hx-on::htmx:response-error         -> htmx:htmx:response-error

4 of 4 hx-on attributes expand to an event htmx never dispatches
```

The real names are present in the bundle and are what a correct attribute would
reach:

```
$ .venv/bin/python -c "…grep htmx:* literals…"
  htmx:afterRequest    kebab-> htmx:after-request
  htmx:responseError   kebab-> htmx:response-error
```

Corroborating check with the same algorithm on the three legal spellings:

```
$ node -e '…htmx Pt() expansion…'
"hx-on::htmx:after-request" -> "htmx:htmx:after-request"     <- shipped
"hx-on::after-request"      -> "htmx:after-request"          <- correct
"hx-on:htmx:after-request"  -> "htmx:after-request"          <- correct
```

**Proposed fix:** rename to `hx-on::response-error` / `hx-on::after-request`
(2 attributes in m11's block; 8 more elsewhere — fix all ten in one commit, the
bug is identical). Add a derived guard that expands every `hx-on*` attribute in
`server/frontend/templates/` through htmx's algorithm and asserts the result is
in the bundle's dispatchable set. A string-equality guard would not have caught
this and neither did any of the fourteen UI test files.

---

**F2 — m11 permanently killed m8's `table:has(tbody:empty) thead th`, the rule it cites as precedent** (HIGH)

**Where:** `server/frontend/static/app.css:226` (the dead rule);
`server/frontend/static/app.css:129` and
`server/frontend/templates/notebook_detail.html:217` (the comments that cite it)

**What:** m8's M16 rectify dropped the `<thead>` boundary from the section rung
to the row rung "with no papers … a structural boundary separating a header
from nothing". Its only site was the papers table, whose `<tbody>` held nothing
but the `{% for %}` loop. m11 moved the empty state **into** that tbody, so the
tbody now contains `<tr id="papers-empty">` in **every** state. `tbody:empty`
can never match again, on either page. m11's own comments name this rule twice
as the precedent for using `:has()` while removing its last subject.

**Why it matters:** a zero-paper notebook — the exact state m11 is authoring —
now draws the ladder's heaviest rule under a header with nothing below it,
which is precisely the defect m8 shipped a rule to fix. The m8 guard
(`tests/test_ui_m8_rule_ladder.py:682`) registers the selector with cue kind
`DEGENERATE` and note "no rows below it to separate from"; that justification is
now false and the guard still passes, so the registry documents a rationale for
a rule with no site.

**Reproduced:** rendered `notebook_detail.html` with `papers=[]` through the
app's own Jinja settings (`server/routes/ui.py:98` — no `trim_blocks`, no
`lstrip_blocks`), at HEAD and at `3338b43~1`:

```
=== HEAD (m11) tbody inner ===
'\n      \n      <tr id="papers-empty">\n        <td colspan="4" class="empty">…'
has element child: True

=== 3338b43~1 (pre-m11) tbody inner ===
'\n      \n    '
has element child: False
is truly empty string: False
```

Note the pre-m11 content is whitespace-only, not empty. Under Selectors Level 3
`:empty` (whitespace text nodes count as children — the behaviour every shipping
engine implements today) the rule **was already dead before m11**; under the
Level 4 whitespace-ignoring definition it matched before m11 and does not now.
Under **either** reading it is dead after m11, because the tbody now has an
element child. I cannot render in a browser to settle which `:empty` semantics
apply, and the finding does not depend on it.

**Proposed fix:** replace `table:has(tbody:empty) thead th` with
`table:has(#papers-empty:not(:has(~ tr))) thead th`, or scope it off `#papers-empty`
directly, so the rule tracks the state it was written for. Then extend the m8
guard so a `DEGENERATE` site must resolve to a live subject in a rendered
template, not merely be listed.

---

**F3 — the control's label ships in the muted empty-state grey; `.empty-action` resets font-style and text-align but not colour** (HIGH)

**Where:** `server/frontend/static/app.css:138` (`.empty > .empty-action`), against
`:122` (`.empty { color: #666 }`) and `:583` (`.empty { color: #9ba1a8 }` dark);
markup at `server/frontend/templates/notebook_detail.html:247-250`

**What:** the authored comment above the rule says the control "takes the
ordinary control voice back". The rule sets `font-style: normal; text-align:
left; max-width; margin-inline` — and **no `color`**. `label` (app.css:141)
declares no colour, so the label "Add the first paper by arXiv URL" inherits
`#666` / `#9ba1a8` from `.empty` at `--text-small` (13px). Every other form
label in the product renders at `--fg`. The `<input>` escapes (UA sets its own
colour) and the `<button>` escapes (explicit `#fff` / `var(--bg)`), so the
label is the one part of the control still wearing the empty-state voice.

**Why it matters:** it does not fail AA, but it is a 3x headroom reduction
against every sibling label, and a form label in recessive grey reads as
disabled. It also makes the CSS comment factually wrong, which in this repo is
itself the defect class (m8's "unedited line and an oversight are
indistinguishable").

**Reproduced:** the repo's own colour math, `tests/_ui_color.py`:

```
$ .venv/bin/python  (load_tokens + contrast_ratio + mix_oklab)
== light ==  --bg=#f6f9fb  row_hover=#edeff2
  .empty text #666666 on --bg            : 5.4306
  .empty text #666666 on tbody tr:hover  : 4.9844
== dark ==   --bg=#090e13  row_hover=#1b2127
  .empty text #9ba1a8 on --bg            : 7.4339
  .empty text #9ba1a8 on tbody tr:hover  : 6.2292
```

Compared with what every other `<label>` gets (`--fg` on `--bg`, already row 1
of `.claude/docs/ui-contrast-table.md`): **16.0:1 light / 14.0:1 dark**.

Separately: `#666` and `#9ba1a8` are hardcoded literals, not tokens — two of the
eleven that `tokens.css` records as debt `--fg-muted` was minted to absorb and
never did. m11 routed *new* text (the cause line and the label) through them
rather than through the token system this epic exists to establish.

**Proposed fix:** add `color: var(--fg);` to `.empty > .empty-action` — that is
what "takes the ordinary control voice back" means and it removes the label from
the literal-grey chain entirely. Leave `.empty-cause` on the muted voice; if it
is to keep a colour, migrate it to `--fg-muted` (7.0176 light / 7.7039 dark,
both measured above) rather than `#666`.

---

**F4 — the new control is a filled primary CTA in the one section whose own comment refuses a filled primary CTA on BAN-9** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:252` (the button)
versus `:178-184` (the refusal, ~70 lines above it in the same `<section>`)

**What:** `<button type="submit">Add</button>` takes the default button rule
(`app.css:180-191`: `background: var(--accent); color: #fff`) — a filled primary
CTA. The comment on the papers `<h2>` says, of this exact region:

> "Deliberately a LINK and not a duplicated control: a second Add/Ingest button
> up here would be a second primary CTA in one viewport, which BAN-9 forbids."

m10's rectify (M14) demoted the per-candidate Discover "Add" buttons to
`button.button-quiet` for the same reason. m11 then added a filled primary Add
to that section without addressing either precedent, while simultaneously
invoking BAN-9 in the commit message and the roadmap AC to **refuse** controls
on the other two empty states.

**Why it matters:** the rule is applied in one direction only. On a first-run
empty notebook the page is short and the accent-filled `Rename` submit
(`notebook_detail.html:100`, also outside the disclosure) and the new accent-filled
`Add` render together; the `danger`-filled Remove-notebook button
(`:157`) is in the same block. Either BAN-9 means what m12's comment and m10's
rectify say it means — in which case this button needs `button-quiet` — or the
BAN-9 refusals recorded against the index and discover empty states do not hold
and those two should get their controls.

**Reproduced:** structural read of the template — the identity `<section>` spans
lines 63-166, the papers `<section>` 171-295, and `<details class="manage-disclosure">`
does not open until line 387, so lines 100, 157 and 252 are all outside the
disclosure and render unconditionally:

```
$ grep -n '<details\|<section\|</section>\|<button\|class="button' server/frontend/templates/notebook_detail.html
63:<section>          100:    <button type="submit">Rename</button>
157:    <button type="button" … class="danger">      166:</section>
171:<section>          252:            <button type="submit">Add</button>      295:</section>
387:<details class="manage-disclosure" …>
```

**Proposed fix:** add `class="button-quiet"` to the empty-state submit — m10
already built and measured that variant for this exact rule — or escalate the
BAN-9 reading and revisit the two refusals in the same pass. Whichever is chosen,
record it once rather than in three places that disagree.

---

**F5 — using the control destroys it and drops focus to `<body>`** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:238-253` +
`server/frontend/static/app.css:131` (`#papers-empty:has(~ tr) { display: none; }`)

**What:** the submit button lives inside `#papers-empty`. On a successful add,
htmx appends a `<tr>` to `#papers-tbody`, `:has(~ tr)` starts matching, and the
whole row — cause line, label, input, button, `<output>` — becomes
`display: none`. The button also carries `hx-disabled-elt="find button"`, so it
is `disabled` (and therefore blurred) before the swap even lands. htmx's focus
restoration only fires for a saved active element that has an `id` and has left
the document (`if(t.elt&&!se(t.elt)&&ee(t.elt,"id")){…f.focus(a)}` in the
vendored bundle); this button has no `id`, and by swap time the saved active
element is `<body>`, which is still in the document. Nothing re-homes focus.

**Why it matters:** a keyboard or screen-reader operator who adds the first
paper is returned to the top of the document with no indication of where they
are, and the control they were using no longer exists — to add a second paper
they must find the `Manage this notebook` disclosure, open it, and tab to a
different Add-by-URL form. The "one actual control" AC#1 asks for is a one-shot.
This is WCAG 2.4.3 (Focus Order) territory, and the *disappearance* half is
specific to m11 — the other five forms stay on screen after use.

**Reproduced:** by construction from the three shipped artifacts —
`display:none` on the ancestor row (app.css:131), the absence of any `id` on
`<button type="submit">Add</button>` (notebook_detail.html:252), and htmx's
restore condition quoted above from `server/frontend/static/htmx.min.js`. I
could not observe the resulting `document.activeElement` (no browser); see the
final section.

**Proposed fix:** give the button an `id` and, in the (repaired, per F1)
`after-request` handler, move focus deliberately — to the papers `<h2>` with
`tabindex="-1"`, or to the newly appended row. That also gives the operator a
spoken landing point for what just happened.

---

**F6 — `.empty` on the row-hover ground is unregistered in the contrast registry, and m11 put it on a second hoverable row** (MEDIUM)

**Where:** `tests/test_ui_contrast.py:265,272` (the two `.empty` rows, both on
`--bg` only) versus `server/frontend/static/app.css:267`
(`tbody tr:hover { background: color-mix(in oklab, var(--card-bg) 95%, var(--fg)) }`)

**What:** `#papers-empty` is a `<tr>` inside `<tbody>`, so hovering it repaints
the ground under the cause line, the label and the (unstyled-background)
`<output>`. `ROW_HOVER` exists in the registry and is used for eight other
pairs, but `.empty` has no hover row in either mode. The registry's own
sourcing note claims a "full read of app.css plus every Jinja2 template".

**Why it matters:** the pointer is *on* this row for the whole time the operator
uses the control, so the hover ground is the ground the empty state is actually
read against. The measured values pass — this is a measurement gap, not a
failure, and saying otherwise would be inventing one. But
`.claude/docs/ui-contrast-table.md` publishes 95 pairs and claims completeness;
two of the surfaces it covers are wrong about their ground.

**Reproduced:**

```
$ grep -n "empty" .claude/docs/ui-contrast-table.md
419 | 49 | light | .empty #666    | #666666 | #f6f9fb | 5.431:1 | 4.5:1 | 1.4.3 | PASS
424 | 54 | dark  | .empty #9ba1a8 | #9ba1a8 | #090e13 | 7.434:1 | 4.5:1 | 1.4.3 | PASS
                                    (no row with ground #edeff2 / #1b2127)
```

and the missing values, computed with `tests/_ui_color.py`:

```
light  .empty #666666  on #edeff2 (tbody tr:hover) : 4.9844   floor 4.5  PASS
dark   .empty #9ba1a8  on #1b2127 (tbody tr:hover) : 6.2292   floor 4.5  PASS
```

The artifact is also stale: `.claude/docs/ui-contrast-table.md` was last written
`Aug 5 11:39`, before `app.css` (`14:57`) and before this commit.

**Proposed fix:** two `_p(_m, ".empty on tbody tr:hover", …, ROW_HOVER, TEXT)`
rows and a regenerate. If F3's `color: var(--fg)` fix lands, add the label's own
pair rather than assuming it inherits.

---

**F7 — the product's first nested live region, and on a populated notebook it sits inside a `display:none` ancestor** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:253`
(`<output id="papers-empty-error">`) inside `:201` (`<tbody id="papers-tbody" aria-live="polite">`);
guard at `tests/test_ui_m13_live_region_hygiene.py:58-66`

**What:** two things at once. (a) `#papers-empty-error` is the only one of the
thirteen live regions on the page that is nested inside another live region — an
`<output>` (implicit `role=status`, `aria-live=polite`) inside an explicit
`aria-live="polite"` tbody. (b) Whenever the notebook has at least one paper,
`#papers-empty` is `display: none`, so this live region is **not in the
accessibility tree** — which is the exact condition m13's headline finding was
about ("a live region must be present and rendered BEFORE its content arrives").

**Why it matters:** m13 built a whole module around live-region hygiene and its
only m11 change was appending `"papers-empty-error"` to `ERROR_BLOCK_IDS`. That
list drives `.error:empty`-has-no-`display:none` checks (which the new output
*does* satisfy — `app.css:420` sets only `padding/margin/min-height/background`,
correctly). It does not check nesting, and it does not check that a live region's
ancestors are rendered. Announcement behaviour for a status region inside a
polite region is implementation-dependent across AT; I am flagging the structure,
not asserting a specific double-announcement, which I cannot observe.

**Reproduced:** parsed the rendered detail page and listed every live region with
its `aria-live` ancestors:

```
output#rename-error          (none)
output#papers-empty-error    ['tbody#papers-tbody=polite']   <- the only nested one
output#topic-error           (none)
output#discover-error        (none)
output#paste-error           (none)
output#upload-error          (none)
output#ingest-error          (none)
div#ingest-live              (none)
span#status-live             (none)
```

and confirmed m13's guard change is list-membership only:

```
$ git show 3338b43 -- tests/test_ui_m13_live_region_hygiene.py
+    "papers-empty-error",      (six lines, all comment + one tuple entry)
```

**Proposed fix:** move the `<output>` out of `#papers-tbody` — put it beside the
table, outside the row, and keep its id — or set `aria-live="off"` on the
region that should not own it. Add a m13 assertion that no live region has a
live-region ancestor and that every live region's ancestor chain is renderable.

---

**F8 — the error output is not programmatically associated with the input it describes** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:247-253`

**What:** the `<input>` has no `id`; the `<output>` has no `for`; there is no
`aria-describedby` from the field to the error and no `aria-invalid` is ever
set. The error is (meant to be) announced once by the live region and then has
no relationship to anything.

**Why it matters:** a screen-reader user who hears "arXiv URL is not valid",
tabs back to the field to correct it, and re-reads the field gets the label and
nothing else — the error is unreachable from the control it is about. This is
SC 3.3.1 / 4.1.2 shape. It is a repo-wide pattern (all seven `<output class="error">`
blocks are the same), but m11 is the first one authored *after* m13 established
the `<output>` contract, and it is the only one whose form is presented as a
first-run onboarding control.

**Reproduced:**

```
$ sed -n '247,253p' server/frontend/templates/notebook_detail.html
            <label>
              Add the first paper by arXiv URL
              <input type="url" name="arxiv_url" required maxlength="512"
                     placeholder="https://arxiv.org/abs/2604.26204">
            </label>
            <button type="submit">Add</button>
            <output id="papers-empty-error" class="error"></output>
$ grep -c 'aria-describedby\|aria-invalid' server/frontend/templates/notebook_detail.html
0
```

**Proposed fix:** `id="papers-empty-url"` on the input,
`aria-describedby="papers-empty-error"` on it, and `for="papers-empty-url"` on
the `<output>`. Set `aria-invalid="true"` in the (repaired) error handler and
clear it on the next submit.

---

**F9 — the cause line and the control it explains do not share a left edge** (MEDIUM)

**Where:** `server/frontend/static/app.css:137-138`

**What:** `.empty > .empty-action` resets `text-align` to `left` and constrains
itself to `max-width: 32rem; margin-inline: auto`. `.empty > .empty-cause` sets
only `margin`, so it keeps `text-align: center` and the full td width from
`.empty` (`:122`). The result is a centred sentence sitting above a
left-aligned form block that is itself horizontally centred within a much wider
cell.

**Why it matters:** `body` is `max-width: clamp(640px, 92vw, 1400px)`, so on a
wide monitor the cause is centred across up to ~1370px while the control is a
512px block; the two halves of the "cause + one action" anatomy read as two
unrelated elements. The CSS comment justifies the `text-align` reset by saying a
centred form row "reads as a marketing 404" — that argument applies equally to
the centred sentence directly above it, and it was not applied there.

**Reproduced:** read of the two rules; the cause paragraph receives no
`text-align` declaration anywhere:

```
$ grep -n 'text-align' server/frontend/static/app.css
122:.empty { color: #666; font-style: italic; text-align: center; … }
138:.empty > .empty-action { font-style: normal; text-align: left; … }
216:th, td { text-align: left; … }        (specificity 0,0,2 — loses to .empty)
```

**Proposed fix:** give `.empty > .empty-cause` the same
`text-align: left; max-width: 32rem; margin-inline: auto` box as
`.empty-action`, so the anatomy is one column. Or drop the reset on
`.empty-action` and centre both — but that is the register the comment refuses.

---

**F10 — the m12 guard that survived m11 now inspects only the cause sentence** (MEDIUM)

**Where:** `tests/test_ui_m12_corpus_before_machinery.py`, `TestEmptyStateCopyIsNotWrong._empty_copy()`

**What:** m11 rewrote the guard to read
`<(?:p|td)[^>]*class="empty"[^>]*>(.*?)</(?:p|td)>`. The lazy group now
terminates at the first `</p>` — the close of `.empty-cause` — so the
"must not point upward" assertion covers the cause sentence and nothing else.
The form m11 added, including its label copy, is outside the guard's subject.

**Why it matters:** the guard's docstring says it asserts against "whatever
element carries the empty state rather than against the `<p>` m12 happened to
ship". It does not; it asserts against a different `<p>` that m11 happened to
ship. If a future edit puts "above" in the label or the button, this guard
passes.

**Reproduced:**

```
$ .venv/bin/python -c "…apply the guard's own regex to the stripped template…"
m12 guard _empty_copy() sees:
'\n          <p class="empty-cause">Nothing indexed yet — this notebook has no papers.'
contains the form's label text 'Add the first paper by arXiv URL'?  False
```

**Proposed fix:** match the whole `<td class="empty">…</td>` with a balanced or
tag-aware extraction (the file already has a `_Dom` parser in the m13 sibling),
or assert against the concatenated text of the parsed subtree.

---

**F11 — the required URL format lives only in the `placeholder`** (LOW)

**Where:** `server/frontend/templates/notebook_detail.html:248-250`

**What:** the label says "Add the first paper by arXiv URL"; the only statement
of what that URL looks like is
`placeholder="https://arxiv.org/abs/2604.26204"`, which disappears the moment
the operator types and is never announced as part of the field's description.

**Why it matters:** this is the product's first-run surface — the one field
whose user has definitionally never seen the format before. Every other
identifier input on the page has a `<p class="hint">` above it stating the rule
(the create form's slug pattern, `index.html:20-23`; the upload form's paper-id
derivation, `notebook_detail.html:533-538`). The empty-state control has none.
SC 3.3.2 (Labels or Instructions).

**Reproduced:**

```
$ sed -n '235,254p' server/frontend/templates/notebook_detail.html   # no .hint in the block
$ grep -n 'class="hint"' server/frontend/templates/notebook_detail.html
183:    <a class="hint" href="#manage">Manage this notebook</a>
276:            <span class="hint" title="upload an ar5iv HTML to enable preview">Preview</span>
447: 482: 533:  …   (one per mutation block inside the disclosure)
```

**Proposed fix:** either move the example into the label text ("…by arXiv URL,
e.g. `arxiv.org/abs/2604.26204`") or add it to the `<output>`'s description
target once F8's `aria-describedby` exists. Keep the placeholder as well; do not
rely on it alone.

---

**F12 — two identically-purposed `arxiv_url` fields are exposed simultaneously on an empty notebook with the disclosure open** (LOW)

**Where:** `server/frontend/templates/notebook_detail.html:249` and `:522`

**What:** m11's control and the disclosure's Add-by-URL form both render an
`<input type="url" name="arxiv_url" required maxlength="512">` with the same
placeholder, posting the same endpoint, each with its own submit button labelled
"Add". On a populated notebook the empty-state one is `display:none` and out of
the tree; on an empty notebook with the disclosure collapsed the disclosure one
is out of the tree. Open the disclosure on an empty notebook and both are live
at once.

**Why it matters:** a screen-reader user pulling up the form-field or button
list sees two "Add" buttons and two arXiv-URL fields with different labels and
identical behaviour. Minor, and bounded to one state, but it is the concrete
cost of the second form and it is not recorded anywhere in the commit.

**Reproduced:**

```
$ grep -n 'name="arxiv_url"' server/frontend/templates/notebook_detail.html
249:              <input type="url" name="arxiv_url" required maxlength="512"
522:      <input type="url" name="arxiv_url" required maxlength="512"
$ grep -n '<button type="submit">Add</button>' server/frontend/templates/notebook_detail.html
252:            <button type="submit">Add</button>
525:    <button type="submit">Add</button>
```

**Proposed fix:** cheapest correct option is to make the empty-state form the
*only* one rendered when `papers` is empty (wrap the disclosure's Add-by-URL
block in `{% if papers %}`), which also removes the duplicate endpoint that
forced four guard relaxations. Otherwise differentiate the button labels.

---

**F13 — `.empty > *` child combinators make the anatomy silently fragile** (LOW)

**Where:** `server/frontend/static/app.css:137-138`

**What:** both new rules use `>`. The entire visual reset of the control —
`font-style: normal`, `text-align: left`, the width box — depends on the
`<form>` being a *direct* child of the `.empty` cell. Wrapping the anatomy in a
`<div>` for any layout reason (which is the obvious next edit, and is what F9's
fix would tempt) silently returns the whole control to centred italic.

**Why it matters:** silent, not loud, and nothing tests the computed result —
`tests/test_ui_class_css_coverage.py` only asserts that each emitted class has
*a* rule, which would still hold.

**Reproduced:**

```
$ sed -n '137,138p' server/frontend/static/app.css
.empty > .empty-cause { margin: 0 0 0.75rem 0; }
.empty > .empty-action { font-style: normal; text-align: left; max-width: 32rem; margin-inline: auto; }
$ .venv/bin/python -m pytest tests/test_ui_class_css_coverage.py -q   # passes; checks existence only
```

**Proposed fix:** drop the `>` to a descendant combinator, or set
`font-style: normal` on the control elements themselves
(`.empty-action, .empty-action *`). Either survives a wrapper.

---

## What I could not verify and why

**No browser is available in this environment.** Nothing below was rendered,
measured on screen, or driven with a keyboard or screen reader. Specifically:

1. **Every layout claim is computed, not observed.** F9's misalignment is read
   off the cascade, not from a screenshot. I did not confirm the rendered pixel
   positions of the cause line or the form block at any viewport.

2. **The 375px / narrow-viewport question is unresolved, and I am not filing a
   finding for it.** I looked for a forced horizontal scroll from
   `max-width: 32rem` on a form inside a `<td>` inside `.table-wrap { overflow-x: auto }`
   and could not construct one on paper: `32rem` = 512px is a *maximum*, the
   percentage `width: 100%` on the input degrades to `auto` during min-content
   sizing so the cell's minimum is roughly the input's default `size=20`
   intrinsic width plus padding (~210px), and the four `<th>` minimums with no
   body rows sum to well under a 343px content box. That reasoning is not a
   measurement. Anyone with a browser should check 320px and 375px directly,
   and should also check whether the label string wraps to three lines.

3. **`:empty` semantics (F2).** I could not determine empirically whether the
   engines this product targets implement Selectors L3 `:empty` (whitespace
   counts) or the L4 revision (whitespace ignored). F2 holds under both, and I
   said so, but the claim "the rule was *already* dead before m11" is only true
   under L3 and I have not verified it.

4. **Focus behaviour after submit (F5).** The mechanism is read from the
   vendored htmx source and the shipped attributes. I did not observe
   `document.activeElement` after a successful add, and I did not confirm that
   setting `disabled` via `hx-disabled-elt` blurs in every engine (it does per
   spec; I did not test it).

5. **Screen-reader announcement behaviour (F7, and the table-semantics axis
   generally).** I established the *structure* — the only nested live region in
   the product, and a `<form>` inside a `<td colspan="4">` inside an
   `aria-live="polite"` `<tbody>`. I did **not** verify what NVDA, JAWS or
   VoiceOver actually speak: not whether the nested `role=status` produces one
   announcement or two, not whether hiding `#papers-empty` triggers a removal
   announcement (default `aria-relevant="additions text"` says it should not,
   but implementations vary), and not how a form inside a table cell is
   announced in browse vs. forms mode. Those need a real AT session; I have
   deliberately not asserted any of them as defects.

6. **`::placeholder` contrast.** The placeholder colour is UA-supplied and I
   could not read its computed value. It is unregistered in
   `tests/test_ui_contrast.py` in either mode, on both this form and the
   disclosure's. Flagged inside F11 as an instruction problem, not as a measured
   contrast failure, because I could not measure it.

7. **F1's blast radius outside m11.** I proved the four attribute *names* expand
   to undispatched events. I did not run the page, so I have not observed the
   eight non-m11 sites failing — including
   `index.html:38`'s `getElementById('notebooks-empty')?.remove()`, which the
   m11 commit message cites as the working precedent the papers table needed a
   CSS alternative to. If F1 is right, that hook has never fired and the index
   page has the same stale-empty-row bug m11 says it structurally fixed on the
   papers table. That is a claim about the index, which is outside m11's diff,
   and I am recording it as a consequence to check rather than as a finding.

**Checked and clean — recorded so a later pass does not redo them:**

- `<td colspan="4">` matches the papers table's four `<th>` (`notebook_detail.html:193`).
- The inherited-italic axis is **not** a defect: `.empty-action`'s
  `font-style: normal` reaches the label, and the UA `font:` shorthand on
  `<input>`/`<button>` resets it independently.
- `.error:empty` (`app.css:420`) sets only `padding/margin/min-height/background`
  and **not** `display: none`, so the new `<output>` obeys m13's rule at the
  rule level (see F7 for the ancestor-visibility variant).
- All three add paths target `#papers-tbody` with `beforeend`
  (`:242-243`, `:515-516`, `:545-546`), so `#papers-empty:has(~ tr)` covers all
  three; nothing appends before the empty row.
- AC#3 holds — no icon anywhere in the new markup.
- `hx-ext="json-enc"` is present on the new form and `json-enc.js` is loaded
  (`base.html:50`), so the request encoding is correct.
- `.empty-cause` / `.empty-action` both have rules;
  `tests/test_ui_class_css_coverage.py` passes.
- `app.css` is 694 lines against the 720 cap, raised in lockstep in all three
  sibling tests.
- The full UI guard set passes:
  `test_ui_contrast.py`, `test_ui_m8_rule_ladder.py`,
  `test_ui_m13_live_region_hygiene.py`, `test_ui_m12_corpus_before_machinery.py`,
  `test_ui_class_css_coverage.py`, `test_ui_m3/m4/m5/m7` — 421 passed. Which is
  the point: none of the thirteen findings above is caught by anything.

---
milestone_id: "ui-uplift-m12"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — ui-uplift-m12

Corpus before machinery — reorder the detail page (v0). UPL-1, parent
`ui-uplift-e3`, `depends_on: [ui-uplift-m8]`.

All line numbers are against the worktree snapshot
`.claude/worktrees/agent-a1f291c49bb395883`, taken 2026-08-04. Paths below
are repo-relative.

---

## 0. Headline corrections to the Phase-0 findings

Three of the orchestrator's premises need adjusting before the implementer
reads anything else. Each is derived below.

| # | Phase-0 premise | Verdict | Where |
|---|---|---|---|
| 1 | "The brief says FIVE mutation forms; the template has SIX `<form>`s" | **Confirmed, and the sixth matters more than expected.** The sixth is the **rename** form, inside the LEADING identity section. The Discover form is one of the five. AC#1 as literally worded cannot be met while rename stays. | §1, §3 |
| 2 | "`<details>` is already in the product — m10 shipped **two** in `notebooks.py`" | **Partly wrong.** There is exactly **ONE** `<details>` in product code (`server/routes/notebooks.py:747`). More importantly, `server/routes/ui.py:283` records an **explicit prior REJECTION** of `<details>` under a poll — the closest precedent to AC#2, and it points the opposite way. | §4 |
| 3 | "The 1823px figure predates m7/m8/m10, so it is probably wrong now" | **Wrong in direction.** m8's two spacing changes nearly cancel. Current best estimate **≈1740px** (bracket 1700–1790), i.e. within ~5% of the recorded figure. The number that IS stale is the **m8 critique's "+96px"** claim — it describes a design m8's own rectify replaced. | §2 |

A fourth finding not in the Phase-0 list, and the largest single risk:

> **`app.css:64-65`'s rule ladder uses a DIRECT-CHILD selector**
> (`main > :where(section, div) + …`). Wrapping the five blocks in
> `<details>` removes them from `main`'s child list, so **every moved block
> silently loses its rule, its margin and its padding**. This is a
> guaranteed visual regression that no existing test catches. See §6.

---

## 1. Block inventory of `notebook_detail.html`, in document order

381 lines. `{% block content %}` spans 5–381. Seven top-level blocks (two
`<section>`, five `<div>`) plus a `<nav>` that the m8 guard does not count
(`app.css:57` — *"`main >` excludes .breadcrumb"*).

Classification column: **LEADS** = identity/state/corpus, stays above.
**MOVES** = mutation machinery, goes into the disclosure.

| # | Lines | El | Heading | Contains | Forms (`hx-target` → `hx-swap`) | Verdict |
|---|---|---|---|---|---|---|
| — | 6 | `nav.breadcrumb` | — | "← All notebooks" | none | LEADS (untouched) |
| 1 | 14–105 | `section` | `<h2><code>{{slug}}</code></h2>` | `p#display-name-block` (aria-live), **rename form**, `dl.meta` (LanceDB path / Created / Parse status / Last indexed), `div.notebook-actions` → Delete button | **`form.rename-form`** (37–53) `#display-name-block` → `outerHTML` | **LEADS** (identity + state) — but see §3, the embedded form is the AC#1 problem |
| 2 | 108–159 | `div` | Topic & discovery | `div#topic-block` (aria-live) readback, topic form | **`form.topic-form`** (133–158) `#topic-block` → `outerHTML` | MOVES |
| 3 | 162–194 | `div` | Discover papers | hint, Discover form, `div#discover-results` (aria-live, aria-atomic) | **Discover form** (180–190) `#discover-results` → `outerHTML` | MOVES |
| 4 | 197–235 | `div` | Add paper by URL | hint, URL form | **Add-paper form** (218–234) `#papers-tbody` → `beforeend` | MOVES — **cross-block target, see §3** |
| 5 | 238–266 | `div` | Upload ar5iv HTML | hint, multipart form | **Upload form** (246–265) `#papers-tbody` → `beforeend` | MOVES — **cross-block target, see §3** |
| 6 | 269–316 | `div` | Ingest | hint (names the 2s poll), Ingest form, `div#ingest-status` placeholder | **Ingest form** (280–290) `#ingest-status` → `outerHTML` | MOVES — **carries the poll, see §4** |
| 7 | 319–380 | `section` | Papers in this notebook ({{n}}) | `p.empty` (conditional), `div.table-wrap` → `table.papers` → `tbody#papers-tbody` (aria-live) + per-row Preview link and Remove button | none | **LEADS** (the corpus — the point of the reorder) |

### Resolving "five" vs "six"

The brief's "five mutation forms" traces to the m8 comment at
`notebook_detail.html:8-12`, which says *"the **five job forms** drop to
DIV"*. That sentence counts **blocks**, not forms — blocks 2–6. The roadmap
summary reused the count as if it enumerated forms.

Corrected inventory:

- **6 `<form>` elements** total.
- **5 live in the five moving DIVs** (topic, discover, add-paper, upload,
  ingest) — this is the set the brief means.
- **The 6th is `form.rename-form` at :37**, inside block 1, the identity
  section that LEADS. The brief overlooked it; it is not the Discover form.
- **The Discover form IS a mutation-adjacent job trigger but is one of the
  five.** It POSTs to `/discover`, which runs the m3 arXiv driver and returns
  a fragment. The template states the queue is EPHEMERAL (:177 — *"The
  candidate queue is EPHEMERAL (no persistence)"*), so it mutates nothing
  server-side. It is a *job trigger*, exactly like Ingest. Both still belong
  in "machinery".
- **Two mutations are NOT forms and are easy to miss in a `<form>` grep:**
  the **Delete notebook** button (:96–103, `hx-delete` + `hx-confirm`, inside
  block 1) and the per-row **Remove** button (:366–373, `hx-delete`, inside
  block 7). Neither has an `hx-target`; both are in LEADING blocks. Leave
  them where they are — Remove must stay with the row it deletes, and Delete
  is an identity-scoped action.

**Net for AC#4:** the AC says "the five moved forms". Take that literally —
five forms move, rename does not — and AC#1 fails on its own wording. See §3.

---

## 2. The 1823px claim — provenance, and a current estimate

### Provenance

The figure is **measured, not inferred**, and traces to one artifact:

- **`.claude/notes/frontend-uplifts/2026q3-ui-uplift/discover/visual-manifest.md:96`**
  — the per-block geometry table, §3 *"Layout geometry — measured at
  1440×900"*. The manifest's own header (`:7-8`) says the screenshot action
  failed, so everything is `✓ measured` via **live DOM geometry**, and there
  are no PNGs.
- Seven downstream restatements (`synthesis.md:51,201,206`,
  `final-report.md:233,428`, `art-direction-scout-brief.md:68,91,328,350,440`,
  `visual-scout-brief.md:43,89,147`, `current-state-critic-brief.md:34,149`)
  all cite that one table. **One measurement, eight citations** — treat the
  repetition as amplification, not corroboration.

What it measured: the top edge of card #7 ("Papers in this notebook") in a
`docHeight 2343px` document, viewport 1440×900, content column 1325px,
**with `.card` still present**, on a notebook with 6 papers.

Recorded table (y / h, card border-box):

| # | block | y | h |
|---|---|---|---|
| 1 | record | 161 | 358 |
| 2 | topic | 535 | 310 |
| 3 | discover | 861 | 194 |
| 4 | add paper | 1071 | 211 |
| 5 | upload | 1297 | 306 |
| 6 | ingest | 1620 | 187 |
| 7 | **papers** | **1823** | 414 |

### Re-derivation for the current tree — the arithmetic

**Step A — recover the old inter-block pitch.** Measured gaps between card
boxes are 16px throughout (535−519 = 16, 861−855 = 6… recompute: 161+358 = 519,
535−519 = **16**; 535+310 = 845, 861−845 = **16**; 861+194 = 1055,
1071−1055 = **16**; 1071+211 = 1282, 1297−1282 = **15**; 1297+306 = 1603,
1620−1603 = **17**; 1620+187 = 1807, 1823−1807 = **16**). That 16px is
`.card`'s `margin-bottom: 1rem`. The card box additionally carries
`padding: 1rem 1.25rem` and a 1px border, so:

```
old content-to-content pitch
  = 16 (pad-bottom) + 1 (border) + 16 (margin) + 1 (border) + 16 (pad-top)
  = 50px      … at every one of the six boundaries
```

**Step B — the shipped m8 ladder.** `app.css:64-65`:

```css
main > :where(section, div) + section { … margin-block-start: 2rem;    padding-block-start: 2rem;    }
main > :where(section, div) + div     { … margin-block-start: 1.25rem; padding-block-start: 1.25rem; }
```

```
boundary → div     = 20 + 1 + 20 = 41px
boundary → section = 32 + 1 + 32 = 65px
```

Block sequence is `S D D D D D S`, so five `→div` boundaries and one
`→section` boundary:

```
Δ_ladder = 5 × (41 − 50) + 1 × (65 − 50)
         = −45 + 15
         = −30px
```

**The page got ~30px SHORTER to the papers table under m8, not longer.**

**Step C — why the m8 critique's "+96px" is stale.**
`.claude/notes/milestones/ui-uplift-m8/critique/dedup.md:139` claims the
corpus *"moved roughly 96px further down"*. That assumed a uniform 4rem
boundary (2rem margin + 2rem padding = 64 vs 48 → +16 × 6 = +96). m8's own
**rectify** then split the ladder — `app.css:59-63` says so in as many words:
*"one rule gave all nine boundaries the same rung … and every boundary paid
2rem+2rem (**~96px added to the detail page**)"*. The +96px describes the
pre-rectify state that did **not** ship. Do not quote it.

**Step D — m7 type scale.** `--text-section` went 1.100rem → 1.25rem
(`tokens.css:240`) and m7 added `line-height: 1.25` to `h2` (`app.css:71`).
Old h2 box ≈ 17.6 × 1.5 = 26.4px; new ≈ 20 × 1.25 = 25.0px. Δ ≈ −1.4px per
h2, six above the table → **≈ −8px**.

**Step E — m10 UPL-9 on the topic block.** `.topic-category` /
`.topic-description` were in `_KNOWN_UNSTYLED` before m10, so UA
`p { margin: 1em 0 }` applied. m10 gave them `margin: 0` and
`margin: 0.25rem 0 0 0`, and `.topic-block { margin: 0 0 0.75rem 0 }`
(`app.css:278-280`). Collapsed UA margins ≈ 48px → ≈ 16px, and both `<p>`
dropped from 16px to `--text-small` 13px. **≈ −40px.**

**Step F — header.** m7 put `h1` on `--text-title` `clamp(1.5rem, 4vw +
0.5rem, 2.25rem)` with `line-height: 1.2` (`app.css:44`). At 1440px the
clamp saturates at 2.25rem = 36px; box 43.2px vs the old UA `2em`/1.5 =
48px. **≈ −5px.**

### Result

```
1823  (recorded)
 −30  m8 rule ladder, net across six boundaries      (§ step B)
  −8  m7 h2 line-height + size                        (§ step D)
 −40  m10 topic-block margin + font-size collapse     (§ step E)
  −5  m7 h1 clamp + line-height                       (§ step F)
────
≈1740px
```

**Current estimate: ≈1740px, bracket 1700–1790px.** The residual uncertainty
is `--text-small`'s pre-m7 value (unknown from the manifest), which applies
to ~10 hint/label/`dl.meta` lines above the table and could take another
20–40px off the low end.

**Conclusion for the brief's headline: the 1823px claim is still
directionally correct and safe to cite with a "measured pre-m7/m8/m10;
≈1740px today" qualifier.** It remains **>1.9× a 900px viewport**. Do not
silently re-quote 1823 as a current number, and do not discard it either.

### Post-reorder projection (what AC#1 buys)

Everything above `main`'s first block ≈ 148px (body padding 16 + header
≈ 96 + breadcrumb ≈ 36). Record-section content ≈ 323px; the
record→papers boundary is `→ section` = 65px.

| reading | papers table top | vs 900px fold |
|---|---|---|
| rename form **stays** in the identity section | **≈ 536px** | clears |
| rename form **moves** into the disclosure (form ≈ 110px) | **≈ 426px** | clears |

Both readings satisfy "roughly one viewport" numerically. The choice is
decided by AC#1's wording, not by geometry — see §3.

---

## 3. Every `hx-target` on the page, and where it resolves (AC#4)

`hx-target="#id"` resolves through `document.querySelector` — **DOM position
and `<details>` open-state are irrelevant to resolution**. So "still
resolves" is satisfied for all six forms no matter how the page is reordered.
The AC's real content is its second clause: *"no swap silently lands out of
view."*

| Source | `hx-target` | Target element | Target's block after reorder | Swap | Risk |
|---|---|---|---|---|---|
| rename form :37 | `#display-name-block` | `p` :26 | block 1 — **LEADS** | `outerHTML` | If rename moves into the disclosure, the swap lands ~1000px **above** the form. Same failure shape as add-paper. If rename stays, no risk. |
| topic form :133 | `#topic-block` | `div` :123 | block 2 — moves **with the form** | `outerHTML` | **Safe.** Target is the form's own sibling; both inside the disclosure, and the form is only submittable when the disclosure is open. |
| discover form :180 | `#discover-results` | `div` :191 | block 3 — moves **with the form** | `outerHTML` | **Safe**, same reason. |
| **add-paper form :218** | `#papers-tbody` | `tbody` :341 | **block 7 — LEADS (moves ABOVE the form)** | `beforeend` | **THE AC#4 FAILURE.** Target flips from below the form to far above it. Operator submits at y≈1000 and the new row appends at y≈600, off-screen upward. |
| **upload form :246** | `#papers-tbody` | `tbody` :341 | **block 7 — LEADS (moves ABOVE the form)** | `beforeend` | **Same failure.** Identical target, identical direction. |
| ingest form :280 | `#ingest-status` | `div` :306 | block 6 — moves **with the form** | `outerHTML` | **Safe** for the submit path. The *poll* on the same element is a separate problem — §4. |
| ingest poll :310 | `#ingest-status` | itself | block 6 — inside the disclosure | `outerHTML` | Swaps into a collapsed `<details>` every 2s. This is AC#2's subject, not AC#4's. |
| Remove button :367 | *(none)* — `hx-on::after-request` does `this.closest('tr').remove()` | own `<tr>` | block 7 | — | **Safe.** No `hx-target`; self-relative. |
| Delete button :97 | *(none)* — `hx-on::after-request` navigates to `/ui/` | — | block 1 | — | **Safe.** |

### The two `#papers-tbody` forms are the whole of AC#4

Both are `beforeend` appends into a `tbody` that the reorder moves from
**below** the form to **above** it. Two mitigating facts and one aggravating
one:

- **Mitigating:** `tbody#papers-tbody` carries `aria-live="polite"`
  (:341), so screen-reader users still get the announcement. The failure is
  **sighted-only**.
- **Mitigating:** the papers table will be at y≈430–540 after the reorder, so
  on a 900px viewport a user scrolled to the disclosure may still have the
  table's lower rows on screen. Not guaranteed at any scroll depth.
- **Aggravating:** the row-count in the heading (`Papers in this notebook
  ({{ papers|length }})`, :320) is **server-rendered and does NOT update on
  a `beforeend` swap**. So after an in-place add, the table gains a row while
  the heading above it still says the old count — and the operator can now
  see neither. That drift exists today but is invisible because the table
  sits directly below the form; the reorder makes it observable.

The implementer needs a recorded decision here. Options, cheapest first:
(a) accept and document — the table is above the fold at all times;
(b) `hx-swap="beforeend show:#papers-tbody:bottom"` (htmx 2.x `show:`
modifier, no new dependency); (c) `hx-swap="beforeend scroll:…"`.
**Note (b)/(c) both cost zero CSS lines**, which matters given §7.

---

## 4. The ingest polling fragment (AC#2 / AC#3)

### The mechanism, end to end

- **Initial render** — `notebook_detail.html:306-315`:
  `<div id="ingest-status" data-status="placeholder" aria-live="polite"
  aria-atomic="true" hx-get="/ui/api/notebooks/{slug}/ingest/latest"
  hx-trigger="load" hx-target="#ingest-status" hx-swap="outerHTML">`.
  Fires **once on load**, then the returned fragment owns the loop.
- **Endpoint** — `server/routes/notebooks.py:2238-2311`
  (`latest_ingest`). Reads `await store.get_latest_ingest_run(slug)`
  (`:2283`) — **exclusively from SQLite, never the in-memory
  `IngestTaskTracker`** (`:2260-2267` documents why).
- **Fragment builder** — `_ingest_status_fragment`
  (`server/routes/notebooks.py:2357-2448`). Four branches.
- **Stop signal** — HTTP **286** on terminal states (`:2294-2299`), plus
  defense-in-depth: terminal fragments **omit** `hx-trigger` entirely.

### The four branches — the exact non-terminal set

| branch | `data-status` | source | carries `hx-trigger="every 2s"`? | HTTP | line |
|---|---|---|---|---|---|
| no row at all | `none` | `get_latest_ingest_run` → `None` | **YES** | 200 | 2392–2401 |
| running | `running` | `row["status"] == "running"` | **YES** | 200 | 2402–2413 |
| success | `success` | `row["status"] == "success"` | no | 286 | 2414–2422 |
| failed | `failed` | `row["status"] == "failed"` | no | 286 | 2423–2448 |

Status vocabulary is closed and lives on the store —
`server/notebooks_store.py:572-574`: `INGEST_STATUS_RUNNING = "running"`,
`INGEST_STATUS_SUCCESS = "success"`, `INGEST_STATUS_FAILED = "failed"`. The
`"none"` token is **synthesised by the route** (`:2288`) for the no-row case
and is not a store constant.

**So AC#2's "non-terminal or failed" resolves to: OPEN unless the state is
`success`.** Three of the four branches want the disclosure open —
`none`, `running` (both still polling) and `failed` (terminal, but the
operator must see the `<pre class="error">` stderr tail at `:2432-2433`).

Note `none` polls **forever**: a notebook that has never been ingested holds
a 2s poll for the life of the page. That is pre-existing behaviour, not
something m12 introduces, but it means "the disclosure is open by default on
a fresh notebook" — which is arguably the right outcome anyway, since a
fresh notebook is exactly when the operator needs the Add/Ingest machinery.

### Verified: the poll does NOT stop inside a closed `<details>`

Load-bearing for AC#2's premise, so I checked the vendored bundle rather than
recalling it. `server/frontend/static/htmx.min.js` is **htmx 2.0.10**
(vendored 2026-05-22). Its polling scheduler, minified as `ut`:

```js
function ut(e,t,n){
  const r=oe(e);
  r.timeout=x().setTimeout(function(){
    if(se(e)&&r.cancelled!==true){                 // se === bodyContains
      if(!pt(n,e,Xt("hx:poll:trigger",{triggerSpec:n,target:e}))){ t(e) }
      ut(e,t,n)
    }
  },n.pollInterval)
}
```

The **only** guards are `bodyContains(elt)` and a `cancelled` flag. There is
no `offsetParent` check, no `IntersectionObserver`, no visibility test. An
element inside a closed `<details>` is still in the document, so **the 2s
poll continues invisibly for the whole run**. AC#2's premise is correct as
written.

(Incidentally `pt` is `maybeFilterEvent`, i.e. the `hx-trigger="every 2s
[cond]"` filter. A conditional poll gated on `details.open` is a viable
*alternative* to force-opening the disclosure — worth naming in Phase 2 as
the road not taken, since it costs no CSS.)

### The prior art points the OTHER WAY — read this before designing AC#2

`server/routes/ui.py:280-286`, `onboarding-uplift-m3` AC5:

> *"m3 synthesis §3 D2 EXPLICITLY rejected `<details>`/`<summary>` because
> `hx-swap="outerHTML"` replaces the entire `<span>` every 10s and would
> snap any `<details>` closed on each poll. A static `<small>` block
> visible-when-degraded has no open-state to lose."*

Reinforced at `:311` and **pinned by a test** —
`tests/test_m3_endpoints.py:529-531` asserts `"<details" not in block`.

**Does that rejection apply to m12? No — but only because of one structural
detail, and the implementer must preserve it.** In the m3 case the
`<details>` would have been *inside* the swapped element, so every poll
destroyed and recreated it, losing `open`. In m12 the polled element
(`#ingest-status`) is a **descendant** of the disclosure; the `<details>`
itself is never a swap target. `outerHTML` on `#ingest-status` replaces only
that div, and the ancestor `<details>` keeps its `open` state untouched.

**This inverts into a hard constraint:** no swap on this page may ever target
the `<details>` element or any ancestor of it. Nothing today does — but m13
(the next milestone, `depends_on: [ui-uplift-m12]`) proposes moving
`aria-live` onto *"a stable never-swapped wrapper"*, which is exactly the
kind of change that could accidentally make the disclosure a swap target.
Flag it forward.

### AC#3 — the state cue is nearly free, and provably same-row

`server/routes/ui.py:461` — the detail-page view already does:

```python
latest_run = await store.get_latest_ingest_run(slug)
```

…and passes it to the template as `latest_run` (`:471`). **That is the
identical method the polling endpoint calls at
`server/routes/notebooks.py:2283`, against the identical SQLite table.** So
AC#3's "sourced from the same row the ingest fragment already reads" is
satisfiable exactly, not approximately.

Stronger: the template **already renders this value** at
`notebook_detail.html:84`:

```jinja
<span class="hint">(ingest <code>{{ latest_run.status }}</code>)</span>
```

So the `<summary>` cue should be `{{ latest_run.status }}` (with the
`latest_run is none` → `"none"` fallback to match the fragment's synthesised
token), and the OPEN predicate is the same expression:

```jinja
<details {% if not latest_run or latest_run.status != 'success' %}open{% endif %}>
```

One `latest_run` read drives both AC#2 and AC#3, and it is the same row the
fragment reads — so the cue **cannot drift by construction**, which is what
the AC is asking for.

Two drift caveats worth recording:

1. The cue is a **page-load snapshot**. The fragment updates every 2s; the
   `<summary>` does not. Over a long run the summary can say `running` while
   the fragment inside says `success`. Same row, different read times. AC#3
   says "sourced from the same row" — satisfied — but the implementer should
   decide whether the cue is explicitly labelled as at-load, or is itself
   made an `hx-swap-oob` target from the poll. **The second option re-enters
   the m3 trap only if it targets the `<details>`; targeting a `<span>`
   inside the `<summary>` is safe.**
2. `notebook_detail.html:84` and the new cue would then be **two renderings
   of one datum**. That is precisely the defect class m7's rectify fixed
   (`:77-83` — *"The two rendering paths for one value disagreed on its
   voice"*). If the identity section keeps its "Last indexed (ingest
   `status`)" line AND the summary gains a cue, they must use the same voice
   (`<code>`, mono) or a critic will file it.

---

## 5. Tests that pin the detail page's structure or order

### 5.1 `tests/test_ui_m8_rule_ladder.py` — WILL BREAK, by design

`class TestSectioningElementDecision` (`:362-470`). Its `_blocks()` helper
(`:393-400`) strips Jinja comments, then matches
`^<(section|div)>` **anchored at column 0, multiline**.

Four members, and **three of the four break**:

| test | line | what it pins | effect of m12 |
|---|---|---|---|
| `test_block_element_split_is_as_decided` | 403 | `EXPECTED = {"notebook_detail.html": (2, 7)}` — 2 sections of 7 top-level blocks | **BREAKS.** Wrapping five divs in `<details>` either indents them out of the `^<div>` match (→ `(2, 2)`) or leaves them matched but relocated. |
| `test_each_block_keeps_the_element_it_was_decided_to_have` | 415 | `DECIDED["notebook_detail.html"] = ["section","div","div","div","div","div","section"]` — the **ordered** per-site record | **BREAKS.** This is the guard the Phase-0 finding names. Its own failure message says: *"swapping two blocks is a re-decision, not a refactor."* |
| `test_every_block_still_opens_with_its_heading` | 433 | regex `^<(?:section\|div)>\s*\n\s*(<[^>\s]+)` must capture `<h2` for all 7 | **BREAKS** on count (`want = 7`), and a `<details>` opens with `<summary>`, not `<h2>`. |
| `test_no_block_was_promoted_to_a_landmark` | 456 | no `aria-label` on any `<section>` | **SAFE** — a `<details>` is not a `<section>`. Do not add `aria-label` to the disclosure's ancestors. |

**Required update, and how.** The docstring at `:383-385` is explicit:

> *"Read from the RECORD, not from the templates — deriving it from the
> markup would make this guard circular, asserting only that the file equals
> itself."*

So the implementer **must not** re-sort `DECIDED` to match whatever the new
template emits. The correct move is a **recorded re-decision**: update
`EXPECTED` and `DECIDED` from m12's own implement/synthesis.md decision
table, with a `#: ui-uplift-m12 (UPL-1):` comment above them explaining the
new order and why the five blocks left `main`'s child list — mirroring how
m8's rectify annotated its own `M8` change at `:373-385`. The heading test
needs a `<details>`-aware branch (its property — *every top-level group
opens with its `<h2>`* — should survive as "every group **inside** the
disclosure still opens with its `<h2>`").

Expected shape after m12 (assuming a `<details>` at column 0 wrapping five
indented divs):
`EXPECTED["notebook_detail.html"] = (2, 2)` and
`DECIDED["notebook_detail.html"] = ["section", "section"]`, plus a new
assertion covering the five now-nested divs.

### 5.2 `tests/test_ui_class_css_coverage.py` (BAN-R2) — **almost certainly NOT triggered**

The Phase-0 note says any new emitted class needs a rule immediately. True,
but **the scope is narrower than stated**. `_KNOWN_UNSTYLED` is indeed `{}`
(`:119`) and guarded non-vacuously by
`TestEmptyDeferralListIsGuarded::test_the_deferral_list_is_empty` (`:661`).
However the module docstring at `:49-52` draws an explicit line:

> *"Templates are out of scope (AC1 and the epic's own `links.code` both name
> only `server/routes/`): Jinja2-only classes like `notebook_detail.html`'s
> `rename-form` are a deliberate scope line."*

The scan globs `server/routes/*.py` and extracts classes from **Python
string literals** (`TestExtractionFindsKnownSites`, `:393`). **A new
`class="manage-disclosure"` written in `notebook_detail.html` is invisible to
this test.** BAN-R2 binds only if m12 touches a fragment builder in
`server/routes/notebooks.py` — which §3/§4 say it should not need to.

Two live sub-guards to respect if a builder *is* touched:
`test_known_unstyled_entries_are_still_actually_emitted` (`:539`) and
`test_new_static_class_with_no_css_rule_is_caught` (`:605`).

### 5.3 `tests/test_ui_contrast.py` — low risk, but read the token loop

- `PAIRS` is **hand-maintained** and asserted only `>= 60` (`:950`), not
  exhaustive. A disclosure reusing `--fg` on `--bg` needs **no new pair**.
- **The trap is `test_all_colour_tokens_are_oklch_on_one_of_two_hues`
  (`:651`)** — it iterates every `:root` token and skips only
  `NON_COLOUR_TOKEN_NAMES = {"--mono"}` plus
  `NON_COLOUR_TOKEN_PREFIXES = ("--dur-", "--text-", "--tracking-",
  "--rule-")`. **Any new non-colour token m12 adds (e.g. a
  `--disclosure-*` size) hard-fails with `is not an oklch() value`** unless
  its prefix joins that tuple. This is the m7 lesson repeating; it is the
  single most likely surprise if m12 adds a token.
- `test_the_non_colour_allow_list_has_no_dead_entries` (`:635`) then requires
  any prefix added to actually match a declared token.
- If m12 introduces a new *colour* pair (a tinted summary background), it
  needs a `PAIRS` row with a measured ratio, or an `EXEMPT` row carrying an
  inline `[EXEMPT: …]` justification (`:426-432`).

### 5.4 The app.css / tokens.css line caps — see §7

`tests/test_ui_m3_dark_and_htmx_feedback.py:636`,
`tests/test_ui_m4_in_place_add_paper.py:728`,
`tests/test_ui_m5_create_remove_in_place.py:855` (all `<= 600`, lockstep);
`tests/test_ui_m7_type_scale.py:470` (`<= 290`).

### 5.5 Everything else that reads the template — all SAFE

Verified position-independent (each locates an element by id/attribute
substring; none asserts inter-block document order):

| file | what it pins | verdict |
|---|---|---|
| `tests/test_ui_a11y_baselines.py:223-241` | `aria-live` present near `#display-name-block`, `#ingest-status`, `#papers-tbody` — via `.index()` **to locate, not to order** | SAFE — but all three ids must keep their `aria-live`/`aria-atomic` attributes verbatim through the move |
| `tests/test_ui_m4_in_place_add_paper.py:364,415` | add-paper form has `hx-target="#papers-tbody"` + `hx-swap="beforeend"`; `<tbody id="papers-tbody">` exists | SAFE — **but this is why §3's fix must not change `hx-target`/`hx-swap` values.** A `show:` modifier appended to `hx-swap="beforeend"` would break `:367`'s exact-string assert `'hx-swap="beforeend"' in form_block`… **it would still pass** (substring match), but verify before relying on it |
| `tests/test_ui_m5_create_remove_in_place.py:499` | Remove button `hx-target="closest tr"` | SAFE — index page + self-relative |
| `tests/test_ui_m2_polish.py:170` | `<table class="papers">` wrapped in `.table-wrap` | SAFE — the wrapper moves intact with block 7 |
| `tests/test_ui_htmx_json_contract.py:182-218` | each `hx-patch`/`hx-post` on the detail page pairs with `hx-ext="json-enc"` | SAFE — attributes travel with the forms. **Preserve `hx-ext="json-enc"` on all five moved forms** (note the Upload form at `:246` deliberately has `hx-encoding="multipart/form-data"` instead — do not "normalise" it) |
| `tests/test_ui_m7_type_scale.py:744-758` | `<details class="discover-abstract">` in `notebooks.py`; clamp on `> summary`; `[open] > summary` releases it | SAFE from the reorder — **but see §6, the CSS leak** |
| `tests/test_notebook_detail_status.py` | server-side parse-status / `latest_run` rendering | SAFE — reads rendered HTML, not order |
| `tests/test_ui_html_pages.py:164` | detail page returns 200 | SAFE |
| `tests/test_m3_endpoints.py:529-531` | `"<details" not in` the **status-badge** remediation block | SAFE — different route (`ui.py`), different fragment. Do **not** let a m12 `<details>` migrate into `_build_remediation_block` |

---

## 6. The `<details>` collision surface

### 6.1 Do they nest or collide?

**No nesting.** The existing `<details class="discover-abstract">`
(`server/routes/notebooks.py:747`) is emitted **only** inside the
`#discover-results` fragment, i.e. inside block 3. After m12 that block sits
inside the Manage disclosure, so the page will have
`details.manage > … > div#discover-results > li > details.discover-abstract`
— **a nested `<details>`, which is valid HTML and behaves independently**
(the outer's `open` gates rendering; the inner keeps its own state). No
collision, but the nesting is real and worth one line in the implement notes.

One consequence: `.discover-abstract` elements inside a **closed** outer
disclosure are not rendered, so their `open` state is preserved but
inaccessible. Harmless — the discover results are ephemeral anyway (`:177`).

### 6.2 The CSS leak — this is the actionable part

`app.css:250-258` styles the existing disclosure **class-scoped**:

```css
.discover-abstract              { margin: 0.25rem 0 0.5rem 0; font-size: var(--text-meta); color: var(--fg-muted); }
.discover-abstract > summary    { max-height: 4.5em; overflow: hidden; cursor: pointer; list-style-position: outside; }
.discover-abstract[open] > summary { max-height: none; }
.discover-abstract > p          { margin: 0.25rem 0 0 0; }
```

Specificity: `.discover-abstract > summary` is **(0,1,1)**; a bare `summary`
is **(0,0,1)**. So for the four properties m10 declares, m10 wins. **For
every property m10 does NOT declare, a bare `summary { … }` rule from m12
wins by default** — there is no competing declaration to lose to.

Concretely, if m12 writes `summary { list-style: none }` or a
`summary::marker` rule to style its own triangle, **m10's abstract-reveal
affordance loses its disclosure triangle** — silently, and
`tests/test_ui_m7_type_scale.py:749-758` will NOT catch it (it only asserts
`max-height` behaviour). That would regress the exact defect m10's rectify
existed to fix (H2/H3/M2: *"a short abstract and a truncated one rendered
identically"*).

**Hard requirement for m12: scope every disclosure rule to a class**
(`.manage-disclosure`, `.manage-disclosure > summary`, …). **No bare
`details` or `summary` selector.** Same reasoning applies to a bare
`details { border: … }`, which would leak onto `.discover-abstract`.

### 6.3 The rule-ladder break — the largest unflagged risk

`app.css:64-65` selects `main > :where(section, div) + section|div`. The
`main >` combinator is **direct-child**, and the comment at `:63` confirms it
is deliberate (*"Specificity is (0,0,1), not the (0,0,0) the old comment
claimed twice — `main >` contributes"*).

After m12, blocks 2–6 are children of `<details>`, not of `<main>`. Therefore:

- **Every moved block loses `border-block-start`, `margin-block-start` and
  `padding-block-start`.** The five forms collapse into one undifferentiated
  run with zero separation — the "ruled sheet reads as a spreadsheet"
  failure inverted into "no rhythm at all". m8's whole rule ladder stops
  applying to five of the seven blocks it was authored for.
- **`main > … + details` matches nothing.** The disclosure itself gets no
  top rule and no top spacing, so it butts directly against the papers
  section.

Minimum new CSS (each line lands against the §7 budget):

1. `main > :where(section, div) + details { border-block-start: var(--rule-section); margin-block-start: 2rem; padding-block-start: 2rem; }` — continues the ladder to the disclosure. **`--rule-section` is the right rung**: the disclosure is a peer group of the two sections, and §7's budget is why this should be *merged into the existing `+ section` selector list* rather than written as a new rule (`… + :where(section, details)` costs **0 net lines**).
2. A ladder for the nested blocks, e.g.
   `details > div + div { border-block-start: var(--rule-row); margin-block-start: 1.25rem; padding-block-start: 1.25rem; }` — 1 line.
3. `.manage-disclosure > summary { … }` — cursor, the state cue's layout. 1–3 lines.

**Cheapest correct form: rewrite `app.css:64` as
`main > :where(section, div) + :where(section, details)` and add ONE nested-ladder line.** Net cost **+1 line**, which fits (§7).

---

## 7. The line budgets — verdict: **it fits, but only just, and only if §6.3 is done the cheap way**

Measured in this worktree:

| file | lines | cap | headroom | asserted by |
|---|---|---|---|---|
| `server/frontend/static/app.css` | **598** | **600** | **2** | `test_ui_m3_dark_and_htmx_feedback.py:636`, `test_ui_m4_in_place_add_paper.py:728`, `test_ui_m5_create_remove_in_place.py:855` — **all three must move in lockstep**; each failure message says so |
| `server/frontend/static/tokens.css` | **289** | **290** | **1** | `test_ui_m7_type_scale.py:470` (single test) |

**Both are effectively full.** The m3 test's own comment at `:631` records
that m8's rectify landed the file at 593/600 and that *"the cap was held, not
raised"* (`test_ui_m4_in_place_add_paper.py:727`). The raise history is
400 → 480 (m6) → 520 (m7 rectify) → 600 (m10). **m8 deliberately declined a
fourth raise.**

### Plain answer

**Yes, m12 fits in 2 lines — if and only if the disclosure rules are folded
into existing selectors rather than added as new ones.** The budget-safe plan:

| change | net lines |
|---|---|
| `app.css:64` → `main > :where(section, div) + :where(section, details)` | **0** (edit in place) |
| nested ladder: `details > div + div { … }` | **+1** |
| `.manage-disclosure > summary { cursor: pointer; }` + cue layout | **+1** (single-line rule, matching the file's prevailing one-line style — see `:250`, `:278-280`) |
| **total** | **+2 → 600/600** |

That lands **exactly on the cap with zero headroom**, which is a bad place to
leave the next milestone (m13 is already queued and also touches this page).

### Recommendation

**Raise the app.css cap to 640 as step one of the milestone, not as
end-of-milestone cleanup.** Rationale to record: m8 held the cap because m8
was *deleting* a primitive; m12 *adds* a structural element, which is the
case the cap exists to make deliberate rather than to forbid. The raise costs
three synchronised edits (m3:636, m4:728, m5:855) plus their comment blocks,
and every one of those files documents the lockstep requirement in its own
failure message — so a partial raise fails loudly, not silently.

**`tokens.css` should need no change at all.** m12 needs no new token: the
disclosure reuses `--rule-section`/`--rule-row` and existing colours. **If a
token is proposed, note that `tokens.css` has 1 line of headroom AND
`test_tokens_css_declares_only_root_blocks` forbids putting rules there — the
m7 split escape hatch is already spent.** Prefer literals or existing tokens.

---

## 8. Acceptance criteria the implementer must meet

Traced 1:1 to `plans/ui-uplift/roadmap.yaml:454-459`.

1. **Papers table visible without scrolling past any input form.** Post-reorder
   projection puts it at **y≈430–540** on a 1440×900 viewport (§2), well
   inside the fold. **Blocked on a decision the AC does not make: the rename
   form at `notebook_detail.html:37` is an input form inside the LEADING
   identity section.** Either move it into the disclosure (satisfies the AC
   literally, but then six forms move and AC#4's "five" undercounts), or
   record an explicit reading that the AC means the five machinery forms and
   that rename is part of identity. **Do not leave this implicit.**
2. **Non-terminal or failed → disclosure OPEN.** Predicate is *open unless
   `success`*, covering `none` / `running` / `failed` (§4). Source both the
   predicate and the cue from the single `latest_run` already in the template
   context (`server/routes/ui.py:461`). Verified at the htmx source that a
   poll inside a closed `<details>` does **not** stop (§4).
3. **Summary carries a state cue from the same row the fragment reads.**
   `{{ latest_run.status }}` — literally the same
   `store.get_latest_ingest_run(slug)` row the endpoint reads at
   `notebooks.py:2283`. Handle `latest_run is none` → `"none"` to match the
   fragment's synthesised token. Keep the cue's typographic voice consistent
   with `notebook_detail.html:84`, which renders the same datum (§4).
4. **Every moved form's `hx-target` resolves; no swap lands out of view.**
   All six resolve unconditionally (`querySelector`). Three are self-contained
   (topic, discover, ingest). **The two `#papers-tbody` forms (add-paper :218,
   upload :246) are the real subject** — their target moves from below the
   form to above it. Decide and record: accept, or `show:`/`scroll:` on
   `hx-swap`. Also preserve `hx-ext="json-enc"` on the four JSON forms and
   `hx-encoding="multipart/form-data"` on Upload (§3).
5. **NO expand animation claimed or budgeted.** Nothing in `app.css` may
   reference `interpolate-size`, `::details-content`, or a `height`/`max-height`
   transition on the new disclosure. Note `app.css:252` already has
   `max-height: 4.5em` on `.discover-abstract > summary` — that is m10's
   **clamp**, not an animation, and must not be mistaken for one or
   "harmonised" into a transition. A negative-assertion test is the cheap way
   to pin this.

Two ACs the milestone inherits but does not list:

6. **The m8 sectioning-element record must be re-decided, not re-sorted**
   (`tests/test_ui_m8_rule_ladder.py:386-391`), with reasons in a comment
   (§5.1).
7. **The rule ladder must be extended to the new nesting depth**, or five of
   seven blocks lose all separation (§6.3).

---

## 9. Risks and open questions

1. **The rename form makes AC#1 and AC#4 mutually inconsistent as written.**
   AC#1 says "past **any** input form"; AC#4 says "the **five** moved forms".
   Six forms exist. The orchestrator must pick a reading before Phase 2, or
   the critique phase will file it as a HIGH either way. *Recommendation:
   move rename into the disclosure and amend AC#4 to six — "identity" is the
   slug, the display name and the metadata, not the control that edits them.*

2. **The rule-ladder direct-child break (§6.3) is invisible to the test
   suite.** No test asserts that blocks 2–6 have separation; `test_the_ladder_is_horizontal_only`
   (`:177`) checks the ladder's *direction*, not its *coverage*. This will
   ship as a silent visual regression unless the implementer adds the nested
   rule AND a guard for it.

3. **The app.css budget lands on exactly 600/600 under the cheapest plan.**
   Any critique finding that costs a CSS line during rectify has nowhere to
   go, and m13 is already queued against the same file. Raise the cap first
   (§7). This is the m7 lesson repeating for the third time: *the line
   budget, not the CSS, is the binding constraint.*

4. **Roadmap coherence gap, worth surfacing to the user, not fixing here.**
   m12's summary says *"the index half pairs with m11"*, but
   `plans/ui-uplift/roadmap.yaml:415-436` shows **m11 is "Author the four
   empty states (UPL-21)"** — not an index reorder. m11's own summary calls
   itself *"HARD-PAIRED with the index reorder"*. **Neither milestone IS an
   index reorder; no such item exists in the plan.** Concrete consequence:
   m12 makes `notebook_detail.html:322` — `<p class="empty">No papers yet.
   Add one above.</p>` — **factually wrong**, since the add form moves below.
   m11 fixes exactly that copy but `depends_on: [ui-uplift-m12]`, and its
   `target_end` (2026-09-15) is **11 days BEFORE** m12's (2026-09-26), which
   is impossible for a dependent. Either m12 fixes that one string inline
   (≈1 line, no CSS cost) or the page ships with wrong instructions.

5. **The `<summary>` cue is a page-load snapshot while the fragment updates
   every 2s** (§4). Same row, different read times, so AC#3 is met — but a
   critic may read a `running` summary over a `success` body as drift.
   Decide up front: label it at-load, or make the cue an `hx-swap-oob` target
   (safe only if it targets a `<span>` inside the `<summary>`, never the
   `<details>`).

---

## 10. Files the implementer will touch

| path | role | expected change |
|---|---|---|
| `server/frontend/templates/notebook_detail.html` | the milestone | reorder blocks; wrap 2–6 in `<details class="manage-disclosure">`; `open` predicate + `<summary>` cue; fix `:322` copy |
| `server/frontend/static/app.css` | rule ladder + disclosure styling | edit `:64` selector; +1 nested-ladder line; +1 scoped summary rule. **Class-scoped only — no bare `details`/`summary`** |
| `tests/test_ui_m8_rule_ladder.py` | the order guard | re-decide `EXPECTED` + `DECIDED` (`:371`, `:386-391`) with recorded reasons; `<details>`-aware heading test (`:433`) |
| `tests/test_ui_m3_dark_and_htmx_feedback.py:636` | app.css cap | lockstep raise (if §7 recommendation taken) |
| `tests/test_ui_m4_in_place_add_paper.py:728` | app.css cap | lockstep raise |
| `tests/test_ui_m5_create_remove_in_place.py:855` | app.css cap | lockstep raise |
| *(new)* `tests/test_ui_m12_*.py` | m12's own guards | AC#2 open-predicate over all four ingest states; AC#3 same-row sourcing; AC#4 target resolution; AC#5 negative animation assertion; §6.2 no-bare-`summary` regression |

**Read-only, but load-bearing — do not edit:**
`server/routes/notebooks.py:2357-2448` (fragment builder),
`server/routes/notebooks.py:2238-2311` (poll endpoint),
`server/routes/ui.py:461-472` (template context),
`server/notebooks_store.py:572-574` (status vocabulary),
`server/routes/ui.py:280-286` (the prior `<details>` rejection).

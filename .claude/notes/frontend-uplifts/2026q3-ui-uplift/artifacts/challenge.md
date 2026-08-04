# Challenge — 2026q3-ui-uplift

**Challenger:** `frontend-uplift-challenger` (Phase 3) · **Catalog under challenge:** `artifacts/synthesis.md` (26 candidates, UPL-1…UPL-26)
**Checklist:** 11-axis FRONTEND-CHALLENGER, arXMCP-calibrated
**Canon read directly:** `.claude/references/frontend-design-language.md` (§5 BAN-1..15, §10 rubric, §3 surface classes, §11 four questions, §14 evidence tiers/DQS) · `.claude/references/frontend-uplift-motion-vocabulary.md` (§0 jobs test, §8 AP-1..7, §9 token discipline) · `.claude/references/frontend-uplift/arxmcp-design-system.md` (§9 house thesis + §9 architectural locks) · `CLAUDE.md §4.7` · `.claude/notes/06-mcp-server-design.md`
**Independent verification performed:** WCAG 2.1 relative-luminance recomputation of 38 colour pairs from `server/frontend/static/app.css`; AST/regex re-count of `aria-live` and `hx-on::htmx:response-error` occurrences in the three templates; source read of `server/routes/notebooks.py`, `server/notebooks_store.py`, `server/middleware.py`, `server/frontend/static/VENDORED.md`.

---

## 1. Executive summary

**0 BLOCKERs · 9 MAJORs · 10 MINORs · 7 NONE.** No candidate proposes an npm-installable library, a
bundler, a CDN, an SPA framework, or a JS animation engine — the catalog is genuinely §4.7-clean, and
the library scout's "zero new libraries, the 2022–2026 CSS platform is the answer" resolution is the
correct call. That is a real achievement and it is why the BLOCKER count is zero rather than padded.

**Frame verdict (Axis 11): the synthesis is NOT frameless — it is a framed catalog and the frame is
load-bearing, so there is no run-level BLOCKER.** §0 opens with a swap-tested thesis, six named
invariants, a chosen direction (D-1 · The Ledger Sheet) argued against two rejected alternates, a
present/absent BAN partition, three run-scoped anti-references (BAN-R1/R2/R3), and a per-route S-2
surface map with motion budgets. The frame demonstrably *decides* things downstream — it kills the
visual scout's `box-shadow` hover-lift, pre-rejects `MOT-18` and `MOT-3`, and pre-empts BAN-13 inside
UPL-5. Two frame-level qualifications, both MAJOR-grade but neither fatal: **(a)** the §10 rubric is
scored only on the CURRENT state (6/13); canon §2 deliverable 6 and §14 both require the **PROPOSED
end state** score, which is the exact number Axis 11 consumes — it is absent from a 63 KB document
(my own projection is in §6.1); **(b)** D-1 is presented as a chosen direction but is materially the
overlay's own *pre-declared house default* ("D-A Precision Instrument across all four surfaces, with a
D-B posture-lede permissible on the detail page's top block", overlay §9 surface map), and four of
D-1's five defining traits — hairline elevation, mono data voice, tracked micro-caps, posture lede —
are named verbatim in BAN-15's list of "this canon's own emergent house look." That is defensible for
this repo, but it should be *stated* rather than sold as novelty.

**Top two objections across the catalog.** **First — the contrast gate that governs the whole colour
program is scoped to the wrong table.** The overlay §4 table UPL-4 promises to re-run covers only
token-on-`--bg` and token-on-`--card-bg` pairs. I recomputed every *rendered* pair: the true tightest
live token pair is dark `--danger #f85149` on `--error-bg #2a1a18` (the `pre.error` rendering,
`app.css:137-141`) at **4.97:1 — 0.47 of headroom, not 0.66**, and that pair appears in neither the
overlay table nor the synthesis. Worse, two *already-shipped* pairs are **already below AA today**:
`.card .note` / `.card .empty` `#777` on `--card-bg #fff` = **4.478:1** (`app.css:63-64`) and
`.status-badge--ok` `#1a7f37` on `#e6f4ea` = **4.472:1** (`app.css:165`). UPL-4 explicitly folds those
literals into the token system, so its stated gate ("a pair dropping below 4.5:1 is a Phase-3
BLOCKER") would fire on a baseline that was never clean. **Second — four candidates are billed at a
cost their mechanism cannot deliver**: UPL-17's "safest kind of dependency, it only deletes code"
actually requires changing the 4xx/5xx response contract on seven `/ui/api` endpoints; UPL-13's
"pure server-side, zero new JS" delta check needs per-client state the stateless fragment builder
does not have, and its `<output>` migration puts flow content inside a phrasing-content element;
UPL-1's `[MOT-15 accordion-expand]` on native `<details>` is not achievable in Baseline CSS at all;
UPL-12's "0 bytes, pure CSS" skeleton is a template change.

**Honest calibration note.** The NONE rate is **7/26 = 27%**, just under the pipeline's usual 30–60%
band. I did not pad to reach it and I did not manufacture findings to depress it: this catalog is
unusually front-loaded with four M-sized foundational candidates that each carry a real hard gate, and
eleven single-brief candidates that were correctly flagged for scrutiny and did not all survive it.
Three candidates I initially drafted as findings (UPL-3, UPL-6, UPL-21) were downgraded to NONE after
re-reading them, because the objections were against the *synthesis's* framing or DAG, not against the
candidates — those moved to §6.

---

## 2. BLOCKER findings

**None.** Stated explicitly rather than by omission, because the run's originating brief asked for
"new libraries which could give an interactive feel" and the obvious failure mode was a catalog full of
npm BLOCKERs. It is not. Every candidate lands in one of three legal lanes: pure CSS (0 bytes),
inline vanilla JS under `script-src 'self' 'unsafe-inline'` (`server/middleware.py:170-177`), or a
vendored same-origin single file in the `htmx.min.js` / `json-enc.js` lane. §6 rejected list is
correct and complete on the framework question.

---

## 3. MAJOR findings

### UPL-1 — Reorder the detail page: corpus before machinery

**Severity: MAJOR**

**Objections**

- **Axis 9 (motion-vocabulary) — `[MOT-15 accordion-expand]` as specified is not implementable.** The
  candidate says "native `<details>`, reduced-motion gated, zero JS", which implies a native expand
  animation. There is none. Animating `<details>` open/close requires either `interpolate-size:
  allow-keywords` + `calc-size()` or `::details-content` + `transition-behavior: allow-discrete` —
  Chromium-only, not Baseline. The synthesis's own §6 rejected list **parks `interpolate-size` as "too
  new to cite a stable baseline"** — i.e. it parked the only mechanism its own MOT-15 needs, and did
  not notice. The honest v0 is "no expand animation; `<details>` snaps." That is fine on S-2 and costs
  nothing; the claim needs correcting so Phase 4 doesn't budget for motion that can't ship.
- **Axis 10 (sequencing) — the stated implementation risk is aimed at the wrong target.** The open
  question worries that "a `beforeend` swap into a collapsed `<details>` needs the region force-opened."
  The two `beforeend` swaps in the product both target `#papers-tbody`
  (`notebook_detail.html:206-207`, `:232-233`), and `#papers-tbody` lives inside the papers table
  (`:300-361`) — the region UPL-1 moves **above** the `<details>`. It is never collapsed. The three
  targets that genuinely end up inside the disclosure are `#topic-block` (`:122`),
  `#discover-results` (`:168`) and `#ingest-status` (`:265`), and for those the failure mode is not
  swap-target resolution (`querySelector` resolves hidden nodes fine) but **invisible success**: the
  `#ingest-status` fragment carries `hx-trigger="every 2s"` (`server/routes/notebooks.py:2352, 2361`)
  and will poll for the full duration of an ingest run inside a closed `<details>`, showing the
  operator nothing.
- **Axis 3 (a11y) + Axis 10 — the `index.html` half ships a copy regression.** UPL-1 applies "the same
  treatment" to the landing page: notebooks list leads, create form collapses beneath. The empty-state
  row at `index.html:86` reads **"No notebooks yet. Create one above."** After the reorder the form is
  neither above nor visible. The same applies to `notebook_detail.html:296` / `:303` ("Add one
  above."). First-run on a fresh install therefore lands on a page whose only instruction is wrong and
  whose only action is behind an unlabelled disclosure. UPL-21 fixes the copy, but the synthesis
  records **no dependency edge** between UPL-1 and UPL-21 in either direction.
- **Axis 11 (distinctiveness) — clean, and the strongest Q4 answer in the catalog.** Q1: BAN-5,
  BAN-R1. Q2: REF-1 restraint, translated as source-order-follows-operator-priority rather than
  shipping-history. Q3: S-2, the reorder *reduces* everything. Q4: a default assembly puts forms
  first because the template generator emits them in field order — reordering against that is
  recognisably authored. No objection.

**Suggested scope adjustment**

- **v0:** `notebook_detail.html` only. No expand animation (state this explicitly). Render the
  `<details>` **open** whenever the notebook has a non-terminal or failed ingest state, so the 2s poll
  is never invisible; closed otherwise. Add a state cue to the `<summary>` (e.g. "Manage this notebook
  — ingest running") sourced from the same row `_ingest_status_fragment` already reads.
- **v1:** `index.html`, **hard-paired with UPL-21** so the empty-state copy and the disclosure land in
  one change. Do not ship the index reorder alone.
- Record the DAG edges the synthesis omits: UPL-1 → UPL-13 (already noted by UPL-13), UPL-1 ↔ UPL-21
  (missing), UPL-1 → UPL-23 (missing — see that finding).

---

### UPL-4 — De-Primer the material: one authored OKLCH family

**Severity: MAJOR**

**Objections**

- **Axis 3 (a11y) — the hard gate names the wrong tightest pair, and understates the risk by 30%.**
  I recomputed the full pair set from `app.css` using WCAG 2.1 relative luminance. The claimed
  tightest pair, dark `--danger #f85149` on `--card-bg #161b22`, is **5.160:1** — the synthesis's
  arithmetic is correct. But it is not the tightest *rendered* pair. `pre.error` sets
  `background: var(--error-bg); color: var(--danger)` (`app.css:137-141`), and in dark mode that is
  `#f85149` on `#2a1a18` = **4.974:1 — 0.47 of headroom over 4.5:1**. Both sides are tokens; the pair
  simply does not appear in the overlay §4 table (which only crosses tokens against `--bg` and
  `--card-bg`) and therefore does not appear in the gate UPL-4 promises to re-run. The gate must be
  re-scoped from "overlay §4's table" to "every rendered foreground/background pair in the stylesheet."
- **Axis 3 (a11y) — the baseline the gate compares against is not clean.** Two pairs that render today
  are **already below SC 1.4.3 (4.5:1)**: `.card .note` and `.card .empty` at `#777` on `--card-bg
  #fff` = **4.478:1** (`app.css:63-64`; 12.8px italic, not large text) and `.status-badge--ok` at
  `#1a7f37` on `#e6f4ea` = **4.472:1** (`app.css:165`; 12px/600, not large text). The overlay §4 text
  asserts "Every pair clears AA in both themes" — true of the eight token pairs it lists, false of the
  stylesheet. UPL-4 explicitly folds "the ~12 hardcoded greys and 8 status-pill literals" into the
  token system, so it *inherits* two failing pairs and its gate would fire on them. Phase 4 needs to
  know these are pre-existing defects to fix, not regressions the candidate introduced.
- **Axis 1 / Axis 3 — `light-dark()` is cited without a baseline gate and its fallback is hostile.**
  The synthesis lists CAND-9 `light-dark()` as "0 bytes, Widely Available 2026-11-13" — that date is
  **after this run (2026-08-03)**, so it is Newly Available, not Widely. More seriously, the proposed
  use is inside custom properties (`--accent: light-dark(a, b)`). Unregistered custom properties accept
  any token stream at parse time, so an unsupporting engine stores the value and fails at
  *substitution* — invalid-at-computed-value-time. `background: var(--accent)` on a button then
  resolves to the initial value (`transparent`), and `button { color: #fff }` (`app.css:92`) leaves
  white text on the page background: invisible primary buttons, not a graceful degradation. This needs
  `@supports (color: light-dark(#000, #fff))` or deferral to v1. No gate is stated.
- **Axis 7 (token discipline) — the accent is load-bearing in five roles and the "4-step ladder" frame
  doesn't capture the constraint.** `--accent` is simultaneously button background (needs ≥4.5:1
  against its own text), focus-ring colour (needs ≥3:1 against **both** `--bg` and `--card-bg` for SC
  1.4.11, `app.css:209`), link colour, `.skip-link` background (`:193`), and the `badge-flash` tint
  (`:349`). A single OKLCH re-derivation must satisfy a three-way constraint simultaneously; the dark
  block already contains a hand-patched compensation for exactly this (`button, .button { color:
  #0d1117 }` at `:260`, with its own comment recording that white-on-`#58a6ff` was ~3.1:1). Any
  re-derivation must reproduce that reasoning, not inherit the patch.
- **Axis 11 — clean on the thesis.** Q1: BAN-15 and BAN-1, both correctly identified, with the
  strongest single piece of evidence in the run (`app.css:234-241`'s own comment says
  "GitHub-Primer-anchored values" and the hexes are GitHub's). Q4: an authored OKLCH family derived
  from one hue decision is definitionally not a default assembly. No objection.

**Suggested scope adjustment**

- **v0 (one milestone):** re-derive the **8 tokens only**, in OKLCH from one hue, both modes authored.
  Ship with a **full rendered-pair contrast table** as an artifact — not the overlay §4 subset — and
  include `--danger`/`--error-bg`, the `--accent` focus-ring-vs-both-grounds pair, and the button
  text pair. `light-dark()` **out of v0**.
- **v1:** fold in the ~12 grey literals and 8 pill literals, and fix the two pre-existing AA failures
  (`#777` → a token at ≥4.5:1; `.status-badge--ok` text darkened) as *named defects*, not silently.
- **v2 (after 2026-11-13):** `light-dark()` collapse of the duplicated block, behind `@supports`.
- Answer the synthesis's own open question ("one milestone or two?") as **two** — the above is v0/v1.

---

### UPL-13 — Consolidate the 12 `aria-live` regions and stop the 2s poll re-announcing

**Severity: MAJOR**

**Objections**

- **Credit first, because the number is right.** I re-derived the count with Jinja- and HTML-comment
  stripping: `notebook_detail.html` carries **11** real `aria-live` attributes, `index.html` **2**,
  `base.html` **1**. The synthesis's "11 + 1 inherited = 12 on one rendered page" is exactly correct,
  and it is *better* than the overlay's own figure ("24 `aria-live="polite"` regions across the three
  templates", overlay §7), which counts the documentation comments. Phase 4 should trust the synthesis
  here and correct the overlay.
- **Axis 3 (a11y) — the `<output>` migration puts flow content inside a phrasing-content element.**
  `<output>`'s content model is phrasing content. The candidate scopes `<output>` to
  `#display-name-block` / `#topic-block` / **`#ingest-status`** — and `#ingest-status`'s failed branch
  emits `<pre>{stderr}</pre>` inside the div (`server/routes/notebooks.py:2379-2389`). `<pre>` is flow
  content. `<output><pre>…</pre></output>` is invalid HTML and AT behaviour on an invalid content model
  is undefined, which is the opposite of the candidate's goal. `#ingest-status` must be excluded from
  the `<output>` scope, or the `<pre>` must move outside it.
- **Axis 8 (effort honesty) — "pure server-side logic, zero new JS" is not achievable as described,
  and the claim is load-bearing for the S sizing.** A delta check means "emit announcement-worthy
  content only when the status changed **since this client last saw it**." `_ingest_status_fragment`
  (`server/routes/notebooks.py:2309-2318`) is a pure function of the current DB row; it has no memory
  of what the polling client already rendered. Implementing a true delta needs either per-session
  server state (which §4.8 rule 1 makes an awkward conversation) or a client-side comparison (which is
  new JS). The **correct and genuinely zero-cost fix is different**: stop swapping the live region.
  Move `aria-live` off the polled fragment and onto a **stable, never-swapped wrapper** around
  `#ingest-status`. A live region only announces *changed text*, so an identical 2s re-render of a
  stable region is silent by spec — no delta logic, no state, no JS. That also retires the drift
  hazard `notebook_detail.html:16-19`'s own comment warns about (every replacement fragment must
  re-carry the attribute), which is the same argument the candidate makes for `<output>`.
- **Axis 10 (sequencing) — the UPL-1 coupling is correctly named** and is the only bidirectional edge
  the synthesis records. No objection there.
- **Axis 11 — mechanical a11y work; Q4 is not applicable** and canon §11 explicitly permits that
  ("acceptable only when the run is explicitly scoped to mechanical fixes (a11y, tokens, states)").
  No objection.

**Suggested scope adjustment**

- **v0:** (a) remove `aria-live` from the six `<pre class="error">` that are empty at first paint —
  an empty polite region announces nothing but costs AT bookkeeping, and `pre.error:empty { display:
  none }` (`app.css:148`) already hides them; (b) move the ingest live region to a stable wrapper as
  above. This is the whole announced-every-2-seconds fix and it is genuinely zero-JS.
- **v1:** `<output>` migration scoped to `#display-name-block` and `#topic-block` **only**. Exclude
  `#ingest-status` (content model), the papers `<tbody>` (a list) and `pre.error` (an alert region) —
  the last two the synthesis already excludes correctly.
- Drop the "server-side delta check" framing entirely; it is the wrong mechanism for the job.

---

### UPL-15 — Row hover state + focus-revealed trailing actions

**Severity: MAJOR** (on the composite candidate; the hover-tint half alone would be NONE)

**Objections**

- **Axis 3 (a11y) — `:focus-within` is necessary but nowhere near sufficient, and the mechanism that
  decides it is unnamed.** The synthesis makes hover-only-without-`:focus-within` the BLOCKER
  condition and stops there. The actual determinant is *how the hidden state is expressed*. If the
  Remove button is hidden with `display: none` or `visibility: hidden`, it is **removed from the tab
  order**, so `:focus-within` can never fire — the control becomes permanently unreachable by
  keyboard, which is strictly worse than the hover-only version the synthesis calls a BLOCKER. Only
  `opacity: 0` (or a `clip-path`/`transform` treatment) keeps the element focusable so the
  `:focus-within` guard can do its job. That constraint is the entire finding and it is not written
  down anywhere in the candidate.
- **Axis 3 (a11y) — SC 1.4.13 (Content on Hover or Focus) governs this and is uncited.** Revealing
  additional content on pointer hover triggers WCAG 2.2 SC 1.4.13's dismissable / hoverable /
  persistent requirements. Hoverable is satisfiable (the button sits inside the hovered row);
  dismissable and persistent need an explicit answer for a control that is also destructive.
- **Axis 3 (a11y) — this is a regression for a population the synthesis does not name.** Today the
  Remove button is unconditionally visible (`index.html:105-113`, `notebook_detail.html:346-353`).
  Hover-gating it is a pointer-precision regression for motor-impaired operators (an unstable hover
  makes the target flicker) and for screen-magnifier users, who may never see the action because their
  viewport does not contain the pointer's row. "Six always-visible red buttons fight calm at repeat
  use" is a real aesthetic complaint, but it is being paid for in reachability.
- **Axis 10 (sequencing) — UPL-11 already solves the stated problem, and the overlap is unnamed.**
  The rationale for hiding the buttons is accidental-destructive-click risk on "six 77×32 Remove
  buttons adjacent in a table column" (inherited from visual-scout HIGH-4). UPL-11 replaces
  `window.confirm()` with an in-language `<dialog>` on exactly those three sites — after which a
  mis-click costs one Escape keypress. If UPL-11 ships, UPL-15's action-hiding is solving a problem
  that no longer exists, at a real a11y cost. These are alternatives, not complements, and the
  synthesis lists them as unrelated.
- **Axis 9 — `[MOT-52 hover-reveal-actions]` is proposed as a new token but the vocabulary's own
  process says otherwise.** The synthesis marks it "not written into the hash-tracked shared canon —
  flagged for human promotion." `frontend-uplift-motion-vocabulary.md` "How to evolve this vocabulary"
  says MOT appends are **direct** at end of run (only §4 REF entries require human promotion, per
  design-language §13). Harmless, but the process citation is wrong and Phase 4 shouldn't stall on a
  promotion gate that doesn't exist.
- **Axis 11 — the hover tint is clean** (Q1: nothing introduced; Q3: S-2 orientation; the `color-mix`
  idiom at `app.css:106` is already house). The reveal half is the part carrying findings.

**Suggested scope adjustment — split the candidate**

- **UPL-15a (ship, would rate NONE standalone):** `tr:hover` tint on both tables via `color-mix`,
  `[MOT-24]` ≤100ms, orientation job. ~4 lines. Composes with UPL-2's "row as the unit of interaction."
- **UPL-15b (defer, and probably kill):** trailing-action reveal. Preconditions: (1) `opacity`-based
  hiding only, never `display`/`visibility`; (2) explicit SC 1.4.13 answer; (3) UPL-11 has **not**
  shipped — if it has, close UPL-15b as superseded.

---

### UPL-17 — Vendor `response-targets`; delete 6 copies of hand-duplicated inline JS

**Severity: MAJOR**

**Objections**

- **Axis 8 (effort honesty) — this is not a drop-in replacement; it requires a server-side response
  contract change on seven endpoints.** The inline handler being deleted is
  `document.getElementById('…-error').textContent = (function(t){try{return JSON.parse(t).detail||t;}
  catch(e){return t;}})(event.detail.xhr.responseText)`. It **extracts FastAPI's `detail` field out of
  a JSON error body** and writes it as `textContent`. `hx-target-4xx` / `hx-target-5xx` do no
  extraction — they swap the raw response body into the target. Today that body is
  `{"detail":"slug already exists"}`, so the operator would see the JSON envelope inside
  `<pre class="error">`. Making UPL-17 behave as advertised means changing every `/ui/api` 4xx/5xx
  path to return an HTML error fragment instead of a JSON error, which is a change in
  `server/routes/notebooks.py`, not in the templates — a different, larger, and security-adjacent
  change (the current `textContent` write is *why* the synthesis can say "no new XSS surface"; an
  HTML-fragment swap is `innerHTML` semantics). "The safest kind of dependency — one that DELETES
  existing code" is the framing this objection retires.
- **Axis 4 / Axis 5 — the repo already made this exact decision, in the opposite direction, and it is
  recorded.** `server/frontend/static/VENDORED.md` documents `json-enc.js` as *"authored in-repo
  rather than vendored from `htmx-extensions` so there is no unverifiable upstream version to pin and
  no dependency on htmx internals."* UPL-17 proposes vendoring from that same upstream repo without
  acknowledging the precedent — and the synthesis's own open question independently rediscovers the
  motivating problem ("the htmx-extensions repo has no root LICENSE and npm reports `license: null`;
  provenance must cite `src/<ext>/LICENSE`"). Vendoring also incurs a SHA-256 pin in `VENDORED.md`
  **and** in `tests/test_vendored_assets_integrity.py`, which the candidate does not cost.
- **Axis 5 — the audit cost is declared but the aggregate is not.** UPL-17 is one of five candidates
  (with UPL-11, 18, 19, 23) that widen the still-open UI security audit `chris-dare-dev/arXMCP#9`.
  UPL-17 is the only one whose entire justification is *reducing* code.
- **Evidence accuracy — the duplication count is 7, not 6, and 5 of 6 line numbers are off by one.**
  Verified by grep: `index.html:27`, `notebook_detail.html:37, 125, 171, 209, 235, 268`. The
  synthesis lists `notebook_detail.html:37,124,170,208,267 + index.html:27` — it **omits the upload
  form at `:235`** entirely and is one line low on four of the five. This is minor in itself but it
  is the run's most-cited "verified live" claim, so the miss matters for calibration.

**Recommended redesign (kill the vendored-asset form; the goal is achievable at zero cost)**

The stated job is de-duplication, and it does not need an extension. Add one exported helper to the
existing project-authored `server/frontend/static/json-enc.js` lane (or a sibling
`ui-errors.js` in the same lane), e.g. `window.arxmcpShowError(id, xhr)`, and reduce the seven inline
attributes to `hx-on::htmx:response-error="arxmcpShowError('create-error', event.detail.xhr)"`. That
deletes the duplicated parse chain, adds **zero** vendored bytes, adds **zero** upstream-provenance
questions, keeps `textContent` semantics and therefore the "no new XSS surface" claim, requires
**no** server response-contract change, and matches the repo's own recorded decision. Close UPL-17 in
its current form.

---

### UPL-18 — Vendor idiomorph for continuity-preserving swaps

**Severity: MAJOR**

**Objections**

- **Axis 9 (motion-jobs test) — the candidate names a job class but no unserved job.** Motion-vocabulary
  §0 is explicit: *"the absence of an animation dependency is NOT itself a design gap — it is a gap
  only when named jobs go unserved."* UPL-18 asserts "continuity" and then describes a *capability*
  ("a morphed node has a before-state to transition from"), never a surface where an operator
  currently loses continuity. Its applicable targets are the four smallest fragments in the product —
  `#display-name-block`, `#topic-block`, `#ingest-status`, `#status-badge`. Two of them are
  single-line text swaps of ≤40 characters; one already has a shipped, tested settle animation
  (`badge-flash`, `app.css:344-351`). This is a capability in search of a job.
- **Axis 10 (sequencing) — it puts two shipped, tested behaviours at regression risk to gain nothing
  currently needed.** The candidate correctly flags that morph may not apply
  `.htmx-swapping` / `.htmx-settling` the way `outerHTML` does. Those two classes are precisely what
  `row-fade-out` (`app.css:363-369`) and `badge-flash` (`:345-351`) hang off — both shipped in
  `ui-attractive-polish-m5`/`m4`. Trading proven behaviour for unproven capability is the wrong
  direction on an S-2 console whose thesis invariant is "calm at repeat use."
- **Axis 4 / Axis 5 — ~3.5 KB gz is a quarter of the htmx baseline plus a `VENDORED.md` + integrity-test
  pin plus a new `arXMCP#9` surface**, for a capability with no named consumer. The weight is not
  disqualifying; the value/weight ratio is.
- **A 0-byte alternative exists and is unmentioned.** `base.html:38-45` already sets
  `htmx.config.globalViewTransitions = true`. Assigning `view-transition-name` to the swapped
  fragments gives cross-swap **element** continuity (the browser pairs old/new by name across the
  swap) at zero bytes, zero JS, zero audit surface, and it reuses the 200ms cap already declared at
  `app.css:352-355`. If a continuity job is ever named, that is the first thing to try.
- **Axis 11 — no Q4 answer.** "The DOM node persists across a swap" is an implementation property, not
  something an operator can recognise. Per canon §11 this is polish, not design — and unlike UPL-13
  the run is not scoped to mechanical fixes here.

**Recommendation: park.** Not a kill on legality — vendoring 0BSD single files is a legal, proven lane
and the license/author story is genuinely the strongest of the three extension candidates. Kill on
value. Re-open only when a specific continuity failure is observed on a specific fragment **and**
`view-transition-name` is shown insufficient for it.

---

### UPL-20 — Surface `notebook_kind` on the index; densify the notebooks list

**Severity: MAJOR**

**Objections**

- **Axis 11 (BAN-7) — the mitigation addresses a rule the canon does not state.** The candidate's guard
  is "ONE chip per row, reusing the existing four-state vocabulary, never a second chip." Canon §5
  BAN-7 is a **per-view** threshold: *"more than ~5 colored status chips visible per view."* One chip
  per row scales linearly with notebook count; at six notebooks the index shows six chips plus the
  footer operability badge = **7 visible chips**, over the line, with no per-row rule violated. The
  §10 rubric tell 7 would then score 1 on the projected state. The guard as written cannot prevent
  this because it is measuring the wrong unit.
- **Axis 11 (BAN-11) + Axis 7 — reusing `.status-badge--*` for a taxonomy is semantic-colour dilution,
  and the repo's own overlay names it.** `arxiv` vs `textbook` is a **kind**, not a **state**. The
  `.status-badge--{ok,warn,ops-warn,down}` palette is the product's live-state vocabulary. The overlay
  §9 anti-reference table says it directly: *"the parse-status + operability badges are LOAD-BEARING
  state; multiplying pills dilutes the one signal the operator relies on"* (BAN-7, BAN-11). The
  synthesis's own §0.4 lists BAN-11 in the must-not-introduce set and then proposes exactly this.
  Painting a two-value taxonomy in the four-state semantic palette is the textbook BAN-11 case.
- **Axis 11 — the second half compounds it.** "Surface `parse_status` / last-indexed inline so the list
  alone answers 'is this notebook usable'" is a second state signal per row, which is precisely the
  "never a second chip" the candidate's own guard forbids.
- **Evidence — verified and the correction is right.** `notebook_kind` appears **0** times in
  `index.html` and **1** time in `notebook_detail.html`; the current-state critic's correction to the
  overlay's stale "3×" is accurate.
- **Axis 11 — the operator need is real.** Two kinds with different available actions, invisible until
  you open the notebook, is a genuine gap. The objection is to the chosen vehicle, not the goal.

**Suggested scope adjustment**

- **v0:** render `notebook_kind` as **plain `--mono` tracked micro-caps text in its own column** —
  `ARXIV` / `TEXTBOOK` — with no background, no border, no semantic colour. This satisfies the operator
  need at **zero** BAN-7 and BAN-11 exposure, costs one `<th>`/`<td>` pair plus one CSS rule, and is
  strictly more D-1-coherent than a pill (D-1's own thesis is "rules carry every structure; the box is
  deleted" — a chip is a box).
- **v1 (gated):** any per-row *state* signal only after a per-view chip census is run against the
  BAN-7 threshold at a realistic notebook count, and only if it earns a distinct visual register from
  the operability badge.

---

### UPL-24 — Ingest/operability state history strip

**Severity: MAJOR** → recommended kill from this catalog

**Objections**

- **Premise: half-verified, and it was answerable in one grep.** The synthesis asks "does the server
  even retain run history? … Requires verification before ranking." It does, for the ingest half:
  `notebook_ingest_runs` is an append-only table (`server/notebooks_store.py:196-212`) with
  `CREATE INDEX idx_runs_slug ON notebook_ingest_runs(slug, id DESC)` and no pruning path in the
  module. So the data exists. The **operability-badge half has no history at all** — `/ui/status-badge`
  is computed live per 10s poll and nothing persists — so half the candidate's stated premise ("both
  status surfaces throw away everything but the latest poll result") is true and not fixable from the
  frontend.
- **Axis 8 (effort honesty) — this is a server candidate wearing a frontend candidate's clothes, just
  not for the reason given.** The only read path is `get_latest_ingest_run`
  (`server/notebooks_store.py:625-647`), which is `ORDER BY id DESC LIMIT 1`. There is no
  `list_ingest_runs`, no route returning >1 row, and no fragment builder for a series. UPL-24 requires
  a new store method, a new `/ui/api` route, a new fragment builder, and route tests before a single
  pixel changes. Sized M as a frontend item; it is M as a *server* item plus S of CSS.
- **Axis 11 (BAN-6 + BAN-15) — the "so what" is thin and the instrument is borrowed.** The frame binds
  BAN-6: threshold, annotation, and a stated "so what," or it does not ship. Grafana state-timelines
  and Datadog monitor-history exist for high-frequency, multi-service, multi-operator fleets where
  "recent state over time" drives an on-call decision. arXMCP is one operator, on loopback, ingesting
  a given notebook a handful of times in its life. Transplanting a fleet-monitoring instrument onto
  that cadence is the BAN-15 borrowed-shell pattern — another product's instrument reused without the
  volume that made it meaningful — and the run's own new standing rule ("looks like GitHub is now a
  measurable failure state") is the same argument pointed at a different vendor.
- **Axis 3 + Axis 9 — `[MOT-26 tooltip-fade]` on per-tick hover puts the only readable content behind
  a pointer.** A strip of coloured ticks whose meaning is available only on hover is inaccessible to
  keyboard and touch operators entirely, and triggers SC 1.4.13. If the strip needs a tooltip to be
  interpretable, it is BAN-R3 ("instrument without a reading") — the run's own anti-reference.

**Recommendation: kill from the frontend catalog.** Re-file as a server-side candidate if and when a
decision that depends on ingest run history is named. The single-tick "last run failed, N runs ago" fact
an operator might actually want is already reachable from UPL-5's posture lede at zero new surface.

---

### UPL-25 — Identity strip on the ar5iv preview surface

**Severity: MAJOR** → defer wholesale

**Objections**

- **Axis 11 / Axis 14 evidence — the candidate is UNSCORABLE this run and rests entirely on that.**
  The synthesis states it plainly: *"This surface was NOT audited this run — no paper in the deployment
  has stored ar5iv HTML, so the route correctly 404s."* Canon §14: a gate-relevant judgment resting on
  no artifact is `UNSCORABLE` and *"never counts toward any total or gate."* This is the one candidate
  in the catalog with **zero** evidence at any tier — not `✓ live`, not `✓ code` for the rendered
  surface, only `~ inferred`. Ranking it alongside 25 candidates that have measured geometry or source
  citations is a tier violation.
- **Axis 5 (CSP) — an identity affordance placed inside a document that is permitted inline CSS can be
  spoofed or hidden by that document.** `CONTENT_SECURITY_POLICY_PREVIEW`
  (`server/middleware.py:218-226`) is `default-src 'none'; style-src 'self' 'unsafe-inline'; script-src
  'none'` — deliberately tight because the route serves **untrusted third-party HTML**. Prepending a
  trusted strip into that same document means the untrusted ar5iv markup can, with legal inline CSS,
  restyle it, cover it, or hide it — on the one affordance whose entire purpose is telling the operator
  which notebook and paper they are looking at. That is a spoofing surface, not a polish item, and it
  belongs in a conversation with `chris-dare-dev/arXMCP#9` open, not in a visual catalog.
- **Axis 11 — it contradicts the run's own surface map.** §0.5 row 3 tags the preview
  "S-2 (document view) · none — **chrome recedes**; tight CSP is a constraint to honour." A sticky
  brand strip is chrome that does not recede. The frame and the candidate disagree and the synthesis
  does not resolve it (contrast with tension 2, where it explicitly resolves in the frame's favour).
- **The gap is already downgraded and may be a non-finding.** The current-state critic's L1 correction
  is recorded in the candidate itself: the Preview link opens `target="_blank" rel="noopener"`, so
  closing the tab *is* the way back — the gap is brand discontinuity only. The candidate's own open
  question then asks whether the same-origin favicon already supplies the identity cue. It probably
  does (`server/frontend/static/favicon.svg` is served same-origin and the tab title carries the
  route).

**Suggested scope adjustment: defer to a follow-up run**, gated on (a) an uploaded ar5iv fixture so the
surface can be audited at `✓ live` tier, (b) an explicit answer on the favicon/tab-title question, and
(c) if it still has value, a spoofing-resistant delivery decision (an out-of-document affordance, not
an in-document strip) made against `arXMCP#9`.

---

## 4. MINOR findings

### UPL-2 — Retire `.card`; adopt a graded hairline rule ladder

**Severity: MINOR**

**Objections**

- **Axis 3 — the arithmetic is correct; verify and keep it.** Light `--border #d8d8d8` on `--bg
  #f8f8f8` recomputes to **1.342:1** and on `--card-bg #fff` to **1.425:1** — the synthesis's 1.34 /
  1.43 are right, and the SC 1.4.11 argument (tolerable while borders are incidental, failing the
  moment rules become the sole structural device) is correct and is the best-argued dependency in the
  catalog. The `#6e7681` figure needs one qualification: it is **4.120:1 on `--bg`** but **3.766:1 on
  `--card-bg`**. Both clear the 3:1 non-text bar, and once cards are deleted only the `--bg` pairing
  survives, so this is a note rather than a defect — but the candidate should cite the pair it means.
- **Axis 7 — deleting `.card` orphans `--card-bg` and the sketch does not say what replaces it.**
  `--card-bg` is not only the card ground: it is the dark-mode input background (`app.css:264-267`),
  the reference ground for the dark `th` (`:290`), and the denominator in the overlay §4 contrast
  table. Deleting `.card` (`:53-59`) without a stated successor role leaves a token defined and
  unused in light mode while three rules still depend on it in dark mode. Decide explicitly: `--card-bg`
  becomes the **control ground** (inputs, table headers), not the panel ground.
- **Axis 3 — the table-header stripe disappears with the card and nothing replaces it.**
  `th { background: #f0f0f0 }` (`app.css:116`) is **1.140:1** against `--card-bg #fff` today —
  already at the edge of perceptibility — and against `--bg #f8f8f8` it drops to ~1.03:1, i.e. gone.
  D-1 says rules carry structure, so the header separation must migrate to a `--rule-section` weight
  under the `<thead>`; otherwise the papers table loses its only column-header cue at exactly the
  moment the table becomes the page's focal content.
- **Axis 11 — clean and the strongest anti-template move in the catalog**, with one honesty caveat
  moved to §6.2 (D-1's traits overlap BAN-15's named house look; that is a frame-level observation,
  not a defect in this candidate).

**Suggested scope adjustment:** ship **inside or immediately after UPL-4** (the synthesis is right
that it cannot precede it). Add to the sketch: (a) `--card-bg` re-scoped to controls, stated; (b) a
`--rule-section` under `<thead>` replacing the `th` background; (c) cite `#6e7681`-on-`--bg` as the
dark rule pair.

---

### UPL-5 — A posture lede for the notebook

**Severity: MINOR**

**Objections**

- **Axis 3 (a11y) — replacing `<dl class="meta">` with an authored sentence trades a machine-readable
  structure for prose, and the trade is unnamed.** `notebook_detail.html:48-76` uses `<dl>`/`<dt>`/`<dd>`,
  which screen readers expose as explicit term↔value associations; an operator can navigate the
  definition list and hear "Parse status: skipped". A composed sentence flattens that into a single
  text run. The candidate says it "replaces the current `<dl class="meta">` + badge + hint assembly"
  and does not mention what replaces the semantics.
- **Axis 14 (evidence) — the ranking rationale rests on a metric the run declares unscorable.** "Largest
  single DQS gain in the catalog (dims 1, 3, 8)" is the candidate's central argument, and §0's binding
  evidence notice says *"the positive DQS half is not [auditable] and must be re-scored against real
  PNGs before any ship gate."* Same issue in UPL-7 ("single largest DQS dim-7 gain"). The claims may
  well be right; they cannot be *used to rank* under this run's own stated tier discipline without
  saying so.
- **Axis 11 — the anti-BAN-13 argument is genuinely good** (one honest sentence of metered facts,
  visible abstention where the daemon has no fact) and is the clearest I-1 realisation in the catalog.
  The BAN-15 exposure ("posture lede" is named in BAN-15's house-look list) is a frame-level note, §6.2.
- The open question ("N papers = junction rows or LanceDB chunks?") is real, self-flagged, and
  answerable: `/ui/api` counts junction rows, which is why the `bridgeland-stability*` notebooks show
  0 against large corpora. It must be decided before the sentence is authored, since I-1 forbids
  showing a number the operator cannot trust.

**Suggested scope adjustment:** **v0** — keep `<dl class="meta">` as the machine-readable substrate and
add ONE authored sentence above it at 2–3× weight, with `parse_status`'s *meaning* rather than its
token (this alone closes BAN-R3 and most of the BAN-5 gap). **v1** — collapse the `<dl>` into the
sentence only if an equivalent semantic structure is designed for it. Label the DQS claims as
projected-not-measured.

---

### UPL-8 — Give `select` / `textarea` the input family's styling

**Severity: MINOR**

**Objections**

- **Axis 8 — "one selector-list extension" will not produce the stated result on `<select>`.** Adding
  `select` to the `input[type=…]` rule (`app.css:74-84`) sets `padding`, `border`, `border-radius` and
  `background` on a control whose UA appearance largely ignores them: WebKit on macOS honours almost
  none of it, and Blink honours it only partially. Making `<select>` visually match `<input>` requires
  `appearance: none` — after which you must supply your own dropdown indicator, and the product has
  **zero icons** (BAN-3 adjacency, the same decision UPL-21 correctly escalates).
- **Axis 3 / Axis 7 — `appearance: none` collides with a documented load-bearing declaration.**
  `color-scheme: light dark` at `app.css:10` exists specifically so *"the browser auto-darkens
  UA-styled controls (form-element internals, scrollbars, default focus rings, default caret color,
  native `<select>` dropdowns)"* — the overlay §4 flags it "load-bearing and NOT a token. Don't delete
  it while tidying." `appearance: none` throws away exactly the UA internals that declaration exists to
  theme, so the dark-mode `<select>` would need a hand-authored replacement.
- **Axis 3 — the underlying defect is real and worth fixing**: `select` 19px vs `input` 33px in the same
  form row is a genuine 14px baseline mismatch and a tap-target problem UPL-6's floor also touches.
- `field-sizing: content` is correctly `@supports`-gated with `rows="2"` as the fallback. No objection.

**Suggested scope adjustment:** **v0** — parity on the properties that work *without* `appearance:
none`: `font-family: inherit`, `font-size`, `padding`, `margin-top`, `display: block`, and a
`min-height` matching the input. That closes the 19px/33px mismatch, which is the actual finding.
**v1** — full `appearance: none` styling only bundled with the icon decision UPL-21 forces and a
dark-mode indicator design.

---

### UPL-9 — Style the Discover-results candidate list

**Severity: MINOR**

**Objections**

- **Axis 9 / Axis 10 — `[MOT-1 fade-in]` duplicates motion that already ships on this exact swap.**
  `#discover-results` is swapped with `hx-swap="outerHTML"` (`notebook_detail.html:168-169`), and
  `base.html:38-45` sets `htmx.config.globalViewTransitions = true`, so the browser already runs a
  root crossfade capped to 200ms (`app.css:352-355`) on that swap. Adding a fade-in keyframe to
  `.discover-list` on top of it either double-animates or fights the transition. The causality job the
  candidate names is **already served**, at zero bytes, by shipped infrastructure.
- **Everything else is clean.** Five rules for five server-emitted classes with zero CSS
  (`server/routes/notebooks.py:731-748` emits `discover-candidate` / `discover-title` /
  `discover-meta` / `discover-abstract` / `discover-list`; verified zero matches in `app.css`) is the
  purest BAN-R2 closure in the catalog. `MOT-3` is correctly pre-rejected against AP-3 with the right
  reasoning (candidate count can reach 10 on an S-2 surface). The `--mono` + `<time>` +
  `tabular-nums` reuse is correct (`app.css:133-135` already scopes `time`). The "why this matches"
  line is correctly held against I-1.

**Suggested scope adjustment:** ship the five CSS rules; **drop the MOT-1 fade** and record that
`globalViewTransitions` already carries the causality job on this target.

---

### UPL-10 — Make the ingest-failure `<pre>` use the house error treatment

**Severity: MINOR**

**Objections**

- **The one-line change is verified and clean.** `server/routes/notebooks.py:2379-2381` is literally
  `f"<pre>{stderr_tail}</pre>"`, and every sibling error surface uses `pre.error`
  (`app.css:137-148`). `stderr_tail` is already `html.escape`'d upstream (docstring at `:2325-2328`),
  so adding a class introduces nothing. Standalone this would be **NONE** — it is the highest
  value-per-character item in the catalog.
- **Axis 11 (BAN-3) — the bundled status icon is the run's most likely "make it prettier" regression and
  the candidate does not flag it.** The synthesis's own §0.4 names BAN-3 as *"the single most likely
  'make it prettier' move; the product has zero icons today and that is an asset,"* and tension 4
  escalates the icon question for UPL-21 — but UPL-10 proposes "a status icon" with no BAN-3 mention
  at all. The same decision cannot be a recorded escalation in one candidate and an unremarked detail
  in another.
- **Axis 9 — the `spin` keyframe reuse works but is subtler than stated.** `@keyframes spin` is
  declared *inside* `@media (prefers-reduced-motion: no-preference)` (`app.css:317-333`), so it only
  exists when that query matches. Referencing it from an unconditional rule silently no-ops under
  `reduce` — which is the desired behaviour, but by accident rather than by construction. Put the new
  rule inside the same media block so the gate is explicit.
- **Axis 9 (I-3) — a continuous spinner on a 2s-polled status line is the frame's own edge case.**
  §0.5 binds "no motion on a poll tick"; a `running` state that spins for the whole run is
  continuous motion on a region that re-renders every 2s. Defensible (the state is genuinely ongoing)
  but it should be argued, not assumed.

**Suggested scope adjustment:** **v0** — the one-line `class="error"` change alone. Ship it first; it
is XS and unconditionally correct. **v1** — `data-status` as a styling hook with `--mono` log
rendering (still icon-free). **v2** — any icon, only after the explicit icon decision UPL-21 demands.

---

### UPL-11 — Replace `window.confirm()` with an in-language `<dialog>`

**Severity: MINOR**

**Objections**

- **Credit: the cost declaration is the model the rest of the catalog should follow.** "DECLARED COST —
  this is the one candidate in the top tier that adds JS surface… If that cost is judged too high this
  run, park it — **do not shrink it to a CSS-only fake** that loses the focus-trap semantics." That is
  exactly right, and CSP-legality under `script-src 'self' 'unsafe-inline'`
  (`server/middleware.py:172`) is correctly asserted.
- **Axis 3 — `htmx:confirm` fires on EVERY htmx request, not only on elements carrying `hx-confirm`.**
  A listener that calls `event.preventDefault()` unconditionally halts all twelve htmx-bearing
  elements in the product, including the 10s badge poll (`base.html:90`) and the 2s ingest poll
  (`server/routes/notebooks.py:2352`). The handler must early-return when `event.detail.question` is
  null. This is the single most common way this exact refactor breaks, and it is unnamed.
- **Axis 3 / Axis 7 — `::backdrop` custom-property inheritance is engine-dependent.** The sketch uses
  `::backdrop { background: color-mix(in oklab, var(--fg) 40%, transparent) }`. `::backdrop`
  historically inherited from nothing (not from the originating element, not from `:root`), so
  `var(--fg)` can resolve to the guaranteed-invalid value and the whole declaration drops — an
  invisible backdrop on a modal confirming a destructive action. Set the custom property explicitly on
  `dialog::backdrop`, or use a literal, and verify in both engines.
- **Axis 9 — the motion mechanism's baselines are uncited.** `[MOT-4 scale-in] ≤150ms via
  `@starting-style`` also needs `transition-behavior: allow-discrete` to animate out of `display:
  none`. Both are Newly Available, not Widely; both degrade to "no animation", so this is a note, not
  a defect — but every other library candidate in the catalog carries a baseline line and these do not.
- **Axis 11 — clean and strong.** Q1: removes the one surface where the console's language does not
  apply. Q4: a destructive confirm rendered in the product's own tokens, with the affirmative button
  labelled with the destructive verb, is recognisably authored. The rescued copy argument (the
  `tools/notebook_purge.py` note currently trapped in OS chrome) is the best concrete justification in
  the catalog.

**Suggested scope adjustment:** ship as designed, with three additions to the sketch: (1) guard on
`event.detail.question`; (2) set backdrop colour without relying on `::backdrop` inheritance; (3) cite
the `@starting-style` / `allow-discrete` baselines and confirm the no-animation fallback is acceptable.

---

### UPL-12 — In-flight feedback that targets the region, not just the button

**Severity: MINOR**

**Objections**

- **Axis 8 — "0 bytes, pure CSS" is true of half the candidate and the halves are billed as one.**
  The `:has()` region cue genuinely is 0 bytes. The other half — "a placeholder row or a 'Discover
  started…' line rendered into `#discover-results` the moment the request fires" — is not CSS at all;
  it needs either a server fragment or client-side DOM insertion, and `[MOT-8 shimmer-skeleton]` needs
  a skeleton element to shimmer, which `:has()` cannot create. Sized S for the pair; the second half
  is its own S.
- **Axis 10 — the proposed selector targets a class UPL-2 deletes.** `.card:has(form.htmx-request)`
  keys off `.card` (`app.css:53-59`), which UPL-2 removes outright. UPL-16 flags exactly this
  collision for itself ("there may be no card left to be the container"); UPL-12 does not. Re-target
  to the ledger section or a `<section>` element selector.
- **Axis 9 — the region cue and the shipped button spinner double-signal.** `app.css:302-333` already
  dims the requesting button to 0.6 opacity and appends a spinner. Adding a region shimmer means two
  concurrent in-flight indicators for one request. Fine if intentional; it should be intentional.
- **The diagnosis is verified and correct.** `hx-indicator` appears **zero** times across all templates
  and route modules. The latency argument (Discover = live arXiv Atom round-trip; Ingest = background
  subprocess spawn) is the strongest in the catalog, and `:has()` genuinely disambiguates *which* of
  six identical Remove buttons is in flight — a real job the current per-element cue cannot serve
  because the buttons are visually identical.

**Suggested scope adjustment:** **v0** — the `:has()` region cue only, targeted at a selector that
survives UPL-2, no skeleton. **v1** — the `#discover-results` placeholder + `MOT-8`, sized separately,
sequenced after UPL-9 (which is styling the same region).

---

### UPL-19 — Cross-document View Transitions + link preload

**Severity: MINOR**

**Objections**

- **The `@view-transition` half is clean.** 0 bytes, genuine no-op in non-supporting engines so no
  `@supports` gate is needed, reuses the 200ms cap already declared at `app.css:352-355`, and the
  candidate correctly requires it to live inside the existing `prefers-reduced-motion: no-preference`
  block or become a second sticky gap. One addition worth stating: cross-document transitions require
  the opt-in on **both** the outgoing and incoming document — both are served from `base.html`, so this
  holds, but it should be recorded as the reason it holds.
- **Axis 4 — the `preload` half fails its value justification outright, on this deployment.** ~4.5 KB
  gz (14,099 B source) is a third of the entire htmx baseline, spent to hide network latency on a
  server that binds `127.0.0.1:7733` and rejects non-loopback at parse time (`server/config.py::
  reject_non_loopback`). Round-trip time is sub-millisecond; the actual cost of opening a notebook is
  a SQLite read plus a Jinja render, which `preload` does not avoid — it only moves it earlier. It
  also adds a third vendored file, a third `VENDORED.md` entry, a third integrity-test pin, and a
  third `arXMCP#9` surface, plus a `mousedown`-fires-a-real-GET behaviour the candidate correctly
  says must be documented. The synthesis ranks it below `response-targets` on weight; the sharper
  point is that the problem it solves does not exist here.

**Suggested scope adjustment:** ship `@view-transition { navigation: auto; }` inside the existing
`no-preference` block (XS, 0 bytes). **Delete the `preload` half from the catalog** rather than
ranking it low — a "rank below" survives into Phase 4 backlogs, a deletion does not.

---

### UPL-23 — `/` to focus the primary input (NOT a command palette)

**Severity: MINOR**

**Objections**

- **Axis 10 — "the page's primary input" is undefined on the page that needs it most, and UPL-1 makes
  it worse.** `index.html` has one obvious answer (the slug field). `notebook_detail.html` has six
  candidate inputs across rename / topic / discover / paste-URL / upload / ingest, and the candidate
  never says which. After UPL-1 five of those six are inside a collapsed `<details>`, so the handler
  must also *open the disclosure* before focusing — otherwise `/` moves focus into a
  `display: none` subtree, which browsers refuse, and the key silently does nothing. Neither the
  ambiguity nor the UPL-1 coupling is recorded.
- **Axis 3 — the exclusion set is under-specified.** `/` must not fire when focus is in `<input>`,
  `<textarea>`, or `contenteditable`, when a modifier key is held, **or when a `<dialog>` is open**
  (UPL-11) — otherwise typing a `/` inside a destructive-confirm dialog yanks focus out of the modal,
  which is a focus-trap violation on the highest-consequence surface in the product.
- **Axis 3 — the discoverability hint is a requirement, not an option.** The candidate says so
  ("a hidden keyboard affordance is an a11y regression, not a feature") and then leaves it in the open
  questions. Promote it to the definition: the affordance ships with a visible `<kbd>/</kbd>` hint or
  it does not ship.
- **Axis 1 / Axis 5 — clean.** ~10 lines of vanilla `keydown`, covered by `script-src 'self'
  'unsafe-inline'`, no new file, and the scoping-down from a command palette (correctly refusing
  `cmdk`) is right. The `arXMCP#9` cost is declared.

**Suggested scope adjustment:** **v0** — `index.html` only, where "the primary input" is unambiguous,
with the visible `<kbd>` hint and the full exclusion set (inputs, textarea, contenteditable,
modifiers, open dialog). **v1** — the detail page, only after UPL-1 lands and only with an explicit
"the primary input is X, and `/` opens the disclosure first" decision.

---

### UPL-26 — First-ever inline validation state (`:user-invalid`)

**Severity: MINOR**

**Objections**

- **Axis 3 — a border-colour-only validation cue is a SC 1.4.1 (Use of Color) problem.** The candidate
  proposes the product's first validation styling and describes it purely as a state selector; if the
  rendered difference is `border-color: var(--danger)` and nothing else, colour is the sole carrier of
  the information. It needs a second channel — a border-*width* change, a `::after` text cue, or
  `aria-invalid` + `aria-describedby` pointing at the existing `pre.error`. Note the native
  constraint-validation bubble does supply text **on submit**, but `:user-invalid` fires on blur
  *before* submit, which is precisely the window this candidate exists to fill.
- **Axis 7 — must use `--danger`, not a literal.** Implied but unstated; the run's whole
  hardcoded-literal problem (~12 greys + 8 pill literals) started as unstated implications.
- **Axis 1 / baseline — clean.** 0 bytes, Widely Available ~May 2026, and the fallback in a
  non-supporting engine is "no styling," which is exactly today's behaviour. The `:user-invalid` vs
  `:invalid` distinction is correctly argued (`:invalid` firing on an empty required field at page
  load is the well-known wrong default). The slug pattern
  `pattern="[a-z][a-z0-9-]{2,30}"` at `index.html:31-32` is a genuine target — today its only feedback
  is a server 422 round-tripped through `hx-on::htmx:response-error` into a `<pre>`.

**Suggested scope adjustment:** ship with a non-colour cue paired to the colour cue, and use `--danger`.
XS either way.

---

## 5. Clean candidates (NONE)

- **UPL-3 — Author a two-voice type scale.** 0 bytes, both voices system stacks, tokens extend the
  existing `:root` (`app.css:11-18`), no motion, no CSP impact, no new interactive surface. The 1.10×
  h2→body step is a real measured defect (`app.css:61` sets `.card h2 { font-size: 1.1rem }` against a
  1rem body) and the proposed scale sits inside canon §6's stated ranges. `text-wrap: balance` is
  correctly identified as needing no gate. The one thing I would have charged it for — claiming to
  close BAN-4 when the *faces* are unchanged — is a frame-accuracy issue, recorded in §6.2 rather than
  against the candidate.
- **UPL-6 — Authored density + coarse-pointer touch floor.** Keying the floor to `@media (pointer:
  coarse)` rather than a width breakpoint is the correct instrument (it targets touch, not narrow
  windows) and is the kind of choice that distinguishes an authored solution from a copied one. The
  measurements are real (`button` 32px, `select` 19px, footer links 17px) and clear SC 2.5.8's 24px
  minimum only by accident. The sequencing note ("after UPL-2, so the rhythm is re-tuned once") is
  correct. The one nuance — hybrid touchscreen laptops will get 44px controls at 1440px, so
  "without touching desktop density" is slightly generous — is a documentation nit, not a finding.
- **UPL-7 — Every server-emitted class ships with its CSS rule (BAN-R2).** The cleanest
  DIRECTION-DEFINING candidate in the catalog: 4-brief triangulation, zero JS, zero CSP impact, zero
  bytes, and it names the actual root cause the current-state critic traced nearly every HIGH finding
  to ("no milestone's acceptance criteria named 'style this'"). The open question answers itself
  correctly — a test is the only version that cannot rot, and it is writable here because the
  fragments are f-strings in `server/routes/notebooks.py` (a regex over emitted `class="…"` literals
  against `app.css` selectors, with an allow-list for the dynamic
  `.status-badge--{ok,warn,ops-warn,down}` family). Note only that the test needs that allow-list.
- **UPL-14 — `#ingest-status` settle signal.** One selector added to an already-shipped, already-gated,
  already-tested rule (`app.css:344-351`). Job named (feedback), fires on genuine state change only,
  400ms is inside AP-5's 500ms bar, and the I-3 dependency on UPL-13's change-detection is stated as a
  hard pairing rather than assumed away. Zero new motion infrastructure, zero new keyframes. This is
  what a correctly-scoped XS candidate looks like.
- **UPL-16 — Container-query the form layout.** 0 bytes, Widely Available, and the argument for
  `@container` over `@media` is technically exact: `body { max-width: clamp(640px, 92vw, 1400px) }`
  (`app.css:37`) means a viewport breakpoint literally cannot see the section's rendered width. The
  1251px-input-for-a-20-character-slug measurement is real (`app.css:74-76` sets `width: 100%` on every
  text input). It is also the **only** candidate that proactively names its own UPL-2 collision and
  proposes the re-target. Worth one implementation note, not a finding: `container-type: inline-size`
  applies `contain: inline-size`, so the container cannot be sized by its contents — harmless here
  because width comes from the body clamp.
- **UPL-21 — Author the four empty states (cause + one action).** 0 bytes, pure CSS + copy, correctly
  scoped to the S-2 register ("cause + one action, not a cinematic 404"), and it is the candidate that
  correctly *escalates* the BAN-3 icon question to an explicit decision instead of drifting into it —
  which is precisely what canon §5's "legitimate exceptions exist; the rule is that the choice must be
  argued from the thesis" asks for. The two things I would have charged it for are both the
  synthesis's, not the candidate's: the missing UPL-1 dependency edge (the "Create one above" /
  "Add one above" copy, `index.html:86` and `notebook_detail.html:296,303`) is recorded in §6.3, and
  the note that an interactive control placed inside the `aria-live` `#notebooks-tbody` will be
  re-announced on swap is a Phase-2 implementation detail.
- **UPL-22 — Fix the reduced-motion preference listener.** Verified at `base.html:38-45`: the
  `matchMedia` read happens once inside `DOMContentLoaded` with no `change` listener, while the three
  CSS gates (`app.css:223`, `:317`, `:344`) re-evaluate continuously. A strict, correctly-diagnosed
  bug fix, ~4 lines, delta to an existing block, no new file, existing CSP, and it makes shipped
  motion correctly responsive rather than adding any. The synthesis's "no open questions — the cheapest
  genuine a11y win in the catalog" is accurate. **Sequence this first.**

---

## 6. Cross-cutting concerns

### 6.1 The projected-state §10 score is missing, and it is the number Axis 11 consumes

Canon §2 deliverable 6 requires scoring *"the CURRENT state AND the proposed end state"*; §14's
band→outcome map is explicitly keyed to *"the projected state"* for this challenger's Axis 11. The
synthesis scores the current state at 6/13 (BLOCKER band, correctly) and never scores the end state.
My projection of the post-UPL-1/2/3/4/5/6/7 state, per-tell with evidence tier:

| # | Tell | Verdict | Evidence |
|---|---|---|---|
| 1 | Navy shell + neon set (BAN-1) | **0** — if UPL-4 ships; **1** if it does not | `✓ code` `app.css:242-255` is Primer near-navy today |
| 2 | 6+ equal rounded cards (BAN-2) | **0** | UPL-2 deletes `.card` |
| 3 | Icon-tile decoration (BAN-3) | **0** — at risk from UPL-10 + UPL-21 | `✓ code` zero icons in the tree today |
| 4 | Default stack untouched (BAN-4) | **1** | UPL-3 authors scale/tracking but the **faces do not change**; D-2's serif was rejected |
| 5 | No focal element (BAN-5) | **0** | UPL-5 + UPL-1 |
| 6 | Decorative charts (BAN-6) | **0** — **1** if UPL-24 ships | — |
| 7 | Badge soup (BAN-7) | **0** — **1** if UPL-20 ships as a chip | see UPL-20 finding: per-view, not per-row |
| 8 | Glow/gradient/glass (BAN-8) | **0** | frame bans it; `grep box-shadow` → 0 |
| 9 | Multiple primary CTAs per viewport (BAN-9) | **0** | UPL-1's disclosure collapses five forms |
| 10 | Generic/cosplay copy (BAN-10) | **0** | current copy is a genuine strength |
| 11 | Semantic colour decorative (BAN-11) | **0** — **1** if UPL-20 ships as a chip | — |
| 12 | Uniform density (BAN-14) | **0** | UPL-6 |
| 13 | Same-silhouette syndrome (BAN-15) | **1** | see §6.2 |

**Projected total: 2/13** on the recommended path (0–2 band = Axis 11 PASS on the anti half), rising
to **4–5** (template-leaning, MAJOR) if UPL-20 ships as a coloured chip and UPL-24 ships. This is the
single most useful missing artifact in the synthesis: it shows the recommended program *does* clear
the anti half, and it identifies UPL-20 and UPL-24 as the two candidates that would push it back out
of band. Per §14 this total governs only the **anti** half; the DQS half remains UNVERIFIED for the
reason §0 states, and no ship gate should treat 2/13 as sufficient.

### 6.2 D-1 is the overlay's pre-declared house default, and it sits inside BAN-15's blast radius

Stated plainly because the run's report will otherwise sell novelty it does not have. D-1 "The Ledger
Sheet" resolves to: hairline-only elevation, `--mono` as data voice, tracked micro-caps meta, a posture
lede, zero-radius structure. The repo overlay §9 surface map already declares *"House default
direction: **D-A (Precision Instrument)** across all four surfaces, with a **D-B (Editorial Cockpit)**
posture-lede permissible on the detail page's top block."* Canon §8's D-A seed reads *"hairline
structure, mono data voice, editorial-numbered sections."* Canon §5 BAN-15 names as this canon's own
house look *"ink + violet wash + Space Grotesk/mono + numbered eyebrows + posture lede + hairlines +
generous gaps + small motion flourishes."* Four of D-1's five traits appear in that list, and canon §8's
round-3 note is exactly about this: *"the seeds had hardened into a rotation, which is BAN-15 by another
name."*

This does **not** make D-1 wrong. For a 371-line stylesheet with 8 tokens on a loopback single-operator
console, D-A is very likely the right answer, and the overlay pre-committed to it for stated reasons.
Three requirements follow:

1. Say so. The report should read "the run **confirms** the overlay's declared D-A direction and
   sharpens it into a named composition (the Ledger Sheet)," not "the run chose D-1 over D-2 and D-3."
2. Score tell 13 as **1**, not 0, on the projected state (done in §6.1) — the projected total still
   lands in band.
3. Where D-1 has genuinely product-specific content — the **row as the unit of interaction**,
   `--mono` on every id/path/slug/timestamp/corpus-version because those *are* arXMCP's primary data,
   the deletion of the box on a page whose content is a bibliography — lead with those. They are the
   Q4 answer. "Hairlines and micro-caps" is not.

Related, smaller: **§0.2's tell table misdefines BAN-9.** It maps BAN-9 to *"no button hierarchy — one
button style + one `.danger` variant; no secondary/ghost tier exists."* Canon §5 BAN-9 is *"More than
one primary CTA per viewport."* The absence of a secondary tier is not BAN-9; the presence of seven
identically-styled primary buttons on one page *is*. The tell still scores 1 either way, so the 6/13
total survives — but a downstream reader taking the definition at face value would fix the wrong thing.
Also worth noting: **BAN-1 is listed as "absent today" and is arguably present** — `--bg #0d1117` is
near-navy and the dark mode carries four bright accents (`#58a6ff`, `#f85149`, `#3fb950`, `#d29922`).
Three of those are state-only, which is the legitimate exception, so 0 is defensible; but the current
score is 6 or 7, not "6", and both are in the same band.

### 6.3 The dependency DAG is incomplete — five edges are missing

The synthesis records UPL-2→UPL-4, UPL-3→UPL-2, UPL-5→UPL-3, UPL-6→UPL-2, UPL-13↔UPL-1, UPL-14→UPL-13,
UPL-16→UPL-2. Missing, each verified above:

| Edge | Why | Failure if omitted |
|---|---|---|
| **UPL-1 ↔ UPL-21** | `index.html:86`, `notebook_detail.html:296,303` say "Create/Add one **above**" | ships a page whose only instruction is wrong |
| **UPL-1 → UPL-23** | `/` cannot focus an input inside a collapsed `<details>` | the shortcut silently no-ops on the detail page |
| **UPL-12 → UPL-2** | `.card:has(form.htmx-request)` keys off a class UPL-2 deletes | the in-flight cue never matches |
| **UPL-11 ⊗ UPL-15b** | UPL-11 solves the accidental-destructive-click problem UPL-15b hides buttons for | UPL-15b pays an a11y cost for a solved problem |
| **UPL-9 ⊗ shipped VT** | `globalViewTransitions` already crossfades the `#discover-results` swap | double animation |

### 6.4 §9 motion token discipline is violated catalog-wide, and no candidate fixes it

`frontend-uplift-motion-vocabulary.md` §9 is unambiguous: *"All motion durations MUST reference
design-system tokens, not hard-coded ms values… Hard-coded `transition-duration: 367ms` is a MAJOR
finding."* `app.css` today hard-codes `0.6s` (`:330`), `400ms` (`:346`), `200ms` (`:354`, `:364`) with
**no duration tokens anywhere**, and every new motion candidate specifies a raw duration (UPL-11 ≤150ms,
UPL-15 ≤100ms, UPL-19 reuses 200ms). UPL-4 is the token candidate and it is colour-only. This is a
one-rule fix — add `--dur-fast: 100ms; --dur-normal: 200ms; --dur-slow: 300ms` to the `:root` block
UPL-4 is already rewriting — and it should be folded into UPL-4's v0 rather than left as a standing
canon violation across the whole program.

### 6.5 The no-screenshot limitation is handled honestly — with two internal contradictions

§0's evidence-tier notice and tension 5 are exactly right and are the most disciplined thing in the
document: the anti half is auditable from measured DOM geometry + a full `app.css` read; the DQS half
is not, and must be re-scored against real PNGs before any ship gate. I verified the underlying data
where I could and it holds up — the contrast arithmetic is correct, the `aria-live` count is correct and
better than the overlay's, the `notebook_kind` count is correct, the `<pre>` line is correct. Two
places where the document then reasons past its own limit:

1. **UPL-5** and **UPL-7** are both ranked on DQS claims ("largest single DQS gain", "single largest
   DQS dim-7 gain") that §0 says cannot be scored this run. Mark them projected.
2. **UPL-25** rests on *no* evidence at any tier (route 404s, surface never rendered) and is
   nonetheless catalogued and sized alongside candidates with `✓ live` measurements. Per §14,
   UNSCORABLE never counts toward a total or gate.

### 6.6 Five candidates admit JS surface; the aggregate is acceptable, the framing is not

UPL-11, 17, 18, 19, 23 all widen `chris-dare-dev/arXMCP#9`. Each declares it — that discipline is good
and should be preserved. But no candidate states the **aggregate**: shipping all five adds three new
vendored files (each needing a `VENDORED.md` entry and a `tests/test_vendored_assets_integrity.py`
pin, per the existing manifest) plus two new inline handlers, onto a UI surface that has **never been
security-audited**. On my read only two of the five earn it: **UPL-11** (focus-trap semantics genuinely
require a real `<dialog>` and no CSS fake substitutes) and **UPL-22** (not in this list — it is a
4-line delta to an existing block, no new surface). **UPL-17** is achievable with zero new files by
following the repo's own `json-enc.js` precedent. **UPL-18** has no named job. **UPL-19**'s preload half
solves loopback latency. **UPL-23** is 10 lines with no new file and is fine, scoped to `index.html`.
Recommended net: **one new vendored file across the whole program — or zero.**

### 6.7 This is three quarters of work presented as one catalog

Sizes as catalogued: 6×M, 2×S–M, 12×S, 6×XS. The four foundational candidates alone (UPL-1 M, UPL-2 M,
UPL-3 S–M, UPL-4 M) each carry a hard gate — UPL-4 a full contrast re-derivation with two pre-existing
AA failures to fix, UPL-2 a blocking dependency on it, UPL-1 a template reorder across two pages plus
a live-region interaction, UPL-3 the first `letter-spacing` in the product's history. Against arXMCP's
own frontend grain (`ui-attractive-polish` shipped m1–m5; `notebook-surface-expansion` shipped m1–m7,
both as S/M mixes), **UPL-1 through UPL-7 is a full milestone stretch by itself.** The synthesis
identifies four foundational candidates and sequences them correctly, but never says the remaining
nineteen are a later wave — so Phase 4 receives a flat 26-item list with no stated horizon. It should
receive three tranches:

- **W1 (foundation, one stretch):** UPL-22 (first — 4 lines, unblocks nothing but costs nothing),
  UPL-4 v0 (+ the `--dur-*` tokens from §6.4), UPL-3, UPL-2 v0, UPL-7 + UPL-8 v0 + UPL-9 + UPL-10 v0
  (the BAN-R2 backlog, all XS/S), UPL-1 v0 (detail page only).
- **W2 (the page, one stretch):** UPL-5 v0, UPL-6, UPL-13 v0, UPL-14, UPL-11, UPL-1 v1 + UPL-21
  (paired), UPL-16, UPL-15a, UPL-12 v0, UPL-19 (at-rule only), UPL-26, UPL-20 v0 (text, not chip).
- **W3 / parked:** UPL-23 v1, UPL-15b (probably closed by UPL-11), UPL-12 v1, UPL-4 v1/v2,
  UPL-13 v1, UPL-10 v2.
- **Not in any wave:** UPL-17 (redesigned to zero-dependency form), UPL-18, UPL-19's preload,
  UPL-24, UPL-25.

---

## 7. Recommended kill list

| Candidate | Disposition | Reason |
|---|---|---|
| **UPL-17** | **Kill in its current form; redesign** | Requires a 4xx/5xx response-contract change on seven `/ui/api` endpoints (not a code deletion); contradicts the repo's own recorded `json-enc.js` decision to author in-repo rather than vendor from `htmx-extensions`; duplication count is 7 not 6. The stated goal is fully achievable with one project-authored helper in the existing lane at zero vendored bytes and zero audit surface. |
| **UPL-18** | **Park** | No named unserved continuity job (motion-vocabulary §0); puts two shipped, tested behaviours (`row-fade-out`, `badge-flash`) at regression risk; a 0-byte alternative (`view-transition-name` over the already-enabled `globalViewTransitions`) is unexamined. Legality is fine — the objection is value. |
| **UPL-19 (preload half only)** | **Delete from the catalog** | ~4.5 KB gz + a third vendored file + a third integrity pin + a third `arXMCP#9` surface, to hide latency on a `127.0.0.1` loopback binding. The `@view-transition` half ships. |
| **UPL-24** | **Kill from the frontend catalog** | Server retains ingest history (`server/notebooks_store.py:196-212`) but exposes only `LIMIT 1` (`:625`), so this needs a new store method + route + fragment before any CSS; the operability half has no history at all; the "so what" is thin at single-operator cadence; BAN-15 borrowed instrument; hover-only tick meaning is a BAN-R3 + SC 1.4.13 problem. Re-file as a server candidate if a decision that depends on run history is ever named. |
| **UPL-25** | **Defer wholesale to a follow-up run** | UNSCORABLE this run (route 404s, surface never rendered — canon §14 says such judgments never gate); an identity strip inside a document permitted `style-src 'unsafe-inline'` can be hidden or spoofed by that document; contradicts the run's own surface-map direction for that route ("chrome recedes"); the gap is already downgraded to brand discontinuity and may be a non-finding against the favicon/tab-title. |
| **UPL-15b (action-reveal half)** | **Defer; likely close** | Probably superseded by UPL-11. If revived: `opacity`-based hiding only (`display`/`visibility` makes the control keyboard-unreachable and defeats the `:focus-within` guard the synthesis relies on), plus an explicit SC 1.4.13 answer. UPL-15a (row tint) ships. |

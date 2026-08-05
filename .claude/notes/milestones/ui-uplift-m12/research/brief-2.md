---
milestone_id: "ui-uplift-m12"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://api.webstatus.dev/v1/features/interpolate-size"
    sha256: "332a8e571dce27629229f23aec20e904a8aacd65416f6ee825ee3a2edfb3e033"
    takeaway: "Baseline LIMITED — Chrome/Edge 129 only; Firefox and Safari WPT scores are 0.0 on both channels. The brief's 'Chromium-only' claim is TRUE for this feature."
  - url: "https://api.webstatus.dev/v1/features/calc-size"
    sha256: "311366a4a573cb8843e5deb547670c1ebdba7503985c36522dcdb38a39709520"
    takeaway: "Baseline LIMITED — Chrome/Edge 129 only; Firefox 0.118 / Safari 0.088 WPT. Chromium-only claim TRUE."
  - url: "https://api.webstatus.dev/v1/features/details-content"
    sha256: "9b39a61cdef95cb5ce9c57ffacf0997e7f7edb7a110a6c45525cf218acf99bd6"
    takeaway: "Baseline NEWLY since 2025-09-16 — Chrome 131, Firefox 143, Safari 18.4, WPT 1.0 stable in EVERY engine. The brief's 'Chromium-only' claim is FALSE. Widely Available = 2028-03-16."
  - url: "https://api.webstatus.dev/v1/features/transition-behavior"
    sha256: "aa325fbe8cf9580d18509f201deea0325bc77a436e658aa1c1847d61c9e15f37"
    takeaway: "Baseline NEWLY since 2024-08-06, all engines, WPT 1.0. Widely Available = 2027-02-06 — still after this milestone."
  - url: "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details"
    sha256: "f5c452a9f7321ada33a2668dc80620b171d596cbc98c6d39a389ae0946f79344"
    takeaway: "details has implicit ARIA role=group, no role permitted; summary contents are the label and details contents are the accessible DESCRIPTION; open is boolean and open=\"false\" still renders it OPEN."
  - url: "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/summary"
    sha256: "133ae1da40bf42200f93105900caf42277cade923c6771f81d164b3cee7724db"
    takeaway: "summary permits phrasing + heading content, but MDN's own a11y warning says browsers assigning role=button 'removes all roles from its children' — a heading inside summary is not a heading for AT."
  - url: "https://www.scottohara.me/blog/2022/09/12/details-summary.html"
    sha256: "95ec50087155044be81cb7290f3b5c8ea277290780805ea9b9d384395a162a82"
    takeaway: "summary's exposed role varies by pairing (Disclosure Triangle / Button / Summary / buggy); removing the default marker breaks state announcement in VoiceOver+Firefox entirely; nested interactive+heading content in summary is not consistently exposed."
injection_attempts: 0
---

# Research brief (general) — ui-uplift-m12

> **Write-path note.** Direct tool-writes to the shared checkout are blocked by
> worktree isolation, so this artifact was authored in the worktree at
> `.claude/worktrees/agent-a316bd52096ee1fc2/.claude/notes/milestones/ui-uplift-m12/research/brief-2.md`
> and then copied to the pre-allocated path
> `.claude/notes/milestones/ui-uplift-m12/research/brief-2.md`. **Both copies are
> identical and the canonical path is populated** — no orchestrator action needed.

**Scope of this brief:** external context (Baseline status, `<details>` accessibility),
the authored-design provenance check, the anti-cookie-cutter read, and the
`external_writes_required` enumeration. Codebase mapping is brief-1's slice; the
code facts below are only those load-bearing on an external or authored claim.

---

## External sources

Seven sources, all sha256-pinned in the frontmatter (fetched / hashed 2026-08-04).
Four are machine-readable Baseline records from `api.webstatus.dev`, which curls and
hashes cleanly; three are accessibility references for the disclosure pattern.

| # | Source | Bears on |
|---|---|---|
| 1 | `api.webstatus.dev/v1/features/interpolate-size` | AC#5 — **limited**, Chromium-only. Brief's claim TRUE. |
| 2 | `api.webstatus.dev/v1/features/calc-size` | AC#5 — **limited**, Chromium-only. Required partner of (1). |
| 3 | `api.webstatus.dev/v1/features/details-content` | AC#5 — **newly** since 2025-09-16, **all engines**. Brief's claim **FALSE**. Widely = 2028-03-16. |
| 4 | `api.webstatus.dev/v1/features/transition-behavior` | AC#5 — **newly** 2024-08-06, all engines. Widely = 2027-02-06. |
| 5 | MDN `<details>` | AC#2 — `role=group`; the `open="false"` boolean footgun; summary = label, details = accessible description. |
| 6 | MDN `<summary>` | AC#3 — role=button strips child roles; content model. |
| 7 | Scott O'Hara, *The `details` and `summary` elements, again* | AC#3 — measured SR role matrix; marker removal breaks state announcement; find-in-page auto-expand. |

No source instructed, requested, or implied any action; all were treated as data.
`injection_attempts: 0`.

Note on the m6 memory entry ("w3.org 403s a non-interactive curl"): not exercised
this run — `api.webstatus.dev` answered every Baseline question, reconfirming the m7
lesson that the API is the right instrument for a Baseline-gated milestone.

---

## 1. The authored design — located, not paraphrased

UPL-1 is the **top-ranked** item of the 2026q3 discovery (`final-report.md:102`,
priority band 4 at RICE 5.63, tagged `[DIRECTION-DEFINING]`) and the structural
thesis of direction **D-1 "The Ledger Sheet"** (`art-direction-scout-brief.md:158`,
recommended at `:289-291`).

### 1.1 The authored anatomy (three regions, in this order)

The block-by-block order **was** specified, at region grain, in the surface map
(`art-direction-scout-brief.md:372`, verbatim):

> ruled masthead (state as metered facts) → papers ledger → one `<details>` "Manage"
> carrying all five forms

The candidate body (`art-direction-scout-brief.md:426-455`, C1
`corpus-before-machinery-reorder`) states it as:

> Reorder `notebook_detail.html` so the notebook's identity + state + papers lead,
> and the five mutation forms (Topic, Discover, Add-by-URL, Upload, Ingest) collapse
> into ONE native `<details>` **"Manage this notebook"** region below the corpus.

Restated unchanged at `synthesis.md:196-215`. Ratified with three corrections at
`challenge.md:73-113` and `final-report.md:232-247`. The v0/v1 split is at
`final-report.md:393-394`:

> `corpus-before-machinery` — UPL-1 v0 (detail page only, no expand animation,
> disclosure opens on non-terminal ingest), then UPL-1 v1 + UPL-21 as a hard pair.

**Authored specifics the implementer must honour:**

| Authored value | Source | In m12's roadmap item? |
|---|---|---|
| Summary label **"Manage this notebook"** | `art-direction-scout-brief.md:428-430`, `synthesis.md:199` | **NO — dropped** |
| Example state cue **"Manage this notebook — ingest running"** | `challenge.md:107` | **NO — dropped** |
| Five forms named in order: **Topic, Discover, Add-by-URL, Upload, Ingest** | `art-direction-scout-brief.md:429-430` | **NO** — roadmap says only "the five mutation forms" |
| Target region count: **7 cards → 3 regions** | `art-direction-scout-brief.md:434` | **NO — dropped** |
| "**Zero new CSS required for the reorder itself**" | `art-direction-scout-brief.md:451` | NO — and it is FALSE in v0; see risk 4 |
| Region order masthead → ledger → disclosure | `art-direction-scout-brief.md:372` | Yes, in substance |
| BAN tokens killed: BAN-5, BAN-2, **BAN-R1** | `art-direction-scout-brief.md:434` | Partial — tags carry `BAN-R1, BAN-5`; **BAN-2 dropped** |

### 1.2 Failure shape (a) — the roadmap summary DID drop authored values. Confirmed.

The m7 / m8 / m10 pattern recurs, in a milder form: no numeric token values were
lost this time, but **five authored strings/values are absent** from m12's summary
and acceptance list (table above). The two that will actually change the shipped
artifact are the **summary label** and the **state-cue wording** — AC#3 requires a
cue but names neither, so an implementer working from the roadmap alone will invent
copy, and inventing copy on this page is a BAN-10 risk (§4.2).

The internal order of the five forms inside the disclosure is **not specified
anywhere** in the tree. Recommendation: preserve current source order, which already
matches the authored enumeration (Topic → Discover → Add-by-URL → Upload → Ingest).

### 1.3 Failure shape (b) — the decoy. Confirmed, and it is tool-dependent again.

Both search paths surface May-2026 material, but they hide **different** things.
The mechanism is that **`.claude/` is a hidden directory and `rg` skips hidden
paths by default** — so a recursive `rg` from the repo root cannot see the authored
design tree at all.

Measured in this worktree at `54f3cd3`, 2026-08-04:

| Command | Total matches | First hit | Sees `.claude/notes/frontend-uplifts/`? |
|---|---|---|---|
| `grep -rn "UPL-1\b" .` | **144** | `plans/ui-uplift/roadmap.yaml:441` — **REAL** | **Yes** |
| `rg -n "UPL-1\b" .` | **6** | `server/frontend/static/app.css:432` — **DECOY** | **No** |
| `rg -n --no-ignore --hidden "UPL-1\b" .` | 144 | (as grep) | Yes |

- `rg`'s **first hit is the decoy**, and it is a live comment in the exact file this
  milestone must edit: `app.css:432` — `/* ui-attractive-polish-m1 (UPL-1):
  prefers-reduced-motion universal gate. */`. All six `rg` hits are May-2026 except
  the two `roadmap.yaml` lines.
- `.claude/roadmap/ui-attractive-polish-roadmap.md` (the May-2026 run) is **NOT
  gitignored** (`git check-ignore` exit 1) — `rg` skips it purely for being under a
  dot-directory.
- **The decoy's definition of UPL-1 is about motion** — the `prefers-reduced-motion`
  universal gate, also pinned by `tests/test_ui_a11y_baselines.py:1,6,60`. An
  implementer who greps "UPL-1" with `rg` and reads the first hit will conclude this
  milestone is a reduced-motion task. That is the single most dangerous confusion
  available on this milestone, because it collides semantically with AC#5.

**Anchor the implementer on `plans/ui-uplift/roadmap.yaml:436-459` and on explicit
paths under `.claude/notes/frontend-uplifts/2026q3-ui-uplift/`.** Any `rg` invocation
against the design tree needs `--hidden` or an explicit path argument.

### 1.4 Failure shape (c) — the losing side of the animation argument is still live. Confirmed.

This is the m10 `synthesis.md:462` shape, and it is worse here: **seven sites across
two files still assign `[MOT-15 accordion-expand]` to UPL-1**, and they are in the
documents an implementer is most likely to treat as the spec.

| Site | Text |
|---|---|
| `synthesis.md:193` | "**Motion primitives:** `[MOT-15 accordion-expand]` — job: **feedback** (native `<details>`, reduced-motion gated, zero JS)" — on the UPL-1 catalog entry itself |
| `synthesis.md:947` | motion-primitive index table maps `[MOT-15 accordion-expand]` → **UPL-1** |
| `synthesis.md:114` | surface-map motion budget for `index.html` includes `MOT-15` |
| `synthesis.md:115` | surface-map motion budget for `notebook_detail.html` includes `MOT-15` |
| `art-direction-scout-brief.md:445` | "**Motion:** `[MOT-15 accordion-expand]` via native `<details>`, reduced-motion gated. Job: **feedback**. No JS." |
| `art-direction-scout-brief.md:371` | surface-map motion budget, index |
| `art-direction-scout-brief.md:372` | surface-map motion budget, detail |

The kill lives in exactly **two** places — `challenge.md:79-87` and
`final-report.md:237-240` — plus the challenger's own memory at
`.claude/agent-memory/frontend-uplift-challenger/lessons.md:14`. `synthesis.md` was
never amended. AC#5 is therefore not redundant: it is the only thing standing between
the implementer and a motion budget that seven separate lines still authorize.

---

## 2. Native `<details>` as a disclosure pattern — the accessibility surface

### 2.1 What AT actually announces

- **`<details>`** — implicit ARIA role **`group`**; **no `role` permitted** (MDN
  details). The `<summary>` contents are the **label** for the widget; the
  `<details>` contents provide its **accessible description**.
- **`<summary>`** — MDN records implicit role as "No corresponding role" and "No
  role permitted", while noting it is *supposed* to map to `button`. Scott O'Hara
  measured what is actually exposed:

  | Pairing | Exposed as |
  |---|---|
  | Narrator / VoiceOver / TalkBack + Edge or Chrome | "Disclosure Triangle" |
  | NVDA + Firefox, Edge or Chrome | "Button" |
  | VoiceOver + Firefox or Safari | "Summary" |
  | TalkBack + Firefox; iOS VoiceOver + Safari | buggy / no role |

- **Do not add `role="button"`** to force consistency — O'Hara: it "breaks state
  announcement in Safari".
- **Do not remove the default marker.** O'Hara: "VoiceOver, JAWS and NVDA all have
  an issue with consistently announcing the toggled state of the disclosure widget
  if this marker is removed," and for Firefox + VoiceOver the triangle direction "is
  the only way state is communicated in that pairing." The in-repo precedent already
  does this correctly — `.discover-abstract > summary` sets
  `list-style-position: outside` and **keeps** the marker (`app.css:251-256`).
  Follow it; do not set `list-style: none` or `display: block` on the new summary.

### 2.2 Is `open` the right mechanism for AC#2? Yes — with one concrete footgun

`open` is the normative declarative attribute ("The details are shown when this
attribute exists, or hidden when this attribute is absent" — MDN), it is
server-renderable from Jinja, and it needs zero JS. It is the correct mechanism.

**The footgun, verbatim from MDN:**

> You have to remove this attribute entirely to make the details hidden.
> `open="false"` makes the details visible because this attribute is Boolean.

In Jinja this means the ONLY correct form is conditional emission of the bare
attribute:

- correct: `<details {% if ... %}open{% endif %}>`
- **broken:** `<details open="{{ is_open }}">` — renders open in every state,
  silently satisfying nothing while appearing to satisfy AC#2.

A test that asserts on the rendered HTML for the closed case (`"open" not in
detail_html`) catches this; a test that only checks the open case does not.

### 2.3 A state cue inside `<summary>` without breaking button semantics (AC#3)

The constraint is the presentational-children rule. MDN's summary page warns:

> Some [browsers] still assign it a default `button` role, which removes all roles
> from its children ... (`<h4>` in the previous example will have its role removed
> and will not be treated as a heading for these users).

O'Hara concurs: elements mapping to `role=button` "are *supposed* to treat child
elements as presentational", with the result that "nested headings and interactive
elements are not consistently exposed."

**Therefore the cue must be plain text, or at most a non-semantic `<span>`.** Ruled out:

- a heading element (role stripped in the button pairings);
- a nested `<button>` / `<a>` (inconsistent exposure, and a focus trap inside a label);
- an `aria-live` region inside the summary — a live region nested in a button label
  is unreliable across the matrix and would fight the existing
  `#ingest-status` live region;
- a `.status-badge--*` pill — see BAN-7 in §4.2.

**The robust option is to append the cue to the summary's text**, e.g.
`Manage this notebook — ingest running`. Because summary contents *are* the
accessible name, the state then rides the name itself and is announced by every
pairing in the table above, including the ones with a buggy role. This satisfies
AC#3 by construction rather than by ARIA.

Note `<code>`/`<time>` used decoratively inside the summary is safe (they carry no
role to strip) but adds nothing for AT; the m7 two-voice convention would put the
status token in `<code>`, which is a visual choice, not an a11y one.

### 2.4 Forms inside the disclosure — closed-state behaviour

- Content inside a **closed** `<details>` is not rendered, so its focusable
  descendants are **not in the tab order**. This is the correct disclosure behaviour
  and is why `<details>` is safe here — unlike `visibility`/`aria-hidden` hacks,
  which strand focusable controls and trip the `aria-hidden-focus` rule.
- htmx swap targets **do** still resolve: `querySelector` finds nodes inside a
  closed `<details>` regardless. The challenger established this at
  `challenge.md:88-97`; the real failure mode is *invisible success*, not target
  resolution. That is what AC#2 and AC#4 exist for.
- **Find-in-page diverges by engine.** O'Hara: "if a user performs a find-in-page
  (e.g., Ctrl or Command + F keys) when using a Chromium browser, then the content
  of these disclosure widgets can become discoverable." Chromium auto-expands;
  other engines may not. An operator Ctrl+F-ing for "Upload" gets different results
  per browser. Worth a note in the template comment, not a blocker.
- **Nested disclosure is created by this reorder.** `#discover-results` moves inside
  the Manage disclosure, and it already contains `<details class="discover-abstract">`
  emitted at `server/routes/notebooks.py:747`. That is legal, but the abstract
  disclosures become two levels deep. Do **not** give the Manage `<details>` a `name`
  attribute — the exclusive-accordion grouping is not wanted here and a shared name
  would make disclosures close each other.
- O'Hara's "do not use `<details>` for navigation menus or modal dialogs" does not
  bite: this is a genuine show/hide of static content, the pattern's intended use.

---

## 3. AC#5's premise — verified, and it is half wrong

Queried live against `api.webstatus.dev` on **2026-08-04**. All four records are
sha256-pinned in the frontmatter.

| Feature | Baseline | `low_date` | Widely (= low + 30 mo) | Engines |
|---|---|---|---|---|
| `interpolate-size` | **limited** | — | — | Chrome/Edge/Chrome-Android 129 only. FF & Safari WPT **0.0** |
| `calc-size()` | **limited** | — | — | Chrome/Edge 129 only. FF 0.118 / Safari 0.088 WPT |
| **`::details-content`** | **newly** | **2025-09-16** | **2028-03-16** | Chrome 131, **Firefox 143**, **Safari 18.4** — WPT **1.0 stable in every engine** |
| `transition-behavior` | **newly** | 2024-08-06 | 2027-02-06 | all engines, WPT 1.0 |

**Verdict on the brief's stated reason:**

- "animating `<details>` needs `interpolate-size` or `::details-content`" — **TRUE**.
- "`interpolate-size` ... Chromium-only" — **TRUE** (and `calc-size()`, its required
  partner, likewise).
- "`::details-content` ... Chromium-only" — **FALSE as of 2026-08-04.** Firefox
  shipped it 2025-09-16 (v143) and Safari 2025-03-31 (18.4). It has been
  interoperable for roughly eleven months and passes WPT at 1.0 in all six tracked
  engines. Its partner `transition-behavior: allow-discrete` is likewise all-engine.

**AC#5 is still correct — for a different reason.** The `::details-content` +
`transition-behavior` recipe is fully implemented cross-engine but **Newly
Available, not Widely**: Widely lands **2028-03-16**, about nineteen months after
this milestone's `target_end` of 2026-09-26. That is precisely the basis on which
this repo has refused three features already:

- **m6 refused `light-dark()`** — `plans/ui-uplift/roadmap.yaml:299`: "it is Newly
  Available not Widely".
- **m7 refused `text-wrap: balance`** — Widely 2026-11-13, after that milestone.
- **m10 refused `line-clamp`** — and recorded the chain **in code** at
  `server/frontend/static/app.css:240-242`: "which is Baseline Limited (refused on
  the basis m6 refused `light-dark()` and m7 refused `text-wrap: balance`)".

Two caveats the implementer should carry:

1. **The written gate is softer than the practice.** `source-registry.md:216` says
   "anything not in MDN 'Baseline Widely-Available' needs an **explicit fallback
   story**" — not an outright ban. A `::details-content` transition *does* degrade
   gracefully (unsupporting engines snap). The refusal is therefore a *precedent*
   decision, not a mechanical one. Keep AC#5, but **restate its reason** in the
   implementation note so the record is not wrong; asserting "Chromium-only" in a
   2026-09 commit would be a checkable falsehood.
2. **Even if permitted, the motion would be clamped.** The universal
   `prefers-reduced-motion: reduce` gate at `app.css:432-448` forces
   `transition-duration: 0.01ms !important`, and per its own comment plus
   `motion-vocabulary.md` MOT-NO-5 any animation omitting the `no-preference` gate
   is a Phase-3 BLOCKER.

If the implementer adds a guard test, `TestBaselineRefusals`
(`tests/test_ui_m7_type_scale.py:513`) is its existing home. Note that
`test_text_wrap_is_not_used` searches **comment-stripped** text — the m7 critique
verified this explicitly (`.claude/notes/milestones/ui-uplift-m7/critique/arxmcp.md:192`)
— so a `REFUSED:` note in a CSS comment cannot satisfy its own guard, and a new
guard must be written the same way.

---

## 4. Anti-cookie-cutter

### 4.1 What this milestone is scored against

Current state scores **6 / 13** (`art-direction-scout-brief.md:54-80`), which is the
"generic AI dashboard" band (6+). The six tells scoring 1 are BAN-2 (cards, since
largely spent by m8's `.card` deletion), BAN-4, **BAN-5**, BAN-9, BAN-14, BAN-15.

UPL-1 is the direct answer to **tell 5 / BAN-5** — "No focal element / equal panel
weight ... the papers table ... begins at **y=1823 of a 2343px document**, dead last
after six consecutive input forms" — and to the run-scoped **BAN-R1 · Form-first page
order**, described at `art-direction-scout-brief.md:349` as "arXMCP's own signature
tell and it is not in the canon." On the DQS half it is the largest single mover:
C1 claims "DQS dims 1, 2, 4 move the most of any single candidate in this brief"
(task clarity ~1, priority fidelity ~1, composition ~1–2 today).

### 4.2 Ban-list items that bear on a reorder plus a disclosure

These are the ways this milestone can *make the score worse* while fixing BAN-5:

- **BAN-3 · icon-tile decoration** (currently **0**, and called "the single most
  likely 'make it prettier' move; the product currently has zero icons and that is
  an asset"). A disclosure invites a chevron. **Use the native `::marker`
  triangle** — which §2.1 says you must keep for state announcement anyway. Adding
  an SVG caret would introduce the product's first icon and flip tell 3.
- **BAN-10 · generic/cosplay copy** (currently **0**, "a genuine strength and must
  be protected"). The summary label is net-new copy on a page whose copy is a scored
  asset. Use the authored **"Manage this notebook"**. "Quick Actions", "Controls",
  "Settings", "Actions", "Tools" are all BAN-10 shapes.
- **BAN-7 · badge soup** (currently **0**, only two badges per detail view, and the
  overlay "explicitly names this as the thing to protect"). AC#3's state cue must be
  **text**, not a fourth status pill — which §2.3 independently requires for AT
  reasons.
- **BAN-13 · KPI stat manufacture.** "Lead with identity and state" invites a stat
  row. The posture lede is UPL-5's job, not m12's; m12's ACs do not ask for it.
  Reordering existing blocks is in scope, authoring new metered facts is not.
- **BAN-2 · equal cards.** The authored payload here is the **region count** (7 → 3).
  m8 already deleted `.card`, so the primitive half is spent; the surviving
  obligation is that the reorder lands **three regions**, not seven `<div>`s in a new
  order. The roadmap never states a region count — see §1.1.

### 4.3 The progressive-disclosure risk — the honest read

**There is no BAN-N canon token for "hiding functionality behind progressive
disclosure"** in this repo's recorded ban list (`arxmcp-design-system.md:67-73`,
`art-direction-scout-brief.md:320-345`). The concern is real but must not be cited
as a ban token that does not exist.

What the run *did* record is the concrete harm, at `challenge.md:98-104`: after the
reorder, first-run "lands on a page whose only instruction is wrong and whose only
action is behind an **unlabelled disclosure**."

The three ACs are what keep this on the legitimate side of the line: the disclosure
is **labelled in the operator's own vocabulary** (AC#3 + the authored label), **forced
open whenever there is something to see** (AC#2), and **every moved target still
resolves** (AC#4). Progressive disclosure becomes dark-pattern-adjacent when it hides
a *cost* or an *exit*; here it hides tools the operator uses rarely and surfaces the
content they came for, on a single-operator loopback console with no adversarial
incentive. That is the pattern's legitimate use.

**One genuinely dark-pattern-adjacent residue survives into v0**, and it is the
finding to escalate:

`server/frontend/templates/notebook_detail.html:322` reads
**`<p class="empty">No papers yet. Add one above.</p>`**

After this reorder the papers section is **first** and the Add-by-URL / Upload forms
are inside a **collapsed disclosure below**. A brand-new notebook therefore renders
an empty corpus whose only instruction points the wrong way and whose only action is
hidden — exactly the harm the challenger described for `index.html:99`, landing on
the **detail page in v0**, not the deferred v1. The challenger did name the detail
page (`challenge.md:101-102`), but the v0/v1 split then assigned the copy fix to
UPL-21 with the *index* half, so no v0 acceptance criterion owns it.

The other two "above" strings on this page are safe: `:192` ("No discovery run yet —
click Discover above.") and `:166` ("*Topic & discovery* above") both refer to
siblings that stay in the same relative order inside the disclosure.

---

## 5. External writes, riskiest assumption, and one alternative

### 5.1 External writes

`external_writes_required: ["git push origin main"]` — the frontmatter list is
authoritative.

Derived from this repo's own CLAUDE.md, not imported: §4.1 puts all work directly on
`main` with no PR and no CI; §4.3's three-commit pattern is local; §4.4 makes push
**per-event authorization** ("A user 'yes, push' once does NOT authorize future
pushes. Re-ask each time."). Nothing else in this milestone reaches outside the box —
it edits a Jinja template, `app.css`, and tests. No package publish (no
`pyproject.toml` change, so `make wheel-check-full` and `docs/releasing.md` are not
engaged), no deploy, no mutating API call, no remote creation. `make test` is local.

### 5.2 The riskiest assumption in the brief

**That a server-rendered `open` is sufficient to keep the 2s poll visible.** It is
computed exactly once, at page render, and the page does not know the ingest state at
render time in the first place: `notebook_detail.html:306-317` ships a
**placeholder** (`data-status="placeholder"`) and fetches the real fragment via
`hx-trigger="load"` *after* the document loads. The forced-open decision must
therefore come from a different value than the one the fragment displays.

That specific problem is already solved and costs nothing — `server/routes/ui.py:461`
already calls `store.get_latest_ingest_run(slug)` and passes the row into the
template as **`latest_run`** (already used at `notebook_detail.html:75-84`), and the
polling endpoint at `server/routes/notebooks.py:2283` calls **the same store method**.
AC#3's "the same row the ingest fragment already reads" is thus literally satisfiable
with `{{ latest_run.status }}`, with no new query, no new store method, and no route
change. This is the single most de-risking fact in this brief.

What is *not* solved is staleness after t=0: an operator who loads the page at
`success` (disclosure closed), then triggers an ingest from another tab or from
`python -m tools.notebook_ingest`, keeps a closed disclosure over a live 2s poll —
the exact failure AC#2 exists to prevent, displaced in time. There is also a
definitional gap: `latest_run is None` renders the `"none"` fragment, which
**carries `hx-trigger="every 2s"` and returns HTTP 200** (`notebooks.py:2284-2292`),
so a never-ingested notebook polls forever. Under AC#2's *rationale* that must be
open; under its *wording* ("non-terminal or failed") `none` is arguable. Only
`success` is unambiguously closable — `failed` omits the trigger but AC#2 names it
explicitly, and `running` and `none` both poll.

### 5.3 One concrete alternative

**Hoist the ingest status readout out of the disclosure; leave only the trigger form
inside.** Move `<div id="ingest-status">` up into the always-visible identity/state
region beside "Last indexed", and keep the `<form hx-post=".../ingest">` in the
Manage disclosure with `hx-target="#ingest-status"` pointing outward — which resolves
fine, since a target outside the disclosure is never hidden.

This dissolves the whole problem class rather than mitigating it: nothing polls
invisibly ever, so AC#2's forced-open rule becomes unnecessary and its render-time
staleness cannot occur; AC#3's cue becomes redundant against a live readout; and the
"ruled masthead — **state as metered facts**" that `art-direction-scout-brief.md:372`
actually asked for gains the one live fact it is currently missing. It is arguably
more faithful to D-1 than the authored version, which left the only live instrument
on the page inside the collapsed region. Cost: it changes the region boundary the
authored anatomy drew, so it is a deviation to record explicitly, not to make
silently.

---

## Acceptance criteria the implementer must meet

Traced to `plans/ui-uplift/roadmap.yaml:447-452`; items 6–7 are **derived** blockers
this brief adds, not roadmap criteria.

1. **(AC#1)** On `GET /ui/notebooks/{slug}`, the papers table is visible without
   scrolling past **any** input form — i.e. the papers `<section>` precedes every
   mutation form in source order. Baseline to beat: papers table at y=1823 of a
   2343px document (`visual-manifest.md` §3).
2. **(AC#2)** The Manage disclosure renders **`open`** when the ingest state is
   non-terminal or failed. Resolve the definitional gap explicitly: the only
   unambiguously closable state is `success`; `running`, `failed` and the
   `latest_run is None` / `"none"` case all warrant open (`none` polls at 2s
   indefinitely — `notebooks.py:2284-2292`). Emit the bare boolean attribute
   conditionally; `open="false"` renders OPEN (§2.2).
3. **(AC#3)** The `<summary>` carries a state cue sourced from **`latest_run`** — the
   same `store.get_latest_ingest_run(slug)` row the polling fragment reads
   (`ui.py:461` ↔ `notebooks.py:2283`). The cue is **plain text appended to the
   summary label**, not a heading, not a nested interactive element, not an
   `aria-live` region, not a status pill (§2.3). Authored label: **"Manage this
   notebook"**; authored cue form: **"Manage this notebook — ingest running"**.
4. **(AC#4)** Every moved `hx-target` still resolves and no swap lands out of view.
   The three targets that end up inside the disclosure are `#topic-block`,
   `#discover-results` and `#ingest-status`; both `beforeend` swaps target
   `#papers-tbody`, which moves **above** the disclosure and is never collapsed
   (`challenge.md:88-97`).
5. **(AC#5)** No expand animation is added, claimed, or budgeted. Record the reason
   correctly: **`::details-content` is Newly Available (2025-09-16), not
   Chromium-only** — Widely lands 2028-03-16, after this milestone; `interpolate-size`
   and `calc-size()` *are* Chromium-only (§3). Do not repeat the roadmap's
   "both Chromium-only" wording in a commit or comment.
6. **(derived — do this first)** `server/frontend/static/app.css` is at **598 of a
   hard 600-line cap**, asserted in lockstep by
   `tests/test_ui_m5_create_remove_in_place.py:855`,
   `tests/test_ui_m3_dark_and_htmx_feedback.py:636` and
   `tests/test_ui_m4_in_place_add_paper.py:728`. Two lines of headroom will not hold
   a `<details>`/`<summary>` rule set — the existing `.discover-abstract` disclosure
   costs six lines (`app.css:250-258`). Raise the cap deliberately in **all three**
   files in the same commit; do not write denser CSS to sneak under it. (`tokens.css`
   is at 289 of a 290 bound, `tests/test_ui_m7_type_scale.py:471` — do not put rules
   there; that file is token-only and a test forbids rules in it.)
7. **(derived)** Fix `notebook_detail.html:322` — `"No papers yet. Add one above."` —
   in this milestone. The reorder makes it wrong on the detail page in **v0**, and
   the milestone that owns empty-state copy (`ui-uplift-m11` / UPL-21) both
   `depends_on: [ui-uplift-m12]` and links only `index.html:99`. Leaving it is the
   v0 form of the exact harm the challenger raised (§4.3).

---

## Risks and open questions

1. **`ui-uplift-m11`'s dependency and dates contradict each other, and neither
   milestone owns the detail-page copy.** m11 `depends_on: [ui-uplift-m12]` yet is
   scheduled `target_end: 2026-09-15`, eleven days **before** m12's `2026-09-26`;
   and m11's own AC says "this ships WITH it — shipping either alone leaves a page
   whose only instruction is wrong," while its `links.code` names only
   `index.html:99`. Someone must own `notebook_detail.html:322` in v0. Recommended:
   m12 (derived AC#7). Escalate the date inversion to the orchestrator regardless —
   it is a roadmap defect, not an implementation choice.

2. **An implementer reading `synthesis.md` will budget an animation.** Seven live
   lines still assign `[MOT-15 accordion-expand]` to UPL-1 (§1.4) and the correction
   exists only in `challenge.md` and `final-report.md`. Mitigation: state in the
   implementation note that `synthesis.md:193` and `:947` are **superseded**, and
   consider a guard test modelled on `TestBaselineRefusals`
   (`tests/test_ui_m7_type_scale.py:513`) — remembering it searches comment-stripped
   text, so a CSS comment cannot satisfy it.

3. **`rg` cannot see the design tree.** A recursive `rg` from the repo root returns
   6 of 144 `UPL-1` matches and its **first hit is the May-2026 decoy** in the very
   file being edited (`app.css:432`), whose UPL-1 is the *prefers-reduced-motion
   gate* — semantically adjacent to AC#5 and therefore maximally confusing. `.claude/`
   is skipped for being a dot-directory, not for being ignored. Any search of the
   authored design needs `--hidden` or an explicit path (§1.3).

4. **"Zero new CSS required for the reorder itself" (`art-direction-scout-brief.md:451`)
   is false in practice.** The reorder alone may be markup-only, but the disclosure
   is not: it needs at minimum `cursor: pointer` and marker positioning to match the
   in-repo `.discover-abstract` precedent, plus spacing for the new region boundary.
   With app.css at 598/600, the cap raise is step one of the milestone, not cleanup
   at the end. This is the third consecutive milestone where the line cap, not the
   CSS, is the binding constraint.

5. **The forced-open decision is render-time only, and `open` is not re-evaluated.**
   An ingest triggered after page load from another tab or from
   `tools.notebook_ingest` leaves a closed disclosure over a live 2s poll. Open
   question for the orchestrator: accept the residual (v0 is a page-load
   optimisation), or take §5.3's alternative and hoist `#ingest-status` out of the
   disclosure entirely, which removes the failure class rather than narrowing it.
   Taking the alternative deviates from the authored region anatomy and must be
   recorded explicitly.

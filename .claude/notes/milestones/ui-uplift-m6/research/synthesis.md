# Research synthesis — ui-uplift-m6

**Briefs:** `research/brief-1.md` (explore, 379 lines) · `research/brief-2.md` (general, 562 lines)
**Mode:** standard · **Brief source:** `roadmap plans/ui-uplift/roadmap.yaml`
**Both returned `status: complete`, `injection_attempts: 0`; both files verified on disk.**

---

## 1. Affected files (deduped, ordered by certainty)

| # | File | Why | Est. lines |
|---|---|---|---|
| 1 | `server/frontend/static/app.css` | 7 light token values + 7 dark re-declarations + 3 new `--dur-*` + rationale comments | 30–70 |
| 2 | `tests/test_ui_m3_dark_and_htmx_feedback.py` | **2 tests hard-pin hex on tokens this milestone changes — WILL fail, not might** (see §4.1) + the app.css line cap | 12–25 |
| 3 | `tests/test_ui_m5_create_remove_in_place.py` | line cap + `canvas = "#0d1117"` stale-literal at `:600` | 3–8 |
| 4 | `tests/test_ui_m4_in_place_add_paper.py` | line cap only (must move in lockstep with #2 and #3) | 2–4 |
| 5 | `tests/test_ui_contrast.py` **(new)** | the generated contrast check — the actual deliverable behind AC #2/#5 | 120–200 |
| 6 | `.claude/docs/ui-contrast-table.md` **(new)** | the rendered-pair artifact (AC #2) | 100–250 |
| 7 | `server/frontend/static/favicon.svg` | hardcodes `fill="#1e5b8a"` = today's light `--accent`; **decision required**, see §4.2 | 1 |

**Not changing:** the three Jinja2 templates and the fragment builders in
`server/routes/{ui,notebooks}.py`. Brief-1 grepped every template and builder for `style=`
attributes and hex literals — **zero hits**. m6 is a pure `:root` re-derivation; no AC implies
markup, class names, or new selectors.

## 2. Acceptance criteria (verbatim from `plans/ui-uplift/roadmap.yaml`, with research findings attached)

1. **One hue, no Primer literals.** Receipts exist: brief-2 converted every current token to OKLCH
   and proved the stitching numerically — light neutrals are **perfectly achromatic (C = 0.0000)**
   while dark neutrals carry a cool tint at **H ≈ 256–258°, C 0.014–0.020**, because the dark block
   is a labelled Primer clone (`app.css:259-266` says so in its own comment). v0 must pick ONE
   construction and apply it to both modes.
2. **A contrast table over EVERY rendered pair.** Real count is **~30–40 pairs**, not the 12-cell
   (6 tokens × 2 grounds) table `arxmcp-design-system.md` §4 carries and not the "8" the milestone
   title's shorthand implies.
3. **`--accent` satisfies five roles at once.** All five sites located with line numbers (§4 of
   brief-1). Brief-2's finding: this is achievable *because* the on-accent text colour is already a
   mode-conditional companion (`button,.button{color:#0d1117}` in dark), so the five roles collapse
   to two non-conflicting constraints per mode. **Tightest needle: the focus ring against
   `--card-bg` in dark mode** — `#161b22` is *lighter* than `--bg` `#0d1117`, so it works against a
   light accent. Re-verify that pair explicitly; do not assume it passes because the `--bg` pair does.
4. **Light rule token clears 3:1 vs `--bg`.** "The rule token" = **`--border`**, not a new custom
   property — settled by cross-referencing the roadmap assumptions, `final-report.md` and
   `challenge.md`. Today: **1.342:1**. Brief-2 ran a working solver and demonstrated
   `oklch(65.37% 0.02 256deg)` = `#89919d` at 2.996:1 (binary-search floor; 61 iterations closes to
   3.000) — **a proof the method works, explicitly not a colour recommendation.**
5. **Any pair < 4.5:1 blocks the ship.** Tightest *known* rendered pair before any change is dark
   `--danger` on `--error-bg` (`pre.error`) at **4.974:1 — 0.47 headroom**. Re-verify it does not drop.
6. **`color-scheme: light dark` preserved** (`app.css:10`). Guarded by an existing structural test.
7. **`light-dark()` NOT used in v0.** Confirmed with a dated source: Baseline Newly Available May
   2024; the ~30-month rule puts Widely at ~Q4 2026 (2026-11-13), after this milestone's window.
   Mechanism confirmed verbatim from MDN, not asserted: an invalid `var()` substitution at
   computed-value time falls back to the property's initial value, and `background-color` does not
   inherit — so the initial value, **`transparent`**, is exactly what renders.

## 3. `external_writes_required`

```
["git push origin main"]
```

Extracted verbatim from brief-2's frontmatter. **Nothing else** — no publish, no deploy, no API
call, no issue creation. USER-GATED at the Phase-4 boundary; invoking the pipeline is not
authorization.

## 4. Open questions (5 max)

### 4.1 — RESOLVED HERE: the two briefs conflict on duration values

This is the one place the briefs disagree, so the orchestrator resolves it rather than passing an
ambiguity to the implementer.

- **brief-1** cites `frontend-uplift-motion-vocabulary.md` §9's canonical scale —
  `fast 100ms / normal 200ms / slow 300ms` — and correctly flags that **none of those equals** the
  existing `400ms` (badge-flash) or `600ms` (spin), so adopting the canon would either re-time two
  animations (spin 2× faster, badge-flash 25% faster) or leave them un-tokenized.
- **brief-2** recommends naming **the values already in the file**: `--dur-fast: 200ms`
  (view-transition + row-fade), `--dur-normal: 400ms` (badge-flash), `--dur-slow: 600ms` (spinner).

**Decision: adopt brief-2's mapping (200 / 400 / 600).** Reasoning: **no acceptance criterion
authorizes a visible behaviour change**, and re-timing the spinner and badge-flash is exactly that.
The milestone's stated motivation is "token-referenced durations", which 200/400/600 satisfies
completely while 100/200/300 satisfies only two of four sites. If the canon's literal values are
wanted, that is a separate, visible-change milestone with its own AC. **Constraint carried
forward:** `row-fade-out`'s 200ms must stay numerically in sync with
`index.html:110`'s `hx-swap="outerHTML swap:200ms"` — a comment at `app.css:389-390` says so
explicitly. Place all three in the base `:root` only; duration is not colour-scheme dependent.

### 4.2 — `favicon.svg` will silently drift from a re-derived `--accent`

`server/frontend/static/favicon.svg:2` hardcodes `fill="#1e5b8a"` — today's light `--accent`
exactly. SVG favicons render in browser-tab chrome and **do not inherit page CSS custom
properties** (this repo learned that already; `base.html:11-13` records it). It is **not** in the
roadmap item's `links.code`. If `--accent` moves, the tab keeps the old brand colour. **Needs an
explicit decision, not a drift** — recommend updating it in the same commit and saying so.

### 4.3 — A third live AA failure, found by brief-2, previously unflagged anywhere

`.skip-link:focus-visible` (`app.css:209-221`) sets `color: #fff` **unconditionally** — it is not
`button`/`.button`, so it does **not** inherit the dark-mode text override at `:285`. In dark mode
its ground is `var(--accent)` `#58a6ff`. Measured: **white on `#58a6ff` = 2.526:1**, failing the
4.5:1 floor. It also contradicts the file's own adjacent comment claiming "~3.1:1" — that hand-typed
number is ~20% wrong, which is a second independent instance of exactly the failure mode AC #5
exists to close. **In scope for m6 by AC #3's own terms** (the skip-link ground is role 4 and must
be re-verified). Fix by extending the mode-conditional on-accent text pattern to the skip-link.

### 4.4 — The app.css line cap needs its 4th consecutive raise

File is at **398 of a 400 cap — 2 lines of headroom**, and 3 new `--dur-*` properties plus this
codebase's convention of 3–10 comment lines per token decision will blow through it. The cap is
pinned in **three** test files that the tests themselves require to move **in lockstep**. Budget for
it; do not discover it at gate time.

### 4.5 — Scope boundary: v0 does NOT fold in the 18 literal sites

Confirmed identical across three independent sources (roadmap AC, `final-report.md`,
`challenge.md`). v0 = re-derive the 8 existing token names + add 3 duration tokens. **v1 (folding
the ~12 greys and the pill literals into tokens) has no milestone id in the roadmap yet** — do not
let m6 quietly absorb it; it is outside m6's AC and would consume the line-cap headroom the
duration tokens already threaten. Also note a pre-existing divergence to leave alone: the dark
`--down` pill's background `#3d1216` is **not** equal to dark `--error-bg` `#2a1a18`.

## 5. Phase 2 path decision

**Estimate: 6–7 files, 270–560 lines** (brief-1 said 5–7 files / 150–350; adding brief-2's
recommended `tests/test_ui_contrast.py` at 120–200 lines pushes both up).

**→ DELEGATED.** Trips the rule on two independent counts: **> 5 files** and **300–800 LOC**. It
also carries genuinely novel work for this repo — no OKLCH derivation exists here, and the only
programmatic WCAG calculator is a 20-line helper buried in one test file
(`tests/test_ui_m5_create_remove_in_place.py:518-538`), which brief-1 correctly identifies as the
thing to **extend rather than re-implement**.

## 6. Standing instructions for the implementer

1. **Derive lightness FROM a target contrast ratio, never the reverse.** OKLCH `L` is perceptually
   uniform; WCAG contrast is sRGB relative luminance with hue/chroma-dependent channel mixing
   (green contributes ~10× blue at equal linear intensity). Four evenly-spaced `L` values do **not**
   produce four evenly-spaced WCAG ratios. brief-2 §1 contains a working `solve_L_for_target_ratio`
   binary search — use it.
2. **Reuse the existing WCAG helpers**, don't re-implement the formula a second time.
3. **Fix `tests/test_ui_m5_create_remove_in_place.py:600`'s `canvas = "#0d1117"`** — it duplicates
   dark `--bg` as a Python string and will **silently validate against the wrong ground** if that
   token moves. Parse it from `APP_CSS` instead.
4. **The `0.03928` vs `0.04045` threshold**: WCAG's published figure carries a known sRGB-spec
   carry-over error; the corrected value is `0.04045`. Invisible for any 8-bit channel ≥ 11/255.
   Match whatever the existing in-repo helper uses so the two agree.
5. **Every new number must be machine-derived.** Two AA failures already shipped from hand-computed
   tables, and brief-2 found a third plus a ~20%-wrong comment. Hand-typed contrast numbers are the
   documented root cause this milestone exists to eliminate.

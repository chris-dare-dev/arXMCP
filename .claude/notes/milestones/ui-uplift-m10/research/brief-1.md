---
milestone_id: "ui-uplift-m10"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — ui-uplift-m10

Measured against the worktree snapshot
`/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/agent-a48523893a61081b2`,
2026-08-04. Every count below was produced by running the real extractor /
regexes over these files, not read off a comment.

---

## 0. Orchestrator Phase-0 findings — verification verdicts

| Phase-0 claim | Verdict | Evidence |
|---|---|---|
| AC#5 already delivered by m7 | **CONFIRMED** | `app.css:245` — `.status-badge__remediation { font-size: var(--text-meta); }`. Also already in the tabular-nums selector list at `app.css:222`. Not in `_KNOWN_UNSTYLED`. |
| AC#7 is 1-of-9 done; 8 entries remain | **CONFIRMED, exactly 8** | Ran the coverage extractor standalone: 17 emissions, 15 distinct static tokens, **8 unstyled** — `topic-block`, `topic-category`, `topic-description`, `discover-candidate`, `discover-title`, `discover-meta`, `discover-abstract`, `discover-list`. No hidden 9th. |
| `"status-badge--"` may make AC#7 unachievable | **RESOLVED — it does not** | It lives in `_DYNAMIC_MODIFIER_ALLOWLIST`, a *different* dict (`test_ui_class_css_coverage.py:84`). The module docstring calls it "permanent" (`:28-34`). AC#7 names `_KNOWN_UNSTYLED` only. Emptying that dict alone satisfies AC#7 and no test breaks (both self-cleaning tests iterate the dict and pass vacuously on `{}`). |
| AC#8's parenthetical is stale | **CONFIRMED** | Cap is **520** in all three siblings (`test_ui_m3_dark_and_htmx_feedback.py:610`, `test_ui_m4_in_place_add_paper.py:721`, `test_ui_m5_create_remove_in_place.py:831`). `app.css` is **498** lines. Headroom **22**. The AC's rule binds; its numbers do not. |

**Does the AC#5 rule satisfy AC#5's intent, or is it a size pin?** It is a
**pure size pin and nothing else.** `.status-badge__remediation` has exactly one
declaration (`font-size: var(--text-meta)`), landed to fix m7's own critique
M3/M12 (nested `<small>` compounding to ~9.2px). The block still has **no
margin, no line-height, no display, and no colour of its own** — it inherits the
active `.status-badge--*` modifier's colour, which `test_ui_contrast.py:194-198`
records explicitly ("has no rule of its own and inherits the active modifier's
colour on its background — same ratio, second render site"). Structurally it is
a `<br>`-separated multi-line block glued to the bottom of a `min-width: 14ch`
inline-block pill. **AC#5's letter is met today; its intent — "this block is
styled" — is not.** Recommend m10 either extend it (a `display: block` +
top-margin + `line-height`) or record an explicit "size pin is sufficient"
refusal. Silence here will read as scope evasion to a Phase-3 critic.

---

## 1. The exact HTML the Discover panel emits

`server/routes/notebooks.py::_discover_results_fragment` — **lines 705-753**
(the roadmap's `705-753` citation is accurate; the `_KNOWN_UNSTYLED` per-class
line numbers `731/732/733/735/748` are off by up to 2 because adjacent
f-strings fold into one AST node — the extractor reports `731` and `746`).

### Element tree, empty case

```html
<div id="discover-results" aria-live="polite" aria-atomic="true">
  <p class="empty">No new candidates found for this topic.</p>
</div>
```

### Element tree, populated case

```html
<div id="discover-results" aria-live="polite" aria-atomic="true">
  <p class="hint">{N} new candidate(s) — results are not saved; click Discover to re-run.</p>
  <ul class="discover-list">
    <li class="discover-candidate">
      <p class="discover-title">{title | "—"}</p>
      <p class="discover-meta"><code>{paper_id}</code> · <time>{submitted_date}</time></p>
      <p class="discover-abstract">{abstract_head}</p>
      <form hx-post="/ui/api/notebooks/{slug}/papers"
            hx-target="#papers-tbody" hx-swap="beforeend"
            hx-disabled-elt="find button">
        <input type="hidden" name="arxiv_url" value="https://arxiv.org/abs/{paper_id}">
        <button type="submit">Add</button>
      </form>
    </li>
    ...
  </ul>
</div>
```

Notes that change the CSS:

- `.empty` and `.hint` are **already styled** (`app.css:65`, `app.css:71`) — the
  panel is not wholly unstyled, only the five list classes are.
- The template's initial (pre-run) state is `notebook_detail.html:180-182`:
  the same `#discover-results` div holding `<p class="hint">No discovery run
  yet — click Discover above.</p>`. Three distinct states share the container.
- **`app.css` contains no `ul`, `ol` or `li` rule of any kind** (verified by
  full read). `.discover-list` therefore renders at the UA default:
  `list-style: disc`, `margin: 1em 0`, `padding-inline-start: 40px`. That
  40px indent and the disc bullets are the "bare bulleted list with default
  browser margins" the brief names.
- Each `<li>` contains an **inline `<form>` with a submit button**. Any padding /
  border on `.discover-candidate` must account for a ~32px-tall button as the
  last flow child, and the `.discover-*` rules must not fight
  `button, .button` (`app.css:113`).
- `input[name="arxiv_url"] { font-family: var(--mono) }` (`app.css:95`) matches
  the hidden input in this form. Inert (hidden), but worth knowing before a
  critic "finds" it.
- The `<time>` carries **no `datetime` attribute**. That is consistent with
  every other `<time>` in the console (`index.html:92`,
  `notebook_detail.html:50,70,333`, `notebooks.py:2032,2091,2371,2380`) — do
  not "fix" it here as a drive-by.

### What the arXiv Atom driver actually supplies — AC#4's hinge

Chain: `_discover_results_fragment` ← `discover_for_notebook_async`
(`tools/discover_for_notebook.py:65-124`) ← `fetch_candidates`
(`tools/_arxiv_api.py:452`) ← `parse_atom_feed` (`tools/_arxiv_api.py:162`).

`DiscoveryCandidate` (`tools/discover_for_notebook.py:41-52`) carries **exactly
four fields**: `paper_id`, `title`, `abstract_head`, `submitted_date`. The
upstream `Candidate` (`tools/_arxiv_api.py:72-89`) also parses `submitted_year`,
`n_authors` and `primary_category` — **all three are dropped** at the
`DiscoveryCandidate(...)` construction (`discover_for_notebook.py:116-121`).

The query is built at `_arxiv_api.py:122-159`:

```python
search_query = f"cat:{category}"          # + ' AND abs:"<phrase>"' when the notebook has a description
params = {..., "sortBy": "submittedDate", "sortOrder": "descending"}
```

**Therefore, for AC#4:**

1. **There is no relevance score anywhere in the pipeline.** arXiv returns a
   boolean match; the ordering is *submission recency*, explicitly not
   relevance. `discover_for_notebook.py:110-111` says so in as many words
   ("keeps the arXiv submittedDate-descending ranking").
2. The only *true* basis facts are **panel-level, not per-candidate**: every
   row matched `cat:<discovery_category>` AND (when a description is set) the
   `abs:"<phrase>"` clause. Those two values are already displayed on the same
   page in `#topic-block`.
3. A per-candidate "why this matched" line would have to be **manufactured**.
   Even `primary_category` — the nearest honest per-row datum — is not
   available in the fragment without widening `DiscoveryCandidate`, which is a
   driver change outside a CSS milestone, and it would still be a filter echo,
   not relevance.
4. **Recommendation: ship no relevance line.** If the implementer wants to
   improve the panel's honesty within scope, the cheapest true statement is
   *panel-level*: amend the existing `.hint` copy to name the category + phrase
   the run used. That is one string edit, needs no new class, and stays inside
   invariant I-1 (operational honesty).

### One finding the ACs do not cover but the styling depends on

**`abstract_head` is the FULL abstract, not a head.** `_arxiv_api.py:210` is
`abstract_head = " ".join(summary.split())` — whitespace-normalised, never
truncated. The only truncation in the codebase is `[:120]` inside
`Candidate.as_tsv_row` (`:98`), a CLI path the console never uses. So
`.discover-abstract` renders a complete arXiv abstract — routinely 800-1500
characters — per candidate, and `discover_for_notebook_async`'s default is
`max_results=200`. Left unclamped, "give it a bibliography hierarchy" produces
a page of solid prose in which the title/meta hierarchy is invisible. This is
the single largest visual decision in the milestone and no AC names it.
If the implementer clamps it, `-webkit-line-clamp` (with
`display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden`) is the
only cross-engine tool — **but this repo runs a Baseline-*Widely*-only bar**
(m6 refused `light-dark()`, m7 refused `text-wrap: balance`, and
`test_ui_m7_type_scale.py:474` enforces the latter as a test). Confirm the
Baseline status before using it; a `max-height` + `overflow: hidden` fallback
needs no Baseline argument.

## 2. The topic fragment

`server/routes/notebooks.py::_topic_fragment` — **lines 605-625** (the emitting
literal is `:621-623`, matching the roadmap):

```html
<div class="topic-block" id="topic-block" aria-live="polite">
  <p class="topic-category">Discovery category: <code>{category | "—"}</code></p>
  <p class="topic-description">{description | "—"}</p>
</div>
```

**This markup is duplicated, byte-for-byte, in
`server/frontend/templates/notebook_detail.html:116-118`** — the Python
fragment is the htmx `outerHTML` re-render of the Jinja original. The classes
are therefore emitted from **two** sources; the coverage test only scans
`server/routes/`, but the CSS must obviously serve both. There is no drift
between them today; keep it that way (this is the exact defect class m7's
M-series found in `_paper_row_html` vs the papers table).

- `.topic-category` holds an authored label plus a `<code>` — the `<code>`
  already gets `--mono` + `--text-small` + tabular-nums from `app.css:200,222`.
- `.topic-description` is **prose** (free-text operator keywords,
  `maxlength=512`). `TestRectifyProseStaysSans` (`test_ui_m7_type_scale.py:592`)
  exists precisely because m7 put prose in the mono voice once already. **Do not
  give `.topic-description` `--mono`.**
- Both `<p>` carry UA `margin: 1em 0`; the container sits directly under a
  `.hint` paragraph inside `<section class="card">`, so the vertical rhythm is
  currently three unrelated default margins stacked.

## 3. Type-scale token inventory — consume, do not re-author

All tokens live in **`server/frontend/static/tokens.css`** (157 lines, own
200-line bound, structurally guarded to contain `:root` blocks only —
`TestTokensCssSplit`). `app.css` **must not declare a custom property**:
`test_no_token_is_declared_in_the_rule_sheet` fails on any `--x:` at line start.
Every `var(--x)` in `app.css` must resolve to a name declared here
(`test_every_var_reference_resolves_to_a_declared_token`).

**Complete inventory (17 names):**

| Token | Value (light) | Value (dark) | Notes |
|---|---|---|---|
| `color-scheme` | `light dark` | — | not a token but declared in the same block |
| `--fg` | `oklch(22.842% 0.014 250)` | `oklch(89.089% 0.008 250)` | 16.0:1 / 14.0:1 on `--bg` |
| `--bg` | `oklch(98% 0.004 250)` | `oklch(16% 0.014 250)` | page canvas anchor |
| `--card-bg` | `oklch(99% 0.004 250)` | `oklch(21% 0.016 250)` | **the discover panel's ground** |
| `--border` | `oklch(62.984% 0.018 250)` | `oklch(52.923% 0.02 250)` | 3.30:1 / 3.35:1 — SC 1.4.11 |
| `--accent` | `oklch(47.863% 0.115 250)` | `oklch(69.761% 0.13 250)` | five roles, all registered |
| `--danger` | `oklch(52.018% 0.165 28)` | `oklch(69.137% 0.17 28)` | |
| `--error-bg` | `oklch(96% 0.015 28)` | `oklch(24% 0.04 28)` | |
| `--mono` | `ui-monospace, "SF Mono", Menlo, Consolas, monospace` | same | not mode-dependent |
| `--dur-fast` | `200ms` | same | **pinned**; coupled to `hx-swap="…swap:200ms"` |
| `--dur-normal` | `400ms` | same | |
| `--dur-slow` | `600ms` | same | |
| **`--text-meta`** | `0.6875rem` (11px) | same | micro-caps column meta |
| **`--text-small`** | `0.8125rem` (13px) | same | labels, captions, identifiers, controls |
| **`--text-body`** | `1rem` (16px) | same | |
| **`--text-section`** | `1.25rem` (20px) | same | 1.25x over body; currently only `.card h2` |
| **`--text-title`** | `clamp(1.5rem, 4vw + 0.5rem, 2.25rem)` | same | **BRAND step** — `header h1` only |
| `--tracking-meta` | `0.06em` | same | must ship together with `text-transform: uppercase` |

**m7's M14 instruction, verbatim**
(`.claude/notes/milestones/ui-uplift-m7/rectify/summary.md:85-87`):

> **M14** — recorded, which is what the finding asked: the `discover-*` panel
> must consume this scale rather than author sizes when `ui-uplift-m10` picks
> up that debt.

Hard constraints that follow:

- **No `font-size` literal.** `--text-section` for the title,
  `--text-small`/`--text-meta` for meta and abstract. m10 has zero mandate to
  add a scale step and `tokens.css` is the only place one could go.
- **Do not reach for `--text-title`.** `tokens.css:118-127` records it as a
  *brand* step whose sole consumer is `header h1`; re-homing it is
  `ui-uplift-m12`'s remit.
- **`letter-spacing` may only be `var(--tracking-meta)`**
  (`test_letter_spacing_only_appears_via_the_token`), and if the implementer
  reaches for `text-transform: uppercase` on the meta line, **that fails**:
  `test_micro_caps_role_never_lands_on_an_identifier` asserts every uppercase
  selector `== "th"`, and the meta line is an identifier surface.

## 4. AC#2 — the tabular-nums scope is now a DERIVED guard

`tests/test_ui_m7_type_scale.py:647-683`, `TestRectifyTabularNumsScope`.

```python
def _selectors_with(decl):        # comma-split selector strings, exact match
    for sel, body in _re.findall(r"([^{}]+)\{([^}]*)\}", APP_CSS_NO_COMMENTS): ...

def test_every_mono_surface_inherits_tabular_nums():
    missing = sorted(self._selectors_with("font-family: var(--mono)")
                     - self._selectors_with("font-variant-numeric: tabular-nums"))
    assert not missing

def test_the_tabular_rule_is_still_a_single_declaration():
    assert len(re.findall(r"font-variant-numeric:\s*tabular-nums", APP_CSS_NO_COMMENTS)) == 1
```

Live sets, measured now:

- mono (7): `.status-badge`, `code`, `time`, `pre.error`,
  `input[name="slug"]`, `input[name="paper_id"]`, `input[name="arxiv_url"]`
- tabular (9): those 7 + `.status-badge__remediation` + `dl.meta dd`
- `mono - tabular` = `[]`; tabular declaration count = 1. Green today.

**The precise edit AC#2 requires**, and it is two edits or the suite goes red:

1. Add `font-family: var(--mono)` (plus the size token) to a new
   `.discover-meta` rule.
2. Add the **identical selector string** `.discover-meta` to the existing
   single tabular rule at **`app.css:222-223`**. Appending it to the second
   selector line keeps that line at ~83 chars, so this costs **zero extra
   lines**. Do **not** author a second `font-variant-numeric` rule —
   `test_the_tabular_rule_is_still_a_single_declaration` and
   `test_tabular_scope_is_one_rule_covering_code_and_time`
   (`test_ui_m7_type_scale.py:303`) both fail on two.

Two traps in that guard:

- The comparison is on **exact selector strings**. Writing
  `.discover-candidate .discover-meta` in one rule and `.discover-meta` in the
  other is a failure, not a match.
- The naive `([^{}]+)\{([^}]*)\}` regex mis-attributes rules nested inside
  `@media`: the captured "selector" for the first nested rule is the `@media`
  prelude. **Never put `font-family: var(--mono)` inside the dark-mode block** —
  it would register as a selector named `@media (prefers-color-scheme: dark)`
  and fail the set difference.

**Honest note on AC#2's value.** `.discover-meta`'s only non-child text is the
`·` separator; the `<code>` and `<time>` inside it already take `--mono`,
`--text-small` and tabular-nums from `app.css:200,222`. Applying both to
`.discover-meta` is the literal reading of AC#2, costs ~nothing, and makes the
rule self-describing — do it — but do not claim it fixes misaligned digits. It
does not; those were already aligned.

## 5. The coverage test — how `_KNOWN_UNSTYLED` is consumed

`tests/test_ui_class_css_coverage.py` (616 lines, 12 tests).

- **Extraction** is AST-scoped over `server/routes/*.py` (glob, not a hand-list;
  `_route_files():262`), excluding real docstrings, folding f-strings and `+`
  chains, then regexing `class="…"` / `class='…'` out of the reconstructed text.
- **"Has a CSS rule" means a word-bounded `.classname` token ANYWHERE in the
  comment-stripped text of every `*.css` under `server/frontend/static/`** —
  `_css_defines_class():294-313`. It is **not** a selector parser and **not**
  restricted to selector position. The guard is right-side only
  (`(?![\w-])`), so `.discover-meta` will not be satisfied by
  `.discover-meta-extra`, but it *would* be satisfied by the string appearing
  in a `content:` value or a `url()`. Declared in the docstring as
  false-negative-only. **Practical consequence: a bare `.discover-title { }`
  with no declarations would pass this test.** The real bar is the Phase-3
  critique, not this matcher.
- Both `app.css` and `tokens.css` are scanned (`_css_files():278`), so a class
  "styled" from `tokens.css` would pass here while failing
  `TestTokensCssSplit::test_tokens_css_declares_only_root_blocks`. Don't.
- **`_KNOWN_UNSTYLED` is consumed at exactly one place**: `_offenders():349`,
  `if e.token in known_unstyled: continue`. Emptying it re-activates AC1
  coverage for all 8 automatically.
- **The self-cleaning checks** are `TestKnownUnstyledDebtIsSelfCleaning`:
  `test_known_unstyled_entries_are_still_actually_unstyled` (:559) fails the day
  a listed class gains a rule — **so leaving an entry in place while styling it
  is a hard failure, not a warning.** The list must be emptied in the *same*
  commit as the CSS. `test_known_unstyled_entries_are_still_actually_emitted`
  (:514) is the other direction.
- **`_KNOWN_UNSTYLED = {}` breaks nothing.** Both self-cleaning tests iterate
  the dict and pass vacuously; `_offenders` defaults it to `{}` already. The
  only newly-binding thing is AC1 itself, which is the point.
- **Stale prose to fix in the same commit** (m9 deferred M3/M5 to m10): the
  module docstring still says "**9** classes ship today with zero CSS and
  `app.css` is at its **400-line** soft cap" (`:35-37`) — both numbers are wrong
  (8 and 520). `:88` repeats "these **9** classes". `:24-27` claims "`app.css`
  has no bare `.foo { }` rules", which m9's M3 already recorded as false.
- **m9 routed nine more findings here** and none are in m10's ACs: **M2**
  (deferral list has no ratchet/expiry — moot once the list is empty, but the
  failure text at `:355-358` still advertises `_KNOWN_UNSTYLED` as an escape
  hatch), **M3**, **M4** (allow-list pinned to only one of two `status-badge--`
  producers), **M5** (headline claims "every server-emitted class" while
  templates are unscanned), **L1** (route glob is non-recursive), **L2**, **L3**,
  **L4**, **L5** (eight unstyled *template* classes unguarded). Source:
  `.claude/notes/milestones/ui-uplift-m9/rectify/summary.md:39-42`. m10 should
  either close the cheap comment-accuracy ones (M3/M5/L3) alongside the
  docstring fix or state that it is not doing so — a critic will find them.

## 6. AC#3's premise — verified TRUE

- `base.html:56-63` enables it after htmx loads and re-reads the media query on
  `change`: `htmx.config.globalViewTransitions = !mq.matches;` (enabled unless
  `prefers-reduced-motion: reduce`).
- `app.css:478-481` overrides the crossfade duration:
  `::view-transition-old(root), ::view-transition-new(root) { animation-duration: var(--dur-fast) }`
  with `--dur-fast: 200ms` (`tokens.css:60`), inside a
  `prefers-reduced-motion: no-preference` block.
- Both facts are already pinned by tests:
  `test_ui_m4_in_place_add_paper.py:530-583` asserts the rule exists, resolves
  the token, asserts `--dur-fast == "200ms"`, and asserts the override sits
  inside a no-preference block.
- The Discover swap is `hx-post` → `hx-target="#discover-results"` →
  `hx-swap="outerHTML"` (`notebook_detail.html:165-178`). htmx's
  `globalViewTransitions` wraps **every** swap in `document.startViewTransition`,
  so this swap takes the root crossfade. **AC#3 is guarding against something
  real.**

Two riders:

- **Nothing in the test suite currently forbids a new keyframe.** AC#3 is a
  design constraint with no guard. If m10 wants it to bind, it needs a new
  derived test (e.g. "no `@keyframes` name other than the three that exist" —
  `spin`, `badge-flash`, `row-fade-out`).
- The `::view-transition-*(root)` override only covers the **default `root`
  group**. Giving `#discover-results` a `view-transition-name` would create a
  separate group outside that duration override — a second way to violate AC#3's
  spirit without adding a keyframe.

## 7. The line budget — plainly

- `app.css` = **498** lines; cap = **520**; headroom = **22**.
- Measured composition of the existing file: **249 comment / 219 code / 30 blank
  = 1.14 comment lines per code line.** That ratio is the repo's own standard,
  and it is enforced culturally, not by a test — m7's rectify records the
  failure mode verbatim: *"my first attempt to fit inside it was to delete
  rationale, which is the wrong trade in a repo that treats per-token provenance
  as the deliverable"* and *"Two lines of headroom is not a budget."*
- Minimum plausible spend: **8 rules** (one line each if densely written)
  + **0** for the tabular extension (fits on the existing line)
  + **1** if any hardcoded grey needs a dark-mode remap
  = **9 code lines**, leaving 13 for comments = a ratio of 1.44. That *does* fit.
- Realistic spend: a multi-declaration `.discover-candidate` (padding + hairline
  separator), a clamped `.discover-abstract` (4 declarations for
  `-webkit-line-clamp`), a `.discover-list` reset, the `.topic-*` trio, plus two
  rationale blocks at the file's own standard, plus the AC#4 refusal recorded in
  a comment (this repo always writes refusals down — `tokens.css:101-106`,
  `app.css:99-105`) = **26-35 lines**.

**Verdict: 22 lines does not fit the work as specified.** AC#8's lockstep raise
is **required, not optional**, and it should be step one of the milestone rather
than a cleanup at the end — that is the exact sequencing lesson m7's rectify
recorded. Two things make it non-negotiable:

1. **The tokens.css split is spent.** `test_ui_m3_dark_and_htmx_feedback.py:585-596`
   says so in the test body: *"Splitting is therefore no longer available as a
   future escape hatch for THIS cap — it has been spent. A future milestone that
   needs more room argues for a raise on the merits."*
2. **All three siblings must move together and each has bespoke prose.** The
   cap literal `520` appears at `test_ui_m3_dark_and_htmx_feedback.py:610`,
   `test_ui_m4_in_place_add_paper.py:721-722`,
   `test_ui_m5_create_remove_in_place.py:831-832`, plus prose occurrences at
   `:598,606`, `:709,717`, `:808,819,827`. m7's rectify recorded the trap: a
   blanket find-and-replace **falsified the historical comments** ("m6: 400 →
   480" briefly read "400 → 520"). Edit the policy numbers, leave the history
   alone.

## 8. Affected files — one-line roles

| File | Role in m10 |
|---|---|
| `server/frontend/static/app.css` | **The whole deliverable.** 8 new rules + 1 selector added to the tabular rule at `:222-223`. 498/520. |
| `server/frontend/static/tokens.css` | **Read-only for m10.** Token inventory §3. Adding a token here needs its own justification and is not in any AC. |
| `server/routes/notebooks.py:605-625` | Topic fragment — the emitted markup for 3 of the 8 classes. No change expected. |
| `server/routes/notebooks.py:705-753` | Discover fragment — 5 of the 8 classes. Change only if AC#4's honest-hint option is taken. |
| `server/frontend/templates/notebook_detail.html:116-118` | The Jinja twin of the topic fragment. Must not drift from the Python builder. |
| `server/frontend/templates/notebook_detail.html:149-182` | The Discover card + the pre-run `#discover-results` initial state. |
| `server/routes/ui.py:300-337` | Emits `<small class="status-badge__remediation">`. Read to judge AC#5's intent; edit only if the block gains structure. |
| `tests/test_ui_class_css_coverage.py:88-102` | Empty `_KNOWN_UNSTYLED`; fix the stale 9/400 prose in the docstring at `:24-45` and `:88`. |
| `tests/test_ui_m3_dark_and_htmx_feedback.py:585-620` | Cap test 1 of 3. |
| `tests/test_ui_m4_in_place_add_paper.py:680-730` | Cap test 2 of 3. |
| `tests/test_ui_m5_create_remove_in_place.py:807-833` | Cap test 3 of 3. |
| `tests/test_ui_m7_type_scale.py:647-683` | `TestRectifyTabularNumsScope` — the derived guard AC#2 must satisfy. |
| `tests/test_ui_contrast.py:174-184` | The PAIRS grey registry, if a new colour literal is introduced (§ risk 2). |
| `tools/discover_for_notebook.py`, `tools/_arxiv_api.py` | **Evidence only** for AC#4. Do not modify from a CSS milestone. |

Test surface to re-run: `tests/test_ui_*.py` (11 files),
`tests/test_discover_route.py`, `tests/test_notebook_api.py`. Note
`test_discover_route.py` asserts only `id="discover-results"` (`:107`, `:147`) —
it pins **no** class names, so the fragment markup is free to change if AC#4's
copy option is taken. Packaging needs no change: `*.css` is already covered by
the `package-data` glob and `COPY server/`.

---

## Acceptance criteria the implementer must meet

1. **(roadmap AC#1)** Title, meta and abstract are typographically
   distinguished and candidates are separated. Consume `--text-section` /
   `--text-small` / `--text-meta`; author no size literal. `.discover-list`
   needs a list reset (no `ul` rule exists anywhere today). Separation should be
   a **hairline rule**, not a box — the uplift's own direction D-1 is "deleting
   the box on a page whose content is a bibliography"
   (`final-report.md:52-62`), and BAN-2 (equal card stack) is on the
   must-remove list.
2. **(roadmap AC#2)** `.discover-meta` gets `font-family: var(--mono)` **and**
   the string `.discover-meta` is appended to the **existing single**
   `font-variant-numeric: tabular-nums` selector list at `app.css:222-223`.
   Both, exact-string, or `TestRectifyTabularNumsScope` fails. Never a second
   tabular declaration; never inside an `@media` block.
3. **(roadmap AC#3)** No fade-in keyframe. Premise verified true (§6). Also do
   not give `#discover-results` a `view-transition-name` — that escapes the
   200ms root override the same way a keyframe would.
4. **(roadmap AC#4)** Ship **no** per-candidate relevance line. The driver
   supplies four fields, no score, and sorts by `submittedDate descending`
   (§1). The only honest option in scope is a **panel-level** hint naming the
   category + phrase the run used. Record the refusal in a CSS comment; this
   repo writes refusals down.
5. **(roadmap AC#5 + AC#6)** `.status-badge__remediation` already has a rule
   (`app.css:245`) — either extend it beyond the size pin or record why a size
   pin is sufficient; do not silently claim AC#5 on m7's work. `.topic-block`,
   `.topic-category`, `.topic-description` each get a real rule. Keep
   `.topic-description` in the **sans** voice (it is prose;
   `TestRectifyProseStaysSans` exists because m7 got this wrong once).
6. **(roadmap AC#7)** `_KNOWN_UNSTYLED = {}` **in the same commit as the CSS** —
   `test_known_unstyled_entries_are_still_actually_unstyled` fails the moment a
   listed class gains a rule. `_DYNAMIC_MODIFIER_ALLOWLIST` is a different dict
   and stays. Fix the docstring's stale "9 classes" / "400-line soft cap" prose
   while you are in the file.
7. **(roadmap AC#8)** Raise the cap deliberately in all three sibling tests in
   the same commit — **required, not contingent** (§7). Edit the policy number,
   not the historical "400 → 480" statements. Do not buy headroom by deleting
   rationale.

---

## Risks and open questions

1. **The abstract is the whole abstract.** `abstract_head` is never truncated
   (§1). Unclamped, the bibliography hierarchy the milestone is buying is
   swamped on the first render. This is the biggest visual risk and **no AC
   covers it**. Open question for the general researcher: is
   `-webkit-line-clamp` (with `display: -webkit-box`) Baseline **Widely**
   Available? The repo bar is Widely-only and is test-enforced for
   `text-wrap`. If it is not Widely, `max-height` + `overflow: hidden` is the
   fallback that needs no argument.
2. **A new colour literal drags in the contrast registry — and the dark-mode
   remap is hand-maintained.** If `.discover-meta` takes a muted grey, the
   panel's ground is `--card-bg` (it is inside `<section class="card">`), and
   `#555` on `--card-bg` is **already registered** as `.card .hint #555`
   (`test_ui_contrast.py:177`) — reusing that exact value adds no new pair.
   But the light greys are remapped for dark mode by a **hand-listed** rule at
   `app.css:379-382`, and `test_dark_block_remaps_tertiary_text_greys`
   (`test_ui_m3_dark_and_htmx_feedback.py:203-229`) only checks that seven
   *named* selectors are present — it will **not** notice a new grey selector
   that was never added. A `.discover-meta { color: #555 }` with no dark-mode
   remap ships a live SC 1.4.3 failure that the whole suite passes. Safest
   route: inherit `--fg` and carry the hierarchy with size alone, or reuse
   `#555`/`#b3b9c0` **and** join the dark remap rule.
3. **`_KNOWN_UNSTYLED` empty is the finish line for `server/routes/` only.**
   m9's M5/L5 record that **templates are never scanned** and that eight
   unstyled *template* classes remain untracked. AC#7's "the BAN-R2 coverage
   policy binds unconditionally" is therefore true of the Python fragment
   builders and false of the Jinja templates. If m10 claims the epic's finish
   line, it should say which half it closed — a critic reading the module
   docstring's own headline ("every server-emitted class") will not miss this.
4. **AC#3 has no guard.** Nothing in the suite forbids a fourth keyframe. If
   the milestone wants AC#3 to bind for the next milestone rather than just for
   this one, it needs a derived test; otherwise the AC is satisfied by review
   only and evaporates on the next CSS change.
5. **The three cap tests each carry bespoke historical prose.** m7's rectify
   recorded that a blanket `480` → `520` replace falsified history in the same
   files. A blanket `520` → `<new>` will do it again. Twelve occurrences across
   the three files (`:598,606,610` / `:709,717,721,722` / `:808,819,827,831,832`);
   only the assertion literal and the "raised X → Y" line for *this* milestone
   should change.

---
milestone_id: "ui-uplift-m9"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — ui-uplift-m9

## Affected files / context

### 1. Every class-literal emission site in `server/routes/` (and verification of the brief's claim)

`server/routes/` has exactly 4 files: `debug.py` (65 lines), `__init__.py` (15 lines),
`notebooks.py` (2639 lines), `ui.py` (629 lines). A repo-wide grep for `class="` confirms
`debug.py` and `__init__.py` emit no HTML at all (JSON-only). A grep of the whole `server/`
tree (not just `routes/`) for `class="` returns **only** `notebooks.py` and `ui.py` — no
other module under `server/` builds an HTML fragment. So "the fragments are f-strings in
server/routes/" is correct as far as *which .py files* hold emissions.

All 16 real emission sites (every one is inside a Python `str`/f-string literal that is part
of a function's `return`, never a bare module-level constant):

| File:line | Function | Class literal(s) | Shape |
|---|---|---|---|
| `server/routes/ui.py:289` | `ui_status_badge` | `status-badge status-badge--{css}` | f-string, **one dynamic suffix** |
| `server/routes/ui.py:336` | `_build_remediation_block` | `status-badge__remediation` | f-string, static |
| `server/routes/notebooks.py:556` | `_display_name_fragment` | `display-name` | f-string, static |
| `server/routes/notebooks.py:621` | `_topic_fragment` | `topic-block` | plain string, static |
| `server/routes/notebooks.py:622` | `_topic_fragment` | `topic-category` | f-string, static |
| `server/routes/notebooks.py:623` | `_topic_fragment` | `topic-description` | f-string, static |
| `server/routes/notebooks.py:722` | `_discover_results_fragment` | `empty` | plain string, static |
| `server/routes/notebooks.py:731` | `_discover_results_fragment` | `discover-candidate` | plain string, static |
| `server/routes/notebooks.py:732` | `_discover_results_fragment` | `discover-title` | f-string, static |
| `server/routes/notebooks.py:733` | `_discover_results_fragment` | `discover-meta` | f-string, static |
| `server/routes/notebooks.py:735` | `_discover_results_fragment` | `discover-abstract` | f-string, static |
| `server/routes/notebooks.py:746` | `_discover_results_fragment` | `hint` | f-string, static |
| `server/routes/notebooks.py:748` | `_discover_results_fragment` | `discover-list` | f-string, static |
| `server/routes/notebooks.py:2016` | `_paper_row_html` | `hint` (2nd site) | plain string, static |
| `server/routes/notebooks.py:2085` | `_notebook_row_html` | `button` | f-string, static |
| `server/routes/notebooks.py:2386` | `_ingest_status_fragment` | `error` | f-string, static |

**Only one dynamic family exists**: `status-badge--{css}` at `ui.py:289`. Every other site is
a fully static class string — verified by reading every match; none of the other 14 sites has
a `{...}` interpolation inside the `class="..."` value itself.

**Where the claim is incomplete — 2 findings:**

- **Jinja2 templates also emit class literals**, some of which exist *only* in the template,
  never in a Python f-string: `server/frontend/templates/notebook_detail.html:31`
  (`class="rename-form"`), `:82` (`class="notebook-actions"`), `:119` (`class="topic-form"`).
  These three plus the template's own `:109` occurrence of `topic-block` (which duplicates the
  Python-emitted one at `notebooks.py:621`) were found and named by the source current-state
  critic audit as finding **L2** (`.claude/notes/frontend-uplifts/2026q3-ui-uplift/discover/current-state-critic-brief.md:410-418`,
  LOW severity, "code-hygiene observation, not a user-facing gap"). AC1 and the epic's own
  `links.code` (`plans/ui-uplift/roadmap.yaml:135`: `server/routes/notebooks.py`,
  `server/routes/ui.py`, `server/frontend/static/app.css` — templates NOT listed) both scope
  strictly to `server/routes/`, so this reads as a **deliberate, already-made** scope decision,
  not an oversight — but it means `rename-form` / `notebook-actions` / `topic-form` will never
  be checked by a test built to AC1's literal wording.
- **A docstring inside `server/routes/notebooks.py` contains a literal `class="..."` string as
  prose, not as an emission.** `_paper_row_html`'s docstring at line 1985 reads: `cell renders
  the m10-rect-F6 disabled-look `` <span class="hint"> `` so the operator sees...` — this is
  inside a triple-quoted docstring describing rendered output, not a return value. A whole-file
  **regex** scan (the brief's own words: "a regex over emitted class literals") would match this
  line exactly like a real emission. It is harmless today (`hint` already has CSS — see below)
  but is a live, concrete instance of the false-positive class test_assert_ban.py's own
  docstring explicitly warns about for a structurally identical problem ("a regex over source
  would... fire on the word inside strings, comments and docstrings" —
  `tests/test_assert_ban.py:68-70`).

### 2. The stylesheet

Exactly **one** CSS file exists: `server/frontend/static/app.css` (399 lines). Confirmed via
glob of `server/frontend/static/*` — the only other files there are `VENDORED.md`,
`favicon.svg`, `htmx.min.js`, `json-enc.js` (no `.css` anywhere else in the repo's shipped
tree). So "matching selector exists in app.css" has no multi-file resolution question.

Selector shapes actually present in the file (a parser/regex needs to handle all of these):

- **Bare element**: `body`, `header`, `table`, `label` (app.css:23, 42, 130, 69)
- **Bare class**: none exist standalone today — every class-based selector in the file is
  compound or grouped (see below); a checker cannot assume `.foo { }` will appear on its own line
- **Compound, class-only, space-descendant**: `.card .note`, `.card .empty`, `.card .display-name`,
  `.card .hint` (app.css:65, 66, 67, 62) — these are how `display-name`, `empty`, `hint` get
  their coverage; the class name is the SECOND token, not the first
- **Compound, element+class, no combinator**: `pre.error` (app.css:159) — this is how `error`
  is covered
- **Grouped/comma-separated selector lists**: `button, .button` (app.css:103) — covers
  `button`; `time, .status-badge, dl.meta dd, td code` (app.css:155); `form.htmx-request
  button[type="submit"], button.htmx-request, .button.htmx-request` (app.css:330-332)
- **Pseudo-class / pseudo-element suffixed**: `tbody tr:hover` (app.css:139), `button.danger.htmx-request:focus-visible`
  (app.css:343), `form.htmx-request button[type="submit"]::after` (app.css:346),
  `.status-badge.htmx-settling` (app.css:373), `tr.htmx-swapping` (app.css:391)
- **Attribute selectors**: `input[type="text"]` (app.css:76), `[tabindex]:focus-visible` (app.css:233)
- **Nested inside `@media`**: the entire dark-mode remap (`@media (prefers-color-scheme: dark)`,
  app.css:267-319) redeclares `.status-badge--ok/warn/ops-warn/down` at app.css:314-317, and the
  motion/htmx-state rules live inside two separate `@media (prefers-reduced-motion:
  no-preference)` blocks (app.css:345-361 and 372-397)
- `:root { }` custom-property block and the universal `*` selector are present but carry no
  class tokens and are irrelevant to this check

**Implication for the derived test**: a check needs to find `.classname` as a *substring token*
anywhere in the file text — inside a descendant chain, a comma list, a compound
element+class pair, or an `@media` block — not require the class to appear as a standalone
top-level rule. A word-boundary match (the class name not immediately followed by another
identifier character, so `.error` doesn't accidentally match inside a hypothetical
`.error-detail`) is the right level of rigor; nothing in this file needs a full CSS-grammar
parser, mirroring how both named precedent tests use *lightweight* derivation (AST for Python,
`fnmatch` glob matching for filenames) rather than a full parser for their respective domains.

### 3. The dynamic status-badge modifier family (AC2)

Generated at **`server/routes/ui.py:289`**:
`f'<span id="status-badge" class="status-badge status-badge--{css}" ...'`
inside `ui_status_badge`. `css` comes from `_classify_status_badge(report)`
(`ui.py:191-229`), which returns exactly these `(label, css)` pairs:

- `("DOWN", "down")` — `ui.py:211`
- `("READY", "ok")` — `ui.py:213`
- `("DEGRADED", "warn")` — `ui.py:220` (schema-drift fallback) and again at `ui.py:228` (a
  retrieval check is non-pass)
- `("WARN", "ops-warn")` — `ui.py:229` (final fallback)

Distinct `css` values: **`{ok, warn, down, ops-warn}` — exactly 4.**

**A second, independent occurrence of the identical pattern exists** in the Jinja2 template
`server/frontend/templates/notebook_detail.html:59`:
`<span class="status-badge status-badge--{{ parse_status_css }}">`, where `parse_status_css`
is computed in `server/routes/ui.py:462-464` from the `_PARSE_STATUS_CSS` dict
(`ui.py:114-120`: `{"complete": "ok", "skipped": "ok", "pending": "warn", "running": "warn",
"failed": "down"}`, `.get(..., "warn")` fallback) — value set `{ok, warn, down}`, a subset of
the same 4. This is a second data point for the "incomplete claim" finding in §1: the SAME
dynamic family is emitted once from a Python f-string (routes-scoped, AC1-visible) and once
from a Jinja2 template sourced from a Python-routes constant (not routes-scoped, AC1-invisible)
— worth naming explicitly if the allow-list is meant to also validate the template site.

All 4 modifiers already have CSS: `app.css:190-193` (light) and `app.css:314-317` (dark
redeclaration) — `.status-badge--ok`, `.status-badge--warn`, `.status-badge--ops-warn`,
`.status-badge--down`. So allow-listing `{ok, warn, down, ops-warn}` per AC2 does not mask a
real gap. Note the 4 literal strings are directly readable from `ui.py`'s own source (the
`_classify_status_badge` return tuples and the `_PARSE_STATUS_CSS` dict values) — an
implementer could either hand-type the 4-member allow-list (matching test_assert_ban.py's own
hardcoded-but-self-checked `SHIPPED_TREES` precedent) or derive it mechanically from those two
sources; both satisfy AC2's "explicit allow-list" wording.

### 4. Derived-test precedents (house pattern)

**`tests/test_assert_ban.py`** (151 lines) — the closer structural analog:

- Hardcodes `SHIPPED_TREES = ("server", "ingest", "tools", "shim", "ops")`, but immediately
  self-checks it is not stale: `test_shipped_trees_are_actually_scanned` asserts `len(files) >
  50` and that the on-disk top-level dirs found equal `SHIPPED_TREES` exactly — "guard the
  guard" so a typo'd or drifted config can't make every other assertion vacuously true.
- Walks the tree via `root.rglob("*.py")`, filtering `__pycache__`.
- Extraction is **`ast.parse` + `ast.walk`**, collecting `isinstance(node, ast.Assert)` — AST,
  not regex, specifically because (per its own docstring, lines 68-70) "a regex over source
  would both miss continuation-line forms and fire on the word inside strings, comments and
  docstrings." This is the exact hazard found live in §1 above for `class="..."` inside a
  docstring.
- Collects every offender into a list of `f"{rel}:{lineno}"` strings, then a single
  `assert not offenders, <one message naming all of them + the fix instruction>` — not one
  assert per offender.
- Additionally pins the *enforcement mechanism itself* (`TestRuffEnforcesTheBan` reads
  `pyproject.toml`'s `[tool.ruff.lint]` and asserts `S101` is selected and only `tests/**` is
  exempt) so the policy can't be silently weakened from config alone.
- `REPO_ROOT = Path(__file__).resolve().parent.parent`, module-level constant.

**`tests/test_wheel_packaging.py`** (418 lines) — the looser-parsing analog:

- Derives its check from `pyproject.toml` (not a hardcoded list) via
  `_include_patterns`/`_shipped_trees` helpers.
- Walks via `root.rglob("*")`, explicit `_SKIP_DIRS` and a `_NOT_SHIPPED_FILENAMES` allow-list
  (`{"README.md", "CLAUDE.md"}`) — the closest existing precedent for AC2's "explicit
  allow-list" requirement.
- Matching is **`fnmatch.fnmatch(path.name, glob)`** — string/glob matching, not a real
  packaging-format parser — establishing that lightweight matching (not a full grammar parser)
  is the repo's accepted rigor level for this class of test.
- Collects all unmatched files into one list, one `assert not unmatched, <message listing every
  one + which config key needs a new glob>`.
- Has a second, named-regression layer (`test_the_known_casualties_are_covered`) that pins
  specific known files even though the general derived check already covers them — "the
  derived test above would catch these, but only while the file still exists at that path.
  Naming them keeps the specific bugs pinned even if the tree is reorganized" (lines 202-207).
- Cross-file consistency checks use `re.search(rf"^COPY {re.escape(tree)}/ ", text,
  re.MULTILINE)` against the Dockerfile — plain regex over raw file text is acceptable there
  because `COPY <tree>/` has no docstring/comment-contamination risk the way HTML class
  attributes inside Python docstrings do.
- Expensive/real checks are gated behind `@pytest.mark.requires_wheel_build` (opt-in); the
  static guards run unconditionally on every `make test`.

**Bonus, closer-in-subject-matter precedent not named in the brief but directly relevant:**
`tests/test_ui_a11y_baselines.py:48-56` already establishes the exact idiom this new test would
need for the CSS side: `REPO_ROOT`, `FRONTEND_STATIC = REPO_ROOT / "server" / "frontend" /
"static"`, `FRONTEND_TEMPLATES = REPO_ROOT / "server" / "frontend" / "templates"`, and
module-level `APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")` read
once, checked via plain `assert "..." in APP_CSS` substring tests. It also directly imports
fragment-builder functions (`_display_name_fragment`, `_ingest_status_fragment`) from
`server.routes.notebooks`, confirming these are safely importable outside a running server /
FastAPI app context (no DB or app-state dependency at import time).

### 5. Where the new test should live

Both named precedents are flat files directly under `tests/`, named for *what they check*
(`test_assert_ban.py`, `test_wheel_packaging.py`), not for a milestone or ticket ID — `tests/`
has no subdirectories for this class of guard test (the only subdirs are `tests/eval/` and
`tests/retrieval/`, both test-*data*-driven, unrelated). A name in that same behavioral style —
e.g. something naming "emitted CSS classes have rules" — fits the convention; ticket-style
names (`test_ban_r2.py`, `test_upl7.py`) do not match either precedent's style, and the closest
subject-matter sibling (`tests/test_ui_a11y_baselines.py`) also uses a descriptive, not
ticket-coded, name.

### 6. Vendored / not-the-repo's-to-style classes

htmx (`server/frontend/static/htmx.min.js`, vendored 2.0.10) applies these classes to elements
**client-side at runtime** — they are never written as `class="..."` string literals anywhere
in `server/routes/*.py` or the templates (grep-confirmed: zero `class="htmx-...` occurrences
repo-wide; the templates only reference these classes as CSS *selectors*):

- `.htmx-request` — app.css:330-343 (loading-state opacity/cursor + spinner `::after`)
- `.htmx-settling` — app.css:373 (badge-flash trigger)
- `.htmx-swapping` — app.css:391 (row-fade-out trigger)

Because AC1's check direction is *emitted-class → must-have-CSS* (not the reverse), these never
enter the picture for a test scoped to `server/routes/` — htmx never emits a `class="..."`
Python/template literal, so there is nothing to flag. This only matters if a future
implementation is tempted to also validate the reverse direction (every CSS class selector
traces to an emission site) or widens the scan to raw file text including `hx-on::htmx:...`
attribute names — worth a one-line comment in the implementation but not a design blocker.

---

### Current CSS-coverage state (load-bearing for the implementer, not just descriptive)

Of the 15 distinct static class names enumerated in §1, **9 currently have NO matching
selector in `app.css`** (verified by reading the full 399-line file, not by trusting any prior
audit — see the discrepancy noted below):

- `status-badge__remediation` (`ui.py:336`)
- `topic-block`, `topic-category`, `topic-description` (`notebooks.py:621-623`)
- `discover-candidate`, `discover-title`, `discover-meta`, `discover-abstract`, `discover-list`
  (`notebooks.py:731-748`)

This is not hypothetical rot — it is the **present state of `main`**, and the roadmap's own
sequencing means a literal AC1 implementation would **fail on landing**, not just at some
future regression point:

- `.status-badge__remediation` is the **single highest-severity** finding in the source audit
  (`current-state-critic-brief.md:26-27`: "the ONE load-bearing trust signal... degrades into a
  491px unstyled run-on line"). A repo-wide grep for `remediation` across
  `plans/ui-uplift/roadmap.yaml` returns **zero matches** — no milestone in the 23-item roadmap
  (m1–m23) is scoped to add this rule. `current-state-critic-brief.md:76-80` explains why: it
  shipped as an `onboarding-uplift-m3` AC5 deliverable ("operator sees an actionable hint"),
  and no later milestone picked up the visual pass.
- The 5 `.discover-*` classes' fix is **`ui-uplift-m10`** ("Style the Discover-results candidate
  list", tag `UPL-9`, `plans/ui-uplift/roadmap.yaml:374-394`), targeted `2026-08-20 ->
  2026-08-27` — starting the exact day `ui-uplift-m9` (`2026-08-11 -> 2026-08-20`) is due to
  end. m9 is sequenced **before** its own backlog-closing sibling.
- `synthesis.md:406-407` states the policy candidate's own scope explicitly: *"The standing rule
  — plus its concrete backlog, which is UPL-8/9/10 below."* UPL-8 = `ui-uplift-m4` (done),
  UPL-10 = `ui-uplift-m3` (done) — both already shipped and both already have CSS (`select`/
  `textarea` via `app.css:96-101`; ingest `<pre class="error">` via `app.css:159`, confirmed
  live). UPL-9 = `ui-uplift-m10` (not yet run). **There is no UPL-number/milestone at all for
  `.status-badge__remediation`.**
- The `.topic-*` classes are not in the "four class families" narrative at all. The source
  audit's own **L2** finding (LOW severity, `current-state-critic-brief.md:410-418`) names only
  `topic-block` among "4 unused hook classes" and explicitly **misses** `topic-category` and
  `topic-description` — both verified here (§1) to have zero CSS exactly like `topic-block`.
  This is worth surfacing as a point *in favor* of the policy (a mechanical test would have
  caught what the manual audit missed) but also means the audit is not itself a reliable source
  to hand-code an allow-list from.

## Acceptance criteria the implementer must meet

1. A test under `tests/` extracts every class-literal token from `class="..."` values written
   inside `server/routes/notebooks.py` and `server/routes/ui.py` (verified: the only 2 of 4
   `server/routes/*.py` files with any such literal) and asserts each has a matching selector
   substring in `server/frontend/static/app.css` (399 lines, the repo's only stylesheet).
2. The one dynamic family — `status-badge--{css}` at `ui.py:289`, mirrored by
   `notebook_detail.html:59` sourced from `_PARSE_STATUS_CSS` (`ui.py:114-120`) — is
   allow-listed by its exact, verified 4-member value set `{ok, warn, down, ops-warn}` (sourced
   from `_classify_status_badge`'s return tuples, `ui.py:211/213/220/228/229`), not by a
   wildcard on the `status-badge--` prefix.
3. The check re-derives from the on-disk tree on every run (walks the actual files, parses the
   actual CSS text) rather than pinning today's class inventory as a snapshot — mirroring both
   named precedents, which re-derive rather than hand-list.
4. The extraction method does not treat prose as an emission: `notebooks.py:1985` contains a
   docstring with a literal `class="hint"` substring that is not a return value — a raw
   whole-file regex scan is provably vulnerable to this (harmless today only because `hint`
   already has CSS); an AST-scoped extraction (visiting string/f-string nodes only where they
   are part of an actual expression the function returns/produces, the same discipline
   `test_assert_ban.py` uses for `ast.Assert`) avoids the class of bug entirely.
5. Landing the test green requires an explicit decision about the 9 currently-uncovered classes
   documented above (`status-badge__remediation`, 3× `topic-*`, 5× `discover-*`) — none of the
   3 roadmap ACs for this milestone say to add CSS, but the test cannot both (a) implement AC1
   literally over the current tree and (b) pass on first run unless either minimal CSS ships
   alongside it or those specific classes are excluded with a reasoned, dated allow-list entry
   distinct from the AC2 status-badge allow-list.
6. The selector-matching logic handles the shapes actually present in `app.css` — descendant
   compounds (`.card .hint`), element+class compounds (`pre.error`), comma-separated groups
   (`button, .button`), pseudo-class/element suffixes, and rules nested inside `@media` blocks
   (the dark-mode redeclare of the 4 status-badge modifiers lives at `app.css:314-317` inside
   `@media (prefers-color-scheme: dark)`) — a bare top-level `.foo { }` assumption would miss
   every currently-covered class in this file.
7. Failure output names every offending `file:line` plus the specific class string and states
   the fix ("add a rule for `.foo` to app.css, or add it to the allow-list with a reason") —
   matching both precedents' single-collected-list-then-one-assert pattern rather than one
   assertion per class.

## Risks and open questions

1. **The test will fail at landing unless the 9-class gap above is resolved.** This is the
   dominant open question for Phase 2: ship minimal CSS for `status-badge__remediation` +
   `topic-*` + `discover-*` as part of this milestone (even though none of its 3 ACs mention
   styling), or add a second, explicitly-reasoned allow-list beyond AC2's status-badge one. The
   roadmap sequences the `discover-*` fix to a later milestone (`ui-uplift-m10`) and has no
   milestone at all for `status-badge__remediation` — so "wait for the sibling milestone" is not
   available for at least one of the three families without an explicit exemption.
2. **Scope boundary (already made, worth re-confirming, not re-litigating):** AC1 and the
   epic's `links.code` both name only `server/routes/`, not the Jinja2 templates — so
   `rename-form` / `notebook-actions` / `topic-form` (template-only classes, LOW-severity L2
   finding) stay permanently out of this policy's reach as scoped. Flagging so Phase 2 doesn't
   silently widen scope mid-implementation and Phase 3 doesn't flag the templates as an
   unaddressed gap in *this* milestone.
3. **Regex-over-raw-text vs. AST-node-traversal is a real design fork, not a style nit.** The
   live docstring false-positive at `notebooks.py:1985` is harmless today only by coincidence
   (`hint` already has CSS); the day a docstring illustrates a not-yet-styled class name for
   documentation purposes, a naive text-regex implementation would fail the suite on prose, not
   code. AST traversal restricted to actual return-value string/f-string nodes avoids this
   entirely and is the more defensible choice given the precedent set by `test_assert_ban.py`.
4. **The source audit that seeded this epic under-counted its own findings**
   (`topic-category`/`topic-description` missing from its L2 list even though `topic-block` —
   found in the exact same function, three lines away — was named). Do not treat
   `current-state-critic-brief.md` or `synthesis.md`'s "four class families" framing as an
   exhaustive enumeration to hand-code; the derived test itself is the only reliable inventory,
   which is the whole point of AC3.
5. **The allow-list mechanism chosen for the status-badge family (AC2) and whatever mechanism
   resolves risk #1 above should not collapse into the same generic "skip list."** AC2's
   allow-list is narrow and justified (a dynamic interpolation a static scan structurally cannot
   resolve to a literal). A second allow-list to paper over the pre-existing 9-class gap would
   be exactly the "hand-maintained list that rots" anti-pattern this whole milestone exists to
   replace — if that path is chosen, it should be small, dated/ticket-referenced, and separate
   in the code from AC2's structural allow-list.

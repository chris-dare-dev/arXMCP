---
milestone_id: "ui-uplift-m9"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://docs.python.org/3/library/ast.html"
    sha256: "920c9fa53e60a9f5b6cd275c5b8d1b637a76d6f041871f14c8fcb03ca696b366"
    takeaway: "JoinedStr.values interleaves Constant (literal text chunks) and FormattedValue (interpolated exprs); an f-string with ZERO placeholders is still parsed as JoinedStr, never simplified to a bare Constant — but a non-f-prefixed literal with no {} is parsed as plain Constant, so a checker must walk both node types."
  - url: "https://purgecss.com/safelisting.html"
    sha256: "533a7b5a35ba5c5c64df18e32c88164a40ff3192927e69534daaeda7a095e74b"
    takeaway: "Industry prior art for AC2: PurgeCSS's safelist is an explicit, small, hand-maintained exact-string list precisely because static analysis structurally cannot resolve a dynamically-composed class name — the same shape AC2 asks for, not a novel pattern."
injection_attempts: 0
---

# Research brief (general) — ui-uplift-m9

## A. External-writes enumeration (load-bearing)

`external_writes_required: ["git push origin main"]`

This is a test-authoring milestone (plus, per the risk below, likely a small CSS
addition) with no library/vendor choice, no deploy, no package publish, and no
GitHub issue/PR mutation implied by the brief or its acceptance criteria. Per
CLAUDE.md §4.4/§4.1 (single-user, single-workstation, all work lands on `main`
directly, push is per-event authorization), the sole external write for this
milestone — as for effectively every milestone in this repo — is `git push
origin main`, to be re-confirmed with the user at Phase 4 rather than assumed
from this brief.

## B. Design research

### B1 — Extracting class literals from Python source: regex-over-text vs `ast`

**Recommendation: hybrid — `ast` for source-level isolation, a small regex for
HTML-attribute-level token extraction within the isolated literals.** These are
not mutually exclusive: AST parsing decides *which* string literals are real
candidates (robust, zero false positives from non-code text); a tiny regex then
pulls `class="..."` tokens out of *those* literals' text (simple, and safe once
the candidate set is already narrow).

**Why raw regex-over-file-text is the weaker half on its own**, with concrete
false-positive instances found live in this repo, not hypothetical ones:

- **Docstring prose that quotes real-looking HTML is indistinguishable from
  real emission code by text shape alone.** `server/routes/notebooks.py:1981`
  is an actual docstring line: `` cell renders the m10-rect-F6 disabled-look
  ``<span class="hint">`` `` — this is prose describing behavior, not emitted
  HTML, but it has the exact same `class="..."` shape a checker is looking
  for. It happens to name a class (`hint`) that IS genuinely emitted elsewhere,
  so today it's a silent no-op false positive — but the mechanism is real and
  would silently pass a class that only ever appears in a comment/docstring,
  never in real output. A pure regex over raw file bytes cannot distinguish
  "this text is inside the first statement of a function body as a triple-
  quoted string" (Python's own definition of a docstring) from "this text is
  a real f-string being returned/passed to `HTMLResponse`." `ast` can: the
  same test/discriminator Python's own `ast.get_docstring()` uses — first
  statement of a `FunctionDef`/`Module`/`ClassDef` body being a bare
  `Expr(value=Constant(value=str))` — is a syntactic fact, not a heuristic.
- **The `class` keyword structurally rules out one class of false positive
  the brief worried about** ("a string that looks like a class but is a dict
  key"): `class` is a reserved word in Python, so `class="foo"` (an `=` sign,
  not a `:`) can never appear as real Python syntax (a kwarg, an assignment)
  outside a string literal — a dict key would be `"class": "foo"` (colon),
  not `class="`(equals). Anchoring the pattern on the literal substring
  `class="` (equals, then a quote) already excludes this specific worry
  structurally, independent of regex vs AST.
- **Adjacent string-literal concatenation is an equal-opportunity fragility,
  not a reason to prefer one approach.** Every emitted fragment in this repo
  concatenates several `f'...'`/`'...'` segments inside one `(...)` tuple
  (see `_discover_results_fragment`, `_ingest_status_fragment`). Python folds
  adjacent literals at compile time, *after* `ast.parse()` — so both a raw-
  text regex and an `ast.JoinedStr`/`ast.Constant` walk see each segment as
  independent. This is fine in practice here because every observed
  `class="..."` attribute opens and closes within a *single* segment (never
  split across two adjacent literals) — but note this as a shared, documented
  limitation of either approach, not a differentiator.

**Confirmed API shape** (fetched from the Python docs, source #1 above):
`ast.JoinedStr.values` is a list of `ast.Constant` (literal text) interleaved
with `ast.FormattedValue` (the `{expr}` interpolation, itself carrying
`.value`/`.conversion`/`.format_spec`). An f-string with **zero** placeholders
is *still* `JoinedStr`, never simplified to `Constant` — but this repo's own
source does NOT use an `f` prefix on segments with no `{}` (ruff's `F541`
"f-string without placeholders" is enforced via the already-selected `"F"`
ruleset in `pyproject.toml:349`), so roughly half of the observed class-
bearing literals (e.g. `'<div class="topic-block" ...">'` in
`notebooks.py:621`) are plain `ast.Constant` strings, not `JoinedStr`. **A
correct walker must visit both node types** — restricting to `JoinedStr` only
would silently miss every static (non-interpolated) class literal in the
file, which is most of them.

**Practical extraction shape** (design, not code): walk `server/routes/*.py`
module ASTs; for every `ast.Constant`(str) and `ast.JoinedStr` node that is
*not* in docstring position, reconstruct its literal text (for `JoinedStr`,
concatenate `Constant.value` chunks verbatim and substitute each
`FormattedValue` with a fixed sentinel token); apply a small regex
(`class="([^"]*)"`) to the reconstructed text to pull the attribute value,
then `.split()` on whitespace for individual class tokens. A token containing
the sentinel is "dynamic" (→ B1/AC2 allowlist path); everything else is a
literal class name to check against CSS (→ B2).

**Why not go further and reconstitute full HTML fragments through
`beautifulsoup4`** (already a project dependency, `pyproject.toml:108`, pure-
`html.parser` backend, so it would cost nothing new)? Individual literal
segments are frequently *incomplete* tags by construction (e.g.
`'<li class="discover-candidate">'` alone, closed several segments later) —
feeding fragments-of-tags through a real HTML parser invites auto-closing/
wrapping behavior that adds noise for no benefit once AST has already made
the false-positive surface this narrow. A flat regex on each isolated literal
is simpler and sufficient here.

### B2 — Extracting class selectors from CSS: regex vs a real parser

**`tinycss2` is not in the dependency tree.** Verified by reading
`pyproject.toml` in full (both the `dependencies` list and the `dev` extra,
lines 105–371) — no CSS-parsing library (`tinycss2`, `cssutils`, or any other)
appears anywhere, runtime or dev. Every existing dependency in this file
carries a multi-line justification comment (license, alternatives considered,
pin rationale); introducing one net-new, even dev-only, would need the same
treatment and is disproportionate for what the milestone's own brief text
already anticipates as "a regex over emitted class literals checked against
app.css selectors" — the roadmap author's own framing assumes regex, not a
parser dependency.

**More importantly: this repo already has a working, battle-tested
comment-stripping precedent — reuse it verbatim rather than reinventing it.**
Four existing test files (`tests/test_ui_m2_polish.py:44-47`,
`tests/test_ui_m3_dark_and_htmx_feedback.py`,
`tests/test_ui_m4_in_place_add_paper.py`,
`tests/test_ui_m5_create_remove_in_place.py`) each define:

```
APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
```

with the comment at `test_ui_m2_polish.py:44-46` stating precisely why:
*"so substring checks for rule-text don't accidentally match inline-comment
documentation that REFERENCES a pattern."* This is not a hypothetical
concern — **I independently found a live instance of exactly this hazard in
the current file**: `server/frontend/static/app.css:259-266` is a `/* ... */`
comment (the UPL-8 v0/dark-mode rationale) whose prose literally reads
`` .status-badge--{ok,warn,ops-warn,down} hardcoded colors at
`.status-badge--*` rules above `` — a comment *mentioning* a class-selector-
shaped glob. Today all four concrete names it references genuinely do have
real rules, so it's a latent hazard rather than a live bug, but it is direct,
current proof that scanning `app.css` without stripping comments first would
be scanning attacker-adjacent (well, author-adjacent) prose that can say
anything. **The new derived test's CSS-side extraction must run over
`APP_CSS_NO_COMMENTS`-equivalent text, using this exact regex.**

**Decimal numbers are a non-issue by construction, not by luck.** A class-
token regex like `\.[A-Za-z_-][\w-]*` (dot, then a *non-digit* start
character) cannot match any of the file's many decimal values (`0.4rem`,
`0.01ms`, `1.5` line-height, etc.) because CSS class identifiers cannot start
with a digit and the character immediately after the dot in every decimal in
this file is a digit. No special-casing needed — just don't allow a digit as
the first post-dot character.

**A real residual gap, worth documenting rather than solving with a full
parser:** if the scan runs over the *whole* comment-stripped file (not just
selector-position text), a future declaration *value* containing a dot-letter
sequence — `url(icon.svg)`, `content: ".foo"` — would produce a spurious
"selector" that doesn't really exist. Nothing in the current 398-line file has
this shape (no `url()`, no dot-bearing `content` strings), so it is a latent,
not live, risk. Because it is false-negative-only (it can only make the
*defined-CSS-classes* set look bigger than reality, which can only ever mask
a real gap, never invent a false failure on an innocent commit), a full
nesting-aware selector/declaration-body scanner is disproportionate for this
file today. Recommend documenting the trade-off explicitly in the new test's
docstring (this repo already ships this kind of narrow, named heuristic limit
— e.g. `server/routes/notebooks.py:1521-1544`'s `_PDF_COUNT_RE` comment-
adjacency gap — rather than reaching for a full grammar), with a one-line
note that a nesting-aware `{`/`}` depth-tracking scan is the documented
escalation path if this ever bites.

**Forward-robustness for the CSS side:** don't hardcode `app.css` as the sole
CSS source — glob `server/frontend/static/*.css`. The existing 400-line-cap
tests (see the sequencing risk below) already name a specific, anticipated
escape hatch — splitting into `tokens.css` + `app.css` — and a hardcoded
single-filename check would silently stop covering half the rules the day
that split happens.

### B3 — Known failure modes of "unused CSS"/"undefined class" checks, and which apply here

The classical failure mode in this space is the *reverse* direction: "is this
CSS selector ever used by any HTML/JS" (PurgeCSS, UnCSS, and similar tools).
That direction is notoriously noisy — dynamically-composed classes
(`` `btn-${variant}` ``-style template construction), classes only ever
applied by third-party/vendored JS, defensive/future-proofing rules, and
utility classes referenced in bulk rather than individually all produce false
"unused" flags. **AC1 deliberately asks for the opposite, one-directional
check — "every emitted class has a rule," never "every rule is used" — and
that framing sidesteps most of this noise by construction:**

- **Vendored third-party JS classes (htmx) never appear as Python class
  literals at all**, so they cannot be false positives for a Python→CSS
  check. `.htmx-request`, `.htmx-swapping`, `.htmx-settling` are applied by
  `htmx.min.js` at runtime based on `hx-*` attributes (confirmed:
  `app.css:325-397` styles all three; grep of `server/routes/*.py` shows zero
  occurrences of any of these three literal strings as emitted `class="..."`
  values) — they are real CSS selectors with no matching Python-emitted
  literal, which is exactly the shape a *reverse* ("is this rule used")
  check would flag and this test correctly ignores.
- **State classes applied by JS at runtime** are the same case as the
  htmx bullet above — not emitted server-side, so structurally invisible to
  (and irrelevant for) this one-directional check.
- **Utility-class-framework noise does not apply.** This codebase has no
  Tailwind/utility-class layer — confirmed independently by the
  current-state-critic scan
  (`.claude/notes/frontend-uplifts/2026q3-ui-uplift/discover/current-state-critic-brief.md`
  §H5: "no Tailwind, no shadcn... every class in the templates is a hand-
  named semantic class"). There is no large surface of intentionally-generic,
  individually-unreferenced utility classes to produce noise either
  direction.
- **Dynamically-composed class names are the one real failure mode that DOES
  apply, and it appears exactly once in the current codebase:**
  `server/routes/ui.py:289` — `` f'... class="status-badge status-badge--{css}" ...' ``.
  This is AC2's named case. The confirmed industry-standard answer (source
  #2, PurgeCSS's `safelist`) is precisely what AC2 asks for: an explicit,
  small, hand-maintained list — not a clever pattern-inference scheme,
  because dynamic composition is *structurally* unresolvable by static
  analysis (the concrete value only exists at runtime). See B4 for the
  specific shape recommended here.
- **Jinja2-template-only classes are out of AC1's stated scope, and that
  scoping is a real, if narrow, gap.** `notebook_detail.html` has 4 classes —
  `rename-form`, `notebook-actions`, `topic-block`, `topic-form` — that carry
  no dedicated CSS rule (`current-state-critic-brief.md` §L2, rated LOW: they
  wrap already-styled bare-element children, so nothing visually breaks).
  Three of these four (`rename-form`, `notebook-actions`, `topic-form`) are
  emitted *only* by the Jinja templates, never by any `server/routes/*.py`
  f-string — AC1's literal wording ("class literal emitted by a fragment
  builder in server/routes/") does not reach them, and a test scoped exactly
  as AC1 describes will not catch them. Flagged as an open question below,
  not a design defect — the brief's own wording draws this boundary
  deliberately.

### B4 — Satisfying AC3 ("binds going forward, not just retroactively")

**The single design property that satisfies AC3 is: do not gate extraction on
identifying "which functions are fragment builders."** The seven observed
emitters (`_display_name_fragment`, `_topic_fragment`,
`_discover_results_fragment`, `_paper_row_html`, `_notebook_row_html`,
`_ingest_status_fragment`, `_build_remediation_block`) all happen to follow a
`_*_fragment`/`_*_html` naming convention today, but relying on that name
shape (or any hand-maintained list of "known" function names) is exactly the
"hand-maintained list" the milestone's own summary explicitly rejects, and it
would silently exempt a differently-named function added later. Instead: scan
*every* non-docstring string/f-string literal in every `.py` file under
`server/routes/` for the `class="..."` attribute shape, unconditionally,
regardless of which function contains it or what that function is named. A
brand-new function emitting a brand-new unstyled class is then caught for
free — there is nothing project-specific to keep in sync as new routes are
added, which is the actual mechanism of "cannot regenerate" the milestone
summary asks for.

For the one *known* dynamic case (AC2), the closed-allowlist shape that keeps
AC3's forward-binding property should be a `{static_prefix: frozenset(known
suffixes)}` mapping (not a bare prefix/wildcard match) — `{"status-badge--":
frozenset({"ok", "warn", "ops-warn", "down"})}`, matching the four literal
return values in `_classify_status_badge` (`ui.py:211-229`). The test should
then (a) require every *concatenated* `prefix+suffix` combination still has a
real CSS selector — so this isn't a bypass, it's routing the check through
enumeration instead of literal-matching — and (b) fail if a dynamic class
token's static prefix is *not* a key in the allowlist at all, so a brand-new
dynamic family with zero allowlist entry still fails loudly. **A bare
prefix/wildcard match (e.g., "pass if *any* `.status-badge--*` selector
exists") would NOT satisfy AC3**: a hypothetical fifth, unstyled
`status-badge--info` value added later would silently pass because
`.status-badge--ok` (or any of the other three) already "proves" the prefix
is styled. The one honest, documented residual gap: a *new* concrete suffix
value added to `_classify_status_badge` without a matching allowlist edit is
invisible to any static check on this f-string, because the token as written
in source is always the literal template `status-badge--{css}`, never the
concretized value — this is an inherent limit of static analysis on a
variable interpolation, not a solvable design flaw, and should be stated as
such in the test's own docstring (mirroring this repo's established pattern
of naming, not hiding, a heuristic's edges).

## Acceptance criteria the implementer must meet

1. The test parses `server/routes/*.py` via `ast` (not a bare regex over raw
   file bytes) to isolate every non-docstring string/f-string literal, then
   extracts `class="..."` tokens from each; it fails for any class token with
   no matching `.token`-shaped selector anywhere in the (comment-stripped)
   CSS. (AC1)
2. The dynamic `status-badge--{css}` family is handled via an explicit,
   *closed* allowlist (`{prefix: frozenset(suffixes)}`, not a prefix/wildcard
   match) whose every concatenated value is itself verified against CSS.
   (AC2)
3. Extraction does not gate on a hand-maintained list of "known fragment-
   builder function names" — scanning is name-agnostic across every string
   literal in the target files, so a brand-new function with an unstyled
   class fails the suite without any test-file edit. (AC3)
4. CSS-side selector extraction strips `/* ... */` comments before matching
   — reuse the exact `APP_CSS_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", APP_CSS,
   flags=re.S)` idiom already shipped at `tests/test_ui_m2_polish.py:44-47`
   (and 3 sibling files) rather than reinventing it.
5. Before this test can land green, the ~9 currently-unstyled class literals
   (see the risk below) need matching CSS — and that addition must not push
   `app.css` over the existing 400-line soft cap enforced in lockstep by
   `tests/test_ui_m3_dark_and_htmx_feedback.py`,
   `tests/test_ui_m4_in_place_add_paper.py`, and
   `tests/test_ui_m5_create_remove_in_place.py`.
6. No new runtime or dev dependency: `tinycss2`/`cssutils` are confirmed
   absent from `pyproject.toml` and unneeded — both extraction halves use
   stdlib only (`ast`, `re`, `pathlib`).
7. CSS-file discovery globs `server/frontend/static/*.css` rather than
   hardcoding `app.css`, so the already-named `tokens.css` + `app.css` split
   escape hatch (see the line-cap tests' own comments) doesn't silently break
   the derived check later.

## Risks and open questions

1. **RED-on-landing risk (the most important finding in this brief).** I
   independently verified, by reading `server/routes/notebooks.py`,
   `server/routes/ui.py`, and `server/frontend/static/app.css` end-to-end and
   cross-referencing every class literal against every CSS selector, that 9
   class literals across 3 families are *currently* emitted with **zero**
   matching CSS rule: `topic-block`/`topic-category`/`topic-description`
   (`notebooks.py:621-623`), `discover-candidate`/`discover-title`/
   `discover-meta`/`discover-abstract`/`discover-list`
   (`notebooks.py:731-748`), and `status-badge__remediation` (`ui.py:336`).
   AC1's test, implemented literally, will fail immediately against the tree
   as it stands today. `depends_on: (none)` names no sibling milestone that
   closes this backlog first. Given CLAUDE.md §4.5 ("`make test` must be
   green before pushing"), the implementer almost certainly needs to add
   minimal CSS for these 3 families as an in-scope part of *this* milestone
   — not just author the test. (The current-state-critic brief at
   `.claude/notes/frontend-uplifts/2026q3-ui-uplift/discover/current-state-critic-brief.md`
   §H1/§H3 already sketches concrete "v1 fill-in" CSS for the discover-* and
   remediation families, reusable almost verbatim; no equivalent sketch
   exists yet for topic-*.)
2. **The 400-line `app.css` soft cap will very likely be exceeded by
   whatever CSS closes finding #1.** Confirmed via `wc -l`: the file is
   currently 398 physical lines — 2 lines of headroom under the cap 3 test
   files enforce "in lockstep"
   (`tests/test_ui_m3_dark_and_htmx_feedback.py`,
   `tests/test_ui_m4_in_place_add_paper.py`,
   `tests/test_ui_m5_create_remove_in_place.py`, each with an explicit
   comment that the cap constant must move together across all three). Any
   CSS addition of more than ~2 lines requires either bumping the cap in all
   three files simultaneously or the `tokens.css` split those same comments
   already flag as the named escape hatch — budget for this before writing
   the new derived test, not after.
3. **AC2 allowlist's residual gap is inherent, not a design choice to
   second-guess in review**: a future 5th `_classify_status_badge` return
   value with no matching allowlist edit is invisible to *any* static check
   on an f-string interpolation. Document this explicitly in the new test's
   docstring so a future critic doesn't mistake it for an oversight.
4. **Selector-token extraction over full declaration text (not just selector
   text) carries a latent, currently-inert false-negative risk** — a future
   `url(...)` or dot-bearing `content` string would inflate the "defined CSS
   classes" set. Recommend accepting and documenting this rather than
   building a nesting-aware `{`/`}` depth-tracking scanner, which is
   disproportionate engineering for a 398-line hand-authored file with no
   such values today (see B2).
5. **Scope boundary is real, not just theoretical**: AC1's literal wording
   ("fragment builder in server/routes/") does not, and per the brief's own
   text should not, reach the 3 Jinja-template-only unstyled hook classes
   (`rename-form`, `notebook-actions`, `topic-form` in
   `notebook_detail.html`) the prior critic already catalogued as LOW-
   severity. Worth one line in the implementation summary confirming this is
   an intentional scope line, not a gap discovered too late.

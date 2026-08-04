# Critique (merged) — ui-uplift-m9

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** 0c95720..018bebd
**Diff stats:** 1 files, 520 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): M1->M6, M2->M7, M3->M8, L1->L2, L2->L3, L3->L4, L4->L5

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The derived check is real — I ran it (10 passed, ruff clean, sibling
UI suites still green), and the AC3 synthetic proof genuinely exercises the same
`_extract_emissions_from_source` + `_offenders` machinery the real-repo test uses, so
this is not a self-certifying test. But AC3's forward-binding claim has constructible
bypasses I reproduced: a single-quoted `class='…'` attribute and any literal nested
inside an f-string interpolation are both invisible to the extractor, and the
`_KNOWN_UNSTYLED` list is self-cleaning in only one of the two directions its own
docstring claims. No CRITICALs: the commit is signed (`%G?=G`), carries the mandated
co-author trailer, touches no `roadmap.yaml`, performs no external write (not pushed),
and is test-only.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

A test-only diff that adds a genuinely derived BAN-R2 policy: all 10 tests pass on win32 against the project venv, ruff is clean, no dependency, schema, prompt, or production surface is touched, and the tool-schema and BP1 hash tests still pass unchanged. The three MEDIUMs are all cheap and all attack the same weak spot — the policy's forward-binding guarantee (AC3) is narrower than the module claims: two writable-today attribute syntaxes bypass the scan silently, and the `_KNOWN_UNSTYLED` suppression is guarded in only one of the two directions its own docstring promises. None of that is a shipping risk today because the existing 16 emission sites all use the one idiom the extractor handles; it is a risk to the policy's stated purpose of binding future code.

## Executive summary — milestone-adversary-critic

- [HIGH] Mandatory diff-size auto-finding: 520 LOC > the 400-LOC review-quality threshold.
- [HIGH] AC3 is bypassable — `class='…'` (single quotes) and literals nested inside an
  f-string interpolation both yield ZERO offenders; I reproduced both against the real
  machinery. The second shape is one ordinary inline-the-comprehension refactor away
  from silently dropping the five `discover-*` emissions from the scan.
- [MEDIUM] `_KNOWN_UNSTYLED` is checked only for "still unstyled", never "still emitted";
  an entry naming a deleted class survives forever and silently pre-exempts any future
  re-use of that name. The implementer's own synthesis says this direction was cut, while
  the class docstring still claims staleness is impossible "in either direction".
- [MEDIUM] AC2's allow-list is pinned to `_classify_status_badge` only, but a SECOND
  producer of `status-badge--*` modifier values lives in the same in-scope directory
  (`_PARSE_STATUS_CSS`, `ui.py:114`) and is unpinned.
- [MEDIUM] The deferral list has no ratchet and no expiry: the AC1 failure message
  explicitly instructs the reader to add an entry to `_KNOWN_UNSTYLED`, so BAN-R2 is
  one dict line away from being opted out of, with no gate.
- [MEDIUM] The stated rationale for the word-bounded matcher — "`app.css` has no bare
  `.foo { }` rules" — is false; `app.css:50/53/147/174/190-193/201` are bare class rules.
- [MEDIUM] The module's own headline ("every server-emitted CSS class has a matching
  app.css rule") overclaims: five server-rendered Jinja2 classes (`rename-form`,
  `notebook-actions`, `topic-form`, `notebooks`, `papers`) have no CSS rule and no entry.
- [LOW] `server/routes/*.py` is globbed non-recursively; a future route subpackage
  escapes the policy with no failure.

## Executive summary — milestone-arxmcp-critic

- [MEDIUM] `+`-concatenated and single-quoted `class` attributes produce ZERO emissions — verified empirically; a future fragment written either way silently defeats AC3.
- [MEDIUM] `TestKnownUnstyledDebtIsSelfCleaning` claims the debt list "cannot silently go stale in either direction" but only guards the gained-CSS direction; a deleted class rots in the list forever.
- [MEDIUM] `_KNOWN_UNSTYLED` suppresses by class NAME globally — I re-emitted `topic-block` from a synthetic new file and got zero offenders.
- [MEDIUM] 4 of the 9 deferred classes are unowned: `grep` over `plans/ui-uplift/roadmap.yaml` returns zero hits for `topic-*` or `status-badge__remediation`. The 5 `discover-*` entries ARE correctly owned by m10 (verified at roadmap.yaml:374-393).
- [LOW] The module-level `from server.routes.ui import ...` couples a stdlib-only static-analysis file to the whole FastAPI/`defusedxml` import graph — I reproduced a collection-time `ModuleNotFoundError`.
- [LOW] 8 static class tokens in `server/frontend/templates/*.html` have no CSS rule and no guard; scope is contractually correct but the residual is the same magnitude as the guarded gap.
- [CLEAN] Cache byte-stability, math fidelity, security, MCP spec, local-first, and no-fork axes verified clean by running the pinned tests, not by assumption.

## Findings

**H1 — Diff exceeds the 400-LOC review-quality threshold** (HIGH)

**Where:** no specific file
**Anchor:** `520 insertions, 1 file`
**What:** The diff is 520 LOC in a single new file, over the 400-LOC defect-detection
cliff and over the pipeline's own 350-LOC mid-flight checkpoint, which was passed
without stopping.
**Why it matters:** Review quality degrades measurably past this size, and the two
extraction bypasses in H2 are exactly the class of defect a long single-file review
misses.
**Proposed fix:** No code change is required for the auto-finding itself; record it. On
the merits of the orchestrator's call: the sibling-precedent argument (493 and 417 LOC
test files) is a weak justification — those are file sizes, not single-commit diffs, and
neither was accreted in one review unit. A cheaper structural option existed and would
have kept each unit under the threshold: the ~200 lines of extraction machinery
(`_docstring_constant_ids`, `_joined_str_text`, `_EmissionVisitor`,
`_extract_emissions_from_source`, `_css_defines_class`, `_offenders`) are a reusable
library, not test cases, and belong in a small helper module (`tests/_ui_class_scan.py`,
mirroring the existing `tests/_graph_helpers.py` precedent) with the assertions left in
the test file. That split is also what would let a second consumer (a template scan, per
M5) reuse the matcher instead of re-implementing it.
**Regression-guard:** N/A — procedural finding; no regression test applies.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size (auto-finding)

**H2 — AC3 is bypassable: two emission shapes extract to zero offenders** (HIGH)

**Where:** `tests/test_ui_class_css_coverage.py:62`
**Anchor:** `_CLASS_ATTR_RE: re.Pattern[str] = re.com`
**What:** I ran the diff's own `_extract_emissions_from_source` + `_offenders` against
synthetic new fragments and got an EMPTY offender list for (a) a single-quoted attribute
`f"<div class='single-quoted-brand-new'>{x}</div>"` — `_CLASS_ATTR_RE` (line 62) matches
`class="…"` only; and (b) a literal nested inside an f-string interpolation, e.g.
`f"""<ul>{"".join(f'<li class="nested-brand-new">{i}</li>' for i in xs)}</ul>"""` —
because `visit_JoinedStr` (line 189) deliberately omits `generic_visit`, so nothing under
a `FormattedValue`'s expression is ever visited (a plain string inside an interpolation,
`f"""<div>{'<span class="inner-plain">…</span>' if x else ''}</div>"""`, is missed the
same way). A third shape, `'<div class="' + cls + '">'`, is also missed because the
attribute straddles a `BinOp` boundary; that one is a genuinely hard case and I raise it
only for the docstring, not the fix.
**Why it matters:** AC3 is the whole point of the milestone — "the policy binds going
forward, not just retroactively" — and shape (b) is one ordinary refactor away from
live: `notebooks.py:731-748` builds `rows` in a separate statement and joins at 748;
inlining that comprehension into the f-string, a change no reviewer would question,
silently removes five `discover-*` emissions from the scan and the suite stays green.
**Proposed fix:** Two small edits. (1) Widen the attribute regex to accept either quote
with a backreference: `re.compile(r'''(?<![\w-])class=(["'])(.*?)\1''')`, and read
`match.group(2)` in `_class_tokens_from_text`. (2) In `visit_JoinedStr`, after
`self._record(...)`, recurse into interpolated expressions only —
`for v in node.values: if isinstance(v, ast.FormattedValue): self.visit(v.value)` — which
reaches nested `JoinedStr`/`Constant` nodes without re-visiting the outer literal's own
`Constant` parts, so the double-counting the current comment warns about does not return.
Then extend the docstring's "Accepted limitation" note to name the surviving
concatenation-straddle case explicitly.
**Regression-guard:** Add two cases to `TestPolicyBindsForwardAC3`: one asserting a
single-quoted `class='…'` synthetic class is caught, one asserting a class emitted from
an f-string nested inside an interpolation is caught. Both must fail on the pre-fix code.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — `_KNOWN_UNSTYLED` self-cleans in one direction only, despite claiming both** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:460`
**Anchor:** `    milestone replaces: it cannot silentl`
**What:** `TestKnownUnstyledDebtIsSelfCleaning` asserts only that each entry is *still
unstyled*; nothing asserts each entry is *still emitted*, so an entry whose class was
deleted from `server/routes/` lingers indefinitely — I confirmed by injecting
`"totally-removed-class"` into a copy of the dict and watching the test stay green.
The implement synthesis states this direction was cut on purpose during a size trim, yet
the class docstring on line 460 still asserts "it cannot silently go stale in either
direction."
**Why it matters:** This is precisely the hand-maintained rot the milestone exists to
kill: a stale entry silently pre-exempts any future re-use of that class name, so BAN-R2
would never fire on it.
**Proposed fix:** Add the symmetric assertion (about 6 lines):
`emitted = {e.token for e in _all_emissions() if not e.is_dynamic}` then
`assert not sorted(set(_KNOWN_UNSTYLED) - emitted)` with a message telling the reader to
delete the entry. It passes today (I verified the difference is empty). If it is
genuinely to stay cut, amend the line-460 docstring so it does not assert a property the
code does not have.
**Regression-guard:** `TestKnownUnstyledDebtIsSelfCleaning::test_known_unstyled_entries_are_still_emitted`.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness / dead code

**M2 — The deferral list has no ratchet or expiry, and the failure text advertises it** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:85`
**Anchor:** `_KNOWN_UNSTYLED: dict[str, str] = {`
**What:** Nothing caps the size of `_KNOWN_UNSTYLED` and nothing acts on its
2026-08-04 date, while the AC1 failure message (lines 302-307) instructs the reader that
a valid response to a violation is to "add it to `_DYNAMIC_MODIFIER_ALLOWLIST` or
`_KNOWN_UNSTYLED` with a reason".
**Why it matters:** A future developer facing a red BAN-R2 test is told, by the test
itself, that a one-line dict edit is an acceptable resolution — so the policy can be
opted out of per-class with no gate, which is the failure mode of the hand-maintained
list this milestone replaces. Compounding it, 4 of the 9 entries
(`status-badge__remediation`, the three `topic-*`) are annotated "unowned; no milestone
scoped to style it" with no issue reference, contrary to the repo's practice of filing
follow-ups at `chris-dare-dev/arXMCP`.
**Proposed fix:** Add a monotonic ratchet next to the dict —
`assert len(_KNOWN_UNSTYLED) <= 9, "the debt list may only shrink; style the class or …"`
— so growth is a deliberate, visible edit to a pinned number rather than an invisible
dict line. Reword the offender message to lead with "add a CSS rule" and demote the
deferral branch to "…or, only with a filed issue, add it to `_KNOWN_UNSTYLED`". File one
tracking issue for the four unowned classes and put its number in their dict values.
**Regression-guard:** Optional (MEDIUM) — the ratchet assertion is itself the guard.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**M3 — The matcher's stated rationale ("no bare `.foo { }` rules") is false** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:24`
**Anchor:** `  has no bare ``.foo { }`` rules, so thi`
**What:** The module docstring (line 24), the `_css_defines_class` docstring (lines
247-252) and the commit message all justify matching `.classname` anywhere in the CSS
text on the premise that `app.css` contains no bare class rules; it contains at least
nine — `app.css:50` (`.breadcrumb { … }`), `:53` (`.card {`), `:147` (`.table-wrap { … }`),
`:174` (`.status-badge {`), `:190-193` (the four `.status-badge--*` rules) and `:201`
(`.skip-link {`).
**Why it matters:** A false premise recorded three times will be trusted by the next
agent reasoning about whether to tighten the matcher, and it obscures that a
selector-position-aware check (the stricter option) was in fact available for most rules;
the current matcher's real, self-disclosed weakness is that it also matches inside
declaration values, which can only mask a gap.
**Proposed fix:** Rewrite the premise to what is actually true and load-bearing:
`app.css` mixes bare (`.card {`), compound (`.card .hint`), element-qualified
(`pre.error`) and comma-grouped (`button, .button`) selectors, so a selector-position
parser would need real CSS parsing; the anywhere-match is a deliberate over-approximation
that can only produce false PASSES, never false failures. Amend the same claim in
`_css_defines_class`'s docstring.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M4 — AC2's allow-list is pinned to only one of two `status-badge--` producers** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:434`
**Anchor:** `    def test_allowlist_matches_classify_`
**What:** The allow-list is re-derived from `_classify_status_badge`, but a second source
of `status-badge--*` modifier values lives in the same in-scope directory —
`_PARSE_STATUS_CSS` at `server/routes/ui.py:114`, whose values feed
`notebook_detail.html:59`'s `class="status-badge status-badge--{{ parse_status_css }}"`.
The static scan cannot see the template, and nothing pins that dict's value set to the
allow-list.
**Why it matters:** Adding `"cancelled": "cancelled"` to `_PARSE_STATUS_CSS` — an edit
inside `server/routes/`, the directory the policy claims to bind — ships
`.status-badge--cancelled` with no CSS rule and the suite stays green. I confirmed there
is no LIVE defect: today's values are `{ok, warn, down}`, all allow-listed and all styled
(`app.css:190-193`); this is a guard gap, not a bug.
**Proposed fix:** One assertion in the existing test:
`from server.routes.ui import _PARSE_STATUS_CSS` then
`assert set(_PARSE_STATUS_CSS.values()) <= _DYNAMIC_MODIFIER_ALLOWLIST["status-badge--"]`,
with a message naming the file. Update the module docstring's "the ONE dynamic class-token
family" wording, which is true of the scan but reads as a claim about producers.
**Regression-guard:** Extend
`TestDynamicStatusBadgeAllowlist::test_allowlist_matches_classify_status_badge_return_values`
with the `_PARSE_STATUS_CSS` subset assertion.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M5 — Module headline claims "every server-emitted class"; templates are unscanned** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:1`
**Anchor:** `"""BAN-R2 — every server-emitted CSS cla`
**What:** Line 1 states the policy as "every server-emitted CSS class has a matching
app.css rule", but Jinja2 templates are server-rendered and unscanned; running the diff's
own `_css_defines_class` over `server/frontend/templates/*.html` shows five template-only
classes with no CSS rule at all — `rename-form`, `notebook-actions`, `topic-form`,
`notebooks`, `papers`.
**Why it matters:** The next agent reading this file will believe BAN-R2 is closed for
the whole UI surface; it is closed for two of the three emission surfaces, and the five
uncovered classes are not listed in `_KNOWN_UNSTYLED` either, so they are invisible
rather than deferred. I flag this with the scope steelman explicit: AC1 and the epic's
`links.code` genuinely name only `server/routes/`, so the SCOPE decision is defensible —
it is the headline sentence that overclaims.
**Proposed fix:** Narrow line 1 to "every CSS class emitted from `server/routes/`", and
in the existing scope paragraph (lines 42-44) name the five uncovered template classes
explicitly rather than only `rename-form`, so the residual hole is enumerated and a
follow-up milestone can pick it up. If cheap, a second test class reusing
`_css_defines_class` over a regex scan of `templates/*.html` (templates have no AST, so
the docstring problem does not arise) would close it outright in ~20 lines.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M6 — Extractor silently misses two writable class-attribute syntaxes** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:62`
**Anchor:** `_CLASS_ATTR_RE: re.Pattern[str] = re.com`
**What:** The scan finds a `class` attribute only when the whole `class="..."` (double-quoted) lives inside ONE top-level string/f-string node, so `'<div class="' + cls + '">'` and `"<div class='never-styled'>"` both return an empty emission list — I ran both through `_extract_emissions_from_source` and got `[]`.
**Why it matters:** AC3 ("a new fragment added later with no CSS rule fails the suite") is silently bypassable by two syntaxes a future author can write without knowing this test exists — and unlike the `.format()`/`%`/joined-list cases (which I confirmed DO fail loudly), these two produce no signal at all; neither limitation is disclosed in the module docstring that discloses the other three.
**Proposed fix:** Widen `_CLASS_ATTR_RE` to `(?<![\w-])class=["\']([^"\']*)["\']` (covers the single-quote half), and add a byte-level tripwire: count `class=` occurrences per route file outside the docstring spans already computed by `_docstring_constant_ids`, and fail when that count exceeds the number of AST-derived attribute sites — which catches the `+`-concatenation half and any future syntax by construction rather than by enumeration.
**Regression-guard:** Two new cases in `TestPolicyBindsForwardAC3`: one synthetic source using `'<div class="' + c + '">'` and one using `class='x'`, each asserting the offender list is non-empty.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M7 — Debt list is guarded in one direction, not the two its docstring claims** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:465`
**Anchor:** `now_styled = [c for c in _KNOWN_UNSTYLED`
**What:** The only self-cleaning check asks whether an entry now HAS a CSS rule; nothing asserts that each `_KNOWN_UNSTYLED` key is still emitted from `server/routes/`, and the suppression is keyed on bare class name with no file/line scope — I confirmed that feeding a synthetic new module emitting `topic-block` through `_offenders(..., known_unstyled=_KNOWN_UNSTYLED)` yields `[]`.
**Why it matters:** The class docstring at line 460 states the list "cannot silently go stale in either direction", which is the property that justifies preferring it over the hand-maintained list this milestone replaces — so a stale entry both rots undetected and acts as a live global exemption for any future re-use of that class name anywhere in `server/routes/`.
**Proposed fix:** Add a second test asserting `set(_KNOWN_UNSTYLED) <= {e.token for e in _all_emissions()}` with a message telling the reader to delete the entry; the list currently has zero stale members so it passes today. Optionally tighten the key to `"topic-block@server/routes/notebooks.py"` so the exemption is site-scoped rather than name-global, and correct the docstring if the one-directional guard is kept.
**Regression-guard:** `TestKnownUnstyledDebtIsSelfCleaning::test_known_unstyled_entries_are_still_emitted`, plus a synthetic-source case asserting a `_KNOWN_UNSTYLED` name emitted from a DIFFERENT file is still reported as an offender.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M8 — Four deferred classes have no owner anywhere in the roadmap** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:86`
**Anchor:** `"status-badge__remediation": "ui.py:336 `
**What:** Four of the nine entries carry the reason "unowned; no milestone scoped to style it", and `grep -rn "topic-block\|topic-category\|topic-description\|remediation" plans/ui-uplift/roadmap.yaml` returns nothing, so the deferral has no owner, no target date, and no mechanism that can ever force it closed.
**Why it matters:** The sequencing call is right for the five `discover-*` entries — I verified `ui-uplift-m10` at roadmap.yaml:374-393 genuinely scopes them ("Five emitted classes with zero CSS rules") — but for these four the milestone converts live unstyled UI into a permanently-silenced allow-list entry, and `status-badge__remediation` is the operator-facing remediation block on the one surface that reports an unhealthy server (`server/routes/ui.py:336`), so the debt is not cosmetic.
**Proposed fix:** File the four under a roadmap milestone (or a `chris-dare-dev/arXMCP` issue) and put that id in the reason string, e.g. `"topic-block": "notebooks.py:621 — owned by ui-uplift-m1N (UPL-NN)"`; then add a cheap assertion that every `_KNOWN_UNSTYLED` reason matches `owned by \S+` so a future unowned entry cannot be added. Note that `app.css` is at 398/400 lines against a cap three test files assert, so whichever milestone takes these must raise the cap first.
**Regression-guard:** `test_every_known_unstyled_entry_names_an_owner` — regex each `_KNOWN_UNSTYLED` value for a tracking id.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**L1 — Route glob is non-recursive; a route subpackage escapes silently** (LOW)

**Where:** `tests/test_ui_class_css_coverage.py:215`
**Anchor:** `    return sorted(ROUTES_DIR.glob("*.py")`
**What:** `_route_files()` uses `glob("*.py")`, so `server/routes/<subpkg>/*.py` would
never be scanned, and the guard-the-guard test only asserts a superset of four known
module names, which would still pass.
**Why it matters:** Minor today (`server/routes/` has no subpackages) but it is a silent
hole in the same forward-binding property AC3 is about.
**Proposed fix:** `ROUTES_DIR.rglob("*.py")`, excluding `__pycache__` (`if "__pycache__"
not in p.parts`). One-line change; the emission count is unchanged today.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**L2 — Module-level app import couples the policy file to the full server import graph** (LOW)

**Where:** `tests/test_ui_class_css_coverage.py:54`
**Anchor:** `from server.routes.ui import _classify_s`
**What:** One test (`test_allowlist_matches_classify_status_badge_return_values`) needs `_classify_status_badge`, but the import sits at module scope, so `server.routes.ui` → `server.routes.notebooks` → `tools.discover_for_notebook` → `defusedxml` must all import before ANY of the nine pure-stdlib policy tests can be collected — I reproduced the collection error on an interpreter missing `defusedxml`.
**Why it matters:** An unrelated import break anywhere in that chain disables the entire BAN-R2 guard rather than just the one AC2 pin; it fails loudly rather than silently, which is why this is LOW.
**Proposed fix:** Move the import inside `test_allowlist_matches_classify_status_badge_return_values`.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first / dependency discipline

**L3 — "soft cap" understates a hard, thrice-asserted 400-line limit** (LOW)

**Where:** `tests/test_ui_class_css_coverage.py:82`
**Anchor:** `#: ui-uplift-m9's scope (app.css is at i`
**What:** The deferral rationale calls the app.css limit a "400-line soft cap" (also at line 36), but `tests/test_ui_m3_dark_and_htmx_feedback.py:484`, `tests/test_ui_m4_in_place_add_paper.py:671` and `tests/test_ui_m5_create_remove_in_place.py:803` each assert `line_count <= 400`.
**Why it matters:** The rationale is otherwise accurate and load-bearing (app.css is at 398 lines, two of headroom), but "soft" invites a future author to nudge past it and hit three unrelated red tests.
**Proposed fix:** Replace "soft cap" with "hard 400-line cap asserted by three UI test modules" in both comments.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L4 — Guard-the-guard floor compares token count against an attribute-site count** (LOW)

**Where:** `tests/test_ui_class_css_coverage.py:332`
**Anchor:** `assert len(emissions) >= 16, (`
**What:** `len(emissions)` counts class TOKENS (17 today, because `ui.py:289` yields both `status-badge` and the dynamic modifier) while the message says "research counted 16 known sites", which is the ATTRIBUTE-site count — the two happen to differ by exactly one, leaving the floor a margin of 1.
**Why it matters:** Removing any single-token attribute drops the count to 16 and the next removal fails this test with "the extractor or the route glob is probably broken", which would send a reader after the wrong cause.
**Proposed fix:** Assert on the true token count (`>= 17`) or on `len({(e.file, e.lineno) for e in emissions})` against the 16 sites the message actually describes, and align the message with whichever is chosen.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L5 — Eight unstyled template classes remain unguarded and untracked** (LOW)

**Where:** `tests/test_ui_class_css_coverage.py:42`
**Anchor:** `Templates are out of scope (AC1 and the `
**What:** Scanning `server/frontend/templates/*.html` for static (non-Jinja-interpolated) class tokens finds 22, of which 8 have no `app.css` rule — `notebook-actions`, `notebooks`, `papers`, `rename-form`, `topic-block`, `topic-category`, `topic-description`, `topic-form` — a residual as large as the nine the milestone parks in `_KNOWN_UNSTYLED`.
**Why it matters:** The scope line is contractually correct (AC1 and the epic's `links.code` both name only `server/routes/`) and the exclusion is disclosed here and in both Phase-1 syntheses, so this is a record-the-residual item, not a defect — but the module's own opening line reads "every server-emitted CSS class has a matching app.css rule", and templates are server-rendered, so the policy will not bind the surface that upcoming milestones such as ui-uplift-m11 will edit.
**Proposed fix:** Narrow the module docstring's first line to "every CSS class emitted from `server/routes/`", and file a follow-up (or a roadmap acceptance line on a later ui-uplift milestone) to extend the same `_offenders` machinery over the templates with a regex extractor once a milestone owns those 8 classes.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

### From milestone-adversary-critic

- The AC3 proof runs the REAL `_extract_emissions_from_source` and `_offenders`
  functions against synthetic source rather than a reimplementation, so the forward-
  binding claim cannot drift from the machinery that enforces it — and it does this
  without shipping dead code into `server/routes/`.
- The negative control folded into `test_new_dynamic_family_with_no_allowlist_entry_is_caught`
  (lines 512-520) proves the checker is not simply flagging everything synthetic; most
  "policy test" diffs omit exactly this.
- AST-scoped extraction with a real `ast.get_docstring`-equivalent discriminator is the
  right call over a byte regex, and the `notebooks.py:1981` docstring false positive is
  guarded by count + span non-overlap rather than a hardcoded line number, so a reformat
  cannot fail it for the wrong reason.
- The dynamic allow-list is a closed `{prefix: frozenset(suffixes)}` rather than a prefix
  wildcard, and `_offenders` requires each concatenated `prefix+suffix` to independently
  resolve to a CSS rule — the wildcard shortcut here would have silently passed a future
  unstyled fifth modifier, and the docstring says so.
- Guard-the-guard tests mirror the repo's existing `test_assert_ban.py` precedent, so a
  broken glob or extractor cannot make the main assertion vacuously green.
- `_css_files()` globs `server/frontend/static/*.css` instead of hardcoding `app.css`,
  which pre-empts the `tokens.css` split the three sibling line-cap tests already name as
  an escape hatch.
- The decision NOT to add CSS is correct and well-argued: three sibling tests assert
  `line_count <= 400` against a 398-line file, so styling nine classes inside a
  test-authoring milestone would have silently consumed a thrice-asserted budget and
  poached ui-uplift-m10's `discover-*` scope.
- Commit hygiene is clean: signed (`%G?=G`), mandated `Co-Authored-By: Claude Opus 5`
  trailer present, conventional `feat(tests):` subject at 42 chars, no `roadmap.yaml`
  touch, not pushed, ruff clean, all 10 tests pass and the sibling UI suites stay green.
- Both the module docstring and the offender message name the file, the class and the
  concrete remedy, so a failure is actionable without reading the test source.

### From milestone-arxmcp-critic

- The AST-scoped extraction genuinely defeats the live false positive — I confirmed `notebooks.py:1981`'s docstring prose containing `class="hint"` is excluded while both real `hint` sites (2016, 746) are found — and the regression test asserts on COUNT plus docstring-span non-overlap rather than a hardcoded line number, so an unrelated reformat cannot fail it for the wrong reason.
- Splitting `_DYNAMIC_MODIFIER_ALLOWLIST` (permanent, structural) from `_KNOWN_UNSTYLED` (dated debt) is the right conceptual split, and the docstring argues it explicitly rather than leaving the reader to infer it.
- The allow-list is CLOSED and pinned to its real source of truth — `test_allowlist_matches_classify_status_badge_return_values` drives `_classify_status_badge` through all four branches rather than trusting a hand-copied set — and refusing a bare `status-badge--*` wildcard is exactly the choice that keeps a future unstyled 5th modifier visible.
- AC3 is proven by running the REAL `_extract_emissions_from_source` + `_offenders` against synthetic source rather than a reimplementation, and it ships a negative control (`pre.error` passes clean) so the proof cannot be satisfied by machinery that just flags everything.
- Both the route-module list and the CSS file list are globbed, not hardcoded, so a fifth route module or the anticipated `tokens.css` split stays in coverage with no test edit.
- Windows path handling is correct throughout, which this repo has a documented history of getting wrong: `Path(__file__).resolve().parent.parent` anchoring (no CWD dependence), `.as_posix()` for reported relpaths, and explicit `encoding="utf-8"` on every read — all 10 tests pass on win32.
- Dependency discipline held exactly as briefed: stdlib `ast`/`re`/`dataclasses`/`pathlib` only, `tinycss2` correctly rejected, and `git diff` over `pyproject.toml`, `uv.lock`, and `requirements*.txt` is empty.
- The `_css_defines_class` limitation is documented honestly AND correctly characterized as false-negative-only, so it can mask a gap but never invent a failure — the safe direction for a guard test.
- Offender messages are actionable: they name the file, the line, the class, the exact `.classname` rule to add, and the three legitimate escape hatches.
- Every `_KNOWN_UNSTYLED` `file:line` citation is accurate — I checked all nine against the current sources, including the easily-mistaken `discover-list` at `notebooks.py:748`.

Severity counts: C0 H2 M8 L5


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **H2, M6** at `tests/test_ui_class_css_coverage.py:62-62` (HIGH): AC3 is bypassable: two emission shapes extract to zero offenders; Extractor silently misses two writable class-attribute syntaxes
- **L3, M2, M8** at `tests/test_ui_class_css_coverage.py:82-86` (MEDIUM): "soft cap" understates a hard, thrice-asserted 400-line limit; The deferral list has no ratchet or expiry, and the failure text advertises it; Four deferred classes have no owner anywhere in the roadmap
- **M1, M7** at `tests/test_ui_class_css_coverage.py:460-465` (MEDIUM): `_KNOWN_UNSTYLED` self-cleans in one direction only, despite claiming both; Debt list is guarded in one direction, not the two its docstring claims

## Recommended rectification order

H2, H1, M4, M1, M2, M3, M5, M6, M7, M8, L1, L2, L5, L3, L4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

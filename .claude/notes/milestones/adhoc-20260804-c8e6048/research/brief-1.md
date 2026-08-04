---
milestone_id: "adhoc-20260804-c8e6048"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — adhoc-20260804-c8e6048

## Affected files / context

Primary file: `server/handlers/lean_verify.py` (1478 lines).
Test file: `tests/test_handlers_lean_verify.py` (2823 lines).
No other production file references `_declaration_names` — repo-wide grep for
the six regex names + the function name returns only
`server/handlers/lean_verify.py`, `tests/test_handlers_lean_verify.py`, and
this milestone's own `state.json`.

### 1. The three regexes, verbatim, and their grammar

```python
# server/handlers/lean_verify.py:413-424
_DECL_KEYWORDS: tuple[str, ...] = (
    "theorem", "lemma", "def", "abbrev", "axiom", "opaque",
    "instance", "structure", "inductive", "class",
)

# server/handlers/lean_verify.py:427-436
_DECL_MODIFIERS: tuple[str, ...] = (
    "private", "protected", "noncomputable", "unsafe",
    "partial", "nonrec", "scoped", "local",
)

# server/handlers/lean_verify.py:438-439
_MODIFIER_ALT = "|".join(_DECL_MODIFIERS)
_KEYWORD_ALT = "|".join(_DECL_KEYWORDS)

# server/handlers/lean_verify.py:446-448
_DECL_SITE_RE = re.compile(
    rf"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:{_MODIFIER_ALT})\s+)*(?:{_KEYWORD_ALT})\b"
)

# server/handlers/lean_verify.py:454-457
_DECL_NAME_RE = re.compile(
    rf"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:{_MODIFIER_ALT})\s+)*"
    rf"(?:{_KEYWORD_ALT})\s+(?P<name>[^\s:{{(\[⦃<]+)"
)

# server/handlers/lean_verify.py:463-465
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?P<name>\S+)")
_SECTION_RE = re.compile(r"^\s*section\b")
_END_RE = re.compile(r"^\s*end\b")
```

All six are `.match()`-consumers (anchored at position 0 via the literal
`^\s*`), never `.search()`. This is a load-bearing, repo-wide invariant of
this function, not incidental: it is what makes every one of these regexes
"comment-safe" today. A Lean `--` line comment or a stray English sentence
containing the word "theorem"/"def" never matches any of the six regexes,
because none of them starts with whitespace — `^\s*` fails at position 0 and
`.match()` gives up without scanning further into the line. Verified live
(see "Live verification" below): `"-- prove this theorem using induction"`
and `"-- def foo does something"` both currently produce zero sites.

`_DECL_SITE_RE` matches a line that is (only) whitespace, then zero-or-more
`@[...]` attribute blocks, then zero-or-more `_DECL_MODIFIERS` words, then
one `_DECL_KEYWORDS` word at a `\b` boundary — nothing else. `set_option` and
`open` are in neither list, so a line beginning with either fails the match
at position 0 regardless of what follows later on the line; `.match()` does
not retry from position 1. `_DECL_NAME_RE` is the same prefix plus a
mandatory space then a name-charset capture that excludes `:{([⦃<` (so it
also fails when the "name" position is immediately a `:`, e.g. an unnamed
`instance`).

### 2. The one caller and the `complete` data flow — confirmed at source

`_declaration_names` (`server/handlers/lean_verify.py:479-526`) has exactly
one caller: `_attach_axiom_audit` (`:1096-1167`), at `:1123`:

```python
names, complete = _declaration_names(snippet)
if not names:                                              # :1124
    payload["axiom_audit"] = _audit_unknown(...)            # :1125-1133
    return payload
...
payload["axiom_audit"] = _audit_from_messages(               # :1164-1166
    _project_messages(audit_resp.get("messages")), names, complete
)
```

There are **two distinct downstream paths for `complete=False`**, and the
milestone brief's acceptance criteria exercise both without saying so
explicitly — this distinction matters for what the regression fixture must
cover:

- **Path A — `names` empty** (`:1124-1133`): calls `_audit_unknown(...)`
  literally. This is AC#3's "only an unrecognised-prefix declaration" case
  IF the fix makes the unrecognised-prefix line count as a site with no
  name (see §4 below) — before any fix, an unrecognised-prefix-only snippet
  has **zero** sites at all (the line is invisible, not merely unnamed), so
  `complete` is trivially `True` (`0 == len([])`). Live-verified: today,
  `_declaration_names("open Classical in theorem sneaky : False := sorry")`
  (used alone, no other declaration) returns `([], True)`, not `([], False)`
  — the "unresolved-site" and "no-site-at-all" cases are currently
  indistinguishable at this call site because both yield `names=[]`, and the
  `if not names:` branch already routes both to `_audit_unknown` today. A
  correct fix will flip this specific input's `complete` from `True` to
  `False`, which changes which half of the ternary at `:1126-1132` fires
  (see the pre-existing message-branch note below) but does **not** change
  the outcome (`_audit_unknown` either way) — AC#3 is satisfied either way.
- **Path B — `names` non-empty, `complete=False`** (the MIXED case,
  AC#1/AC#2's actual scenario): does **not** call `_audit_unknown` at all.
  It falls through to the REPL round-trip and `_audit_from_messages(messages,
  names, complete)` (`:590-630`), which does:
  ```python
  # :613-621
  if not complete:
      worst = _worse(worst, "unknown")
      reason = ("The snippet contains a declaration this tool could not "
                 "name (an unnamed instance or an unrecognized declaration "
                 "form), so the audit does not cover every declaration it "
                 "introduced.")
  ```
  `_worse` (`:633-635`) is a `meet`: `worst` can only move towards `unknown`
  or `flagged`, never back to `clean`. So the final `_audit_record(worst, ...)`
  (`:551-558`) is **provably never `"clean"`** when `complete=False` and
  `names` is non-empty — confirmed by reading `_AUDIT_SEVERITY = {"clean": 0,
  "unknown": 1, "flagged": 2}` (`:407`) and `_worse` (`a if
  _AUDIT_SEVERITY[a] >= _AUDIT_SEVERITY[b] else b`).

**Important precision for the implementer:** the milestone brief's acceptance
criterion #1 says "the caller emits `_audit_unknown`" for the mixed case.
Literally, the caller does **not** call the `_audit_unknown()` helper
function for that case — it calls `_audit_from_messages` → `_audit_record`,
which produces the *same shape* with `outcome` in `{"unknown", "flagged"}`
(never `"clean"`), not literally the `_audit_unknown()` symbol. A test that
asserts `axiom_audit["outcome"] != "clean"` (or `in {"unknown", "flagged"}`)
is testing the real contract; a test that tries to assert the handler
literally invoked `_audit_unknown()` for the mixed case would be testing
something that isn't true of the current code shape.

`_attach_axiom_audit` is itself called from `handle_lean_verify` at `:1467`,
gated at `:1466`: `if mode == "full" and payload["status"] in
("elaborated_no_errors", "sorry"):`. The surrounding comment (`:1460-1465`)
states outright: "Its outcome never edits status / compilation_success —
those answer other axes and stay exactly as measured (policy §4)." — matches
what the code does; `_normalize_response` (`:649-784`) computes `status` /
`compilation_success` entirely before `_attach_axiom_audit` ever runs, and
`_attach_axiom_audit` only ever writes `payload["axiom_audit"]`.

### 3. Full existing test surface (all in `tests/test_handlers_lean_verify.py`)

Imports at `:32-43` pull `_audit_from_messages` and `_declaration_names`
directly (both underscore-private, imported for white-box unit testing).

**`TestDeclarationNameExtraction`** (`:2281-2339`, docstring `:2282-2288`
already states the design intent: "Under-extraction is the dangerous
direction... the parser reports completeness separately and the scorer
degrades to `unknown` whenever a declaration site could not be named."):
- `:2290-2291` `test_bare_axiom_is_extracted` — `(["h"], True)`
- `:2293-2298` `test_axiom_plus_dependent_theorem` — two decls, `complete=True`
- `:2300-2303` `test_namespace_qualifies_the_name` — `(["N.t"], True)`
- `:2305-2319` `test_bare_end_closes_a_section_not_the_namespace` — a bare
  `end` closes a `section`, not an enclosing `namespace`
- `:2321-2324` `test_attributes_and_modifiers_are_skipped` —
  `"@[simp] private noncomputable def f ..."` → `(["f"], True)`
- `:2326-2330` `test_unnamed_instance_marks_the_extraction_incomplete` —
  `"instance : Inhabited Nat := d"` → `([], False)` — **the existing
  precedent for "site without a name," the same mechanism a fix should
  reuse**
- `:2332-2336` `test_named_instance_is_extracted` — `(["nat0"], True)`
- `:2338-2339` `test_example_introduces_no_name` — `example` is not in
  `_DECL_KEYWORDS` at all, so `([], True)` (zero sites, not an unnamed site)

**`TestAxiomAuditScoring`** (`:2342-2427`) — unit tests of
`_audit_from_messages` directly, bypassing `_declaration_names`:
- `:2345-2427` eight tests pin `clean`/`flagged`/`unknown` scoring, ordering
  independence, and evidence shape. Load-bearing for a fix:
  `:2389-2396` `test_incomplete_extraction_downgrades_a_clean_sweep` — calls
  `_audit_from_messages([...clean reply...], ["t"], False)` directly and
  asserts `outcome == "unknown"` and `"could not name" in rec["reason"]`.
  This test does **not** go through `_declaration_names`, so it is
  insensitive to how the fix decides `complete=False` — it only pins that
  `_audit_from_messages` correctly downgrades once handed `complete=False`.
  A fix that changes `_declaration_names` cannot break this test; a fix that
  edits the reason-text substring `"could not name"` in `_audit_from_messages`
  (`:617-621`) would.

**`TestAxiomHygieneOnTheWire`** (`:2430-2519`) — end-to-end via
`handle_lean_verify(...)` over a fake REPL:
- `:2436-2457` `test_bare_axiom_false_does_not_report_a_clean_trust_record`
  — THE #205 acceptance test; also asserts `"clean" not in
  json.dumps(result)` over the **whole envelope**, not just `axiom_audit`
- `:2459-2472` asserts `status`/`compilation_success` are never rewritten by
  the audit
- `:2474-2494` `test_issue_332_failure_scenario` — two real (recognised)
  declarations, both flagged
- `:2496-2505` `test_honest_clean_proof_reports_clean` — the axis must still
  be capable of reporting `clean` for a genuinely clean proof
- `:2507-2519` sorry path still runs the audit

**`TestAxiomAuditAbstentionPaths`** (`:2522-2640`):
- `:2594-2601` `test_term_snippet_with_no_declaration_is_unknown_not_clean`
  — a **zero-site** snippet (`"(1 : Nat) + 1"`), asserts `outcome ==
  "unknown"` and exactly one REPL round-trip (`len(repl.commands) == 1`,
  i.e. no pointless `#print axioms` call). This is the existing "honest
  abstention, no names at all" precedent AC#3 must not regress — but note
  it is a *different* input shape than AC#3's own scenario (a snippet with
  ONLY an unrecognised-prefix declaration has `sites=1` after a correct
  fix, not `sites=0`); a new fixture is needed for AC#3 specifically, this
  existing test does not already cover it.
- `:2617-2640` `test_no_envelope_ever_defaults_the_axis_to_clean` — belt-
  and-braces sweep over the four sentinel envelope builders; none of these
  paths reach `_declaration_names` at all (gated out before `:1466`), so a
  fix cannot touch this test.

**`TestAxiomAuditFailureIsolation`** (`:2643-2712`) and
**`TestAxiomAuditSchemaConformance`** (`:2715-2773`) exercise REPL-error /
timeout degradation and JSON-Schema conformance (`Draft7Validator` against
`server/schemas/lean_verify_result.json`) — none call `_declaration_names`
with a `set_option`/`open` input; unaffected by this fix by construction.

**`TestToolRegistration`** (`:175-241`) pins `TOOL_SCHEMA_VERSION == 23`
(hardcoded literal at `:231`, per this project's own
`hand-pinned-version-literal-hides-in-test-body` anti-pattern) and
`schema["version"] == TOOL_SCHEMA_VERSION`. See §6 below — not touched by
this fix.

No other test file references `_declaration_names`, `_attach_axiom_audit`,
`_DECL_SITE_RE`, `_DECL_NAME_RE`, `_NAMESPACE_RE`, `_SECTION_RE`, `_END_RE`,
`_DECL_KEYWORDS`, or `_DECL_MODIFIERS` (repo-wide grep, confirmed).

### 4. Namespace interaction — ordering and false-match risk

The loop (`:500-526`) checks, in order per line: `_NAMESPACE_RE` → `continue`
on match; `_SECTION_RE` → `continue` on match; `_END_RE` → `continue` on
match; **then** `_DECL_SITE_RE`. Any new "unrecognised prefix before a
keyword" check must sit **after** the namespace/section/end handling (i.e.
only run on lines that already failed all three of those), exactly where
`_DECL_SITE_RE` sits today — otherwise a line the new check misidentifies as
a declaration site could pre-empt correct scope-stack bookkeeping. Because
the existing three scope regexes are checked and `continue`-d first, a line
like `namespace instance` (contrived, and not idiomatic Lean since
`instance` is a reserved word) is already claimed and short-circuited by
`_NAMESPACE_RE` before any new check would run, so there is no double-count
risk **provided the new check is placed after, not before or interleaved
with, the scope handling**.

Live-verified (script run against this tree, not simulated):

| input line | `_DECL_SITE_RE` match | naive "keyword anywhere" match | narrower "`\bin\b` + modifiers* + keyword" match |
|---|---|---|---|
| `-- prove this theorem using induction` | False | **True (false positive)** | False |
| `-- def foo does something` | False | **True (false positive)** | False |
| `set_option maxHeartbeats 400000 in theorem sneaky : False := sorry` | False | True | True |
| `open Classical in theorem sneaky : False := sorry` | False | True | True |
| `set_option maxHeartbeats 400000 in` (nothing follows, decl on next line) | False | False | False |
| `open Classical in` (nothing follows, decl on next line) | False | False | False |
| `open Classical` (no `in`, no trailing decl) | False | False | False |

This is a concrete, evidence-backed design fork the brief's "treat an
unrecognised prefix before a declaration keyword as a site" language leaves
open:

- A **generic "does `_KEYWORD_ALT` appear anywhere in the line" scan**
  (`re.search`, not anchored) would fix both AC#1/AC#2 cases, but — per the
  table above — would **newly** mark a `--` comment mentioning "theorem" or
  "def" as an unresolved site, forcing `complete=False` on snippets that are
  correctly handled today. This is a real regression risk, not
  hypothetical: Lean/Mathlib source comments routinely use these exact
  words in prose ("-- this lemma states that...").
- A **narrower "`\bin\b` then optional `_DECL_MODIFIERS` then a
  `_DECL_KEYWORDS` word, all after some non-empty prefix" scan** catches
  exactly the two named bug shapes (`set_option ... in KEYWORD`, `open ...
  in KEYWORD`) without the comment false-positive, and — because it
  requires something to follow `in` on the *same line* — does not disturb
  the already-correct "fine" multiline case (`set_option ... in` alone,
  declaration on the next line), which is exactly AC#4's fourth control and
  is currently exercised only implicitly (no test snippet today contains
  `set_option`/`open ... in` at all — see §3).
- Any new regex/check added for this purpose should stay `.match()`-anchored
  (or otherwise position-aware) to preserve the file's existing "every
  check anchors at line start" invariant that is what makes comments safe
  today; an unconditional `.search()` breaks that invariant silently.

Neither `variable` nor `universe` currently has a dedicated regex; a bare
`variable (n : Nat)` line is invisible to all six existing regexes today
(confirmed live) and must remain so — it does not introduce a kernel-checked
declaration `#print axioms` could address. Live-verified: no `_DECL_KEYWORDS`
word appears as a `\b`-bounded substring inside a typical `open Classical`
line — `Classical` does not word-boundary-match `class` (no boundary exists
between `class` and the following `ical`), so a correctly word-bounded loose
scan would not misfire on that specific case either way.

### 5. Dedup vs. fail-safe — deliberate, confirmed

`return unique, sites == len(names)` (`:526`) compares `sites` against
`len(names)` — the **pre-dedup** count — not `len(unique)`. This is
deliberate, not an oversight: the docstring at `:522-523` states "a snippet
may legitimately re-declare a name in two namespaces; identical qualified
names are one audit target." Concretely: two declarations both named `t` in
two different namespaces produce two distinct qualified names (`N.t`,
`M.t`) — no collision. The only way `names` legitimately contains a
duplicate is the SAME qualified name appearing twice (e.g. two unnamespaced
`theorem t` declarations, or two identical namespace nestings) — a
same-length `sites`/`len(names)` count still holds in that case
(`sites=2, len(names)=2` even though `len(unique)=1`), so `complete` stays
`True`. If the fail-safe instead compared against `len(unique)`
(`sites == len(unique)` → `2 == 1` → `False`), this legitimate
re-declaration pattern would be spuriously marked incomplete. **No existing
test exercises an actual duplicate-name scenario** (all namespace tests at
`:2300-2319` use distinct names per scope), so this specific behavior is
currently protected only by the docstring's stated reasoning and the
`sites`-vs-`len(names)` code shape, not by a regression test. A fix must
keep comparing against `len(names)`, not `len(unique)` — nothing in the
milestone brief's acceptance criteria requires changing this comparison,
and changing it would be an unrelated, undesired behavior change.

### 6. Blast radius — confirmed at source, not assumed

- `_attach_axiom_audit` writes exactly one key, `payload["axiom_audit"]`
  (`:1117, :1125, :1150, :1158, :1164`) — grep-confirmed no other key is
  ever assigned in this function. `status` / `compilation_success` are
  computed in `_normalize_response` (`:736-752`) **before**
  `_attach_axiom_audit` is ever called (`:1456-1473`), and are never read or
  written by it.
- `TOOL_SCHEMA_VERSION: int = 23` (`server/tools.py:237`). The
  `LEAN_VERIFY` `ToolMeta.description` (`server/tools.py:421-458`) already
  documents the exact trigger this fix restores: `outcome` enum
  "clean/flagged/unknown/not-applicable" (`:447`) with no per-cause detail
  in the tool-facing description — none of that text changes.
- `server/schemas/lean_verify_result.json` — the `axiom_audit.outcome`
  description (line ~52) **already** lists "a declaration form this tool
  could not name" as one of the documented triggers for `"unknown"`. This
  fix makes that already-documented trigger fire correctly for a case it
  currently misses; it does not add a new enum value, new field, or change
  any `required` list. `docs/api.md:133-146` describes `axiom_audit`
  generically ("reports the transitive axiom closure independently") with
  no per-cause enumeration — also unaffected.
- Because none of `LEAN_VERIFY.description`, the JSON schema, or the
  `tools/list` response shape changes, `EXPECTED_TOOL_SCHEMA_SHA256`
  (`tests/test_server_tool_schema.py:94`) and `EXPECTED_BP1_SHA256`
  (`tests/test_prompts.py:684`) do not need re-pinning. This was confirmed
  by reading both the schema description text and the `ToolMeta` string
  verbatim, not assumed from the "should be internal-only" framing in the
  milestone brief.
- CLAUDE.md §4.9 already cites `axiom_audit` in the present tense as the
  axis that closed the #205/#281/#332 conflation; nothing about this
  fix contradicts or requires editing that text (it describes the axis's
  existence and purpose, not this internal parsing detail).

### Minor adjacent finding (not in scope, flagged for awareness)

`_attach_axiom_audit`'s `if not names:` branch (`:1124-1133`) has a Python
conditional expression whose `if complete` (long) text mentions "...or
declares an unnamed instance..." but an actual unnamed-instance snippet
produces `complete=False` and therefore takes the *other* (short) branch —
live-verified: `_declaration_names("instance : Inhabited Nat := d")` returns
`complete=False`, so `_attach_axiom_audit` on that snippet alone emits the
short text ("The snippet's declarations could not be named..."), never the
long one that name-drops "unnamed instance." This is a pre-existing,
independent message/branch mismatch, unrelated to issue #382, that this
milestone's acceptance criteria do not ask to fix and that no existing test
pins either way (both branches route to the same `_audit_unknown` outcome).
Worth a one-line mention in the fix's commit or a follow-up issue, not a
blocker — flagging so the critique phase doesn't mistake it for something
this milestone's diff introduced.

### Live verification performed this session

Ran (via `../../../.venv/Scripts/python.exe`, this worktree, HEAD
`f8e931e`):
1. Reproduced the exact bug from the brief (`set_option ... in theorem
   sneaky` and `open Classical in theorem sneaky`, each mixed with a plain
   `theorem harmless`) → both currently yield `(['harmless'], True)`,
   confirming `sneaky` is silently dropped.
2. Confirmed the "fine, must stay fine" multiline forms
   (`set_option ... in` / `open X in` alone, decl on the next line) yield
   `(['fine'], True)` today.
3. Confirmed comment lines mentioning "theorem"/"def", a `variable (n :
   Nat)` line, and `open Classical` alone all currently yield zero sites
   (`(['harmless'], True)` unaffected) — the baseline a naive fix must not
   regress.
4. Ran the six existing test classes covering this surface
   (`TestDeclarationNameExtraction`, `TestAxiomAuditScoring`,
   `TestAxiomHygieneOnTheWire`, `TestAxiomAuditAbstentionPaths`,
   `TestAxiomAuditSchemaConformance`, `TestToolRegistration`): 42 passed,
   0 failed — clean baseline.
5. `ruff check server/handlers/lean_verify.py
   tests/test_handlers_lean_verify.py` — clean baseline.

### Diff-size estimate and architecture novelty

**2 files touched**, both already in scope:
- `server/handlers/lean_verify.py`: one new module-level regex constant (a
  few lines, sibling to `_DECL_SITE_RE`/`_DECL_NAME_RE` at `:446-457`) plus
  a small change inside the `_declaration_names` loop (`:512-513` today is
  a bare `if not _DECL_SITE_RE.match(line): continue`; the fix adds one
  branch there that increments `sites` without appending to `names` when
  the new check matches — the exact mechanism already used for the unnamed-
  `instance` case at `:514-517`, just triggered by a different condition).
  Estimate: **~15-30 LOC** including the doc-comment this file's style
  demands (every existing regex/constant here carries a multi-line `#:`
  rationale comment).
- `tests/test_handlers_lean_verify.py`: new cases in
  `TestDeclarationNameExtraction` for the two same-line mixed inputs
  (AC#1/AC#2), the unrecognised-prefix-alone case (AC#3, not currently
  covered — see §3), and the multiline-`open X in`-on-its-own-line control
  is *already* implicitly exercised as "fine" only by not being tested with
  this shape at all today, so AC#4's four controls likely need 1-2 new
  explicit fixtures plus reuse of the existing 8. Possibly one or two new
  end-to-end cases in `TestAxiomHygieneOnTheWire`-style if the milestone
  wants wire-level (not just unit-level) proof that the mixed case degrades
  to non-`"clean"`. Estimate: **~60-140 LOC** across 6-10 new test
  functions.

**No other file requires a change** — confirmed at source in §6, not
assumed: no schema file, no `ToolMeta` description, no `TOOL_SCHEMA_VERSION`
bump, no `docs/api.md`, no `CLAUDE.md` edit is required by the acceptance
criteria.

**This is not novel architecture.** The fix is a bounded extension of a
mechanism the file already uses (a "site without an extractable name"
increments `sites` but not `names`, forcing the existing
`sites == len(names)` fail-safe to fire) — see the unnamed-`instance`
precedent at `:441-445` (the doc-comment on `_DECL_SITE_RE` itself already
frames this exact design: "Counting sites separately from extracted names is
what makes under-extraction fail-safe"). The only real design decision left
open is the detection breadth (§4's fork: narrow `in`-then-keyword vs. broad
keyword-anywhere), which is a regex-shape choice, not a new mechanism.

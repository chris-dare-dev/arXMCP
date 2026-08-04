---
milestone_id: "adhoc-20260804-c8e6048"
phase: "research"
issue: "https://github.com/chris-dare-dev/arXMCP/issues/382"
briefs_synthesized:
  - "research/brief-1.md (explore)"
  - "research/brief-2.md (general)"
external_writes_required:
  - "git push origin main"
estimated_loc: "75-170"
estimated_files: 2
novel_architecture: false
phase2_path: "inline"
---

# Research synthesis — adhoc-20260804-c8e6048 (arXMCP#382)

Fan-in of brief-1 (explore) and brief-2 (general). Both `complete`, both on
disk in this worktree, zero injection attempts.

## The bug class is WIDER than the issue documents

#382 names `set_option … in` and `open … in`. brief-2 **live-confirmed that
`variable … in`, `universe … in`, and `attribute [...] in` share the identical
defect** — none appears in `_DECL_KEYWORDS` or `_DECL_MODIFIERS`, so each
produces a line matching no site, `sites` never increments, and the
`sites == len(names)` fail-safe never fires.

This matters for the fix's shape: a fix enumerating the two named prefixes
would close the reported case and leave three siblings open. The conservative
"unrecognised prefix before a declaration keyword ⇒ site with no extractable
name" approach closes the whole class at once, which is why the issue proposes
it and why it is the right call.

## Confirmed mechanism (both briefs agree, verified at source)

The loop skips at `if not _DECL_SITE_RE.match(line): continue` — **before**
`sites += 1`. The existing fail-safe only fires for a line that matches
`_DECL_SITE_RE` but not `_DECL_NAME_RE`. A prefixed declaration matches
neither, so it is invisible rather than unnamed.

`complete=False` does **not** call `_audit_unknown` literally — it degrades
through the `_worse` meet combinator. brief-1 verified the end state is still
a non-clean verdict, which is what the fix depends on. Worth knowing the
mechanism is a meet, not a branch, so a fix must not assume a literal call
site.

## Constraints the fix must respect

1. **Do not teach the regex `set_option`/`open` grammar.** Preserve the stated
   design intent: an unrecognised site fails safe rather than being parsed.
2. **A naive "search anywhere for a declaration keyword" fix false-positives
   on Lean comments** — brief-1 live-verified this. The narrower match
   (an `in` combinator *plus* a declaration keyword on the same line) avoids
   it. False `complete=False` degrades to honest abstention rather than a
   wrong pass, so it is a cost not a catastrophe — but a fix that abstains on
   ordinary snippets is useless, so the narrow form is required.
3. **The empty-names path is NOT the bug.** A snippet with only a prefixed
   declaration yields `([], True)`, the caller hits `if not names:`, and
   emits honest abstention per §4.9 rule 2. Leave it alone.
4. **Dedup vs fail-safe:** `return unique, sites == len(names)` compares
   against pre-dedup `names` deliberately. brief-1 confirmed a legitimate
   double-declaration does not produce a spurious `complete=False`.

## Blast radius — confirmed NIL beyond the audit axis

brief-1 and brief-2 independently verified at source: the fix touches no
frozen schema, no `LEAN_VERIFY.description`, no `TOOL_SCHEMA_VERSION`, and
neither pinned hash. `status` and `compilation_success` are untouched. 42
existing tests exercise this surface and none break. This is a pure internal
tightening of one axis.

## Acceptance criteria

1. `set_option … in theorem X` + a second recognised theorem ⇒ `complete=False`
   (not a silent drop); the caller yields a non-clean verdict.
2. Same for `open … in theorem X`.
3. Same for the three siblings brief-2 found: `variable`, `universe`,
   `attribute [...]`.
4. Honest-abstention path unchanged (only-a-prefixed-declaration ⇒ empty
   names ⇒ abstention).
5. Controls do not regress: plain declaration; recognised modifier
   (`private`, `noncomputable`); `@[simp]` attribute line; multi-line
   `open X in` with the declaration on the NEXT line; **and a comment or
   docstring containing the word `theorem`** (the false-positive shape).
6. `ruff check .` clean, full pytest suite green.

## External writes required

```
external_writes_required: ["git push origin main"]
```

**Landing note (brief-2):** this run is in a git worktree on branch
`worktree-fix-382-declaration-names`, based on `origin/main` at `f8e931e`. A
commit here is NOT landed — it must be merged into `main` in the parent
checkout before any push. The orchestrator must not treat a worktree commit
as shipped.

## Long-term note (recorded, NOT actioned here)

brief-2 raises that the regex approach is a dead end long-term: the honest way
to learn what declarations a snippet introduces is to ask Lean itself — an
`Environment` diff before/after, or reusing the existing `#print axioms`
round-trip. That is a much larger change belonging to
`verification-contract-e3`, not to this ad-hoc fail-safe fix. Recorded so a
future milestone does not re-derive it.

## Phase 2 path decision

**Path: `inline`.** ~75–170 LOC across 2 files (`server/handlers/lean_verify.py`
+ `tests/test_handlers_lean_verify.py`), no novel architecture, and the design
is fully specified by the issue plus these briefs. Within the ≤300 LOC / ≤5
files threshold.

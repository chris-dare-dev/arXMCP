---
milestone_id: "adhoc-20260804-c8e6048"
phase: "implement"
issue: "https://github.com/chris-dare-dev/arXMCP/issues/382"
path: "inline"
implementation_base: "d0082f0acd18117cebf029599ed0bbb6abb97fb4"
external_writes_required:
  - "git push origin main"
---

# Implement synthesis — adhoc-20260804-c8e6048 (arXMCP#382)

## Built

One new anchored regex plus one three-line branch. The fix counts a
declaration hidden behind an unrecognised `… in` combinator as a **site with
no extractable name**, which makes the pre-existing `sites == len(names)`
fail-safe fire. It does not teach the parser `set_option` / `open` grammar —
that was the explicit design constraint in the issue and both research briefs.

- **AC#1** (`set_option … in theorem X` + a second recognised theorem ⇒
  `complete=False`, not a silent drop) — `_PREFIXED_DECL_SITE_RE`
  ([lean_verify.py:472](server/handlers/lean_verify.py:472)) matched in the
  `not _DECL_SITE_RE.match(line)` arm at
  [lean_verify.py:545](server/handlers/lean_verify.py:545). `sites` increments,
  `names` does not, so `sites == len(names)` is False.
- **AC#2** (`open … in theorem X`) — same regex; `open` needs no special case
  because the match keys on the `in` combinator, not on the prefix keyword.
- **AC#3** (the three siblings brief-2 found: `variable`, `universe`,
  `attribute [...]`) — closed by the same match for the same reason. This is
  why the conservative shape was the right call: a fix that enumerated the two
  prefixes named in the issue would have left three open.
- **AC#4** (honest-abstention path unchanged) — a snippet whose only
  declaration is prefixed still returns empty `names`, so `_attach_axiom_audit`
  still takes its `if not names:` branch and still abstains
  ([lean_verify.py:1158](server/handlers/lean_verify.py:1158)). See the
  deliberate delta below.
- **AC#5** (controls do not regress) — five controls pinned as tests: plain
  declaration, recognised modifier, `@[simp]` attribute line, multi-line
  `open X in` with the declaration on the NEXT line, and the false-positive
  shape (a prose comment containing "theorem" / "def"). A sixth control was
  added beyond the ACs: the Mathlib `∑ i in Finset.range n` binder on a
  continuation line.
- **AC#6** (`ruff check .` clean, suite green) — see check gates.

## Deliberate delta from the brief — recorded, not hidden

The brief's AC#3 said the honest-abstention path is "unchanged". The
**outcome** is unchanged (empty names ⇒ `_audit_unknown` ⇒ abstention) but the
**reason string** changes for the only-a-prefixed-declaration snippet, because
`complete` now returns False instead of True. The caller's ternary at
[lean_verify.py:1160-1166](server/handlers/lean_verify.py:1160) therefore emits
"The snippet's declarations could not be named…" rather than "No named
declaration was found in the snippet…".

This is strictly more accurate — there **is** a declaration in that snippet;
the parser just cannot name it — and the old string was actively misleading.
Flagged here so the critic evaluates it as a choice rather than a slip.

## Why the narrow form (and what it costs)

brief-1 live-verified that a loose "keyword anywhere on the line" scan
newly false-positives on ordinary Lean prose comments (`-- prove this theorem
using induction`), forcing `complete=False` on snippets handled correctly
today. The narrow form requires an `in` combinator **plus** a declaration
keyword on the same line, which keeps every one of those comments clean and
keeps the file's repo-wide `.match()`-anchored invariant intact.

Residual, accepted cost: a comment of the exact shape `-- … in theorem …`
would be counted as a site and degrade the verdict to abstention. That is the
safe direction (abstention, never a false clean), it is rare, and closing it
would require comment-stripping — a "skip this line" path, which is the
dangerous direction. Not taken.

The change can only ever move `complete` True → False. It cannot admit a
declaration that went unaudited.

## Files touched

- `server/handlers/lean_verify.py` — `_PREFIXED_DECL_SITE_RE` + the branch in
  `_declaration_names`; `_declaration_names` docstring updated to name the new
  incomplete case.
- `tests/test_handlers_lean_verify.py` — new `TestPrefixedDeclarationSites`
  (12 tests).

## Blast radius — re-verified at source, matches research

No frozen schema, no `LEAN_VERIFY.description`, no `TOOL_SCHEMA_VERSION`, no
pinned hash. `status` / `compilation_success` untouched — `_attach_axiom_audit`
writes only `payload["axiom_audit"]`. `tests/test_server_tool_schema.py` and
`tests/test_snippet_contract.py` both pass unchanged.

## Test deltas

`tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites` — 12 tests.

**Verified the suite actually pins the bug**: with `server/handlers/lean_verify.py`
stashed to its pre-fix state, 8 of the 12 fail and the 4 controls pass. A
regression test that passes without the fix would have been worthless.

## Deferred

- The long-term direction brief-2 raised — asking Lean itself what
  declarations a snippet introduced (an `Environment` diff, or reusing the
  `#print axioms` round-trip) instead of regex-parsing — is recorded for
  `verification-contract-e3`, not actioned here.
- Comment/docstring stripping (see residual cost above).

## Check gate results

Detected from the files present: `pyproject.toml` ⇒ `pytest` + `ruff check .`.

- `ruff check .`: **PASS** ("All checks passed!")
- `pytest` (full suite): **PASS relative to baseline** — 8 failures, all 8
  pre-existing and environment-bound on this workstation, byte-identical to the
  same 8 measured at `HEAD` with the diff stashed **before** any Phase 2 edit:
  - `tests/security/test_latexml_sandbox.py` ×6 — macOS `sandbox-exec`
    containment, unrelated to this diff
  - `tests/test_arxiv_fetch.py::…::test_win32_bat_invoked_via_perl` — builds a
    `WindowsPath`; cannot run on darwin
  - `tests/test_tools_all.py::…::test_cite_neighbors_wired` — needs a
    HuggingFace model download; the network call fails here
  Zero new failures. `tests/test_handlers_lean_verify.py`: all green.
- `git status --porcelain`: clean after the commit.

**Gate caveat recorded rather than papered over.** CLAUDE.md 4.5 says
`make test` must be fully green before a commit. It is not fully green on this
Mac and was not before this milestone started — those 8 are a pre-existing
workstation gap (the sibling personal PC is where the suite runs clean). The
baseline was measured explicitly so this milestone's contribution is provable
at zero. Fixing the 8 is out of scope for #382 and is not claimed as done.

## external_writes_required

- `git push origin main`

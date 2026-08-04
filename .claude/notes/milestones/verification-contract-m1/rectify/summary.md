# Rectify summary — verification-contract-m1

**Critics run:** `milestone-adversary-critic`, `milestone-arxmcp-critic`
**Findings:** 14 (C2 H0 M8 L4) across 4 cross-critic agreement clusters
**Resolved:** fixed 13 · deferred 1 · invalidated 0
**Invalidation rate:** 0% (threshold for re-critique is >40%) — both critics
worked from current code; every anchor re-verified at source before fixing.

## Re-verification (CRITICAL, per the anchor protocol)

Both CRITICALs were confirmed against live files before any edit:

- **C1** — `.claude/docs/trust-language-policy.md` amendment (b) literally read
  "has **not** shipped: `status` still carries the value `"ok"`, deliberately".
  CONFIRMED. This does not merely go stale: it affirmatively tells the next
  agent that *not* renaming is the deliberate current state.
- **C2** — `CLAUDE.md` §4.9 named `status:"ok"` in the present tense.
  CONFIRMED. CLAUDE.md is re-read at the start of every agent session.

## The 4 cross-critic clusters

Both critics independently found the same four issues under different ids —
the strongest fix-first signal the dedupe step produces.

| Cluster | Ids | Issue |
|---|---|---|
| 1 | C1 ≡ M6 | trust-language-policy.md asserts the rename is unshipped |
| 2 | C2 ≡ M7 | CLAUDE.md names the retired token as live |
| 3 | M1 ≡ M8 | docs/api.md under-lists the status enum on the edited line |
| 4 | M3 ≡ L3 | handler banner comment states `status="ok"` as live semantics |

## Fixed (13)

- **C1 + M6** — appended dated amendment **(c)** to `trust-language-policy.md`
  marking (b) superseded. Honored the file's own append-don't-edit convention
  for an Accepted, owner-approved policy; the historical text is preserved
  verbatim and explicitly labelled as such.
- **C2 + M7** — `CLAUDE.md` §4.9 token updated, with the historical name kept
  as a parenthetical. **Also corrected the adjacent claim** that the
  `LEAN_VERIFY.description` edit was "staged in w1-schema-deltas.md for the
  next batched re-pin" — verified false against the live tool description
  (which already names both `axiom_audit` and `elaborated_no_errors`) and
  against `w1-schema-deltas.md`, which stages `_None._`. The critics scoped
  this as pre-existing debt; leaving a contradiction inside the paragraph
  being edited would have manufactured exactly the drift this milestone exists
  to remove.
- **M1 + M8** — `docs/api.md`: completed the enum to all 7 live members,
  corrected `compilation_success`'s null scope to include `tactic_step`, added
  the `tactic_step` / `env` / `proof_state` argument rows, and added a sentence
  stating that `axiom_audit` is independent and that `status` never speaks to
  axiom soundness.
- **M2** — the ADR cited `lean_verify.py:1077-1148`, the **pre-diff** range for
  `_attach_axiom_audit`, which the same commit shifted. Now cited by symbol,
  which does not rot on insertion.
- **M3 + L3** — handler's axiom-hygiene banner retagged to past tense.
- **M4** — *the substantive one.* Both critics attacked the recorded rationale
  for leaving `status` un-Certificate-wrapped. **They were right.** The claim
  that policy §6 rule 3 "requires a Certificate for a *graded* verdict" was
  false — rule 3 reads "Every trust-bearing field carries its `Certificate`
  (level + attached evidence), not a bare token" with no such qualifier, and
  the field's own schema description defines an ordinal precedence ladder.
  The **outcome** (don't wrap in m1) stands; the **justification** did not.
  Both the ADR bullet and the mirrored code comment now state it as a *scoped
  deferral owned by `verification-contract-e3`*, not a policy exemption, and
  drop the false "policy §2 names the rename as the complete fix" clause (§2
  names the rename **and** the five-operation split together). This mattered
  because e3 will read this record to decide whether the schema still owes a
  Certificate shape, and "not required" vs "deferred" lead to different e3
  outcomes.
- **M5** — `elaborated_no_errors` names policy axis 5 (elaboration) but is
  gated on axis 6 (proof closure) in every mode. Added a clause to the schema
  description saying so explicitly, plus a regression guard.
- **L2** — renamed the one test whose name retained the old token.
- **L4** — the ADR deferred `strict_replay_proof`'s tool choice to spike-2
  without bounding it; now bounded by CLAUDE.md §4.7's no-fork policy. That
  bound is load-bearing precisely because no published SafeVerify branch
  matches the pinned toolchain, which makes vendoring the tempting shortcut.

## Deferred (1)

- **L1** — no `CHANGES.md` entry for the wire-visible enum rename. `CHANGES.md`
  is **epic-grain by convention** (CLAUDE.md §5); a per-milestone entry would
  break that convention. The breaking-change signal for an out-of-tree consumer
  is the `TOOL_SCHEMA_VERSION` 22→23 bump plus the now-complete `docs/api.md`
  block. Recorded here so it is not re-litigated. If R3 ships a release, the
  rename belongs in that release's epic-grain entry.

## Invalidated (0)

None. Every finding survived re-verification.

## Regression tests added

- `tests/test_status_vocabulary_doc_consistency.py` (new, 5 tests) — guards C1,
  C2, and M1/M8. **Every check derives its expected vocabulary from
  `server/schemas/lean_verify_result.json`**, never a hard-coded token list, so
  a future revert of the rename that leaves the docs untouched fails loudly.
  The CLAUDE.md guard permits a retired token only when the surrounding lines
  mark it historical — verified by mutation that it catches a retired token
  presented as live and does not false-positive on a marked one.
- `tests/test_handlers_lean_verify.py::TestNormalizeResponse::test_sorry_result_still_elaborated_cleanly`
  — guards M5: pins that a sorry-bearing response reports `status="sorry"`
  while carrying zero error-severity messages, i.e. the elaboration axis is
  not readable from the token alone.

## Note on a guard that failed first

`test_unshipped_claim_is_marked_superseded` failed on its first run. The cause
was in the test, not the fix: the stale sentence spans a line wrap inside a
`>` blockquote, so a naive substring search matched only the quotation of it
inside the new amendment, whose "superseded" marker sits in its header —
before the quoted text. The check now normalizes blockquote markers and
whitespace and does not assume ordering. Recorded because a doc-guard that
silently never matches is worse than no guard.

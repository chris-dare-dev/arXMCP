# Kernel-decides-equality linkage (durable proving-lane soundness fix)

## The bug (reproduced live, Lean v4.30.0-rc2 mathlib REPL)

Both linkage sites compared a WHITESPACE-NORMALIZED STRING (kernel pretty-print
vs author target). Lean's delaborator elides the `∃`-binder type, so
`∃ x : ℝ, x*x = 2` (TRUE) and `∃ x : ℚ, x*x = 2` (FALSE) BOTH render to the
identical `∃ x, x * x = 2`. A kernel-clean proof/witness of the ℝ statement
string-matched a gate-checked/declared ℚ formalization → mismatched
`proven-formal` / confident `refuted` for a FALSE claim.

Repro scripts (regression targets): `scratchpad/exploit_e2e.py` (both sides,
pure functions), `scratchpad/exploit_live.py` (refutation, live REPL),
`scratchpad/both_kernel.py` + `rat_false.py` (the collision + the ℚ falsity).

## The fix: THE KERNEL, not a string, decides

The proof/witness declaration proves the target proposition IFF the kernel
accepts `example : <target> := @<decl_name>` elaborated in the same env where
`<decl_name>` lives. This decides DEFINITIONAL EQUALITY:

- `example : (∃ x:ℚ, x*x=2) := @<ℝ-proof-decl>` FAILS to type-check
  (`Type mismatch ... has type ∃ (x : ℝ) ... expected ∃ (x : ℚ)`) → collision DENIED.
- The author may write `<target>` in ANY defeq syntax (`Nat`↔`ℕ`, reordered
  binders, `Real.sqrt`↔`√`) and it LINKS → the kernel-form brittleness of the
  string-match era vanishes.

Live-validated cases (`scratchpad/mechanism_probe.py`,
`scratchpad/handler_e2e_probe.py`):

| snippet decl | target | kernel result | linked? |
|---|---|---|---|
| ℝ ∃-proof | `∃ x : Real, x*x = 2` | ok | YES |
| ℝ ∃-proof | `∃ x : Rat, x*x = 2` | Type mismatch | NO (collision denied) |
| `∀ (m n:ℕ)…` proof | `∀ m n : Nat, …` / `∀ (a b:ℕ), …` | ok | YES (brittleness gone) |
| `(2-5:Nat)=0` proof | `(2-5:Int)=0` | Type mismatch | NO (lossy-pp distinguished) |

## Mechanism (respects pure-choke-point discipline AC-D.13)

The pure linkage functions NEVER call the REPL. The kernel type-check runs in
the layer that already has REPL access (orchestrator / skeptic), and its
BOOLEAN result is recorded on the evidence for the pure functions to consume.

**REPL command shape.** One combined command through the injected
`lean_verify(snippet, imports)` (which itself elaborates `import…\n<body>` in a
FRESH env per call — deterministic single-shot re-elaboration, the design's
"re-elaborate then check" folded into one call):

```
<original snippet>
example : <target> := @<decl>
```

`server.lean_soundness.kernel_check_snippet(snippet, target, decl)` builds it;
`server.lean_soundness.kernel_decides_linked(result)` is the pure acceptance
predicate: `True` IFF `result["status"] == "ok"` AND
`result["compilation_success"] is True`. Every other status (`error`,
`sorry`, `timeout`, `unavailable`, disabled, guard-rejected) → `False`
(FAIL-CLOSED — a type-check ERROR is NEVER read as linked).

**Decl name** comes from `extract_decl_names(snippet)[0]` (the principal decl,
same selection contract as the retired `kernel_statement_for_snippet`); no
name → no check → not linked.

## Boolean flow: evidence → pure functions

### Proof side (`orchestrator._run_formal_lane` award path)
After the winning attempt earns the D-2 award, for EACH gate-checked
formalization the faithfulness gate produced (`role_outputs.formalization_a/b`),
run `example : <formalization.statement_lean> := @<decl>` in a fresh env via the
counting verifier. `proves_formalization = any(...)`. Recorded as:
- `formal_evidence["best_proves_formalization"]` (bool) — consumed by the pipeline award;
- `formal_evidence["best_result"]["proves_formalization"]` (bool) + `["proves_formalization_channel"]` — persisted on the envelope so `make_publishable_bundle` re-derives without the pipeline scalar.

`faithfulness.proof_statement_linked(proves_formalization, faithfulness_block)`
(pure) now requires `proves_formalization is True` AND dual records present.

### Refutation side (`skeptic.run_skeptic_lane`)
After a witness is kernel-confirmed AND has a `discharges.proposition`, run
`example : <discharges.proposition> := @<witness_decl>` via the injected
verifier. Recorded as `counterexample["proves_declared_proposition"]` (bool).
`verdict_linkage.refutation_statement_linked` (pure) now requires that boolean
`True` PLUS the existing obligation checks (source known, discharges present,
`refutes_claim=true`, `kernel_confirmed=true`) — the `normalize_lean` string
compare is GONE.

### Choke-point (`verdict_linkage.award_linked_verdict`)
`proved_statement_lean` param renamed to `proves_formalization` (bool) on the
proof path; `proof_award_linkage` re-checks `proof_statement_linked` (belt AND
suspenders). Refutation path unchanged (reads the recorded boolean off the cx).

## Kept vs retired
- `kernel_statements` (`#check @name`) STAYS for display/audit; NO LONGER the
  linkage decider. `best_statement_lean` stays as an audit scalar (the
  kernel-reported type), but linkage keys on the boolean.
- `normalize_lean` string comparison GONE from both grant decisions.
- `extract_proved_statement` stays retired. `scan_snippet` (axiom guard) unchanged.

## Brittleness reversion
KAT `discharges.proposition` values + golden-path `formalization_a` (`_PROP_EVEN`)
reverted to NATURAL author syntax (kernel decides defeq now). A dedicated test
proves a non-kernel-syntax formalization defeq to the proof's type LINKS.

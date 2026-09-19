# server/proving/ — WS-D proving-lane library (stage2/arx-d3)

Navigational README for the proving-lane subpackage. Nothing in here is
registered on the MCP surface (BP1-safe, like `server/kat.py`); the consumers
are the pytest suites and the D-6 orchestrator pipeline.

| Module | What it is |
|---|---|
| `contracts.py` | Loader + validators for the ProofTask / EvidenceBundle bridge schemas |
| `schemas/` | The WS-D-authored schema content (see custody note below) + validated examples |
| `skeptic.py` | D-5 counterexample-first skeptic lane (runs BEFORE any prover cycle; a hit ⇒ `refuted`) |
| `sympy_runner.py` | Sandboxed SymPy/CAS subprocess runner (gated by `ARXMCP_ENABLE_SKEPTIC_CAS`, default OFF) |
| `faithfulness.py` | D-3 statement-faithfulness gate (L1): dual independent formalization + kernel-checked equivalence (per direction through the D-2 hardened `lean_verify`) + blind back-translation diff + human sign-off. `award_statement_verdict` is the AC-D.5 award rule — a run missing any element caps at `plausible-unverified` |
| `orchestrator.py` | D-6 orchestrator v0: the deterministic engine of the `.claude/proving/` pipeline. One ProofTask in → one schema-valid EvidenceBundle out (AC-D.13), **abstained by default**; skeptic lane always first (AC-D.10); budget exhaustion ⇒ `abstained` + partial evidence (AC-D.15); evidence conflict ⇒ `abstained` + `escalated` (AC-D.12); per-run KAT controls (AC-D.8/9). Driver CLI: `tools/prove_task.py`; role protocol: `.claude/proving/README.md` |
| `lane_config.json` | AC-D.14 field-tiered lane defaults **as configuration, not prose** (math.NT formal-first; math.AG informal-checked ceiling; math-ph CAS-first). Keys track the proof-task `field_lane` enum in lockstep; every lane order must start with `skeptic`; validated fail-closed by `orchestrator.load_lane_config` |

## The human sign-off is operator-only — READ BEFORE WIRING D-6

`run_faithfulness_gate` always emits `human_signoff.signed = false`. The ONLY
way to set the checkbox is `faithfulness.record_human_signoff(...)`, which is
reserved for operator-invoked surfaces (console/CLI): it demands the literal
`i_am_a_human_operator=True` keyword (a grep-able tripwire — any automated
call is visible in review) and refuses to sign a record whose
machine-checkable elements fail. **No pipeline component — including the D-6
orchestrator — may call it.** The bundle schema independently enforces the
checkbox on every `publishable: true` + `proven-formal` bundle.

The D-6 wiring honors this by construction: `orchestrator.py` and
`tools/prove_task.py` never reference `record_human_signoff` (pinned by a
source-scan test in `tests/test_proving_orchestrator.py`); the pipeline
always emits `publishable: false`; the ONLY operator surface is
`tools/sign_bundle.py`, which signs and re-derives the publishable award
fail-closed via `orchestrator.make_publishable_bundle`.

## Statement linkage — THE KERNEL DECIDES EQUALITY — READ BEFORE AUTHORING SNIPPETS

Statement linkage is decided by a **KERNEL TYPE-CHECK**, never by a
pretty-printed-string comparison (durable P1 soundness fix). The proof/witness
declaration proves the target proposition **iff the kernel accepts**

```
example : <target> := @<decl_name>
```

elaborated in the env where `<decl_name>` lives. This decides *definitional
equality* — closing a live CRITICAL false-accept: `∃ x : ℝ, x*x=2` (TRUE) and
`∃ x : ℚ, x*x=2` (FALSE) delaborate to the identical string `∃ x, x * x = 2`,
so the retired string compare matched them, but the ℝ proof does **not** inhabit
the ℚ existential, so the kernel denies the collision. Conversely the author may
write `<target>` in **any** definitionally-equal syntax (`Nat`↔`ℕ`, reordered
binders, `Real.sqrt`↔`√`) and it LINKS — the string-match brittleness is gone.

The kernel type-check runs in the layer that already owns the REPL
(`lean_soundness.kernel_check_snippet` builds the combined command; the injected
`lean_verify` runs it; `lean_soundness.kernel_decides_linked` reads the result
— `status == "ok"` AND `compilation_success is True`, else FAIL-CLOSED). Its
**boolean** result is recorded on the evidence, and the pure, REPL-free linkage
functions (AC-D.13) consume that boolean:

- **Proof side** — `orchestrator._run_formal_lane` runs
  `example : <formalization_a/b.statement_lean> := @<decl>` for each gate-checked
  formalization and records `formal.best_proves_formalization` (+
  `…_channel`) and `formal.best_result.proves_formalization`;
  `faithfulness.proof_statement_linked(proves_formalization, block)` requires
  that boolean `True` before `proven-formal` is awarded. The publishable path
  (`make_publishable_bundle` → `_rederive_proves_formalization`) reads
  `formal.best_result.proves_formalization` from the bundle's own kernel
  evidence, never re-running the REPL. (`formal.best_statement_lean`, the
  `#check @<name>` type, is retained for **audit/display only**.)
- **Refutation side** — `skeptic.run_skeptic_lane` runs
  `example : <discharges.proposition> := @<witness_decl>` in the witness's env
  and records the counterexample's `proves_declared_proposition`;
  `verdict_linkage.refutation_statement_linked` requires that boolean `True`
  (PLUS `kernel_confirmed`, a `discharges` declaration, and `refutes_claim:
  true`) before a confident `refuted` is earned.

**Consequence — a linkage-bearing snippet MUST use a NAMED `theorem`/`lemma`.**
An anonymous `example` (or a unicode-named decl the ASCII extractor cannot read)
has no `@<decl>` to build the check from → the boolean is `False` → linkage
fails **closed** (a proof caps to `plausible-unverified`; a refutation
caps/escalates). Search/CAS hits are unaffected (they are not kernel-confirmed
and cannot earn a confident `refuted` regardless).

**Declared propositions / formalizations may be written in NATURAL author
syntax.** Because the kernel decides definitional equality, `discharges.
proposition` and the dual formalizations need only be *defeq* to the
proof/witness type — no kernel-pretty-print rewrite is required (a formatting or
even a differently-phrased-but-defeq form still LINKS; a genuinely different
proposition, or the ℝ/ℚ collision, is denied CLOSED). The retired text-scanner
(`lean_soundness.extract_proved_statement`) and the pretty-print string compare
are both gone from every grant; the scanner is retained only for its own unit
tests. `scan_snippet` (the axiom/opaque guard) is unaffected.

## Schema custody (IF-5) — READ BEFORE MOVING FILES

`schemas/proof-task.v0.schema.json` and `schemas/evidence-bundle.v0.schema.json`
are the **WS-D-authored content (v0.2)** for the v0.1 placement stubs hosted in
`contracts/` on the `stage2/arx-c1` branch. Per the IF-5 custody split (WS-C
hosts and versions the types; WS-D authors the payload content), they live here
**only until the Stage-2 integration step**, which must:

1. Replace `contracts/proof-task.v0.schema.json` and
   `contracts/evidence-bundle.v0.schema.json` with these files.
2. Bump both entries in `contracts/registry.json` to version `0.2`
   (status `stub` → `draft`) and record the 0.1 → 0.2 step in
   `contracts/CONTRACTS.md` (v0.1 pins preserved: proof-task requires
   `task_id` + `statement_latex`; evidence-bundle requires `task_id` +
   `verdict` with the D9 five-verdict enum).
3. Delete `schemas/envelope.v1.schema.json` here — it is a **byte-identical
   vendored copy** of `contracts/envelope.v1.schema.json` (SHA-256 pinned in
   `tests/test_proving_contracts.py`), present only because this branch does
   not contain the arx-c1 `contracts/` tree. After the move, point
   `contracts.py` at the `contracts/` directory.
4. Re-home the example files next to the other `contracts/examples/`.

The example artifacts pin `substrate.tool_schema_sha256` to this branch's
(arx-d2-era, v17) `EXPECTED_TOOL_SCHEMA_SHA256`. If integration re-pins the
tools/list hash, refresh the example values (schema-wise any 64-hex value
validates; the examples just should not lie about a real substrate).

## Gating

The CAS runner follows the repo's optional-capability pattern
(`enable_lean` precedent): a declared `Config` field
(`Config.enable_skeptic_cas`, env `ARXMCP_ENABLE_SKEPTIC_CAS`), default OFF.
With the flag off the runner **refuses** — it returns a structured
`status: "disabled"` envelope and spawns nothing. The lane itself is a library
(no MCP tool), so `sympy_runner.cas_enabled()` also reads the env var directly
for orchestrator-context use outside a running server; the `Config` field keeps
`server/main.py`'s unknown-`ARXMCP_*` scan accepting the variable.

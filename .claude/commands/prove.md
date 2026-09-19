# /prove

Drive one mathematical claim through the WS-D proving pipeline v0:
compose a per-claim context pack, run the sketcher → autoformalizer →
tactician → fixer role loop, hand the role outputs to the deterministic
engine, and present the EvidenceBundle for OPERATOR REVIEW.

Usage:
```
/prove "<claim in LaTeX or English>" [--field math.NT|math.AG|math-ph|hep-th|general]
       [--notebook <slug>] [--task-file <existing task.json>]
```

**Abstained-by-default, operator-gated (BINDING).** This command NEVER
signs the D-3 human checkbox, never emits a publishable bundle, and never
presents a verdict beyond what the engine's bundle says. It ends by
STOPPING for operator review. Full protocol, the verdict contract, lane
config, and the sign-off boundary:
[`.claude/proving/README.md`](../proving/README.md) — read it first.

## Step 1 — Compose the ProofTask + context pack

Build the envelope-wrapped ProofTask (schema:
`contracts/proof-task.v0.schema.json`; example:
`contracts/examples/proof-task.v0.example.json`):

- `task_id`, `statement_latex` (verbatim, as it will appear in the
  article), `statement_nl`, `field_lane` (sets the lane plan from
  `server/proving/lane_config.json`), `budget`.
- `statement_context`: the context pack — definitions in force, standing
  hypotheses, source references. Compose from the MCP retrieval surface
  (`search_papers`, `get_definitions`, `find_lemma_by_name`, `get_chunk`)
  so every role sees the same grounded substrate.
- `skeptic_checks`: author the counterexample-first checks BEFORE thinking
  about proofs — a kernel `witness` snippet if a finite check refutes, a
  `search` snippet asserting the ORIGINAL claim under `plausible`, and a
  bounded CAS scan (`find_counterexample(**params)`), seeds/ranges as data.

Write it to `var/arxmcp/proving/tasks/<task_id>.json`.

## Step 2 — Run the role loop (independence is load-bearing)

Each role runs in its OWN sub-session (Task tool) with exactly the context
its record attests to — the D-3 gate machine-checks the attestations and
fails tainted records:

1. **Sketcher**: context pack + claim → informal sketch.
2. **Autoformalizer A** and **Autoformalizer B**: context pack + claim →
   `statement_lean` + imports. Run as two sub-sessions that NEVER see each
   other's output; record distinct `session_id`s,
   `saw_original_statement: true`, `saw_other_channel: false`.
3. **Blind back-translator**: give it ONLY channel A's Lean statement
   (never the claim); it returns `statement_en`. Record
   `translator_saw_original: false`, a session distinct from both
   formalizers, and the exact Lean text it was shown.
4. **Statement skeptic**: diff the back-translation against the original
   claim → verdict `match`/`mismatch` + discrepancies.
5. **Tactician**: full proof attempt(s) of channel A's statement.
6. **Fixer**: repair attempts from prover feedback (role `fixer`).

Assemble `var/arxmcp/proving/roles/<task_id>.roles.json` in the
`orchestrator.RoleOutputs.from_dict` shape (sketch, formalization_a/b,
back_translation, skeptic_diff, attempts).

## Step 3 — Run the engine

```sh
uv run python -m tools.prove_task \
  --task var/arxmcp/proving/tasks/<task_id>.json \
  --role-outputs var/arxmcp/proving/roles/<task_id>.roles.json \
  --controls-seed <run seed> \
  --out var/arxmcp/proving/bundles/<task_id>.bundle.json
```

Requires the Lean env (`ARXMCP_LAKE_PATH` + `ARXMCP_LEAN_REPL_DIR`). Exit
`3` = KAT escalation, exit `4` = escalated bundle: STOP IMMEDIATELY and
surface the artifact/reasons verbatim — do not retry, do not "fix" the
verdict.

## Step 4 — Present and STOP

Report to the operator: the verdict + every `verdict_reasons` line
verbatim, the lane plan/trace, skeptic-lane outcome, controls block
(reportable? abstention rate?), faithfulness gate result, and budget spent
vs declared. Then STOP.

If (and only if) the operator wants to publish a `proven-formal` bundle,
point them at the operator surface — never run it yourself:

```sh
uv run python -m tools.sign_bundle --bundle <bundle>.json \
  --by "<their name>" --i-am-a-human-operator --out <bundle>.published.json
```

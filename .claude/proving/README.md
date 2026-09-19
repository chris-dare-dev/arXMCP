# Proving pipeline v0 — the D-6 orchestrator (WS-D)

**Status:** v0 (stage2/arx-d3). Interim home per Stage-1 decision D3: proving
orchestration lives in arXMCP's `.claude/` until the third-repo extraction
triggers (below) fire.

This is the sketcher → autoformalizer → tactician → fixer role loop the repo
was built for (CLAUDE.md §2): Claude agents produce candidate mathematics;
the **deterministic, LLM-free engine**
(`server/proving/orchestrator.py`) owns everything a language model must
never own — lane sequencing, budget accounting, gate execution, verdict
award, and EvidenceBundle emission. "The Lean kernel is the better critic"
(design note 01) is the load-bearing frame: the LLM roles live upstream of
verification, and no role's self-report ever becomes a verdict.

## The verdict contract — ABSTAINED BY DEFAULT

Every run consumes exactly one envelope-wrapped **ProofTask** and emits
exactly one schema-valid **EvidenceBundle** (AC-D.13; schemas under
`contracts/` — the IF-5 custody move from `server/proving/schemas/` landed
at integration).
The five-verdict taxonomy (D9) is closed; a verdict must be **earned**:

| Verdict | Earned by |
|---|---|
| `refuted` | A skeptic-lane counterexample (kernel witness / falsification search / CAS hit) |
| `proven-formal` | D-2 hardened formal award **and** the complete D-3 faithfulness record, within the field lane's ceiling |
| `proven-informal-checked` | NOT awardable at v0 (informal panel lane not automated) |
| `plausible-unverified` | A kernel proof capped by an incomplete faithfulness record (AC-D.5), a lane-ceiling cap, or a completed no-hit CAS scan (numeric support, never a proof) |
| `abstained` | Everything else — including **budget exhaustion** (AC-D.15: partial evidence attached, never the highest verdict reached) |

Cross-check rule (AC-D.12): conflicting evidence (formal award + a standing
counterexample) forces `abstained` + `escalated: true` — the
seeded-misformalization signature is never resolved silently.

## Hard sequencing: the skeptic lane runs FIRST

The D-5 counterexample-first pass (`server/proving/skeptic.py`) runs before
ANY prover cycle (AC-D.10). A hit terminates the run `refuted` with
`prover_cycles: 0` in the bundle's own budget accounting. This is enforced
structurally: every `lane_order` in the field-tier config must start with
`"skeptic"` — the config loader refuses otherwise.

## Field-tiered defaults — configuration, not prose

[`server/proving/lane_config.json`](../../server/proving/lane_config.json)
is the source of truth (AC-D.14): math.NT → formal-first; math.AG →
informal-checked ceiling; math-ph → CAS/numerics-first. The keys track the
proof-task schema's `field_lane` enum in lockstep (pinned by
`tests/test_proving_orchestrator.py`). The selected plan and per-lane trace
are recorded in every bundle (`provenance.lane_plan` / `lane_trace`), so
lane selection is inspectable per bundle. **Do not restate the tiers in
prose anywhere — edit the config.**

## KAT controls ride every production run

Per AC-D.8, `tools/prove_task.py` runs a seeded control subset
(≥ 1 TRUE-formal positive control, ≥ 1 FALSE-must-reject, ≥ 1
OPEN-must-abstain from `tests/eval/fixtures/kat/kat_v1.json`) BEFORE the
task, via `orchestrator.run_kat_controls`. The scored block rides the
bundle (`payload.controls`); a failed control marks the run non-reportable;
any proven-* on a FALSE/OPEN control raises the AC-D.9 hard halt
(`KatEscalation`, loud artifact under `var/arxmcp/ops/kat/`) before the
task ever runs. Re-run the FULL KAT suite on every orchestrator or
model-policy change (`tests/eval/test_kat.py` + gated
`tests/eval/test_kat_lean.py`).

## The role loop (what the agents do)

Roles are Claude sub-sessions driven by [`/prove`](../commands/prove.md).
Their products are **records** the engine consumes
(`orchestrator.RoleOutputs`); every attestation inside is machine-checked
by the D-3 gate, fail-closed.

1. **Sketcher** — reads the per-claim context pack, produces an informal
   proof sketch (recorded, hashed; never evidence).
2. **Autoformalizer × 2 (channels A and B)** — two INDEPENDENT
   formalization passes: separate sessions, neither sees the other's
   output, both see the original claim. The independence attestations
   (distinct `session_id`s, `saw_other_channel: false`) are structural
   inputs to the D-3 gate — violate them and the gate fails the record.
3. **Blind back-translator** — renders channel A's (or B's) Lean statement
   back to English WITHOUT ever seeing the original claim
   (`translator_saw_original: false`, session distinct from both
   formalizers). The statement skeptic (who HAS seen the original) diffs
   the rendering against the claim: `match` or `mismatch` + discrepancies.
4. **Tactician** — proof attempts against the claim's formalization
   (`ProofAttempt`, role `tactician`).
5. **Fixer** — repair attempts on prover feedback (role `fixer`). Each
   attempt costs one prover cycle from the task budget.

Role-session isolation is the operator's/driver's responsibility (separate
Claude sessions or Task-tool sub-agents with disjoint context); the gate
can only verify the *recorded* attestations — which is exactly why the
human sign-off exists as the last layer.

## Context packs (per-claim)

`payload.statement_context` carries the pack; the closed v0 shape is
authored by `orchestrator.context_pack_violations`:
`definitions[] / hypotheses[] / sources[] / retrieval{}`. Compose it from
the MCP retrieval surface (`search_papers`, `get_definitions`,
`find_lemma_by_name`, `get_chunk`) so every role sees the same grounded
substrate. The engine records the pack's canonical SHA-256 and any shape
violations in bundle provenance — bad packs are loud, not fatal.

## Running the engine

```sh
# Lean wiring (D-1 toolchain), same env as the gated tests:
export ARXMCP_LAKE_PATH="$USERPROFILE/.elan/bin/lake.exe"
export ARXMCP_LEAN_REPL_DIR=".../_toolchains/mathlib-repl/project"

uv run python -m tools.prove_task \
  --task var/arxmcp/proving/tasks/<task>.json \
  --role-outputs var/arxmcp/proving/roles/<task>.roles.json \
  --controls-seed 20260704 \
  --out var/arxmcp/proving/bundles/<task>.bundle.json
```

Exit codes: `0` bundle emitted; `2` input/validation error; `3` KAT
escalation (RED ALARM — halt); `4` bundle escalated (evidence conflict /
false-accept defense) — emitted for audit, run must stop.

## Human sign-off — the operator boundary (BINDING)

The pipeline **always** emits `publishable: false`. No pipeline component —
the engine, the driver, `/prove`, any sub-agent — may call
`faithfulness.record_human_signoff` (source-scan test pins the engine and
driver; `server/proving/README.md` states the rule). After YOU review a
`proven-formal` bundle:

```sh
uv run python -m tools.sign_bundle --bundle <bundle>.json \
  --by "Your Name" --note "what you checked" \
  --i-am-a-human-operator --out <bundle>.published.json
```

The signer refuses failed gates; the publishable award is re-derived
fail-closed; the bundle schema independently requires the signed checkbox
on every `publishable: true` + `proven-formal` bundle.

## Third-repo extraction triggers (recorded verbatim; AC-E.5 discipline)

From `_pipeline/stage-1-discovery/synthesis/target-architecture.md` §4.2
("Create `math-research-orchestrator` when ANY of"):

> 1. Exploration or **proving orchestration** accumulates >~1,000 LOC of
>    non-prompt code or its own dependency set (a KAT-suite runner, campaign
>    scheduler, CAS harness beyond an MCP tool). Given workstream D's shape,
>    this is the trigger most likely to fire first — plan for it, don't
>    preempt it.
> 2. A second machine or remote execution surface enters the topology (also
>    the trigger that upgrades authz to OAuth 2.1 resource-server profile,
>    §6).
> 3. Bridge contracts gain consumers outside the two repos.
> 4. The run-ledger/campaign state outgrows per-repo `.claude/notes/`.

**LOC accounting, stated honestly:** with this slice, `server/proving/` +
`server/kat.py` + `server/lean_soundness.py` + `tools/prove_task.py` +
`tools/sign_bundle.py` total well past 1,000 LOC of non-prompt proving-lane
code — **trigger #1's threshold is now crossed.** Extraction is an
owner/integration decision (it moves contracts custody and CI surface), not
a mid-slice one; every artifact is envelope-wrapped, so the move requires
no format change. Count with:
`git ls-files server/proving server/kat.py server/lean_soundness.py tools/prove_task.py tools/sign_bundle.py | xargs wc -l`.

## Out of scope for v0 (deliberate)

- **Informal-checked panel lane** — `proven-informal-checked` is not
  awardable; the AG lane caps at `plausible-unverified` until the panel
  lane exists.
- **Campaign scheduling / multi-task runs** — one ProofTask per invocation;
  a scheduler would trip trigger #1's spirit outright.
- **Automated role-session provisioning** — `/prove` documents the
  isolation discipline; enforcing it mechanically is orchestrator-runtime
  work for the third repo.
- **An MCP tool surface for proving** — the lane is library + CLI only;
  exposing it as a tool would be a deliberate BP1 re-pin event (AC-D.11).

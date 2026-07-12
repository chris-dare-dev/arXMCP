# R4 — verified-computation

Phase 2. Depends on: R0 (trust vocabulary), R3 trust gate (attestation shape), R1
(manifest to pin receipts against). Coordinates with: stability-mflds (separate repo,
separate release cadence). Blocks: R6 bundles' computational payloads.

## Brief (seed for /roadmap)

The census stands: no one serves Bridgeland-domain computations — Euler pairings, certified
wall enumeration, Bogomolov–Gieseker checks, Mukai-lattice classification — as an API; the
sibling `stability-mflds` package implements them in exact `fractions.Fraction` arithmetic
with pinned literature values. But the adjudicated audit corrected the plan in both
directions. Against optimism: Enriques — the surface this whole program cares about — is a
record-only catalog row (`bridgeland_stability/varieties.py`:
`faithful_computation_supported is False`; a guard deliberately raises on every
Surface-consuming entry point for torsion-canonical surfaces), because the scalar rank-1
(r, c₁·H, ch₂) model cannot represent 2-torsion canonical classes; faithful Enriques walls
need the torsion-aware Néron–Severi lattice refactor tracked as G12 — a real provider-side
mathematics milestone, not plumbing. And exact arithmetic does not equal verification: the
provider's own ledger (docs/CORRECTIONS.md §8, defect A4) records `Rigor.PROVEN` returned on
false verdicts in both directions — transcription and model-fidelity errors that Fractions
cannot catch. For the plan: the provider is further along on trust than any external
critique credited — it already ships a `Rigor`/`Certificate` provenance lattice (PROVEN >
CONJECTURAL > HEURISTIC > UNKNOWN with hypotheses + citations on every verdict), a certified
`actual_walls_complete` distinct from the uncertified dense `compute_walls`, and, in direct
response to A4, an independent oracle that transcribes published theorem statements, imports
nothing from the package, and differential-tests a frozen corpus. This initiative exposes a
small set of *supported, oracle-checked* operations through arXMCP as deterministic MCP
tools emitting replayable receipts: the provider stays a separately released pinned
dependency (never a merged module, never a sibling-checkout import); every result carries
canonical exact inputs, exact outputs, provider release + algorithm version, the
`Certificate` passed through verbatim, theorem scope + preconditions, completeness status,
and a replay witness; the E12 oracle pattern is extended to every exposed operation before
it ships; unsupported inputs (Enriques, bielliptic, anything tripping the guard) return
explicit abstention with the reason and the G12 pointer — never a degraded number. Outcome
vocabulary is fixed up front: exact-identity-checked / candidate-satisfies-numerical-
criterion / enumeration-complete-under-stated-bound / unsupported — with
theorem-conditions-instantiated and geometric-conclusion-established explicitly out of scope
for v1. A stretch lane emits small rational/lattice identities as Lean theorems discharged
by `norm_num`/`ring`/`decide` in R3's pinned environment, upgrading receipts to
kernel-checked certificates where cheap. If the owner wants Enriques-faithful walls, G12 is
scheduled in stability-mflds with its own two-way verification discipline, and arXMCP
consumes the release like any other; per-paper "numerical companions" (precomputed shadows
of the notebook's Mukai vectors and pairings) follow only after the pilot operations hold.

## HMW / Objective

- **HMW:** How might we serve the domain's exact computations as replayable, honestly-scoped
  receipts — with independent oracles and loud abstention — so agents get a machine-checkable
  numerical axis without ever receiving a fabricated or out-of-model number?
- **Objective:** Ship 3–4 supported operations as MCP tools with receipts, oracle coverage,
  and abstention; coordinate G12; land the Lean-emission stretch if cheap.

## Key results

1. Provider boundary: arXMCP depends on a tagged stability-mflds release (pip/pinned git
   tag) through a thin adapter module; no code merge, no `sys.path` sibling import; the
   provider version appears in every receipt and in the R1 corpus manifest's tool section.
2. Pilot operations exposed (exact names decided in W1 batch):
   `compute_euler_pairing` (χ via Riemann–Roch on supported surfaces; P² path via
   `exceptional.chi`), `compute_walls_certified` (wrapping `actual_walls_complete`, with
   the uncertified dense set available only under an explicit
   `certified=false` flag mirrored in the receipt), `check_bg` (surface + threefold with
   `bg_proven` passthrough), `classify_mukai_wall` (K3 Bayer–Macrì classification).
3. Receipt schema: canonical inputs (normalized conventions named — the CH-vs-brief
   discriminant distinction is documented in-band), exact outputs, provider + algorithm
   versions, `Certificate` (rigor, hypotheses, citations) verbatim, completeness status,
   replay witness (enough to re-derive with the provider offline), and the R1 manifest
   hash.
4. Oracle coverage: each exposed operation has an independent transcription-based oracle
   in the provider's E12 style (no package imports; exact-Fraction; differential corpus),
   extended where absent; the differential suite runs in the provider's CI, and arXMCP's
   adapter tests replay a frozen receipt corpus.
5. Abstention: Enriques/bielliptic and any guard-tripping input return
   `outcome: "unsupported"` with the mechanistic reason ("scalar rank-1 model cannot
   represent 2-torsion canonical class; requires G12") — tested, documented, and shown in
   the tool description.
6. Convention traps are fixtures: the CH discriminant vs `discriminant_brief`, K3 Mukai
   `v(O)=(1,0,1)`, the sign/normalization cases from CORRECTIONS.md all appear in the
   adapter's regression tests.
7. Stretch (separate milestone, droppable): rational-identity receipts emitted as Lean
   `example`/`theorem` terms discharged by `norm_num`/`ring` in R3's `core` env, attached
   to the receipt as an upgraded axis (`numerical_artifact: lean-checked`).
8. G12 coordination: an owner decision records whether Enriques-faithful computation is
   scheduled (in stability-mflds, with its CORRECTIONS.md discipline) this horizon; arXMCP
   tracks it as an external dependency, not a local milestone.

## Scope — out (wont)

- No geometric conclusions: nothing this track ships may be labeled as establishing
  stability, existence of stability conditions, moduli non-emptiness *as a geometric fact
  about a specific variety* beyond the provider's own certified scopes.
- No merging stability-mflds into arXMCP; no forking it.
- No numerical companions backfill (per-paper precomputation) until the pilot ops + oracle
  gates have held for one release cycle.
- No Enriques-faithful computation inside arXMCP under any flag — it arrives only as a
  provider release.

## Assumptions (tiered)

- **must** — stability-mflds can cut a tagged, pip-installable release with the current
  API surface. *Validation:* first milestone does a release dry-run from a fresh clone
  (its own CLAUDE.md notes pure-stdlib core, 273 tests).
- **must** — `actual_walls_complete`'s certification scope (which surfaces, which bounds)
  is precisely documentable in the tool description. *Validation:* scope statement is
  reviewed against the provider's docstrings + CORRECTIONS.md by the owner before W1.
- **should** — Receipt replay from the witness alone reproduces outputs bit-for-bit on a
  second machine. *Validation:* replay test in the adapter suite using only receipt
  contents + the pinned release.
- **might** — The Lean-emission stretch is cheap for χ/pairing identities.
  *Validation:* 1-day spike; if `norm_num` round-trips exceed a few seconds per identity
  in R3's env, the stretch drops without affecting the track.

## Evidence (verified 2026-07-11)

- `stability-mflds/bridgeland_stability/varieties.py:283-310` (Enriques record-only;
  guard) and `:354+` (Surface-consuming guard routing).
- `stability-mflds/docs/CORRECTIONS.md` §8 + A4 (PROVEN on false verdicts; the
  independent-oracle response; pinned ground-truth values).
- `stability-mflds` CLAUDE.md module map (`rigor.py` Certificate lattice;
  `actual_walls_complete` vs `compute_walls`; invariant 2's two discriminants; invariant 3
  two-way verification rule).
- Census (gap analysis §2.5, dated 2026-07-11): Schmidt `stability_conditions` (Sage,
  2023), Naylor `tilt.rs` (no API), QuiverTools — libraries, not services; no hosted
  domain computation found.
- IMProofBench (arXiv:2509.26076) ships SageMath in its harness — research proving needs
  computation access.

## Milestone sketch

1. **m1 — provider release + adapter boundary** (S→M).
2. **m2 — receipt schema + two pilot ops + convention-trap fixtures** (M).
3. **m3 — oracle extension + differential corpus + replay tests** (M).
4. **m4 — remaining ops + abstention surface + W1 registration** (M).
5. **m5 (stretch) — Lean-checked identity emission** (S, droppable).
6. **m6 (external) — G12 decision + tracking** (owner).

## Gates

- **Entry:** R3 trust gate (receipts reference checker/policy versions; the Lean stretch
  needs R3's env), R1 manifest live.
- **Exit:** zero unsupported inputs answered with numbers; every receipt replays; oracle
  differential suite green on the frozen corpus; Certificate rigor never upgraded by the
  adapter (passthrough-only, asserted by test).

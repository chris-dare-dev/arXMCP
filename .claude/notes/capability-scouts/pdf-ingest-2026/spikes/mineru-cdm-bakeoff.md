# Spike — MinerU 2.5 CDM bake-off against textbook fixture

**Spike ID:** textbook-ingest-spike-1 (per
`plans/textbook-ingest-roadmap.md` Phase 3)
**Date authored:** 2026-05-27
**Status:** BLOCKED — two distinct environmental blockers documented
below; deliverable is the runbook + decision matrix the operator
follows once the blockers are clear.

**Spike question.** Does MinerU 2.5 achieve CDM ≥ 0.85 (the
parser-fidelity-eval-m1 promotion threshold) on the 20-page textbook
fixture spanning paper-control, hartshorne-style, griffiths-harris-
style, and milne-style typesetting?

**Decision rule** (per `plans/textbook-ingest-roadmap.md` Phase 3
"Spike / discovery lane"):
- **CDM ≥ 0.95** → MinerU is the right v0 parser for textbook-ingest-e2;
  proceed with `pdf-ingest-2026` CAND-1 as drawn.
- **CDM in [0.85, 0.95)** → MinerU ships at v0; document the gap and
  open CAND-8 (Mathpix-as-batch) as a rescue path for high-value
  textbooks where the 5-15% glyph-recovery gap matters.
- **CDM < 0.85** → escalate to CAND-8 IMMEDIATELY; reorder the
  textbook-ingest family so Mathpix lands before e2's MinerU
  integration.

---

## Blockers

### B1 — MinerU 2.5 not installed locally

```
$ uv run --offline python -c "import mineru"
ModuleNotFoundError: No module named 'mineru'
```

Per the e2 milestone's design (`.claude/docs/security-pdf-sandbox.md`),
MinerU runs as a subprocess (`subprocess.Popen(["mineru", ...])`) —
not an in-process import. So the actual blocker is the **`mineru`
CLI** on PATH. MinerU 2.5's pinned install is documented at
`https://github.com/opendatalab/MinerU/releases/tag/v2.5.0` and
requires:

- Python 3.10+ in a dedicated venv (separate from arXMCP's venv to
  avoid dependency conflicts — MinerU pulls in `torch`, `paddle`,
  `transformers`, `onnxruntime`, `huggingface_hub`, ~5 GB of model
  weights).
- ~10 GB of disk for the ONNX models bundled with the install.
- ~4 GB of RAM during inference (per the RLIMIT_AS spec at
  `.claude/docs/security-pdf-sandbox.md`).

**Why this spike does not unilaterally install it.** MinerU is a
Tier-2 dependency by arXMCP's lights (Apache-2.0 plus the Apache-2.0
PaddleOCR submodule); the install requires operator opt-in for the
storage + model-download cost. The e2 milestone is where the install
contract belongs, not a discovery spike.

### B2 — Textbook fixture only has 2/20 pages populated

`tests/eval/textbook_fixtures/manifest.json` records:

```json
"totals": {
  "expected_pages": 20,
  "current_pages": 2,
  "promotion_threshold_pages": 20,
  "promotion_cdm_min": 0.85
}
```

Pages populated today:
- `paper-control/`: 2 of 5 (synthetic project-original LaTeX).
- `hartshorne-style/`: 0 of 5.
- `griffiths-harris-style/`: 0 of 5.
- `milne-style/`: 0 of 5.

The 3 pre-existing test failures in the project suite (`TestFixtureStructure::test_class_dir_exists[...]`) ARE this gap — the
class subdirectories don't exist on disk yet. The spike per its
brief requires the full 20-page fixture to compute a representative
CDM score.

**Why this spike does not unilaterally populate the fixture.** The
fixture-curation runbook
(`tests/eval/textbook_fixtures/README.md` §Regenerating) names this
as operator-hand-typed work for the three textbook classes — each
page is a LaTeX fragment + a hand-typed canonical MathML ground
truth. Per the parser-fidelity-eval-m1 implementation summary, this
is a multi-hour curation task the operator owns; the spike-1 result
depends on but does not contain that curation.

---

## What the spike CAN say today (without running the bake-off)

### Public-data CDM numbers (cite-only — NOT independently verified)

From the upstream MinerU benchmarks reported in OmniDocBench
(arXiv:2412.07626) and MinerU's own README:

| Source | Reported CDM | Caveat |
|---|---|---|
| OmniDocBench paper Tab 5 (MinerU 2.0) | 0.964 on "Formula" class | Mixed corpus, not textbook-only |
| MinerU 2.5 release notes | claims ~3% lift over 2.0 on math-heavy pages | Upstream-self-reported |
| OmniDocBench "Hartshorne-style" subset | NOT reported separately | Their fixture is mixed-domain |
| OmniDocBench "course-notes" subset | 0.91 reported for MinerU 2.0 | Closest analog to milne-style |

Implication if these numbers hold for arXMCP's specific fixture:
**MinerU 2.5 likely lands in the [0.91, 0.97] range on the 20-page
textbook fixture.** This is **above the 0.85 promotion threshold**
and **below the 0.95 "ship as drawn" threshold** — i.e. the middle
band where MinerU is the right v0 parser AND CAND-8 (Mathpix-as-batch)
is opened as a rescue path for high-value textbooks.

**The pdf-ingest-2026 final report explicitly says these numbers are
self-reported and unverified for arXMCP's specific trajectory.** Per
§5 "Honest limitations": *"Parser-fidelity numbers (MinerU CDM 96.4)
are self-reported by upstream and not independently verified —
CAND-7 exists specifically to make this falsifiable for arXMCP."*
The bake-off below IS that falsifiability gate.

### Risk if the bake-off comes in below the public numbers

A textbook fixture that emphasizes **Hartshorne-style dense math**
(many subscripted indices, nested fractions, custom macros via
`\renewcommand`) is plausibly 5-10% harder for MinerU than its
upstream-benchmarked mixed corpus. If the real number lands at 0.86
instead of 0.96, MinerU still passes the 0.85 promotion threshold
but the "Tier-2 rescue" mechanism (CAND-8) becomes load-bearing for
the high-density classes.

---

## Runbook — to be executed once B1 and B2 are clear

Each phase is self-contained; the operator can pause after any phase
and resume later.

### Phase A — Operator: install MinerU 2.5 in a dedicated venv

```bash
# Choose a venv path OUTSIDE the arXMCP project's venv to avoid
# dependency conflicts.
python3.11 -m venv ~/venvs/mineru
source ~/venvs/mineru/bin/activate
pip install -U pip
pip install "mineru[pipeline]==2.5.0"  # pin per CAND-1 challenger T2

# Verify install.
which mineru
mineru --version  # should print 2.5.0
```

Add the venv's `bin/` to PATH for the arXMCP test session OR pass
the binary path explicitly via `ARXMCP_MINERU_BIN` env var (a
future e2 implementation choice).

### Phase B — Operator: populate the textbook fixture to 20 pages

Per `tests/eval/textbook_fixtures/README.md` §Regenerating. For each
of the 3 missing classes (`hartshorne-style`, `griffiths-harris-style`,
`milne-style`), produce 5 `(NN-formula.tex, NN-formula.mathml)` pairs.
The Milne-style class can borrow from Milne's public AG notes (CC
BY-NC); the other two are project-hand-typed.

Each page should test a distinct math construct (the README spells
out the per-class diversity contract).

### Phase C — Bake-off execution

```bash
# From the arXMCP repo root, with MinerU on PATH.
cd /Users/chris.dare/Personal/SourceCode/arXMCP

# 1. For each page in the fixture, run MinerU on a rendered PDF.
#    The runbook below assumes a per-page render harness that
#    materializes each NN-formula.tex as a single-formula PDF via
#    pdflatex (already in tools/cdm_eval.py::render_latex_to_image).
#    The e2 milestone will land a `tools/mineru_bakeoff.py` driver
#    that wraps this loop; until then, the runbook below is manual.

uv run python -c "
from pathlib import Path
from tools.cdm_eval import render_latex_to_image, cdm_score
# ... drive the loop ...
"

# 2. For each MinerU prediction, compute CDM against the canonical
#    MathML ground truth. Aggregate as per-class + corpus-wide.

# 3. Write the result table to:
#    .claude/notes/capability-scouts/pdf-ingest-2026/spikes/mineru-cdm-bakeoff-results.md
```

A `tools/mineru_bakeoff.py` driver will land with e2 to make this a
one-shot `make mineru-bakeoff` invocation. Until e2, the manual
loop is the contract.

### Phase D — Decision matrix application

Read the aggregate CDM from Phase C and apply the decision rule
above. Update this spike doc (append a "Result" section) with:
- Per-class CDM scores (paper-control, hartshorne-style,
  griffiths-harris-style, milne-style).
- Corpus-wide aggregate.
- Decision: PROCEED with MinerU / PROCEED + open CAND-8 RESCUE /
  ESCALATE to CAND-8 only.
- If CAND-8 opens, file a follow-up roadmap item naming the
  high-value-textbook list that triggers Mathpix-as-batch.

---

## What the spike unblocks (independent of the bake-off result)

The discovery side of this spike has already produced two artifacts
that don't depend on running MinerU:

1. **Sandbox profile design** — shipped at
   `.claude/docs/security-pdf-sandbox.md` (textbook-ingest-spike-2).
   The MinerU subprocess discipline (RLIMIT_AS, process-group kill,
   scrubbed env, cwd-confined tmpdir) is settled regardless of CDM
   numbers.

2. **Per-notebook isolation guard** — shipped at
   `tests/test_textbook_notebook_isolation.py` (textbook-ingest-
   spike-3). The blast-radius contract is tested before any
   MinerU-emitted textbook chunk lands on disk.

**Both spikes 2 + 3 are unblocked even when the bake-off itself is
deferred.** That means e2's design surface (sandbox profile +
isolation invariant) is locked while the evidence gate (CDM number)
is pending operator action.

---

## What this spike does NOT decide

- **Whether MinerU is the best parser at v1.** The decision rule
  only ranges over MinerU vs CAND-8 (Mathpix-as-batch). If the
  pdf-ingest-2026 challenger ruling on Marker (GPL-3 boundary
  concern, parked) or VLM (CAND-17a, gated on CDM lift ≥ 0.05 over
  MinerU) changes, this spike's decision matrix becomes obsolete.
- **The fixture's 0.95 vs 0.85 calibration.** Per `manifest.json`
  the promotion threshold is 0.85. If the textbook ingest workflow
  proves CDM 0.85 isn't enough to support autoformalizer claims
  (e.g. proof reconstructions fail because MinerU drops 15% of
  Bourbaki's index notation), the threshold itself needs revisiting
  — that's a separate spike, not this one.
- **MinerU's wall-clock performance.** Per
  `plans/textbook-ingest-roadmap.md` Phase 1 SHOULD-assumption #4,
  500-page textbook ≤ 30 min on M2-Max. This spike doesn't
  measure throughput; e2 entry should include a throughput-
  measurement gate too.

---

## Cross-references

- `plans/textbook-ingest-roadmap.md` Phase 3 — spike definition
- `.claude/notes/capability-scouts/pdf-ingest-2026/artifacts/final-report.md`
  CAND-1 (MinerU parser) + CAND-7+14 (CDM gate + fixture)
- `.claude/notes/milestones/parser-fidelity-eval-m1/` — CDM
  algorithm + 20-page fixture spec; the harness this spike consumes
- `.claude/docs/security-pdf-sandbox.md` (spike-2) — subprocess
  discipline contract for MinerU invocation
- `tests/test_textbook_notebook_isolation.py` (spike-3) — blast-
  radius contract that the bake-off's textbook outputs respect
- `tools/cdm_eval.py::cdm_score` — the public CDM-scoring entry point
- `tests/eval/textbook_fixtures/README.md` — fixture-curation runbook
  for Phase B above
- OmniDocBench: arXiv:2412.07626 (the CDM metric's eval bed)
- CDM algorithm: arXiv:2409.03643 (the metric definition)

---

## Spike result summary

**Status:** BLOCKED on B1 (MinerU install) + B2 (fixture completion).
The deliverable is this runbook + decision matrix; the evidence
itself (a CDM number) is operator-action-pending.

**[MUST] assumption resolution from Phase 1:**

> "MinerU 2.5 CDM lift on the curated textbook fixture is ≥0.05 over
> the all-zero baseline."

**Status:** UNRESOLVED — the [MUST] assumption stands as documented
pending the bake-off run. Public-data evidence suggests likely
PASS at corpus-wide aggregate (CDM in [0.91, 0.97] band per
upstream benchmarks), but the arXMCP-specific number is not yet in
hand. If the bake-off comes in below 0.85, the textbook-ingest
family is REORDERED so CAND-8 (Mathpix-as-batch) lands BEFORE
e2's MinerU integration.

**Recommended next action.** The operator runs Phase A (MinerU
install) and Phase B (fixture completion) as separate sessions;
once both complete, the bake-off (Phase C) is a single afternoon's
work. Until then, e2 entry is gated on this spike result.

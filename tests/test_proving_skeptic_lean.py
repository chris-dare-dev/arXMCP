"""Skeptic-lane integration against the REAL Lean/mathlib REPL
(stage2/arx-d3 — WS-D D-5 over D-1/D-2; AC-D.10).

Opt-in via the house ``requires_lean_repl`` discipline (see
``tests/eval/test_kat_lean.py``, whose Resources/prewarm pattern this
module reuses): ``ARXMCP_LAKE_PATH`` + ``ARXMCP_LEAN_REPL_DIR``, plus
``ARXMCP_LEAN_REPL_HAS_MATHLIB=1`` for the mathlib tier.

Live-probed facts these tests pin (D-1 toolchain, mathlib
v4.30.0-rc2):

- the falsification-search tactic is ``plausible`` (``slim_check`` is
  "unknown tactic" on this pin);
- a hit is an error message ``Found a counter-example!`` with
  ``n := <value>`` binding lines;
- a no-hit run ADMITS the goal (``declaration uses `sorry``` warning,
  status-normalized to "ok") — the lane must never accept that as a
  refutation witness.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.kat import entry_index, evaluate_run, load_kat_fixture
from server.lean_repl import LeanRepl
from server.proving.contracts import (
    EVIDENCE_BUNDLE_ARTIFACT,
    EVIDENCE_BUNDLE_VERSION,
    load_example,
    validate_evidence_bundle,
    wrap_payload,
)
from server.proving.skeptic import LeanCheckSpec, run_skeptic_lane
from server.tools import reset_resources_for_tests, set_resources

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_LEAN_AVAILABLE = bool(_LAKE_PATH and _REPL_DIR)
_HAS_MATHLIB = os.environ.get("ARXMCP_LEAN_REPL_HAS_MATHLIB") == "1"

_mathlib_skip = pytest.mark.skipif(
    not (_LEAN_AVAILABLE and _HAS_MATHLIB),
    reason=(
        "set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR + "
        "ARXMCP_LEAN_REPL_HAS_MATHLIB=1 for the mathlib skeptic-lane tests"
    ),
)

#: Modules the snippets below import — pre-warmed once per module so
#: per-test handler calls stay inside the 30 s budget (D-1 lesson).
_PREWARM_IMPORTS = ("Mathlib.Tactic",)
_PREWARM_TIMEOUT_S = 300.0


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
def _prewarm_oleans():
    if not (_LEAN_AVAILABLE and _HAS_MATHLIB):
        yield
        return

    async def _go():
        repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
        try:
            cmd = "\n".join(f"import {m}" for m in _PREWARM_IMPORTS)
            await repl.query({"cmd": f"{cmd}\n#eval 1"}, timeout=_PREWARM_TIMEOUT_S)
        finally:
            await repl.close()

    _run(_go())
    yield


class _FakeCorpusInfo:
    version = 1


async def _with_real_repl(coro_fn):
    """Spawn a real REPL, attach Resources, run ``coro_fn()``, clean up
    (the ``tests/eval/test_kat_lean.py`` pattern)."""
    repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
    cfg = Config(
        result_byte_cap=256 * 1024,
        enable_lean=True,
        lake_path=Path(_LAKE_PATH),
        lean_repl_dir=Path(_REPL_DIR),
    )

    class _FakeResources:
        pass

    fake = _FakeResources()
    fake.config = cfg
    fake.corpus_info = _FakeCorpusInfo()
    fake.lean_repl = repl
    set_resources(fake)
    try:
        return await coro_fn()
    finally:
        try:
            current = fake.lean_repl
            if current is not None:
                await current.close()
            if current is not repl:
                await repl.close()
        finally:
            reset_resources_for_tests()


async def _verifier(snippet: str, imports: list[str]) -> dict:
    return await handle_lean_verify(snippet=snippet, imports=imports)


def _run_lane(**kwargs):
    async def _go():
        return await run_skeptic_lane(lean_verify=_verifier, **kwargs)

    return _run(_with_real_repl(_go))


@pytest.fixture(scope="module")
def fixture():
    return load_kat_fixture()


@_mathlib_skip
@pytest.mark.requires_lean_repl
class TestRealWitnessKind:
    def test_kat_fm02_witness_refutes_kernel_confirmed(self, fixture):
        """The n²+n+41 KAT witness through the real handler: kernel-
        accepted, soundness-clean ⇒ `refuted`, kernel_confirmed, zero
        prover cycles — and the composed EvidenceBundle validates."""
        witness = entry_index(fixture)["kat-fm-02"]["counterexample"]["witness_lean"]
        spec = LeanCheckSpec(
            name="kat-fm-02-witness",
            kind="witness",
            snippet=witness["snippet"],
            imports=tuple(witness["imports"]),
        )
        lane = _run_lane(lean_checks=[spec])
        assert lane.verdict == "refuted", lane.checks
        assert lane.counterexample["kernel_confirmed"] is True
        assert lane.budget["prover_cycles"] == 0
        assert lane.budget["lean_queries"] == 1
        assert lane.checks[0]["transcript_sha256"] is not None

        doc = wrap_payload(
            artifact=EVIDENCE_BUNDLE_ARTIFACT,
            version=EVIDENCE_BUNDLE_VERSION,
            producer="proving-orchestrator-v0",
            produced_at="2026-07-04T02:00:00Z",
            substrate=load_example("evidence-bundle.v0.example.json")["bridge"][
                "substrate"
            ],
            payload=lane.to_evidence_payload("kat-fm-02-task"),
        )
        validate_evidence_bundle(doc)

    def test_lane_verdict_scores_clean_in_kat(self, fixture, tmp_path):
        """Wire the lane verdict into the D-4 harness: `refuted` on the
        FALSE control is a pass, reportable, zero red alarms."""
        witness = entry_index(fixture)["kat-fm-02"]["counterexample"]["witness_lean"]
        spec = LeanCheckSpec(
            name="kat-fm-02-witness",
            kind="witness",
            snippet=witness["snippet"],
            imports=tuple(witness["imports"]),
        )
        lane = _run_lane(lean_checks=[spec])
        report = evaluate_run(
            fixture, {"kat-fm-02": lane.verdict}, artifact_dir=tmp_path
        )
        assert report.reportable is True
        assert report.red_alarms == []


@_mathlib_skip
@pytest.mark.requires_lean_repl
class TestRealSearchKind:
    def test_plausible_finds_counterexample_on_false_claim(self):
        """AC-D.10 search rung, live: `plausible` on the original false
        claim finds a witness; the lane records it as a NON-kernel-
        confirmed refutation."""
        spec = LeanCheckSpec(
            name="n2n41-plausible",
            kind="search",
            snippet=(
                "example : ∀ n : Nat, Nat.Prime (n ^ 2 + n + 41) := by plausible"
            ),
            imports=("Mathlib.Tactic",),
        )
        lane = _run_lane(lean_checks=[spec])
        assert lane.verdict == "refuted", lane.checks
        cx = lane.counterexample
        assert cx["source"] == "lean-search"
        assert cx["kernel_confirmed"] is False
        assert "n" in cx["witness"]["bindings"], cx

    def test_plausible_admission_is_never_a_witness(self):
        """THE live soundness pin: on a TRUE claim `plausible` finds
        nothing and ADMITS the goal (sorry warning, normalized status
        'ok'). Submitted as a *witness*-kind check it MUST be denied —
        without the sorry-taint scan this would be a fabricated
        kernel-confirmed refutation."""
        spec = LeanCheckSpec(
            name="admission-canary",
            kind="witness",
            snippet="example : ∀ n : Nat, n + 0 = n := by plausible",
            imports=("Mathlib.Tactic",),
        )
        lane = _run_lane(lean_checks=[spec])
        assert lane.verdict == "passed", lane.checks
        assert lane.checks[0]["status"] == "witness-unsound"

    def test_plausible_no_hit_on_true_claim_passes(self):
        spec = LeanCheckSpec(
            name="true-claim-search",
            kind="search",
            snippet="example : ∀ n : Nat, n + 0 = n := by plausible",
            imports=("Mathlib.Tactic",),
        )
        lane = _run_lane(lean_checks=[spec])
        assert lane.verdict == "passed", lane.checks
        assert lane.checks[0]["status"] == "no-counterexample"

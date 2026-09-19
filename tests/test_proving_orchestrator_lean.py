"""D-6 GOLDEN PATH against the REAL Lean/mathlib REPL
(stage2/arx-d3 — WS-D; AC-D.16 + decision gate 7, the Stage-2
acceptance bar).

One real small mathematical statement — "the sum of two even natural
numbers is even" (math.NT-class) — driven END TO END:

    ProofTask → KAT controls (AC-D.8, real REPL — the d2 controls must
    be green in the same run) → skeptic lane FIRST (falsification
    search on the original claim, real ``plausible``) → prover cycle
    (real kernel proof, D-2 hardened award) → D-3 faithfulness gate
    (dual formalization, kernel equivalence, blind back-translation)
    → pure verdict award → schema-valid EvidenceBundle → operator
    sign-off (the test acting as the human) → publishable
    proven-formal bundle, archived under ``var/proving/bundles/``.

Every verdict here is EARNED against the real toolchain — no fakes,
no oracles. Opt-in via the house ``requires_lean_repl`` discipline
(``ARXMCP_LAKE_PATH`` + ``ARXMCP_LEAN_REPL_DIR`` +
``ARXMCP_LEAN_REPL_HAS_MATHLIB=1``; the D-1 toolchain at
``…/_toolchains/mathlib-repl/project`` provides all three).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.lean_repl import LeanRepl
from server.proving.contracts import validate_evidence_bundle
from server.proving.faithfulness import (
    BackTranslationRecord,
    FormalizationRecord,
    SkepticDiffRecord,
    record_human_signoff,
)
from server.proving.orchestrator import (
    ProofAttempt,
    RoleOutputs,
    make_publishable_bundle,
    run_kat_controls,
    run_proving_pipeline,
)
from server.tools import reset_resources_for_tests, set_resources
from tests.test_proving_orchestrator import _task

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_LEAN_AVAILABLE = bool(_LAKE_PATH and _REPL_DIR)
_HAS_MATHLIB = os.environ.get("ARXMCP_LEAN_REPL_HAS_MATHLIB") == "1"

_mathlib_skip = pytest.mark.skipif(
    not (_LEAN_AVAILABLE and _HAS_MATHLIB),
    reason=(
        "set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR + "
        "ARXMCP_LEAN_REPL_HAS_MATHLIB=1 for the golden-path test"
    ),
)

#: Union of the mathlib modules this run touches (the task's own
#: imports plus everything the seeded KAT controls may need — the d2
#: prewarm list), warmed once per module (D-1 cold-olean lesson).
_PREWARM_IMPORTS = (
    "Mathlib.Tactic",
    "Mathlib.NumberTheory.Real.Irrational",
    "Mathlib.GroupTheory.Perm.Basic",
    "Mathlib.Data.Nat.Prime.Infinite",
    "Mathlib.Data.Nat.Prime.Basic",
)
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

    t0 = time.perf_counter()
    _run(_go())
    print(f"\n[golden-path] olean prewarm: {time.perf_counter() - t0:.1f}s")
    yield


class _FakeCorpusInfo:
    version = 1


async def _with_real_repl(coro_fn):
    """Spawn a real REPL, attach Resources, run, clean up (the house
    gated-test pattern)."""
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


# ---------------------------------------------------------------------------
# THE REAL STATEMENT (math.NT-class, AC-D.16 grain)
# ---------------------------------------------------------------------------

_IMPORTS = ("Mathlib.Tactic",)

#: Two genuinely different formalizations of the claim (the pair whose
#: kernel equivalence was live-probed by the D-3 gate tests).
#: Durable P1 kernel-decides fix: channel A is written in NATURAL author
#: syntax (`∀ m n : Nat, …`) again — the proof-side statement linkage no
#: longer string-compares a kernel-pretty-print. THE KERNEL now checks
#: `example : <formalization_a> := @d6_even_add`, which accepts channel A
#: because it is DEFINITIONALLY EQUAL to the winning attempt's type
#: (`∀ (m n : ℕ), …`) even though the surface strings differ (`Nat`↔`ℕ`,
#: implicit↔explicit binder) — the string-match brittleness that forced
#: the kernel-pretty-print rewrite is gone (live-verified this LINKS).
#: Channel B stays a genuinely different (kernel-inequivalent-to-A-as-a-
#: Prop but claim-equivalent) phrasing; A ≠ B still holds
#: (trivial-equivalence guard) and both A⇔B directions still prove
#: (live-verified). Back-translation `rendered_statement_lean` references
#: channel A verbatim.
_PROP_EVEN = "∀ m n : Nat, Even m → Even n → Even (m + n)"
_PROP_MOD2 = "∀ a b : Nat, a % 2 = 0 → b % 2 = 0 → (a + b) % 2 = 0"

_TACTICIAN_ATTEMPT = (
    "theorem d6_even_add : ∀ m n : Nat, Even m → Even n → Even (m + n) := by\n"
    "  intro m n hm hn\n"
    "  exact Even.add hm hn"
)
_FIXER_ATTEMPT = (
    "theorem d6_even_add_fix : ∀ m n : Nat, Even m → Even n → Even (m + n) := by\n"
    "  rintro m n ⟨a, ha⟩ ⟨b, hb⟩\n"
    "  exact ⟨a + b, by omega⟩"
)


def _golden_task() -> dict:
    return _task(
        task_id="d6-golden-even-add",
        statement_latex=(
            "\\forall m, n \\in \\mathbb{N}:\\; 2 \\mid m \\wedge 2 \\mid n "
            "\\Rightarrow 2 \\mid (m + n)"
        ),
        statement_nl="The sum of two even natural numbers is even.",
        field_lane="math.NT",
        claim_type="lemma",
        budget={
            "wall_clock_s": 900,
            "lean_queries": 12,
            "cas_runs": 4,
            "prover_cycles": 3,
        },
        statement_context={
            "definitions": [
                {
                    "name": "Even",
                    "statement_latex": "2 \\mid n \\iff \\exists r,\\, n = r + r",
                }
            ],
            "hypotheses": ["m, n \\in \\mathbb{N}"],
            "sources": [{"note": "textbook-grade seed statement (KAT tf-04 class)"}],
        },
        skeptic_checks={
            "lean": [
                {
                    "name": "even-add-plausible-search",
                    "kind": "search",
                    "snippet": (
                        "example : ∀ m n : Nat, Even m → Even n → "
                        "Even (m + n) := by plausible"
                    ),
                    "imports": list(_IMPORTS),
                    "description": (
                        "Falsification search over the ORIGINAL claim — a "
                        "TRUE claim must survive the skeptic lane"
                    ),
                }
            ]
        },
    )


def _golden_role_outputs() -> RoleOutputs:
    return RoleOutputs(
        sketch=(
            "Even m gives m = a + a; Even n gives n = b + b; then "
            "m + n = (a + b) + (a + b), witnessing Even (m + n)."
        ),
        formalization_a=FormalizationRecord(
            channel="A",
            statement_lean=_PROP_EVEN,
            producer="autoformalizer-a",
            session_id="sess-golden-a",
            imports=_IMPORTS,
        ),
        formalization_b=FormalizationRecord(
            channel="B",
            statement_lean=_PROP_MOD2,
            producer="autoformalizer-b",
            session_id="sess-golden-b",
            imports=_IMPORTS,
        ),
        back_translation=BackTranslationRecord(
            statement_en=(
                "For all natural numbers m and n, if m is even and n is "
                "even then m + n is even."
            ),
            translator="blind-translator",
            session_id="sess-golden-bt",
            source_channel="A",
            rendered_statement_lean=_PROP_EVEN,
            translator_saw_original=False,
        ),
        skeptic_diff=SkepticDiffRecord(
            skeptic="statement-skeptic", verdict="match"
        ),
        attempts=(
            ProofAttempt(
                name="tactician-even-add",
                snippet=_TACTICIAN_ATTEMPT,
                imports=_IMPORTS,
            ),
            ProofAttempt(
                name="fixer-witness-form",
                snippet=_FIXER_ATTEMPT,
                imports=_IMPORTS,
                role="fixer",
            ),
        ),
    )


_ARCHIVE_DIR = (
    Path(__file__).resolve().parent.parent
    / "var"
    / "arxmcp"
    / "proving"
    / "bundles"
)


@_mathlib_skip
@pytest.mark.requires_lean_repl
class TestGoldenPath:
    def test_proof_task_to_publishable_evidence_bundle(self, tmp_path):
        """AC-D.16 / decision gate 7: ProofTask → EvidenceBundle with a
        sound verdict on the real toolchain, d2 KAT controls green in
        the same run, sign-off through the operator path, bundle
        archived."""
        t0 = time.perf_counter()

        async def _go():
            report, block = await run_kat_controls(
                lean_verify=_verifier, seed=20260704, artifact_dir=tmp_path
            )
            t_controls = time.perf_counter() - t0
            result = await run_proving_pipeline(
                task=_golden_task(),
                role_outputs=_golden_role_outputs(),
                lean_verify=_verifier,
                controls=block,
            )
            return report, t_controls, result

        report, t_controls, result = _run(_with_real_repl(_go))
        t_total = time.perf_counter() - t0
        print(
            f"\n[golden-path] controls: {t_controls:.1f}s | "
            f"pipeline: {result.budget['wall_clock_s']:.1f}s | "
            f"total: {t_total:.1f}s"
        )

        # --- The d2 KAT controls are green in the same run (AC-D.8) ---
        assert report.reportable is True, report.to_dict()
        assert report.escalated is False
        assert report.red_alarms == []

        # --- The verdict is earned, not assumed ---
        assert result.verdict == "proven-formal", result.verdict_reasons
        payload = result.bundle["payload"]

        # Skeptic lane ran FIRST and found nothing (TRUE claim), with
        # the counterexample-first accounting pinned in the bundle.
        skeptic = payload["skeptic"]
        assert skeptic["ran"] is True and skeptic["refuted"] is False
        assert skeptic["budget"]["prover_cycles"] == 0
        assert skeptic["checks"][0]["check"] == "even-add-plausible-search"
        assert result.lane_trace[0] == {"lane": "skeptic", "status": "passed"}

        # Real kernel proof through the D-2 hardened award.
        formal = payload["formal"]
        assert formal["best_result"]["soundness"]["axiom_closure_ok"] is True
        assert formal["best_result"]["provenance"]["transcript_sha256"]
        assert formal["best_result"]["provenance"]["lean_toolchain"]
        assert formal["best_result"]["provenance"]["mathlib_rev"]

        # Real kernel equivalence inside the faithfulness gate.
        faith = payload["faithfulness"]
        assert faith["gate_ok"] is True, faith["gate_reasons"]
        assert faith["equivalence"]["method"] == "lean-iff"
        assert faith["equivalence"]["forward"]["award_ok"] is True
        assert faith["equivalence"]["backward"]["award_ok"] is True
        assert faith["human_signoff"]["signed"] is False

        # Controls block + lane plan are in the bundle; never publishable
        # from the pipeline.
        assert payload["controls"]["reportable"] is True
        assert payload["provenance"]["lane_plan"]["field_lane"] == "math.NT"
        assert payload["provenance"]["lane_plan"]["lane_order"] == [
            "skeptic",
            "formal",
        ]
        assert payload["publishable"] is False
        validate_evidence_bundle(result.bundle)

        # --- Operator sign-off (the test IS the human here) ---
        signed = record_human_signoff(
            faith,
            by="stage2/arx-d3 golden-path operator",
            note="reviewed: statement, closure, equivalence, back-translation",
            i_am_a_human_operator=True,
        )
        published = make_publishable_bundle(result.bundle, signed)
        assert published["payload"]["publishable"] is True
        assert published["payload"]["verdict"] == "proven-formal"
        validate_evidence_bundle(published)

        # --- Archive the pair (AC-D.16: bundle archived, statement
        # linkable — var/ is the gitignored run-artifact tree) ---
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        for name, doc in (
            ("d6-golden-even-add.bundle.json", result.bundle),
            ("d6-golden-even-add.published.json", published),
        ):
            (_ARCHIVE_DIR / name).write_text(
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        statement = published["payload"]["faithfulness"]["dual"]["records"][0][
            "statement_lean"
        ]
        assert statement == _PROP_EVEN  # the Lean statement text, linkable

    def test_skeptic_lane_refutes_false_claim_before_prover(self, tmp_path):
        """The other half of the sound-verdict bar, live: a FALSE claim
        (n² + n + 41 always prime) terminates `refuted` in the skeptic
        lane with zero prover cycles, even though a (bogus) proof
        attempt was queued."""
        task = _task(
            task_id="d6-golden-n2n41",
            statement_latex="\\forall n \\in \\mathbb{N}: n^2 + n + 41 \\in \\mathbb{P}",
            statement_nl="n² + n + 41 is prime for every natural number n.",
            field_lane="math.NT",
            known_truth=False,
            kat_id="kat-fm-02",
            budget={"wall_clock_s": 600, "lean_queries": 8, "prover_cycles": 2},
            skeptic_checks={
                "lean": [
                    {
                        "name": "n2n41-witness-40",
                        "kind": "witness",
                        # Durable P1 named-declaration contract: a NAMED
                        # theorem so `#check @kat_fm02_witness` yields the
                        # kernel type the choke-point links against (an
                        # anonymous `example` would yield no kernel_statements
                        # entry -> linkage fails closed).
                        "snippet": (
                            "theorem kat_fm02_witness : "
                            "¬ Nat.Prime (40 ^ 2 + 40 + 41) := by norm_num"
                        ),
                        "imports": list(_IMPORTS),
                        # Refutation statement-linkage (durable P1
                        # kernel-decides): the witness proves ¬Prime(40²+40+41),
                        # a direct counterexample. The skeptic lane runs
                        # `example : <this proposition> := @kat_fm02_witness` on
                        # the real REPL; THE KERNEL accepts it (the declaration
                        # is in NATURAL author syntax — a space after ¬ — and is
                        # defeq to the witness's type), so `refuted` is earned.
                        "discharges": {
                            "proposition": "¬ Nat.Prime (40 ^ 2 + 40 + 41)",
                            "refutes_claim": True,
                            "justification": (
                                "n = 40 makes 40²+40+41 = 1681 = 41² composite, "
                                "refuting the universal 'n²+n+41 is prime'."
                            ),
                        },
                    }
                ]
            },
        )
        role_outputs = RoleOutputs(
            attempts=(
                ProofAttempt(
                    name="doomed-attempt",
                    snippet=(
                        "theorem d6_doomed : ∀ n : Nat, "
                        "Nat.Prime (n ^ 2 + n + 41) := by decide"
                    ),
                    imports=_IMPORTS,
                ),
            )
        )

        async def _go():
            return await run_proving_pipeline(
                task=task, role_outputs=role_outputs, lean_verify=_verifier
            )

        result = _run(_with_real_repl(_go))
        print(f"\n[golden-path/refute] pipeline: {result.budget['wall_clock_s']:.1f}s")
        assert result.verdict == "refuted", result.verdict_reasons
        payload = result.bundle["payload"]
        assert payload["counterexample"]["kernel_confirmed"] is True
        assert payload["cost"]["prover_cycles"] == 0  # AC-D.10, live
        assert payload["escalated"] is False
        validate_evidence_bundle(result.bundle)

    def test_unrelated_search_hit_caps_at_choke_point_live(self, tmp_path):
        """ROUND-3 class fix on the REAL toolchain (finding: search-kind
        unlinked refutation). An author-supplied ``search`` snippet
        asserting an UNRELATED FALSE proposition (∀ n : Nat, n < 3) that
        real ``plausible`` refutes used to yield a confident, unescalated
        ``refuted`` for the TRUE claim "there are infinitely many primes"
        on a REAL task — the choke-point passed it through
        "linked-by-construction". Now the search hit
        (``kernel_confirmed=False``) fails the kernel-linkage half and the
        pipeline caps to ``abstained``; the raw hit stays in the skeptic
        trail for audit. The task is ``known_truth=None`` so the round-2
        escalation net is inert — the choke-point is the only guard."""
        task = _task(
            task_id="d6-adv-search-unlinked",
            statement_latex="There are infinitely many prime numbers.",
            statement_nl="There are infinitely many prime numbers.",
            field_lane="math.NT",
            known_truth=None,
            budget={"wall_clock_s": 600, "lean_queries": 8, "prover_cycles": 2},
            skeptic_checks={
                "lean": [
                    {
                        "name": "unrelated-search",
                        "kind": "search",
                        # NOT the claim — a FALSE proposition plausible
                        # refutes (n=3 breaks n<3). search kind carries no
                        # discharges (it was "linked by construction").
                        "snippet": "example : ∀ n : Nat, n < 3 := by plausible",
                        "imports": list(_IMPORTS),
                    }
                ]
            },
        )

        async def _go():
            return await run_proving_pipeline(
                task=task, role_outputs=RoleOutputs(), lean_verify=_verifier
            )

        result = _run(_with_real_repl(_go))
        print(f"\n[adv/search] pipeline verdict={result.verdict}")
        assert result.verdict == "abstained", result.verdict_reasons
        assert result.verdict != "refuted"
        assert any("choke-point" in r for r in result.verdict_reasons)
        payload = result.bundle["payload"]
        assert "counterexample" not in payload
        assert payload["skeptic"]["refuted"] is True  # raw hit still audited
        validate_evidence_bundle(result.bundle)

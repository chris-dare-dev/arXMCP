"""Tests for the KAT suite harness + v1 fixture
(stage2/arx-d2 — WS-D D-4; AC-D.7/AC-D.8/AC-D.9).

Offline and LLM/REPL-free: fixture structural validation, control
sampling determinism, run scoring, the red-alarm escalation rule (any
proven-* on FALSE-must-reject or OPEN-must-abstain ⇒ escalated halt +
loud artifact), and the formal-lane bridge predicates. The real-REPL
integration tier lives in ``tests/eval/test_kat_lean.py``.
"""

from __future__ import annotations

import json
import logging

import pytest

from server.kat import (
    ACCEPTABLE_VERDICTS,
    FALSE_MUST_REJECT,
    KAT_CLASSES,
    MIN_ENTRIES_PER_CLASS,
    OPEN_MUST_ABSTAIN,
    TRUE_KNOWN_FORMAL,
    TRUE_KNOWN_INFORMAL,
    KatEscalation,
    KatFixtureError,
    entries_by_class,
    entry_index,
    evaluate_run,
    formal_verdict,
    load_kat_fixture,
    raise_if_escalated,
    sample_controls,
    witness_ok,
)
from server.lean_soundness import scan_snippet


@pytest.fixture(scope="module")
def fixture():
    return load_kat_fixture()


# ===========================================================================
# Fixture structure (AC-D.7)
# ===========================================================================


class TestFixtureV1:
    def test_loads_and_validates(self, fixture):
        assert fixture["kat_version"] == 1

    def test_every_class_meets_v1_floor(self, fixture):
        by_class = entries_by_class(fixture)
        for cls in KAT_CLASSES:
            assert len(by_class[cls]) >= MIN_ENTRIES_PER_CLASS, (
                f"{cls}: {len(by_class[cls])} < {MIN_ENTRIES_PER_CLASS}"
            )

    def test_acceptance_seed_statements_present(self, fixture):
        """The concrete seeds enumerated in acceptance-criteria.md §WS-D
        must appear: the FALSE small-counterexample trio + the humility
        pair + the three named OPEN seeds."""
        nl = " ".join(e["statement_nl"] for e in fixture["entries"]).lower()
        for fragment in (
            "order 6",            # S3 seed
            "n² + n + 41",        # Euler polynomial
            "fermat",             # F5
            "sum of two irrational",
            "pólya",              # large-counterexample humility
            "mertens",            # no-explicit-counterexample humility
            "goldbach",
            "twin prime",
            "euler-mascheroni",   # irrationality of γ
        ):
            assert fragment in nl, f"seed statement missing: {fragment!r}"

    def test_controls_available_per_class_needed(self, fixture):
        """AC-D.8 needs ≥1 control-eligible entry in TF / FALSE / OPEN."""
        by_class = entries_by_class(fixture)
        for cls in (TRUE_KNOWN_FORMAL, FALSE_MUST_REJECT, OPEN_MUST_ABSTAIN):
            assert any(e.get("control_eligible") for e in by_class[cls])

    def test_formal_snippets_pass_the_d2_snippet_guard(self, fixture):
        """Consistency between the instruments: no fixture snippet may
        itself trip the D-2 guard or carry award-denying flags."""
        for entry in fixture["entries"]:
            snippets = []
            formal = entry.get("formal") or {}
            if formal.get("snippet"):
                snippets.append(formal["snippet"])
            witness = (entry.get("counterexample") or {}).get("witness_lean")
            if witness:
                snippets.append(witness["snippet"])
            for snippet in snippets:
                scan = scan_snippet(snippet)
                assert not scan.rejected, (entry["id"], scan.rejected_keywords)
                assert not scan.flags, (entry["id"], scan.flags)

    def test_true_informal_entries_never_expect_proven_formal(self, fixture):
        for entry in entries_by_class(fixture)[TRUE_KNOWN_INFORMAL]:
            assert "proven-formal" not in entry["expected_verdicts"]


class TestFixtureValidationRejectsBadFixtures:
    def _write(self, tmp_path, fixture_dict):
        p = tmp_path / "kat_bad.json"
        p.write_text(json.dumps(fixture_dict), encoding="utf-8")
        return p

    def _minimal_entries(self):
        """40 structurally-valid entries (10 per class)."""
        entries = []
        for cls, truth, extra in (
            (TRUE_KNOWN_FORMAL, True, {}),
            (TRUE_KNOWN_INFORMAL, True, {}),
            (
                FALSE_MUST_REJECT,
                False,
                {"counterexample": {"description": "cx"}},
            ),
            (OPEN_MUST_ABSTAIN, None, {}),
        ):
            for i in range(10):
                entry = {
                    "id": f"{cls}-{i}",
                    "class": cls,
                    "statement_nl": "s",
                    "known_truth": truth,
                    "expected_verdicts": sorted(ACCEPTABLE_VERDICTS[cls])[:1],
                    **extra,
                }
                if cls == FALSE_MUST_REJECT:
                    entry["false_kind"] = [
                        "mutation",
                        "historical",
                        "small-counterexample",
                        "large-counterexample",
                    ][i % 4]
                entries.append(entry)
        return entries

    def test_minimal_synthetic_fixture_is_valid(self, tmp_path):
        p = self._write(
            tmp_path, {"kat_version": 1, "entries": self._minimal_entries()}
        )
        assert load_kat_fixture(p)["kat_version"] == 1

    @pytest.mark.parametrize(
        ("mutate", "match"),
        [
            (lambda f: f.update(kat_version="one"), "kat_version"),
            (lambda f: f.update(entries=[]), "no entries"),
            (
                lambda f: f["entries"][0].update(id=f["entries"][1]["id"]),
                "duplicate id",
            ),
            (lambda f: f["entries"][0].update({"class": "BOGUS"}), "unknown class"),
            (
                lambda f: f["entries"][0].update(known_truth=False),
                "inconsistent with class",
            ),
            (
                lambda f: f["entries"][0].update(
                    expected_verdicts=["refuted"]
                ),
                "expected_verdicts",
            ),
            (
                lambda f: f["entries"][20].pop("counterexample"),
                "counterexample",
            ),
            (
                lambda f: f["entries"][20].update(false_kind="bogus"),
                "false_kind",
            ),
            (lambda f: f["entries"].pop(0), "floor is 10"),
        ],
    )
    def test_structural_violations_raise(self, tmp_path, mutate, match):
        fixture = {"kat_version": 1, "entries": self._minimal_entries()}
        mutate(fixture)
        p = self._write(tmp_path, fixture)
        with pytest.raises(KatFixtureError, match=match):
            load_kat_fixture(p)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(KatFixtureError, match="cannot read"):
            load_kat_fixture(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(KatFixtureError, match="not valid JSON"):
            load_kat_fixture(p)

    def test_missing_false_kind_coverage_raises(self, tmp_path):
        fixture = {"kat_version": 1, "entries": self._minimal_entries()}
        for e in fixture["entries"]:
            if e["class"] == FALSE_MUST_REJECT:
                e["false_kind"] = "mutation"
        p = self._write(tmp_path, fixture)
        with pytest.raises(KatFixtureError, match="missing"):
            load_kat_fixture(p)


# ===========================================================================
# Control sampling (AC-D.8)
# ===========================================================================


class TestSampleControls:
    def test_deterministic_for_seed(self, fixture):
        a = [e["id"] for e in sample_controls(fixture, seed=42)]
        b = [e["id"] for e in sample_controls(fixture, seed=42)]
        assert a == b

    def test_different_seed_can_differ(self, fixture):
        seen = {
            tuple(e["id"] for e in sample_controls(fixture, seed=s))
            for s in range(20)
        }
        assert len(seen) > 1, "20 seeds all produced the same controls"

    def test_class_floors_enforced(self, fixture):
        controls = sample_controls(fixture, seed=7)
        classes = [e["class"] for e in controls]
        assert TRUE_KNOWN_FORMAL in classes
        assert FALSE_MUST_REJECT in classes
        assert OPEN_MUST_ABSTAIN in classes

    def test_zero_floor_rejected(self, fixture):
        with pytest.raises(ValueError, match="AC-D.8"):
            sample_controls(fixture, seed=1, n_false=0)

    def test_only_control_eligible_entries_sampled(self, fixture):
        for _seed in range(10):
            for e in sample_controls(fixture, seed=_seed, n_false=3, n_open=3):
                assert e.get("control_eligible") is True

    def test_over_request_raises(self, fixture):
        with pytest.raises(KatFixtureError, match="control-eligible"):
            sample_controls(fixture, seed=1, n_open=999)


# ===========================================================================
# Run evaluation + the red-alarm escalation rule (AC-D.9)
# ===========================================================================


class TestEvaluateRun:
    def test_all_expected_verdicts_reportable(self, fixture, tmp_path):
        verdicts = {
            e["id"]: e["expected_verdicts"][0] for e in fixture["entries"]
        }
        report = evaluate_run(fixture, verdicts, artifact_dir=tmp_path)
        assert report.escalated is False
        assert report.reportable is True
        assert report.red_alarms == []
        assert report.artifact_path is None
        assert 0.0 < report.abstention_rate < 1.0
        total = sum(c["evaluated"] for c in report.per_class.values())
        assert total == len(fixture["entries"])
        assert all(c["failed"] == 0 for c in report.per_class.values())
        # No escalation ⇒ no loud artifact.
        assert list(tmp_path.iterdir()) == []
        # raise_if_escalated passes the report through.
        assert raise_if_escalated(report) is report

    def test_true_formal_miss_is_failure_not_alarm(self, fixture, tmp_path):
        """A capability gap (abstained on a TRUE-known-formal entry)
        fails the entry and the run report — but never escalates."""
        report = evaluate_run(
            fixture, {"kat-tf-01": "abstained"}, artifact_dir=tmp_path
        )
        assert report.escalated is False
        assert report.reportable is False  # control failed ⇒ non-reportable
        assert report.per_class[TRUE_KNOWN_FORMAL]["failed"] == 1

    def test_refuted_on_true_formal_escalates_with_loud_artifact(
        self, fixture, tmp_path, caplog
    ):
        """findings: refuted-verdict-skips-statement-linkage. The
        symmetric image of the FALSE-accept alarm: a `refuted` verdict
        on a TRUE-known-formal control is a false REFUTATION of a true
        theorem (a skeptic-lane witness sound in isolation but never
        checked for relevance to the claim). Unlike the `abstained` miss
        above (a capability gap, per AC-D.7), asserting a falsehood about
        a true theorem is a soundness failure — it must escalate + halt
        with a loud artifact, exactly like the proven-*-on-FALSE case."""
        with caplog.at_level(logging.CRITICAL, logger="server.kat"):
            report = evaluate_run(
                fixture,
                {
                    "kat-tf-01": "refuted",  # red alarm: false refutation
                    "kat-fm-02": "refuted",  # correct on a FALSE control
                    "kat-op-01": "abstained",
                },
                artifact_dir=tmp_path,
                run_id="testrun-refute",
            )
        assert report.escalated is True
        assert report.reportable is False
        # ONLY the TRUE control's refutation is the alarm; the FALSE
        # control's refutation is the correct, expected outcome.
        assert [o.entry_id for o in report.red_alarms] == ["kat-tf-01"]
        assert report.per_class[TRUE_KNOWN_FORMAL]["failed"] == 1
        # CRITICAL log fired.
        assert any(
            "KAT ESCALATION" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.CRITICAL
        )
        # Loud artifact written, self-describing.
        artifact = tmp_path / "KAT-ESCALATION-testrun-refute.json"
        assert str(artifact) == report.artifact_path
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert "RED ALARM" in payload["!!"]
        assert payload["report"]["red_alarms"][0]["entry_id"] == "kat-tf-01"
        # The halt primitive raises, naming the false refutation.
        with pytest.raises(KatEscalation, match="kat-tf-01=refuted"):
            raise_if_escalated(report)

    def test_true_informal_refuted_also_escalates(self, fixture, tmp_path):
        """The TRUE-known-informal class inherits the false-refutation
        alarm too (a known-true statement refuted is a soundness failure
        regardless of whether it was formally or informally established)."""
        tinf = next(
            e["id"] for e in fixture["entries"]
            if e["class"] == TRUE_KNOWN_INFORMAL
        )
        report = evaluate_run(
            fixture, {tinf: "refuted"}, artifact_dir=tmp_path
        )
        assert report.escalated is True
        assert [o.entry_id for o in report.red_alarms] == [tinf]

    def test_proven_formal_on_false_escalates_with_loud_artifact(
        self, fixture, tmp_path, caplog
    ):
        """THE harness rule: any proven-* verdict on a FALSE control ⇒
        immediate escalated halt with a loud artifact."""
        with caplog.at_level(logging.CRITICAL, logger="server.kat"):
            report = evaluate_run(
                fixture,
                {
                    "kat-fm-02": "proven-formal",  # red alarm
                    "kat-op-01": "abstained",
                    "kat-tf-05": "proven-formal",
                },
                artifact_dir=tmp_path,
                run_id="testrun",
            )
        assert report.escalated is True
        assert report.reportable is False
        assert [o.entry_id for o in report.red_alarms] == ["kat-fm-02"]
        # CRITICAL log fired.
        assert any(
            "KAT ESCALATION" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.CRITICAL
        )
        # Loud artifact written, self-describing, machine-readable.
        artifact = tmp_path / "KAT-ESCALATION-testrun.json"
        assert str(artifact) == report.artifact_path
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert "RED ALARM" in payload["!!"]
        assert payload["report"]["escalated"] is True
        assert payload["report"]["red_alarms"][0]["entry_id"] == "kat-fm-02"
        # The halt primitive raises.
        with pytest.raises(KatEscalation, match="kat-fm-02=proven-formal"):
            raise_if_escalated(report)

    def test_proven_informal_on_open_escalates(self, fixture, tmp_path):
        """OPEN entries inherit the red-alarm rule (Tao-grade
        skepticism protocol: assume leakage/misformalization)."""
        report = evaluate_run(
            fixture,
            {"kat-op-05": "proven-informal-checked"},
            artifact_dir=tmp_path,
        )
        assert report.escalated is True
        assert len(list(tmp_path.iterdir())) == 1

    def test_small_cx_abstention_fails_without_alarm(self, fixture, tmp_path):
        """Abstaining on a small-counterexample FALSE entry is a
        skeptic-lane miss (fail), not a soundness alarm."""
        report = evaluate_run(
            fixture, {"kat-fm-02": "abstained"}, artifact_dir=tmp_path
        )
        assert report.escalated is False
        assert report.per_class[FALSE_MUST_REJECT]["failed"] == 1

    def test_humility_case_abstention_passes(self, fixture, tmp_path):
        """Pólya (large counterexample) accepts abstained — humility is
        the calibrated outcome there."""
        report = evaluate_run(
            fixture, {"kat-fm-07": "abstained"}, artifact_dir=tmp_path
        )
        assert report.reportable is True

    def test_missing_verdict_fails_entry(self, fixture, tmp_path):
        report = evaluate_run(
            fixture, {"kat-tf-01": None}, artifact_dir=tmp_path
        )
        assert report.escalated is False
        assert report.outcomes[0].ok is False

    def test_unknown_id_raises(self, fixture, tmp_path):
        with pytest.raises(KatFixtureError, match="unknown KAT ids"):
            evaluate_run(fixture, {"nope": "abstained"}, artifact_dir=tmp_path)

    def test_empty_verdicts_raise(self, fixture, tmp_path):
        with pytest.raises(KatFixtureError, match="no verdicts"):
            evaluate_run(fixture, {}, artifact_dir=tmp_path)

    def test_out_of_taxonomy_verdict_raises(self, fixture, tmp_path):
        with pytest.raises(KatFixtureError, match="taxonomy"):
            evaluate_run(
                fixture, {"kat-tf-01": "PROVED!!"}, artifact_dir=tmp_path
            )

    def test_abstention_rate_computed(self, fixture, tmp_path):
        report = evaluate_run(
            fixture,
            {
                "kat-op-01": "abstained",
                "kat-op-02": "abstained",
                "kat-tf-05": "proven-formal",
                "kat-fm-02": "refuted",
            },
            artifact_dir=tmp_path,
        )
        assert report.abstention_rate == pytest.approx(0.5)


# ===========================================================================
# Formal-lane bridge predicates
# ===========================================================================


def _award_worthy() -> dict:
    return {
        "status": "ok",
        "mode": "full",
        "compilation_success": True,
        "soundness": {
            "guard": "passed",
            "rejected_keywords": [],
            "flags": [],
            "audit_status": "ok",
            "audit_detail": None,
            "audited_decls": ["t"],
            "axioms_by_decl": {"t": ["propext"]},
            "axiom_closure": ["propext"],
            "axiom_closure_ok": True,
        },
    }


class TestFormalLaneBridge:
    def test_award_worthy_result_maps_to_proven_formal(self):
        assert formal_verdict(_award_worthy()) == "proven-formal"

    def test_anything_less_maps_to_abstained(self):
        r = _award_worthy()
        r["soundness"]["axiom_closure_ok"] = False
        assert formal_verdict(r) == "abstained"
        assert formal_verdict({}) == "abstained"
        assert formal_verdict({"status": "error"}) == "abstained"

    def test_witness_ok_accepts_clean_example_without_audit(self):
        """Anonymous `example` witnesses legitimately skip the
        per-declaration audit — audit 'skipped' is acceptable for a
        refutation witness; audit FAILED is not."""
        r = _award_worthy()
        r["soundness"].update(
            audit_status="skipped",
            audited_decls=[],
            axioms_by_decl=None,
            axiom_closure=None,
            axiom_closure_ok=None,
        )
        assert witness_ok(r) is True

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda r: r.update(status="error"),
            lambda r: r.update(mode="syntax_only"),
            lambda r: r.update(compilation_success=None),
            lambda r: r["soundness"].update(guard="rejected"),
            lambda r: r["soundness"].update(flags=["native_decide"]),
            lambda r: r["soundness"].update(axiom_closure_ok=False),
        ],
    )
    def test_witness_ok_denies(self, mutate):
        r = _award_worthy()
        mutate(r)
        assert witness_ok(r) is False


class TestEntryIndex:
    def test_index_roundtrip(self, fixture):
        index = entry_index(fixture)
        assert index["kat-fm-02"]["class"] == FALSE_MUST_REJECT
        assert len(index) == len(fixture["entries"])

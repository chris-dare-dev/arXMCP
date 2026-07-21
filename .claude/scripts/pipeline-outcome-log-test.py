#!/usr/bin/env python3
"""pipeline-outcome-log-test.py — suite for pipeline-outcome-log.py.

Run: python3 pipeline-outcome-log-test.py   (exit 0 == all pass)

Stdlib only (unittest + importlib). Passes on native Windows: fcntl is
ImportError-guarded in the module under test, so the append path degrades to a
plain O_APPEND write there. No metric-emit tests and no default-branch
assumptions (both were upstream-platform-only concerns).
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MODULE_PATH = _HERE / "pipeline-outcome-log.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("pipeline_outcome_log", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


olog = _load_module()


def _write_state(path: Path, **overrides) -> Path:
    state = {
        "id": "demo-m1",
        "created_at": "2026-07-09T10:00:00Z",
        "updated_at": "2026-07-09T12:00:00Z",
        "phase": "complete",
        "critique_finding_counts": {"critical": 0, "high": 2, "medium": 1, "low": 0},
        "fixed_findings": ["H1", "H2"],
        "rectification_commit": "abc1234",
    }
    state.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


class OutcomeLogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()
        self._saved_env = {
            k: os.environ.get(k) for k in ("REPO_ROOT", "PIPELINE_OUTCOME_LOG")
        }
        os.environ["REPO_ROOT"] = str(self.root)
        os.environ.pop("PIPELINE_OUTCOME_LOG", None)

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    # 1
    def test_repo_root_env(self):
        self.assertEqual(olog.find_repo_root(), self.root.resolve())

    # 2
    def test_default_log_path(self):
        p = olog.resolve_log_path(self.root)
        self.assertEqual(
            p, self.root / ".claude" / "notes" / "pipeline-outcomes" / "outcomes.jsonl"
        )

    # 3
    def test_env_override_log_path(self):
        target = self.root / "custom" / "log.jsonl"
        os.environ["PIPELINE_OUTCOME_LOG"] = str(target)
        self.assertEqual(olog.resolve_log_path(self.root), target)

    # 4
    def test_explicit_override_beats_env(self):
        os.environ["PIPELINE_OUTCOME_LOG"] = str(self.root / "env.jsonl")
        explicit = str(self.root / "explicit.jsonl")
        self.assertEqual(olog.resolve_log_path(self.root, explicit), Path(explicit))

    # 5
    def test_emit_writes_one_line(self):
        rc = olog.main(["emit", "--pipeline", "milestone", "--id", "demo-m1"])
        self.assertEqual(rc, 0)
        log = olog.resolve_log_path(self.root)
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)

    # 6
    def test_record_has_stable_columns(self):
        rec = olog.build_record("milestone", "demo-m1", None, None)
        for key in (
            "schema_version",
            "run_id",
            "emitted_at",
            "pipeline",
            "id",
            "source_state_path",
            "outcome",
            "critique_finding_counts",
            "fixed_findings",
            "rectification_count",
            "candidate_count",
            "challenge_finding_counts",
            "token_cost",
        ):
            self.assertIn(key, rec)
        self.assertEqual(rec["schema_version"], olog.SCHEMA_VERSION)

    # 7
    def test_token_cost_null(self):
        rec = olog.build_record("milestone", "demo-m1", None, None)
        self.assertIsNone(rec["token_cost"])

    # 8
    def test_discovery_columns_null(self):
        rec = olog.build_record("milestone", "demo-m1", None, None)
        self.assertIsNone(rec["candidate_count"])
        self.assertIsNone(rec["challenge_finding_counts"])

    # 9
    def test_reads_state_columns(self):
        sp = _write_state(
            self.root / ".claude" / "notes" / "milestones" / "demo-m1" / "state.json"
        )
        rec = olog.build_record("milestone", "demo-m1", str(sp), None)
        self.assertEqual(rec["created_at"], "2026-07-09T10:00:00Z")
        self.assertEqual(rec["phase"], "complete")
        self.assertEqual(rec["outcome"], "complete")
        self.assertEqual(rec["critique_finding_counts"]["high"], 2)

    # 10
    def test_rectification_count_is_len_fixed(self):
        sp = _write_state(
            self.root / ".claude" / "notes" / "milestones" / "demo-m1" / "state.json",
            fixed_findings=["C1", "H1", "H2"],
        )
        rec = olog.build_record("milestone", "demo-m1", str(sp), None)
        self.assertEqual(rec["rectification_count"], 3)
        self.assertEqual(rec["fixed_findings"], ["C1", "H1", "H2"])

    # 11
    def test_field_override_and_extra(self):
        rec = olog.build_record(
            "milestone", "demo-m1", None, ["outcome=complete", "note=hello world"]
        )
        self.assertEqual(rec["outcome"], "complete")
        self.assertEqual(rec["note"], "hello world")

    # 12
    def test_roadmap_source_path_via_field(self):
        rec = olog.build_record(
            "roadmap",
            "arxmcp-v2",
            None,
            ["source_state_path=plans/arxmcp-v2/roadmap.yaml", "outcome=complete"],
        )
        self.assertEqual(rec["source_state_path"], "plans/arxmcp-v2/roadmap.yaml")
        self.assertEqual(rec["pipeline"], "roadmap")
        self.assertEqual(rec["outcome"], "complete")

    # 13
    def test_summary_filters_and_json(self):
        olog.main(["emit", "--pipeline", "milestone", "--id", "demo-m1"])
        olog.main(["emit", "--pipeline", "roadmap", "--id", "arxmcp-v2"])
        log = olog.resolve_log_path(self.root)
        recs = olog.read_records(log)
        self.assertEqual(len(recs), 2)
        milestone_only = [r for r in recs if r["pipeline"] == "milestone"]
        self.assertEqual(len(milestone_only), 1)

    # 14 -- emit-race fix (OSE review 2026-07-16): a terminal emit that lands
    # before the caller's phase flip must still record the DECLARED outcome.
    def test_declared_outcome_wins_over_stale_phase(self):
        sp = _write_state(
            self.root / ".claude" / "notes" / "milestones" / "demo-m1" / "state.json",
            phase="rectify-running",
        )
        rec = olog.build_record("milestone", "demo-m1", str(sp), None, outcome="complete")
        self.assertEqual(rec["outcome"], "complete")
        # The state-read phase stays visible verbatim -- the lag is auditable,
        # never laundered into a fabricated phase.
        self.assertEqual(rec["phase"], "rectify-running")

    # 15 -- --field is applied last and still beats the declared outcome.
    def test_field_override_still_beats_declared_outcome(self):
        rec = olog.build_record(
            "milestone", "demo-m1", None, ["outcome=abandoned"], outcome="complete"
        )
        self.assertEqual(rec["outcome"], "abandoned")

    # 16 -- without --outcome the snapshot behaviour is unchanged.
    def test_no_declared_outcome_preserves_snapshot_behaviour(self):
        sp = _write_state(
            self.root / ".claude" / "notes" / "milestones" / "demo-m1" / "state.json",
            phase="rectify-running",
        )
        rec = olog.build_record("milestone", "demo-m1", str(sp), None)
        self.assertEqual(rec["outcome"], "rectify-running")
        self.assertEqual(rec["phase"], "rectify-running")

    # 17 -- CLI end-to-end: emit --outcome writes the declared outcome, keeps
    # the stale phase column, and still exits 0 (best-effort contract).
    def test_emit_outcome_flag_end_to_end(self):
        sp = _write_state(
            self.root / ".claude" / "notes" / "milestones" / "demo-m1" / "state.json",
            phase="rectify-running",
        )
        rc = olog.main(
            ["emit", "--pipeline", "milestone", "--id", "demo-m1",
             "--state", str(sp), "--outcome", "complete"]
        )
        self.assertEqual(rc, 0)
        recs = olog.read_records(olog.resolve_log_path(self.root))
        self.assertEqual(recs[-1]["outcome"], "complete")
        self.assertEqual(recs[-1]["phase"], "rectify-running")

    # bonus: best-effort emit never raises even if state path is bogus
    def test_emit_tolerates_missing_state(self):
        rc = olog.main(
            ["emit", "--pipeline", "milestone", "--id", "demo-m1",
             "--state", "/no/such/state.json"]
        )
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Tests for the LaTeXML drift detector (E10_S04).

Two layers:

* **Default (fast, no LaTeXML).** Mock-based tests of the diff
  logic, exit codes, sentinel file behavior, counter increment, and
  `--update-fixtures` plumbing. These tests run on every
  `make test`.
* **Integration (slow, real `latexmlc`).** Marked
  `@pytest.mark.requires_latexmlc`. Skipped by default; opt-in via
  `pytest -m requires_latexmlc`. Renders the actual `.tex` fixtures
  and asserts no drift against the checked-in baselines.

The integration layer is the AC1 closure ("running the drift-check
script against the current LaTeXML image produces zero alerts");
the mock layer is the AC2/AC3 closure (modifying a baseline → exit
non-zero + counter increment).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from ops.drift_check import (
    DEFAULT_FIXTURE_DIR,
    EXPECTED_SUFFIX,
    DriftResult,
    _cli,
    check_all_fixtures,
    check_fixture,
    clear_sentinel,
    expected_path_for,
    extract_canonical_mathml,
    list_fixtures,
    render_fixture,
    write_sentinel,
)
from server.metrics import (
    LATEXML_DRIFT_DETECTED_COUNTER,
    reset_drift_metrics_for_tests,
)

FIXTURE_NAMES = {"frac", "integral", "sum", "align", "pmatrix"}


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_drift_metrics():
    """Reset the LaTeXML drift counter between tests so per-test
    assertions on `.inc()` calls don't leak across tests."""
    reset_drift_metrics_for_tests()
    yield
    reset_drift_metrics_for_tests()


@pytest.fixture
def fixture_dir() -> Path:
    """The checked-in fixture directory; tests read from it but do
    not write."""
    return DEFAULT_FIXTURE_DIR


@pytest.fixture
def tmp_fixture_dir(tmp_path: Path) -> Path:
    """A tmp_path-scoped copy of the fixture directory so tests that
    need to mutate baselines (e.g. simulate drift) don't dirty the
    checked-in files. Copies every `.tex` and `.expected.mathml`."""
    dst = tmp_path / "drift-fixtures"
    dst.mkdir()
    for src in DEFAULT_FIXTURE_DIR.glob("*.tex"):
        shutil.copy(src, dst / src.name)
        expected = src.with_suffix(EXPECTED_SUFFIX)
        if expected.exists():
            shutil.copy(expected, dst / expected.name)
    return dst


# ===========================================================================
# Pure helpers
# ===========================================================================


class TestListFixtures:
    def test_returns_five_fixtures_sorted(self, fixture_dir):
        fixtures = list_fixtures(fixture_dir)
        names = [p.stem for p in fixtures]
        assert set(names) == FIXTURE_NAMES
        # Sorted alphabetically.
        assert names == sorted(names)

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="does not exist"):
            list_fixtures(tmp_path / "nope")


class TestExpectedPathFor:
    def test_maps_tex_to_expected(self, fixture_dir):
        tex = fixture_dir / "frac.tex"
        expected = expected_path_for(tex)
        assert expected.name == "frac.expected.mathml"
        assert expected.is_file()


class TestExtractCanonicalMathML:
    def test_extracts_math_elements(self):
        html = (
            "<html><body>"
            '<p>prose with <math alttext="x"><mi>x</mi></math></p>'
            '<math display="block"><mfrac><mi>a</mi><mi>b</mi></mfrac></math>'
            "</body></html>"
        )
        result = extract_canonical_mathml(html)
        # Two <math> elements joined by newline.
        assert result.count("<math") == 2
        assert "<mfrac>" in result

    def test_html_without_math_returns_empty(self):
        html = "<html><body><p>no math here</p></body></html>"
        assert extract_canonical_mathml(html) == ""


# ===========================================================================
# Diff logic (mock-based — no real latexmlc)
# ===========================================================================


class TestCheckFixtureMocked:
    def test_no_drift_when_actual_matches_expected(self, tmp_fixture_dir):
        """AC1 mock-layer: when the freshly-rendered MathML matches
        the baseline, the result is `drifted=False` and the counter
        does NOT increment."""
        tex = tmp_fixture_dir / "frac.tex"
        expected = expected_path_for(tex).read_text(encoding="utf-8")

        # Stub render_fixture / extract_canonical_mathml to return
        # the same string the baseline holds.
        with patch(
            "ops.drift_check.render_fixture", return_value="<html/>",
        ), patch(
            "ops.drift_check.extract_canonical_mathml",
            return_value=expected,
        ):
            result = check_fixture(tex)

        assert not result.drifted
        assert result.actual == result.expected
        # Counter did NOT increment.
        sample = LATEXML_DRIFT_DETECTED_COUNTER.labels(
            fixture="frac"
        )._value.get()
        assert sample == 0

    def test_drift_increments_counter(self, tmp_fixture_dir):
        """AC2 + AC3: modify the expected baseline so the diff
        triggers; assert `drifted=True` AND the counter incremented
        by 1 with the correct label."""
        tex = tmp_fixture_dir / "frac.tex"
        # Bake a mismatch by stubbing the actual side.
        with patch(
            "ops.drift_check.render_fixture", return_value="<html/>",
        ), patch(
            "ops.drift_check.extract_canonical_mathml",
            return_value="<math><mi>DIFFERENT</mi></math>",
        ):
            result = check_fixture(tex)

        assert result.drifted
        assert result.actual != result.expected
        sample = LATEXML_DRIFT_DETECTED_COUNTER.labels(
            fixture="frac"
        )._value.get()
        assert sample == 1

    def test_check_all_fixtures_returns_per_fixture(
        self, tmp_fixture_dir
    ):
        with patch(
            "ops.drift_check.render_fixture", return_value="<html/>",
        ), patch(
            "ops.drift_check.extract_canonical_mathml", return_value="",
        ):
            results = check_all_fixtures(tmp_fixture_dir)
        # Five fixtures, all drifted (empty actual vs non-empty
        # expected).
        assert len(results) == 5
        assert all(isinstance(r, DriftResult) for r in results)
        # Counter incremented for every fixture name.
        for name in FIXTURE_NAMES:
            sample = LATEXML_DRIFT_DETECTED_COUNTER.labels(
                fixture=name
            )._value.get()
            assert sample == 1


# ===========================================================================
# Sentinel file
# ===========================================================================


class TestSentinel:
    def test_write_creates_file_with_content(self, tmp_path):
        sentinel = tmp_path / "drift.flag"
        write_sentinel(sentinel)
        assert sentinel.is_file()
        assert "drift-detected" in sentinel.read_text()

    def test_clear_removes_file(self, tmp_path):
        sentinel = tmp_path / "drift.flag"
        sentinel.write_text("x")
        clear_sentinel(sentinel)
        assert not sentinel.exists()

    def test_clear_is_idempotent_when_absent(self, tmp_path):
        sentinel = tmp_path / "drift.flag"
        # Should not raise.
        clear_sentinel(sentinel)


# ===========================================================================
# CLI
# ===========================================================================


class TestCLI:
    def test_cli_exits_zero_on_no_drift(
        self, tmp_fixture_dir, tmp_path, capsys
    ):
        """F1 regression (E10_S04 critique) — AC1 CLI happy path: when
        every fixture's actual MathML matches its own baseline, the
        CLI exits 0, prints ``ok``, and does NOT write the sentinel.

        The prior version of this test asserted ``rc == 1`` because a
        static mock returning a single baseline string only matched
        ``frac`` (the other 4 fixtures drifted against frac's content).
        That assertion was correct for THAT mock, but the test name +
        docstring promised the happy path. The fix: patch
        ``check_fixture`` directly to return a non-drifted
        :class:`DriftResult` for every fixture, exercising the all-pass
        CLI branch.
        """
        sentinel = tmp_path / "drift.flag"

        def _no_drift(tex_path):
            return DriftResult(
                name=tex_path.stem,
                drifted=False,
                actual="<math/>",
                expected="<math/>",
                message=f"{tex_path.stem}: ok",
            )

        with patch("ops.drift_check.check_fixture", side_effect=_no_drift):
            rc = _cli(
                [
                    "--fixture-dir",
                    str(tmp_fixture_dir),
                    "--sentinel-path",
                    str(sentinel),
                ]
            )

        out, _err = capsys.readouterr()
        assert rc == 0, "CLI must exit 0 when no fixture drifted"
        assert not sentinel.exists(), (
            "sentinel file must not be written on the happy path"
        )
        assert "ok:" in out, f"expected 'ok:' in stdout, got {out!r}"

    def test_cli_exits_one_on_drift(
        self, tmp_fixture_dir, tmp_path, capsys
    ):
        """AC2 CLI-layer: when drift is detected, the CLI exits 1
        AND writes the sentinel file."""
        sentinel = tmp_path / "drift.flag"

        with patch(
            "ops.drift_check.render_fixture", return_value="<html/>",
        ), patch(
            "ops.drift_check.extract_canonical_mathml", return_value="",
        ):
            rc = _cli(
                [
                    "--fixture-dir",
                    str(tmp_fixture_dir),
                    "--sentinel-path",
                    str(sentinel),
                ]
            )
        assert rc == 1
        assert sentinel.is_file()

    def test_update_fixtures_refuses_empty_actual(
        self, tmp_fixture_dir
    ):
        """F2 regression (E10_S04 critique) — ``update_fixtures``
        MUST refuse to write empty baselines from a broken LaTeXML
        run. Without this guard, a silently-failing ``latexmlc`` that
        exits 0 with no ``<math>`` elements would overwrite every
        baseline with ``""``, and the next ``--check`` would silent-
        pass because ``"" == ""``. That's the corruption mode the
        drift detector exists to prevent.
        """
        from ops.drift_check import update_fixtures

        with (
            patch(
                "ops.drift_check.render_fixture", return_value="<html/>",
            ),
            patch(
                "ops.drift_check.extract_canonical_mathml", return_value="",
            ),
            pytest.raises(
                RuntimeError, match="refusing to write empty baselines"
            ),
        ):
            update_fixtures(tmp_fixture_dir)

    def test_update_fixtures_allow_empty_override(self, tmp_fixture_dir):
        """F2 close — the ``allow_empty=True`` escape hatch lets a
        legitimately math-free fixture rebase. No current fixture
        uses this, but the API stays consistent."""
        from ops.drift_check import update_fixtures

        with patch(
            "ops.drift_check.render_fixture", return_value="<html/>",
        ), patch(
            "ops.drift_check.extract_canonical_mathml", return_value="",
        ):
            updated = update_fixtures(tmp_fixture_dir, allow_empty=True)
        assert set(updated) == FIXTURE_NAMES
        for tex in list_fixtures(tmp_fixture_dir):
            assert expected_path_for(tex).read_text(encoding="utf-8") == ""

    def test_check_fixture_with_missing_baseline_drifts(
        self, tmp_path
    ):
        """F9 regression (E10_S04 critique) — a fixture added without
        a matching ``.expected.mathml`` file MUST be flagged as
        drift. ``_read_expected`` returns ``""`` when the baseline
        is absent, so the diff against any non-empty actual
        correctly drifts. This pins that contract so a future
        refactor (e.g. raising on missing baseline instead) doesn't
        ship undetected.
        """
        # Stage a single .tex with NO matching .expected.mathml.
        new_tex = tmp_path / "fixtures" / "freshly_added.tex"
        new_tex.parent.mkdir(parents=True)
        new_tex.write_text(
            r"\documentclass{article}\usepackage{amsmath}"
            r"\begin{document}\begin{equation}x\end{equation}\end{document}"
            "\n",
            encoding="utf-8",
        )

        with patch(
            "ops.drift_check.render_fixture", return_value="<html/>",
        ), patch(
            "ops.drift_check.extract_canonical_mathml",
            return_value="<math><mi>x</mi></math>",
        ):
            result = check_fixture(new_tex)
        assert result.drifted, (
            "fixture without baseline must drift against non-empty actual"
        )
        assert result.expected == "", (
            "missing baseline should yield empty expected, not raise"
        )

    def test_cli_update_fixtures_writes_baselines(
        self, tmp_fixture_dir, tmp_path
    ):
        """The `--update-fixtures` flow regenerates every baseline."""
        sentinel = tmp_path / "drift.flag"
        with patch(
            "ops.drift_check.render_fixture", return_value="<html/>",
        ), patch(
            "ops.drift_check.extract_canonical_mathml",
            return_value="<math><mi>NEW</mi></math>",
        ):
            rc = _cli(
                [
                    "--fixture-dir",
                    str(tmp_fixture_dir),
                    "--sentinel-path",
                    str(sentinel),
                    "--update-fixtures",
                ]
            )
        assert rc == 0
        # Every baseline now contains the new content.
        for tex in list_fixtures(tmp_fixture_dir):
            expected = expected_path_for(tex)
            assert "<mi>NEW</mi>" in expected.read_text(encoding="utf-8")


# ===========================================================================
# Runbook content (AC4)
# ===========================================================================


class TestRunbookContent:
    def test_runbook_exists(self):
        runbook = (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "ops"
            / "latexml-drift-runbook.md"
        )
        assert runbook.is_file()

    def test_runbook_documents_timing_estimates(self):
        """AC4: the runbook includes timing estimates for the
        50-paper seed corpus AND the 200K-paper full corpus."""
        runbook = (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "ops"
            / "latexml-drift-runbook.md"
        ).read_text(encoding="utf-8")
        # Loose phrase matches — the exact wording can evolve.
        assert "50-paper" in runbook
        assert "200K" in runbook

    def test_runbook_references_extract_and_index_modules(self):
        """The runbook must reference the CORRECT modules
        (`ingest.extract_equations` + `ingest.index_equations`),
        NOT the brief's spurious `--rerender-all` flag.
        """
        runbook = (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "ops"
            / "latexml-drift-runbook.md"
        ).read_text(encoding="utf-8")
        assert "ingest.extract_equations" in runbook
        assert "ingest.index_equations" in runbook
        # The brief's non-existent flag must NOT appear (would be
        # a hint that someone copy-pasted from the brief without
        # verifying against the codebase).
        assert "--rerender-all" not in runbook


# ===========================================================================
# Integration — requires latexmlc on PATH
# ===========================================================================


@pytest.mark.requires_latexmlc
class TestIntegrationRealLatexmlc:
    """AC1 closure — the real cron path. Renders every checked-in
    fixture via the actual `latexmlc` binary and asserts no drift
    against the checked-in baselines.

    Skipped by default — opt in via `pytest -m requires_latexmlc`.
    Inside the marker, ``_require_latexmlc()`` will raise loudly if
    ``latexmlc`` is absent (F10 close — the previous additional
    ``skipif`` produced silent skips even on explicit opt-in, masking
    a "no PASS, no FAIL" outcome on CI dashboards).
    """

    def test_all_fixtures_match_baselines(self, fixture_dir):
        results = check_all_fixtures(fixture_dir)
        drifted = [r for r in results if r.drifted]
        assert not drifted, (
            "drift detected against current latexmlc — re-run "
            "`python -m ops.drift_check --update-fixtures` after "
            "confirming the LaTeXML upgrade is intentional. "
            f"Drifted: {[r.name for r in drifted]}"
        )

    def test_render_fixture_does_not_leave_log_artifact(
        self, fixture_dir, tmp_path
    ):
        """Regression — `latexmlc` writes a `.latexml.log` file
        alongside its input. The drift detector stages the `.tex`
        into a tmpdir so the log file does NOT land in the
        checked-in fixture dir.
        """
        tex = fixture_dir / "frac.tex"
        # Snapshot the directory before the call.
        before = set(fixture_dir.iterdir())
        render_fixture(tex)
        after = set(fixture_dir.iterdir())
        # No new files added to the checked-in fixture dir.
        assert after == before, (
            f"render_fixture added files to {fixture_dir}: "
            f"{after - before}"
        )


# ===========================================================================
# Missing latexmlc
# ===========================================================================


class TestMissingLatexmlc:
    def test_render_fixture_raises_when_latexmlc_absent(
        self, fixture_dir
    ):
        tex = fixture_dir / "frac.tex"
        with (
            patch("ops.drift_check.shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="latexmlc not found"),
        ):
            render_fixture(tex)


# ===========================================================================
# Metrics import surface
# ===========================================================================


class TestMetricsCounterExports:
    def test_counter_is_in_metrics_module(self):
        # Imported at module top; this is the regression guard that
        # the counter symbol stays exported with the contract name.
        assert LATEXML_DRIFT_DETECTED_COUNTER is not None
        # Verify the metric name matches the contract.
        assert (
            LATEXML_DRIFT_DETECTED_COUNTER._name
            == "arxmcp_latexml_drift_detected"
        )

    def test_reset_drift_metrics_for_tests_exported(self):
        from server.metrics import reset_drift_metrics_for_tests as fn

        # Should be callable without raising.
        fn()

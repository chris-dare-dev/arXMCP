"""Tests for tools/validate_notebook_fixtures.py (proof-verify-handler-wiring-m4).

Coverage matrix:

- test_validate_*_happy_path                — AC #4 (both real notebooks pass)
- test_validate_rejects_*                   — each REQUIRED_TOP_KEYS missing case
- test_validate_rejects_query_*             — each REQUIRED_QUERY_KEYS missing case
- test_validate_rejects_duplicate_id        — duplicate query id catch
- test_validate_rejects_invalid_paper_id    — is_valid_paper_id reject
- test_validate_rejects_unknown_paper_id    — papers.txt membership reject
- test_validate_rejects_short_queries_list  — MIN_NOTEBOOK_QUERIES floor
- test_validate_rejects_slug_mismatch       — CLI slug vs queries.json mismatch
- test_validate_rejects_missing_*           — IO error paths
- test_cli_exit_codes                       — CLI exit-code contract

All tests use ``tmp_path`` plus a redirected NOTEBOOKS_BASE so they
don't touch the live ``var/arxmcp/notebooks/`` tree. The two
happy-path tests against the real notebooks are kept SEPARATE and
opt-in via a small loader fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import _notebook_common, validate_notebook_fixtures
from tools.validate_notebook_fixtures import (
    MIN_NOTEBOOK_QUERIES,
    FixtureValidationError,
    main,
    validate_notebook_fixture,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect NOTEBOOKS_BASE so writes don't escape tmp_path."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(
        validate_notebook_fixtures, "notebook_dir",
        lambda slug: base / slug,
    )
    return base


def _make_papers_txt(nb_dir: Path, paper_ids: list[str]) -> None:
    nb_dir.mkdir(parents=True, exist_ok=True)
    (nb_dir / "papers.txt").write_text(
        "# header comment\n" + "\n".join(paper_ids) + "\n",
        encoding="utf-8",
    )


def _make_queries_json(
    nb_dir: Path,
    slug: str,
    *,
    n_queries: int = 6,
    paper_id_pool: list[str] | None = None,
    overrides: dict | None = None,
) -> dict:
    """Build a minimal-but-valid notebook queries.json and write it
    to ``nb_dir/queries.json``. ``overrides`` is shallow-merged into
    the top-level dict so individual tests can break specific keys."""
    if paper_id_pool is None:
        paper_id_pool = ["2604.26204", "0712.1083"]
    queries = [
        {
            "id": f"{slug}-q{i+1}",
            "difficulty": "easy",
            "text": f"Sample query text number {i+1}",
            "expected_relevant_papers": [paper_id_pool[i % len(paper_id_pool)]],
        }
        for i in range(n_queries)
    ]
    data = {
        "schema_version": "1.0",
        "notebook_slug": slug,
        "notebook_display_name": slug.replace("-", " ").title(),
        "created_at": "2026-05-22",
        "queries": queries,
    }
    if overrides:
        data.update(overrides)
    nb_dir.mkdir(parents=True, exist_ok=True)
    (nb_dir / "queries.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    return data


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPath:
    """End-to-end pass on synthetic + real fixtures."""

    def test_minimal_valid_fixture_passes(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204", "0712.1083"])
        _make_queries_json(nb, "demo-nb")
        data = validate_notebook_fixture("demo-nb")
        assert data["notebook_slug"] == "demo-nb"
        assert len(data["queries"]) == 6

    def test_real_bridgeland_notebook_validates(self) -> None:
        """Smoke-test against the actual on-disk bridgeland fixture.

        Hard pin — if curation changes the schema in a way that breaks
        the validator, both this test and the validator must move
        together. Currently 39 papers + 10 queries.
        """
        data = validate_notebook_fixture("bridgeland-stability")
        assert data["notebook_slug"] == "bridgeland-stability"
        assert len(data["queries"]) >= MIN_NOTEBOOK_QUERIES

    def test_real_shimura_notebook_validates(self) -> None:
        """Smoke-test against the actual on-disk shimura fixture.

        12 HTML papers + 10 queries; the 2 deferred PDFs are in
        ``pdf-deferred/`` and don't appear in ``papers.txt`` so the
        ``expected_relevant_papers`` membership check passes.
        """
        data = validate_notebook_fixture("shimura-varieties")
        assert data["notebook_slug"] == "shimura-varieties"
        assert len(data["queries"]) >= MIN_NOTEBOOK_QUERIES


# ---------------------------------------------------------------------------
# Top-level structural checks
# ---------------------------------------------------------------------------


class TestTopLevelStructure:
    def test_missing_papers_txt_rejected(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        _make_queries_json(nb, "demo-nb")  # creates dir, no papers.txt
        with pytest.raises(FixtureValidationError, match="papers.txt not found"):
            validate_notebook_fixture("demo-nb")

    def test_missing_queries_json_rejected(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204"])
        with pytest.raises(FixtureValidationError, match="queries.json not found"):
            validate_notebook_fixture("demo-nb")

    def test_empty_papers_txt_rejected(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        nb.mkdir()
        (nb / "papers.txt").write_text("# only a comment\n", encoding="utf-8")
        _make_queries_json(nb, "demo-nb")
        with pytest.raises(
            FixtureValidationError, match="contains no valid paper IDs"
        ):
            validate_notebook_fixture("demo-nb")

    def test_invalid_json_rejected(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204"])
        nb.mkdir(exist_ok=True)
        (nb / "queries.json").write_text("{this is not json", encoding="utf-8")
        with pytest.raises(FixtureValidationError, match="not valid JSON"):
            validate_notebook_fixture("demo-nb")

    def test_non_object_root_rejected(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204"])
        nb.mkdir(exist_ok=True)
        (nb / "queries.json").write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(
            FixtureValidationError, match="must be a JSON object"
        ):
            validate_notebook_fixture("demo-nb")

    @pytest.mark.parametrize(
        "drop_key",
        ["schema_version", "notebook_slug", "notebook_display_name",
         "created_at", "queries"],
    )
    def test_each_required_top_key_missing_rejected(
        self, notebooks_base: Path, drop_key: str,
    ) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204"])
        data = _make_queries_json(nb, "demo-nb")
        del data[drop_key]
        (nb / "queries.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        with pytest.raises(
            FixtureValidationError, match="missing required top-level keys"
        ):
            validate_notebook_fixture("demo-nb")

    def test_slug_mismatch_rejected(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204"])
        _make_queries_json(nb, "demo-nb",
                           overrides={"notebook_slug": "wrong-slug"})
        with pytest.raises(
            FixtureValidationError, match="does not match CLI slug"
        ):
            validate_notebook_fixture("demo-nb")

    def test_queries_not_list_rejected(self, notebooks_base: Path) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204"])
        _make_queries_json(nb, "demo-nb", overrides={"queries": "not-a-list"})
        with pytest.raises(
            FixtureValidationError, match="'queries' must be a list"
        ):
            validate_notebook_fixture("demo-nb")

    def test_short_queries_list_rejected(self, notebooks_base: Path) -> None:
        """Below MIN_NOTEBOOK_QUERIES floor must fail."""
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204"])
        _make_queries_json(nb, "demo-nb", n_queries=MIN_NOTEBOOK_QUERIES - 1)
        with pytest.raises(
            FixtureValidationError, match="minimum is"
        ):
            validate_notebook_fixture("demo-nb")

    def test_exactly_min_queries_passes(self, notebooks_base: Path) -> None:
        """Boundary: exactly MIN_NOTEBOOK_QUERIES must pass."""
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204", "0712.1083"])
        _make_queries_json(nb, "demo-nb", n_queries=MIN_NOTEBOOK_QUERIES)
        data = validate_notebook_fixture("demo-nb")
        assert len(data["queries"]) == MIN_NOTEBOOK_QUERIES


# ---------------------------------------------------------------------------
# Per-query structural checks
# ---------------------------------------------------------------------------


class TestPerQueryStructure:
    def _setup(self, base: Path, slug: str = "demo-nb") -> Path:
        nb = base / slug
        _make_papers_txt(nb, ["2604.26204", "0712.1083"])
        return nb

    @pytest.mark.parametrize(
        "drop_key",
        ["id", "difficulty", "text", "expected_relevant_papers"],
    )
    def test_each_required_query_key_missing_rejected(
        self, notebooks_base: Path, drop_key: str,
    ) -> None:
        nb = self._setup(notebooks_base)
        data = _make_queries_json(nb, "demo-nb")
        del data["queries"][0][drop_key]
        (nb / "queries.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        with pytest.raises(
            FixtureValidationError, match="missing required keys"
        ):
            validate_notebook_fixture("demo-nb")

    def test_duplicate_query_id_rejected(self, notebooks_base: Path) -> None:
        nb = self._setup(notebooks_base)
        data = _make_queries_json(nb, "demo-nb")
        # Force a collision: copy q1's id onto q2.
        data["queries"][1]["id"] = data["queries"][0]["id"]
        (nb / "queries.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        with pytest.raises(FixtureValidationError, match="duplicate"):
            validate_notebook_fixture("demo-nb")

    def test_empty_expected_relevant_papers_rejected(
        self, notebooks_base: Path,
    ) -> None:
        nb = self._setup(notebooks_base)
        data = _make_queries_json(nb, "demo-nb")
        data["queries"][0]["expected_relevant_papers"] = []
        (nb / "queries.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        with pytest.raises(
            FixtureValidationError, match="must be a non-empty list"
        ):
            validate_notebook_fixture("demo-nb")

    def test_invalid_arxiv_id_rejected(self, notebooks_base: Path) -> None:
        nb = self._setup(notebooks_base)
        data = _make_queries_json(nb, "demo-nb")
        data["queries"][0]["expected_relevant_papers"] = ["NOT-A-PAPER-ID"]
        (nb / "queries.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        with pytest.raises(
            FixtureValidationError, match="is not a valid arXiv paper_id"
        ):
            validate_notebook_fixture("demo-nb")

    def test_paper_id_not_in_papers_txt_rejected(
        self, notebooks_base: Path,
    ) -> None:
        """Membership check: the validator catches a curator listing
        a relevant paper that isn't actually in the notebook's
        ingestable set. This is the FM the m4 brief was written for."""
        nb = self._setup(notebooks_base)
        data = _make_queries_json(nb, "demo-nb")
        # Valid format, but not in papers.txt (only 2604.26204 and
        # 0712.1083 were written).
        data["queries"][0]["expected_relevant_papers"] = ["1234.56789"]
        (nb / "queries.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        with pytest.raises(
            FixtureValidationError, match="is not in the notebook's papers.txt"
        ):
            validate_notebook_fixture("demo-nb")

    def test_blank_query_text_rejected(self, notebooks_base: Path) -> None:
        nb = self._setup(notebooks_base)
        data = _make_queries_json(nb, "demo-nb")
        data["queries"][0]["text"] = "   "
        (nb / "queries.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        with pytest.raises(
            FixtureValidationError, match="must be a non-empty string"
        ):
            validate_notebook_fixture("demo-nb")


# ---------------------------------------------------------------------------
# CLI exit-code contract
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_exit_0_on_valid(
        self, notebooks_base: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204", "0712.1083"])
        _make_queries_json(nb, "demo-nb")
        rc = main(["demo-nb"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK: demo-nb queries.json valid" in out

    def test_cli_exit_1_on_validation_fail(
        self, notebooks_base: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        nb = notebooks_base / "demo-nb"
        _make_papers_txt(nb, ["2604.26204", "0712.1083"])
        _make_queries_json(nb, "demo-nb",
                           overrides={"notebook_slug": "wrong"})
        rc = main(["demo-nb"])
        assert rc == 1
        err = capsys.readouterr().err
        assert err.startswith("FAIL:")

    def test_cli_exit_2_on_invalid_slug(
        self, notebooks_base: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["BAD/Slug"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "invalid notebook slug" in err

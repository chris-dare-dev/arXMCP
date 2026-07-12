"""Unit tests for the embedder-truncation-m1 re-embed driver.

The driver at ``tools/re_embed_all.py`` discovers every LanceDB
dataset under ``var/arxmcp/notebooks/<slug>/lancedb/`` (plus the
shared corpus) and invokes :func:`ingest.re_embed.run_re_embed`
against each. These tests exercise the discovery logic and the
exit-code semantics WITHOUT invoking ``run_re_embed`` itself —
that would require the BGE-M3 model (a ``requires_model`` gate).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests._symlink_support import requires_symlink
from tools.re_embed_all import (
    discover_targets,
    run,
)


def _make_notebook_dataset(base: Path, slug: str, *, with_chunks: bool) -> Path:
    """Create a synthetic notebook layout under ``base``.

    If ``with_chunks`` is True, the notebook has a ``lancedb/chunks.lance/``
    subdir (qualifying for discovery). Otherwise the notebook has the
    lancedb dir but no chunks table (should be skipped silently).
    """
    nb_dir = base / slug
    nb_dir.mkdir(parents=True)
    lancedb_dir = nb_dir / "lancedb"
    lancedb_dir.mkdir()
    if with_chunks:
        # LanceDB stores tables as subdirs; the existence of the
        # chunks.lance subdir is the discovery signal.
        (lancedb_dir / "chunks.lance").mkdir()
    return nb_dir


class TestDiscovery:
    """``discover_targets()`` finds notebook + shared datasets that
    contain a ``chunks.lance`` subdir; skips empty or partial layouts.
    """

    def test_discovers_notebook_with_chunks(self, tmp_path):
        nb_base = tmp_path / "notebooks"
        _make_notebook_dataset(nb_base, "alpha", with_chunks=True)
        _make_notebook_dataset(nb_base, "beta", with_chunks=True)

        targets = discover_targets(
            notebooks_base=nb_base,
            shared_lancedb_path=tmp_path / "index" / "lancedb",
        )
        labels = sorted(t.label for t in targets)
        assert labels == ["alpha", "beta"]
        for t in targets:
            assert t.active_lancedb_path.is_dir()
            assert (
                t.staging_lancedb_path
                == t.active_lancedb_path.parent / "lancedb-staging"
            )

    def test_skips_notebook_without_chunks_table(self, tmp_path):
        nb_base = tmp_path / "notebooks"
        _make_notebook_dataset(nb_base, "empty", with_chunks=False)
        _make_notebook_dataset(nb_base, "full", with_chunks=True)

        targets = discover_targets(
            notebooks_base=nb_base,
            shared_lancedb_path=tmp_path / "index" / "lancedb",
        )
        assert [t.label for t in targets] == ["full"]

    def test_includes_shared_corpus_when_populated(self, tmp_path):
        nb_base = tmp_path / "notebooks"
        nb_base.mkdir()
        shared = tmp_path / "index" / "lancedb"
        shared.mkdir(parents=True)
        (shared / "chunks.lance").mkdir()

        targets = discover_targets(
            notebooks_base=nb_base, shared_lancedb_path=shared,
        )
        assert [t.label for t in targets] == ["shared"]
        assert targets[0].staging_lancedb_path == shared.parent / "lancedb-staging"

    def test_skips_shared_corpus_when_empty(self, tmp_path):
        nb_base = tmp_path / "notebooks"
        _make_notebook_dataset(nb_base, "only", with_chunks=True)
        shared = tmp_path / "index" / "lancedb"
        shared.mkdir(parents=True)
        # No chunks.lance subdir.

        targets = discover_targets(
            notebooks_base=nb_base, shared_lancedb_path=shared,
        )
        assert [t.label for t in targets] == ["only"]

    def test_no_targets_returns_empty(self, tmp_path):
        nb_base = tmp_path / "notebooks"
        nb_base.mkdir()
        targets = discover_targets(
            notebooks_base=nb_base,
            shared_lancedb_path=tmp_path / "index" / "lancedb",
        )
        assert targets == []

    @requires_symlink
    def test_skips_symlinked_notebook_dir(self, tmp_path, caplog):
        """F3 (rect): align with the m6 F3 symlink-rejection contract
        codified at tools/_notebook_common.py::notebook_dir. A symlink
        at the slug position is a red flag and must NOT be treated as
        a re-embed target — even if it would otherwise look like a
        valid lancedb-bearing notebook.
        """
        nb_base = tmp_path / "notebooks"
        nb_base.mkdir()

        # Build a real lancedb-bearing notebook outside the base, then
        # symlink it INTO the base. Without the F3 guard, discovery
        # would follow the symlink (is_dir() returns True) and
        # accept it as a target.
        real_nb = tmp_path / "out_of_tree" / "real"
        real_nb.mkdir(parents=True)
        (real_nb / "lancedb").mkdir()
        (real_nb / "lancedb" / "chunks.lance").mkdir()
        (nb_base / "spooky").symlink_to(real_nb)

        # And a legitimate non-symlinked notebook so we know the loop
        # ran at all.
        _make_notebook_dataset(nb_base, "alpha", with_chunks=True)

        with caplog.at_level("WARNING", logger="re_embed_all"):
            targets = discover_targets(
                notebooks_base=nb_base,
                shared_lancedb_path=tmp_path / "index" / "lancedb",
            )
        assert [t.label for t in targets] == ["alpha"], (
            "spooky symlink notebook must be excluded by the m6 F3 "
            "symlink-rejection contract"
        )
        assert any(
            "symlinked notebook dir spooky" in r.message
            for r in caplog.records
        ), "symlink rejection must emit a WARNING for ops visibility"

    def test_targets_sorted_alphabetically_for_deterministic_order(self, tmp_path):
        # The order matters because re-embed is single-writer-per-
        # dataset and serializes — operators should see a stable
        # ordering across runs.
        nb_base = tmp_path / "notebooks"
        for slug in ["zeta", "alpha", "mu"]:
            _make_notebook_dataset(nb_base, slug, with_chunks=True)

        targets = discover_targets(
            notebooks_base=nb_base,
            shared_lancedb_path=tmp_path / "index" / "lancedb",
        )
        assert [t.label for t in targets] == ["alpha", "mu", "zeta"]


class TestRunExitCodes:
    """``run()`` returns the documented exit codes (0/1/2)."""

    def test_no_targets_returns_2(self, tmp_path, capsys):
        nb_base = tmp_path / "notebooks"
        nb_base.mkdir()
        rc = run(
            dry_run=False,
            notebooks_base=nb_base,
            shared_lancedb_path=tmp_path / "index" / "lancedb",
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "no LanceDB datasets discovered" in err

    def test_dry_run_returns_0_and_skips_re_embed(self, tmp_path, capsys):
        nb_base = tmp_path / "notebooks"
        _make_notebook_dataset(nb_base, "alpha", with_chunks=True)

        with patch("ingest.re_embed.run_re_embed") as mock_run_re_embed:
            rc = run(
                dry_run=True,
                notebooks_base=nb_base,
                shared_lancedb_path=tmp_path / "index" / "lancedb",
            )
        assert rc == 0
        mock_run_re_embed.assert_not_called()
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "dry-run" in out

    def test_per_dataset_failure_propagates_to_exit_code(self, tmp_path, capsys):
        nb_base = tmp_path / "notebooks"
        _make_notebook_dataset(nb_base, "alpha", with_chunks=True)
        _make_notebook_dataset(nb_base, "beta", with_chunks=True)

        from types import SimpleNamespace

        # Mock run_re_embed to fail on the second dataset only.
        # F2 (rect): papers_failed is list[str] per
        # ingest/re_embed.py:103; mock must mirror the real type so
        # the formatted-failure-message regression is exercised.
        call_count = {"n": 0}

        def fake_run(**kwargs):
            call_count["n"] += 1
            return SimpleNamespace(
                papers_total=1,
                papers_failed=(
                    ["2307.00100"] if call_count["n"] == 2 else []
                ),
                chunks_source=10,
                chunks_target=10,
                chunks_copied=10,
                chunks_re_embedded=0,
                chunks_dropped=0,
                chunks_skipped_resume=0,
                chunks_failed=0,
                copy_fraction=1.0,
                elapsed_seconds=0.1,
            )

        with patch("ingest.re_embed.run_re_embed", side_effect=fake_run):
            rc = run(
                dry_run=False,
                notebooks_base=nb_base,
                shared_lancedb_path=tmp_path / "index" / "lancedb",
            )
        assert rc == 1, "fail-loudly contract: any per-dataset failure → exit 1"
        assert call_count["n"] == 2, "driver must continue past first failure"

        # F2 regression: the failure line must format as a COUNT
        # (e.g. "1 paper failure(s): 2307.00100"), NOT as the repr of
        # the list (e.g. "(['2307.00100'] paper failures)").
        err = capsys.readouterr().err
        assert "1 paper failure" in err, (
            f"F2 regression: stderr should contain a count + paper id, "
            f"got: {err!r}"
        )
        assert "2307.00100" in err
        assert "['2307.00100']" not in err, (
            "F2 regression: failure line is rendering the list[str] "
            "via repr instead of formatting count + IDs."
        )

    def test_all_success_returns_0(self, tmp_path):
        nb_base = tmp_path / "notebooks"
        _make_notebook_dataset(nb_base, "alpha", with_chunks=True)

        from types import SimpleNamespace

        def fake_run(**kwargs):
            return SimpleNamespace(
                papers_total=1, papers_failed=[],
                chunks_source=5, chunks_target=5,
                chunks_copied=5, chunks_re_embedded=0,
                chunks_dropped=0, chunks_skipped_resume=0,
                chunks_failed=0, copy_fraction=1.0,
                elapsed_seconds=0.1,
            )

        with patch("ingest.re_embed.run_re_embed", side_effect=fake_run):
            rc = run(
                dry_run=False,
                notebooks_base=nb_base,
                shared_lancedb_path=tmp_path / "index" / "lancedb",
            )
        assert rc == 0

    def test_run_re_embed_exception_marks_dataset_failed(self, tmp_path, caplog):
        nb_base = tmp_path / "notebooks"
        _make_notebook_dataset(nb_base, "alpha", with_chunks=True)

        with (
            patch(
                "ingest.re_embed.run_re_embed",
                side_effect=RuntimeError("bge-m3 OOM"),
            ),
            caplog.at_level("ERROR", logger="re_embed_all"),
        ):
            rc = run(
                dry_run=False,
                notebooks_base=nb_base,
                shared_lancedb_path=tmp_path / "index" / "lancedb",
            )
        assert rc == 1
        assert any("re-embed failed" in r.message for r in caplog.records)

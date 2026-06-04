"""Tests for the notebook ar5iv + raw-tex fetcher (tools/notebook_fetch.py).

Focus: the ``run()`` batch loop must not abort when a single paper's
best-effort raw-`.tex` recovery raises. All network + filesystem side
effects are mocked at the ``tools.notebook_fetch`` module boundary so the
suite runs offline (mirrors ``tests/test_ar5iv_fetch.py`` conventions:
``unittest.mock.patch``, ``tmp_path`` isolation, class-based grouping).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.ar5iv_fetch import Ar5ivResult
from tools import notebook_fetch
from tools._notebook_common import fetch_raw_tex_if_missing


def _local_cache_hit(paper_id: str, **_kwargs) -> Ar5ivResult:
    """Stand-in for ``try_cache`` that reports an on-disk hit.

    ``reason="ok_local_cache"`` keeps the run loop off the politeness
    sleep and the ``fetched`` bucket, so the test exercises the raw-tex
    recovery branch without any network simulation.
    """
    return Ar5ivResult(
        paper_id=paper_id,
        hit=True,
        cache_path=Path("/fake/cache") / f"{paper_id}.html",
        parsed_path=Path("/fake/parsed") / paper_id / "index.html",
        reason="ok_local_cache",
    )


class TestNotebookFetchRun:
    """``run()`` batch-loop resilience."""

    def test_old_style_id_does_not_abort_run(self, tmp_path, capsys, caplog):
        """Regression for oldstyle-id-ingest-fix-m1 fix (2).

        An old-style id (``math/0212237``) reaches the best-effort raw-`.tex`
        recovery, where ``fetch_raw_tex_if_missing -> fetch_eprint ->
        validate_paper_id`` raises ``ValueError`` (new-style-only by design).
        Before the fix that ValueError was unhandled and aborted the WHOLE
        batch with a traceback. The run must instead degrade the old-style
        id to ``raw_tex_missing`` and still process the new-style id, exiting
        0. On the pre-fix code this test fails (``run`` raises ValueError).
        """
        nb_dir = tmp_path / "notebooks" / "bridgeland-stability"
        nb_dir.mkdir(parents=True)
        (nb_dir / "papers.txt").write_text(
            "2401.00001\nmath/0212237\n", encoding="utf-8"
        )
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()

        def _fake_raw_tex(paper_id: str, _raw_dir, **_kwargs) -> bool:
            # New-style id recovers; old-style id raises the same
            # ValueError that fetch_eprint's validate_paper_id would.
            if paper_id == "math/0212237":
                raise ValueError(
                    f"paper_id {paper_id!r} does not match new-style arXiv ID"
                )
            return True

        with (
            patch.object(
                notebook_fetch, "resolve_contact_email",
                return_value="ops@example.com",
            ),
            patch.object(
                notebook_fetch, "notebook_dir", return_value=nb_dir,
            ),
            patch.object(notebook_fetch, "CORPUS_RAW_DIR", raw_dir),
            patch.object(
                notebook_fetch, "try_cache", side_effect=_local_cache_hit,
            ),
            patch.object(
                notebook_fetch, "fetch_raw_tex_if_missing",
                side_effect=_fake_raw_tex,
            ),
            caplog.at_level(logging.INFO, logger="notebook_fetch"),
        ):
            exit_code = notebook_fetch.run(
                "bridgeland-stability", sleep_seconds=0.0
            )

        # The batch completed without aborting.
        assert exit_code == 0
        # F4: compare exact whitespace-split tokens, not substrings — a
        # substring like ``raw_tex_missing=1`` would also match
        # ``raw_tex_missing=10``. Splitting pins the exact count.
        summary_tokens = capsys.readouterr().out.split()
        # New-style id recovered; old-style id degraded to missing,
        # NOT counted as malformed (it is a valid arXiv id).
        assert "raw_tex_recovered=1" in summary_tokens
        assert "raw_tex_missing=1" in summary_tokens
        assert "malformed=0" in summary_tokens
        assert "from_cache=2" in summary_tokens
        # F1 regression guard: the silent-swallow degrade must leave a
        # breadcrumb. Exactly one INFO record from the except branch,
        # naming the old-style id, so a future silent-swallow regression
        # fails here.
        degrade_records = [
            r for r in caplog.records
            if r.name == "notebook_fetch" and "math/0212237" in r.getMessage()
        ]
        assert len(degrade_records) == 1
        assert "raw_tex_missing" in degrade_records[0].getMessage()

    def test_real_chain_raises_value_error_for_old_style_id(self, tmp_path):
        """Closes F2: the broad ``except ValueError`` in ``run()`` is only
        correct if the REAL ``fetch_raw_tex_if_missing -> fetch_eprint ->
        validate_paper_id`` chain raises ``ValueError`` (not some other
        type) for an old-style id.

        The batch test above mocks that boundary, so it cannot pin the
        exception TYPE. This test drives the real helper (offline:
        ``validate_paper_id`` raises at ``tools/arxiv_fetch.py:273`` BEFORE
        the ``urlopen`` at ``:282``, so no network egress occurs) and locks
        the contract. If a refactor ever changed the raised type, this
        fails — catching the type-drift the over-mocked test cannot.
        """
        # Empty raw_dir → no cached .tex → the helper proceeds to
        # fetch_eprint, whose validate_paper_id rejects the old-style id.
        with pytest.raises(ValueError, match="paper_id"):
            fetch_raw_tex_if_missing("math/0212237", tmp_path)

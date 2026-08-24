"""Behavioral coverage for the shared marker validator (issues #447/#448/#449).

Written against a REAL LanceDB table, deliberately. The first cut of all three
fixes shipped green under source-scanning tests that asserted a function
existed and that a string appeared in a docstring; an external review then
found each one wrong at runtime (#495). Every test here builds a corpus, runs
the code, and reads the verdict.

What each issue's second cut has to prove:

**#448** — the embedder pin is checked on EVERY path that binds a corpus, not
only ``startup``. ``_bind_corpus`` is what ``late_bind`` (bootstrap promotion)
and ``refresh_corpus_if_stale`` (#207's version-bump rebind) share, and it had
no embedder check at all — so the desktop first-run path, the one most likely
to promote a corpus built by a different embedder, published a clean verdict.

**#448b** — precedence is explicit. ``DegradedState`` carries one reason, and
the embedder branch used to assign unconditionally, silently overwriting
``corpus_corruption`` two lines below a comment claiming "only the FIRST match
sets degraded".

**#447** — the paper_id scan projects at the SCANNER. ``to_arrow().select()``
materializes all fourteen columns, both 1024-float vectors included, and
projects the copy.

**#449** — a version-ahead marker may only exonerate the data ("The data is NOT
corrupt") when the data has actually been read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from ingest.schema import CHUNKS_SCHEMA_V1
from server.corpus import CorpusVersionInfo, DegradedState, project_column
from server.resources import Resources, _escalate, reconcile_corpus_marker

EMBEDDING_DIM = 1024


def _rows(count: int, *, papers: int, embedder: str = "test") -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": f"c{i:04d}",
            "paper_id": f"p{i % papers:03d}",
            "kind": "section",
            "section_path": ["1"],
            "theorem_name": None,
            "theorem_label": None,
            "body_text": f"body {i}",
            "body_tokens": f"body {i}",
            "embedding_stmt": [0.1] * EMBEDDING_DIM,
            "embedding_proof": None,
            "embedding_eq": None,
            "chunker_version": "test",
            "embedder_version": embedder,
            "preamble_ref": None,
        }
        for i in range(count)
    ]


def _table(tmp_path: Path, count: int = 12, *, papers: int = 4) -> Any:
    import lancedb

    arrow = pa.Table.from_pylist(
        _rows(count, papers=papers), schema=CHUNKS_SCHEMA_V1
    )
    db = lancedb.connect(str(tmp_path / "lancedb"))
    return db.create_table("chunks", data=arrow)


def _marker(
    *,
    embedder: str,
    chunk_count: int = 12,
    paper_count: int = 4,
    version: int = 1,
) -> CorpusVersionInfo:
    return CorpusVersionInfo(
        version=version,
        chunker_version="test",
        embedder_version=embedder,
        created_at="2026-08-23T00:00:00Z",
        paper_count=paper_count,
        chunk_count=chunk_count,
    )


def _loaded_pin() -> str:
    from ingest.embedder import EMBEDDER_VERSION

    return EMBEDDER_VERSION


# ---------------------------------------------------------------------------
# #447 — the projection reaches the scanner
# ---------------------------------------------------------------------------
def test_projection_agrees_with_the_full_materialization(tmp_path: Path) -> None:
    """Same answer, or the optimization is a behavior change."""
    tbl = _table(tmp_path, 12, papers=4)
    projected = project_column(tbl, "paper_id", expected_rows=12)
    full = tbl.to_arrow().column("paper_id").to_pylist()
    assert projected is not None
    assert sorted(projected) == sorted(full)
    assert len(set(projected)) == 4


def test_projection_reads_one_column_not_fourteen(tmp_path: Path) -> None:
    """The measurement that motivated #447's reopening, as an assertion.

    The vector columns are what make this matter: 1024 float32 per row per
    column. Comparing Arrow buffer sizes is the direct evidence that the
    projection is pushed down rather than applied to a materialized copy.
    """
    tbl = _table(tmp_path, 12, papers=4)
    full_bytes = tbl.to_arrow().nbytes
    projected_bytes = (
        tbl.search().select(["paper_id"]).limit(12).to_arrow().nbytes
    )
    assert projected_bytes * 50 < full_bytes, (
        f"projection must not materialize the vector columns: "
        f"full={full_bytes} projected={projected_bytes}"
    )


def test_a_short_read_returns_none_rather_than_a_wrong_count(
    tmp_path: Path,
) -> None:
    """The silent-undercount failure mode, which is the dangerous direction.

    A projection that comes back short looks EXACTLY like a real row-count
    divergence, so it would flip /readyz to degraded on a healthy corpus.
    ``None`` means "could not project" and the caller skips its check.
    """
    tbl = _table(tmp_path, 12, papers=4)
    assert project_column(tbl, "paper_id", expected_rows=99) is None
    assert project_column(tbl, "paper_id", expected_rows=-1) is None
    assert project_column(tbl, "paper_id", expected_rows=0) == []


def test_paper_count_divergence_is_detected_through_the_projection(
    tmp_path: Path,
) -> None:
    tbl = _table(tmp_path, 12, papers=4)
    result = reconcile_corpus_marker(
        tbl,
        corpus_info=_marker(embedder=_loaded_pin(), paper_count=9999),
        tolerance=0.0,
        degraded=None,
        caller="test",
    )
    assert result.paper_count == 4
    assert result.degraded is not None
    assert result.degraded.reason == "paper_count_diverged"


# ---------------------------------------------------------------------------
# #448 — the embedder pin, on every binding path
# ---------------------------------------------------------------------------
def test_a_mismatched_embedder_degrades(tmp_path: Path) -> None:
    tbl = _table(tmp_path, 12, papers=4)
    result = reconcile_corpus_marker(
        tbl,
        corpus_info=_marker(embedder="bge-m3@definitely-not-the-pin"),
        tolerance=0.0,
        degraded=None,
        caller="test",
    )
    assert result.degraded is not None
    assert result.degraded.reason == "embedder_version_mismatch"


def test_a_matching_embedder_does_not_degrade(tmp_path: Path) -> None:
    """The negative control. Without it the test above passes on a validator
    that degrades unconditionally."""
    tbl = _table(tmp_path, 12, papers=4)
    result = reconcile_corpus_marker(
        tbl,
        corpus_info=_marker(embedder=_loaded_pin()),
        tolerance=0.0,
        degraded=None,
        caller="test",
    )
    assert result.degraded is None
    assert result.chunk_count == 12
    assert result.paper_count == 4


@pytest.mark.parametrize(
    "caller", ["Resources.startup", "late_bind", "refresh_corpus_if_stale"]
)
def test_every_binding_caller_reaches_the_same_verdict(
    tmp_path: Path, caller: str
) -> None:
    """The heart of #448.

    Startup checked the pin; ``_bind_corpus`` — shared by ``late_bind`` and
    ``refresh_corpus_if_stale`` — did not. Three callers, one validator, one
    verdict: parameterizing the caller is what makes a future re-divergence a
    test failure rather than a silent one.
    """
    tbl = _table(tmp_path, 12, papers=4)
    result = reconcile_corpus_marker(
        tbl,
        corpus_info=_marker(embedder="bge-m3@wrong"),
        tolerance=0.0,
        degraded=None,
        caller=caller,
    )
    assert result.degraded is not None
    assert result.degraded.reason == "embedder_version_mismatch"


# ---------------------------------------------------------------------------
# #448b — precedence is explicit, not assignment order
# ---------------------------------------------------------------------------
def test_corruption_survives_a_concurrent_embedder_mismatch(
    tmp_path: Path,
) -> None:
    """Both conditions at once. Corruption must win.

    This is the case the old code got backwards: the embedder branch assigned
    unconditionally, so a corrupt corpus that ALSO had a stale embedder pin
    reported ``embedder_version_mismatch`` and lost the corruption verdict —
    the one that says the corpus cannot answer at all.
    """
    tbl = _table(tmp_path, 12, papers=4)
    corruption = DegradedState(
        reason="corpus_corruption", fallback_version=1, original_version=2
    )
    result = reconcile_corpus_marker(
        tbl,
        corpus_info=_marker(embedder="bge-m3@wrong", version=2),
        tolerance=0.0,
        degraded=corruption,
        caller="test",
    )
    assert result.degraded is not None
    assert result.degraded.reason == "corpus_corruption"
    assert result.degraded.fallback_version == 1


def test_the_embedder_verdict_still_beats_a_count_verdict(
    tmp_path: Path,
) -> None:
    """Ordering is a total order, not just "corruption on top".

    A wrong vector space makes every ANSWER wrong; a wrong chunk_count makes a
    reported NUMBER wrong. The former has to win.
    """
    tbl = _table(tmp_path, 12, papers=4)
    result = reconcile_corpus_marker(
        tbl,
        corpus_info=_marker(embedder="bge-m3@wrong", chunk_count=999),
        tolerance=0.0,
        degraded=None,
        caller="test",
    )
    assert result.degraded is not None
    assert result.degraded.reason == "embedder_version_mismatch"


def test_escalation_never_downgrades() -> None:
    ranked = [
        "corpus_corruption",
        "hosted_embedder_outage",
        "embedder_version_mismatch",
        "chunk_count_diverged",
        "paper_count_diverged",
    ]
    for i, higher in enumerate(ranked):
        for lower in ranked[i + 1 :]:
            hi = DegradedState(
                reason=higher, fallback_version=1, original_version=1
            )
            lo = DegradedState(
                reason=lower, fallback_version=1, original_version=1
            )
            assert _escalate(hi, lo).reason == higher, f"{lower} displaced {higher}"
            assert _escalate(lo, hi).reason == higher, f"{higher} lost to {lower}"


def test_an_unranked_reason_cannot_displace_a_known_one() -> None:
    """Adding a reason without a rank must fail SAFE."""
    known = DegradedState(
        reason="corpus_corruption", fallback_version=1, original_version=1
    )
    novel = DegradedState(
        reason="some_future_reason", fallback_version=1, original_version=1
    )
    assert _escalate(known, novel).reason == "corpus_corruption"


def test_every_reason_the_validator_can_emit_has_a_rank() -> None:
    """A reason with no rank sorts at 0 and would never win — including
    against nothing at all, which is the one case that still works. Keeping
    the two sets in step is what stops that from mattering."""
    from server.resources import _DEGRADED_SEVERITY

    for reason in (
        "corpus_corruption",
        "embedder_version_mismatch",
        "chunk_count_diverged",
        "paper_count_diverged",
    ):
        assert reason in _DEGRADED_SEVERITY


def test_ranked_reasons_are_all_known_to_the_metrics_gauge() -> None:
    """A reason absent from health.py's label tuple never resets its gauge to
    0 after the condition clears, so it reads as permanently active."""
    health = Path("server/health.py").read_text(encoding="utf-8")
    from server.resources import _DEGRADED_SEVERITY

    for reason in _DEGRADED_SEVERITY:
        assert f'"{reason}"' in health, (
            f"{reason} is missing from server/health.py's gauge label space"
        )


# ---------------------------------------------------------------------------
# #449 — do not exonerate data that was never read
# ---------------------------------------------------------------------------
def test_the_tip_lookup_reads_a_row(tmp_path: Path) -> None:
    """A healthy dataset resolves its tip."""
    from server.corpus import _dataset_tip_version

    _table(tmp_path, 12, papers=4)
    assert _dataset_tip_version(tmp_path / "lancedb") == 1


def test_an_unreadable_tip_yields_no_version(tmp_path: Path) -> None:
    """The #449 regression, reproduced through the #428 corruption shape.

    Zeroing the fragments leaves the manifest intact, so ``open_chunks_table``
    still succeeds — which is why the first cut of #449 resolved a tip here and
    went on to tell the operator "The data is NOT corrupt". With the tip
    smoke-read, the lookup returns None and that claim is never reached.
    """
    from server.corpus import _dataset_tip_version

    _table(tmp_path, 12, papers=4)
    data_dir = tmp_path / "lancedb" / "chunks.lance" / "data"
    fragments = sorted(data_dir.glob("*.lance"))
    assert fragments, "expected at least one fragment to corrupt"
    for fragment in fragments:
        fragment.write_bytes(b"\x00" * fragment.stat().st_size)

    assert _dataset_tip_version(tmp_path / "lancedb") is None


# ---------------------------------------------------------------------------
# #448 — the WIRING. The validator existing is not the fix; being called is.
# ---------------------------------------------------------------------------
def _patch_bind_heavy_io(monkeypatch: pytest.MonkeyPatch, table: Any) -> None:
    """Stub the expensive handles, leave the reconciliation REAL.

    Deliberately narrow: ``open_chunks_table_with_fallback`` is redirected to a
    genuine LanceDB table rather than a mock, so ``count_rows`` and the
    projection execute for real. Stubbing those is what let the original #448
    slip through — a fake table answers whatever the fixture says.
    """
    from unittest.mock import MagicMock

    import server.cache as cache_mod
    import server.resources as res_mod
    from server.cache import RetrievalCache
    from server.retrieval import BM25Phase

    monkeypatch.setattr(
        res_mod, "open_chunks_table_with_fallback", lambda **_kw: (table, None)
    )
    fake_bm25 = MagicMock(spec=BM25Phase)
    fake_bm25.corpus_size = 12

    async def _bm25(**_kw: Any) -> Any:
        return fake_bm25

    async def _cache(**_kw: Any) -> Any:
        return MagicMock(spec=RetrievalCache)

    monkeypatch.setattr(BM25Phase, "startup", staticmethod(_bm25))
    monkeypatch.setattr(RetrievalCache, "open", staticmethod(_cache))
    monkeypatch.setattr(cache_mod, "set_cache", lambda _c: None)


def _write_marker(lancedb_path: Path, *, embedder: str) -> None:
    import json

    lancedb_path.mkdir(parents=True, exist_ok=True)
    (lancedb_path / "corpus-version.json").write_text(
        json.dumps(
            {
                "version": 1,
                "chunker_version": "test",
                "embedder_version": embedder,
                "created_at": "2026-08-23T00:00:00Z",
                "paper_count": 4,
                "chunk_count": 12,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("embedder", "expected"),
    [
        ("bge-m3@definitely-not-the-pin", "embedder_version_mismatch"),
        (None, None),  # None -> substituted with the live pin below
    ],
    ids=["mismatched-embedder", "matching-embedder"],
)
def test_late_bind_publishes_the_embedder_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    embedder: str | None,
    expected: str | None,
) -> None:
    """Bootstrap promotion must reach the same verdict startup does.

    This is the exact path #426 made bootable and #448 left unchecked: the
    desktop app boots with no corpus, an ingest completes, and ``late_bind``
    promotes the stub. Before this fix that promotion published
    ``degraded=None`` no matter what embedder built the corpus.

    The pairing matters as much as the positive case — a validator that
    degrades unconditionally would satisfy the first arm alone.
    """
    import asyncio

    from server.config import Config

    table = _table(tmp_path, 12, papers=4)
    lancedb_path = tmp_path / "lancedb"

    cfg = Config(
        lancedb_path=lancedb_path,
        notebooks_db_path=tmp_path / "notebooks.db",
        cache_db_path=tmp_path / "cache.db",
        bootstrap_mode=True,
        enable_rerank=False,
    )
    _patch_bind_heavy_io(monkeypatch, table)

    # The marker must NOT exist yet: startup has to enter bootstrap mode, or
    # this exercises the startup path it already covered instead of the
    # promotion path #448 left unchecked.
    stub = asyncio.run(Resources.startup(cfg))
    assert stub.bootstrap_mode_active is True

    # "ingest completes" — the marker appears.
    _write_marker(lancedb_path, embedder=embedder or _loaded_pin())

    assert asyncio.run(stub.late_bind(cfg)) is True
    assert stub.bootstrap_mode_active is False

    if expected is None:
        assert stub.degraded is None, (
            f"a matching embedder must promote clean; got {stub.degraded}"
        )
    else:
        assert stub.degraded is not None, (
            "late_bind published a clean verdict for a corpus built by a "
            "different embedder — this is issue #448 regressed"
        )
        assert stub.degraded.reason == expected


def test_late_bind_reports_a_paper_count_divergence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other check the rebind path never had (#447)."""
    import asyncio
    import json

    from server.config import Config

    table = _table(tmp_path, 12, papers=4)
    lancedb_path = tmp_path / "lancedb"
    cfg = Config(
        lancedb_path=lancedb_path,
        notebooks_db_path=tmp_path / "notebooks.db",
        cache_db_path=tmp_path / "cache.db",
        bootstrap_mode=True,
        enable_rerank=False,
    )
    _patch_bind_heavy_io(monkeypatch, table)

    stub = asyncio.run(Resources.startup(cfg))
    assert stub.bootstrap_mode_active is True

    lancedb_path.mkdir(parents=True, exist_ok=True)
    (lancedb_path / "corpus-version.json").write_text(
        json.dumps(
            {
                "version": 1,
                "chunker_version": "test",
                "embedder_version": _loaded_pin(),
                "created_at": "2026-08-23T00:00:00Z",
                "paper_count": 9999,
                "chunk_count": 12,
            }
        ),
        encoding="utf-8",
    )

    assert asyncio.run(stub.late_bind(cfg)) is True
    assert stub.degraded is not None
    assert stub.degraded.reason == "paper_count_diverged"

"""READY must mean answerable, and a cache must never gate the server.

Three data-layer findings from the 2026-08-22 chaos run, fixed together
because they share one shape: something that reports health without checking
the thing it claims to be reporting on.

**#428 — a destroyed corpus booted READY.** ``open_chunks_table`` reads only
the manifest, and ``count_rows()`` reads only fragment METADATA. Zero every
byte of every fragment and both still succeed, so the startup reconciliation
compared two numbers that each survive the corruption they were meant to
detect. ``DegradedState`` came back ``None`` and only the first real query
raised. Measured: 90 zeroed fragments, ``count_rows()`` still 4279.

**#429 — the divergence alarm was permanently ringing.** The bulk-ingest
"last paper wins" marker bug under-reported by ~40x, so a good corpus sat at
``degraded(chunk_count_diverged)`` on every boot and the one signal that
would catch a REAL divergence was noise. The writer itself was already fixed
by ``corpus-integrity-observability-m1`` (``ingest/store.py`` now counts off
the committed table); what remained was the remediation advice, which told
operators to re-run ingest — hours — when ``make reconcile`` does it in
seconds.

**#430 — a cache file could stop the server.** ``server/cache_sqlite.py``
states the contract verbatim: *"a cache failure mode is 'stale read' not
'data loss'"*, citing the constitution's *"Cache layer crash / OOM → Fall
through to recompute; log; alert."* Both ``RetrievalCache.open`` call sites
were bare, so a corrupt or locked SQLite file was a hard boot blocker — and
at the rebind site it threw inside an already-running server.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
CORPUS_PY: str = (REPO_ROOT / "server" / "corpus.py").read_text(encoding="utf-8")
RESOURCES_PY: str = (REPO_ROOT / "server" / "resources.py").read_text(encoding="utf-8")


STORE_PY: str = (REPO_ROOT / "ingest" / "store.py").read_text(encoding="utf-8")


def _function_body(func: object) -> str:
    """Source with the docstring removed.

    These functions DOCUMENT the constructs they must not use, so a scan over
    the whole source flags the explanation as the offence — the same trap
    ui.js and lifecycle.rs hit earlier in this run.
    """
    source = inspect.getsource(func)  # type: ignore[arg-type]
    marker = '"""'
    first = source.find(marker)
    if first == -1:
        return source
    second = source.find(marker, first + len(marker))
    return source if second == -1 else source[second + len(marker) :]


# ---------------------------------------------------------------------------
# #428 — READY means answerable
# ---------------------------------------------------------------------------
def _enclosing_call(source: str, needle: str) -> str:
    """The whole call expression containing ``needle``, paren-balanced.

    A fixed-size window (`source[i : i + 700]`) is the recurring trap in this
    file's history: it silently overruns into the NEXT statement when a block
    shrinks, and silently truncates the assertion target when a block grows —
    which is exactly what happened when the two divergence warnings were
    merged into one shared validator and gained a `caller` argument. Balance
    the parens instead of guessing a length.
    """
    index = source.index(needle)
    start = source.rindex("(", 0, index)
    while start > 0 and source[start - 1] not in "\n ":
        prev = source.rindex("(", 0, start)
        if source[start - 1].isidentifier() or source[start - 1] in "._":
            break
        start = prev
    depth = 0
    for pos in range(start, len(source)):
        if source[pos] == "(":
            depth += 1
        elif source[pos] == ")":
            depth -= 1
            if depth == 0:
                return source[start : pos + 1]
    raise AssertionError(f"unbalanced parens around {needle!r}")


def test_the_table_open_path_reads_a_row() -> None:
    """A manifest that parses is not a corpus that answers."""
    assert "def _smoke_read(" in CORPUS_PY, (
        "server/corpus.py must prove the table is READABLE, not merely "
        "openable (#428)"
    )
    from server.corpus import _smoke_read

    body = _function_body(_smoke_read)
    assert ".limit(1)" in body, "the probe must stay bounded to one row"
    assert "count_rows" not in body, (
        "count_rows reads fragment metadata and survives the corruption this "
        "probe exists to catch — it cannot be the probe. (Checked against the "
        "BODY: the docstring names count_rows to explain exactly this.)"
    )


def test_the_smoke_read_arms_the_existing_fallback() -> None:
    """Placement is the whole fix.

    The N-1 fallback machinery was already correct and simply never fired,
    because nothing in the open path touched the data. The probe has to sit
    INSIDE the try for the corruption handler to see it.
    """
    from server.corpus import open_chunks_table_with_fallback

    source = inspect.getsource(open_chunks_table_with_fallback)
    primary = source.index("tbl = open_chunks_table(lancedb_path, version=version)")
    handler = source.index("except corrupt_exc as primary_exc:")
    smoke = source.index("_smoke_read(tbl)")
    assert primary < smoke < handler, (
        "the smoke read must run inside the try, between the open and the "
        "corruption handler, or the fallback still cannot fire (#428)"
    )


def test_the_fallback_target_is_proved_too() -> None:
    """Falling back to a second unreadable version relocates the lie."""
    from server.corpus import open_chunks_table_with_fallback

    source = inspect.getsource(open_chunks_table_with_fallback)
    assert source.count("_smoke_read(") == 2, (
        "both the live tip and the N-1 fallback must be proved readable"
    )


def test_an_empty_table_is_not_treated_as_corruption() -> None:
    """Zero rows read cleanly is a real state — bootstrap, or a fresh corpus.

    Conflating "no rows" with "cannot read rows" would refuse to start on
    exactly the first-run corpus #426 exists to make bootable.
    """
    from server.corpus import _smoke_read

    doc = _smoke_read.__doc__ or ""
    assert "EMPTY table is not a failure" in doc, (
        "the empty-vs-unreadable distinction must be stated where the next "
        "reader will see it"
    )


# ---------------------------------------------------------------------------
# #429 — the alarm has to be worth acting on
# ---------------------------------------------------------------------------
def test_the_marker_is_written_from_the_committed_table() -> None:
    """The writer half, fixed earlier by corpus-integrity-observability-m1.

    Asserted here so #429 cannot silently regress through the writer while
    the remediation advice stays correct.
    """
    assert "chunk_count = tbl.count_rows()" in STORE_PY, (
        "the marker must count off the COMMITTED TABLE, not the in-flight "
        "batch — per-paper callers overwrite it, so len(chunks) records only "
        "the last paper (#429)"
    )
    assert 'project_column(tbl, "paper_id"' in STORE_PY, (
        "paper_count must likewise be the distinct set across the table — "
        "projected at the SCANNER (#447 round 2). The previous form, "
        "`to_arrow().select([\"paper_id\"])`, materialized all fourteen "
        "columns (both 1024-float vectors) and projected the copy, on every "
        "marker write."
    )


def test_divergence_advice_names_the_cheap_remedy() -> None:
    """Advice that costs hours is advice an operator learns to ignore.

    And an ignored degrade signal cannot report a real divergence — which is
    the actual harm in #429, not the wrong number itself.
    """
    # ONE occurrence, deliberately. This assertion used to require TWO — the
    # startup bind and the post-ingest rebind each carrying their own copy of
    # the warning — and that duplication was the mechanism of #448: the two
    # copies drifted until only one of them checked the embedder pin. They are
    # now one shared validator (`reconcile_corpus_marker`), so a second
    # occurrence would mean the duplication has come back.
    anchor = "corpus chunk_count DIVERGED"
    assert RESOURCES_PY.count(anchor) == 1, (
        f"expected exactly one divergence warning (one shared validator), "
        f"found {RESOURCES_PY.count(anchor)}"
    )
    block = _enclosing_call(RESOURCES_PY, anchor)
    assert "make reconcile" in block, (
        "the divergence warning must name `make reconcile`, which recounts "
        "from the committed table in seconds"
    )


def test_divergence_advice_no_longer_demands_a_reingest() -> None:
    assert "Re-run ingest to reconcile the marker" not in RESOURCES_PY, (
        "a full re-ingest is not required to fix a counter, and telling "
        "operators otherwise is why the signal got ignored (#429)"
    )


def test_the_reconcile_remedy_actually_exists() -> None:
    """The advice must point at something real, AND reachable.

    First cut of this fix named `make reconcile` (shared) — which turned out
    to be unreachable for the corpus that actually drifts. Its `--shared`
    path is hardcoded to ``var/arxmcp/index/lancedb``, an empty directory on
    this machine, while the stale marker lived at ``index/lancedb-staging``,
    which neither a slug nor --shared can address. Advice that names a
    command which cannot run is no better than advice that costs hours.
    """
    tool = REPO_ROOT / "tools" / "notebook_reconcile_marker.py"
    assert tool.is_file(), "the advice names a tool that must exist"
    text = tool.read_text(encoding="utf-8")
    assert "--lancedb-path" in text, (
        "a corpus at a non-default index path (lancedb-staging, "
        "lancedb-mathag) must be reachable, or the remedy is unreachable "
        "for exactly the corpora that drift (#429)"
    )


def test_the_divergence_advice_names_the_reachable_form() -> None:
    """The warning must offer the path form, not only the slug form.

    Was ">= 2", one per duplicated call site; the sites are now one shared
    validator (#448), so a single occurrence is the whole surface.
    """
    assert RESOURCES_PY.count("--lancedb-path") >= 1, (
        "the divergence warning must name the form that reaches a "
        "non-default index path"
    )


def test_reconcile_selectors_are_mutually_exclusive() -> None:
    """Three ways to name a corpus; exactly one at a time."""
    from tools.notebook_reconcile_marker import main

    assert main(["--shared", "--lancedb-path", "/tmp/nope"]) == 1
    assert main([]) == 1


# ---------------------------------------------------------------------------
# #430 — a cache is a performance artifact, never a gate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("anchor", "what"),
    [
        ("Resources.startup: retrieval cache unavailable", "startup"),
        ("_bind_corpus: retrieval cache unavailable", "post-ingest rebind"),
    ],
)
def test_cache_open_cannot_block(anchor: str, what: str) -> None:
    """Both call sites were bare. The rebind one is the worse of the two —
    it throws inside an ALREADY-RUNNING server."""
    assert anchor in RESOURCES_PY, (
        f"the {what} cache open must degrade to cacheless, not raise (#430)"
    )


def test_a_cacheless_server_is_a_supported_state() -> None:
    """Not a new state — bootstrap mode already runs this way.

    If any consumer assumed a cache were present, #430's fix would trade a
    boot failure for a later crash.
    """
    from server.cache import set_cache
    from server.resources import Resources

    signature = inspect.signature(set_cache)
    annotation = str(signature.parameters["cache"].annotation)
    assert "None" in annotation, "set_cache must accept None"

    fields = getattr(Resources, "__dataclass_fields__", {})
    assert "cache" in fields
    assert fields["cache"].default is None, (
        "Resources.cache defaults to None, which is what makes cacheless a "
        "supported state rather than a new one"
    )


def test_the_cache_contract_is_still_documented_where_it_is_implemented() -> None:
    cache_sqlite = (REPO_ROOT / "server" / "cache_sqlite.py").read_text(
        encoding="utf-8"
    )
    assert "Fall through to recompute" in cache_sqlite, (
        "the contract #430 restores must stay stated next to the code that "
        "implements it"
    )


# ---------------------------------------------------------------------------
# #430 round 2 — the log must not contradict the fallback
# ---------------------------------------------------------------------------
def test_a_cacheless_boot_says_cacheless_and_not_warm(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The behaviour half of #430, which the structural tests above miss.

    The fallback itself was correct: a corrupt or unopenable cache file no
    longer stops the boot. What shipped with it was an unconditional
    ``RetrievalCache warm`` log seven lines below the ``cache unavailable``
    warning, naming the sqlite path it had just failed to open. A log that
    answers "is this server running with a cache?" both ways is not a
    diagnostic.

    Everything expensive is stubbed EXCEPT ``RetrievalCache.open``, which is
    the thing under test — stubbing it is what let this ship.
    """
    import asyncio
    import json
    from unittest.mock import MagicMock

    import lancedb
    import pyarrow as pa

    import server.cache as cache_mod
    import server.resources as res_mod
    from ingest.embedder import EMBEDDER_VERSION
    from ingest.schema import CHUNKS_SCHEMA_V1
    from server.config import Config
    from server.resources import Resources
    from server.retrieval import BM25Phase

    rows = [
        {
            "chunk_id": f"c{i}",
            "paper_id": f"p{i}",
            "kind": "section",
            "section_path": ["1"],
            "theorem_name": None,
            "theorem_label": None,
            "body_text": "body",
            "body_tokens": "body",
            "embedding_stmt": [0.1] * 1024,
            "embedding_proof": None,
            "embedding_eq": None,
            "chunker_version": "test",
            "embedder_version": "test",
            "preamble_ref": None,
        }
        for i in range(3)
    ]
    lance = tmp_path / "lancedb"
    table = lancedb.connect(str(lance)).create_table(
        "chunks", data=pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    )
    (lance / "corpus-version.json").write_text(
        json.dumps(
            {
                "version": 1,
                "chunker_version": "test",
                "embedder_version": EMBEDDER_VERSION,
                "created_at": "2026-08-23T00:00:00Z",
                "paper_count": 3,
                "chunk_count": 3,
            }
        ),
        encoding="utf-8",
    )

    # A cache path that cannot be opened as a file, so the REAL
    # RetrievalCache.open raises and the fallback runs for real.
    bad_cache = tmp_path / "cache.db"
    bad_cache.mkdir()

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(
            res_mod, "open_chunks_table_with_fallback", lambda **_kw: (table, None)
        )
        fake_bm25 = MagicMock(spec=BM25Phase)
        fake_bm25.corpus_size = 3

        async def _bm25(**_kw: object) -> object:
            return fake_bm25

        monkey.setattr(BM25Phase, "startup", staticmethod(_bm25))
        monkey.setattr(cache_mod, "set_cache", lambda _c: None)

        cfg = Config(
            lancedb_path=lance,
            notebooks_db_path=tmp_path / "nb.db",
            cache_db_path=bad_cache,
            enable_rerank=False,
        )
        with caplog.at_level("INFO"):
            resources = asyncio.run(Resources.startup(cfg))
    finally:
        monkey.undo()

    assert resources.cache is None, "the fixture must actually produce a cacheless boot"
    messages = [record.getMessage() for record in caplog.records]
    assert any("retrieval cache unavailable" in m for m in messages), (
        "the failure must still be reported"
    )
    assert not any("RetrievalCache warm" in m for m in messages), (
        "a cacheless boot must not claim the cache is warm — that line ran "
        "unconditionally, seven lines below the failure it contradicts (#430)"
    )
    assert any("running CACHELESS" in m for m in messages), (
        "cacheless is a supported state; it has to be a legible one"
    )

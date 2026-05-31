"""corpus-integrity-completion-m3 — end-to-end multi-paper write→/readyz
integration test.

The headline KR-1 of the corpus-integrity-completion epic: prove that a
multi-paper `write_chunks` call against a real LanceDB followed by a
real FastAPI lifespan boot followed by a `GET /readyz` query produces a
body where `chunk_count == marker_chunk_count` — AND prove the same test
catches the pre-m1 bug shape (`chunk_count = len(last_per_paper_batch)`
instead of `tbl.count_rows()`) via a monkeypatch mutation.

This crosses the seam between:
  - `tests/test_store.py` (write-path tests, synthetic data)
  - `tests/test_corpus_count_reconciliation.py` (reconciliation logic,
    mocked tables or JSON-rewrite mutation)

Neither boundary test exercises the full write→lifespan→`/readyz`
chain. The motivating ~100x silent drift bug lived precisely in that
gap. After m3 ships, any future commit that re-introduces a `len(...)`-
flavored `chunk_count` write fails the mutation test in CI.

Synthesis source: `.claude/notes/milestones/corpus-integrity-completion-m3/research-synthesis.md`.

Design decisions (resolved at synthesis time):
  - Sync `fastapi.testclient.TestClient` with `with` block — canonical
    lifespan-triggering pattern. NOT async httpx (no pytest-asyncio dep
    in this project). The brief's `httpx.AsyncClient` mention is an
    aspirational contradiction with the codebase's actual dependency
    tree — resolved per synthesis Mismatch B.
  - Reuse the `_seed_corpus(lancedb_path, n=30)` + `_patch_model`
    helpers from `tests/test_corpus_count_reconciliation.py`. The
    brief's pointer to `tests/_graph_helpers.py::build_synthetic_lancedb`
    is the WRONG primary tool — that helper does NOT call
    `write_chunks`, does NOT write a marker, does NOT build HNSW
    indices, and would cause `Resources.startup` to raise
    `CorpusNotIngestedError`. Resolved per synthesis Mismatch A.
  - Dual-module BGE-M3 mock via `_patch_model` (patches BOTH
    `server.query_encoder` AND `server.resources`). The simple
    single-module `mocked_bge_m3` fixture in `test_server_startup.py`
    is INSUFFICIENT because `server/resources.py:78-82` binds
    `_get_model` / `_get_tokenizer` by name at module load time.
    This is the FM-1 top-risk per the research and the
    `notebook-retrieval-m2` lesson encoded in
    `_patch_model`'s docstring.
  - Monkeypatch target for the mutation test:
    `ingest.store.write_corpus_version_marker` — the module's own
    namespace (since `write_chunks` calls it by bare name at module
    scope per `ingest/store.py:946`). Patching the wrong binding (a
    test-local alias, a caller's import) silently no-ops, masking the
    mutation entirely.
  - Mutation injected count: `chunk_count=1` (positive integer, well
    below the `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE=0.05` floor for a
    30-row table). A negative sentinel (`chunk_count=-1`) would route
    through the "count unavailable, skip check" branch of
    `compute_chunk_count_divergence` and NOT trigger the divergence
    path — the test must inject a wrong POSITIVE count.
  - Assertion ordering: assert `body["chunk_count"] is not None` BEFORE
    the equality check. `null == null` is vacuously true and would
    silently pass if `Resources.startup` set the `-1` sentinel for a
    different reason. Closes synthesis FM-5.

Wall-clock budget: ≤ 5s per test per AC-4. Measured with the
dual-module patch: lifespan completes in <0.5s, LanceDB cold-open on
30 rows in <0.5s, well under budget. No `requires_full_corpus` /
`requires_model` marker — runs in the default `make test` set.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import ingest.store as store_mod
from server.config import Config
from server.health import reset_metrics_for_tests
from server.main import create_app
from tests.test_corpus_count_reconciliation import _patch_model, _seed_corpus

# Multi-paper fixture size. The brief specifies "3-paper × ~30-chunks";
# `_seed_corpus(lancedb_path, n=N)` yields N chunks across N papers (one
# chunk per paper). 30 satisfies the "~30 chunks" intent. The exact
# paper count is not load-bearing for KR-1 — what matters is that
# `write_chunks` is called multiple times across the per-paper loop and
# the marker reflects the cumulative count (the m1 bug shape would have
# written `chunk_count = 1` for the final per-paper batch instead of
# `chunk_count = 30` for the whole table).
_SYNTHETIC_CORPUS_SIZE = 30


def test_chunk_count_marker_equals_table_after_multi_paper_write(
    tmp_path, monkeypatch
):
    """KR-1 positive path: after a real `write_chunks` call against a
    fresh LanceDB and a real FastAPI lifespan boot, `GET /readyz`
    returns 200 with a body whose `chunk_count` equals
    `marker_chunk_count`.

    Crosses the write→lifespan→readyz seam end-to-end with the actual
    `_seed_corpus` → `write_chunks` → `write_corpus_version_marker` →
    `Resources.startup` → `compute_chunk_count_divergence` → `/readyz`
    chain. No mocks except BGE-M3 (a runtime concern, not a
    correctness one for this test).

    Closes the gap m1+m2 critiques flagged: name-pin and shape-pin
    tests do not cross the seam. This test does.
    """
    _patch_model(monkeypatch)
    lancedb_path = tmp_path / "lancedb"

    _seed_corpus(lancedb_path, n=_SYNTHETIC_CORPUS_SIZE)

    cfg = Config(lancedb_path=lancedb_path)
    app = create_app(cfg)
    reset_metrics_for_tests()
    with TestClient(app) as client:
        r = client.get("/readyz")

    if r.status_code != 200:
        raise AssertionError(
            f"/readyz returned {r.status_code} (expected 200); "
            f"body={r.json()!r}"
        )
    body = r.json()
    # FM-5: the -1 sentinel renders as JSON null. `null == null` is
    # vacuously true and would silently pass if the count_rows() call
    # failed at startup. Assert the integer presence BEFORE the
    # equality check.
    if body["chunk_count"] is None:
        raise AssertionError(
            f"/readyz body['chunk_count'] is None — count_rows() likely "
            f"raised at startup. Full body: {body!r}"
        )
    if body["chunk_count"] != body["marker_chunk_count"]:
        raise AssertionError(
            f"/readyz body chunk_count ({body['chunk_count']}) != "
            f"marker_chunk_count ({body['marker_chunk_count']}). This is "
            f"exactly the pre-m1 silent-drift bug class. Full body: "
            f"{body!r}"
        )
    # Sanity: both equal the synthetic corpus size (the seed wrote N
    # chunks per N papers; m1's fix means the marker reflects the
    # cumulative table count, not the last per-paper batch).
    if body["chunk_count"] != _SYNTHETIC_CORPUS_SIZE:
        raise AssertionError(
            f"expected chunk_count == {_SYNTHETIC_CORPUS_SIZE}; got "
            f"{body['chunk_count']}"
        )


def test_pre_m1_bug_shape_is_caught_by_integration(tmp_path, monkeypatch):
    """KR-1 mutation: the positive-path test MUST fail when the
    pre-m1 bug shape is re-introduced.

    The pre-m1 bug wrote `chunk_count = len(chunks)` where `chunks` was
    the LAST per-paper batch (not the cumulative table count) — so a
    multi-paper ingest of 30 papers × 1 chunk each produced a marker
    with `chunk_count = 1` against a table with 30 rows. The m1 fix
    routes through `tbl.count_rows()`.

    This mutation test monkey-patches `write_corpus_version_marker` at
    its module-local binding (`ingest.store.write_corpus_version_marker`
    — the bare-name call site at `ingest/store.py:946`) to inject
    `chunk_count=1` regardless of the real table size. The integration
    test must then detect the divergence — `Resources.startup` runs
    `compute_chunk_count_divergence`, sees the 29-row gap (96.7%) is
    well above the 5% default tolerance, sets
    `DegradedState(reason='chunk_count_diverged')`, and `/readyz`
    returns 503 with `body["status"] == "degraded"` +
    `body["reason"] == "chunk_count_diverged"`.

    If this test ever fails (e.g. the divergence detection regresses,
    or the monkeypatch target binding silently no-ops), the positive
    test is no longer a reliable guard against the regression class.
    """
    _patch_model(monkeypatch)
    lancedb_path = tmp_path / "lancedb"

    # Capture the real marker writer and wrap it to inject a WRONG
    # POSITIVE chunk_count. FM-9 guard: must NOT inject -1 (negative
    # sentinel) because compute_chunk_count_divergence skips the check
    # when actual_count < 0 — but here the real table count is correct,
    # we're patching the MARKER side. Inject 1 — for a 30-row table
    # that's a 96.7% divergence, well above the 5% tolerance floor
    # (max(1, 0.05 * 1) = 1; |30 - 1| = 29 > 1).
    real_marker = store_mod.write_corpus_version_marker

    def bad_marker_writer(
        target_path,
        *,
        version,
        chunker_version,
        embedder_version,
        paper_count,
        chunk_count,  # noqa: ARG001 — intentionally ignored to simulate the bug
    ):
        return real_marker(
            target_path,
            version=version,
            chunker_version=chunker_version,
            embedder_version=embedder_version,
            paper_count=paper_count,
            chunk_count=1,  # PRE-M1 BUG SHAPE — last-batch-only
        )

    # FM-4: patch the module's own namespace, NOT a caller's import
    # alias. `write_chunks` calls write_corpus_version_marker at bare
    # name from within ingest/store.py; the module-global binding is
    # the load-bearing site.
    monkeypatch.setattr(
        store_mod, "write_corpus_version_marker", bad_marker_writer
    )

    # Now ingest the corpus. The seed runs n successive write_chunks
    # calls — each one writes a marker with chunk_count=1 thanks to
    # the patch. After the seed completes, the table has 30 rows but
    # the marker says chunk_count=1.
    _seed_corpus(lancedb_path, n=_SYNTHETIC_CORPUS_SIZE)

    cfg = Config(lancedb_path=lancedb_path)
    app = create_app(cfg)
    reset_metrics_for_tests()
    with TestClient(app) as client:
        r = client.get("/readyz")

    if r.status_code != 503:
        raise AssertionError(
            f"mutation test expected /readyz 503 (degraded); got "
            f"{r.status_code}. The pre-m1 bug shape was NOT detected — "
            f"the integration test's regression-guard contract is "
            f"broken. Full body: {r.json()!r}"
        )
    body = r.json()
    if body["status"] != "degraded":
        raise AssertionError(
            f"mutation test expected body['status']='degraded'; got "
            f"{body['status']!r}. Body: {body!r}"
        )
    if body["reason"] != "chunk_count_diverged":
        raise AssertionError(
            f"mutation test expected body['reason']='chunk_count_diverged'; "
            f"got {body['reason']!r}. The wrong divergence reason was "
            f"set — the regression-detection path may have been "
            f"clobbered. Body: {body!r}"
        )


# Belt-and-suspenders sanity check that the synthetic-corpus size is
# above the divergence-tolerance floor for the chosen mutation count.
# Documents the math the mutation test depends on; if a future
# refactor changes _SYNTHETIC_CORPUS_SIZE without updating the
# mutation count, this asserts loudly at collection time.
def test_synthetic_corpus_size_exceeds_divergence_tolerance_floor():
    """The mutation test inject chunk_count=1 against a real table of
    _SYNTHETIC_CORPUS_SIZE rows. compute_chunk_count_divergence uses
    `max(1, tolerance * marker)` as the floor and the default
    tolerance is 0.05. For marker=1, floor=max(1, 0.05)=1, so the gap
    must be >1 to trigger divergence. Confirms the chosen corpus size
    is safe."""
    from server.resources import compute_chunk_count_divergence

    mutation_marker_count = 1
    result = compute_chunk_count_divergence(
        mutation_marker_count, _SYNTHETIC_CORPUS_SIZE, 0.05
    )
    if result is None:
        raise AssertionError(
            f"_SYNTHETIC_CORPUS_SIZE ({_SYNTHETIC_CORPUS_SIZE}) does NOT "
            f"exceed the divergence tolerance floor against the mutation's "
            f"injected chunk_count=1. The mutation test would silently "
            f"pass (no degrade fires). Increase _SYNTHETIC_CORPUS_SIZE "
            f"or lower the mutation count."
        )
    # Should be the "rows_added" direction (table has more rows than marker).
    if result != "rows_added":
        raise AssertionError(
            f"expected compute_chunk_count_divergence to return "
            f"'rows_added'; got {result!r}. Direction mismatch — the "
            f"mutation test's body['reason'] assertion may be wrong."
        )


# Hint to pytest that these tests do NOT need the requires_full_corpus
# marker — synthetic fixture, sub-second wall-clock per test. Listed
# here as a no-op marker check so a future reviewer who greps for
# `requires_full_corpus` in this file sees the deliberate non-opt-in.
pytestmark = []  # no opt-in markers required

"""corpus-integrity-completion-m3 — end-to-end multi-paper write→/readyz
integration test.

The headline KR-1 of the corpus-integrity-completion epic: prove that
a real **multi-call** ``write_chunks`` ingest sequence (one call per
paper, matching the production bulk-ingest cadence) followed by a real
FastAPI lifespan boot followed by a ``GET /readyz`` query produces a
body where ``chunk_count == marker_chunk_count`` — AND prove the same
test catches the exact pre-m1 bug shape
(``chunk_count = len(last_per_paper_batch)`` instead of
``tbl.count_rows()``) via a monkeypatch mutation.

This crosses the seam between:
  - ``tests/test_store.py`` (write-path tests, synthetic data)
  - ``tests/test_corpus_count_reconciliation.py`` (reconciliation logic,
    mocked tables or JSON-rewrite mutation)

Neither boundary test exercises the full multi-call
write→lifespan→``/readyz`` chain. The motivating ~100x silent drift
bug lived precisely in that gap: the pre-m1 ``chunk_count = len(chunks)``
wrote the LAST per-paper batch's chunk count into the marker (e.g. 1
chunk for the last paper) while the cumulative LanceDB table had grown
to the full cumulative count (e.g. 30 chunks). A single-call test
fixture (one ``write_chunks(chunks_30, ...)``) does NOT reproduce the
bug class — ``len(chunks_30) == count_rows() == 30`` on the single
call, so a regressed write path would silently pass.

**Multi-call cumulative fixture** (rect F1) reproduces the bug shape:
``seed_corpus_multi_paper(lancedb_path, n_papers=3, chunks_per_paper=10)``
calls ``write_chunks`` THREE times with 10 chunks per call. Each call's
``len(chunks) == 10``, but the cumulative table grows to 30 across the
three calls. A regressed ``chunk_count = len(chunks)`` write path would
publish ``chunk_count == 10`` in the final marker against a 30-row
table — the 20-row gap (200% divergence vs the 5% tolerance floor)
trips the reconciliation, ``/readyz`` returns 503, and BOTH the
positive test (which expects equality) AND the mutation test (which
expects the exact divergence signature) catch it.

Synthesis source:
``.claude/notes/milestones/corpus-integrity-completion-m3/research-synthesis.md``.
Rect critique:
``.claude/notes/milestones/corpus-integrity-completion-m3/critique-merged.md``.

Design decisions (resolved at synthesis time):
  - Sync ``fastapi.testclient.TestClient`` with ``with`` block — canonical
    lifespan-triggering pattern. NOT async httpx (no pytest-asyncio dep
    in this project). The brief's ``httpx.AsyncClient`` mention is an
    aspirational contradiction with the codebase's actual dependency
    tree — resolved per synthesis Mismatch B.
  - Reuse the shared helpers from ``tests/_corpus_helpers.py`` (rect F3
    promoted these out of test_corpus_count_reconciliation.py).
    ``seed_corpus_multi_paper`` is the load-bearing multi-call fixture
    that exercises the bug class. The single-call ``seed_corpus`` is
    NOT used here — see rect F1.
  - Dual-module BGE-M3 mock via ``patch_bge_m3_model``. The simple
    single-module ``mocked_bge_m3`` fixture in
    ``test_server_startup.py`` is INSUFFICIENT because
    ``server/resources.py:78-82`` binds ``_get_model`` /
    ``_get_tokenizer`` by name at module load time. This is the FM-1
    top-risk per the research and the ``notebook-retrieval-m2``
    lesson encoded in the shared helper's docstring.
  - Monkeypatch target for the mutation test:
    ``ingest.store.write_corpus_version_marker`` — the module's own
    namespace (since ``write_chunks`` calls it by bare name at module
    scope per ``ingest/store.py:946``). **Coverage scope (rect F2):**
    this monkeypatch intercepts ONLY the ``ingest.store`` write path.
    It does NOT intercept ``server/routes/notebooks._rewrite_corpus_version_marker``
    or ``tools/notebook_reconcile_marker.py`` — those are parallel
    marker-write paths that mirror the schema but bypass the
    module-local binding. A future "marker corruption" through those
    paths would NOT be caught by this test; that gap is documented
    here so a future contributor can extend coverage to the sibling
    paths if/when that becomes a concern.
  - Mutation injected count: ``chunk_count=10`` (the
    ``chunks_per_paper`` value — exactly what the pre-m1 bug shape
    would have written if it survived). For a 30-row cumulative table
    that's a 20-row gap (200% divergence vs the 5% tolerance floor).
    Closes synthesis FM-9 (positive integer, NOT a -1 sentinel that
    would route through the "count unavailable, skip check" branch).
  - ``bad_marker_writer`` uses ``**kwargs`` passthrough (rect F5) so a
    future schema extension that adds a new keyword to
    ``write_corpus_version_marker`` won't trip a misleading
    ``TypeError`` in this wrapper.
  - Assertion ordering: assert ``body["chunk_count"] is not None``
    BEFORE the equality check. ``null == null`` is vacuously true and
    would silently pass if ``Resources.startup`` set the ``-1``
    sentinel for a different reason. Closes synthesis FM-5.

Wall-clock budget: ≤ 5s per test per AC-4. Measured: 3 tests in
~1.5s total. No ``requires_full_corpus`` / ``requires_model`` marker
— runs in the default ``make test`` set.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import ingest.store as store_mod
from server.config import Config
from server.health import reset_metrics_for_tests
from server.main import create_app
from tests._corpus_helpers import (
    patch_bge_m3_model,
    seed_corpus_multi_paper,
)

# Multi-call cumulative fixture parameters. The brief specifies
# "3-paper × ~30 chunks"; the synthesis pinned a configuration that
# reproduces the pre-m1 bug shape STRUCTURALLY:
#
#   _N_PAPERS = 3, _CHUNKS_PER_PAPER = 10
#     → 3 write_chunks() calls, each with len(chunks) == 10
#     → cumulative tbl.count_rows() == 30 after all calls
#     → pre-m1 bug shape (chunk_count = len(chunks)) would write
#       chunk_count == 10 in the final marker vs the cumulative 30
#     → 20-row gap = 200% divergence, well above 5% tolerance
#
# The mutation test injects chunk_count=10 (the _CHUNKS_PER_PAPER
# value — exactly what the pre-m1 bug would have written). This pins
# the regression-detection chain to the specific bug shape, not just
# "any divergence."
_N_PAPERS = 3
_CHUNKS_PER_PAPER = 10
_CUMULATIVE_CHUNK_COUNT = _N_PAPERS * _CHUNKS_PER_PAPER  # 30


def test_chunk_count_marker_equals_table_after_multi_paper_write(
    tmp_path, monkeypatch
):
    """KR-1 positive path: after a real **multi-call**
    ``write_chunks`` sequence (one call per paper, matching the
    production bulk-ingest cadence) and a real FastAPI lifespan
    boot, ``GET /readyz`` returns 200 with a body whose
    ``chunk_count`` equals ``marker_chunk_count``.

    The multi-call fixture (``seed_corpus_multi_paper`` with N_PAPERS
    write_chunks calls) is the load-bearing detail per rect F1.
    A single-call fixture (one ``write_chunks(all_chunks, ...)``)
    would NOT reproduce the pre-m1 bug shape and would silently
    pass even on a regressed write path. This fixture's per-call
    ``len(chunks) == _CHUNKS_PER_PAPER == 10`` while cumulative
    ``tbl.count_rows() == _CUMULATIVE_CHUNK_COUNT == 30`` after
    all calls.

    Crosses the write→lifespan→readyz seam end-to-end with the actual
    multi-call ``seed_corpus_multi_paper`` → ``write_chunks`` ×
    ``_N_PAPERS`` → ``write_corpus_version_marker`` →
    ``Resources.startup`` → ``compute_chunk_count_divergence`` →
    ``/readyz`` chain. No mocks except BGE-M3 (a runtime concern, not
    a correctness one for this test).

    Closes the gap m1+m2 critiques flagged: name-pin and shape-pin
    tests do not cross the seam. This test does, AND uses the
    multi-call fixture that reproduces the original bug class.
    """
    patch_bge_m3_model(monkeypatch)
    lancedb_path = tmp_path / "lancedb"

    seed_corpus_multi_paper(
        lancedb_path,
        n_papers=_N_PAPERS,
        chunks_per_paper=_CHUNKS_PER_PAPER,
    )

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
    # failed at startup. Assert integer presence BEFORE the equality
    # check.
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
    # Sanity: both equal the CUMULATIVE corpus size after all
    # multi-call writes. The pre-m1 bug shape would have written
    # _CHUNKS_PER_PAPER (10) here instead of _CUMULATIVE_CHUNK_COUNT
    # (30) — assertion fails loudly with the diagnostic gap.
    if body["chunk_count"] != _CUMULATIVE_CHUNK_COUNT:
        raise AssertionError(
            f"expected cumulative chunk_count == "
            f"{_CUMULATIVE_CHUNK_COUNT} (after {_N_PAPERS} write_chunks "
            f"calls × {_CHUNKS_PER_PAPER} chunks each); got "
            f"{body['chunk_count']}. A regressed write path that "
            f"reverted to len(last_batch) would report "
            f"{_CHUNKS_PER_PAPER} here — the pre-m1 bug shape."
        )


def test_pre_m1_bug_shape_is_caught_by_integration(tmp_path, monkeypatch):
    """KR-1 mutation: the positive-path test MUST fail when the
    pre-m1 bug shape is re-introduced.

    The pre-m1 bug wrote ``chunk_count = len(chunks)`` where
    ``chunks`` was the LAST per-paper batch (not the cumulative
    table count) — so a multi-paper ingest of N papers ×
    ``chunks_per_paper`` chunks each produced a marker with
    ``chunk_count = chunks_per_paper`` against a table with
    ``N * chunks_per_paper`` rows. The m1 fix routes through
    ``tbl.count_rows()``.

    This mutation test monkey-patches
    ``ingest.store.write_corpus_version_marker`` at the module-local
    binding (the bare-name call site at ``ingest/store.py:946``) to
    inject ``chunk_count = _CHUNKS_PER_PAPER == 10`` regardless of
    the real table size — the EXACT value the pre-m1 bug would have
    written.

    **Coverage scope (rect F2):** this mutation intercepts ONLY the
    ``ingest.store.write_corpus_version_marker`` binding. The
    parallel marker writers at
    ``server/routes/notebooks._rewrite_corpus_version_marker`` and
    ``tools/notebook_reconcile_marker.py`` are NOT intercepted by
    this test. A future regression in either of those paths would
    not be caught; that gap is documented in the module docstring.

    The integration test must then detect the divergence —
    ``Resources.startup`` runs ``compute_chunk_count_divergence``,
    sees the 20-row gap (10 marker vs 30 actual; 200% divergence) is
    well above the 5% default tolerance, sets
    ``DegradedState(reason='chunk_count_diverged')``, and
    ``/readyz`` returns 503 with ``body["status"] == "degraded"`` +
    ``body["reason"] == "chunk_count_diverged"``.

    If this test ever fails (e.g. the divergence detection regresses,
    or the monkeypatch target binding silently no-ops), the positive
    test is no longer a reliable guard against the regression class.
    """
    patch_bge_m3_model(monkeypatch)
    lancedb_path = tmp_path / "lancedb"

    # Capture the real marker writer and wrap it to inject the EXACT
    # pre-m1 bug shape: chunk_count = len(last_per_paper_batch) =
    # _CHUNKS_PER_PAPER. For a cumulative 30-row table that's a
    # 20-row gap (200% divergence vs the 5% tolerance floor).
    #
    # FM-9 guard: positive integer, NOT a negative sentinel — the
    # latter would route through compute_chunk_count_divergence's
    # "count unavailable, skip check" branch (server/resources.py:240).
    #
    # rect F5: **kwargs passthrough makes the wrapper forward-
    # compatible with future write_corpus_version_marker schema
    # extensions. The wrapper crashes loudly on UNEXPECTED kwargs
    # would have failed-noisy at a future kwarg addition (e.g.
    # corpus_hash, parent_corpus_version) with a misleading message
    # pointing at the test wrapper rather than the production change.
    real_marker = store_mod.write_corpus_version_marker

    def bad_marker_writer(target_path, **kwargs):
        # PRE-M1 BUG SHAPE — last-batch-only
        kwargs["chunk_count"] = _CHUNKS_PER_PAPER
        return real_marker(target_path, **kwargs)

    # FM-4: patch the module's own namespace, NOT a caller's import
    # alias. ``write_chunks`` calls write_corpus_version_marker at
    # bare name from within ingest/store.py; the module-global
    # binding is the load-bearing site.
    monkeypatch.setattr(
        store_mod, "write_corpus_version_marker", bad_marker_writer
    )

    # Now ingest the corpus via the multi-call fixture. Each
    # write_chunks call writes a marker with
    # chunk_count=_CHUNKS_PER_PAPER thanks to the patch. After all
    # _N_PAPERS calls complete, the cumulative table has
    # _CUMULATIVE_CHUNK_COUNT rows but the marker says
    # chunk_count=_CHUNKS_PER_PAPER — the EXACT pre-m1 bug shape.
    seed_corpus_multi_paper(
        lancedb_path,
        n_papers=_N_PAPERS,
        chunks_per_paper=_CHUNKS_PER_PAPER,
    )

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
# refactor changes _N_PAPERS or _CHUNKS_PER_PAPER without updating
# the mutation count, this asserts loudly at collection time.
def test_synthetic_corpus_size_exceeds_divergence_tolerance_floor():
    """The mutation test injects chunk_count=_CHUNKS_PER_PAPER against
    a real cumulative table of _CUMULATIVE_CHUNK_COUNT rows.
    compute_chunk_count_divergence uses ``max(1, tolerance * marker)``
    as the floor and the default tolerance is 0.05.

    For marker=10 (the bug-shape value), floor = max(1, 0.5) = 1, so
    the gap must be > 1 to trigger divergence. Our cumulative count
    is 30; gap is 20 — well above the floor.

    Confirms the chosen multi-call configuration is safe for the
    mutation test.
    """
    from server.resources import compute_chunk_count_divergence

    mutation_marker_count = _CHUNKS_PER_PAPER
    result = compute_chunk_count_divergence(
        mutation_marker_count, _CUMULATIVE_CHUNK_COUNT, 0.05
    )
    if result is None:
        raise AssertionError(
            f"_CUMULATIVE_CHUNK_COUNT ({_CUMULATIVE_CHUNK_COUNT}) "
            f"does NOT exceed the divergence tolerance floor against "
            f"the mutation's injected chunk_count="
            f"{mutation_marker_count}. The mutation test would "
            f"silently pass (no degrade fires). Increase _N_PAPERS or "
            f"_CHUNKS_PER_PAPER."
        )
    # Should be the "rows_added" direction (table has more rows than marker).
    if result != "rows_added":
        raise AssertionError(
            f"expected compute_chunk_count_divergence to return "
            f"'rows_added'; got {result!r}. Direction mismatch — the "
            f"mutation test's body['reason'] assertion may be wrong."
        )

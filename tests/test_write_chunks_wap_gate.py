"""WAP-gate write-time correctness tests (corpus-integrity-completion-e1).

This file exercises the Write-Audit-Publish gate added to
``ingest/store.py::write_chunks`` per the binding spike-1 decision at
``.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md``.

The gate is placed AFTER the existing best-effort marker-write
``try/except`` block (lines 931-977) closes, BEFORE
``_append_store_stats(stats)`` at line 985. It reads
``corpus-version.json`` back from disk and verifies its ``chunk_count``
matches a fresh ``tbl.count_rows()``; on divergence it raises
``RuntimeError`` so the caller path surfaces the failure rather than
silently shipping a stale marker.

**Test plan (spike-1 §3 + research-synthesis §"Implementation roadmap"):**

- ``test_positive_path_single_call`` — single ``write_chunks`` call via
  ``seed_corpus_multi_paper(n_papers=3, chunks_per_paper=10)``; gate
  passes silently. The fixture's multi-call shape (3 separate
  ``write_chunks`` calls) is what would have tripped the pre-m1 bug
  shape — verifying that the gate does NOT false-fire here is the
  load-bearing positive sanity check.

- ``test_positive_path_re_embed_two_call_shape`` — TWO sequential
  ``write_chunks`` calls on the same LanceDB path (the production
  ``ingest/re_embed.py`` pattern: copy-pass then re-embed-pass).
  Gate passes silently on both. This addresses FM-13 surfaced in
  research-brief-2 §"FM-13": ``ingest/re_embed.py:528,558`` invokes
  ``write_chunks`` twice per paper; both calls hit the gate, both
  must pass cleanly on the happy path.

- ``test_mutation_A_wrong_value_marker`` — monkeypatch
  ``ingest.store.write_corpus_version_marker`` to inject
  ``chunk_count=1``; assert ``RuntimeError`` with the count-mismatch
  error text. Copies the rect-F4-corrected pattern from
  ``tests/test_server_startup_integration.py:265-278``.

- ``test_mutation_B_missing_marker`` — monkeypatch the marker writer
  to a no-op lambda (file never written); assert ``RuntimeError``
  with the missing-marker text AND ``caplog`` captures the existing
  swallow's ``"could not write corpus-version.json marker"`` warning.
  This is the cold-clone sub-case of FM-10.

- ``test_mutation_C_malformed_marker`` — monkeypatch the marker
  writer to write ``"not valid json"`` to ``target_path /
  "corpus-version.json"``; assert ``RuntimeError`` with the
  malformed-marker text. Exercises the ``except ValueError → raise
  RuntimeError`` arm (FM-3: truncated atomic rename).

- ``test_mutation_D_stale_marker_swallow`` — pre-seed a valid marker
  via ``seed_corpus_multi_paper(n_papers=2)``, then make a third
  ``write_chunks`` call whose ``write_corpus_version_marker`` is
  monkeypatched to raise ``IOError``. Assert (a) the swallow warning
  IS logged AND (b) the WAP gate raises COUNT-MISMATCH (stale prior
  marker's chunk_count < fresh ``tbl.count_rows()``). This is the
  production-common stale-marker path of FM-10 — operators see a
  count-mismatch error, NOT a missing-marker error, and the error
  message guides them to check the preceding swallow-warning log
  line to disambiguate.

**Why all tests use ``seed_corpus_multi_paper`` (not ``seed_corpus``):**
the OLD single-call ``seed_corpus`` helper would silently pass against
both correct and buggy code because ``len(chunks) == count_rows()``
within a single ``write_chunks`` call. Only the multi-call shape
exercises the bug class. Adversary memory file
``seed-helper-single-call-vs-claimed-per-paper-loop.md`` documents
this HIGH-risk drift pattern.
"""

from __future__ import annotations

import logging

import pytest

import ingest.store as store_mod
from tests._corpus_helpers import seed_corpus_multi_paper


def test_positive_path_single_call(tmp_path):
    """Happy path: 3-paper × 10-chunks multi-call ingest passes the
    gate on every call without raising.

    The fixture makes THREE separate ``write_chunks`` calls; the gate
    fires inside each. Reaching ``return final_version`` proves all
    three gate firings cleared.
    """
    lancedb_path = tmp_path / "lancedb"
    final_version = seed_corpus_multi_paper(
        lancedb_path, n_papers=3, chunks_per_paper=10
    )
    assert final_version > 0


def test_positive_path_re_embed_two_call_shape(tmp_path):
    """FM-13 coverage: TWO sequential ``write_chunks`` calls on the
    same LanceDB path (the ``ingest/re_embed.py:528,558`` shape).

    Gate fires inside each call; both pass silently on the happy
    path. The second call reads the marker the first call wrote and
    finds it correct (no stale-marker false-positive on legitimate
    sequential writes).
    """
    lancedb_path = tmp_path / "lancedb"
    # First call: 2 papers × 5 chunks = 10 cumulative rows.
    seed_corpus_multi_paper(lancedb_path, n_papers=2, chunks_per_paper=5)
    # Second call: 1 more paper × 5 chunks = 15 cumulative rows.
    # If the gate had a TOCTOU bug where it read the marker BEFORE the
    # second call's count_rows() landed, this would false-fire.
    final_version = seed_corpus_multi_paper(
        lancedb_path, n_papers=1, chunks_per_paper=5
    )
    assert final_version > 0


def test_mutation_A_wrong_value_marker(tmp_path, monkeypatch):
    """Mutation A — wrong-value marker: inject ``chunk_count=1`` into
    every marker write. Multi-call cumulative table is 30 rows; the
    last marker says ``chunk_count=1``. Gate fires the COUNT-MISMATCH
    arm.

    Pattern lifted verbatim from
    ``tests/test_server_startup_integration.py:265-278`` (rect-F4
    monkeypatch the module's OWN namespace, not a caller alias; bare
    name resolution at call time intercepts).
    """
    lancedb_path = tmp_path / "lancedb"
    real_marker = store_mod.write_corpus_version_marker

    def bad_marker_writer(target_path, **kwargs):
        kwargs["chunk_count"] = 1
        return real_marker(target_path, **kwargs)

    monkeypatch.setattr(
        store_mod, "write_corpus_version_marker", bad_marker_writer
    )

    with pytest.raises(RuntimeError, match="reports chunk_count="):
        seed_corpus_multi_paper(
            lancedb_path, n_papers=3, chunks_per_paper=10
        )


def test_mutation_B_missing_marker(tmp_path, monkeypatch, caplog):
    """Mutation B — cold-clone case: marker writer is a no-op (file
    never written). ``read_corpus_version`` returns ``None``; gate
    fires the MISSING-marker arm.

    Also asserts ``caplog`` captures the existing swallow's
    ``"could not write corpus-version.json marker"`` warning — the
    error message instructs operators to look for this log line, so
    the test guards that the discriminator is in fact present.

    The no-op lambda raises an exception (e.g. swallow-eligible
    ``IOError``) rather than silently doing nothing, so the existing
    ``except Exception`` swallow logs the warning AND no marker file
    is created. Both pre-conditions for the MISSING-marker arm are
    satisfied.
    """
    lancedb_path = tmp_path / "lancedb"

    def silently_skip_marker(target_path, **kwargs):
        # Raise inside the try-block so the existing swallow logs the
        # discriminator warning AND no marker file is written.
        raise OSError("simulated marker-write I/O failure")

    monkeypatch.setattr(
        store_mod, "write_corpus_version_marker", silently_skip_marker
    )

    with (
        caplog.at_level(logging.ERROR, logger="ingest.store"),
        pytest.raises(RuntimeError, match="is absent after"),
    ):
        seed_corpus_multi_paper(
            lancedb_path, n_papers=1, chunks_per_paper=5
        )

    # The existing swallow's warning must be in caplog — the gate's
    # error message tells operators to look for this exact text.
    swallow_records = [
        rec
        for rec in caplog.records
        if "could not write corpus-version.json marker" in rec.message
    ]
    assert swallow_records, (
        "swallow warning 'could not write corpus-version.json marker' "
        "not found in caplog; the WAP gate's error message references "
        "this log line as the operator discriminator. If this fails, "
        "the existing swallow at ingest/store.py:970-977 may have "
        "moved or its log message changed — re-pin the gate's error "
        "text in lockstep."
    )


def test_mutation_C_malformed_marker(tmp_path, monkeypatch):
    """Mutation C — malformed JSON: monkeypatch the marker writer to
    write ``"not valid json"`` to the marker file. ``read_corpus_version``
    raises ``ValueError`` on JSON parse failure; the gate's
    ``except ValueError → raise RuntimeError`` arm catches it (FM-3
    truncated atomic rename scenario).
    """
    from ingest.store import CORPUS_VERSION_MARKER_NAME

    lancedb_path = tmp_path / "lancedb"

    def malformed_marker_writer(target_path, **kwargs):
        # Write a deliberately malformed file. The gate's
        # read_corpus_version raises ValueError; the gate's except
        # arm re-raises as RuntimeError.
        marker_path = target_path / CORPUS_VERSION_MARKER_NAME
        marker_path.write_text("not valid json", encoding="utf-8")

    monkeypatch.setattr(
        store_mod, "write_corpus_version_marker", malformed_marker_writer
    )

    with pytest.raises(RuntimeError, match="malformed and cannot be parsed"):
        seed_corpus_multi_paper(
            lancedb_path, n_papers=1, chunks_per_paper=5
        )


def test_mutation_D_stale_marker_swallow(tmp_path, monkeypatch, caplog):
    """Mutation D — production-common stale-marker case.

    1. Pre-seed a valid marker via ``seed_corpus_multi_paper(n_papers=2)``:
       papers 1 and 2 land, cumulative 20 rows; marker chunk_count=20.
    2. Monkeypatch ``write_corpus_version_marker`` to raise ``IOError``.
    3. Call ``seed_corpus_multi_paper(n_papers=3)``: the loop iterates
       paper-by-paper. Papers 1 and 2 are upserts (their chunk_ids
       already exist; merge_insert is idempotent) — the table stays
       at 20 rows, the marker writer raises but the swallow keeps the
       stale on-disk marker at 20, and the gate sees 20==20 → passes.
       Paper 3 is NEW (paper_id ``2307.00003`` is unseen) — its 10
       chunks land via merge_insert; table count = 30. Marker write
       raises; the swallow logs the discriminator warning and leaves
       the prior chunk_count=20 marker on disk. The gate reads back
       chunk_count=20, fresh_count=30 → COUNT-MISMATCH arm fires.

    This is the production-common failure shape: an operator who
    rebuilds a partial bulk run encounters a transient marker-write
    failure on one paper while subsequent papers continue adding
    rows. The gate catches the divergence at the WRITE boundary; the
    error message's reference to the preceding swallow-warning log
    line is the disambiguator that distinguishes this swallow-driven
    case from a pre-m1-style arithmetic regression.

    **Why pre-seed n_papers=2 then call n_papers=3 (not two
    single-paper calls then a third):** ``seed_corpus_multi_paper``
    starts ``paper_idx`` from 1 on every call, so two back-to-back
    ``n_papers=1`` invocations would write the SAME paper_id twice
    (an upsert; the table never grows). The (n_papers=2 → n_papers=3)
    pattern is the only multi-call shape that lands distinct
    paper_ids across the swallow boundary while still exercising the
    gate's stale-marker arm on the final, genuinely-new paper.
    """
    lancedb_path = tmp_path / "lancedb"

    # Step 1: pre-seed papers 1 and 2 (20 rows; marker chunk_count=20).
    seed_corpus_multi_paper(lancedb_path, n_papers=2, chunks_per_paper=10)

    # Step 2: monkeypatch the marker writer to raise (post-swallow,
    # the stale prior marker remains on disk).
    def failing_marker_writer(target_path, **kwargs):
        raise OSError("simulated transient marker-write I/O failure")

    monkeypatch.setattr(
        store_mod, "write_corpus_version_marker", failing_marker_writer
    )

    # Step 3: call n_papers=3. Papers 1/2 upsert (table stays at 20,
    # gate passes 20==20). Paper 3 adds 10 new rows (table=30, marker
    # stays stale at 20 → COUNT-MISMATCH arm raises on the third
    # write_chunks call).
    with (
        caplog.at_level(logging.ERROR, logger="ingest.store"),
        pytest.raises(RuntimeError, match="reports chunk_count=") as excinfo,
    ):
        seed_corpus_multi_paper(
            lancedb_path, n_papers=3, chunks_per_paper=10
        )

    # The error message MUST mention the swallow-warning discriminator
    # so operators can disambiguate this case from a pre-m1-style
    # arithmetic regression.
    assert "could not write corpus-version.json marker" in str(
        excinfo.value
    ), (
        "WAP gate's stale-marker error text must reference the "
        "swallow-warning log line so operators can distinguish a "
        "swallowed-I/O case from an arithmetic regression. "
        f"Actual error text: {excinfo.value!s}"
    )

    # And the swallow itself must have actually logged that warning.
    swallow_records = [
        rec
        for rec in caplog.records
        if "could not write corpus-version.json marker" in rec.message
    ]
    assert swallow_records, (
        "the existing best-effort swallow at ingest/store.py:970-977 "
        "did NOT log the discriminator warning on the third call's "
        "failing marker write. Either the swallow has been removed or "
        "its log message has changed — both invalidate the gate's "
        "operator-actionability story."
    )

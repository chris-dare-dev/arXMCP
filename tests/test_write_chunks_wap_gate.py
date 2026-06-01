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
    """Mutation A — wrong-value marker: the monkeypatched
    ``write_corpus_version_marker`` injects ``chunk_count=1`` into
    EVERY marker write (rect F1: docstring corrected — the gate fires
    on the FIRST ``write_chunks`` call, not the third).

    Actual firing sequence:
    1. First ``write_chunks`` call writes 10 chunks. After
       merge_insert: ``tbl.count_rows() == 10``. The monkeypatched
       writer lands a marker with ``chunk_count=1`` (the injection).
       The WAP gate reads back ``chunk_count=1`` and compares against
       ``fresh_count=10`` → COUNT-MISMATCH arm raises.
    2. The second and third ``write_chunks`` calls never execute.
    3. Because the marker write SUCCEEDED (the wrapper called the
       real writer with the wrong kwargs), the in-call
       ``marker_write_failed`` flag is False → the gate's S6 routing
       tag fires (arithmetic regression, not S5 swallow).

    Rect F1 strengthens the regression guard with two firing-point
    pins: (a) the numerical state (marker chunk_count=1 vs
    fresh count_rows=10, NOT 30) in the error text, and (b) the
    ``Routing: S6`` tag from rect F3 (the writer fired cleanly; the
    bug is arithmetic, not swallow).

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

    with pytest.raises(
        RuntimeError, match="reports chunk_count="
    ) as excinfo:
        seed_corpus_multi_paper(
            lancedb_path, n_papers=3, chunks_per_paper=10
        )

    err_text = str(excinfo.value)
    # Rect F1: pin the firing-point numerical state. The gate fires
    # on call 1 (10 rows, marker chunk_count=1), NOT on call 3 (30
    # rows, marker chunk_count=1). A test that asserts only "any
    # MISMATCH" would silently pass against a regression that moved
    # the gate to LATER calls — the regression guard would weaken.
    assert "chunk_count=1" in err_text, (
        f"WAP gate error must cite marker chunk_count=1 (the "
        f"monkeypatched value); got: {err_text}"
    )
    assert "tbl.count_rows()=10" in err_text, (
        f"WAP gate must fire on FIRST write_chunks call (table=10 "
        f"after the first 10-chunk write). If this assertion fails "
        f"with tbl.count_rows()=20 or =30, the gate has shifted to "
        f"a later call — a real regression. Got: {err_text}"
    )
    # Rect F3: clean marker write + wrong content => S6 routing tag.
    assert "Routing: S6" in err_text, (
        f"WAP gate must tag this as S6 (arithmetic regression) "
        f"because the monkeypatched writer SUCCEEDS — only its "
        f"chunk_count kwarg was wrong. If S5 fires here, the rect "
        f"F3 marker_write_failed flag has regressed. Got: {err_text}"
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

    # Rect F3: the in-call swallow fired BEFORE the gate ran, so the
    # gate's COUNT-MISMATCH arm tags this as S5 (recoverable via
    # `make reconcile`). Operators on the 2am-page path get the
    # routing decision from the exception text alone, without
    # grepping for the discriminator log line.
    assert "Routing: S5" in str(excinfo.value), (
        "WAP gate must tag this as S5 (swallow + stale marker) "
        "because the in-call swallow fired before the gate ran. If "
        "S6 fires here, the rect F3 marker_write_failed flag has "
        "regressed. Got: " + str(excinfo.value)
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


def test_mutation_E_audit_row_lands_on_gate_failure_path(
    tmp_path, monkeypatch
):
    """Rect F2 regression guard: when the WAP gate raises, the
    store-stats.jsonl audit row STILL lands (via the
    ``try/finally`` around the gate). Pre-rect-F2 the gate raised
    BEFORE ``_append_store_stats`` ran, so the audit log was silent
    about the very failure path the gate exists to surface —
    operators correlating "what got written when" against the audit
    log saw a gap where the gate caught a divergence.

    This test re-runs Mutation A (wrong-value marker injected via
    monkeypatch) and confirms (a) the gate still raises and (b) the
    store-stats.jsonl audit row for the failing call is present
    with the expected ``gate_failure_reason`` field.
    """
    import json

    from ingest.store import STORE_STATS_PATH

    # Snapshot the audit log so we can identify rows from THIS test.
    pre_existing_rows = 0
    if STORE_STATS_PATH.is_file():
        pre_existing_rows = sum(
            1 for _ in STORE_STATS_PATH.read_text(encoding="utf-8").splitlines()
        )

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

    # The audit row MUST exist for the failing call. The gate raised
    # via try/finally — without rect F2, this assertion would fail
    # because _append_store_stats was skipped on the raise path.
    assert STORE_STATS_PATH.is_file(), (
        f"store-stats.jsonl absent at {STORE_STATS_PATH} after the "
        f"gate's RuntimeError. The audit log must persist; the gate "
        f"raises but the try/finally around _append_store_stats "
        f"must still execute (rect F2)."
    )
    all_lines = (
        STORE_STATS_PATH.read_text(encoding="utf-8").splitlines()
    )
    new_lines = all_lines[pre_existing_rows:]
    assert new_lines, (
        f"no new audit rows appended after the gate fired (rect F2 "
        f"regression). pre_existing={pre_existing_rows}, total="
        f"{len(all_lines)}. The try/finally is the only path that "
        f"lands the audit row when the gate raises."
    )
    # The newest row should carry the gate_failure_reason.
    last_row = json.loads(new_lines[-1])
    assert last_row.get("gate_failure_reason") == "count_mismatch_arithmetic", (
        f"audit row missing gate_failure_reason or wrong value. "
        f"Expected 'count_mismatch_arithmetic' (Mutation A is an S6 "
        f"arithmetic-regression case — the marker write succeeds with "
        f"wrong content). Got: {last_row!r}"
    )

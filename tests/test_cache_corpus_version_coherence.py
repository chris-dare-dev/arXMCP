"""Tier-1 corpus_version coherence — GitHub issue #337.

The cache had no single ``corpus_version`` contract. #204 closed two of
the four sub-defects (Tier-2's hardcoded ``corpus_version=0`` sentinel,
and the per-call override being dropped on the Tier-2 path). This module
covers the remaining two:

**(c) column vs key salt.** ``_tier1_put`` took no ``corpus_version`` and
wrote ``self._corpus_version`` — the process-wide SHARED version — into
the SQLite column even when the row's KEY had been salted with a
notebook's per-call override. Column and key hash then described
different corpora, which makes the column useless as the operational
filter it exists to be: ``purge_other_corpus_versions`` filters on the
column, while reachability depends on the key.

**Brief-spec alias parity.** ``lookup`` / ``store`` are documented as
aliases for ``lookup_search`` / ``store_search`` but silently omitted
``corpus_version``, so a caller following the documented API lost the
notebook override and got shared-corpus keys. An alias that narrows its
target's contract is worse than no alias — the omission is invisible at
the call site.

Explicitly NOT covered here, and deliberately so: making
``purge_other_corpus_versions`` notebook-aware. It keeps ONE version, so
a shared-corpus rebind still drops reachable notebook-keyed rows. That
is a cache miss rather than a wrong answer, and the real remedy (a
keep-SET) needs notebook versions that are not known at rebind time
because notebook tables open lazily. ``TestPurgeSemanticsArePinned``
pins the current behaviour so the trade-off is visible rather than
discovered.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from server.cache import RetrievalCache, reset_cache_for_tests
from server.cache_sqlite import derive_tier1_key
from server.metrics import TIER_1, reset_cache_metrics_for_tests

#: The shared/process-wide corpus version every cache below is opened at.
SHARED = 101
#: A notebook's pinned version, deliberately unequal to SHARED.
NOTEBOOK = 369


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_cache_state():
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()
    yield
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()


def _read_rows(cache: RetrievalCache) -> list[tuple[str, int]]:
    """Return ``[(key, corpus_version), ...]`` straight from SQLite.

    Reads the real column rather than a mock — the whole defect was that
    the column disagreed with the key, so a fake would test nothing."""
    conn = cache._tier1_store._conn
    return [
        (k, int(v))
        for k, v in conn.execute(
            "SELECT key, corpus_version FROM tier1_cache"
        ).fetchall()
    ]


# ===========================================================================
# (c) — the SQLite column must equal the salt the key was derived from
# ===========================================================================


class TestColumnMatchesKeySalt:

    def test_shared_write_tags_the_shared_version(self, tmp_path):
        async def go():
            cache = await RetrievalCache.open(tmp_path / "a.db", corpus_version=SHARED)
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload={"results": []},
                    level="theorem", corpus_version=None,
                )
                rows = _read_rows(cache)
                assert len(rows) == 1
                key, column = rows[0]
                assert column == SHARED
                # And the column names the version the KEY was built from.
                assert key == derive_tier1_key(
                    "q", None, 10, SHARED, level="theorem")
            finally:
                await cache.close()

        _run(go())

    def test_notebook_override_tags_the_notebook_version(self, tmp_path):
        """THE BUG. A per-call override salts the key with the notebook's
        version; pre-#337 the column was still written as the shared
        version, so the row described two different corpora at once."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "b.db", corpus_version=SHARED)
            try:
                await cache.store_search(
                    query="q", filters={"notebook": "bridgeland"}, k=10,
                    payload={"results": []}, level="theorem",
                    corpus_version=NOTEBOOK,
                )
                rows = _read_rows(cache)
                assert len(rows) == 1
                key, column = rows[0]
                assert column == NOTEBOOK, (
                    f"column says corpus {column}, but the key was salted "
                    f"with {NOTEBOOK} — the row describes two corpora"
                )
                assert key == derive_tier1_key(
                    "q", {"notebook": "bridgeland"}, 10, NOTEBOOK,
                    level="theorem",
                )
            finally:
                await cache.close()

        _run(go())

    def test_every_written_row_is_self_consistent(self, tmp_path):
        """Generalizes the two cases above: whatever mix of shared and
        overridden writes a process performs, no row may end up tagged
        with a version its key was not derived from."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=SHARED)
            try:
                writes = [
                    ("q1", None, None),
                    ("q2", {"notebook": "alpha"}, NOTEBOOK),
                    ("q3", {"notebook": "beta"}, 7),
                    ("q4", None, SHARED),
                ]
                for query, filters, override in writes:
                    await cache.store_search(
                        query=query, filters=filters, k=10,
                        payload={"results": []}, level="theorem",
                        corpus_version=override,
                    )
                by_key = dict(_read_rows(cache))
                assert len(by_key) == len(writes)
                for query, filters, override in writes:
                    salt = SHARED if override is None else override
                    key = derive_tier1_key(
                        query, filters, 10, salt, level="theorem")
                    assert by_key[key] == salt
            finally:
                await cache.close()

        _run(go())


# ===========================================================================
# Brief-spec alias parity
# ===========================================================================


class TestBriefSpecAliasParity:

    def test_aliases_accept_every_keyword_the_full_methods_do(self):
        """Structural guard: a future keyword added to ``lookup_search``
        or ``store_search`` and forgotten on the alias re-opens #337's
        silent-override-loss defect. ``query_embedding`` and the return
        shape are allowed to differ; the KEYWORDS are not."""
        for alias, full in (
            (RetrievalCache.lookup, RetrievalCache.lookup_search),
            (RetrievalCache.store, RetrievalCache.store_search),
        ):
            alias_kw = {
                name for name, p in inspect.signature(alias).parameters.items()
                if p.kind is inspect.Parameter.KEYWORD_ONLY
            }
            full_kw = {
                name for name, p in inspect.signature(full).parameters.items()
                if p.kind is inspect.Parameter.KEYWORD_ONLY
            }
            missing = full_kw - alias_kw
            assert not missing, (
                f"{alias.__qualname__} drops {sorted(missing)} that "
                f"{full.__qualname__} accepts — a caller following the "
                f"documented API loses them silently"
            )

    def test_store_alias_honors_the_override(self, tmp_path):
        """Behavioural half: the override must reach the key AND the
        column, not just be accepted and discarded."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "d.db", corpus_version=SHARED)
            try:
                await cache.store(
                    query="q", filters=None, k=10, payload={"results": []},
                    level="theorem", corpus_version=NOTEBOOK,
                )
                rows = _read_rows(cache)
                assert rows == [(
                    derive_tier1_key("q", None, 10, NOTEBOOK, level="theorem"),
                    NOTEBOOK,
                )]
            finally:
                await cache.close()

        _run(go())

    def test_lookup_alias_honors_the_override(self, tmp_path):
        """Pre-#337 this hit: the alias dropped the override, so both the
        store and the lookup silently fell back to the shared salt and
        agreed with each other for the wrong reason."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "e.db", corpus_version=SHARED)
            try:
                await cache.store(
                    query="q", filters=None, k=10, payload={"results": ["nb"]},
                    level="theorem", corpus_version=NOTEBOOK,
                )
                hit, tier = await cache.lookup(
                    query="q", filters=None, k=10, level="theorem",
                    corpus_version=NOTEBOOK,
                )
                assert tier == TIER_1 and hit == {"results": ["nb"]}
                # The shared salt must NOT reach the notebook's row.
                miss, _ = await cache.lookup(
                    query="q", filters=None, k=10, level="theorem",
                    corpus_version=None,
                )
                assert miss is None
            finally:
                await cache.close()

        _run(go())


# ===========================================================================
# Purge semantics — pinned, not fixed
# ===========================================================================


class TestPurgeSemanticsArePinned:
    """``purge_other_corpus_versions`` keeps ONE version. These tests
    record what that means now that the column is honest, so the residual
    is visible to the next reader rather than discovered."""

    def test_purge_keeps_rows_reachable_at_the_kept_version(self, tmp_path):
        async def go():
            cache = await RetrievalCache.open(tmp_path / "f.db", corpus_version=SHARED)
            try:
                await cache.store_search(
                    query="shared", filters=None, k=10,
                    payload={"results": []}, level="theorem",
                )
                dropped = await cache._tier1_store.purge_other_corpus_versions(
                    SHARED)
                assert dropped == 0
                assert len(_read_rows(cache)) == 1
            finally:
                await cache.close()

        _run(go())

    def test_purge_drops_notebook_rows_a_cache_miss_not_a_wrong_answer(
        self, tmp_path,
    ):
        """The residual #337 does NOT close. A notebook-keyed row is
        salted on the notebook's version, so a shared-corpus rebind
        purges it even though it was reachable. Recomputing is the
        correct failure direction for a performance layer — but if this
        test ever starts failing because someone made the purge
        keep-SET-based, that is an improvement, not a regression."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "g.db", corpus_version=SHARED)
            try:
                await cache.store_search(
                    query="nb", filters={"notebook": "alpha"}, k=10,
                    payload={"results": []}, level="theorem",
                    corpus_version=NOTEBOOK,
                )
                dropped = await cache._tier1_store.purge_other_corpus_versions(
                    SHARED)
                assert dropped == 1
                assert _read_rows(cache) == []
            finally:
                await cache.close()

        _run(go())

    def test_purge_drops_a_superseded_shared_version(self, tmp_path):
        """The half the honest column buys: rows salted on a superseded
        shared version are now identifiable and get reclaimed."""
        async def go():
            db = tmp_path / "h.db"
            old = await RetrievalCache.open(db, corpus_version=SHARED)
            try:
                await old.store_search(
                    query="q", filters=None, k=10, payload={"results": []},
                    level="theorem",
                )
            finally:
                await old.close()

            # Corpus bumps; reopen at the new version with the purge on,
            # exactly as server/resources.py does on a rebind.
            new = await RetrievalCache.open(
                db, corpus_version=SHARED + 1, purge_other_versions=True)
            try:
                assert _read_rows(new) == []
            finally:
                await new.close()

        _run(go())


def test_module_covers_the_issue_the_docstring_claims() -> None:
    """Cheap guard that this file stays pointed at #337 if it is renamed
    or split — the issue number is the only handle a future reader has."""
    text = Path(__file__).read_text(encoding="utf-8")
    assert "#337" in text

"""Read-only LanceDB ``chunks`` table accessor with MVCC version pinning (E04_S02).

The MVCC handshake — verbatim from the brief AC and from
:mod:`ingest.store`'s docstring:

  No symlink swaps. LanceDB version int IS the corpus_version.
  Writers use the current dataset; readers call
  dataset.checkout(version=N).

The MCP server (E06) reads the ``corpus_version`` (an integer) from a
runtime config and passes it to :func:`open_chunks_table` to pin the
dataset view at startup. The eval harness (E05) does the same. Pinning
ensures that concurrent writers cannot affect a long-running reader's
result set, and that a reader can reproduce any query against any
historical dataset version.

**Why a separate module rather than re-exporting from ingest.store.**
``ingest.store`` is the *writer*; ``server.corpus`` is the *reader*.
LanceDB's ``checkout`` API is read-only — calling it on a table object
that's also being used to write would corrupt the writer's view. By
isolating the reader in a server-layer module we make the
read-vs-write distinction explicit at the import-graph level: nothing
in ``ingest/`` imports ``server.corpus``, and nothing in
``server.corpus`` writes to LanceDB.

**checkout mutates in place.** ``tbl.checkout(N)`` is an in-place
mutation of the table object that pins reads to version ``N``. A
shared/cached table reference passed to ``checkout`` would corrupt
other readers' views. :func:`open_chunks_table` therefore returns a
**fresh table handle per call** — closes F1 from the E04_S02 critique
by relying on ``lancedb.connect`` returning a fresh ``Connection`` per
invocation (verified live and locked by
``tests/test_mvcc.py::TestHandleIndependence``). Callers that want to
cache should cache the *returned* handle, NOT the intermediate
``open_table`` result, AND must not subsequently call ``checkout`` on
the cached handle (that would invalidate every cached pin).

**HNSW + checkout interaction.** When a reader pins to a version that
predates an HNSW index build, LanceDB transparently falls back to
brute-force scan for ANN queries. Results are correct; performance
degrades. The integer returned by :func:`ingest.store.write_chunks` is
the post-index version (E04_S01 docstring's "MVCC handshake" section),
so readers pinning to that integer always get an indexed view.

**Caching contract (F12 from the E04_S02 critique).** This function is
the **uncached primitive**. Every call performs ``lancedb.connect`` →
``db.open_table`` → optional ``checkout`` and returns a fresh handle.
For an MCP server handling 10+ search_papers/sec, the per-call connect
overhead is real. The recommended pattern for E06 is: call this
function ONCE per pinned version at startup, cache the returned handle,
and route queries to the cached handle. Re-pinning to a new version
requires opening a new handle (do not call ``checkout`` on a cached
one).

**Threat 1 (08-security-observability-ops.md).** This function accepts
a filesystem path. In production the path comes from a trusted config
value, not from tool input — but we ``Path(...).exists()``-check before
passing to LanceDB so the failure mode is a clear ``FileNotFoundError``
with the offending path in the message, not a confusing
LanceDB-internal error. **Path-traversal validation is deferred to
E06's tool-input boundary (TODO(E06))**: that layer must validate the
path against the configured corpus root BEFORE invoking this function.
Closes F9 from the E04_S02 critique by surfacing the deferral
explicitly.

**Cache invalidation contract (E04_S03 → E08_S03 → issue #207).**
Downstream caches (E08_S03) must include corpus_version in their keys.
Specifically: server-side caches use the ``version`` integer from
:class:`CorpusVersionInfo` as their cache namespace key — NOT
``chunker_version``, NOT ``embedder_version``, NOT ``created_at``.
Only ``version``. When the server reads a ``corpus-version.json``
naming a different ``version`` than the one it is serving, it MUST
re-bind the corpus and clear every in-process cache keyed on the old
version. This prevents stale serving after a corpus update without
requiring a server restart. The caching doc's Tier-1 key formula
(``07-multi-agent-caching.md`` § "Tier 1 — Exact-query") is::

    key = sha256(model_name + model_version + canonical_form(query) + corpus_version)

**Where the contract is implemented, and what it did NOT cover until
2026-07-31.** This paragraph previously ended "Sonnet B's E08_S03
implementation honors this contract." Only the *keying* half was ever
true. The *invalidation* half — "when the server reads a new marker it
MUST clear" — had no implementation at all: nothing re-read the marker
after startup, ``Resources.notebook_table`` memoized its
``(table, corpus_info)`` pair for process lifetime, and
:meth:`server.cache_sqlite.Tier1Store.purge_other_corpus_versions` had
zero callers in the entire repo. The operator-visible consequence was
that clicking **Ingest** in the shipped ``/ui/`` console left the
running server serving the pre-ingest table while echoing the OLD
``corpus_version`` in the response envelope as truth. Filed and closed
as issue #207.

Today the contract is carried by :mod:`server.corpus_freshness` and the
methods it feeds — read that module's docstring for the seam's shape,
its two trigger paths, and (importantly) the boundary it does NOT
cover: the other six on-disk stores that must agree about what "the
corpus" contains carry no version marker of their own.

Two clarifications the original text got wrong, worth keeping straight:

* The trigger is a **different** version, not a **higher** one. A
  restore-from-backup lowers the marker, and serving handles pinned to
  the higher version against the restored dataset is the same silent
  lie in the other direction.
* Old-version Tier-1 rows are unreachable **by key construction**, so
  purging them is disk housekeeping, not correctness. The tier that
  genuinely needs clearing is **Tier-3**: its key is
  ``sha256(query_embedding + sorted_candidate_ids + reranker_version)``
  with no corpus version, so a re-ingest that rewrites a chunk's body
  under the same ``chunk_id`` leaves a reachable, stale rerank memo.
  Tier-2 had the same hole when this was written; issue #204 closed it
  by folding ``corpus_version`` into the scope fingerprint, so clearing
  Tier-2 is now reclamation rather than correctness — see
  :meth:`server.cache.RetrievalCache.invalidate_corpus_version`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ingest.schema import CHUNKS_TABLE_NAME

# Import the writer's default path so reader and writer have a
# symmetric default — closes F3 from the E04_S02 critique. Both
# modules now share a single source of truth for where the LanceDB
# dataset lives. ``ingest.store`` does NOT import from ``server.*``,
# so this dependency is one-way and does not close a cycle.
#
# E04_S03: also pull in the marker filename constant so reader and
# writer agree on the on-disk path.
from ingest.store import CORPUS_VERSION_MARKER_NAME, DEFAULT_LANCEDB_PATH

if TYPE_CHECKING:  # pragma: no cover
    import lancedb.table

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DegradedState:
    """Server failure-mode degradation marker (E14_S05 D2).

    Surfaced by :func:`open_chunks_table_with_fallback` when the
    live corpus version is corrupt and the N-1 fallback was
    activated. Read by :func:`server.health.readyz` to produce the
    degraded 503 response body and by
    :func:`server.observability.metrics.DEGRADED_MODE_ACTIVE`
    gauge refresh.

    Attributes
    ----------
    reason:
        Short slug identifying the cause. Today's set:
        ``"corpus_corruption"``. Reserve future causes
        (``"hosted_embedder_outage"`` etc.) as additional values
        — the gauge label space stays bounded by this enum.
    fallback_version:
        The corpus version actually being served (``v-1`` when
        the live tip ``v`` was corrupt).
    original_version:
        The version we tried to open first; useful for
        operator-facing log lines.
    """

    reason: str
    fallback_version: int
    original_version: int


def _trim_vendored_paths(message: str) -> str:
    """Drop the crates.io build-machine path from a LanceDB error (issue #476).

    pyo3 concatenates the Rust source location into its error string, so
    arXMCP's own operator-facing message ended with
    ``/Users/runner/.cargo/registry/src/.../lance-file-4.0.0/src/reader.rs:471:24``.
    Not a leak of anything sensitive — it is a CI machine's path, not this
    one's — but it buries the actionable half of the message and makes the log
    read as an arXMCP bug in a vendored file.

    Conservative: only strips a trailing ``, /…/.cargo/registry/…`` clause,
    which is the shape pyo3 appends. Anything it does not recognise is passed
    through unchanged, because a mangled error is worse than a noisy one.
    """
    cut = message.find(", /")
    if cut != -1 and ".cargo/registry" in message[cut:]:
        return message[:cut]
    return message


def _dataset_tip_version(lancedb_path: str | Path | None) -> int | None:
    """Newest version this dataset actually has, or ``None`` if unknowable.

    Used ONLY on the failure path (issue #449), so its cost never lands on a
    healthy boot. ``None`` on any error keeps the previous behaviour: an
    unreadable dataset is a corruption question, not a marker question, and
    guessing here would swap one wrong diagnosis for another.
    """
    try:
        table = open_chunks_table(lancedb_path, version=None)
        return int(table.version)
    except Exception:  # noqa: BLE001 — diagnosis only; never raise from here
        return None


def _smoke_read(tbl: lancedb.table.Table) -> None:
    """Prove the table can be READ, not merely opened (issue #428).

    ``open_chunks_table`` succeeds on a dataset whose every fragment is
    zeroed or truncated, because opening reads only the manifest.
    ``count_rows()`` is no better: it reads FRAGMENT METADATA, so it
    cheerfully reports the full row count for a corpus that cannot return a
    single row. The measured consequence was a server booting **READY** —
    ``DegradedState=None`` — on a corpus where the first real query raised.

    So the reconciliation at startup was comparing two numbers that both
    survive the corruption it was meant to detect. One row of actual data is
    what distinguishes "the manifest parses" from "the bytes are there".

    Cheap by construction: one Arrow scan, one column, ``limit(1)`` — the
    same shape ``server/retrieval/ann.py`` already uses for its startup
    column probe. Fires once per open, never per query.

    An EMPTY table is not a failure: zero rows read cleanly is a real and
    valid state (bootstrap mode, a freshly created corpus). Only an
    exception means the data cannot be reached.
    """
    tbl.search().select(["chunk_id"]).limit(1).to_arrow()


def open_chunks_table_with_fallback(
    lancedb_path: str | Path | None = None,
    *,
    version: int,
) -> tuple[lancedb.table.Table, DegradedState | None]:
    """Open the ``chunks`` table at ``version``, falling back to
    ``version - 1`` if the live tip is corrupt (E14_S05 D2).

    Closes failure mode 2 (LanceDB corrupt on restart) from
    :doc:`.claude/notes/08-security-observability-ops.md`
    §"Failure modes and graceful degradation":

        *"Fall back to previous dataset version via
        ``dataset.checkout(version=N-1)``; alert. No symlink swap."*

    Detection contract is intentionally broad: corruption surfaces
    unpredictably across LanceDB releases (``lance.LanceError``,
    ``OSError`` on a truncated fragment, ``RuntimeError`` on
    internal panics, ``ValueError`` from the in-tree retry that
    :func:`open_chunks_table` itself raises on a checkout failure).
    We catch the union, log WARN, and retry once at ``version - 1``.

    Returns
    -------
    table, degraded
        ``table`` is the LanceDB handle (pinned to whatever
        version succeeded). ``degraded`` is ``None`` on the
        happy path and a :class:`DegradedState` instance when the
        fallback was activated.

    Raises
    ------
    RuntimeError
        Both ``version`` and ``version - 1`` failed to open; the
        operator must restore from backup. ``version`` may also
        already be at the floor (``v == 1``), in which case no
        fallback target exists and we raise immediately.
    """
    # The exceptions we treat as "fallback-worthy." Broad on
    # purpose — LanceDB doesn't expose a single canonical
    # "corruption" exception class, so any error from the
    # filesystem layer (OSError on a truncated fragment),
    # RuntimeError (LanceDB-internal panic), or ValueError
    # (the in-tree retry that ``open_chunks_table`` raises on
    # checkout failure) is treated as a corruption signal worthy
    # of attempting the N-1 fallback.
    corrupt_exc: tuple[type[BaseException], ...] = (
        OSError,
        RuntimeError,
        ValueError,
    )

    try:
        tbl = open_chunks_table(lancedb_path, version=version)
        # #428: inside the try ON PURPOSE. The fallback machinery below was
        # already correct and simply never fired, because nothing in the open
        # path touched the data. Reading one row is what arms it.
        _smoke_read(tbl)
        return tbl, None
    except corrupt_exc as primary_exc:
        # #449: before blaming corruption, check the simpler explanation. The
        # marker's `version` is validated as >= 1 and nothing else, so a
        # marker naming 999999 over a 181-version dataset surfaces here as an
        # open failure, then degrades into "try 999998" — also absent — and
        # finally reports corpus_corruption_unrecoverable. The data is fine;
        # the marker names a version that never existed, and the operator was
        # being sent to restore from backup for a one-line JSON error.
        tip = _dataset_tip_version(lancedb_path)
        if tip is not None and version > tip:
            raise RuntimeError(
                f"corpus_marker_version_absent: corpus-version.json names "
                f"version {version}, but this dataset's newest version is "
                f"{tip}. The data is NOT corrupt — the marker is wrong. Heal "
                f"it with `make reconcile`, or "
                f"`tools.notebook_reconcile_marker --lancedb-path <dir>` for "
                f"a non-default index path."
            ) from primary_exc
        if version < 2:
            # Floor case — no version below 1 exists.
            raise RuntimeError(
                f"corpus_corruption_unrecoverable: live tip version "
                f"{version} failed to open and no fallback target "
                f"exists (version floor is 1). Original error: "
                f"{_trim_vendored_paths(str(primary_exc))}"
            ) from primary_exc

        logger.warning(
            "corpus version %d failed to open (%s); attempting "
            "fallback to version %d per E14_S05 D2",
            version,
            primary_exc,
            version - 1,
        )
        try:
            tbl = open_chunks_table(lancedb_path, version=version - 1)
            # The fallback target gets the same proof. Falling back to a
            # second unreadable version would just relocate the lie.
            _smoke_read(tbl)
        except corrupt_exc as fallback_exc:
            raise RuntimeError(
                f"corpus_corruption_unrecoverable: both live tip "
                f"version {version} and fallback version {version - 1} "
                f"failed to open. Live-tip error: "
                f"{_trim_vendored_paths(str(primary_exc))}; "
                f"fallback error: {_trim_vendored_paths(str(fallback_exc))}. Restore from "
                f"the most-recent restic snapshot — see "
                f"docs/ops/backup-restore.md."
            ) from fallback_exc

        return tbl, DegradedState(
            reason="corpus_corruption",
            fallback_version=version - 1,
            original_version=version,
        )


def open_chunks_table(
    lancedb_path: str | Path | None = None,
    version: int | None = None,
) -> lancedb.table.Table:
    """Open the ``chunks`` table at LanceDB ``version``.

    Returns a fresh, version-pinned ``lancedb.table.Table`` handle.
    The handle supports the standard LanceDB read API: ``count_rows``,
    ``to_arrow``, ``search``, ``schema``, ``version``. Writes raise
    ``ValueError`` from LanceDB's own write guard ("table cannot be
    modified when a specific version is checked out") — no defensive
    wrapper is added on this side.

    Pass ``lancedb_path=None`` (default) to use
    :data:`ingest.store.DEFAULT_LANCEDB_PATH` — the same default the
    writer uses (closes F3).

    Pass ``version=None`` (default) to open the live tip (latest
    version). The server uses this on cold startup before reading the
    ``corpus-version.json`` marker file (E04_S03); after the marker is
    read, the server re-opens with the explicit integer.

    The ``lancedb_path`` is checked for existence before connecting so
    the failure mode is a clear ``FileNotFoundError`` rather than a
    confusing LanceDB-internal error.

    .. warning::

       Path-traversal validation (Threat 1 from
       ``08-security-observability-ops.md``) is **deferred to E06's
       tool-input boundary**. This function trusts ``lancedb_path`` as
       config-derived. Callers that pass user-supplied paths MUST
       validate against an allowlisted corpus root first.

    Each call opens a fresh table handle. ``checkout`` mutates the
    table object in place, so a shared/cached table passed to
    ``checkout`` would corrupt other readers' views.
    ``lancedb.connect()`` returns a fresh ``Connection`` per call
    (verified by ``tests/test_mvcc.py::TestHandleIndependence``), so
    independent calls produce independent handles even when racing.

    Raises
    ------
    FileNotFoundError
        ``lancedb_path`` does not exist on disk.
    ValueError
        ``version`` is not a known LanceDB dataset version (LanceDB's
        own ``ValueError`` / ``LookupError`` / ``KeyError`` are
        re-raised as ``ValueError`` with a clearer message that names
        both the requested and live-tip versions). Other exception
        types (``OSError`` for disk-full, ``RuntimeError`` for
        LanceDB-internal panics) propagate unchanged so triage points
        at the real fault — closes F2 from the E04_S02 critique.
    """
    import lancedb  # noqa: PLC0415

    resolved_path = (
        Path(lancedb_path) if lancedb_path is not None else DEFAULT_LANCEDB_PATH
    )
    if not resolved_path.exists():
        raise FileNotFoundError(
            f"LanceDB path does not exist: {resolved_path}. "
            f"Run ingest.store.write_chunks first."
        )

    db = lancedb.connect(str(resolved_path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)

    if version is not None:
        try:
            tbl.checkout(version)
        # F2: narrow to the LanceDB exception types that signal
        # "version doesn't exist." OSError (disk full / permission
        # denied) and RuntimeError (LanceDB-internal panic) propagate
        # so triage doesn't get a misleading "version not accessible"
        # message.
        except (ValueError, LookupError, KeyError) as exc:
            live_version = getattr(tbl, "version", None)
            raise ValueError(
                f"LanceDB version {version} is not accessible "
                f"(live tip is {live_version}); call open_chunks_table "
                f"with a valid version or version=None for the live tip"
            ) from exc

    logger.debug(
        "opened chunks table at %s pinned to version %s (live tip = %s)",
        resolved_path,
        version if version is not None else "latest",
        tbl.version,
    )
    return tbl


# ---------------------------------------------------------------------------
# E04_S03: corpus_version marker reader
# ---------------------------------------------------------------------------


@dataclass
class CorpusVersionInfo:
    """Typed view of ``corpus-version.json`` (E04_S03).

    Mirrors the shape produced by
    :func:`ingest.store.write_corpus_version_marker`. Server startup
    code reads this dataclass via :func:`read_corpus_version` and uses
    ``version`` to call
    ``server.corpus.open_chunks_table(path, version=info.version)``.

    The ``version`` integer is also the **cache namespace key** for
    all server-side caches per the cache contract in this module's
    docstring. ``chunker_version`` and ``embedder_version`` are
    informational (debugging, audit, ops dashboards) — they MUST NOT
    enter cache keys.
    """

    version: int
    chunker_version: str
    embedder_version: str
    created_at: str
    paper_count: int
    chunk_count: int

    def to_dict(self) -> dict:
        """Serialize with alphabetical keys for byte-stability."""
        return {
            "chunk_count": self.chunk_count,
            "chunker_version": self.chunker_version,
            "created_at": self.created_at,
            "embedder_version": self.embedder_version,
            "paper_count": self.paper_count,
            "version": self.version,
        }

    def with_counts(
        self, *, chunk_count: int, paper_count: int
    ) -> CorpusVersionInfo:
        """Return a copy with ``chunk_count`` + ``paper_count`` overridden;
        every other field (including ``created_at``) preserved verbatim.

        Used by ``onboarding-uplift-m3``'s ``reconcile-marker``
        endpoint + the ``tools/notebook_reconcile_marker.py`` CLI to
        produce a recount marker that is **byte-identical** to a prior
        reconcile result for the same drift state. Per m3 synthesis §3
        D4 / FM-10: a repeated ``make reconcile`` MUST be a true
        no-op (not just same-data-but-different-timestamp), so
        ``created_at`` is preserved from the existing marker rather
        than refreshed to ``now()``.

        Validates that the new counts are non-negative integers — a
        recount producing a negative value would mean the LanceDB
        ``count_rows()`` / ``count_distinct(paper_id)`` returned a
        bad result, which should fail loud at this layer rather than
        write a corrupt marker.
        """
        if not isinstance(chunk_count, int) or chunk_count < 0:
            raise ValueError(
                f"chunk_count must be a non-negative int, "
                f"got {type(chunk_count).__name__} ({chunk_count!r})"
            )
        if not isinstance(paper_count, int) or paper_count < 0:
            raise ValueError(
                f"paper_count must be a non-negative int, "
                f"got {type(paper_count).__name__} ({paper_count!r})"
            )
        return CorpusVersionInfo(
            version=self.version,
            chunker_version=self.chunker_version,
            embedder_version=self.embedder_version,
            created_at=self.created_at,
            paper_count=paper_count,
            chunk_count=chunk_count,
        )

    @classmethod
    def from_dict(cls, data: dict) -> CorpusVersionInfo:
        """Inverse of :meth:`to_dict`. Lenient on ``created_at``.

        ``created_at`` is debug-only metadata; if a future schema
        reduction drops it the reader continues to work (returns an
        empty string). All other fields are required and validated
        for type AND domain — a missing entry, wrong type, or
        domain-violating value (e.g. ``version=-1``,
        ``embedder_version=None``, ``chunker_version=5``) raises
        ``ValueError`` with a field-naming message.

        Closes H1 + L1 from the E04_S03 critique: the previous
        permissive ``int(...)`` / ``str(...)`` casts silently accepted
        wrong types and negative integers. The previous code also
        raised three different exception classes (``KeyError`` for
        missing, ``TypeError`` for ``None``, ``ValueError`` for
        non-castable strings); this version normalizes everything to
        a single ``ValueError`` so callers catch one type.
        """
        try:
            # Required string fields — must be non-empty strings.
            for field_name in ("chunker_version", "embedder_version"):
                if field_name not in data:
                    raise KeyError(field_name)
                value = data[field_name]
                if not isinstance(value, str) or not value:
                    raise ValueError(
                        f"{field_name} must be a non-empty string, "
                        f"got {type(value).__name__} ({value!r})"
                    )
            # Required int fields — must be ``int`` (NOT ``bool``,
            # which ``isinstance(True, int)`` returns True for) AND
            # in the allowed domain.
            for field_name, min_value in (
                ("version", 1),
                ("paper_count", 0),
                ("chunk_count", 0),
            ):
                if field_name not in data:
                    raise KeyError(field_name)
                value = data[field_name]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(
                        f"{field_name} must be an int, got "
                        f"{type(value).__name__} ({value!r})"
                    )
                if value < min_value:
                    raise ValueError(
                        f"{field_name} must be >= {min_value}, "
                        f"got {value}"
                    )
            # ``created_at`` is debug-only and lenient. Default to ""
            # when absent. When present it must be a string.
            created_at_raw = data.get("created_at", "")
            if not isinstance(created_at_raw, str):
                raise ValueError(
                    f"created_at must be a string when present, "
                    f"got {type(created_at_raw).__name__}"
                )
            return cls(
                version=data["version"],
                chunker_version=data["chunker_version"],
                embedder_version=data["embedder_version"],
                created_at=created_at_raw,
                paper_count=data["paper_count"],
                chunk_count=data["chunk_count"],
            )
        except KeyError as exc:
            # Re-raise as ValueError so callers catch ONE error type.
            raise ValueError(
                f"corpus-version data missing required field: {exc.args[0]!r}"
            ) from exc


def read_corpus_version(
    lancedb_path: str | Path | None = None,
) -> CorpusVersionInfo | None:
    """Read ``corpus-version.json`` next to the LanceDB dataset.

    Returns the parsed :class:`CorpusVersionInfo` on success.

    Returns ``None`` when the marker file is **absent** — the
    "no ingest has run yet" cold-start path. Mirrors the discipline of
    :func:`ingest.embedder._read_embeddings_manifest` and
    :func:`ingest.preamble._read_existing_preamble` which both return
    ``None`` for absent files. The MCP server (E06) handles this by
    falling back to ``open_chunks_table(path, version=None)`` (live
    tip).

    Raises ``ValueError`` when the file is **present but
    corrupt/malformed** (parse failure, missing required field, wrong
    type). Corruption is a recoverable signal that ops should see —
    not a silent fall-through to the cold-start path.

    Pass ``lancedb_path=None`` to use :data:`DEFAULT_LANCEDB_PATH` —
    symmetric with :func:`open_chunks_table` and the writer.

    .. warning::

       Path-traversal validation (Threat 1 from
       ``08-security-observability-ops.md``) is **deferred to E06's
       tool-input boundary** (TODO(E06)) — same discipline as
       :func:`open_chunks_table` and
       :func:`ingest.store.write_corpus_version_marker`. This function
       trusts ``lancedb_path`` as config-derived. Callers passing
       user-supplied paths MUST validate against an allowlisted
       corpus root first (closes M2 from the E04_S03 critique).
    """
    resolved_path = (
        Path(lancedb_path) if lancedb_path is not None else DEFAULT_LANCEDB_PATH
    )
    marker_path = resolved_path / CORPUS_VERSION_MARKER_NAME
    # Closes M5 from the E04_S03 critique: ``is_file()`` is the right
    # absent-or-not-a-file check. ``exists()`` would treat a directory
    # at the marker location (e.g. left behind by a failed atomic
    # rename, or a deliberate symlink loop) as "exists" and fall
    # through to ``read_text``, which raises ``IsADirectoryError`` —
    # an ``OSError`` outside the documented ``ValueError`` contract.
    if not marker_path.is_file():
        return None
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"corpus-version.json at {marker_path} is not valid JSON: {exc}"
        ) from exc
    # ``from_dict`` now normalizes every error to ``ValueError`` (L1
    # close), so the wrapper just enriches the message with the path.
    try:
        return CorpusVersionInfo.from_dict(data)
    except ValueError as exc:
        raise ValueError(
            f"corpus-version.json at {marker_path} is malformed: {exc}"
        ) from exc


__all__ = [
    "CorpusVersionInfo",
    "DegradedState",
    "open_chunks_table",
    "open_chunks_table_with_fallback",
    "read_corpus_version",
]

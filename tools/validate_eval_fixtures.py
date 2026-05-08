#!/usr/bin/env python3
"""Validator for ``tests/eval/fixtures/queries.json`` (E05_S01).

The eval fixture is a hand-curated set of ``(query, chunk_id, relevance)``
triples used by the E05_S02 retrieval-quality harness to compute nDCG@5
and Recall@10 against the pinned corpus. This validator enforces the
fixture's structural invariants and the stale-id safety net required by
the E05 risk note:

    "If chunk_ids are not reproducible, the fixture becomes stale on
    every chunker run and curation effort is wasted.
    validate_eval_fixtures.py catching stale IDs is the safety net."

The script is run as part of ``make test`` via the pytest wrapper at
``tests/eval/test_fixtures.py`` (which calls :func:`validate`); a CLI
entry point at the bottom of this module exists for ad-hoc invocation.

**User-blocked content vs implementer-shipped tooling.** Per the
milestone brief ("the implementer cannot automate the curation itself
— that would make the eval circular"), this module ships the
*tooling*. The 20 hand-labeled triples themselves are populated by a
human curator following ``docs/eval-curation.md``. The seed fixture
that ships with this milestone has ``"queries": []`` (zero triples) —
the validator treats that as the "curation pending" mode and exits 0
with a clear info line. See :func:`validate` for the full behavior
matrix.

**Behavior matrix** (``len(queries)`` × corpus presence):

================================  ===  =================================
``var/arxmcp/corpus/chunks/``     N    Behavior
================================  ===  =================================
empty / missing                   0    warn "both pending", exit 0
empty / missing                   1+   error "fixture references chunks
                                       but no manifest exists"
populated                         0    warn "queries pending", exit 0
populated                         1-19 error "expected 0 or 20 queries"
populated                         20   full validation (AC-1, 2, 3, 4, 7)
================================  ===  =================================

The 1-19 ("partial fixture") branch fires regardless of corpus
presence — a partial fixture committed to the repo is always wrong
because curation is all-or-nothing. This catches accidental
half-merges of in-progress curation work.

**Single source of truth for ``CHUNKER_VERSION``.** The validator
imports ``CHUNKER_VERSION`` from :mod:`ingest.chunker_types` rather
than literalizing the version string. The fixture header's ``chunker_version``
field is the curator's commit; the validator's job is to confirm it
matches the running chunker. Hardcoding the literal would silently
mask a constant bump.

**Read-only.** This script writes nothing on disk. It does not log to
``var/arxmcp/ops/`` (no stats file, no failure log) — the pytest
wrapper captures all output via stdout/stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths and identity constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# Allow running as ``python tools/validate_eval_fixtures.py`` directly
# (the brief AC) without requiring ``pip install -e``. Prepending
# REPO_ROOT to ``sys.path`` is idempotent: in pytest / installed-pkg
# contexts, ``ingest`` is already importable and the prepend is a
# no-op. Closes F1 from the E05_S01 critique (the original CLI invocation
# crashed with ``ModuleNotFoundError: ingest`` when run from the shell).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ingest.chunker_types import CHUNKER_VERSION  # noqa: E402

#: Default fixture path; the validator is callable with an override path.
DEFAULT_FIXTURE_PATH = REPO_ROOT / "tests" / "eval" / "fixtures" / "queries.json"

#: Mirrors :data:`ingest.chunker.CHUNKS_DIR` exactly. Re-derived from
#: ``REPO_ROOT`` rather than imported because importing
#: :mod:`ingest.chunker` pulls heavy chunker deps the validator does not
#: need.
CHUNKS_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"

#: The expected number of queries when curation is complete.
TARGET_QUERY_COUNT = 20

#: The minimum count, by ``kind``, of queries that must reference at
#: least one chunk of that kind. AC-7 ("≥ 5 queries reference
#: ``kind="stmt"`` chunks AND ≥ 5 reference ``kind="proof"``").
MIN_QUERIES_BY_KIND = {"stmt": 5, "proof": 5}

#: Mirrors :data:`ingest.chunker._PAPER_ID_RE` exactly. Duplicated
#: rather than imported to keep the validator zero-dep on the chunker
#: module (which carries LaTeXML-shaped imports). Lockstep with
#: ``ingest.chunker._PAPER_ID_RE`` is locked by
#: ``tests/eval/test_fixtures.py::test_paper_id_regex_matches_chunker``.
_PAPER_ID_RE = re.compile(
    r"^\d{4}\.\d{4,5}(v\d+)?$|^[a-z][a-z\-]*/\d{7}(v\d+)?$"
)

#: ``arxiv:<paper_id>:<16-hex>``. Validates the full chunk_id shape.
_CHUNK_ID_RE = re.compile(
    r"^arxiv:(?P<paper_id>"
    r"\d{4}\.\d{4,5}(v\d+)?"
    r"|"
    r"[a-z][a-z\-]*/\d{7}(v\d+)?"
    r"):[0-9a-f]{16}$"
)

#: ISO-8601 calendar date (``YYYY-MM-DD``). The brief's example
#: ``"2026-05-06"`` is exactly this shape; the runbook documents that
#: ``created_at`` is fixed at fixture-creation time. Closes F7 from
#: the E05_S01 critique: arbitrary strings (``""``, ``"yesterday"``)
#: would silently pass without this regex.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Allowed values for the ``relevance`` field in a fixture query's
#: ``relevant_chunks`` entries. The brief: "Relevance is graded 0–3".
_VALID_RELEVANCE_GRADES = (0, 1, 2, 3)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FixtureValidationError(ValueError):
    """Raised on any fixture-level integrity violation.

    A single error class keeps the pytest wrapper's failure message
    concise. The message itself names the AC item or invariant that
    fired so triage is one read.
    """


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Per-call summary of a validator invocation.

    Returned by :func:`validate` so callers (the pytest wrapper, the
    CLI entry point) can branch on the kind of pass:

    - ``mode == "complete"`` and ``warnings == []`` → fully curated
      fixture validated against the corpus.
    - ``mode == "seed"`` → empty-fixture happy path; warnings carry
      the "curation pending" info line.
    - On any error, :class:`FixtureValidationError` is raised; this
      type is never returned in an error state.

    **F8 from the E05_S01 critique.** The ``warnings`` field is
    currently only populated in ``seed`` mode (the "curation pending"
    line). The CLI's warnings-print loop is a no-op on the
    ``complete`` path. The field is preserved for E05_S02 to populate
    with quality-of-curation advisories (e.g. "stmt-kind queries == 5,
    the AC-7 minimum — no headroom"). Until E05_S02 lands, complete
    mode returns ``warnings=[]``.
    """

    mode: str  # "seed" | "complete"
    query_count: int
    chunk_manifests_found: int
    warnings: list[str]


# ---------------------------------------------------------------------------
# Manifest scan
# ---------------------------------------------------------------------------


def _iter_chunk_manifest_paths(chunks_dir: Path) -> list[Path]:
    """Return every ``chunk_manifest.json`` under ``chunks_dir``.

    Mirrors the discipline of ``ingest.embedder._iter_paper_chunks``
    but writes nothing. Returns a sorted list for deterministic error
    ordering. An absent ``chunks_dir`` returns ``[]`` (cold-start dev
    box).

    Closes F5 from the E05_S01 critique: directory names are filtered
    against :data:`_PAPER_ID_RE` so a malformed directory (e.g. one
    introduced by a buggy chunker or a manual mkdir) cannot contribute
    chunk_ids to the validator's index. The chunker's own writer
    enforces ``_validate_paper_id`` at write time; this filter is
    defense-in-depth at read time.
    """
    if not chunks_dir.is_dir():
        return []
    return sorted(
        p
        for p in chunks_dir.glob("*/chunk_manifest.json")
        if _PAPER_ID_RE.match(p.parent.name)
    )


def _load_chunk_kind_index(manifest_paths: list[Path]) -> dict[str, str]:
    """Load every (chunk_id → kind) pair from manifests.

    Raises :class:`FixtureValidationError` if any manifest is malformed
    (missing keys, wrong types). The chunker writes manifests
    atomically with ``sort_keys=True`` so a partial / corrupt file
    indicates upstream bug, not a race.

    Closes F6 from the E05_S01 critique: chunk_ids whose embedded
    paper_id contradicts the manifest's directory name are silently
    skipped (not raised). The chunker's own write-time invariant is
    that a manifest at ``chunks/<paper_id>/`` only contains chunks for
    ``<paper_id>``; the validator refuses to import inconsistent rows
    rather than treat them as resolved chunk_ids. Combined with F5,
    this closes the "stale-id safety net" promise even against an
    upstream-chunker bug.
    """
    index: dict[str, str] = {}
    for manifest_path in manifest_paths:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FixtureValidationError(
                f"could not read chunk manifest {manifest_path}: {exc}"
            ) from exc
        if not isinstance(data, dict) or "chunks" not in data:
            raise FixtureValidationError(
                f"malformed chunk manifest {manifest_path}: "
                "missing 'chunks' key"
            )
        chunks_field = data["chunks"]
        if not isinstance(chunks_field, list):
            raise FixtureValidationError(
                f"malformed chunk manifest {manifest_path}: "
                "'chunks' is not a list"
            )
        directory_paper_id = manifest_path.parent.name
        for entry in chunks_field:
            if (
                not isinstance(entry, dict)
                or "chunk_id" not in entry
                or "kind" not in entry
            ):
                raise FixtureValidationError(
                    f"malformed chunks entry in {manifest_path}: "
                    f"expected dict with 'chunk_id' and 'kind', got "
                    f"{entry!r}"
                )
            cid = entry["chunk_id"]
            kind = entry["kind"]
            if not isinstance(cid, str) or not isinstance(kind, str):
                raise FixtureValidationError(
                    f"malformed chunks entry in {manifest_path}: "
                    f"chunk_id and kind must be strings, got "
                    f"({type(cid).__name__}, {type(kind).__name__})"
                )
            # F6: cross-check the chunk_id's embedded paper_id against
            # the manifest's directory name. A mismatched row is
            # skipped (not raised) — silent skip preserves "validator
            # is read-only safety net, never makes upstream bugs into
            # hard test failures."
            match = _CHUNK_ID_RE.match(cid)
            if match is None or match.group("paper_id") != directory_paper_id:
                continue
            # Last-write-wins on duplicates is fine for the validator —
            # a duplicate within the manifest set is upstream's problem
            # to detect (chunker invariant).
            index[cid] = kind
    return index


# ---------------------------------------------------------------------------
# Fixture parse + structural checks
# ---------------------------------------------------------------------------


def _load_fixture(fixture_path: Path) -> dict:
    """Load and shallow-validate the fixture file."""
    if not fixture_path.is_file():
        raise FixtureValidationError(
            f"fixture file does not exist: {fixture_path}"
        )
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureValidationError(
            f"fixture {fixture_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise FixtureValidationError(
            f"fixture {fixture_path}: top-level must be a JSON object, "
            f"got {type(data).__name__}"
        )
    return data


def _validate_header(data: dict, fixture_path: Path) -> None:
    """Assert top-level header keys are present, typed, and consistent.

    Required header keys (per brief):

    - ``schema_version``: ``"1.0"`` literal
    - ``chunker_version``: must equal :data:`CHUNKER_VERSION` (AC-4)
    - ``created_at``: a string (no further structural validation —
      the field is documented as fixture metadata, not consumed by
      the validator at runtime per D5 of the synthesis)
    - ``queries``: a list (further validated downstream)
    """
    required = {"schema_version", "chunker_version", "created_at", "queries"}
    missing = required - data.keys()
    if missing:
        raise FixtureValidationError(
            f"fixture {fixture_path}: missing required top-level "
            f"keys {sorted(missing)}"
        )
    # F3: reject unknown top-level keys. The brief schema is fixed at
    # exactly 4 keys; any drift (e.g. a curator adding an ad-hoc
    # ``_curation_status`` field) should fail loudly. The runbook
    # promised this; the validator now delivers it.
    extra = data.keys() - required
    if extra:
        raise FixtureValidationError(
            f"fixture {fixture_path}: unknown top-level keys "
            f"{sorted(extra)} are not allowed. The schema admits "
            f"exactly {sorted(required)}."
        )
    if data["schema_version"] != "1.0":
        raise FixtureValidationError(
            f"fixture {fixture_path}: schema_version must be '1.0', "
            f"got {data['schema_version']!r}"
        )
    if data["chunker_version"] != CHUNKER_VERSION:
        # AC-4: chunker_version in the fixture must match the running
        # chunker constant. A mismatch means chunk_ids are stale.
        raise FixtureValidationError(
            f"fixture {fixture_path}: chunker_version must equal "
            f"ingest.chunker_types.CHUNKER_VERSION ({CHUNKER_VERSION!r}), "
            f"got {data['chunker_version']!r}. Re-curate the fixture "
            f"or revert the CHUNKER_VERSION bump."
        )
    if not isinstance(data["created_at"], str):
        raise FixtureValidationError(
            f"fixture {fixture_path}: created_at must be a string, "
            f"got {type(data['created_at']).__name__}"
        )
    # F7: enforce ISO-8601 calendar date (``YYYY-MM-DD``). Empty
    # strings and free-form text (``"yesterday"``) silently passed
    # before this check. The brief example uses ``"2026-05-06"`` —
    # implicit ISO-8601.
    if not _ISO_DATE_RE.match(data["created_at"]):
        raise FixtureValidationError(
            f"fixture {fixture_path}: created_at must be an ISO-8601 "
            f"calendar date (YYYY-MM-DD), got {data['created_at']!r}"
        )
    if not isinstance(data["queries"], list):
        raise FixtureValidationError(
            f"fixture {fixture_path}: queries must be a list, "
            f"got {type(data['queries']).__name__}"
        )


def _validate_query_structure(query: dict, query_idx: int) -> None:
    """Per-query structural validation.

    Required per-query keys: ``query_id``, ``query_text``,
    ``relevant_chunks`` (a non-empty list of ``{chunk_id, relevance}``
    dicts when curation is complete).
    """
    if not isinstance(query, dict):
        raise FixtureValidationError(
            f"queries[{query_idx}]: must be a JSON object, "
            f"got {type(query).__name__}"
        )
    required = {"query_id", "query_text", "relevant_chunks"}
    missing = required - query.keys()
    if missing:
        raise FixtureValidationError(
            f"queries[{query_idx}]: missing required keys {sorted(missing)}"
        )
    if not isinstance(query["query_id"], str) or not query["query_id"]:
        raise FixtureValidationError(
            f"queries[{query_idx}]: query_id must be a non-empty string, "
            f"got {query['query_id']!r}"
        )
    if not isinstance(query["query_text"], str) or not query["query_text"]:
        raise FixtureValidationError(
            f"queries[{query_idx}]: query_text must be a non-empty "
            f"string, got {query['query_text']!r}"
        )
    if (
        not isinstance(query["relevant_chunks"], list)
        or not query["relevant_chunks"]
    ):
        raise FixtureValidationError(
            f"queries[{query_idx}] (query_id={query['query_id']!r}): "
            f"relevant_chunks must be a non-empty list"
        )
    seen_chunk_ids: set[str] = set()
    for chunk_idx, entry in enumerate(query["relevant_chunks"]):
        if not isinstance(entry, dict):
            raise FixtureValidationError(
                f"queries[{query_idx}].relevant_chunks[{chunk_idx}]: "
                f"must be a JSON object, got {type(entry).__name__}"
            )
        if "chunk_id" not in entry or "relevance" not in entry:
            raise FixtureValidationError(
                f"queries[{query_idx}].relevant_chunks[{chunk_idx}]: "
                f"missing chunk_id or relevance key"
            )
        cid = entry["chunk_id"]
        rel = entry["relevance"]
        if not isinstance(cid, str) or not _CHUNK_ID_RE.match(cid):
            # D10 of the synthesis: a typo in a curated fixture must
            # report as a malformed chunk_id, not "stale".
            raise FixtureValidationError(
                f"queries[{query_idx}].relevant_chunks[{chunk_idx}]: "
                f"malformed chunk_id {cid!r} — expected "
                f"'arxiv:<paper_id>:<16-hex>'"
            )
        if (
            not isinstance(rel, int)
            or isinstance(rel, bool)
            or rel not in _VALID_RELEVANCE_GRADES
        ):
            raise FixtureValidationError(
                f"queries[{query_idx}].relevant_chunks[{chunk_idx}]: "
                f"relevance must be an integer in {_VALID_RELEVANCE_GRADES}, "
                f"got {type(rel).__name__} ({rel!r})"
            )
        if cid in seen_chunk_ids:
            raise FixtureValidationError(
                f"queries[{query_idx}] (query_id={query['query_id']!r}): "
                f"duplicate chunk_id {cid!r} in relevant_chunks"
            )
        seen_chunk_ids.add(cid)


def _validate_query_set_invariants(
    queries: list[dict],
    chunk_kind_index: dict[str, str],
    fixture_path: Path,
) -> None:
    """The "curation complete" branch (count == 20).

    Checks all of:

    - AC-1: exactly :data:`TARGET_QUERY_COUNT` queries (already
      enforced by caller; assertion here is defense-in-depth).
    - AC-2: every query has at least one grade-3 relevant_chunk.
    - AC-3: every chunk_id resolves to a known manifest entry.
    - AC-7: at least :data:`MIN_QUERIES_BY_KIND` queries reference
      each named ``kind``.
    - Plus: unique ``query_id``s across the set.
    """
    assert len(queries) == TARGET_QUERY_COUNT  # caller guard

    seen_query_ids: set[str] = set()
    queries_by_kind: dict[str, set[str]] = {
        kind: set() for kind in MIN_QUERIES_BY_KIND
    }

    for query_idx, query in enumerate(queries):
        qid = query["query_id"]
        if qid in seen_query_ids:
            raise FixtureValidationError(
                f"queries[{query_idx}]: duplicate query_id {qid!r}"
            )
        seen_query_ids.add(qid)

        # AC-2: at least one grade-3 chunk per query.
        if not any(c["relevance"] == 3 for c in query["relevant_chunks"]):
            raise FixtureValidationError(
                f"queries[{query_idx}] (query_id={qid!r}): no grade-3 "
                "relevant_chunk (AC-2 requires ≥ 1 grade-3 per query)"
            )

        # AC-3: every chunk_id must exist in the manifest set.
        for chunk_idx, entry in enumerate(query["relevant_chunks"]):
            cid = entry["chunk_id"]
            if cid not in chunk_kind_index:
                raise FixtureValidationError(
                    f"queries[{query_idx}] (query_id={qid!r}): "
                    f"relevant_chunks[{chunk_idx}].chunk_id {cid!r} "
                    f"does not exist in any chunk_manifest.json. "
                    f"Either re-chunk the seed corpus or re-curate "
                    f"the fixture (see docs/eval-curation.md)."
                )
            kind = chunk_kind_index[cid]
            if kind in queries_by_kind:
                queries_by_kind[kind].add(qid)

    # AC-7: kind quotas.
    for kind, min_count in MIN_QUERIES_BY_KIND.items():
        actual = len(queries_by_kind[kind])
        if actual < min_count:
            raise FixtureValidationError(
                f"fixture {fixture_path}: only {actual} queries "
                f"reference kind={kind!r} chunks; AC-7 requires "
                f"at least {min_count}"
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate(
    fixture_path: Path | str = DEFAULT_FIXTURE_PATH,
    chunks_dir: Path | str = CHUNKS_DIR,
) -> ValidationResult:
    """Validate the eval fixture.

    Parameters
    ----------
    fixture_path
        Path to ``queries.json`` (default:
        :data:`DEFAULT_FIXTURE_PATH`).
    chunks_dir
        Path to the chunker output root (default: :data:`CHUNKS_DIR`).
        The override is for tests; production calls use the default.

    Returns
    -------
    ValidationResult
        Summary of the call (mode + counts + warnings). On any error,
        :class:`FixtureValidationError` is raised; this function never
        returns a result with an error state.

    Raises
    ------
    FixtureValidationError
        On any structural, identity, or AC violation. The message
        cites the exact AC item (e.g. "AC-2 requires ≥ 1 grade-3 per
        query") and the offending file/path so triage is one read.
    """
    fixture_path = Path(fixture_path)
    chunks_dir = Path(chunks_dir)

    data = _load_fixture(fixture_path)
    _validate_header(data, fixture_path)
    queries = data["queries"]
    n_queries = len(queries)

    manifest_paths = _iter_chunk_manifest_paths(chunks_dir)
    n_manifests = len(manifest_paths)

    # Per-query structural validation always runs (catches malformed
    # entries even in seed mode if the curator started filling things
    # in but committed mid-edit).
    for query_idx, query in enumerate(queries):
        _validate_query_structure(query, query_idx)

    warnings: list[str] = []

    # Behavior matrix: see the module docstring.
    if n_queries == 0:
        # Seed mode. Both branches (corpus present or not) are
        # exit-0-with-warning, but the warning text differs so triage
        # knows what's pending.
        if n_manifests == 0:
            warnings.append(
                "no curated queries and no corpus chunks — both pending "
                "(run the chunker on the seed corpus, then curate per "
                "docs/eval-curation.md)"
            )
        else:
            warnings.append(
                f"no curated queries (corpus has {n_manifests} chunked "
                f"papers) — curation pending per docs/eval-curation.md"
            )
        return ValidationResult(
            mode="seed",
            query_count=0,
            chunk_manifests_found=n_manifests,
            warnings=warnings,
        )

    if n_queries != TARGET_QUERY_COUNT:
        # Partial fixture. Per the synthesis D3, this is always an
        # error — curation is all-or-nothing.
        raise FixtureValidationError(
            f"fixture {fixture_path}: expected 0 (seed) or "
            f"{TARGET_QUERY_COUNT} (complete) queries, got {n_queries}. "
            f"Partial fixtures are rejected to catch accidental "
            f"half-merges of in-progress curation work."
        )

    # n_queries == TARGET_QUERY_COUNT. Need a manifest to resolve
    # chunk_ids; without one, AC-3 cannot pass.
    if n_manifests == 0:
        raise FixtureValidationError(
            f"fixture {fixture_path}: {TARGET_QUERY_COUNT} curated "
            f"queries but no chunk_manifest.json files exist under "
            f"{chunks_dir}. Re-chunk the seed corpus before validating."
        )

    chunk_kind_index = _load_chunk_kind_index(manifest_paths)
    _validate_query_set_invariants(queries, chunk_kind_index, fixture_path)

    return ValidationResult(
        mode="complete",
        query_count=TARGET_QUERY_COUNT,
        chunk_manifests_found=n_manifests,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate tests/eval/fixtures/queries.json against the "
            "current chunker version and chunked-corpus manifests. "
            "Run as part of make test."
        )
    )
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE_PATH),
        help="path to queries.json (default: %(default)s)",
    )
    parser.add_argument(
        "--chunks-dir",
        default=str(CHUNKS_DIR),
        help="path to chunker output root (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    try:
        result = validate(args.fixture, args.chunks_dir)
    except FixtureValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"INFO: {warning}", file=sys.stderr)
    print(
        f"OK: fixture validated in {result.mode} mode "
        f"(queries={result.query_count}, manifests={result.chunk_manifests_found})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())


__all__ = [
    "CHUNKS_DIR",
    "DEFAULT_FIXTURE_PATH",
    "FixtureValidationError",
    "MIN_QUERIES_BY_KIND",
    "TARGET_QUERY_COUNT",
    "ValidationResult",
    "validate",
]

"""Validate a per-notebook ``queries.json`` fixture file.

This is the m4 companion validator for the per-notebook eval fixtures
under ``var/arxmcp/notebooks/<slug>/queries.json``. It is intentionally
SEPARATE from ``tools/validate_eval_fixtures.py`` — that script has a
closed-schema guard against extra top-level keys and validates
chunk-level relevance (``relevant_chunks: [{chunk_id, relevance}, ...]``),
whereas the notebook fixtures use PAPER-level relevance
(``expected_relevant_papers: ["<arxiv_id>", ...]``) plus several
notebook-bookkeeping fields (``notebook_slug``,
``notebook_display_name``, ``curated_by``, ``difficulty_classes``).
Coupling the global eval validator to the notebook schema would
require widening the F3 closed-schema guard and adding a ``--mode
notebook`` branch larger than this standalone script. The
proof-verify-handler-wiring-m4 synthesis (Disagreement 3) chose the
separate-tool path.

CLI contract::

    uv run python tools/validate_notebook_fixtures.py <slug>

- Reads ``var/arxmcp/notebooks/<slug>/queries.json`` and
  ``var/arxmcp/notebooks/<slug>/papers.txt``.
- Validates the queries.json shape, the slug match, the minimum
  query count (``MIN_NOTEBOOK_QUERIES``), and that every
  ``expected_relevant_papers`` entry is both a valid arXiv ID
  (per ``ingest.identifiers.is_valid_paper_id``) and a member of
  the notebook's ``papers.txt``.
- Exits 0 on pass; non-zero with a single-line error to stderr on
  fail. The first failure short-circuits — no continue-on-error.
"""

from __future__ import annotations

import argparse
import json
import sys

from ingest.identifiers import is_valid_arxiv_paper_id
from tools._notebook_common import (
    NotebookError,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    validate_slug,
)

#: Floor on the per-notebook query count. Bridgeland has 10, shimura
#: has 10 — well above the floor. m4 synthesis open-question #1
#: resolved to 5 (low enough to leave room for future curation
#: revisions without breaking the fixture, high enough to flag an
#: accidentally-truncated queries.json).
MIN_NOTEBOOK_QUERIES: int = 5

#: Required top-level keys in the notebook queries.json. The schema
#: also commonly carries ``curated_by``, ``difficulty_classes``, and
#: per-query ``notes`` — those are OPTIONAL and tolerated.
#:
#: If you edit this frozenset, ALSO update the live notebook fixtures
#: at ``var/arxmcp/notebooks/{bridgeland-stability,shimura-varieties}/
#: queries.json`` so the real-notebook happy-path tests at
#: ``tests/tools/test_validate_notebook_fixtures.py::TestHappyPath::
#: test_real_{bridgeland,shimura}_notebook_validates`` continue to
#: pass. The validator <-> live-fixture coupling is intentional
#: (m4 rect F3 cross-reference).
REQUIRED_TOP_KEYS: frozenset[str] = frozenset({
    "schema_version",
    "notebook_slug",
    "notebook_display_name",
    "created_at",
    "queries",
})

#: Required per-query keys. ``notes`` is OPTIONAL.
REQUIRED_QUERY_KEYS: frozenset[str] = frozenset({
    "id",
    "difficulty",
    "text",
    "expected_relevant_papers",
})


class FixtureValidationError(RuntimeError):
    """Raised when the queries.json fails any structural check."""


def _validate_top_level(data: dict, slug: str) -> None:
    """Check required top-level keys + slug match."""
    if not isinstance(data, dict):
        raise FixtureValidationError(
            f"queries.json must be a JSON object; got {type(data).__name__}"
        )
    missing = REQUIRED_TOP_KEYS - set(data)
    if missing:
        raise FixtureValidationError(
            f"queries.json missing required top-level keys: {sorted(missing)}"
        )
    if data["notebook_slug"] != slug:
        raise FixtureValidationError(
            f"queries.json notebook_slug={data['notebook_slug']!r} does "
            f"not match CLI slug {slug!r}"
        )
    if not isinstance(data["queries"], list):
        raise FixtureValidationError(
            f"queries.json 'queries' must be a list; got "
            f"{type(data['queries']).__name__}"
        )
    n = len(data["queries"])
    if n < MIN_NOTEBOOK_QUERIES:
        raise FixtureValidationError(
            f"queries.json has {n} queries; minimum is "
            f"{MIN_NOTEBOOK_QUERIES} (MIN_NOTEBOOK_QUERIES)"
        )


def _validate_queries(queries: list, paper_id_set: set[str]) -> None:
    """Check per-query shape + paper_id membership."""
    seen_ids: set[str] = set()
    for i, q in enumerate(queries):
        if not isinstance(q, dict):
            raise FixtureValidationError(
                f"queries[{i}] must be an object; got {type(q).__name__}"
            )
        missing = REQUIRED_QUERY_KEYS - set(q)
        if missing:
            raise FixtureValidationError(
                f"queries[{i}] missing required keys: {sorted(missing)}"
            )
        qid = q["id"]
        if not isinstance(qid, str) or not qid:
            raise FixtureValidationError(
                f"queries[{i}].id must be a non-empty string; got {qid!r}"
            )
        if qid in seen_ids:
            raise FixtureValidationError(
                f"queries[{i}].id={qid!r} is a duplicate"
            )
        seen_ids.add(qid)
        if not isinstance(q["text"], str) or not q["text"].strip():
            raise FixtureValidationError(
                f"queries[{i}={qid!r}].text must be a non-empty string"
            )
        erp = q["expected_relevant_papers"]
        if not isinstance(erp, list) or not erp:
            raise FixtureValidationError(
                f"queries[{i}={qid!r}].expected_relevant_papers must be a "
                f"non-empty list; got {erp!r}"
            )
        for j, pid in enumerate(erp):
            if not isinstance(pid, str):
                raise FixtureValidationError(
                    f"queries[{i}={qid!r}].expected_relevant_papers[{j}] "
                    f"must be a string; got {type(pid).__name__}"
                )
            # m4 rect F5: is_valid_paper_id was hardened at m1 rect F3
            # to reject trailing-newline / trailing-CR / leading-whitespace
            # classes via the `\Z` anchor (see ingest/identifiers.py:67
            # and tests/test_search_filter.py::TestRectificationGuards).
            # The boundary-class coverage for this validator's own surface
            # lives at tests/tools/test_validate_notebook_fixtures.py::
            # TestPerQueryStructure::test_paper_id_boundary_classes_rejected.
            if not is_valid_arxiv_paper_id(pid):
                raise FixtureValidationError(
                    f"queries[{i}={qid!r}].expected_relevant_papers[{j}]="
                    f"{pid!r} is not a valid arXiv paper_id"
                )
            if pid not in paper_id_set:
                raise FixtureValidationError(
                    f"queries[{i}={qid!r}].expected_relevant_papers[{j}]="
                    f"{pid!r} is not in the notebook's papers.txt"
                )


def validate_notebook_fixture(slug: str) -> dict:
    """Validate the notebook's queries.json against its papers.txt.

    Returns the parsed queries.json dict on success. Raises
    ``FixtureValidationError`` on any structural failure (with a
    single-sentence message naming the failed check).
    """
    validate_slug(slug)
    nb_dir = notebook_dir(slug)
    queries_path = nb_dir / "queries.json"
    papers_path = nb_dir / "papers.txt"

    if not queries_path.is_file():
        raise FixtureValidationError(
            f"queries.json not found at {queries_path}"
        )
    if not papers_path.is_file():
        raise FixtureValidationError(
            f"papers.txt not found at {papers_path}"
        )

    # m4 rect F2: wrap the read paths in try/except OSError so the
    # CLI emits a single-line `FAIL: ...` message per the module
    # docstring contract, rather than dumping a raw Python traceback
    # on a TOCTOU race or a chmod-locked file. `json.JSONDecodeError`
    # is also caught below.
    try:
        paper_ids = read_paper_ids_from_papers_txt(papers_path)
    except OSError as e:
        raise FixtureValidationError(
            f"papers.txt at {papers_path} is unreadable: {e}"
        ) from e
    if not paper_ids:
        raise FixtureValidationError(
            f"papers.txt at {papers_path} contains no valid paper IDs"
        )
    paper_id_set = set(paper_ids)

    try:
        with queries_path.open(encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise FixtureValidationError(
                    f"queries.json at {queries_path} is not valid JSON: {e}"
                ) from e
    except OSError as e:
        raise FixtureValidationError(
            f"queries.json at {queries_path} is unreadable: {e}"
        ) from e

    _validate_top_level(data, slug)
    _validate_queries(data["queries"], paper_id_set)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a per-notebook queries.json fixture against its "
            "papers.txt. Returns 0 on pass; non-zero on any failure."
        )
    )
    parser.add_argument(
        "slug",
        help="The notebook slug (e.g. 'bridgeland-stability').",
    )
    args = parser.parse_args(argv)

    try:
        data = validate_notebook_fixture(args.slug)
    except NotebookError as e:
        print(f"ERROR: invalid notebook slug: {e}", file=sys.stderr)
        return 2
    except FixtureValidationError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    n = len(data["queries"])
    print(
        f"OK: {args.slug} queries.json valid "
        f"(schema_version={data['schema_version']!r}, queries={n})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

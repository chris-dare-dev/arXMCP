"""Build every index derived from a LanceDB dataset, inside that dataset.

A dataset that carries its own indexes can be promoted, rolled back or
backed up as one directory. The producers of a dataset (bulk ingest,
re-embed) call :func:`build_derived_indexes` before they report the
dataset ready, so a cutover never promotes chunks without the indexes
that answer queries over them.

The equations table is not built here: it comes from equation
extraction, which runs per paper during parsing.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from ingest.write_lock import exits_when_write_locked, holds_dataset_write_lock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DerivedIndexSummary:
    corpus_version: int
    definitions: int
    definition_papers: int
    theorem_names: int
    theorem_name_papers: int


@holds_dataset_write_lock("lancedb_path")
def build_derived_indexes(lancedb_path: str | Path) -> DerivedIndexSummary:
    """Build the BM25, definitions and theorem-name indexes of a dataset.

    Each is built for the version in the dataset's ``corpus-version.json``
    and written inside the dataset. Rebuilding is safe: BM25 skips a
    version it already holds, and the other two replace their rows.
    """
    from ingest.bm25_indexer import build_bm25_index
    from ingest.index_definitions import index_definitions_for_corpus
    from ingest.index_theorem_names import build_theorem_names_index
    from server.corpus import read_corpus_version

    path = Path(lancedb_path)
    info = read_corpus_version(lancedb_path=path)
    if info is None:
        raise FileNotFoundError(f"no corpus-version.json in {path}")
    build_bm25_index(path, corpus_version=info.version)
    definitions, definition_papers = index_definitions_for_corpus(path)
    names = build_theorem_names_index(path)
    summary = DerivedIndexSummary(
        corpus_version=info.version,
        definitions=definitions,
        definition_papers=definition_papers,
        theorem_names=sum(names.values()),
        theorem_name_papers=len(names),
    )
    logger.info("derived indexes built for %s: %s", path, summary)
    return summary


@exits_when_write_locked
def _cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rebuild the indexes stored inside a LanceDB dataset."
    )
    parser.add_argument("lancedb_path", type=Path)
    args = parser.parse_args(argv)
    s = build_derived_indexes(args.lancedb_path)
    print(
        f"corpus_version={s.corpus_version} "
        f"definitions={s.definitions} ({s.definition_papers} papers) "
        f"theorem_names={s.theorem_names} ({s.theorem_name_papers} papers)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))

__all__ = ["DerivedIndexSummary", "build_derived_indexes"]

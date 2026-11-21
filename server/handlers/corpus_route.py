"""Which corpus a retrieval call reads: the shared one or a named notebook.

``search_papers(filters={"notebook": slug})`` returns chunk and paper ids
from that notebook's own chunks table, pinned at that notebook's
``corpus_version``. A follow-up call that takes one of those ids has to read
the same table, or a chunk the server just returned comes back as
``found: false`` under the shared corpus's version. Every tool that accepts
a notebook therefore resolves it here, so the validation, the error a caller
sees and the version echoed in the envelope are the same for all of them.

Two steps, because callers validate input before touching ``Resources``:
:func:`parse_notebook` checks the slug's shape (no I/O), and
:func:`resolve_corpus` opens the notebook's table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The ``notebook`` argument's description in ``tools/list``. One string
#: for every tool that takes it, so the argument reads the same everywhere.
NOTEBOOK_ARG_DESCRIPTION = (
    "Notebook slug to read from: pass the filters.notebook value the id "
    "came from in search_papers. Omit for the shared corpus."
)


@dataclass(frozen=True)
class CorpusRoute:
    """The table a call reads and the version its envelope echoes.

    ``corpus_version`` is ``None`` on the shared corpus, which is what
    :func:`server.tools.envelope` takes to mean "the process's own
    version", so a call without a notebook is unchanged.
    """

    table: Any
    corpus_version: int | None
    notebook: str | None


def parse_notebook(value: object, *, arg: str) -> str:
    """Return ``value`` as a validated notebook slug.

    ``arg`` names the argument in the error (``"notebook"``, or
    ``"filters['notebook']"`` for ``search_papers``). An invalid slug is
    a ``ValueError`` — a clean tool error — and is rejected before any
    path is built from it. Callers skip this when no notebook was given.
    """
    if not isinstance(value, str):
        raise ValueError(
            f"{arg} must be a str (a notebook slug), got {type(value).__name__}"
        )
    from ingest.notebooks import (  # noqa: PLC0415
        NotebookError,
        validate_slug,
    )

    try:
        validate_slug(value)
    except NotebookError as exc:
        raise ValueError(f"{arg}={value!r} is not a valid notebook slug: {exc}") from exc
    return value


async def resolve_corpus(r: Any, notebook: str | None, *, arg: str) -> CorpusRoute:
    """Open the corpus ``notebook`` names, or the shared one for ``None``.

    A notebook that does not exist or has not been ingested is a
    ``ValueError`` naming ``arg``, never an empty answer from the shared
    corpus: answering from a different corpus than the caller asked for
    is the silent mismatch this module exists to prevent.
    """
    if notebook is None:
        return CorpusRoute(table=r.chunks_table, corpus_version=None, notebook=None)
    from ingest.notebooks import NotebookError  # noqa: PLC0415
    from server.resources import CorpusNotIngestedError  # noqa: PLC0415

    try:
        table, corpus_info = await r.notebook_table(notebook)
    except (NotebookError, CorpusNotIngestedError) as exc:
        raise ValueError(f"{arg}={notebook!r}: {exc}") from exc
    return CorpusRoute(
        table=table, corpus_version=corpus_info.version, notebook=notebook
    )

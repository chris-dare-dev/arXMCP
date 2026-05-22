"""REST surface for the notebook UI under ``/ui/api`` (m7).

Wired in ``server/main.py::create_app`` via::

    app.include_router(notebooks_router, prefix="/ui/api")

Routes (full paths after the ``/ui/api`` prefix):

- ``GET    /notebooks``                         — list all notebooks
- ``POST   /notebooks``                         — create notebook (201) or 409 on dup
- ``DELETE /notebooks/{slug}``                  — metadata-only delete (204)
- ``GET    /notebooks/{slug}/papers``           — list junction rows
- ``POST   /notebooks/{slug}/papers``           — add paper from arxiv URL (201)
- ``DELETE /notebooks/{slug}/papers/{paper_id}`` — remove single junction row (204)

**Deletion semantics** (resolved 2026-05-21, restated from the m7
brief): ``DELETE /ui/api/notebooks/{slug}`` is metadata-only — the
on-disk LanceDB / BM25 / ar5iv assets under
``var/arxmcp/notebooks/{slug}/`` are NOT touched. Destructive on-disk
wipe is the explicit job of ``tools/notebook_purge.py <slug>`` (m6).
The implementation enforces this by ONLY calling
:meth:`NotebooksStore.delete_notebook`; no filesystem mutation.

**Slug + URL validation** delegate to existing project helpers:
- ``tools._notebook_common.validate_slug`` (m6 F1/F3 path-traversal
  + symlink defense)
- ``ingest.identifiers.is_valid_paper_id`` (m1 rect F3 \\Z-anchor
  hardening against trailing-newline classes)

No re-implementation of either regex — both are shared with the
``tools/notebook_*.py`` CLI scripts.
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ingest.identifiers import is_valid_paper_id
from tools._notebook_common import (
    NotebookError,
    notebook_dir,
    validate_slug,
)

if TYPE_CHECKING:
    from server.notebooks_store import NotebooksStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current time as an ISO-8601 UTC string.

    Factored as a module-level helper so tests can monkeypatch a
    deterministic value (``server.routes.notebooks._now_iso``).
    Format: ``YYYY-MM-DDTHH:MM:SS+00:00`` (seconds precision —
    enough for human-readable ordering; not load-bearing for any
    primary key).
    """
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


#: arXiv URL host whitelist for m7. Only ``arxiv.org`` (the canonical
#: paper host) is in scope. ``ar5iv.labs.arxiv.org`` is explicitly
#: out of scope per the m7 synthesis Disagreement-3 resolution;
#: m8's paste UI may extend this if needed.
_ACCEPTED_HOSTS: frozenset[str] = frozenset({"arxiv.org"})


def _arxiv_url_to_paper_id(url: str) -> str | None:
    """Extract and validate the paper_id from an arxiv.org URL.

    Returns the paper_id string on success, or ``None`` if the URL
    does not match the accepted form. Caller translates ``None`` to
    HTTP 422.

    Accepted forms (m7 FM-4):
      - ``https://arxiv.org/abs/<paper_id>``
      - ``http://arxiv.org/abs/<paper_id>``  (scheme tolerated)
      - ``https://arxiv.org/abs/<paper_id>v<N>`` (version suffix)
      - ``https://arxiv.org/abs/hep-th/0001234`` (old style)

    Rejected (returns None):
      - ``www.arxiv.org`` (subdomain not in whitelist)
      - ``arxiv.org/pdf/...`` (path prefix mismatch)
      - ``ar5iv.labs.arxiv.org/html/...`` (out of m7 scope)
      - Any host outside :data:`_ACCEPTED_HOSTS`
      - Trailing newlines / whitespace (rejected via
        :func:`ingest.identifiers.is_valid_paper_id` \\Z anchor)
    """
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.hostname not in _ACCEPTED_HOSTS:
        return None
    path = parsed.path
    prefix = "/abs/"
    if not path.startswith(prefix):
        return None
    candidate = path[len(prefix):]
    # Strip trailing slash for cosmetic tolerance (``/abs/<id>/``).
    candidate = candidate.rstrip("/")
    if not candidate or not is_valid_paper_id(candidate):
        return None
    return candidate


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_notebooks_store(request: Request) -> NotebooksStore:
    """FastAPI dependency that fetches the :class:`NotebooksStore`
    instance attached to ``app.state`` in the lifespan.

    Raises HTTP 503 if the store is not yet initialized (server still
    in startup). This is defensive — the lifespan opens the store
    BEFORE yielding so requests should never see this case in normal
    operation.
    """
    store = getattr(request.app.state, "notebooks_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="notebook store not initialized",
        )
    return store


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class NotebookCreate(BaseModel):
    """Body for ``POST /ui/api/notebooks``.

    Only ``slug`` is required; ``display_name`` defaults to ``""``.
    ``lancedb_path`` is AUTO-DERIVED from ``NOTEBOOKS_BASE / slug /
    "lancedb"`` (the caller MUST NOT supply a custom path — that
    would let a buggy or malicious client steer a notebook at any
    on-disk location bypassing the per-notebook directory contract
    from m6).
    """

    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=256)


class PaperAdd(BaseModel):
    """Body for ``POST /ui/api/notebooks/{slug}/papers``."""

    arxiv_url: str = Field(min_length=1, max_length=512)


# ---------------------------------------------------------------------------
# Notebook routes
# ---------------------------------------------------------------------------


@router.get("/notebooks")
async def list_notebooks(
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> list[dict[str, str]]:
    """Return all notebooks ordered by ``created_at DESC``."""
    return await store.list_notebooks()


@router.post(
    "/notebooks",
    status_code=status.HTTP_201_CREATED,
)
async def create_notebook(
    body: NotebookCreate,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, str]:
    """Create a new notebook.

    Idempotency contract (m7 AC #1): a duplicate slug returns HTTP
    409, never silently overwrites the existing row. The
    ``sqlite3.IntegrityError`` from the PRIMARY KEY constraint is
    caught and translated.

    Side effect: creates ``var/arxmcp/notebooks/<slug>/`` on disk
    (idempotent via ``mkdir(parents=True, exist_ok=True)``). The
    directory may ALREADY exist from a prior notebook with the same
    slug (m7 AC #3 — DELETE is metadata-only).
    """
    # FM-2: slug regex via shared helper.
    try:
        validate_slug(body.slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # Belt-and-braces: notebook_dir runs the m6 F3 symlink-rejection
    # containment check before any mkdir.
    try:
        nb_dir = notebook_dir(body.slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # Auto-derive the LanceDB path from the canonical per-notebook
    # layout. Stored as a string for SQLite (Path objects don't
    # serialize cleanly across the boundary).
    lancedb_path = str(nb_dir / "lancedb")

    try:
        await store.create_notebook(
            slug=body.slug,
            display_name=body.display_name,
            lancedb_path=lancedb_path,
            created_at=_now_iso(),
        )
    except sqlite3.IntegrityError as e:
        # FM-5: duplicate slug. The async lock inside NotebooksStore
        # serializes writes in-process; this catch is for cross-
        # process correctness + AC #1 idempotency.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"notebook slug {body.slug!r} already exists",
        ) from e

    # AC #1 side effect: create the on-disk directory. AFTER the
    # SQLite INSERT so a constraint violation doesn't leave an
    # orphan directory. FM-9: exist_ok=True because the directory
    # may already exist from a prior incarnation.
    nb_dir.mkdir(parents=True, exist_ok=True)

    return {
        "slug": body.slug,
        "display_name": body.display_name,
        "lancedb_path": lancedb_path,
    }


@router.delete(
    "/notebooks/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_notebook(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> None:
    """Drop the notebook's metadata + cascade to ``notebook_papers``.

    Metadata-only — does NOT touch on-disk
    ``var/arxmcp/notebooks/<slug>/`` assets. The on-disk wipe is the
    explicit job of ``tools/notebook_purge.py``.

    404 if the slug doesn't exist (no row to delete).
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    deleted = await store.delete_notebook(slug)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    # 204 No Content — explicit None return matches FastAPI's
    # convention for body-less responses.
    return None


# ---------------------------------------------------------------------------
# Paper routes
# ---------------------------------------------------------------------------


@router.get("/notebooks/{slug}/papers")
async def list_papers(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> list[dict[str, str]]:
    """Return paper junction rows for the notebook, ``added_at DESC``.

    404 if the notebook doesn't exist (distinguishes "no such notebook"
    from "notebook exists but is empty").
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    if await store.get_notebook(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    return await store.list_papers(slug)


@router.post(
    "/notebooks/{slug}/papers",
    status_code=status.HTTP_201_CREATED,
)
async def add_paper(
    slug: str,
    body: PaperAdd,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, str]:
    """Normalize an arxiv URL to a paper_id and insert a junction row.

    AC #2: validates URL via :func:`_arxiv_url_to_paper_id` (host
    whitelist + path-prefix check + ``is_valid_paper_id`` regex).
    Returns 422 on a malformed URL; 404 if the notebook doesn't
    exist; 409 on duplicate ``(slug, paper_id)``.
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    if await store.get_notebook(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )

    paper_id = _arxiv_url_to_paper_id(body.arxiv_url)
    if paper_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"arxiv_url {body.arxiv_url!r} did not match an accepted "
                f"form (expected: https://arxiv.org/abs/<paper_id>)"
            ),
        )

    try:
        await store.add_paper(
            slug=slug, paper_id=paper_id, added_at=_now_iso(),
        )
    except sqlite3.IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"paper {paper_id!r} already in notebook {slug!r}"
            ),
        ) from e

    return {"slug": slug, "paper_id": paper_id}


@router.delete(
    "/notebooks/{slug}/papers/{paper_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_paper(
    slug: str,
    paper_id: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> None:
    """Remove a single paper from a notebook's junction.

    Note: ``paper_id`` uses ``{paper_id:path}`` syntax to accept the
    embedded slash in old-style IDs (e.g. ``hep-th/0001234``).
    Validated against :func:`is_valid_paper_id` to reject path-
    traversal attempts via crafted IDs (m1-rect-F3 hardening).

    Returns 422 on invalid paper_id form; 404 if the (slug, paper_id)
    junction row doesn't exist.
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    if not is_valid_paper_id(paper_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"paper_id {paper_id!r} is not a valid arXiv id",
        )

    removed = await store.remove_paper(slug, paper_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"paper {paper_id!r} not in notebook {slug!r}"
            ),
        )
    return None


__all__ = [
    "NotebookCreate",
    "PaperAdd",
    "get_notebooks_store",
    "router",
]

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

import contextlib
import datetime as _dt
import html
import logging
import os
import sqlite3
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse
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


#: arXiv URL host whitelist. m7 shipped with only ``arxiv.org``;
#: m8 extends to also accept ``ar5iv.labs.arxiv.org`` (AC #3) so
#: the htmx UI's URL-paste form handles both forms operators
#: commonly find on the web.
_ACCEPTED_HOSTS: frozenset[str] = frozenset({
    "arxiv.org", "ar5iv.labs.arxiv.org",
})

#: Per-host path-prefix dispatch (m8). ``arxiv.org`` papers live
#: under ``/abs/<id>``; ar5iv's HTML mirror lives under
#: ``/html/<id>``. The extracted paper_id is then validated via
#: ``is_valid_paper_id`` regardless of which host it came from
#: — the m1-rect-F3 ``\Z``-anchor hardening protects both paths.
_HOST_PATH_PREFIX: dict[str, str] = {
    "arxiv.org": "/abs/",
    "ar5iv.labs.arxiv.org": "/html/",
}


def _arxiv_url_to_paper_id(url: str) -> str | None:
    """Extract and validate the paper_id from an arxiv.org URL.

    Returns the paper_id string on success, or ``None`` if the URL
    does not match the accepted form. Caller translates ``None`` to
    HTTP 422.

    Accepted forms (m7 FM-4 + m8 AC #3):
      - ``https://arxiv.org/abs/<paper_id>``
      - ``http://arxiv.org/abs/<paper_id>``  (scheme tolerated)
      - ``https://arxiv.org/abs/<paper_id>v<N>`` (version suffix)
      - ``https://arxiv.org/abs/hep-th/0001234`` (old style)
      - ``https://ar5iv.labs.arxiv.org/html/<paper_id>`` (m8)
      - ``https://ar5iv.labs.arxiv.org/html/<paper_id>v<N>`` (m8)

    Rejected (returns None):
      - ``www.arxiv.org`` (subdomain not in whitelist)
      - ``arxiv.org/pdf/...`` (path prefix mismatch — only /abs/)
      - ``ar5iv.labs.arxiv.org/abs/...`` (wrong prefix for that host)
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
    # m8: dispatch on the host to pick the right path prefix
    # (arxiv.org → /abs/, ar5iv.labs.arxiv.org → /html/).
    prefix = _HOST_PATH_PREFIX.get(parsed.hostname, "")
    path = parsed.path
    if not prefix or not path.startswith(prefix):
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
    #
    # m7 rect F3: wrap mkdir in try/except so a failure (permission
    # denied, disk full, parent-readonly) rolls back the SQLite row
    # rather than leaving the operator with "row exists but disk is
    # broken" → permanent 409 on retry. The rollback uses the same
    # delete_notebook the DELETE handler calls — cascading FK cleans
    # up any junction rows that somehow landed (shouldn't be any on
    # the create path, but defensive).
    try:
        nb_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        await store.delete_notebook(body.slug)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"created notebook row but mkdir failed for "
                f"{nb_dir!s}: {e}. SQLite row rolled back; retry "
                f"once the disk condition is resolved."
            ),
        ) from e

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


# ---------------------------------------------------------------------------
# m8 — Upload ar5iv HTML file for a paper
# ---------------------------------------------------------------------------


#: Max bytes the magic-byte sniff reads from an uploaded file. HTML
#: files start with either ``<!DOCTYPE`` (case-insensitive — most
#: ar5iv output uses ``<!DOCTYPE html>``) or just ``<html``. 16 bytes
#: is plenty to disambiguate from binary formats (.exe, .pdf, .zip)
#: while staying small enough to avoid heap pressure on truncated
#: streams.
_MAGIC_SNIFF_BYTES: int = 16


def _is_html_bytes(head: bytes) -> bool:
    """Return True if ``head`` (first 16 bytes of an upload) looks
    like an HTML document.

    Strict gate (m8 FM-2): the file MUST start with ``<!`` (typical
    ``<!DOCTYPE html>``) or ``<h`` (bare ``<html...>``). Whitespace
    leniency limited to the first byte being a leading-BOM-or-ASCII
    space so well-formed-but-formatted HTML survives. Anything else
    is rejected — `.exe`, `.zip`, `.pdf`, JSON, JavaScript, etc.
    Case-insensitive on the alpha portion (``<HTML`` is valid).
    """
    if not head:
        return False
    s = head.lstrip(b"\xef\xbb\xbf \t\r\n")  # strip BOM + leading whitespace
    if not s:
        return False
    return s[:2].lower() in (b"<!", b"<h")


@router.post(
    "/notebooks/{slug}/papers/upload",
    response_class=HTMLResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_paper(
    slug: str,
    paper_id: str = Form(...),  # noqa: B008  (FastAPI DI pattern)
    file: UploadFile = File(...),  # noqa: B008  (FastAPI DI pattern)
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> Response:
    """Upload an ar5iv HTML file for a paper into a notebook (m8 AC #2).

    Multipart form fields:
      - ``paper_id``: arXiv paper id (validated via
        :func:`is_valid_paper_id`). The on-disk filename is derived
        from this field, NEVER from ``file.filename`` (m8 FM-4 —
        path-traversal defense).
      - ``file``: the ar5iv HTML file (≤ 10 MB per
        ``RequestBodySizeLimitMiddleware``'s ``prefix_caps`` carve-out
        for ``/ui/api/notebooks``).

    Server behavior:
      1. Validate slug (path-traversal regex) and paper_id format.
      2. Confirm the notebook exists in the SQLite store (404 else).
      3. Stream-read the upload (already capped at 10 MB upstream).
      4. Magic-byte sniff (first 16 bytes start with ``<!`` or
         ``<h``) — reject non-HTML uploads with 422 (FM-2).
      5. Atomic write: ``Path(.../{paper_id}.html.tmp).write_bytes(...)``
         then ``os.replace(...)`` to the final ``.html`` name
         (FM-5 — readers never see a partial file).
      6. Insert junction row; 409 on duplicate ``(slug, paper_id)``.
      7. Return an HTML ``<tr>`` fragment suitable for htmx
         ``hx-swap="beforeend"`` into the papers table.

    The ``file.filename`` field is used ONLY for logging — it is
    NEVER interpolated into a filesystem path (FM-4 / m6 F1
    CRITICAL parity).
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

    if await store.get_notebook(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )

    # Read the upload. The 10 MB upstream cap means this is bounded;
    # ar5iv HTML is typically 100 KB – 5 MB, well under the cap.
    try:
        content = await file.read()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"could not read uploaded file: {e}",
        ) from e

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="uploaded file is empty",
        )

    # FM-2: magic-byte sniff. Reject non-HTML uploads even if the
    # client lied about Content-Type or used a forged .html extension.
    if not _is_html_bytes(content[:_MAGIC_SNIFF_BYTES]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "uploaded file does not appear to be HTML "
                f"(first {_MAGIC_SNIFF_BYTES} bytes must start with "
                "'<!' or '<h')"
            ),
        )

    # Compute the on-disk paths. FM-4: filename derives EXCLUSIVELY
    # from the validated paper_id, NEVER from file.filename. The
    # ar5iv subdirectory is created on first upload (notebook_dir
    # runs the m6 F3 symlink-rejection check).
    try:
        nb_dir = notebook_dir(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    ar5iv_dir = nb_dir / "ar5iv"
    try:
        ar5iv_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"could not create ar5iv directory: {e}",
        ) from e

    # paper_id may contain a slash (old-style hep-th/0001234); turn
    # that into a flat filename with the slash replaced so the
    # on-disk path stays single-level. The flat form is unambiguous
    # because is_valid_paper_id already constrains the character
    # set (no shell metachars).
    flat_paper_id = paper_id.replace("/", "_")
    target_path = ar5iv_dir / f"{flat_paper_id}.html"
    tmp_path = ar5iv_dir / f"{flat_paper_id}.html.tmp"

    # FM-5: atomic write. Write to .tmp, then os.replace() to the
    # final name so readers never see a partial file.
    try:
        tmp_path.write_bytes(content)
        os.replace(tmp_path, target_path)
    except OSError as e:
        # Clean up the .tmp file if it survived.
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"could not write uploaded file: {e}",
        ) from e

    # Insert the junction row. FM-5: 409 on duplicate (slug, paper_id)
    # mirrors the m7 add_paper handler's behavior. The on-disk file
    # has already been overwritten atomically — idempotent.
    try:
        await store.add_paper(
            slug=slug, paper_id=paper_id, added_at=_now_iso(),
        )
    except sqlite3.IntegrityError:
        # Duplicate junction row — the file is now updated on disk
        # (idempotent overwrite was the intended UX). Return 200
        # with a "row already existed" HTML fragment rather than 409,
        # because the upload itself succeeded.
        return HTMLResponse(
            status_code=status.HTTP_200_OK,
            content=_paper_row_html(
                slug=slug,
                paper_id=paper_id,
                added_at="(existing row; file updated)",
            ),
        )

    logger.info(
        "uploaded ar5iv html: slug=%s paper_id=%s bytes=%d "
        "claimed_filename=%r",
        slug, paper_id, len(content), file.filename,
    )

    return HTMLResponse(
        status_code=status.HTTP_201_CREATED,
        content=_paper_row_html(
            slug=slug, paper_id=paper_id, added_at=_now_iso(),
        ),
    )


def _paper_row_html(slug: str, paper_id: str, added_at: str) -> str:
    """Build an HTML ``<tr>`` fragment for the upload handler's
    htmx-swap response.

    Kept as a Python helper rather than a Jinja2 partial because the
    fragment is tiny and inlining keeps the upload handler
    self-contained. All interpolated values are HTML-escaped via
    :func:`html.escape` — paper_id is regex-validated upstream and
    cannot contain HTML-significant characters today, but escaping
    is defensive.

    m10: the table now has FOUR columns (Paper ID, Added, Preview,
    Actions) to match the rendered ``notebook_detail.html`` body.
    The Preview cell is always a live link in this fragment because
    the upload handler just wrote the notebook-scoped ar5iv HTML to
    disk — ``has_preview`` is True by construction. The Actions
    cell shows "uploaded" rather than a Remove button (the m8
    pattern: immediately providing Remove after upload is UX
    confusion; the next page-load restores the standard Remove
    affordance via the rendered template).
    """
    preview_url = (
        f"/ui/notebooks/{html.escape(slug)}/papers/"
        f"{html.escape(paper_id)}/preview"
    )
    return (
        f'<tr data-slug="{html.escape(slug)}" '
        f'data-paper-id="{html.escape(paper_id)}">'
        f'<td>{html.escape(paper_id)}</td>'
        f'<td>{html.escape(added_at)}</td>'
        f'<td><a href="{preview_url}" target="_blank" rel="noopener">'
        f"Preview</a></td>"
        f'<td>uploaded</td>'
        f"</tr>"
    )


# ---------------------------------------------------------------------------
# m9 — Ingest trigger + status polling
# ---------------------------------------------------------------------------


def _get_ingest_tracker(request: Request):
    """FastAPI dependency: fetch the ``IngestTaskTracker`` attached
    to ``app.state`` in the lifespan (m9).

    Raises 503 if the tracker is not yet initialized (server
    still in startup) — defensive; the lifespan attaches the
    tracker BEFORE yielding.
    """
    tracker = getattr(request.app.state, "ingest_tracker", None)
    if tracker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingest tracker not initialized",
        )
    return tracker


@router.post(
    "/notebooks/{slug}/ingest",
    response_class=HTMLResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_ingest(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> Response:
    """Spawn a background ingest for ``slug`` (m9 AC #1).

    Returns 202 Accepted with an HTML fragment that the htmx UI
    swaps into ``#ingest-status``. The fragment carries the
    ``hx-trigger="every 2s"`` for the polling loop; the polling
    endpoint returns HTTP 286 when the run reaches a terminal
    state to stop the loop (m9 synthesis D2).

    Sequencing (FM-7 closure): validate → 409-check → INSERT row
    → spawn subprocess task → return fragment. The DB row exists
    BEFORE the first 2s poll fires.

    409 collision (AC #3): two layers — in-memory ``is_running``
    on the live ``asyncio.Task`` (primary) + DB
    ``has_running_ingest`` (cross-restart fallback).
    """
    from server.ingest_tracker import IngestTaskTracker  # noqa: PLC0415

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

    tracker: IngestTaskTracker = _get_ingest_tracker(request)

    # AC #3: 409 if any in-flight ingest exists for this slug.
    # Two-layer check — in-memory authoritative for the running
    # process, DB fallback for the crash-restart case.
    if tracker.is_running(slug) or await store.has_running_ingest(slug):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"an ingest is already in flight for notebook "
                f"{slug!r} — wait for it to finish before triggering "
                f"another"
            ),
        )

    # FM-7: insert the run row BEFORE spawning the task so the
    # first 2s poll always finds a row to render.
    started_at = _now_iso()
    run_id = await store.insert_ingest_run(slug, started_at)

    # Fire-and-forget the subprocess via the tracker; the task
    # ref is stored on the tracker to prevent GC.
    tracker.start_ingest(
        slug=slug, run_id=run_id, store=store,
        now_iso_provider=_now_iso,
    )

    return HTMLResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=_ingest_status_fragment(
            slug=slug, run_id=run_id, status="running",
            started_at=started_at, finished_at=None,
            exit_code=None, stderr_tail=None,
        ),
    )


@router.get(
    "/notebooks/{slug}/ingest/latest",
    response_class=HTMLResponse,
)
async def latest_ingest(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> Response:
    """Return an HTML fragment describing the most recent ingest
    run for ``slug`` — for htmx ``every 2s`` polling (m9 AC #1).

    Status-code contract (m9 synthesis D2 — HTTP 286 is the
    htmx-documented polling-stop signal):
      - 200 ``running``   — htmx keeps polling
      - 200 ``none``      — no run yet; htmx keeps polling
      - 286 ``success``   — htmx stops polling
      - 286 ``failed``    — htmx stops polling
      - 404 — notebook doesn't exist; htmx stops polling
        (the missing-row case for a real notebook returns 200
        ``none``; only the no-such-notebook case 404s)
      - 422 — malformed slug

    m9 rect F6: this endpoint reads exclusively from the SQLite
    store (NOT the in-memory ``IngestTaskTracker``). The DB row
    is authoritative for polling because the trigger handler
    INSERTs ``running`` before spawning the task AND the task's
    cancel-path (m9 rect F1) + happy-path both UPDATE the row
    inline before returning. The ``IngestTaskTracker`` is
    consulted ONLY by the trigger handler's 409-collision check
    where in-memory authority over live tasks matters.
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

    row = await store.get_latest_ingest_run(slug)
    if row is None:
        return HTMLResponse(
            status_code=status.HTTP_200_OK,
            content=_ingest_status_fragment(
                slug=slug, run_id=None, status="none",
                started_at=None, finished_at=None,
                exit_code=None, stderr_tail=None,
            ),
        )

    # HTTP 286: terminal-state polling-stop signal (htmx canonical).
    response_status = (
        status.HTTP_200_OK
        if row["status"] == store.INGEST_STATUS_RUNNING
        else 286  # custom code for htmx; not in starlette.status
    )
    return HTMLResponse(
        status_code=response_status,
        content=_ingest_status_fragment(
            slug=slug,
            run_id=row["id"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            exit_code=row["exit_code"],
            stderr_tail=row["stderr_tail"],
        ),
    )


def _ingest_status_fragment(
    *,
    slug: str,
    run_id: int | None,
    status: str,
    started_at: str | None,
    finished_at: str | None,
    exit_code: int | None,
    stderr_tail: str | None,
) -> str:
    """Build the HTML fragment swapped into ``#ingest-status``.

    The ``running`` fragment carries the ``hx-trigger="every 2s"``
    polling attribute; terminal-state fragments OMIT it
    (defense-in-depth on top of the HTTP 286 polling-stop signal).
    The ``slug`` and other interpolated values are HTML-escaped at
    the boundary (the m8 ``_paper_row_html`` precedent); the
    ``stderr_tail`` value is ALREADY html.escape'd by
    ``prepare_stderr_tail`` so it is interpolated raw into a
    ``<pre>`` here.
    """
    safe_slug = html.escape(slug)
    if status == "none":
        return (
            f'<div id="ingest-status" data-status="none" '
            f'hx-get="/ui/api/notebooks/{safe_slug}/ingest/latest" '
            f'hx-trigger="every 2s" hx-target="#ingest-status" '
            f'hx-swap="outerHTML">'
            f"No ingest runs yet."
            f"</div>"
        )
    if status == "running":
        return (
            f'<div id="ingest-status" data-status="running" '
            f'hx-get="/ui/api/notebooks/{safe_slug}/ingest/latest" '
            f'hx-trigger="every 2s" hx-target="#ingest-status" '
            f'hx-swap="outerHTML">'
            f"Status: running"
            f" · Started {html.escape(started_at or '')}"
            f" · Run #{run_id}"
            f"</div>"
        )
    if status == "success":
        return (
            f'<div id="ingest-status" data-status="success">'
            f"Status: success"
            f" · Finished {html.escape(finished_at or '')}"
            f" · Run #{run_id}"
            f"</div>"
        )
    # status == "failed"
    safe_exit = html.escape(str(exit_code)) if exit_code is not None else "?"
    # stderr_tail is already html.escape'd by prepare_stderr_tail.
    stderr_pre = (
        f"<pre>{stderr_tail}</pre>" if stderr_tail else ""
    )
    return (
        f'<div id="ingest-status" data-status="failed">'
        f"Status: failed"
        f" · Exit {safe_exit}"
        f" · Run #{run_id}"
        f"{stderr_pre}"
        f"</div>"
    )


__all__ = [
    "NotebookCreate",
    "PaperAdd",
    "get_notebooks_store",
    "router",
    "upload_paper",
]

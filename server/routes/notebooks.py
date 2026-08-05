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
import io
import json
import logging
import os
import re
import sqlite3
import tarfile
from pathlib import Path
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

from ingest.identifiers import is_valid_arxiv_paper_id, is_valid_paper_id
from server.operator_settings import get_contact_email
from tools._notebook_common import (
    NOTEBOOKS_BASE,
    NotebookError,
    notebook_dir,
    notebook_lancedb_path,
    validate_slug,
)
from tools.discover_for_notebook import discover_for_notebook_async
from tools.security.pdfid import find_javascript as _pdf_find_javascript

if TYPE_CHECKING:
    from server.notebooks_store import NotebooksStore
    from tools.discover_for_notebook import DiscoveryCandidate

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
    if not candidate or not is_valid_arxiv_paper_id(candidate):
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


#: notebook-paper-discovery-m1: the arXiv categories a notebook may
#: declare for topic-driven discovery (CLAUDE.md §2 target set:
#: ``math.AG``, ``math.NT``, ``math-ph``, ``hep-th``). The empty string
#: is ALSO valid (no category declared) and is checked separately so a
#: blank field is never rejected.
_VALID_DISCOVERY_CATEGORIES: frozenset[str] = frozenset(
    {"math.AG", "math.NT", "math-ph", "hep-th"}
)


def _validate_discovery_category(value: str) -> None:
    """Raise :class:`NotebookError` if ``value`` is a non-empty non-member.

    The empty string is accepted (no category declared — FM-1). Per
    ``CLAUDE.md §4.7`` this uses ``if … raise``, NOT ``assert`` (Python
    ``-O`` strips asserts). The route handlers translate ``NotebookError``
    to HTTP 422, mirroring :func:`validate_slug`'s call sites.
    """
    if value and value not in _VALID_DISCOVERY_CATEGORIES:
        raise NotebookError(
            f"discovery_category {value!r} is not one of "
            f"{sorted(_VALID_DISCOVERY_CATEGORIES)} (or empty)"
        )


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class NotebookCreate(BaseModel):
    """Body for ``POST /ui/api/notebooks``.

    Only ``slug`` is required; ``display_name`` defaults to ``""`` and
    ``notebook_kind`` defaults to ``"arxiv"``. ``lancedb_path`` is
    AUTO-DERIVED from ``NOTEBOOKS_BASE / slug / "lancedb"`` (the caller
    MUST NOT supply a custom path — that would let a buggy or
    malicious client steer a notebook at any on-disk location
    bypassing the per-notebook directory contract from m6).

    textbook-ingest-m3: ``notebook_kind`` ``str`` with Pydantic
    pattern ``^(arxiv|textbook)$``. Operator opt-in for the textbook-
    corpus path (parser e2 + chunker e3 ship later); arXiv remains the
    default. The pattern validation rejects ``"freeform-garbage"`` at
    the route layer before it reaches the SQLite writer.
    """

    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=256)
    notebook_kind: str = Field(
        default="arxiv",
        pattern="^(arxiv|textbook)$",
    )
    # notebook-paper-discovery-m1: optional topic metadata for the
    # m2-m4 discovery channels. ``discovery_category`` is enum-validated
    # at the handler via ``_validate_discovery_category`` (Pydantic
    # max_length here is only a defense-in-depth length bound, NOT the
    # enum check). ``description`` is free text, rendered autoescaped.
    discovery_category: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=512)


class NotebookRename(BaseModel):
    """Body for ``PATCH /ui/api/notebooks/{slug}`` (notebook-surface-expansion-m2).

    Carries ONLY ``display_name`` — slug / notebook_kind / parse_status are
    NOT acceptable PATCH fields (mass-assignment defense; the store method
    takes only ``(slug, display_name)``). Same ``max_length=256`` bound as
    ``NotebookCreate`` → FastAPI returns 422 on an over-long name before the
    handler body runs. NO ``min_length``: an empty string is a valid value
    (clears the display name; renders as ``—``).
    """

    display_name: str = Field(max_length=256)


class NotebookTopicUpdate(BaseModel):
    """Body for ``PATCH /ui/api/notebooks/{slug}/topic`` (notebook-paper-discovery-m1).

    Carries ONLY the two topic-metadata fields — ``slug`` /
    ``display_name`` / ``notebook_kind`` / ``parse_status`` are NOT
    acceptable here (mass-assignment defense; the dedicated ``/topic``
    sub-route keeps the rename endpoint's contract untouched). Both
    fields accept an empty string (clears the topic). ``discovery_category``
    is enum-validated in the handler via ``_validate_discovery_category``;
    the ``max_length`` bounds here are only defense-in-depth.
    """

    discovery_category: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=512)


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
    # ui-attractive-polish-m5 (UPL-12 v1): union return (HTMLResponse
    # | dict) — mirrors the m4 add_paper precedent. response_model=None
    # suppresses FastAPI's Pydantic-model autogeneration on the union.
    response_model=None,
)
async def create_notebook(
    body: NotebookCreate,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse | dict[str, str]:
    """Create a new notebook.

    Idempotency contract (m7 AC #1): a duplicate slug returns HTTP
    409, never silently overwrites the existing row. The
    ``sqlite3.IntegrityError`` from the PRIMARY KEY constraint is
    caught and translated.

    Side effect: creates ``var/arxmcp/notebooks/<slug>/`` on disk
    (idempotent via ``mkdir(parents=True, exist_ok=True)``). The
    directory may ALREADY exist from a prior notebook with the same
    slug (m7 AC #3 — DELETE is metadata-only).

    ui-attractive-polish-m5 (UPL-12 v1): content-negotiation on the
    ``HX-Request: true`` header. htmx clients get a ``<tr>`` fragment
    for ``hx-swap="beforeend"`` into ``#notebooks-tbody`` (no full-
    page reload); non-htmx clients (curl, scripts) still get the
    existing JSON dict body. Mirrors the m4 ``add_paper`` precedent
    exactly — Spike-2 pre-flight applies: validation runs BEFORE the
    response fork; the fragment uses ``_notebook_row_html`` (which
    html.escape()s every interpolated value); the ``HX-Request``
    header is a client hint NOT a trust boundary. The HTML branch
    deliberately omits the host-path-leak ``lancedb_path`` field
    (per ``06-mcp-server-design.md`` note on lancedb_path info-leak)
    — the JSON branch preserves it for backwards compatibility with
    scripted callers.
    """
    # FM-2: slug regex via shared helper.
    try:
        validate_slug(body.slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # notebook-paper-discovery-m1: reject a bad discovery_category at
    # the route boundary (empty string is allowed — FM-1).
    try:
        _validate_discovery_category(body.discovery_category)
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

    # textbook-ingest-m6: textbook-kind notebooks land with
    # ``parse_status='pending'`` so the upload route's parse-task
    # scheduler observes the right initial state. arxiv-kind keeps
    # the column-level default ('skipped') by passing
    # ``parse_status=None``.
    initial_parse_status = (
        "pending" if body.notebook_kind == "textbook" else None
    )
    # notebook-paper-discovery-m1 rect F1: strip C0 control chars + DEL
    # from ``description`` BEFORE storage, mirroring the PATCH /topic path
    # (``update_notebook_topic``) and the rename handler. The design-note
    # contract (.claude/notes/notebook-discovery-model.md §1) states the
    # field is "control chars stripped before storage"; m2's arXiv query
    # builder reads it as an ``abs:``/``ti:`` keyword string, so it must
    # be clean text regardless of which write path created the notebook.
    cleaned_description = _CONTROL_CHARS_RE.sub("", body.description)
    # ui-attractive-polish-m5 (UPL-12 v1): capture once for both the
    # store insert + the fragment response (mirrors m4 add_paper at
    # the equivalent call site).
    created_at = _now_iso()
    try:
        await store.create_notebook(
            slug=body.slug,
            display_name=body.display_name,
            lancedb_path=lancedb_path,
            created_at=created_at,
            notebook_kind=body.notebook_kind,
            parse_status=initial_parse_status,
            discovery_category=body.discovery_category,
            description=cleaned_description,
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

    # ui-attractive-polish-m5 (UPL-12 v1): content-negotiation.
    # Starlette normalizes header names to lowercase, so "hx-request"
    # is the canonical key (matches the m4 add_paper precedent).
    # The HTML fragment omits ``lancedb_path`` (host-path leak per
    # 06-mcp-server-design.md); the JSON branch preserves it for
    # scripted callers.
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            status_code=status.HTTP_201_CREATED,
            content=_notebook_row_html(
                slug=body.slug,
                display_name=body.display_name,
                notebook_kind=body.notebook_kind,
                created_at=created_at,
            ),
        )
    return {
        "slug": body.slug,
        "display_name": body.display_name,
        "lancedb_path": lancedb_path,
        "notebook_kind": body.notebook_kind,
        "discovery_category": body.discovery_category,
        "description": cleaned_description,
    }


@router.delete(
    "/notebooks/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    # ui-attractive-polish-m5 (UPL-12 v1): union return (Response |
    # None) — Response for the HX-Request branch (200 empty body so
    # htmx applies hx-swap="outerHTML" — htmx 2.0.10 explicitly skips
    # the swap on 204), None for the existing 204 default path.
    response_model=None,
)
async def delete_notebook(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> Response | None:
    """Drop the notebook's metadata + cascade to ``notebook_papers``.

    Metadata-only — does NOT touch on-disk
    ``var/arxmcp/notebooks/<slug>/`` assets. The on-disk wipe is the
    explicit job of ``tools/notebook_purge.py``.

    404 if the slug doesn't exist (no row to delete).

    ui-attractive-polish-m5 (UPL-12 v1): content-negotiation on the
    ``HX-Request: true`` header. The vendored htmx 2.0.10 explicitly
    sets ``{code:"204",swap:false}`` in its responseHandling config,
    so a 204 response would short-circuit the row-removal swap. The
    HX-Request branch returns 200 with an empty body so htmx's
    ``hx-swap="outerHTML"`` on the remove button (with
    ``hx-target="closest tr"``) actually removes the ``<tr>``. The
    non-htmx path keeps the historical 204 — verified harmless for
    existing JSON-direct tests (``test_notebook_api.py`` +
    ``test_notebook_rename_delete.py`` both call without HX-Request).
    Spike-2 pre-flight applies: ``validate_slug`` precedes the fork;
    the 404-on-missing check precedes the fork; the HX-Request
    header is a renderer hint NOT a trust boundary.
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
    # ui-attractive-polish-m5 (UPL-12 v1): HX-Request → 200 empty so
    # the htmx swap removes the row; non-htmx → 204 (default per
    # @router.delete decorator).
    if request.headers.get("hx-request") == "true":
        return Response(status_code=status.HTTP_200_OK, content=b"")
    # 204 No Content — explicit None return matches FastAPI's
    # convention for body-less responses.
    return None


#: notebook-surface-expansion-m2: strip C0 control chars + DEL from a display
#: name before storage. A display name is a SINGLE-LINE field — NUL, newlines,
#: tabs, and other control chars have no legitimate place and would (a) corrupt
#: the single-line render and (b) enable log-injection. Stripping only shrinks
#: the string, so the Pydantic ``max_length=256`` bound (validated on the raw
#: body) still holds afterwards. m2-rect F3: the C1 range 0x80-0x9f is
#: intentionally NOT stripped (valid Unicode codepoints, not HTML-control-
#: significant) — and note neither Jinja2 autoescape nor ``html.escape``
#: transforms C1 bytes; escaping only touches ``& < > " '``.
_CONTROL_CHARS_RE: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f]")


def _display_name_fragment(display_name: str) -> str:
    """Build the htmx-swap fragment for a renamed notebook's display name.

    The PATCH handler returns this in place of the ``#display-name-block``
    element (``hx-swap="outerHTML"``). Mirrors :func:`_paper_row_html` and
    ``server.routes.ui.ui_status_badge``: a tiny Python f-string fragment with
    EVERY interpolated value HTML-escaped via :func:`html.escape` — NOT a
    Jinja2 partial (m2 synthesis D1). An empty name renders as ``—`` (matching
    ``index.html``'s ``{{ nb.display_name or "—" }}``). Never wrap this in
    ``| safe``; the escape here IS the XSS guard for the fragment path.
    """
    # ui-attractive-polish-m1 (UPL-3): aria-live="polite" MUST be on the
    # outerHTML-swap fragment, not just the initial template render in
    # notebook_detail.html. htmx replaces the <p> entirely on rename success;
    # the new element must carry aria-live or screen readers stop announcing
    # rename-result changes after the first swap (research-synthesis.md §2).
    shown = html.escape(display_name) if display_name else "—"
    return (
        f'<p class="display-name" id="display-name-block" aria-live="polite">'
        f"{shown}</p>"
    )


@router.patch(
    "/notebooks/{slug}",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
)
async def rename_notebook(
    slug: str,
    body: NotebookRename,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse:
    """Rename a notebook's ``display_name`` (notebook-surface-expansion-m2).

    Returns the re-rendered ``#display-name-block`` HTML fragment for the
    detail page's htmx ``outerHTML`` swap. Security posture (synthesis D4):

    - ``validate_slug`` FIRST → 422 on a malformed/path-traversal slug
      (identical to :func:`delete_notebook`).
    - Over-long name → 422 via Pydantic ``Field(max_length=256)`` on
      ``NotebookRename`` (before this body runs).
    - Mass-assignment closed: ``NotebookRename`` carries only
      ``display_name``; the store update touches only that column.
    - Control chars stripped before storage (single-line field; log-injection
      defense).
    - XSS: the returned fragment html-escapes the value (NOT ``| safe``).
    - 404 if the slug is unknown (``update_display_name`` → ``False``).
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    cleaned = _CONTROL_CHARS_RE.sub("", body.display_name)
    updated = await store.update_display_name(slug, cleaned)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    return HTMLResponse(content=_display_name_fragment(cleaned))


def _topic_fragment(discovery_category: str, description: str) -> str:
    """Build the htmx-swap fragment for a notebook's topic metadata.

    The ``PATCH /ui/api/notebooks/{slug}/topic`` handler returns this in
    place of the ``#topic-block`` element (``hx-swap="outerHTML"``).
    Mirrors :func:`_display_name_fragment`: a tiny Python f-string with
    EVERY interpolated value HTML-escaped via :func:`html.escape` — NOT a
    Jinja2 partial. An empty value renders as ``—``. Never wrap this in
    ``| safe``; the escape here IS the XSS guard for the fragment path.
    ``aria-live="polite"`` is carried on the swapped element so screen
    readers announce the updated topic after the outerHTML swap (the swap
    REPLACES the element, so the attribute must live in the fragment too).
    """
    cat = html.escape(discovery_category) if discovery_category else "—"
    desc = html.escape(description) if description else "—"
    return (
        '<div class="topic-block" id="topic-block" aria-live="polite">'
        f'<p class="topic-category">Discovery category: <code>{cat}</code></p>'
        f'<p class="topic-description">{desc}</p>'
        "</div>"
    )


@router.patch(
    "/notebooks/{slug}/topic",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
)
async def update_notebook_topic(
    slug: str,
    body: NotebookTopicUpdate,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse:
    """Update a notebook's topic metadata (notebook-paper-discovery-m1).

    Returns the re-rendered ``#topic-block`` HTML fragment for the detail
    page's htmx ``outerHTML`` swap. Security posture mirrors
    :func:`rename_notebook`:

    - ``validate_slug`` FIRST → 422 on a malformed/path-traversal slug.
    - ``_validate_discovery_category`` → 422 on a non-empty non-member
      category (empty string accepted — FM-1).
    - Over-long fields → 422 via Pydantic ``max_length`` on
      ``NotebookTopicUpdate`` (before this body runs).
    - Mass-assignment closed: ``NotebookTopicUpdate`` carries only the two
      topic fields; the store update touches only those columns. The
      rename endpoint is untouched.
    - Control chars stripped from ``description`` before storage
      (log-injection defense, mirroring the rename path).
    - XSS: the returned fragment html-escapes both values (NOT ``| safe``).
    - 404 if the slug is unknown (``update_topic`` → ``False``).
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    try:
        _validate_discovery_category(body.discovery_category)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    cleaned_desc = _CONTROL_CHARS_RE.sub("", body.description)
    updated = await store.update_topic(
        slug, body.discovery_category, cleaned_desc
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    return HTMLResponse(
        content=_topic_fragment(body.discovery_category, cleaned_desc)
    )


# ---------------------------------------------------------------------------
# Discover (notebook-paper-discovery-m4)
# ---------------------------------------------------------------------------


def _safe_contact_email() -> str | None:
    """Best-effort contact email for the arXiv polite User-Agent.

    Reads the operator-settings ``contact_email`` when available; any failure
    (settings table absent, db missing) degrades to ``None`` —
    ``fetch_candidates`` accepts ``None``. Never raises into the request path.
    """
    try:
        return get_contact_email()
    except Exception:  # noqa: BLE001 — best-effort; discovery must not fail on this
        return None


def _discover_results_fragment(
    slug: str, candidates: list[DiscoveryCandidate],
) -> str:
    """Build the htmx-swap fragment listing discovered candidates.

    Returned by ``POST /ui/api/notebooks/{slug}/discover`` in place of
    ``#discover-results`` (``hx-swap="outerHTML"``). Mirrors
    :func:`_paper_row_html` / :func:`_topic_fragment`: a Python f-string with
    EVERY interpolated value HTML-escaped via :func:`html.escape` — NOT a Jinja2
    partial (autoescape does not cover f-strings). The candidate ``title`` and
    ``abstract_head`` come from the arXiv API (external, untrusted), so escaping
    IS the XSS guard (FM-A); never wrap any of this in ``| safe``.
    ``aria-live`` is re-emitted on the swapped element so screen readers announce
    the result. The candidate queue is EPHEMERAL — the panel says so.
    """
    safe_slug = html.escape(slug)
    if not candidates:
        body = '<p class="empty">No new candidates found for this topic.</p>'
    else:
        rows: list[str] = []
        for c in candidates:
            pid = html.escape(c.paper_id)
            # "Add" reuses the existing add-paper route (records the
            # notebook_papers junction row; LanceDB embedding is the separate
            # "Ingest now" step, exactly like URL-paste adding).
            rows.append(
                '<li class="discover-candidate">'
                # m10 rectify (critique M13): <h3>, not <p>+font-weight. The
                # title was a heading by styling only, so the hierarchy this
                # milestone built existed for sighted readers and nowhere in
                # the accessibility tree. <h3> is correct under the page's
                # <h2> section headings.
                f'<h3 class="discover-title">{html.escape(c.title) or "—"}</h3>'
                f'<p class="discover-meta"><code>{pid}</code> · '
                f'<time>{html.escape(c.submitted_date)}</time></p>'
                # m10 rectify (critique H2/H3/M2): the abstract was clamped
                # with max-height and NO way to see the rest — 40-85% of the
                # text unreachable on the console's only operator-judgment
                # surface, and a short abstract looked identical to a
                # truncated one. <details> is native, keyboard-operable and
                # needs no JS; the full text was already in the DOM, so this
                # adds a control rather than a payload.
                '<details class="discover-abstract">'
                f'<summary>{html.escape(c.abstract_head)}</summary>'
                f'<p>{html.escape(c.abstract_head)}</p>'
                "</details>"
                f'<form hx-post="/ui/api/notebooks/{safe_slug}/papers"'
                # m12 rectify (H1): the papers table now sits ABOVE this
                # disclosure, so a bare beforeend appended the new row
                # off-screen — success with no visible effect, which is
                # exactly AC#4's second clause. m12 fixed this for the two
                # TEMPLATE forms and missed the fragment builder, a file the
                # reorder never touched. Same show: string as those two.
                ' hx-target="#papers-tbody"'
                ' hx-swap="beforeend show:#papers-tbody:bottom"'
                ' hx-disabled-elt="find button">'
                '<input type="hidden" name="arxiv_url" '
                f'value="https://arxiv.org/abs/{pid}">'
                # m10 rectify (critique M14): .button-quiet, not the default
                # primary. BAN-9 ("multiple primary CTAs per viewport") is on
                # the must-be-removed list, and a results panel renders one
                # full-accent button PER ROW. The action stays equally
                # available; it stops being the loudest thing on the surface.
                '<button type="submit" class="button-quiet">Add</button>'
                "</form>"
                "</li>"
            )
        # m10 rectify (critique M8/M15/M17): disclose the ordering basis.
        # The arXiv Atom feed carries NO relevance score, and the driver pins
        # sortBy=submittedDate — but bibliography styling makes a list read as
        # relevance-ranked, so silence let an operator infer a ranking the
        # data does not support (CLAUDE.md 4.9). Saying "newest first" is the
        # honest disclosure the absent relevance line could not make.
        body = (
            f'<p class="hint">{len(candidates)} new candidate(s), newest first '
            "— arXiv does not rank by relevance. Results are not saved; "
            "click Discover to re-run.</p>"
            # role="list" is NOT redundant: list-style:none strips the list
            # role in WebKit/VoiceOver (critique M1/M12), so the count of
            # candidates stops being announced without it.
            f'<ul class="discover-list" role="list">{"".join(rows)}</ul>'
        )
    return (
        '<div id="discover-results" aria-live="polite" aria-atomic="true">'
        f"{body}</div>"
    )


@router.post(
    "/notebooks/{slug}/discover",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    response_model=None,
)
async def discover_papers(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse:
    """Discover new arXiv papers for a notebook's topic (notebook-paper-discovery-m4).

    Loopback-only operator-console action. Runs the m3 arXiv-Atom discovery
    driver (the async core) for the notebook's ``discovery_category`` +
    ``description``, deduplicates against ``notebook_papers``, and returns an
    htmx fragment of candidate rows with per-row "Add" buttons. PROPOSE-only:
    "Add" records the paper via the existing add-paper route; LanceDB embedding
    is the separate "Ingest now" action. The candidate queue is EPHEMERAL.

    Security posture (security-reviewer): ``validate_slug`` first (path-traversal
    defense); candidate ``title``/``abstract`` are html.escape'd in the fragment
    (XSS guard); arXiv failures and unconfigured notebooks return 4xx/502 (the
    panel's ``hx-on::htmx:response-error`` surfaces the detail) — never a 500.
    The route inherits ``SecFetchSite`` + ``OriginValidation`` on ``/ui/*``.
    NOTE: the synchronous arXiv fetch briefly blocks the event loop — accepted
    for the single-operator loopback console (``MAX_RESPONSE_BYTES`` caps the
    response).
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

    try:
        # m10 rectify (critique M17): pass max_results EXPLICITLY. The driver
        # default is 200 (tools/discover_for_notebook.py:69), and at ~150px
        # per styled candidate that is a ~30,000px unbroken ladder with the
        # only count scrolled off the top — and #discover-results carries
        # aria-live="polite" aria-atomic="true", so a screen reader announces
        # the whole region. m10's bibliography styling made the row taller,
        # which turned an already-large default into an unusable one.
        # 25 is an operator page. Explicit so a driver-side default change
        # cannot silently re-open a 200-row render.
        candidates = await discover_for_notebook_async(
            store, slug, contact_email=_safe_contact_email(), max_results=25,
        )
    except ValueError as e:
        # Notebook exists but has no discovery_category set (not configured).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except (RuntimeError, OSError) as e:
        # arXiv unreachable / error-entry / parse failure — never surface a 500.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"discovery failed: {e}",
        ) from e

    return HTMLResponse(content=_discover_results_fragment(slug, candidates))


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
    # m4: union return (HTMLResponse | dict) — FastAPI can't autogenerate
    # a Pydantic model from the union, and there's no value in trying.
    response_model=None,
)
async def add_paper(
    slug: str,
    body: PaperAdd,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse | dict[str, str]:
    """Normalize an arxiv URL to a paper_id and insert a junction row.

    AC #2: validates URL via :func:`_arxiv_url_to_paper_id` (host
    whitelist + path-prefix check + ``is_valid_paper_id`` regex).
    Returns 422 on a malformed URL; 404 if the notebook doesn't
    exist; 409 on duplicate ``(slug, paper_id)``.

    ui-attractive-polish-m4 (UPL-12 v0): content-negotiation on the
    ``HX-Request: true`` header. htmx clients get a ``<tr>`` fragment
    for ``hx-swap="beforeend"`` into ``#papers-tbody`` (no full-page
    reload); non-htmx clients (curl, scripts) still get the existing
    JSON dict body. The Spike-2 pre-flight checklist confirms this
    branch adds no novel attack surface beyond the m8 upload-handler
    precedent: validation runs BEFORE the response fork; the fragment
    uses ``_paper_row_html`` (which html.escape()s every interpolated
    value); the ``HX-Request`` header is a client hint NOT a trust
    boundary; ``SecFetchSiteMiddleware`` + ``CONTENT_SECURITY_POLICY_UI``
    + ``validate_slug`` + ``_arxiv_url_to_paper_id`` are all unchanged.
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

    # m4 UPL-12 v0: capture once for both the store insert + the fragment
    # response (mirrors the upload handler's pattern at the equivalent
    # call site). _now_iso() returns "YYYY-MM-DDTHH:MM:SS+00:00".
    added_at = _now_iso()
    try:
        await store.add_paper(
            slug=slug, paper_id=paper_id, added_at=added_at,
        )
    except sqlite3.IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"paper {paper_id!r} already in notebook {slug!r}"
            ),
        ) from e

    # m4 UPL-12 v0: content-negotiation. Starlette normalizes header
    # names to lowercase, so "hx-request" is the canonical key. The
    # has_preview=False arg renders the m10-rect-F6 disabled-look
    # placeholder (URL-paste writes no ar5iv HTML on disk).
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            status_code=status.HTTP_201_CREATED,
            content=_paper_row_html(
                slug=slug,
                paper_id=paper_id,
                added_at=added_at,
                has_preview=False,
            ),
        )
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
    if not is_valid_arxiv_paper_id(paper_id):
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
# ---------------------------------------------------------------------------
# onboarding-uplift-m3 — repair-registry + reconcile-marker + per-notebook
# health endpoints
# ---------------------------------------------------------------------------
#
# Heals the two drift bugs we hand-fixed earlier this session:
#
# 1. On-disk vs SQLite-registry split — older milestone work created
#    notebook dirs (var/arxmcp/notebooks/<slug>/) without registering them
#    in notebooks.db::notebooks. The UI shows zero notebooks while a
#    healthy corpus exists on disk. ``POST /ui/api/admin/repair-registry``
#    walks the dirs, registers any missing slug via the canonical
#    ``NotebooksStore.create_notebook`` path (m2 F1 lesson: never direct
#    SQLite INSERT to the ``notebooks`` table).
#
# 2. corpus-version.json marker drift — the pre-m1 ``write_chunks`` wrote
#    the marker per-batch instead of cumulative, leaving production
#    notebooks with massively-stale chunk_counts. ``POST /ui/api/notebooks/<slug>/reconcile-marker``
#    opens the per-notebook LanceDB at the marker's pinned version (MVCC
#    snapshot — concurrent-ingest-safe per m3 synthesis FM-1), recounts
#    rows + distinct paper_ids, and atomically rewrites the marker.
#
# Plus a per-notebook ``GET /ui/api/notebooks/<slug>/health`` drift
# report endpoint that surfaces marker-vs-reality skew for any single
# notebook (operator-triggered diagnostic; NOT a hot poll).


def _read_marker_safely(
    notebook_lance_path: Path,
) -> tuple[object | None, str | None]:
    """Read a per-notebook ``corpus-version.json`` marker without raising.

    Returns ``(info, None)`` on success, ``(None, "no_marker")`` when the
    file is absent, ``(None, "malformed")`` when the JSON is invalid.

    Used by ``repair_registry`` (which classifies each dir's outcome via
    this discriminator) and ``reconcile_marker`` (which 422s on
    ``no_marker``). The error path is structured rather than raised so
    the walk loop in ``repair_registry`` keeps going across the
    remaining dirs.
    """
    from server.corpus import read_corpus_version  # local

    try:
        info = read_corpus_version(notebook_lance_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "m3 marker read failed at %s: %s",
            notebook_lance_path,
            exc,
        )
        return None, "malformed"
    if info is None:
        return None, "no_marker"
    return info, None


def _recount_notebook_lancedb(
    notebook_lance_path: Path, *, version: int
) -> tuple[int, int]:
    """Open the per-notebook LanceDB at the pinned ``version`` (MVCC
    snapshot — m3 synthesis FM-1 / FM-2: concurrent-ingest-safe) and
    return ``(chunk_count, distinct_paper_count)``.

    Uses ``server.corpus.open_chunks_table(...)`` which calls
    ``tbl.checkout(version)`` in-place — confirmed snapshot-consistent
    by ``tests/test_mvcc.py::TestVersionPinning``. The handle is
    read-only after checkout; concurrent ``tbl.add()`` from an
    in-flight ingest produces a NEW version > N and cannot affect
    counts at version N.

    Distinct paper_id count uses PyArrow's ``pc.count_distinct``
    (m3 synthesis §3 D3 — preferred over pandas ``nunique`` for fewer
    allocations).
    """
    import pyarrow.compute as pc  # noqa: PLC0415

    from server.corpus import open_chunks_table  # local

    tbl = open_chunks_table(notebook_lance_path, version=version)
    chunk_count = tbl.count_rows()
    arrow_tbl = tbl.to_arrow()
    paper_count = int(pc.count_distinct(arrow_tbl["paper_id"]).as_py())
    return chunk_count, paper_count


def _write_marker_atomically(
    notebook_lance_path: Path, info: object
) -> None:
    """Rewrite ``corpus-version.json`` atomically — mirrors
    ``ingest/store.py::write_corpus_version_marker`` verbatim (m3
    synthesis §2 — load-bearing facts).

    POSIX-atomic ``os.replace`` requires the tmp file to be co-located
    with the target on the same filesystem (m3 synthesis FM-2 +
    cross-filesystem-tmp-trap memory entry). Tmp filename carries PID
    + uuid hex to prevent collision between concurrent rewriters.

    The JSON payload uses ``sort_keys=True`` + the minimal separator
    set so a re-run against an unchanged state produces a byte-identical
    file (m3 synthesis §3 D4 idempotency).
    """
    import uuid  # noqa: PLC0415

    out_path = notebook_lance_path / "corpus-version.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # ``info`` is a ``CorpusVersionInfo``; we use its alphabetical-key
    # ``to_dict`` to match the existing marker's byte-shape. The
    # serializer arguments mirror ``ingest/store.py::write_corpus_version_marker``
    # VERBATIM (sort_keys=True, ensure_ascii=False, default
    # separators, trailing "\n"). Diverging here would break the
    # byte-identical idempotency contract from m3 synthesis §3 D4
    # (a re-run would produce different bytes despite identical data).
    payload = (
        json.dumps(info.to_dict(), ensure_ascii=False, sort_keys=True)  # type: ignore[attr-defined]
        + "\n"
    )
    tmp = out_path.with_suffix(
        f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


class _RepairRegistryResult(BaseModel):
    """Response body for ``POST /ui/api/admin/repair-registry``.

    Four buckets correspond to the four per-dir outcomes the walker
    distinguishes — all are operator-actionable signals:
    - ``registered``: previously-orphan dir now in notebooks.db.
    - ``already_registered``: dir's slug was ALREADY in the registry
      (the IntegrityError-on-duplicate path; expected on re-runs).
    - ``skipped_no_marker``: dir exists but no
      ``lancedb/corpus-version.json`` — likely a scaffolded notebook
      where ``make ingest`` hasn't run yet.
    - ``skipped_malformed_marker``: marker file exists but JSON is
      invalid OR fails ``CorpusVersionInfo.from_dict`` field validation.
      Operator investigates manually.
    """

    registered: list[str]
    already_registered: list[str]
    skipped_no_marker: list[str]
    skipped_malformed_marker: list[str]


class _ReconcileResult(BaseModel):
    """Response body for ``POST /ui/api/notebooks/{slug}/reconcile-marker``.

    ``drift_resolved`` is ``after.chunk_count - before.chunk_count`` —
    positive when the marker under-counted (the typical pre-m1 case),
    negative if the marker over-counted, zero for an idempotent re-run.
    """

    slug: str
    before: dict[str, int]
    after: dict[str, int]
    drift_resolved: int


class _NotebookHealthResult(BaseModel):
    """Response body for ``GET /ui/api/notebooks/{slug}/health``.

    ``status`` is the operator-actionable summary:
    - ``ok``: marker + LanceDB agree.
    - ``drift``: marker disagrees with the LanceDB recount (run
      ``make reconcile NOTEBOOK=<slug>``).
    - ``no_marker``: ``make ingest`` hasn't run yet.
    - ``malformed_marker``: marker JSON is invalid; investigate.
    """

    slug: str
    status: str
    marker_chunk_count: int | None
    actual_chunk_count: int | None
    marker_paper_count: int | None
    actual_paper_count: int | None
    drift: int | None
    corpus_version: int | None
    detail: str | None


@router.post(
    "/admin/repair-registry",
    status_code=status.HTTP_200_OK,
    response_model=_RepairRegistryResult,
)
async def repair_registry(
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008
) -> _RepairRegistryResult:
    """Walk ``var/arxmcp/notebooks/`` and register any on-disk dirs
    with a valid ``corpus-version.json`` marker that are NOT already
    in ``notebooks.db::notebooks``.

    Per m3 synthesis §1 + §3 D2 — every registration goes through
    :meth:`NotebooksStore.create_notebook` (the canonical writer; m2
    F1 lesson). ``sqlite3.IntegrityError`` on duplicate slug is the
    expected ``already_registered`` path. The walk's per-dir
    ``_read_marker_safely`` catches malformed markers and continues
    (FM-7 mitigation).

    Loopback-only deployment is the auth boundary (m3 synthesis §2 +
    R1 §"Note on /admin/ prefix"); no additional middleware needed.
    """
    registered: list[str] = []
    already_registered: list[str] = []
    skipped_no_marker: list[str] = []
    skipped_malformed: list[str] = []

    existing_slugs = {row["slug"] for row in await store.list_notebooks()}

    if not NOTEBOOKS_BASE.is_dir():
        # No on-disk notebooks tree yet — nothing to walk.
        logger.info(
            "repair-registry: %s does not exist; nothing to walk",
            NOTEBOOKS_BASE,
        )
        return _RepairRegistryResult(
            registered=[],
            already_registered=[],
            skipped_no_marker=[],
            skipped_malformed_marker=[],
        )

    for child in sorted(NOTEBOOKS_BASE.iterdir()):
        if not child.is_dir() or child.is_symlink():
            continue
        slug = child.name
        # Validate the slug at the boundary — refuse to register names
        # that fail the regex (catches stray test dirs, hidden files,
        # etc.). NotebookError → skip.
        try:
            validate_slug(slug)
        except NotebookError:
            logger.debug(
                "repair-registry: skipping %s (invalid slug)", child
            )
            continue

        nb_lance = child / "lancedb"
        info, err = _read_marker_safely(nb_lance)
        if err == "no_marker":
            skipped_no_marker.append(slug)
            continue
        if err == "malformed":
            skipped_malformed.append(slug)
            continue

        if slug in existing_slugs:
            already_registered.append(slug)
            continue

        # New registration — route through NotebooksStore.create_notebook
        # (the canonical writer; raises IntegrityError on duplicate, which
        # we wouldn't hit because the existing_slugs check above already
        # filtered, but the catch is belt-and-braces against TOCTOU vs a
        # concurrent ``create_notebook`` call).
        try:
            await store.create_notebook(
                slug=slug,
                display_name="",
                lancedb_path=str(notebook_lancedb_path(slug)),
                created_at=_now_iso(),
            )
            registered.append(slug)
            logger.info(
                "repair-registry: registered slug=%s "
                "version=%d chunks=%d papers=%d",
                slug, info.version, info.chunk_count, info.paper_count,  # type: ignore[attr-defined]
            )
        except sqlite3.IntegrityError:
            # TOCTOU — a concurrent ``create_notebook`` won the race.
            already_registered.append(slug)

    logger.info(
        "repair-registry: registered=%d already=%d "
        "skipped_no_marker=%d skipped_malformed=%d",
        len(registered), len(already_registered),
        len(skipped_no_marker), len(skipped_malformed),
    )
    return _RepairRegistryResult(
        registered=registered,
        already_registered=already_registered,
        skipped_no_marker=skipped_no_marker,
        skipped_malformed_marker=skipped_malformed,
    )


@router.post(
    "/notebooks/{slug}/reconcile-marker",
    status_code=status.HTTP_200_OK,
    response_model=_ReconcileResult,
)
async def reconcile_marker(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008
) -> _ReconcileResult:
    """Recount a notebook's LanceDB at the marker's pinned version and
    atomically rewrite the marker JSON.

    Per m3 synthesis §1 + FM-1: the LanceDB is opened at the marker's
    ``version`` field — NEVER ``version=None``. MVCC checkout-at-version
    provides a snapshot-consistent recount even if a concurrent ingest
    is producing v+1. The marker rewrite uses the canonical
    ``ingest/store.py`` atomic pattern (tmp co-located + ``os.replace``).

    ``created_at`` is preserved from the existing marker so a repeated
    ``make reconcile`` is **byte-identical** (m3 synthesis §3 D4 / FM-10).

    Errors:
    - 404 if the notebook is not registered in ``notebooks.db``.
    - 422 if the marker is absent (notebook scaffolded but never
      ingested; "run make ingest first").
    - 422 if the marker is malformed JSON.
    """
    try:
        validate_slug(slug)
    except NotebookError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if await store.get_notebook(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not registered",
        )

    nb_lance = notebook_lancedb_path(slug)
    old_info, err = _read_marker_safely(nb_lance)
    if err == "no_marker":
        # m3 critique F1: do NOT leak the absolute install path. Match
        # the sibling notebook_health endpoint's redacted form (which
        # already references the slug instead of `nb_lance`). Aligns
        # with the project's `redact_paths` precedent at
        # server/ingest_tracker.py:81.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no corpus-version.json for {slug!r}; "
                   "run `make ingest` first",
        )
    if err == "malformed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"corpus-version.json for {slug!r} is malformed; "
                   "operator investigation required",
        )

    # MVCC-pinned recount.
    new_chunks, new_papers = _recount_notebook_lancedb(
        nb_lance, version=old_info.version  # type: ignore[attr-defined]
    )
    new_info = old_info.with_counts(  # type: ignore[attr-defined]
        chunk_count=new_chunks, paper_count=new_papers
    )
    _write_marker_atomically(nb_lance, new_info)

    drift_resolved = new_chunks - old_info.chunk_count  # type: ignore[attr-defined]
    logger.info(
        "reconcile-marker: slug=%s version=%d "
        "before_chunks=%d after_chunks=%d "
        "before_papers=%d after_papers=%d drift_resolved=%d",
        slug, old_info.version,  # type: ignore[attr-defined]
        old_info.chunk_count, new_chunks,  # type: ignore[attr-defined]
        old_info.paper_count, new_papers,  # type: ignore[attr-defined]
        drift_resolved,
    )
    return _ReconcileResult(
        slug=slug,
        before={
            "chunk_count": old_info.chunk_count,  # type: ignore[attr-defined]
            "paper_count": old_info.paper_count,  # type: ignore[attr-defined]
        },
        after={"chunk_count": new_chunks, "paper_count": new_papers},
        drift_resolved=drift_resolved,
    )


@router.get(
    "/notebooks/{slug}/health",
    response_model=_NotebookHealthResult,
)
async def notebook_health(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008
) -> _NotebookHealthResult:
    """Per-notebook drift report.

    Live recount (NOT cached) — per m3 synthesis §3 D1: the
    ``Resources.startup_chunk_count`` cache is the SHARED corpus count,
    not per-notebook. This endpoint is an operator-triggered
    diagnostic (NOT a 10s auto-poll; the SHARED ``/status`` endpoint is
    what the badge polls). Per-notebook startup caching is m6 scope.

    Status classification:
    - ``ok``: marker chunk_count + paper_count both match the LanceDB
      recount.
    - ``drift``: marker disagrees with recount in EITHER count.
    - ``no_marker``: ``corpus-version.json`` absent
      (notebook scaffolded but never ingested).
    - ``malformed_marker``: marker JSON invalid.
    """
    try:
        validate_slug(slug)
    except NotebookError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if await store.get_notebook(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not registered",
        )

    nb_lance = notebook_lancedb_path(slug)
    info, err = _read_marker_safely(nb_lance)
    if err == "no_marker":
        return _NotebookHealthResult(
            slug=slug,
            status="no_marker",
            marker_chunk_count=None,
            actual_chunk_count=None,
            marker_paper_count=None,
            actual_paper_count=None,
            drift=None,
            corpus_version=None,
            detail="no corpus-version.json; run `make ingest` first",
        )
    if err == "malformed":
        return _NotebookHealthResult(
            slug=slug,
            status="malformed_marker",
            marker_chunk_count=None,
            actual_chunk_count=None,
            marker_paper_count=None,
            actual_paper_count=None,
            drift=None,
            corpus_version=None,
            detail="corpus-version.json is malformed; investigate",
        )

    actual_chunks, actual_papers = _recount_notebook_lancedb(
        nb_lance, version=info.version  # type: ignore[attr-defined]
    )
    marker_chunks = info.chunk_count  # type: ignore[attr-defined]
    marker_papers = info.paper_count  # type: ignore[attr-defined]
    drift = actual_chunks - marker_chunks
    in_sync = drift == 0 and marker_papers == actual_papers
    return _NotebookHealthResult(
        slug=slug,
        status="ok" if in_sync else "drift",
        marker_chunk_count=marker_chunks,
        actual_chunk_count=actual_chunks,
        marker_paper_count=marker_papers,
        actual_paper_count=actual_papers,
        drift=drift,
        corpus_version=info.version,  # type: ignore[attr-defined]
        detail=None
        if in_sync
        else (
            f"marker says {marker_chunks} chunks / {marker_papers} papers; "
            f"LanceDB has {actual_chunks} chunks / {actual_papers} papers. "
            f"Run `make reconcile NOTEBOOK={slug}` to heal."
        ),
    )


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


# ---------------------------------------------------------------------------
# textbook-ingest-m4 — PDF upload pre-flight gate
# ---------------------------------------------------------------------------

#: Upload-cap envelope for arxiv-kind notebooks (HTML ar5iv files).
#: The middleware allows 200 MB through; the route handler rejects
#: 413 if the body exceeds this cap on an arxiv-kind notebook.
#: m4 D3 mechanism per .claude/notes/milestones/textbook-ingest-m4/
#: research-synthesis.md.
_ARXIV_UPLOAD_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB

#: Maximum PDF page count accepted at the upload boundary. Bourbaki
#: tops out around 500 pages; 5000 is a 10x safety margin against
#: page-count-exhaustion DoS (per `.claude/docs/security-pdf-sandbox.md`).
_PDF_MAX_PAGE_COUNT: int = 5000

#: Tail-window size for polyglot detection. ZIP central-directory
#: records (``PK\x05\x06`` EOCD) live at the END of valid ZIP files;
#: scanning the last 1 KB catches the canonical PDF+ZIP polyglot.
#: ZIP-CD-relocated-via-comment-padding bypasses this check — a
#: documented limitation backstopped by m5's MinerU sandbox.
_PDF_POLYGLOT_TAIL_BYTES: int = 1024

#: Polyglot-tail markers. ZIP EOCD signature (``PK\x05\x06``) catches
#: PDF+ZIP; the HTML closing tags catch PDF+HTML. Case-insensitive
#: matching done by lowercasing the tail bytes.
_POLYGLOT_TAIL_MARKERS: tuple[bytes, ...] = (
    b"PK\x05\x06",  # ZIP end-of-central-directory record
    b"</html>",     # HTML closing tag (lowercased)
    b"</body>",     # HTML body closer (defense-in-depth for partial-HTML polyglots)
)

#: Regex for the PDF page-count probe. Per ISO 32000-1:2008 §7.7.3.2,
#: the Page Tree root dictionary carries ``/Count <int>`` giving the
#: total page count. String-grep takes ``max()`` across all matches
#: (intermediate Page Tree nodes also carry ``/Count`` but the root
#: carries the largest value). Heuristic — not a full parser; a
#: malicious PDF can lie about ``/Count`` by declaring a small value
#: while embedding a large Page Tree. m5's MinerU sandbox + wall-
#: clock timeout bound the damage on misdetection.
#:
#: **Documented limitations (m4 rect F7):**
#:
#: 1. ``/Count <int>`` with an intervening PDF comment is missed.
#:    PDF syntax (ISO 32000-1:2008 §7.2.4) allows ``%comment\n``
#:    between any two tokens, so ``/Count % see footnote\n 10000``
#:    is valid PDF but the ``\s+`` here only matches whitespace,
#:    not ``%...\n``. An adversary can hide a large declared count
#:    behind a comment. Backstops: m5's wall-clock timeout on the
#:    MinerU subprocess bounds page-count-exhaustion DoS at parse
#:    time.
#: 2. ``/Counter`` and other ``/Count``-prefixed names are NOT
#:    false-positives: the ``\s+`` requires whitespace between the
#:    name and the integer, which prevents matches on
#:    ``/Counter 100``, ``/Count_100``, ``/Count100`` etc.
_PDF_COUNT_RE = re.compile(rb"/Count\s+(\d+)")


def _is_pdf_bytes(head: bytes) -> bool:
    """Return True if ``head`` looks like a PDF document.

    Per ISO 32000-1:2008 §7.5.2, every PDF file MUST start with the
    bytes ``%PDF-`` (case-sensitive, exactly 5 bytes). The version
    number (``1.7``, ``2.0``, etc.) follows the dash. This sniff is
    strictly spec-compliant — readers that tolerate the header at a
    non-zero offset are not spec-compliant.

    Used as the first (cheapest) gate in :func:`_run_pdf_preflight`.
    """
    return len(head) >= 5 and head[:5] == b"%PDF-"


def _pdf_polyglot_check(pdf_bytes: bytes) -> None:
    """Reject polyglot files (PDF+ZIP, PDF+HTML).

    Scans the last :data:`_PDF_POLYGLOT_TAIL_BYTES` of the body for
    any marker in :data:`_POLYGLOT_TAIL_MARKERS`. Raises
    :class:`HTTPException` with status 415 on detection.

    **Caller contract** (m4 rect F8): this function assumes its
    caller (currently :func:`_run_pdf_preflight`) has ALREADY run
    :func:`_is_pdf_bytes` and confirmed the magic-byte sniff
    passed. There is NO defensive re-check here — callers that
    invoke this helper directly without the magic-byte gate are
    misusing the API. If a future refactor adds a second caller,
    that caller must run the magic-byte sniff first.

    **Documented limitation:** an attacker can relocate the ZIP
    central directory outside the tail window by padding the EOCD
    comment field (up to 65535 bytes per spec). This check catches
    the canonical case but is defense-in-depth, not a complete
    polyglot eliminator. m5's MinerU sandbox is the backstop.
    """
    tail = pdf_bytes[-_PDF_POLYGLOT_TAIL_BYTES:].lower()
    for marker in _POLYGLOT_TAIL_MARKERS:
        if marker.lower() in tail:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"polyglot file detected (tail contains "
                    f"{marker!r})"
                ),
            )


def _pdf_declared_page_count(pdf_bytes: bytes) -> int:
    """Return the highest ``/Count`` integer in the PDF byte stream.

    Heuristic — searches for ``/Count <int>`` patterns and returns
    the maximum. A PDF with no ``/Count`` token returns 0 (caller
    treats that as "no page-count assertion"). Adversarial PDFs that
    declare ``/Count 0`` while embedding a huge Page Tree slip past
    this check; m5's MinerU wall-clock timeout is the runtime
    backstop.
    """
    matches = _PDF_COUNT_RE.findall(pdf_bytes)
    if not matches:
        return 0
    return max(int(m) for m in matches)


def _run_pdf_preflight(content: bytes) -> None:
    """Run all 5 PDF rejection vectors on ``content``.

    Order is fast-first per
    ``.claude/notes/milestones/textbook-ingest-m4/research-synthesis.md``
    D5:

    1. Magic-byte sniff (5-byte read) — :func:`_is_pdf_bytes`.
    2. Polyglot tail (last 1 KB scan) — :func:`_pdf_polyglot_check`.
    3. JavaScript / auto-action detection (full-body regex) —
       :func:`tools.security.pdfid.find_javascript`.
    4. Page-count probe (full-body regex) —
       :func:`_pdf_declared_page_count`.

    The size cap is enforced by the caller BEFORE this preflight (the
    middleware envelope + the per-notebook-kind handler check).

    Raises :class:`HTTPException` (status 415) on any rejection. The
    detail message names the specific vector + the relevant bytes /
    tokens so the operator can debug at the API boundary.
    """
    if not _is_pdf_bytes(content[:5]):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "uploaded file does not appear to be a PDF "
                "(first 5 bytes must be '%PDF-' per ISO 32000)"
            ),
        )
    _pdf_polyglot_check(content)
    dangerous_tokens = _pdf_find_javascript(content)
    if dangerous_tokens:
        # Deduplicate by occurrence — surface unique tokens to the
        # operator. The full list (with duplicates) lands in the log
        # via the route-level exception handler.
        unique_tokens = sorted(set(dangerous_tokens))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"PDF contains embedded active-content tokens "
                f"({unique_tokens}) — rejected per the textbook-"
                f"ingest pre-flight gate. See tools/security/"
                f"pdfid.py for the detection rules."
            ),
        )
    declared_pages = _pdf_declared_page_count(content)
    if declared_pages > _PDF_MAX_PAGE_COUNT:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"PDF declares {declared_pages} pages — exceeds "
                f"the {_PDF_MAX_PAGE_COUNT}-page cap per the "
                f"textbook-ingest pre-flight gate"
            ),
        )


@router.post(
    "/notebooks/{slug}/papers/upload",
    response_class=HTMLResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_paper(
    request: Request,
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

    # textbook-ingest-m4: fetch the notebook BEFORE validating
    # paper_id format because the validation rule depends on
    # notebook_kind (arxiv → is_valid_arxiv_paper_id; textbook →
    # is_valid_paper_id, which accepts the textbook:<slug> form).
    notebook = await store.get_notebook(slug)
    if notebook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    notebook_kind = notebook.get("notebook_kind", "arxiv")
    is_textbook = notebook_kind == "textbook"

    # Per-kind paper_id validation. arxiv notebooks reject anything
    # that's not an arXiv shape; textbook notebooks accept either
    # arXiv (e.g. an arXiv preprint cross-referenced in the
    # notebook) OR textbook:<slug> form via is_valid_paper_id.
    if is_textbook:
        if not is_valid_paper_id(paper_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"paper_id {paper_id!r} is not a valid arXiv id "
                    f"or textbook:<slug> form"
                ),
            )
    else:
        if not is_valid_arxiv_paper_id(paper_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"paper_id {paper_id!r} is not a valid arXiv id",
            )

    # Read the upload. For arxiv notebooks the body is capped at
    # _ARXIV_UPLOAD_MAX_BYTES (10 MB) by the handler-level check
    # below; for textbook notebooks the middleware envelope of 200 MB
    # is the upper bound. The middleware has already buffered the
    # bytes by the time we reach here (eager-read per the
    # RequestBodySizeLimitMiddleware F1 fix), so the handler-level
    # checks see the full body in memory.
    #
    # textbook-ingest-m4 rect F1: the per-kind cap fires AFTER the
    # full body is read — there is NO "non-PDF caught at 5 bytes"
    # short-circuit. A 200 MB body to an arxiv-kind notebook is
    # buffered fully before the 10 MB check below fires HTTP 413.
    # Acceptable under loopback-only deployment per CLAUDE.md; a
    # future networked deployment must move the per-kind cap into
    # the middleware. See `.claude/docs/security-pdf-sandbox.md` §
    # "Memory-pressure caveat" for the design tradeoff.
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

    # textbook-ingest-m4 D3: per-kind upload-cap enforcement. The
    # middleware envelope allows 200 MB through unconditionally for
    # the /ui/api/notebooks prefix; this handler-level check rejects
    # arxiv-kind uploads that exceed the 10 MB ar5iv cap.
    if not is_textbook and len(content) > _ARXIV_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"upload of {len(content)} bytes exceeds the "
                f"{_ARXIV_UPLOAD_MAX_BYTES}-byte cap for arxiv-kind "
                f"notebooks (textbook-kind notebooks accept up to "
                f"200 MB; raise this notebook's kind to 'textbook' "
                f"if you intend to upload PDFs)"
            ),
        )

    # Magic-byte + format dispatch per notebook_kind.
    if is_textbook:
        # textbook-ingest-m4: 5-vector PDF preflight gate. Order is
        # fast-first (magic-byte → polyglot tail → JS detection →
        # page-count) per the synthesis D5. Any rejection raises
        # HTTPException(415) with a vector-specific detail.
        _run_pdf_preflight(content)
    elif not _is_html_bytes(content[:_MAGIC_SNIFF_BYTES]):
        # arxiv-kind notebook: m8 FM-2 magic-byte sniff for HTML.
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
    # subdirectory (ar5iv/ for arxiv; pdfs/ for textbook) is created
    # on first upload (notebook_dir runs the m6 F3 symlink-rejection
    # check).
    try:
        nb_dir = notebook_dir(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    if is_textbook:
        upload_dir = nb_dir / "pdfs"
        ext = "pdf"
    else:
        upload_dir = nb_dir / "ar5iv"
        ext = "html"
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"could not create {ext} directory: {e}",
        ) from e

    # paper_id may contain a slash (old-style hep-th/0001234); turn
    # that into a flat filename with the slash replaced so the
    # on-disk path stays single-level. The flat form is unambiguous
    # because is_valid_arxiv_paper_id constrains the character set
    # to ``[a-z0-9./-]`` (no shell metachars, no colon).
    #
    # textbook-ingest-m1 rect F1 (HIGH): defense-in-depth — also
    # neutralize the colon byte, which arXiv shapes never contain
    # but the ``textbook:<slug>`` shape from m1 does. For textbook
    # paper_ids ``textbook:my-book`` becomes ``textbook_my-book.pdf``
    # on disk — both unambiguous and free of HFS+/APFS colon-
    # confusion-via-Finder vectors.
    flat_paper_id = paper_id.replace("/", "_").replace(":", "_")
    target_path = upload_dir / f"{flat_paper_id}.{ext}"
    tmp_path = upload_dir / f"{flat_paper_id}.{ext}.tmp"

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
        "uploaded %s: slug=%s paper_id=%s bytes=%d claimed_filename=%r",
        "pdf" if is_textbook else "ar5iv html",
        slug, paper_id, len(content), file.filename,
    )

    # textbook-ingest-m6: schedule the parse task for textbook uploads.
    # The notebook's parse_status was set to 'pending' at notebook
    # creation; transition to 'running' here, then dispatch the
    # MinerU → renderer pipeline via ParseTaskTracker.
    if is_textbook:
        parse_tracker = getattr(request.app.state, "parse_tracker", None)
        if parse_tracker is None:
            # The tracker is wired by the lifespan; absence means
            # the daemon is not fully booted. Refuse the parse
            # dispatch (file IS on disk; operator can retry).
            logger.warning(
                "parse_tracker absent — textbook PDF saved at %s but "
                "no parse scheduled. Lifespan startup may not have "
                "completed.",
                target_path,
            )
        elif parse_tracker.is_running(slug) or await store.has_running_parse(
            slug
        ):
            # A parse is already in flight for this notebook; refuse
            # to schedule a second one (m6 FM-3 — Semaphore(1) global
            # cap would queue but the per-notebook check rejects the
            # collision earlier with a clear signal).
            #
            # m6 F4: check BOTH the in-memory tracker (live tasks)
            # AND the DB ``has_running_parse`` fallback (cross-restart
            # + closes the TOCTOU window where two near-simultaneous
            # uploads both observe is_running==False before either
            # task is registered). Mirrors trigger_ingest's two-layer
            # collision check.
            logger.warning(
                "parse_tracker: slug=%s already parsing; new upload "
                "kept on disk but NOT scheduled. Operator must wait.",
                slug,
            )
        else:
            await store.update_parse_status(
                slug, store.PARSE_STATUS_RUNNING, parse_error="",
            )
            mineru_output_dir = nb_dir / "parsed" / flat_paper_id / "_mineru"
            mineru_output_dir.mkdir(parents=True, exist_ok=True)
            parsed_dir = nb_dir / "parsed"
            parse_tracker.start_parse(
                slug=slug,
                pdf_path=target_path,
                paper_id=paper_id,
                output_dir=mineru_output_dir,
                parsed_dir=parsed_dir,
                store=store,
            )
            logger.info(
                "parse scheduled: slug=%s paper_id=%s "
                "mineru_output=%s parsed_dir=%s",
                slug, paper_id, mineru_output_dir, parsed_dir,
            )

    return HTMLResponse(
        status_code=status.HTTP_201_CREATED,
        content=_paper_row_html(
            slug=slug, paper_id=paper_id, added_at=_now_iso(),
        ),
    )


def _paper_row_html(
    slug: str,
    paper_id: str,
    added_at: str,
    *,
    has_preview: bool = True,
) -> str:
    """Build an HTML ``<tr>`` fragment for the upload + URL-paste handlers'
    htmx-swap responses.

    Kept as a Python helper rather than a Jinja2 partial because the
    fragment is tiny and inlining keeps the handlers self-contained.
    All interpolated values are HTML-escaped via :func:`html.escape` —
    paper_id is regex-validated upstream and cannot contain HTML-
    significant characters today, but escaping is defensive (Spike-2
    pre-flight checklist item: server-fragment correctness).

    m10: the table has FOUR columns (Paper ID, Added, Preview, Actions)
    to match the rendered ``notebook_detail.html`` body. The ar5iv-HTML
    upload path writes a file readable by the preview route
    (``has_preview=True`` default — Preview cell is a live link); the
    m4 URL-paste branch writes NO file (``has_preview=False`` — Preview
    cell renders the m10-rect-F6 disabled-look ``<span class="hint">``
    so the operator sees the same affordance the next page-load gives
    them, not a broken 404 link).

    .. note::
       The textbook PDF upload path (``notebook_kind="textbook"``) also
       currently defaults to ``has_preview=True``, which renders a
       Preview link that 404s until the textbook parse pipeline
       completes. This is a pre-existing m8 behaviour (the m4 patch did
       not introduce it); the m4-rect critique flagged the docstring
       drift, not the behaviour itself. Tracked separately under the
       m9 parse-tracker work (out of m4 scope) — a future milestone
       should thread ``has_preview=False`` from the textbook-upload
       branch until parse completes.

    The Actions cell shows "added" (was "uploaded" pre-m4; renamed for
    neutrality across both paths). Neither path shows a Remove button
    on the immediate post-success row — the m8 pattern: immediately
    providing Remove after the action is UX confusion; the next
    page-load restores the standard Remove affordance via the rendered
    template.
    """
    if has_preview:
        preview_cell = (
            f'<td><a href="/ui/notebooks/{html.escape(slug)}/papers/'
            f'{html.escape(paper_id)}/preview" target="_blank" '
            f'rel="noopener">Preview</a></td>'
        )
    else:
        # m4 (UPL-12 v0): URL-paste writes no ar5iv HTML on disk. Mirror
        # the m10-rect-F6 "no preview" pattern from notebook_detail.html
        # (a disabled-look <span> with a tooltip pointing the operator
        # to the upload card) so the operator sees the same affordance
        # the next page-load gives them.
        preview_cell = (
            '<td><span class="hint" '
            'title="upload an ar5iv HTML to enable preview">'
            'Preview</span></td>'
        )
    # ui-uplift-m7 (AC#2): the paper id and the timestamp are wrapped in
    # <code> and <time>, matching notebook_detail.html:325-326 — the template
    # that renders THIS SAME TABLE on page load. They diverged: this builder
    # emitted bare <td>, so an htmx-appended row rendered in the sans voice
    # with proportional figures directly beside identical rows in mono with
    # tabular figures, until the operator reloaded. _notebook_row_html below
    # always got this right. Fragment and template must agree on the element
    # wrapper, not merely on the text — the CSS keys off the element.
    return (
        f'<tr data-slug="{html.escape(slug)}" '
        f'data-paper-id="{html.escape(paper_id)}">'
        f'<td><code>{html.escape(paper_id)}</code></td>'
        f'<td><time>{html.escape(added_at)}</time></td>'
        f'{preview_cell}'
        f'<td>added</td>'
        f"</tr>"
    )


def _notebook_row_html(
    *,
    slug: str,
    display_name: str | None,
    notebook_kind: str,
    created_at: str,
) -> str:
    """Build a single notebooks-index ``<tr>`` fragment.

    Used by ``create_notebook``'s HX-Request branch
    (ui-attractive-polish-m5 / UPL-12 v1). Mirrors the m4
    ``_paper_row_html`` precedent exactly:

    - Per-value ``html.escape()`` is load-bearing (Spike-2 pre-flight
      checklist: server-fragment correctness). The display_name field
      is operator-controlled; an XSS payload like
      ``<img src=x onerror=alert(1)>`` MUST escape to ``&lt;img ...``.
    - The Actions cell shows ONLY an ``Open`` link (NO Remove button
      on the immediate post-create row). Mirrors m4's "added" pattern:
      immediately providing Remove is UX confusion; the next page-load
      restores the standard Remove affordance via the rendered
      template.
    - ``lancedb_path`` is deliberately NOT interpolated (host-path
      leak per ``06-mcp-server-design.md`` note on lancedb_path
      info-leak). The JSON branch in ``create_notebook`` keeps
      returning it for scripted callers.
    - The 4-column schema matches the rendered ``index.html`` body:
      Slug / Display name / Created / Actions.

    Args:
        slug: the notebook slug, post-``validate_slug``.
        display_name: operator-supplied display name; may be ``None``
            or empty string. Rendered as "—" when falsy, mirroring
            the template's ``{{ nb.display_name or "—" }}``.
        notebook_kind: server-validated via Pydantic ``Pattern``
            constraint. Not currently rendered (the ``index.html``
            template doesn't show kind), but kept in the signature
            for future column additions.
        created_at: server-generated via ``_now_iso()`` — never raw
            request data.
    """
    # Mirror the template's `{{ nb.display_name or "—" }}` for empty
    # display_name (None or ""). Escape AFTER the falsy fallback.
    display_text = display_name if display_name else "—"
    # `notebook_kind` is accepted but not rendered today; accepting
    # it future-proofs the helper signature without changing the
    # rendered surface.
    _ = notebook_kind
    return (
        f'<tr data-slug="{html.escape(slug)}">'
        f'<td><code>{html.escape(slug)}</code></td>'
        f'<td>{html.escape(display_text)}</td>'
        f'<td><time>{html.escape(created_at)}</time></td>'
        f'<td><a href="/ui/notebooks/{html.escape(slug)}" '
        f'class="button">Open</a></td>'
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


@router.get("/notebooks/{slug}/parse-status")
async def parse_status(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, str]:
    """Return the textbook-parse status for ``slug`` (textbook-ingest-m6).

    Returns JSON (not htmx HTML) — operators and scripts can poll
    this endpoint directly. The five terminal states are:

    - ``skipped``  — arxiv-kind notebook; no parse pipeline applies.
    - ``pending``  — textbook notebook created but no PDF uploaded yet.
    - ``running``  — parse task is in flight (MinerU + LaTeXML).
    - ``complete`` — parse succeeded; ``parsed_html_path`` populated.
    - ``failed``   — parse failed; ``parse_error`` carries the
      HTML-escaped tail of the failure.

    Returns 404 if the slug is unknown; 422 if malformed.
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    notebook = await store.get_notebook(slug)
    if notebook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )

    return {
        "slug": slug,
        "notebook_kind": notebook["notebook_kind"],
        "parse_status": notebook["parse_status"],
        "parse_error": notebook["parse_error"],
        "parsed_html_path": notebook["parsed_html_path"],
    }


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
    # ui-attractive-polish-m1 (UPL-3): every fragment branch below MUST emit
    # aria-live="polite" AND aria-atomic="true" on the new
    # <div id="ingest-status">. The outerHTML swap REPLACES the element each
    # poll cycle; without aria-live on the replacement, screen readers stop
    # announcing ingest run-state transitions (running -> success/failed)
    # after the first swap. aria-atomic="true" is added in m1-rect F1 for
    # parity with the badge fragment in server/routes/ui.py — the
    # ingest-status content is a composite string ("Status: success ·
    # Finished … · Run #42") and atomic-true tells the AT to re-read the
    # whole region, not just the changed nodes. Otherwise AT behavior on a
    # whole-element-replaced node varies (some announce everything, some
    # nothing — the parity gap surfaces as a regression at first manual
    # VoiceOver test).
    safe_slug = html.escape(slug)
    if status == "none":
        return (
            f'<div id="ingest-status" data-status="none" '
            f'aria-live="polite" aria-atomic="true" '
            f'hx-get="/ui/api/notebooks/{safe_slug}/ingest/latest" '
            f'hx-trigger="every 2s" hx-target="#ingest-status" '
            f'hx-swap="outerHTML">'
            f"No ingest runs yet."
            f"</div>"
        )
    if status == "running":
        return (
            f'<div id="ingest-status" data-status="running" '
            f'aria-live="polite" aria-atomic="true" '
            f'hx-get="/ui/api/notebooks/{safe_slug}/ingest/latest" '
            f'hx-trigger="every 2s" hx-target="#ingest-status" '
            f'hx-swap="outerHTML">'
            f"Status: <code>running</code>"
            f" · Started <time>{html.escape(started_at or '')}</time>"
            f" · Run #<code>{run_id}</code>"
            f"</div>"
        )
    if status == "success":
        return (
            f'<div id="ingest-status" data-status="success" '
            f'aria-live="polite" aria-atomic="true">'
            f"Status: <code>success</code>"
            f" · Finished <time>{html.escape(finished_at or '')}</time>"
            f" · Run #<code>{run_id}</code>"
            f"</div>"
        )
    # status == "failed"
    safe_exit = html.escape(str(exit_code)) if exit_code is not None else "?"
    # stderr_tail is already html.escape'd by prepare_stderr_tail.
    # 2026q3-ui-uplift UPL-10 v0: use the house `pre.error` treatment
    # (app.css:137-148 — tinted --error-bg + --danger text) that every OTHER
    # error surface in the console already uses (create-error, rename-error,
    # topic-error, discover-error, paste-error, upload-error, ingest-error).
    # A failed corpus ingest is the highest-stakes error an operator reads
    # here and was the one alarm surface rendering as an unstyled <pre>.
    stderr_pre = (
        f'<pre class="error">{stderr_tail}</pre>' if stderr_tail else ""
    )
    # ui-uplift-m7 (AC#2): the state token, the timestamps, the run id and
    # the exit code are identifiers — the operator reads them to correlate a
    # run against a log — so they take the mono voice via <code>/<time> like
    # every other identifier surface. The "Status:"/"Run #"/"Exit" prose
    # around them stays in the sans voice, which is the two-voice split.
    return (
        f'<div id="ingest-status" data-status="failed" '
        f'aria-live="polite" aria-atomic="true">'
        f"Status: <code>failed</code>"
        f" · Exit <code>{safe_exit}</code>"
        f" · Run #<code>{run_id}</code>"
        f"{stderr_pre}"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# notebook-surface-expansion-m6 — portable export bundle (tar + manifest)
# ---------------------------------------------------------------------------

#: Bundle format version (bump on any breaking manifest-shape change).
#: m7 (restore) reads this from the manifest before extracting.
_EXPORT_MANIFEST_FORMAT_VERSION: int = 1

#: ALLOWLIST of notebook-row fields embedded in the manifest (m6 synthesis D3,
#: mirrors m4 D3/F4). Omits ``lancedb_path`` + ``parsed_html_path`` (absolute
#: host paths = info-leak class) AND ``parse_error`` (HTML-escaped stderr;
#: not useful for backup/move and may carry parser path fragments). m7 derives
#: the path fields from ``notebook_dir(slug)`` in the target base.
_EXPORT_NOTEBOOK_ALLOWLIST: tuple[str, ...] = (
    "slug", "display_name", "notebook_kind", "created_at", "parse_status",
)

#: USTAR ``name`` field is **100 chars** (not POSIX ``NAME_MAX`` = 255 — that's
#: the FILESYSTEM cap which is what produced the file in the first place). USTAR
#: optionally splits a long path at a slash into a 155-char ``prefix`` + 100-char
#: ``name`` (Python ``tarfile._posix_split_name``), but a single-segment filename
#: with no slash cannot be split — ``tar.addfile`` would raise
#: ``ValueError: name is too long`` → unhandled 500. m6-rect F1: gate at 100 so
#: the preflight skips (and WARNs) the file rather than crashing the export.
#: PAX/GNU long-name extensions would lift this cap but drift mtime in extended
#: headers — incompatible with the m6 byte-determinism AC. The discipline is
#: "partial bundle is better than 500-ing" (synthesis D5).
_EXPORT_USTAR_NAME_MAX: int = 100


def _build_export_manifest(
    notebook: dict, papers: list[dict], slug: str
) -> bytes:
    """Build the deterministic manifest.json bytes (m6 D3).

    Allowlists the notebook fields, sorts ``papers`` by ``paper_id`` (stable
    across exports independent of ``list_papers``' ``added_at DESC`` order),
    and serializes with ``sort_keys=True`` + canonical JSON separators so the
    bytes are byte-identical across two exports of the same notebook.
    """
    # m6-rect F5: dict.get(key, "") fires the default only on ABSENT keys, not
    # on a key whose value IS None — and ``get_notebook`` returns ``parse_status:
    # None`` for arxiv notebooks NULL'd before textbook-ingest-m6. Coerce
    # None → "" so the manifest schema is "string, possibly empty", never null.
    nb_dict = {
        k: ("" if notebook.get(k) is None else notebook.get(k))
        for k in _EXPORT_NOTEBOOK_ALLOWLIST
    }
    nb_dict["slug"] = slug  # route slug is authoritative
    papers_sorted = sorted(
        ({"paper_id": p["paper_id"], "added_at": p["added_at"]} for p in papers),
        key=lambda r: r["paper_id"],
    )
    manifest = {
        "format_version": _EXPORT_MANIFEST_FORMAT_VERSION,
        "notebook": nb_dict,
        "papers": papers_sorted,
        "slug": slug,
    }
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _iter_safe_export_members(
    nb_dir: os.PathLike[str], slug: str
):
    """Yield ``(member_name, data_bytes)`` for every safely-exportable file
    under ``nb_dir`` (m6 D5 preflight).

    Skip + WARN (do NOT abort) for: symlinks (don't embed as SYMTYPE), non-files
    (dirs/devices/FIFOs), paths whose resolved location escapes ``nb_dir``,
    member names exceeding USTAR's 255-byte field or carrying control chars.
    Sorted by slug-relative member name for byte-deterministic order.
    """
    from pathlib import Path  # noqa: PLC0415

    nb_path = Path(nb_dir)
    nb_resolved = nb_path.resolve()
    for path in sorted(
        nb_path.rglob("*"), key=lambda p: str(p.relative_to(nb_path))
    ):
        rel = path.relative_to(nb_path)
        if path.is_symlink():
            logger.warning(
                "notebook %r export: skipping symlink member %r (m6 D5)",
                slug, str(rel),
            )
            continue
        if not path.is_file():  # dirs, devices, FIFOs
            continue
        try:
            resolved = path.resolve(strict=False)
        except OSError:
            logger.warning(
                "notebook %r export: skipping unresolvable path %r (m6 D5)",
                slug, str(rel),
            )
            continue
        if not resolved.is_relative_to(nb_resolved):
            logger.warning(
                "notebook %r export: skipping path escaping notebook_dir "
                "(possible symlink tamper; m6 D5)",
                slug,
            )
            continue
        member_name = f"{slug}/{rel.as_posix()}"
        if (
            len(member_name.encode("utf-8")) > _EXPORT_USTAR_NAME_MAX
            or any(ord(c) < 0x20 for c in member_name)
        ):
            logger.warning(
                "notebook %r export: skipping member name over USTAR limit "
                "or containing control chars (m6 D5)",
                slug,
            )
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning(
                "notebook %r export: skipping unreadable file %r (%s; m6 D5)",
                slug, str(rel), exc,
            )
            continue
        yield member_name, data


def _make_deterministic_tarinfo(name: str, size: int) -> tarfile.TarInfo:
    """A TarInfo with EVERY drift-prone field normalized (m6 D2).

    USTAR + manual construction (NOT ``gettarinfo``) zeroes ``mtime/uid/gid``,
    blanks ``uname/gname``, pins ``mode = 0o644`` + ``type = REGTYPE`` — so
    two exports of the same notebook produce byte-identical tar streams.
    """
    ti = tarfile.TarInfo(name=name)
    ti.size = size
    ti.mtime = 0
    ti.uid = 0
    ti.gid = 0
    ti.uname = ""
    ti.gname = ""
    ti.mode = 0o644
    ti.type = tarfile.REGTYPE
    return ti


@router.get(
    "/notebooks/{slug}/export",
    responses={
        200: {"content": {"application/x-tar": {}}},
        404: {"description": "notebook not found"},
        422: {"description": "malformed slug"},
    },
)
async def export_notebook(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> Response:
    """Stream a portable, deterministic tar of ONE notebook (m6).

    Bundle layout:
    - ``manifest.json`` at the bundle root — `format_version`, allowlisted
      `notebook` row, sorted `papers` rows for THIS slug only.
    - ``<slug>/<rel>`` members — the notebook's on-disk assets under
      ``var/arxmcp/notebooks/<slug>/`` (PDFs / ar5iv HTML / per-notebook
      LanceDB), filtered by the m6 D5 safe-member preflight.

    Security: ``validate_slug`` first (path-traversal guard); ``notebook_dir``
    containment (refuses a symlinked ``<slug>`` dir); per-member preflight
    drops symlinks / containment escapes / over-long names. Determinism:
    USTAR + manual ``TarInfo`` normalization + sorted member order — two
    exports of the same notebook are byte-identical (the load-bearing AC).
    Response cap: the export path is exempted in
    ``server.main._is_exempt_path`` (m6 synthesis D1; narrow suffix-only).
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    notebook = await store.get_notebook(slug)
    if notebook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    papers = await store.list_papers(slug)
    try:
        nb_dir = notebook_dir(slug)
    except NotebookError as e:
        # Slug-level symlink / containment failure (m6 F3 / m6 D5). Same
        # 422 the existing handlers raise for path-traversal errors.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    manifest_bytes = _build_export_manifest(notebook, papers, slug)

    buf = io.BytesIO()
    with tarfile.open(
        fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT
    ) as tar:
        # 1) manifest.json at the bundle root (top-level; m7 reads this
        #    before extracting the rest).
        tar.addfile(
            _make_deterministic_tarinfo("manifest.json", len(manifest_bytes)),
            io.BytesIO(manifest_bytes),
        )
        # 2) Asset files under ``<slug>/<rel>``. If the on-disk dir doesn't
        #    exist yet (notebook created but never uploaded to), the export
        #    is just the manifest — still a valid bundle.
        if nb_dir.is_dir():
            for member_name, data in _iter_safe_export_members(nb_dir, slug):
                tar.addfile(
                    _make_deterministic_tarinfo(member_name, len(data)),
                    io.BytesIO(data),
                )

    content = buf.getvalue()
    return Response(
        content=content,
        media_type="application/x-tar",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}.tar"',
            "Content-Length": str(len(content)),
        },
    )


__all__ = [
    "NotebookCreate",
    "PaperAdd",
    "get_notebooks_store",
    "router",
    "upload_paper",
]

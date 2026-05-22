"""HTML page routes for the notebook UI under ``/ui/`` (m8).

Companion to :mod:`server.routes.notebooks` — that file is the JSON
REST surface (`/ui/api/*` from m7) plus the htmx-fragment upload
endpoint (m8). This file is the Jinja2-rendered HTML pages
operators visit in the browser:

- ``GET /ui/`` — landing page; lists notebooks; create-notebook form;
  per-notebook "open" link.
- ``GET /ui/notebooks/{slug}`` — per-notebook detail page; paper list;
  URL-paste form; drag-drop upload card.

Both pages serve as the htmx shell — mutations POST to the m7 JSON
routes (which return JSON), then trigger a full-page reload via
``hx-on::htmx:afterRequest`` for simplicity. The new m8 upload
endpoint at ``/ui/api/notebooks/{slug}/papers/upload`` is the one
exception: it returns an HTML fragment so htmx can append to the
papers table without a reload.

Templates live at ``frontend/templates/`` (referenced via the
``server.routes.ui.templates`` global). Static assets (vendored
htmx, minimal CSS) live at ``frontend/static/`` and are mounted
at ``/ui/static/`` in :func:`server.main.create_app`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ingest.identifiers import is_valid_paper_id
from server.middleware import CONTENT_SECURITY_POLICY_PREVIEW
from server.routes.notebooks import get_notebooks_store
from tools._notebook_common import (
    CORPUS_PARSED_DIR,
    NotebookError,
    notebook_dir,
    validate_slug,
)

if TYPE_CHECKING:
    from server.notebooks_store import NotebooksStore

logger = logging.getLogger(__name__)

#: Repo-root-relative templates dir. Resolved once at import.
_TEMPLATES_DIR: Path = Path(__file__).resolve().parents[2] / "frontend" / "templates"

#: Jinja2Templates instance with an EXPLICITLY constructed environment.
#: Starlette's default ``Jinja2Templates(directory=...)`` constructs
#: a ``jinja2.Environment`` with ``autoescape=select_autoescape()``
#: under the hood — same protection for ``.html``/``.htm``/``.xml``
#: extensions — but the brief's "explicit > implicit" discipline
#: (m8 synthesis) calls for naming autoescape in this file so a
#: future template-loader change can't silently regress it.
_env: jinja2.Environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(
        enabled_extensions=("html", "htm", "xml"),
        default_for_string=True,
    ),
)
templates: Jinja2Templates = Jinja2Templates(env=_env)

router = APIRouter(tags=["ui"])


def _preview_html_path(slug: str, paper_id: str) -> Path | None:
    """Return the on-disk path to a paper's preview HTML, or ``None``.

    Search order (m10 research synthesis A1):

    1. **Notebook-scoped** (m8 upload site) —
       ``var/arxmcp/notebooks/<slug>/ar5iv/<flat_paper_id>.html``
       where ``flat_paper_id = paper_id.replace("/", "_")``. This is
       the primary location for per-notebook curated previews.

    2. **Corpus-global fallback** (ingest pipeline site) —
       ``var/arxmcp/corpus/parsed/<paper_id>/index.html``. Papers
       fetched via ``tools/notebook_fetch.py`` or the bulk ingest
       driver land here; the preview falls through to this location
       so seed-corpus papers that haven't been re-uploaded through
       m8 are still previewable.

    Both paths route through the same validators in the caller
    (:func:`validate_slug` + :func:`is_valid_paper_id`) and inherit
    the m6 symlink-rejection check via :func:`notebook_dir`. The
    function returns ``None`` rather than raising when neither path
    exists — the caller decides whether to 404 (preview route) or
    render a "no preview available" tooltip (browse table).

    Performance: two stat() calls in the negative path; one in the
    positive path. Loopback-only deployment makes this cheap (~µs).
    """
    # Notebook-scoped (primary). notebook_dir() runs the m6 F3
    # symlink-rejection check; bubble NotebookError as None so the
    # browse-table render path treats it the same as a missing file.
    try:
        nb_dir = notebook_dir(slug)
    except NotebookError:
        return None
    flat_paper_id = paper_id.replace("/", "_")
    nb_html = nb_dir / "ar5iv" / f"{flat_paper_id}.html"
    if nb_html.is_file():
        return nb_html
    # Corpus-global (fallback). The corpus path uses paper_id directly
    # as a subdirectory name; old-style IDs like ``hep-th/0001234``
    # produce nested subdirs naturally.
    corpus_html = CORPUS_PARSED_DIR / paper_id / "index.html"
    if corpus_html.is_file():
        return corpus_html
    return None


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def ui_index(
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse:
    """Landing page — list notebooks + create-notebook form (AC #1)."""
    notebooks = await store.list_notebooks()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"notebooks": notebooks},
    )


@router.get(
    "/notebooks/{slug}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def ui_notebook_detail(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse:
    """Per-notebook detail page — paper list + paste form + upload
    card (the "open" link from the landing page).

    404 if the slug doesn't exist; 422 on a malformed slug.
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
    # m10 AC #2 — annotate each paper row with on-disk preview existence
    # so the template can conditionally render the Preview link vs a
    # "no preview available" tooltip. Two filesystem stats per paper
    # (notebook-scoped + corpus-global); loopback-only deployment makes
    # this cheap. ``store.list_papers`` returns ``list[dict[str, str]]``;
    # we widen the value type to include the new bool but the template
    # only reads it via ``p.has_preview`` style access so the existing
    # ``paper_id`` / ``added_at`` keys are untouched.
    annotated_papers: list[dict[str, object]] = []
    for row in papers:
        paper_id = row.get("paper_id", "")
        has_preview = (
            isinstance(paper_id, str)
            and is_valid_paper_id(paper_id)
            and _preview_html_path(slug, paper_id) is not None
        )
        annotated_papers.append({**row, "has_preview": has_preview})
    return templates.TemplateResponse(
        request=request,
        name="notebook_detail.html",
        context={"notebook": notebook, "papers": annotated_papers},
    )


@router.get(
    "/notebooks/{slug}/papers/{paper_id:path}/preview",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def ui_paper_preview(
    slug: str,
    paper_id: str,
    request: Request,  # noqa: ARG001  (FastAPI route-injection signature)
) -> Response:
    """Serve a paper's stored ar5iv HTML with a TIGHT per-response CSP.

    The route is the m10 "Preview" affordance — clicking a Preview
    link in the browse table opens this URL in a new tab. The served
    HTML is the verbatim ar5iv output from arXiv (untrusted content),
    so the response carries an aggressively-restrictive
    :data:`server.middleware.CONTENT_SECURITY_POLICY_PREVIEW` header
    that blocks scripts, ``<base href>`` hijack, form-action
    exfiltration, and clickjacking of the preview page.

    Validation chain (m10 synthesis A5; triple defense):

    1. :func:`validate_slug` — m6 regex guard.
    2. :func:`is_valid_paper_id` — ``\\Z``-anchored arXiv-ID regex
       (m1-rect-F3 hardening); MUST fire BEFORE any ``Path(...)``
       construction or ``.replace("/", "_")`` substitution.
    3. :func:`notebook_dir` (called inside :func:`_preview_html_path`)
       — m6 symlink-rejection path-containment.
    4. Belt-and-braces: the resolved ``html_path`` is verified to lie
       under the resolved corpus / notebook base before bytes are read.

    Returns 404 with a GENERIC body when the HTML is absent (don't
    leak filesystem paths to a prober). Returns 422 on validation
    failures.

    The CSP override mechanism (m10 synthesis A4): this handler sets
    the ``Content-Security-Policy`` header explicitly on the response.
    :class:`SecurityHeadersMiddleware` checks
    ``b"content-security-policy" not in existing`` and skips injection
    when the handler already supplied a value — so our tight CSP wins
    over the broader m8 ``/ui/*`` CSP without any middleware change.

    Math-rendering trade-off (m10 synthesis A6): ar5iv uses MathJax 3
    which requires ``script-src 'self' 'unsafe-eval'``. With
    ``script-src 'none'`` math displays as raw LaTeX markup. Accepted
    for v2 m10; server-side KaTeX pre-render is a future enhancement.
    """
    # 1. Slug validation. NotebookError -> 422.
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    # 2. Paper-ID validation. is_valid_paper_id uses \Z anchor and the
    # regex constrains to arXiv ID format only — no ``..``, no shell
    # metachars, no path separators outside the old-style ``subject/N``
    # form. This MUST run before any Path construction below.
    if not is_valid_paper_id(paper_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid paper_id {paper_id!r}",
        )
    # 3 + 4. Locate the HTML on disk via the shared helper (handles
    # notebook-first + corpus-fallback search order). Belt-and-braces
    # containment check: both branches of _preview_html_path return
    # paths constructed under known prefixes (notebook_dir result or
    # CORPUS_PARSED_DIR), but we still verify the RESOLVED path lies
    # under one of them to defeat a hypothetical symlink-inside-a-
    # notebook attack that slipped past the m6 directory-level check.
    html_path = _preview_html_path(slug, paper_id)
    if html_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no preview available",
        )
    resolved = html_path.resolve()
    # Allowed prefixes: notebook-scoped ar5iv dir OR corpus-parsed root.
    # notebook_dir(slug) is safe to call again — validate_slug already
    # passed and the m6 symlink check is idempotent. Both prefixes are
    # resolved so symlinked corpus volumes are handled correctly.
    try:
        nb_ar5iv = (notebook_dir(slug) / "ar5iv").resolve()
    except NotebookError as e:
        # Should not happen post-validate_slug, but treat defensively.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    corpus_root = CORPUS_PARSED_DIR.resolve()
    if not (
        str(resolved).startswith(str(nb_ar5iv) + "/")
        or str(resolved).startswith(str(corpus_root) + "/")
        or resolved in (nb_ar5iv, corpus_root)
    ):
        # Generic 404 — never leak the resolved path or which prefix
        # check failed.
        logger.warning(
            "preview path-containment rejected for slug=%r paper_id=%r",
            slug,
            paper_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no preview available",
        )
    try:
        content_bytes = resolved.read_bytes()
    except OSError:
        # File vanished between the is_file() check and the read.
        # Race window is tiny on loopback; generic 404 keeps the
        # response shape stable.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no preview available",
        ) from None
    return Response(
        content=content_bytes,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": CONTENT_SECURITY_POLICY_PREVIEW.decode(
                "ascii"
            ),
        },
    )


__all__ = ["router", "templates"]

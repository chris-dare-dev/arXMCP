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
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from server.routes.notebooks import get_notebooks_store
from tools._notebook_common import NotebookError, validate_slug

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
    return templates.TemplateResponse(
        request=request,
        name="notebook_detail.html",
        context={"notebook": notebook, "papers": papers},
    )


__all__ = ["router", "templates"]

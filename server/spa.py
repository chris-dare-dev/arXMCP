"""Static SPA mount — serves ``frontend-app/dist`` at ``/app`` (WS-B M0).

Stage-2 D1 ADR: Node/Vite is a *build-time-only* toolchain. The built
``dist/`` tree is committed, so this mount needs nothing but the files
on disk — the runtime stays a single Python process with zero network
fetches (constitution invariants preserved).

Security posture:

- The ``/app`` surface receives ``CONTENT_SECURITY_POLICY_APP`` from
  :class:`server.middleware.SecurityHeadersMiddleware` — STRICTER than
  the ``/ui/`` console CSP: ``script-src 'self'`` with **no**
  ``unsafe-inline`` (the Vite build emits no inline scripts; the
  design-gate E2E suite asserts the app works under it).
- :class:`SPAFiles` inherits Starlette's built-in path-traversal
  protection (``os.path.commonpath`` check after ``realpath``
  resolution in ``starlette/staticfiles.py``).
- The history-API fallback serves ``index.html`` ONLY for extensionless
  paths (client-route navigations like ``/app/specimen``); asset paths
  with an extension 404 honestly rather than masquerading as HTML.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger(__name__)

#: Repo-root-relative location of the committed Vite build output.
FRONTEND_APP_DIST = Path(__file__).resolve().parent.parent / "frontend-app" / "dist"


class SPAFiles(StaticFiles):
    """``StaticFiles`` with a history-API fallback to ``index.html``.

    Client-side routes (``/app/specimen``) have no file on disk; a
    browser reload on one must receive ``index.html`` so the router
    can resolve the path. Requests whose final segment carries a file
    extension are real asset lookups and keep their 404.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and self._is_route_path(path):
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and self._is_route_path(path):
            return await super().get_response("index.html", scope)
        return response

    @staticmethod
    def _is_route_path(path: str) -> bool:
        last = path.rsplit("/", 1)[-1]
        return "." not in last


def mount_frontend_app(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """Mount the SPA at ``/app`` if the build output exists.

    Returns True when mounted. A missing ``dist/`` (fresh clone before
    the committed build landed, or an operator experiment) logs a
    WARNING and leaves the server fully functional — the ``/ui/``
    console is the frozen zero-JS fallback, so SPA absence must never
    block startup.
    """
    directory = dist_dir if dist_dir is not None else FRONTEND_APP_DIST
    index_html = directory / "index.html"
    if not index_html.is_file():
        logger.warning(
            "frontend-app dist not found at %s - /app not mounted "
            "(build with: cd frontend-app && npm ci && npm run build)",
            directory,
        )
        return False
    app.mount("/app", SPAFiles(directory=str(directory), html=True), name="frontend-app")
    return True

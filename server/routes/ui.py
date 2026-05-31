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
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ingest.identifiers import is_valid_arxiv_paper_id
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

#: F1 closure (m10 adversary critique): CSP3 has no directive that
#: blocks ``<meta http-equiv="refresh" content="0;url=...">``. The
#: proposed ``navigate-to`` directive never made it to CSP3 baseline.
#: With the direct-serve route shape chosen in m10 synthesis D1, an
#: untrusted ar5iv HTML containing a meta-refresh tag would navigate
#: the new tab to an attacker origin on load — bypassing the entire
#: CSP. The rejected Option A's ``<iframe sandbox="allow-same-origin">``
#: would have blocked this via HTML5 §16.2 ("the sandboxing flag set"
#: blocks ``<meta refresh>``); the direct-serve route has no
#: equivalent.
#:
#: Mitigation: strip the tag from served bytes before constructing
#: the response. Cheap (one regex) and complete (the browser cannot
#: act on a tag that isn't in the body). The regex matches the
#: HTML5 attribute-order-agnostic form — ``http-equiv="refresh"``
#: may appear anywhere inside the ``<meta>`` tag, with or without
#: quotes, in any case.
_META_REFRESH_RE: re.Pattern[bytes] = re.compile(
    rb"<\s*meta[^>]+http-equiv\s*=\s*['\"]?refresh['\"]?[^>]*>",
    re.IGNORECASE,
)

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

#: notebook-surface-expansion-m1 — map a notebook's ``parse_status`` enum
#: (server/notebooks_store.py: skipped/pending/running/complete/failed) to the
#: shared ``.status-badge--{ok,warn,down}`` CSS classes (frontend/static/app.css,
#: added in notebook-ops-hardening-m4). ``skipped`` is the normal arxiv-kind
#: state (no PDF parse needed) → ok. ``.get(..., "warn")`` is the forward-compat
#: fallback: an unknown future status renders amber (attention) rather than
#: crashing a match/if-chain.
_PARSE_STATUS_CSS: dict[str, str] = {
    "complete": "ok",
    "skipped": "ok",
    "pending": "warn",
    "running": "warn",
    "failed": "down",
}

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


#: ui-badge-disambiguate — check keys whose non-``pass`` state means the
#: operator should ACT (the badge label flips to "DEGRADED"). All other
#: non-``pass`` checks are ops-side / informational and produce the softer
#: "WARN" label. Keep in lockstep with the check-key set built in
#: :func:`server.health.compute_health_status` — if you add a check there,
#: classify it here (membership = retrieval-side, omission = ops-side).
#:
#: Today's bucket assignments:
#:   retrieval-side (here)  : embedder:status, lancedb:status,
#:                            corpus:version, notebooks:count
#:   ops-side (fall-through): backup:time, disk:utilization, process:uptime
_RETRIEVAL_CHECK_KEYS: frozenset[str] = frozenset({
    "embedder:status",
    "lancedb:status",
    "corpus:version",
    "notebooks:count",
})


def _classify_status_badge(report: dict) -> tuple[str, str]:
    """Return ``(label, css_modifier)`` for the operator-console badge.

    The four outcomes:

    - ``fail``                   → ``("DOWN", "down")``      — server not warm.
    - ``warn`` with any retrieval check non-pass → ``("DEGRADED", "warn")``
      — operator should ACT (corpus drift, lancedb MVCC fallback, embedder
      down, notebooks-store probe failure).
    - ``warn`` with only ops-side checks non-pass → ``("WARN", "ops-warn")``
      — informational (backup not yet run, disk near threshold).
    - ``pass``                    → ``("READY", "ok")``.

    The badge MUST re-derive the label by inspecting ``report["checks"]``
    rather than reading ``report["summary"]`` — :func:`compute_health_status`
    pre-renders ``"DEGRADED"`` for ALL warn cases (it is shared with the
    ``make status`` CLI where terminal context wants the loudest label).
    """
    status = str(report.get("status") or "fail")
    if status == "fail":
        return ("DOWN", "down")
    if status == "pass":
        return ("READY", "ok")
    # status == "warn": split by check classification.
    checks = report.get("checks")
    if not isinstance(checks, dict):
        # Defensive: schema drift fallback — preserve today's "DEGRADED"
        # behavior so a future health-shape change cannot silently mask a
        # real retrieval degradation behind a softer "WARN" label.
        return ("DEGRADED", "warn")
    for key in _RETRIEVAL_CHECK_KEYS:
        entries = checks.get(key) or []
        for entry in entries:
            if (
                isinstance(entry, dict)
                and entry.get("status") not in (None, "pass")
            ):
                return ("DEGRADED", "warn")
    return ("WARN", "ops-warn")


@router.get(
    "/status-badge", response_class=HTMLResponse, include_in_schema=False
)
async def ui_status_badge(request: Request) -> HTMLResponse:
    """Live operability badge for the UI shell (notebook-ops-hardening-m4).

    Returns a tiny HTML ``<span>`` fragment the footer badge swaps in via
    ``hx-get`` / ``hx-trigger="every 10s"``. Backed by the SAME
    :func:`server.health.compute_health_status` snapshot as the
    ``/status`` JSON endpoint.

    Lives under ``/ui/`` (NOT ``/status``) on purpose: htmx renders HTML not
    JSON, and a browser XHR to the non-``/ui`` ``/status`` would be 403'd by
    ``SecFetchSiteMiddleware`` (which exempts only ``/ui``). **Always returns
    200** — the badge must render the state (even "DOWN") in the browser; it
    is a UI fragment, not a probe. The fragment re-emits its own
    ``hx-get``/``hx-trigger`` so the swapped-in element keeps polling.

    Label disambiguation (ui-badge-disambiguate): "DEGRADED" means a
    retrieval-relevant check is non-pass (operator should act); "WARN" means
    only ops-side checks (backup, disk, uptime) are non-pass (informational,
    retrieval is unaffected). Both share the same `warn`-flavored top-level
    `/status` status but render with distinct labels + CSS classes.
    """
    import html as _html  # noqa: PLC0415

    from server.health import compute_health_status  # noqa: PLC0415

    resources = getattr(request.app.state, "resources", None)
    store = getattr(request.app.state, "notebooks_store", None)
    report = await compute_health_status(resources, store)
    label, css = _classify_status_badge(report)
    raw_summary = str(report.get("summary") or "")
    # Replace compute_health_status()'s leading READY/DEGRADED token with the
    # disambiguated label, preserving the " | corpus v..." trailer (and the
    # leading space before the first pipe — health.py renders
    # "{LABEL} | corpus v{N} | {M} notebooks", and a naive `find("|")` slice
    # would drop the space).
    _, sep, rest = raw_summary.partition("|")
    summary = f"{label} {sep}{rest}" if sep else label
    safe = _html.escape(summary)
    # ui-attractive-polish-m1 (UPL-3): aria-live="polite" + aria-atomic="true"
    # MUST be on the SWAP RESULT (this fragment), not only on the initial
    # render in base.html. htmx hx-swap="outerHTML" replaces the <span>
    # entirely every 10s — if the new element omits these attributes, screen
    # readers stop announcing badge state changes after the first poll
    # (research-synthesis.md §2 — both Phase-1 researchers flagged this
    # independently as the most-critical implementation risk for m1).
    # onboarding-uplift-m3 (AC5): when status is non-pass, append a
    # static <small> remediation block with operator-actionable hints
    # naming the failing check + the Make command to heal it. m3
    # synthesis §3 D2 EXPLICITLY rejected <details>/<summary> because
    # hx-swap="outerHTML" replaces the entire <span> every 10s and
    # would snap any <details> closed on each poll. A static <small>
    # block visible-when-degraded has no open-state to lose.
    remediation = _build_remediation_block(report, css)
    fragment = (
        f'<span id="status-badge" class="status-badge status-badge--{css}" '
        f'aria-live="polite" aria-atomic="true" '
        f'hx-get="/ui/status-badge" hx-trigger="every 10s" '
        f'hx-swap="outerHTML" title="{safe}">{safe}{remediation}</span>'
    )
    return HTMLResponse(content=fragment)


def _build_remediation_block(report: dict, css: str) -> str:
    """Build the operator-actionable ``<small>`` remediation block
    appended to the badge when status is non-``ok``.

    Renders one ``<br>``-separated line per failing check, naming the
    check + the Make command to heal it. Returns an empty string when
    css == ``"ok"`` (no remediation needed).

    Per m3 synthesis §3 D2 / FM-6 — the block contains NO raw paths;
    only check names and Make command strings. The operator-trusted
    loopback context means we can include the slug, but exposing
    ``var/arxmcp/notebooks/<slug>/lancedb/`` would be noisy and
    unnecessary (the Make command does the path lookup internally).

    Static block (no JS, no <details>) per the same D2 — a JS-driven
    open/close-preserving tooltip would violate CLAUDE.md §4.7's no-
    build-chain rule. The visual affordance is the CSS-styled
    background colour (status-badge--warn / --down / --ops-warn)
    plus the small text block under the main label.
    """
    if css == "ok":
        return ""
    import html as _html  # noqa: PLC0415

    lines = list(_remediation_lines_for_checks(report.get("checks")))
    if not lines:
        # Fallback: surface the raw status without leaking internal
        # structure. Operators following this hint go to
        # docs/install.md for the troubleshooting matrix.
        lines = ["status non-pass — see docs/install.md troubleshooting"]
    body = "<br>".join(_html.escape(line) for line in lines)
    return (
        f'<small class="status-badge__remediation" aria-live="polite">'
        f'{body}</small>'
    )


def _remediation_lines_for_checks(checks: object) -> Iterable[str]:
    """Map non-``pass`` health checks to one operator-actionable line each.

    Inspects ``report["checks"]`` — same source ``_classify_status_badge``
    uses — and yields per-check remediation strings keyed off the well-
    known check names from ``server/health.py::compute_health_status``.

    Unknown / future checks fall through to a generic "investigate"
    line so a check rename or addition can't silently produce an empty
    tooltip.
    """
    if not isinstance(checks, dict):
        return
    # Map each check key to a human-readable name + remediation. Ordered
    # by criticality so retrieval-side appears first in the block.
    _CHECK_REMEDIATION: dict[str, tuple[str, str]] = {
        "corpus:version": (
            "corpus version marker drift",
            "run `make reconcile NOTEBOOK=<slug>` to heal",
        ),
        "lancedb:status": (
            "lancedb dataset health",
            "check the boot log for fallback_version warnings",
        ),
        "embedder:status": (
            "BGE-M3 embedder not loaded",
            "wait for warmup, or restart with `make up`",
        ),
        "notebooks:count": (
            "notebook registry / disk mismatch",
            "run `make repair-registry` to heal",
        ),
        "backup:time": (
            "no recent backup recorded",
            "run the restic backup job (see docs/ops/backup-runbook.md)",
        ),
        "disk:utilization": (
            "disk free space below threshold",
            "free space or expand the volume",
        ),
        "process:uptime": (
            "server process newly started",
            "informational — wait for caches to warm",
        ),
    }
    for key, (name, action) in _CHECK_REMEDIATION.items():
        entries = checks.get(key) or []
        for entry in entries:
            if (
                isinstance(entry, dict)
                and entry.get("status") not in (None, "pass")
            ):
                yield f"{name}: {action}"
                break  # one line per check (not per entry)


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
            and is_valid_arxiv_paper_id(paper_id)
            and _preview_html_path(slug, paper_id) is not None
        )
        annotated_papers.append({**row, "has_preview": has_preview})
    # notebook-surface-expansion-m1: per-notebook freshness signal. ONE O(1)
    # call (NOT per paper); returns the latest ingest-run row or None when the
    # notebook has never been ingested. The template renders "Never indexed" on
    # None. notebook["parse_status"] is already present from get_notebook above
    # (it lives on the notebooks table, not notebook_papers) — no extra query.
    latest_run = await store.get_latest_ingest_run(slug)
    parse_status_css = _PARSE_STATUS_CSS.get(
        notebook.get("parse_status") or "", "warn"
    )
    return templates.TemplateResponse(
        request=request,
        name="notebook_detail.html",
        context={
            "notebook": notebook,
            "papers": annotated_papers,
            "latest_run": latest_run,
            "parse_status_css": parse_status_css,
        },
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
    if not is_valid_arxiv_paper_id(paper_id):
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
        # check failed. F5 closure (m10 adversary critique): also
        # do NOT log the slug or paper_id — both are attacker-
        # controllable in the threat model that triggers this branch
        # (filesystem-symlink attacker). Logging them would form a
        # side-channel oracle confirming whether the redirect was
        # detected. Both inputs are recoverable from a correlated
        # access-log entry if forensics need them.
        logger.warning(
            "preview path-containment rejected (validated inputs)"
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
    # F1 closure (m10 adversary critique): strip <meta http-equiv=
    # "refresh"> tags before serving. The direct-serve route shape
    # (synthesis D1) has no CSP3 directive that blocks meta-refresh
    # navigation escapes; the regex strip is the cleanest closure.
    # The substitution comment is HTML — keeps the byte offset
    # roughly stable for line-numbered debugging in browser devtools.
    content_bytes = _META_REFRESH_RE.sub(
        b"<!-- meta-refresh stripped (m10 F1) -->", content_bytes,
    )
    return Response(
        content=content_bytes,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": CONTENT_SECURITY_POLICY_PREVIEW.decode(
                "ascii"
            ),
            # F7 closure (m10 adversary critique): suppress Referer
            # header on any navigation OUT of the preview tab. If the
            # served content tricks the user into clicking a link to
            # an attacker site, the attacker would otherwise see the
            # full preview URL (including the user-chosen slug, which
            # may have semantic meaning the user prefers not to leak).
            "Referrer-Policy": "no-referrer",
        },
    )


__all__ = ["router", "templates"]

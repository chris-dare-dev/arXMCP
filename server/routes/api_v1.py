"""``/api/v1`` — the JSON-only operator API (stage2/arx-a1, WS-A A1).

Aliases the 17 ``/ui/api`` notebook routes as a stable, versioned,
JSON-only surface (target-architecture.md §8.2; workstreams.md WS-A A1):

- **JSON only.** No ``HX-Request`` HTML|JSON unions anywhere: a request
  carrying ``HX-Request: true`` receives the byte-identical JSON body
  as one without (AC-A.1). The htmx fragment renderers stay on the
  legacy ``/ui/api`` surface, which remains mounted until the Jinja
  console retires (strangler pattern).
- **Explicit versioning.** Every JSON response carries
  ``format_version`` (currently ``1``); binary responses (the export
  tar) carry it as the ``X-Arxmcp-Format-Version`` header instead.
- **Pagination.** List endpoints accept ``limit``/``offset`` and return
  ``{format_version, items, total, limit, offset}`` with stable
  ordering (the store's ``ORDER BY`` clauses carry deterministic
  tiebreaks: ``created_at DESC, slug ASC`` / ``added_at DESC,
  paper_id ASC``).
- **Zero MCP impact.** Plain HTTP routes only; ``tools/list`` bytes and
  the BP1 hashes are untouched (pinned suite-wide by
  ``tests/test_server_tool_schema.py`` and re-asserted post-route by
  ``tests/test_bridge_route.py::TestByteStabilityGuard``).

Implementation strategy (single-source-of-truth discipline):

- Routes whose ``/ui/api`` handler is already JSON-only are
  **delegated** directly to that handler function (repair-registry,
  reconcile-marker, health, parse-status, remove-paper, export).
- Routes with an ``HX-Request`` union (create-notebook, add-paper,
  delete-notebook) are delegated through :func:`_json_only_request`,
  which strips the ``hx-request`` header from the ASGI scope so the
  shared handler always takes its JSON branch — the fragment branch is
  unreachable from this surface by construction.
- Routes that are HTML-fragment-only on ``/ui/api`` (rename, topic,
  discover, upload, ingest trigger/poll) get thin JSON handlers here
  that call the SAME validators and store/tracker methods as the
  legacy handlers. When ``/ui/api`` retires, these become the only
  implementations.

The OpenAPI document for this surface is generated OFFLINE by
``python -m tools.dump_openapi`` (Interface Artifact IF-1); the runtime
``openapi_url`` stays disabled (Threat 4 — see
``server/main.py::create_app``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from starlette.requests import Request as StarletteRequest

from server.routes import notebooks as _nb
from server.routes.notebooks import (
    NotebookCreate,
    NotebookRename,
    NotebookTopicUpdate,
    PaperAdd,
    get_notebooks_store,
)
from tools._notebook_common import NotebookError, validate_slug

if TYPE_CHECKING:
    from server.notebooks_store import NotebooksStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api-v1"])

#: The explicit response format version every JSON body on this surface
#: carries. Bump ONLY with a documented, versioned migration — external
#: consumers (the WS-B typed client, bridge tooling) parse it.
API_V1_FORMAT_VERSION: int = 1

#: Pagination bounds. ``limit`` defaults generously (the biggest live
#: notebook holds ~127 papers) but is capped so a buggy client cannot
#: request an unbounded page.
_MAX_PAGE_LIMIT: int = 500
_DEFAULT_PAGE_LIMIT: int = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with ``format_version`` stamped (never mutates)."""
    return {"format_version": API_V1_FORMAT_VERSION, **payload}


def _page(rows: list[Any], limit: int, offset: int) -> dict[str, Any]:
    """Build the paginated list envelope over an already-ordered list."""
    return {
        "format_version": API_V1_FORMAT_VERSION,
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


def _json_only_request(request: Request) -> Request:
    """Return a Request whose scope has the ``hx-request`` header removed.

    The shared ``/ui/api`` handlers fork on ``HX-Request: true`` to
    serve htmx fragments. On ``/api/v1`` that fork must be unreachable:
    AC-A.1 requires the identical JSON body with or without the header.
    Rebuilding the request around a filtered ASGI ``headers`` list is
    the minimal, transport-level way to guarantee the delegated handler
    always takes its JSON branch — no handler-side flag threading, no
    behavioural drift risk on the legacy surface.
    """
    if "hx-request" not in request.headers:
        return request
    scope = dict(request.scope)
    scope["headers"] = [
        (k, v) for (k, v) in request.scope["headers"] if k.lower() != b"hx-request"
    ]
    return StarletteRequest(scope, request.receive)


def _validate_slug_or_422(slug: str) -> None:
    """Shared slug gate — identical translation to the legacy handlers."""
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


async def _get_notebook_or_404(store: NotebooksStore, slug: str) -> dict:
    notebook = await store.get_notebook(slug)
    if notebook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    return notebook


# ---------------------------------------------------------------------------
# Notebook collection
# ---------------------------------------------------------------------------


@router.get("/notebooks")
async def list_notebooks_v1(
    limit: int = Query(default=_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """List notebooks, paginated, ordered ``created_at DESC, slug ASC``
    (the store's stable ordering)."""
    rows = await store.list_notebooks()
    return _page(rows, limit, offset)


@router.post("/notebooks", status_code=status.HTTP_201_CREATED)
async def create_notebook_v1(
    body: NotebookCreate,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Create a notebook. Delegates to the shared handler's JSON branch
    (409 on duplicate slug; 422 on bad slug/category)."""
    result = await _nb.create_notebook(body, _json_only_request(request), store)
    # The delegated call can only return the dict branch (the fragment
    # branch requires the hx-request header, stripped above); the
    # isinstance gate is belt-and-braces against future drift.
    if not isinstance(result, dict):  # pragma: no cover — unreachable by construction
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="delegated create_notebook returned a non-JSON branch",
        )
    return _stamp(result)


@router.delete("/notebooks/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notebook_v1(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> None:
    """Metadata-only delete (404 if absent). Always 204 — the legacy
    handler's HX-Request 200-empty-body branch is unreachable here."""
    result = await _nb.delete_notebook(slug, _json_only_request(request), store)
    if result is not None:  # pragma: no cover — unreachable by construction
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="delegated delete_notebook returned a non-204 branch",
        )
    return None


@router.patch("/notebooks/{slug}")
async def rename_notebook_v1(
    slug: str,
    body: NotebookRename,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Rename a notebook's ``display_name`` — JSON alias of the legacy
    fragment-only PATCH. Same validation order and store call; returns
    the stored (control-char-stripped) value instead of an HTML swap."""
    _validate_slug_or_422(slug)
    cleaned = _nb._CONTROL_CHARS_RE.sub("", body.display_name)
    updated = await store.update_display_name(slug, cleaned)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    return _stamp({"slug": slug, "display_name": cleaned})


@router.patch("/notebooks/{slug}/topic")
async def update_topic_v1(
    slug: str,
    body: NotebookTopicUpdate,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Update topic metadata — JSON alias of the legacy fragment-only
    PATCH. Same category enum gate + control-char stripping."""
    _validate_slug_or_422(slug)
    try:
        _nb._validate_discovery_category(body.discovery_category)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    cleaned_desc = _nb._CONTROL_CHARS_RE.sub("", body.description)
    updated = await store.update_topic(slug, body.discovery_category, cleaned_desc)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    return _stamp({
        "slug": slug,
        "discovery_category": body.discovery_category,
        "description": cleaned_desc,
    })


@router.post("/notebooks/{slug}/discover")
async def discover_papers_v1(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Run topic discovery — JSON alias of the legacy fragment-only
    POST. Same driver, dedup, and error translation (422 unconfigured;
    502 arXiv failure); returns the candidate list as JSON. The
    candidate QUEUE remains EPHEMERAL (propose-only; no junction rows
    are written); real paper metadata is populated separately by the
    per-notebook arXiv-Atom backfill (``tools/notebook_metadata_backfill.py``
    → ``server.paper_metadata_store``)."""
    from tools.discover_for_notebook import (  # noqa: PLC0415
        discover_for_notebook_async,
    )

    _validate_slug_or_422(slug)
    # 404 if the notebook does not exist (contract preserved); the
    # returned row is otherwise unused now that discovery is propose-only.
    await _get_notebook_or_404(store, slug)
    try:
        candidates = await discover_for_notebook_async(
            store, slug, contact_email=_nb._safe_contact_email(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except (RuntimeError, OSError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"discovery failed: {e}",
        ) from e
    return _stamp({
        "slug": slug,
        "candidates": [
            {
                "paper_id": c.paper_id,
                "title": c.title,
                "abstract_head": c.abstract_head,
                "submitted_date": c.submitted_date,
            }
            for c in candidates
        ],
        "count": len(candidates),
    })


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------


@router.get("/notebooks/{slug}/papers")
async def list_papers_v1(
    slug: str,
    limit: int = Query(default=_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """List a notebook's paper junction rows, paginated, ordered
    ``added_at DESC, paper_id ASC`` (the store's stable ordering)."""
    _validate_slug_or_422(slug)
    await _get_notebook_or_404(store, slug)
    rows = await store.list_papers(slug)
    return _page(rows, limit, offset)


@router.post("/notebooks/{slug}/papers", status_code=status.HTTP_201_CREATED)
async def add_paper_v1(
    slug: str,
    body: PaperAdd,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Add a paper by arXiv URL. Delegates to the shared handler's JSON
    branch (422 bad URL; 404 no notebook; 409 duplicate)."""
    result = await _nb.add_paper(slug, body, _json_only_request(request), store)
    if not isinstance(result, dict):  # pragma: no cover — unreachable by construction
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="delegated add_paper returned a non-JSON branch",
        )
    return _stamp(result)


@router.delete(
    "/notebooks/{slug}/papers/{paper_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_paper_v1(
    slug: str,
    paper_id: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> None:
    """Remove a paper junction row — direct delegate (already JSON/204)."""
    return await _nb.remove_paper(slug, paper_id, store)


@router.post("/notebooks/{slug}/papers/upload", status_code=status.HTTP_201_CREATED)
async def upload_paper_v1(
    request: Request,
    slug: str,
    paper_id: str = Form(...),  # noqa: B008  (FastAPI DI pattern)
    file: UploadFile = File(...),  # noqa: B008  (FastAPI DI pattern)
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> Response:
    """Upload an ar5iv HTML (arxiv-kind) or PDF (textbook-kind) file.

    Delegates the ENTIRE validated pipeline (per-kind caps, magic-byte
    sniff, 5-vector PDF preflight, atomic write, junction insert, parse
    scheduling) to the shared handler, then translates its
    fragment-response status into a JSON body:

    - 201 → ``result: "created"`` (new junction row + file written)
    - 200 → ``result: "updated_existing"`` (row existed; file
      atomically overwritten — the legacy handler's idempotent-upload
      contract)
    """
    from fastapi.responses import JSONResponse  # noqa: PLC0415

    delegated = await _nb.upload_paper(request, slug, paper_id, file, store)
    result = (
        "created"
        if delegated.status_code == status.HTTP_201_CREATED
        else "updated_existing"
    )
    return JSONResponse(
        status_code=delegated.status_code,
        content=_stamp({"slug": slug, "paper_id": paper_id, "result": result}),
    )


# ---------------------------------------------------------------------------
# Ingest trigger + status
# ---------------------------------------------------------------------------


@router.post("/notebooks/{slug}/ingest", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest_v1(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Spawn a background ingest — JSON alias of the legacy
    fragment-returning trigger. Same sequencing (validate → 409-check →
    INSERT row → spawn task) and the same two-layer collision check;
    returns the run row reference instead of an htmx fragment.

    stage2/arx-a45 (AC-A.18): kind-aware dispatch via the SAME
    ``_ingest_dispatch_kwargs`` helper as the legacy trigger — a
    textbook notebook spawns ``tools.notebook_textbook_ingest`` with
    its stored ``textbook_chunker``; arxiv-kind keeps the papers.txt
    bulk ingest. One helper, two surfaces, zero drift.
    """
    _validate_slug_or_422(slug)
    notebook = await _get_notebook_or_404(store, slug)
    tracker = _nb._get_ingest_tracker(request)
    if tracker.is_running(slug) or await store.has_running_ingest(slug):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"an ingest is already in flight for notebook "
                f"{slug!r} — wait for it to finish before triggering "
                f"another"
            ),
        )
    dispatch = await _nb._ingest_dispatch_kwargs(store, notebook)
    started_at = _nb._now_iso()
    run_id = await store.insert_ingest_run(slug, started_at)
    tracker.start_ingest(
        slug=slug, run_id=run_id, store=store,
        now_iso_provider=_nb._now_iso,
        **dispatch,
    )
    return _stamp({
        "slug": slug,
        "run_id": run_id,
        "status": "running",
        "started_at": started_at,
    })


@router.get("/notebooks/{slug}/ingest/latest")
async def latest_ingest_v1(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Latest ingest-run state as JSON. Plain 200 always (no HTTP 286 —
    that status is an htmx polling-transport artifact of the legacy
    surface); ``terminal`` tells a JSON poller when to stop.

    ``status: "none"`` when the notebook has no runs yet.
    """
    _validate_slug_or_422(slug)
    await _get_notebook_or_404(store, slug)
    row = await store.get_latest_ingest_run(slug)
    if row is None:
        return _stamp({"slug": slug, "status": "none", "terminal": False})
    return _stamp({
        "slug": slug,
        "run_id": row["id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "exit_code": row["exit_code"],
        "stderr_tail": row["stderr_tail"],
        "terminal": row["status"] != store.INGEST_STATUS_RUNNING,
    })


@router.get("/notebooks/{slug}/parse-status")
async def parse_status_v1(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Textbook-parse status — direct delegate (already JSON) + stamp."""
    result = await _nb.parse_status(slug, store)
    return _stamp(result)


# ---------------------------------------------------------------------------
# Citation graph (stage2/arx-a45, AC-A.20)
# ---------------------------------------------------------------------------


@router.get("/notebooks/{slug}/graph/neighbors")
async def graph_neighbors_v1(
    slug: str,
    request: Request,
    paper_id: str = Query(min_length=1, description="arXiv paper id"),
    direction: str = Query(
        default="cites",
        pattern="^(cites|cited_by|depends_on)$",
        description="Graph traversal direction",
    ),
    depth: int = Query(default=2, ge=1, le=2, description="Hop count"),
    limit: int = Query(
        default=30, ge=1, le=100, description="Max neighbors returned",
    ),
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Citation-graph neighbors of ``paper_id`` — the REST read twin of
    the MCP ``cite_neighbors`` tool (AC-A.20).

    Mirrors the MCP handler's envelope vocabulary and degradation
    semantics exactly (``server/handlers/citations.py``,
    verification-feedback-m1):

    - ``graph_status: "absent"`` — the Kùzu DB path does not exist
      (graph not ingested). Empty ``neighbors``, HTTP 200.
    - ``graph_status: "unavailable"`` — the path exists but is not a
      queryable Kùzu graph (stray dir / corrupt / half-ingested DB;
      Kùzu raises RuntimeError). Empty ``neighbors``, HTTP 200,
      logged at WARNING so the operator failure is observable.
    - ``graph_status: "present"`` — queried successfully; ``neighbors``
      rows carry the same ``CitationNeighbor`` field vocabulary as the
      MCP tool (``paper_id``/``chunk_id``/``edge_kind``/
      ``hop_distance``/``source``/``confidence``, ordered
      ``(hop_distance ASC, paper_id ASC)``).

    Differences owned by this surface (documented, deliberate): the
    query key is ``paper_id`` (junction rows, not chunk ids — the MCP
    tool's chunk_id parse happens before the shared library entry
    anyway) and the version stamp is ``format_version`` (the
    ``/api/v1`` envelope) rather than the MCP ``corpus_version`` echo,
    which requires warm retrieval Resources this read-only surface
    must not depend on (the graph is queryable in bootstrap mode).

    F2 path-validation contract: the Kùzu/LanceDB paths come from
    ``app.state.config`` — NEVER from request input. The client
    controls only ``paper_id`` (regex-validated), ``direction``/
    ``depth``/``limit`` (enum/bounds-validated).
    """
    import dataclasses  # noqa: PLC0415

    from ingest.identifiers import is_valid_arxiv_paper_id  # noqa: PLC0415
    from server.graph_queries import cite_neighbors_for_paper  # noqa: PLC0415

    _validate_slug_or_422(slug)
    await _get_notebook_or_404(store, slug)
    if not is_valid_arxiv_paper_id(paper_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"paper_id {paper_id!r} does not match the arXiv id format"
            ),
        )

    config = request.app.state.config
    kuzu_path = config.kuzu_path

    neighbors: list[dict[str, Any]] = []
    if not kuzu_path.exists():
        graph_status = "absent"
    else:
        try:
            results = await cite_neighbors_for_paper(
                paper_id,
                depth=depth,
                direction=direction,  # type: ignore[arg-type]  # pattern-validated above
                max_results=limit,
                kuzudb_path=str(kuzu_path),
                lancedb_path=str(config.lancedb_path),
            )
        except RuntimeError as exc:
            # Same unambiguity argument as the MCP handler: inputs are
            # pre-validated, so RuntimeError here is a graph-
            # availability failure, never an input error.
            logger.warning(
                "graph_neighbors_v1: Kùzu graph at %s is not queryable: %s",
                kuzu_path,
                exc,
            )
            graph_status = "unavailable"
        else:
            neighbors = [dataclasses.asdict(n) for n in results]
            graph_status = "present"

    return _stamp({
        "slug": slug,
        "paper_id": paper_id,
        "direction": direction,
        "depth": depth,
        "limit": limit,
        "graph_status": graph_status,
        "neighbors": neighbors,
    })


# ---------------------------------------------------------------------------
# Admin / drift-healing / export
# ---------------------------------------------------------------------------


@router.post("/admin/repair-registry")
async def repair_registry_v1(
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Registry repair — direct delegate (already JSON) + stamp."""
    result = await _nb.repair_registry(store)
    return _stamp(result.model_dump())


@router.post("/notebooks/{slug}/reconcile-marker")
async def reconcile_marker_v1(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Marker reconcile — direct delegate (already JSON) + stamp."""
    result = await _nb.reconcile_marker(slug, store)
    return _stamp(result.model_dump())


@router.get("/notebooks/{slug}/health")
async def notebook_health_v1(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> dict[str, Any]:
    """Per-notebook drift report — direct delegate (already JSON) + stamp."""
    result = await _nb.notebook_health(slug, store)
    return _stamp(result.model_dump())


@router.get(
    "/notebooks/{slug}/export",
    responses={
        200: {"content": {"application/x-tar": {}}},
        404: {"description": "notebook not found"},
        422: {"description": "malformed slug"},
    },
)
async def export_notebook_v1(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> Response:
    """Deterministic notebook tar — direct delegate. Binary response;
    the format version rides in ``X-Arxmcp-Format-Version`` (the tar's
    internal ``manifest.json`` carries the bundle's own
    ``format_version`` independently)."""
    response = await _nb.export_notebook(slug, store)
    response.headers["X-Arxmcp-Format-Version"] = str(API_V1_FORMAT_VERSION)
    return response


__all__ = [
    "API_V1_FORMAT_VERSION",
    "router",
]

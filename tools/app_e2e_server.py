"""Hermetic e2e server for the frontend-app Playwright suite (arx-b1).

Serves the REAL committed ``frontend-app/dist`` through the REAL
:mod:`server.spa` mount and the REAL :class:`SecurityHeadersMiddleware`
(so the Playwright suite exercises the production ``/app`` CSP byte-
for-byte), plus a mock ``/api/v1`` implementation mirroring the
fixtures in ``frontend-app/src/api/mock.ts`` — IF-1's decoupling
promise: the SPA test suite needs no live arXMCP process, no models,
no corpus.

Also serves the D7 MathML render-spike surfaces:

- ``/spike/mathml`` — a committed fixture with ar5iv-shaped MathML,
  served under the REAL ``CONTENT_SECURITY_POLICY_PREVIEW``
  (``script-src 'none'``) so the spike verdict is measured against
  the exact policy the preview route uses.
- ``/spike/mathml-real`` — a stored ar5iv paper from the workstation
  cache when present (read-only), 404 otherwise; the Playwright spec
  skips itself gracefully off-workstation.

Run: ``python tools/app_e2e_server.py`` (loopback 127.0.0.1:7799).
Playwright starts/stops it via ``webServer`` in playwright.config.ts.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# THIS checkout's server package, not an editable install pointing at
# another worktree — the CSP bytes under test must be this branch's.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio  # noqa: E402
import copy  # noqa: E402
import datetime as _dt  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, Request, UploadFile  # noqa: E402
from fastapi.responses import (  # noqa: E402
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)

from server.middleware import (  # noqa: E402
    CONTENT_SECURITY_POLICY_PREVIEW,
    SecurityHeadersMiddleware,
)
from server.spa import mount_frontend_app  # noqa: E402

#: Mirrors frontend-app/src/api/mock.ts — keep in lockstep.
FIXTURE_NOTEBOOKS = [
    {
        "slug": "bridgeland-stability",
        "display_name": "Bridgeland stability",
        "lancedb_path": "var/arxmcp/notebooks/bridgeland-stability/lancedb",
        "created_at": "2026-06-22T03:08:28Z",
        "notebook_kind": "arxiv",
        "parse_status": "skipped",
        "parse_error": None,
        "parsed_html_path": None,
        "discovery_category": "math.AG",
        "description": "Stability conditions on derived categories",
    },
    {
        "slug": "fourier-duality",
        "display_name": "Fourier duality",
        "lancedb_path": "var/arxmcp/notebooks/fourier-duality/lancedb",
        "created_at": "2026-06-15T22:16:29Z",
        "notebook_kind": "arxiv",
        "parse_status": "skipped",
        "parse_error": None,
        "parsed_html_path": None,
        "discovery_category": "math.AG",
        "description": "Fourier-Mukai transforms and duality",
    },
]

#: Mirrors frontend-app/src/api/mock.ts FIXTURE_PAPERS — keep in lockstep.
FIXTURE_PAPERS = {
    "bridgeland-stability": [
        {"paper_id": "0705.3794", "added_at": "2026-06-22T03:10:02Z"},
        {"paper_id": "1109.5069", "added_at": "2026-06-22T03:09:11Z"},
    ],
    "fourier-duality": [],
}

#: Mirrors frontend-app/src/api/mock.ts FIXTURE_HEALTH — keep in lockstep.
FIXTURE_HEALTH = {
    "bridgeland-stability": {
        "format_version": 1,
        "slug": "bridgeland-stability",
        "status": "ok",
        "marker_chunk_count": 12672,
        "actual_chunk_count": 12672,
        "marker_paper_count": 2,
        "actual_paper_count": 2,
        "drift": 0,
        "corpus_version": 1690,
        "detail": None,
        "marker_created_at": "2026-06-22T04:00:11Z",
        "chunker_version": "2",
        "embedder_version": "bge-m3@567",
    },
    "fourier-duality": {
        "format_version": 1,
        "slug": "fourier-duality",
        "status": "drift",
        "marker_chunk_count": 2051,
        "actual_chunk_count": 2050,
        "marker_paper_count": 1,
        "actual_paper_count": 1,
        "drift": -1,
        "corpus_version": 1517,
        "detail": (
            "marker says 2051 chunks / 1 papers; LanceDB has 2050 chunks / "
            "1 papers. Run `make reconcile NOTEBOOK=fourier-duality` "
            "(or POST reconcile-marker)."
        ),
        "marker_created_at": "2026-06-15T23:00:41Z",
        "chunker_version": "2",
        "embedder_version": "bge-m3@567",
    },
}


def _page(rows: list, limit: int, offset: int) -> dict:
    """The api_v1 ``_page`` envelope over an already-ordered list."""
    return {
        "format_version": 1,
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


#: Mirrors server/routes/notebooks.py `_arxiv_url_to_paper_id` on THIS
#: branch (the A1 spine): arxiv.org accepts only /abs/; ar5iv accepts
#: only /html/. The arx-a45 branch widens arxiv.org to /html/ too —
#: keeping the spine behavior here is deliberate, so the Playwright
#: suite exercises the SPA's documented native-HTML degrade path.
_E2E_ACCEPTED = {
    "arxiv.org": ("/abs/",),
    "ar5iv.labs.arxiv.org": ("/html/",),
}

_NEW_STYLE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?\Z")
_OLD_STYLE = re.compile(r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z")


def _is_arxiv_id(candidate: str) -> bool:
    return bool(_NEW_STYLE.match(candidate) or _OLD_STYLE.match(candidate))


def _e2e_arxiv_url_to_paper_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    prefixes = _E2E_ACCEPTED.get(parsed.hostname or "")
    if not prefixes:
        return None
    for prefix in prefixes:
        if parsed.path.startswith(prefix):
            candidate = parsed.path[len(prefix):].rstrip("/")
            if candidate and _is_arxiv_id(candidate):
                return candidate
    return None


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


#: Mirrors frontend-app/src/api/mock.ts FIXTURE_DISCOVER — keep in lockstep.
FIXTURE_DISCOVER = [
    {
        "paper_id": "2406.01234",
        "title": "Stability conditions under Fourier–Mukai transforms",
        "abstract_head": (
            "We study the behaviour of Bridgeland stability conditions under "
            "Fourier–Mukai transforms between derived categories of "
            "smooth projective varieties…"
        ),
        "submitted_date": "2026-06-30",
    },
    {
        "paper_id": "2406.05678",
        "title": "Derived categories of K3 surfaces revisited",
        "abstract_head": (
            "A new proof of the derived Torelli theorem for K3 surfaces, "
            "with applications to moduli of stable objects…"
        ),
        "submitted_date": "2026-06-28",
    },
]

#: ------------------------------------------------------------------
#: arx-b3 observability fixtures — deterministic timestamps anchored
#: at 2026-07-04T12:00:00Z so the visual baselines pin stable clock
#: strings. Shapes mirror the arx-a23 payloads field-for-field
#: (server/observability/events.py + server/session.snapshot_sessions)
#: and stay in lockstep with
#: frontend-app/src/pages/observability/testDoubles.ts.
#: ------------------------------------------------------------------
_OBS_T0 = 1783166400.0  # 2026-07-04T12:00:00Z

FIXTURE_OBS_LOGS = [
    {
        "level": "INFO", "name": "server.tools",
        "message": "search_papers served", "event": "tool_call",
        "tool": "search_papers", "session_id": "a1b2c3d4e5f60718",
        "role": "sketcher",
    },
    {
        "level": "INFO", "name": "server.cache", "message": "tier1 hit",
        "event": "cache_probe", "tool": "search_papers",
    },
    {
        "level": "WARNING", "name": "server.session",
        "message": "cap approaching", "event": "cap_check",
        "session_id": "a1b2c3d4e5f60718", "role": "sketcher",
    },
    {
        "level": "ERROR", "name": "server.ingest",
        "message": "latexml conversion failed", "event": "ingest_stage",
        "tool": "get_chunk",
    },
    {"level": "INFO", "name": "server.health", "message": "readyz probe", "event": "probe"},
    {"level": "INFO", "name": "server.health", "message": "readyz probe", "event": "probe"},
    {"level": "INFO", "name": "server.health", "message": "readyz probe", "event": "probe"},
    {
        "level": "INFO", "name": "server.tools",
        "message": "get_chunk served", "event": "tool_call",
        "tool": "get_chunk", "session_id": "a1b2c3d4e5f60718",
        "role": "sketcher",
    },
]

FIXTURE_OBS_REQUESTS = [
    {
        "tool": "search_papers", "status": "ok", "error_code": None,
        "session_id": "a1b2c3d4e5f60718", "role": "sketcher",
        "profile": "default", "notebook": "bridgeland-stability",
        "latency_ms": 42.5, "cache_layer": "tier1", "result_bytes": 2048,
        "k": 5, "corpus_version": 1690,
        "phases_ms": {"cache_probe": 1.2, "embed": 18.3, "ann": 20.1},
    },
    {
        "tool": "get_chunk", "status": "ok", "error_code": None,
        "session_id": "a1b2c3d4e5f60718", "role": "sketcher",
        "profile": "default", "notebook": None, "latency_ms": 3.1,
        "cache_layer": "tier2", "result_bytes": 4096, "k": None,
        "corpus_version": 1690,
    },
    {
        "tool": "search_papers", "status": "cap",
        "error_code": "RETRIEVAL_CAP_REACHED",
        "session_id": "a1b2c3d4e5f60718", "role": "sketcher",
        "profile": "default", "notebook": None, "latency_ms": 0.4,
        "cache_layer": None, "result_bytes": None, "k": 5,
        "corpus_version": None,
    },
    {
        "tool": "lean_verify", "status": "error", "error_code": "RuntimeError",
        "session_id": "0f1e2d3c4b5a6978", "role": "tactician",
        "profile": "pipeline", "notebook": None, "latency_ms": 130.9,
        "cache_layer": None, "result_bytes": None, "k": None,
        "corpus_version": None,
    },
]

FIXTURE_OBS_SESSIONS = [
    {
        "session_id_prefix": "a1b2c3d4e5f60718",
        "created_at": _OBS_T0 - 600,
        "last_seen_at": _OBS_T0 + 30,
        "roles_seen": ["sketcher"],
        "counts": {"search_papers": 3, "get_chunk": 1},
        "caps": {
            "search_papers": {"limit": 3, "used": 3, "remaining": 0},
            "get_chunk": {"limit": 4, "used": 1, "remaining": 3},
        },
        "hourly": {"used": 4, "limit": 1000, "window_seconds": 3600},
    },
    {
        "session_id_prefix": "0f1e2d3c4b5a6978",
        "created_at": _OBS_T0 - 7200,
        "last_seen_at": _OBS_T0 - 3600,
        "roles_seen": ["tactician", "fixer"],
        "counts": {"search_papers": 1},
        "caps": {"search_papers": {"limit": 3, "used": 1, "remaining": 2}},
        "hourly": {"used": 1, "limit": 1000, "window_seconds": 3600},
    },
]

FIXTURE_OBS_INGEST = [
    {
        "kind": "ingest", "slug": "bridgeland-stability",
        "stage": "preflight", "phase": "finished", "run_id": 3,
    },
    {
        "kind": "ingest", "slug": "bridgeland-stability", "stage": "chunk",
        "phase": "finished", "run_id": 3, "detail": {"papers_ok": 2},
    },
    {
        "kind": "ingest", "slug": "bridgeland-stability", "stage": "run",
        "phase": "finished", "run_id": 3,
    },
    {
        "kind": "parse", "slug": "spectral-textbook", "stage": "mineru",
        "phase": "failed", "run_id": 9, "detail": {"error": "exit 1"},
    },
]


#: ------------------------------------------------------------------
#: arx-b3 capability + graph fixtures.
#:
#: Capabilities mirror server/routes/capabilities.py on stage2/arx-a23:
#: the GET serves the PARSED view — a synthesized permissive `default`
#: appears whenever the operator has not defined one; one operator
#: profile ("website", allowlisted) is pre-seeded so the D5 call-time
#: copy renders on the read-only instance for axe + the visual
#: baselines.
#:
#: The graph adjacency mirrors
#: frontend-app/src/pages/graph/testDoubles.ts — keep in lockstep.
#: Shapes mirror api_v1.graph_neighbors_v1 on stage2/arx-a45
#: (CitationNeighbor rows, (hop ASC, paper_id ASC) ordering,
#: present/absent/unavailable degradation, 422 on malformed ids).
#: ------------------------------------------------------------------

FIXTURE_CAP_PROFILES = {
    "website": {
        "enabled": True,
        "token_sha256": "ab" * 32,
        "tools": {"allow": ["get_paper", "search_papers"]},
        "caps": {"search_papers": 5},
        "notebooks": {"allow": ["bridgeland-stability"]},
    },
}

_CAP_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_CAP_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
_CAP_PUT_FIELDS = {"enabled", "token_sha256", "tools", "caps", "notebooks"}

#: (neighbor_paper_id, representative_chunk_id) per root, per direction.
FIXTURE_GRAPH: dict[str, dict[str, list[tuple[str, str | None]]]] = {
    "cites": {
        "0705.3794": [
            ("0708.2247", "0708.2247#stmt-0001"),
            ("0811.2435", None),
        ],
        "0708.2247": [
            ("0705.3794", "0705.3794#stmt-0002"),
            ("1106.5217", None),
        ],
        "1109.5069": [("1203.4613", "1203.4613#stmt-0007")],
    },
    "cited_by": {
        "0705.3794": [("1203.4613", "1203.4613#stmt-0007")],
    },
    "depends_on": {},
}


#: Read-only probe locations for a real stored ar5iv paper (the main
#: checkout's cache first, then this worktree's own var tree).
_REAL_AR5IV_CANDIDATES = (
    Path("C:/Users/cedar/Documents/Personal Projects/Source Code/arXMCP")
    / "var/arxmcp/cache/ar5iv/0705.3794.html",
    REPO_ROOT / "var/arxmcp/cache/ar5iv/0705.3794.html",
)


def create_e2e_app() -> FastAPI:
    """Hermetic app. STATEFUL per process: the notebook-flows spec runs
    against a second instance (port 7800) so mutations never race the
    read-only visual/axe suites on 7799; ``POST /e2e/reset`` restores
    the pristine fixtures between tests (the flows spec is serial).
    """
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    state: dict = {}
    #: Live SSE subscribers (one unbounded queue per stream client —
    #: test-scale only; the real EventBus enforces caps, AC-A.14).
    subscribers: set[asyncio.Queue] = set()

    def _reset_state() -> None:
        # Generation token: a scripted ingest task from a previous test
        # aborts as soon as reset bumps the generation.
        state["generation"] = state.get("generation", 0) + 1
        state["notebooks"] = copy.deepcopy(FIXTURE_NOTEBOOKS)
        state["papers"] = copy.deepcopy(FIXTURE_PAPERS)
        state["health"] = copy.deepcopy(FIXTURE_HEALTH)
        state["ingest"] = {}
        state["ingest_mode"] = "succeed"
        state["sse_enabled"] = True
        state["run_counter"] = 0
        # arx-b3 observability world: three rings with per-ring seq
        # counters (the a23 EventRing stamps seq + ts on append), the
        # session snapshot, and the A1-spine toggle (obs GETs 404).
        state["obs_enabled"] = True
        state["obs_rings"] = {"logs": [], "requests": [], "ingest": []}
        state["obs_seq"] = {"logs": 0, "requests": 0, "ingest": 0}
        state["obs_sessions"] = copy.deepcopy(FIXTURE_OBS_SESSIONS)
        # arx-b3 capability + graph worlds: operator-defined profiles
        # (the synthesized default is derived at read time, like the
        # real parse_profiles_document) and the graph serving mode.
        state["caps_enabled"] = True
        state["cap_profiles"] = copy.deepcopy(FIXTURE_CAP_PROFILES)
        state["graph_mode"] = "present"
        for i, rec in enumerate(copy.deepcopy(FIXTURE_OBS_LOGS)):
            _obs_append("logs", rec, ts=_OBS_T0 + 1 + i, publish=False)
        for i, rec in enumerate(copy.deepcopy(FIXTURE_OBS_REQUESTS)):
            _obs_append("requests", rec, ts=_OBS_T0 + 10 * (i + 1), publish=False)
        for i, rec in enumerate(copy.deepcopy(FIXTURE_OBS_INGEST)):
            _obs_append("ingest", rec, ts=_OBS_T0 + 100 + 10 * i, publish=False)

    def _obs_append(
        topic: str, event: dict, *, ts: float | None = None, publish: bool = True
    ) -> dict:
        """Ring append + SSE fan-out, the a23 EventRing/EventBus shape:
        the stored row and the bus frame both carry seq + ts."""
        state["obs_seq"][topic] += 1
        row = {
            **event,
            "seq": state["obs_seq"][topic],
            "ts": ts if ts is not None else round(_dt.datetime.now(_dt.UTC).timestamp(), 3),
        }
        state["obs_rings"][topic].append(row)
        if publish:
            for q in list(subscribers):
                q.put_nowait((topic, row))
        return row

    _reset_state()

    def _publish_ingest(event: dict) -> None:
        """arx-a23 frame shape (publish_ingest_stage_event): recorded in
        the ingest ring AND fanned out — the connections history and
        the b2 stepper read the same events."""
        _obs_append("ingest", event)

    async def _run_ingest_script(slug: str, run_id: int, generation: int) -> None:
        """Scripted stage sequence mirroring the a23 tracker's emission
        order for a notebook ingest run: preflight at trigger, then
        chunk/embed/index, then the terminal run pseudo-stage. The
        'fail' mode fails at embed with a stderr tail — the stepper's
        pinned-failure state."""
        delay = 0.15

        def alive() -> bool:
            row = state["ingest"].get(slug)
            return (
                state.get("generation") == generation
                and row is not None
                and row.get("run_id") == run_id
            )

        def stage(name: str, phase: str, detail: dict | None = None) -> None:
            event = {
                "kind": "ingest", "slug": slug, "stage": name,
                "phase": phase, "run_id": run_id,
            }
            if detail:
                event["detail"] = detail
            _publish_ingest(event)

        def run_log(level: str, name: str, message: str, event: str) -> None:
            # Merged-server truth: the a23 RingBufferLogHandler sits on
            # the ROOT logger, so the tracker/driver records emitted
            # during a run land in the log ring (post-redaction). The
            # scripted run mirrors that so the logs surface genuinely
            # shows the ingest's records (AC-B.20 step 4).
            _obs_append(
                "logs",
                {"level": level, "name": name, "message": message, "event": event},
            )

        run_log(
            "INFO", "server.ingest_tracker",
            f"ingest run {run_id} started for slug={slug}", "ingest_run",
        )
        stage("preflight", "finished")
        await asyncio.sleep(delay)
        if not alive():
            return
        stage("chunk", "started")
        await asyncio.sleep(delay)
        if not alive():
            return
        stage("chunk", "finished", {"papers_ok": 2, "derived": "run_summary"})
        stage("embed", "started")
        await asyncio.sleep(delay)
        if not alive():
            return
        row = state["ingest"][slug]
        if state["ingest_mode"] == "fail":
            stage("embed", "failed", {"error": "embedder exited 1"})
            row.update(
                status="failed",
                finished_at=_now_iso(),
                exit_code=1,
                stderr_tail=(
                    "RuntimeError: BGE-M3 embed batch failed\n"
                    "  at ingest/embedder.py:212 (paths redacted to var/arxmcp/)"
                ),
            )
            run_log(
                "ERROR", "server.ingest_tracker",
                f"ingest run {run_id} for slug={slug} failed: exit_code=1",
                "ingest_run",
            )
            stage("run", "failed")
            return
        stage("embed", "finished", {"derived": "run_summary"})
        stage("index", "started")
        await asyncio.sleep(delay)
        if not alive():
            return
        stage("index", "finished", {"corpus_version": 1691})
        # Wire truth: the m9 store persists INGEST_STATUS_SUCCESS =
        # "success" and api_v1 passes the column through verbatim. The
        # twin emits the REAL wire value so the browser suites exercise
        # the SPA's normalization seam (useIngestProgress maps it to
        # the canonical "succeeded").
        row.update(
            status="success", finished_at=_now_iso(), exit_code=0,
            stderr_tail=None,
        )
        run_log(
            "INFO", "server.ingest_tracker",
            f"ingest run {run_id} for slug={slug} finished: exit_code=0",
            "ingest_run",
        )
        # A successful run writes the marker: reflect it in /health so
        # the detail page's post-run reload shows an ok report.
        state["health"][slug] = {
            "format_version": 1,
            "slug": slug,
            "status": "ok",
            "marker_chunk_count": 2051,
            "actual_chunk_count": 2051,
            "marker_paper_count": len(state["papers"].get(slug, [])),
            "actual_paper_count": len(state["papers"].get(slug, [])),
            "drift": 0,
            "corpus_version": 1691,
            "detail": None,
            "marker_created_at": _now_iso(),
            "chunker_version": "2",
            "embedder_version": "bge-m3@567",
        }
        stage("run", "finished")

    def _find(slug: str) -> dict | None:
        for row in state["notebooks"]:
            if row["slug"] == slug:
                return row
        return None

    @app.post("/e2e/reset")
    async def e2e_reset() -> dict:
        _reset_state()
        return {"reset": True}

    @app.post("/e2e/ingest-mode")
    async def e2e_ingest_mode(request: Request) -> dict:
        """Script the NEXT run's outcome: {"mode": "succeed"|"fail"}."""
        body = await request.json()
        state["ingest_mode"] = str(body.get("mode", "succeed"))
        return {"ingest_mode": state["ingest_mode"]}

    @app.post("/e2e/sse-mode")
    async def e2e_sse_mode(request: Request) -> dict:
        """Toggle the SSE endpoint: {"enabled": false} makes
        /api/v1/events/stream 404 like the A1 spine, so the Playwright
        suite exercises the SPA's polling fallback for real."""
        body = await request.json()
        state["sse_enabled"] = bool(body.get("enabled", True))
        return {"sse_enabled": state["sse_enabled"]}

    # ------------------------------------------------------------------
    # arx-b3: scripted twins of the a23 observability read-APIs
    # (server/routes/observability.py — envelope + since_seq/level/slug
    # semantics mirrored; /e2e/obs-mode {enabled:false} = the A1 spine).
    # ------------------------------------------------------------------

    def _page_obs(
        items: list, limit: int, offset: int, since_seq: int | None = None
    ) -> dict:
        latest_seq = items[-1]["seq"] if items else 0
        if since_seq is not None:
            items = [e for e in items if e["seq"] > since_seq]
        newest_first = list(reversed(items))
        return {
            "format_version": 1,
            "items": newest_first[offset : offset + limit],
            "total": len(newest_first),
            "limit": limit,
            "offset": offset,
            "latest_seq": latest_seq,
        }

    def _obs_404() -> JSONResponse:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    @app.post("/e2e/obs-mode")
    async def e2e_obs_mode(request: Request) -> dict:
        """{"enabled": false} makes the four observability GETs 404
        like the A1 spine, so the honest degraded states are testable
        in a real browser."""
        body = await request.json()
        state["obs_enabled"] = bool(body.get("enabled", True))
        return {"obs_enabled": state["obs_enabled"]}

    @app.post("/e2e/obs-clear")
    async def e2e_obs_clear(request: Request) -> dict:
        """Empty an observability ring while leaving the GET routed and
        200 (obs_enabled stays true) — the traffic-less state, distinct
        from /e2e/obs-mode {enabled:false} (route-absent 404). Fuels the
        Requests ghost-lane teaching state so its AA contrast is
        axe-testable (the seeded fixture always has traffic). Body:
        {"topic": "logs"|"requests"|"ingest"} (default "requests")."""
        body = await request.json()
        topic = str(body.get("topic", "requests"))
        if topic not in ("logs", "requests", "ingest"):
            return JSONResponse(
                {"detail": f"topic {topic!r} not clearable"}, status_code=422
            )
        state["obs_rings"][topic] = []
        # Leave the seq counter alone: real rings never rewind seq.
        return {"topic": topic, "cleared": True}

    @app.post("/e2e/obs-emit", response_model=None)
    async def e2e_obs_emit(request: Request) -> dict | JSONResponse:
        """Script live traffic: {"topic": "logs"|"requests", "count": N}
        appends fresh scripted events (now-stamped) and fans them out
        over the SSE stream — the live-tail/pill Playwright fuel."""
        body = await request.json()
        topic = str(body.get("topic", "logs"))
        count = int(body.get("count", 1))
        if topic not in ("logs", "requests"):
            return JSONResponse(
                {"detail": f"topic {topic!r} not scriptable"}, status_code=422
            )
        emitted = []
        for _ in range(count):
            if topic == "logs":
                seq_next = state["obs_seq"]["logs"] + 1
                row = _obs_append(
                    "logs",
                    {
                        "level": "INFO",
                        "name": "server.e2e",
                        "message": f"live line {seq_next}",
                        "event": "live",
                        "tool": "find_equation",
                    },
                )
            else:
                row = _obs_append(
                    "requests",
                    {
                        "tool": "find_equation", "status": "ok",
                        "error_code": None,
                        "session_id": "a1b2c3d4e5f60718", "role": "fixer",
                        "profile": "default", "notebook": None,
                        "latency_ms": 12.0, "cache_layer": "tier1",
                        "result_bytes": 128, "k": 3, "corpus_version": 1690,
                    },
                )
            emitted.append(row["seq"])
        return {"topic": topic, "emitted": emitted}

    @app.post("/e2e/obs-gap")
    async def e2e_obs_gap(request: Request) -> dict:
        """Publish an explicit gap frame (the drop-oldest marker)."""
        body = await request.json()
        dropped = int(body.get("dropped", 1))
        for q in list(subscribers):
            q.put_nowait(("gap", {"dropped": dropped}))
        return {"dropped": dropped}

    @app.get("/api/v1/requests", response_model=None)
    async def obs_requests(
        limit: int = 100, offset: int = 0, since_seq: int | None = None
    ) -> dict | JSONResponse:
        if not state["obs_enabled"]:
            return _obs_404()
        return _page_obs(state["obs_rings"]["requests"], limit, offset, since_seq)

    @app.get("/api/v1/logs/tail", response_model=None)
    async def obs_logs_tail(
        limit: int = 100,
        offset: int = 0,
        since_seq: int | None = None,
        level: str | None = None,
    ) -> dict | JSONResponse:
        if not state["obs_enabled"]:
            return _obs_404()
        items = state["obs_rings"]["logs"]
        if level is not None:
            wanted = level.strip().upper()
            items = [e for e in items if str(e.get("level", "")).upper() == wanted]
        return _page_obs(items, limit, offset, since_seq)

    @app.get("/api/v1/sessions", response_model=None)
    async def obs_sessions(
        limit: int = 100, offset: int = 0
    ) -> dict | JSONResponse:
        if not state["obs_enabled"]:
            return _obs_404()
        rows = state["obs_sessions"]
        return {
            "format_version": 1,
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/v1/ingest-events", response_model=None)
    async def obs_ingest_events(
        limit: int = 100,
        offset: int = 0,
        since_seq: int | None = None,
        slug: str | None = None,
    ) -> dict | JSONResponse:
        if not state["obs_enabled"]:
            return _obs_404()
        items = state["obs_rings"]["ingest"]
        if slug is not None:
            items = [e for e in items if e.get("slug") == slug]
        return _page_obs(items, limit, offset, since_seq)

    # ------------------------------------------------------------------
    # arx-b3: scripted twin of the a23 capability-profile CRUD
    # (server/routes/capabilities.py — parsed view incl. synthesized
    # default, AC-A.10 raw-token 422, named domain 404s; /e2e/caps-mode
    # {enabled:false} = the A1 spine's route-absent 404).
    # ------------------------------------------------------------------

    def _caps_404() -> JSONResponse:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    def _cap_effective_rows() -> list[dict]:
        profiles = dict(state["cap_profiles"])
        if "default" not in profiles:
            # The synthesized permissive default (day-one behavior).
            profiles["default"] = {"enabled": True}
        rows = []
        for name in sorted(profiles):
            p = profiles[name]
            tools = p.get("tools")
            notebooks = p.get("notebooks")
            rows.append(
                {
                    "name": name,
                    "enabled": bool(p.get("enabled", True)),
                    "token_sha256": p.get("token_sha256"),
                    "tools": sorted(tools["allow"]) if tools else None,
                    "caps": dict(sorted(p.get("caps", {}).items())),
                    "notebooks": (
                        sorted(notebooks["allow"]) if notebooks else None
                    ),
                }
            )
        return rows

    @app.post("/e2e/caps-mode")
    async def e2e_caps_mode(request: Request) -> dict:
        body = await request.json()
        state["caps_enabled"] = bool(body.get("enabled", True))
        return {"caps_enabled": state["caps_enabled"]}

    @app.get("/api/v1/capabilities/profiles", response_model=None)
    async def caps_list() -> dict | JSONResponse:
        if not state["caps_enabled"]:
            return _caps_404()
        rows = _cap_effective_rows()
        return {"format_version": 1, "items": rows, "total": len(rows)}

    @app.put("/api/v1/capabilities/profiles/{name}", response_model=None)
    async def caps_upsert(name: str, request: Request) -> dict | JSONResponse:
        if not state["caps_enabled"]:
            return _caps_404()
        if not _CAP_NAME_RE.match(name):
            return JSONResponse(
                {
                    "detail": (
                        f"profile name {name!r} is invalid (want "
                        f"^[a-z][a-z0-9-]{{0,63}}$)"
                    )
                },
                status_code=422,
            )
        body = await request.json()
        extra = set(body) - _CAP_PUT_FIELDS
        if extra:
            # extra="forbid" — the AC-A.10 raw-token tripwire.
            return JSONResponse(
                {
                    "detail": [
                        {"msg": "Extra inputs are not permitted", "loc": ["body", f]}
                        for f in sorted(extra)
                    ]
                },
                status_code=422,
            )
        token = body.get("token_sha256")
        if token is not None and not _CAP_TOKEN_RE.match(str(token).lower()):
            return JSONResponse(
                {
                    "detail": (
                        "token_sha256 must be a 64-char lowercase hex SHA-256 "
                        "digest of the token — never the token value itself"
                    )
                },
                status_code=422,
            )
        caps = body.get("caps")
        if caps is not None:
            for tool, cap in caps.items():
                if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
                    return JSONResponse(
                        {
                            "detail": (
                                f"cap for tool {tool!r} must be a "
                                f"non-negative integer"
                            )
                        },
                        status_code=422,
                    )
        entry: dict = {"enabled": bool(body.get("enabled", True))}
        if token is not None:
            entry["token_sha256"] = str(token).lower()
        if body.get("tools") is not None:
            entry["tools"] = {"allow": sorted(body["tools"])}
        if caps is not None:
            entry["caps"] = dict(sorted(caps.items()))
        if body.get("notebooks") is not None:
            entry["notebooks"] = {"allow": sorted(body["notebooks"])}
        state["cap_profiles"][name] = entry
        return {"format_version": 1, "name": name, "result": "upserted"}

    @app.delete(
        "/api/v1/capabilities/profiles/{name}",
        status_code=204,
        response_model=None,
    )
    async def caps_delete(name: str) -> None | JSONResponse:
        if not state["caps_enabled"]:
            return _caps_404()
        if name not in state["cap_profiles"]:
            return JSONResponse(
                {"detail": f"profile {name!r} not found"}, status_code=404
            )
        del state["cap_profiles"][name]
        return None

    # ------------------------------------------------------------------
    # arx-b3: scripted twin of the a45 REST citation-graph endpoint
    # (api_v1.graph_neighbors_v1 — envelope, ordering and degradation
    # mirrored; /e2e/graph-mode scripts present/absent/unavailable/off,
    # off = the A1 spine's route-absent 404).
    # ------------------------------------------------------------------

    @app.post("/e2e/graph-mode", response_model=None)
    async def e2e_graph_mode(request: Request) -> dict | JSONResponse:
        body = await request.json()
        mode = str(body.get("mode", "present"))
        if mode not in ("present", "absent", "unavailable", "off"):
            return JSONResponse(
                {"detail": f"mode {mode!r} not scriptable"}, status_code=422
            )
        state["graph_mode"] = mode
        return {"graph_mode": mode}

    @app.get(
        "/api/v1/notebooks/{slug}/graph/neighbors", response_model=None
    )
    async def graph_neighbors(
        slug: str,
        paper_id: str,
        direction: str = "cites",
        depth: int = 2,
        limit: int = 30,
    ) -> dict | JSONResponse:
        if state["graph_mode"] == "off":
            # Route-absent: FastAPI's default body, byte-for-byte.
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if _find(slug) is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        if not _is_arxiv_id(paper_id):
            return JSONResponse(
                {
                    "detail": (
                        f"paper_id {paper_id!r} does not match the arXiv id "
                        f"format"
                    )
                },
                status_code=422,
            )
        if direction not in FIXTURE_GRAPH:
            return JSONResponse(
                {"detail": f"direction {direction!r} invalid"}, status_code=422
            )

        neighbors: list[dict] = []
        if state["graph_mode"] == "present":
            adjacency = FIXTURE_GRAPH[direction]
            seen: dict[str, dict] = {}
            for nid, chunk in adjacency.get(paper_id, []):
                seen[nid] = {
                    "chunk_id": chunk,
                    "paper_id": nid,
                    "edge_kind": direction,
                    "hop_distance": 1,
                    "source": "openAlex",
                    "confidence": 1.0,
                }
            if depth >= 2:
                for nid in list(seen):
                    for nid2, chunk2 in adjacency.get(nid, []):
                        if nid2 == paper_id or nid2 in seen:
                            continue
                        seen[nid2] = {
                            "chunk_id": chunk2,
                            "paper_id": nid2,
                            "edge_kind": direction,
                            "hop_distance": 2,
                            "source": "openAlex",
                            "confidence": 1.0,
                        }
            neighbors = sorted(
                seen.values(),
                key=lambda r: (r["hop_distance"], r["paper_id"]),
            )[:limit]

        return {
            "format_version": 1,
            "slug": slug,
            "paper_id": paper_id,
            "direction": direction,
            "depth": depth,
            "limit": limit,
            "graph_status": (
                "present" if state["graph_mode"] == "present"
                else state["graph_mode"]
            ),
            "neighbors": neighbors,
        }

    @app.get("/api/v1/notebooks")
    async def list_notebooks(limit: int = 50, offset: int = 0) -> dict:
        return _page(state["notebooks"], limit, offset)

    @app.post("/api/v1/notebooks", status_code=201, response_model=None)
    async def create_notebook(request: Request) -> dict | JSONResponse:
        body = await request.json()
        slug = str(body.get("slug", ""))
        if _find(slug) is not None:
            return JSONResponse(
                {"detail": f"notebook slug {slug!r} already exists"},
                status_code=409,
            )
        row = {
            "slug": slug,
            "display_name": str(body.get("display_name", "")),
            "lancedb_path": f"var/arxmcp/notebooks/{slug}/lancedb",
            "created_at": "2026-07-04T12:00:00+00:00",
            "notebook_kind": str(body.get("notebook_kind", "arxiv")),
            "parse_status": "skipped",
            "parse_error": None,
            "parsed_html_path": None,
            "discovery_category": None,
            "description": None,
        }
        state["notebooks"].insert(0, row)  # created_at DESC ordering
        state["papers"][slug] = []
        return {"format_version": 1, **row}

    @app.patch("/api/v1/notebooks/{slug}", response_model=None)
    async def rename_notebook(slug: str, request: Request) -> dict | JSONResponse:
        row = _find(slug)
        if row is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        body = await request.json()
        row["display_name"] = str(body.get("display_name", ""))
        return {
            "format_version": 1,
            "slug": slug,
            "display_name": row["display_name"],
        }

    @app.delete("/api/v1/notebooks/{slug}", status_code=204, response_model=None)
    async def delete_notebook(slug: str) -> None | JSONResponse:
        row = _find(slug)
        if row is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        state["notebooks"].remove(row)
        return None

    @app.patch("/api/v1/notebooks/{slug}/topic", response_model=None)
    async def update_topic(slug: str, request: Request) -> dict | JSONResponse:
        row = _find(slug)
        if row is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        body = await request.json()
        row["discovery_category"] = str(body.get("discovery_category", ""))
        row["description"] = str(body.get("description", ""))
        return {
            "format_version": 1,
            "slug": slug,
            "discovery_category": row["discovery_category"],
            "description": row["description"],
        }

    @app.post("/api/v1/notebooks/{slug}/discover", response_model=None)
    async def discover(slug: str) -> dict | JSONResponse:
        row = _find(slug)
        if row is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        if not row.get("discovery_category"):
            return JSONResponse(
                {
                    "detail": (
                        f"notebook {slug!r} has no discovery_category configured"
                    )
                },
                status_code=422,
            )
        return {
            "format_version": 1,
            "slug": slug,
            "candidates": FIXTURE_DISCOVER,
            "count": len(FIXTURE_DISCOVER),
        }

    @app.post(
        "/api/v1/notebooks/{slug}/papers", status_code=201, response_model=None
    )
    async def add_paper(slug: str, request: Request) -> dict | JSONResponse:
        rows = state["papers"].get(slug)
        if rows is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        body = await request.json()
        url = str(body.get("arxiv_url", ""))
        paper_id = _e2e_arxiv_url_to_paper_id(url)
        if paper_id is None:
            # Verbatim-shaped 422 from the real A1-spine handler — the
            # SPA's native-HTML degrade path keys on this status.
            return JSONResponse(
                {
                    "detail": (
                        f"arxiv_url {url!r} did not match an accepted form "
                        f"(expected: https://arxiv.org/abs/<paper_id>)"
                    )
                },
                status_code=422,
            )
        if any(p["paper_id"] == paper_id for p in rows):
            return JSONResponse(
                {"detail": f"paper {paper_id!r} already in notebook {slug!r}"},
                status_code=409,
            )
        rows.insert(0, {"paper_id": paper_id, "added_at": "2026-07-04T12:01:00+00:00"})
        return {"format_version": 1, "slug": slug, "paper_id": paper_id}

    @app.post(
        "/api/v1/notebooks/{slug}/papers/upload",
        status_code=201,
        response_model=None,
    )
    async def upload_paper(
        slug: str,
        paper_id: str = Form(...),  # noqa: B008  (FastAPI DI pattern)
        file: UploadFile = File(...),  # noqa: B008  (FastAPI DI pattern)
    ) -> JSONResponse:
        """Mirrors api_v1.upload_paper_v1: 201 created / 200
        updated_existing; 422 on empty or (arxiv-kind) non-HTML bytes."""
        nb = _find(slug)
        rows = state["papers"].get(slug)
        if nb is None or rows is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        content = await file.read()
        if not content:
            return JSONResponse(
                {"detail": "uploaded file is empty"}, status_code=422
            )
        is_textbook = nb["notebook_kind"] == "textbook"
        if is_textbook:
            if not content.startswith(b"%PDF-"):
                return JSONResponse(
                    {"detail": "PDF preflight rejected: not a PDF"},
                    status_code=415,
                )
        elif not content[:16].startswith((b"<!", b"<h")):
            return JSONResponse(
                {
                    "detail": (
                        "uploaded file does not appear to be HTML (first 16 "
                        "bytes must start with '<!' or '<h')"
                    )
                },
                status_code=422,
            )
        existing = any(p["paper_id"] == paper_id for p in rows)
        if not existing:
            rows.insert(0, {"paper_id": paper_id, "added_at": _now_iso()})
        # Mirrors the real handler's INFO record (notebooks.py "uploaded
        # %s: slug=%s paper_id=%s bytes=%d"), which the a23 root-logger
        # ring handler captures — the logs surface shows the upload.
        _obs_append(
            "logs",
            {
                "level": "INFO", "name": "server.routes.notebooks",
                "message": (
                    f"uploaded ar5iv HTML: slug={slug} "
                    f"paper_id={paper_id} bytes={len(content)}"
                ),
                "event": "upload",
            },
        )
        return JSONResponse(
            status_code=200 if existing else 201,
            content={
                "format_version": 1,
                "slug": slug,
                "paper_id": paper_id,
                "result": "updated_existing" if existing else "created",
            },
        )

    @app.post(
        "/api/v1/notebooks/{slug}/ingest", status_code=202, response_model=None
    )
    async def trigger_ingest(slug: str) -> dict | JSONResponse:
        if _find(slug) is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        row = state["ingest"].get(slug)
        if row is not None and row["status"] == "running":
            return JSONResponse(
                {
                    "detail": (
                        f"an ingest is already in flight for notebook "
                        f"{slug!r} — wait for it to finish before "
                        f"triggering another"
                    )
                },
                status_code=409,
            )
        state["run_counter"] += 1
        run_id = state["run_counter"]
        started_at = _now_iso()
        state["ingest"][slug] = {
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
            "finished_at": None,
            "exit_code": None,
            "stderr_tail": None,
        }
        # Mirrors the uvicorn.access record the a23 root-logger ring
        # handler captures for the trigger request itself — the logs
        # surface shows the ingest's own HTTP request (AC-B.20 step 4).
        _obs_append(
            "logs",
            {
                "level": "INFO", "name": "uvicorn.access",
                "message": (
                    f'127.0.0.1 - "POST /api/v1/notebooks/{slug}/ingest '
                    f'HTTP/1.1" 202'
                ),
                "event": "http_request",
            },
        )
        asyncio.get_running_loop().create_task(
            _run_ingest_script(slug, run_id, state["generation"])
        )
        return {
            "format_version": 1,
            "slug": slug,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        }

    @app.get("/api/v1/notebooks/{slug}/ingest/latest", response_model=None)
    async def latest_ingest(slug: str) -> dict | JSONResponse:
        if _find(slug) is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        row = state["ingest"].get(slug)
        if row is None:
            return {
                "format_version": 1, "slug": slug,
                "status": "none", "terminal": False,
            }
        return {
            "format_version": 1,
            "slug": slug,
            **row,
            "terminal": row["status"] != "running",
        }

    @app.get("/api/v1/events/stream")
    async def events_stream(topics: str = "ingest"):
        """Scripted twin of the arx-a23 multiplexed SSE endpoint (IF-2):
        `ready` frame with cursors, `event: <topic>` frames, keepalive
        comments. /e2e/sse-mode {enabled:false} turns it into the A1
        spine's 404 so the poll fallback is testable."""
        if not state["sse_enabled"]:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        queue: asyncio.Queue = asyncio.Queue()
        subscribers.add(queue)

        def frame(event_name: str, payload: dict) -> str:
            return (
                f"event: {event_name}\n"
                f"data: {json.dumps(payload, sort_keys=True, default=str)}\n\n"
            )

        async def gen():
            try:
                yield frame(
                    "ready",
                    {
                        "topics": sorted(
                            t.strip() for t in topics.split(",") if t.strip()
                        ),
                        "cursors": {
                            "requests": state["obs_seq"]["requests"],
                            "logs": state["obs_seq"]["logs"],
                            "ingest": state["obs_seq"]["ingest"],
                        },
                    },
                )
                while True:
                    try:
                        topic, payload = await asyncio.wait_for(
                            queue.get(), timeout=5.0
                        )
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield frame(topic, payload)
            finally:
                subscribers.discard(queue)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.delete(
        "/api/v1/notebooks/{slug}/papers/{paper_id:path}",
        status_code=204,
        response_model=None,
    )
    async def remove_paper(slug: str, paper_id: str) -> None | JSONResponse:
        rows = state["papers"].get(slug, [])
        for p in rows:
            if p["paper_id"] == paper_id:
                rows.remove(p)
                return None
        return JSONResponse(
            {"detail": f"paper {paper_id!r} not in notebook"}, status_code=404
        )

    @app.post("/api/v1/notebooks/{slug}/reconcile-marker", response_model=None)
    async def reconcile_marker(slug: str) -> dict | JSONResponse:
        health = state["health"].get(slug)
        if health is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not registered"}, status_code=404
            )
        before = {
            "chunk_count": health["marker_chunk_count"],
            "paper_count": health["marker_paper_count"],
        }
        health["marker_chunk_count"] = health["actual_chunk_count"]
        health["marker_paper_count"] = health["actual_paper_count"]
        health["drift"] = 0
        health["status"] = "ok"
        health["detail"] = None
        return {
            "format_version": 1,
            "slug": slug,
            "before": before,
            "after": {
                "chunk_count": health["marker_chunk_count"],
                "paper_count": health["marker_paper_count"],
            },
            "drift_resolved": health["marker_chunk_count"] - before["chunk_count"],
        }

    @app.get("/api/v1/notebooks/{slug}/health", response_model=None)
    async def notebook_health(slug: str) -> dict | JSONResponse:
        body = state["health"].get(slug)
        if body is None:
            if _find(slug) is not None:
                # Registered but never ingested (e.g. just created in a
                # flows test) — the real handler's no_marker shape.
                return {
                    "format_version": 1,
                    "slug": slug,
                    "status": "no_marker",
                    "marker_chunk_count": None,
                    "actual_chunk_count": None,
                    "marker_paper_count": None,
                    "actual_paper_count": None,
                    "drift": None,
                    "corpus_version": None,
                    "detail": "no corpus-version.json; run `make ingest` first",
                }
            return JSONResponse(
                {"detail": f"notebook {slug!r} not registered"}, status_code=404
            )
        return body

    @app.get("/api/v1/notebooks/{slug}/papers", response_model=None)
    async def list_papers(
        slug: str, limit: int = 100, offset: int = 0
    ) -> dict | JSONResponse:
        rows = state["papers"].get(slug)
        if rows is None:
            return JSONResponse(
                {"detail": f"notebook {slug!r} not found"}, status_code=404
            )
        return _page(rows, limit, offset)

    @app.get("/status")
    async def status() -> dict:
        return {"status": "ready", "corpus_version": 1690}

    @app.get("/spike/mathml")
    async def mathml_fixture() -> HTMLResponse:
        fixture = REPO_ROOT / "frontend-app" / "e2e" / "fixtures" / "mathml.html"
        resp = HTMLResponse(fixture.read_text(encoding="utf-8"))
        resp.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY_PREVIEW.decode()
        return resp

    @app.get("/spike/mathml-real", response_model=None)
    async def mathml_real() -> HTMLResponse | JSONResponse:
        for candidate in _REAL_AR5IV_CANDIDATES:
            if candidate.is_file():
                resp = HTMLResponse(candidate.read_text(encoding="utf-8", errors="replace"))
                resp.headers["Content-Security-Policy"] = (
                    CONTENT_SECURITY_POLICY_PREVIEW.decode()
                )
                return resp
        return JSONResponse({"error": "no stored ar5iv sample on this machine"}, status_code=404)

    if not mount_frontend_app(app):
        raise RuntimeError("frontend-app/dist missing - build before running e2e")
    return app


if __name__ == "__main__":
    port = 7799
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    uvicorn.run(create_e2e_app(), host="127.0.0.1", port=port, log_level="warning")

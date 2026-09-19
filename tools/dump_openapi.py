"""Offline OpenAPI dump for the ``/api/v1`` operator surface (stage2/arx-a1).

Interface Artifact **IF-1** (workstreams.md §4): generates
``openapi.json`` at the repo root as a BUILD-TIME artifact so WS-B's
typed client (``@hey-api/openapi-ts``) can be generated from a file —
no live server needed. The runtime schema endpoints stay disabled
(``openapi_url=None`` in ``server/main.py::create_app`` — Threat 4
surface reduction); this dump is the ONLY sanctioned way to obtain the
schema, and it never ships over HTTP.

Scope: the operator JSON plane only —

- ``/healthz`` / ``/readyz`` / ``/status`` (probe surface)
- ``/api/v1/*`` (the 17 JSON-only notebook-route aliases)
- ``/bridge/contracts`` (the contract-registry handshake)

The legacy ``/ui/api`` htmx surface and the ``/mcp`` agent plane are
deliberately EXCLUDED: the former is retiring (strangler pattern), the
latter has its own byte-stable contract (``tools/list`` + BP1 hashes).

Determinism: the document is assembled from a fresh FastAPI app built
purely from the routers (no env, no ``Config()``, no lifespan, no model
loads) and serialized with ``sort_keys=True`` — two consecutive runs
produce byte-identical output (AC-A.2; pinned by
``tests/test_openapi_dump.py``, which also fails when the committed
file is stale).

Usage::

    python -m tools.dump_openapi          # writes ./openapi.json
    python -m tools.dump_openapi --check  # exit 1 if the committed file is stale
    make openapi                          # Makefile alias

"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Output path — repo root. The doc-placement rule (CLAUDE.md §1)
#: restricts root MARKDOWN files; openapi.json is a build artifact
#: named by the Stage-1 contract (workstreams.md IF-1).
OPENAPI_PATH = REPO_ROOT / "openapi.json"

#: Static metadata. Version tracks the /api/v1 response
#: ``format_version`` (MAJOR only — the path prefix carries the API
#: major version; see server/routes/api_v1.py).
_TITLE = "arXMCP operator API"
_VERSION = "1.0.0"
_DESCRIPTION = (
    "JSON-only operator surface of the arXMCP server: /api/v1 notebook "
    "management aliases, health/readiness/status probes, and the "
    "/bridge/contracts handshake. Generated OFFLINE by "
    "tools/dump_openapi.py (IF-1); the runtime openapi_url is disabled "
    "by design (Threat 4)."
)


def build_openapi_document() -> dict:
    """Assemble the OpenAPI document from the operator-plane routers.

    Builds a fresh, minimal FastAPI app (routers only — none of the
    security middleware affects the schema) so the dump is fully
    deterministic and independent of the caller's environment. The
    router set and prefixes MUST mirror ``server/main.py::create_app``;
    ``tests/test_openapi_dump.py`` pins the /api/v1 path inventory
    against the live app factory to catch drift.
    """
    from fastapi import FastAPI  # noqa: PLC0415 — import under call so --help stays fast

    from server.health import router as health_router  # noqa: PLC0415
    from server.routes.api_v1 import router as api_v1_router  # noqa: PLC0415
    from server.routes.bridge import router as bridge_router  # noqa: PLC0415
    from server.routes.capabilities import (  # noqa: PLC0415
        router as capabilities_router,
    )
    from server.routes.observability import (  # noqa: PLC0415
        router as observability_router,
    )

    app = FastAPI(title=_TITLE, version=_VERSION, description=_DESCRIPTION)
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix="/api/v1")
    # stage2/arx-a23: observability read-APIs + capability CRUD join
    # the operator plane (same mount shape as server/main.py).
    app.include_router(observability_router, prefix="/api/v1")
    app.include_router(capabilities_router, prefix="/api/v1")
    app.include_router(bridge_router, prefix="/bridge")

    schema = app.openapi()
    # Loopback server entry — informational for generated clients.
    schema["servers"] = [{"url": "http://127.0.0.1:7733"}]
    return schema


def render_openapi_bytes() -> bytes:
    """Serialize deterministically: sorted keys, 2-space indent,
    ASCII-safe, trailing newline."""
    doc = build_openapi_document()
    return (
        json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in args

    rendered = render_openapi_bytes()

    if check_only:
        if not OPENAPI_PATH.is_file():
            sys.stderr.write(
                f"openapi.json missing at {OPENAPI_PATH}; run "
                f"`python -m tools.dump_openapi`\n"
            )
            return 1
        committed = OPENAPI_PATH.read_bytes()
        if committed != rendered:
            sys.stderr.write(
                "openapi.json is STALE (the /api/v1 surface changed); "
                "regenerate with `python -m tools.dump_openapi` and "
                "commit the result\n"
            )
            return 1
        sys.stdout.write("openapi.json is current\n")
        return 0

    OPENAPI_PATH.write_bytes(rendered)
    sys.stdout.write(
        f"wrote {OPENAPI_PATH} ({len(rendered)} bytes, "
        f"{len(build_openapi_document().get('paths', {}))} paths)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Notebooks as MCP **resources** (notebook-surface-expansion-m4).

A pipeline agent (sketcher → autoformalizer → tactician → fixer) discovers the
available notebook corpora via the MCP ``resources/list`` + ``resources/read``
surface — at ZERO BP1 cost, because resources are a SEPARATE JSON-RPC method from
``tools/list`` and never enter the frozen tool-schema / BP1 prompt-cache prefix
(proven byte-identical by ``notebook-surface-expansion-spike-1``).

Two resources are registered (see :func:`register_resources`):

- ``arxmcp://notebooks`` — a **concrete** index resource; ``resources/read``
  returns ``{count, notebooks: [{slug, display_name, uri}, …]}`` (enumeration).
- ``arxmcp://notebooks/{slug}`` — a **template**; ``resources/read`` returns ONE
  notebook's METADATA (NO chunk content, NO LanceDB query).

This surface is **read-only** — notebook mutation stays on the ``/ui/api`` REST
surface (the MCP notebook-mutation-tools path is on the project's Won't list).

Security (security-reviewer lens; ``08-security-observability-ops.md``):

- ``validate_slug`` is the FIRST call in the per-slug path — a ``resources/read``
  is an unauthenticated MCP call, so the slug is treated as hostile (the regex
  allowlist rejects ``../``, decoded/encoded slashes, uppercase, shell metachars)
  BEFORE any store / filesystem access.
- Operator-authored text (``display_name`` / ``slug``) flows to an agent, so the
  JSON payload is wrapped in ``<retrieved_notebook>…</retrieved_notebook>`` via
  :func:`server.tools.wrap_retrieved_text` (Threat 2 — content inside the tag is
  DATA, not instructions).
- The absolute ``lancedb_path`` is NOT exposed (host-path info-leak); a derived
  ``is_ingested`` boolean conveys ingestion state without leaking the path.

The store is reached via a module-level reference (resource callbacks get no
FastAPI request / DI), mirroring ``server.tools.set_resources``. FastMCP is
mounted in the SAME uvicorn event loop, so the store's ``asyncio.to_thread``
methods are safe to await from a callback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server import corpus_manifest
from server.tools import ResourcesNotReadyError, get_resources, wrap_retrieved_text
from tools._notebook_common import NotebookError, notebook_dir, validate_slug

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.application_paths import ApplicationPaths
    from server.notebooks_store import NotebooksStore

logger = logging.getLogger(__name__)

#: Resource URIs (RFC3986 custom scheme ``arxmcp://``).
NOTEBOOKS_INDEX_URI = "arxmcp://notebooks"
NOTEBOOK_TEMPLATE_URI = "arxmcp://notebooks/{slug}"
#: source-truth-m3: a THIRD concrete resource (not a template) — the
#: content-addressed corpus provenance manifest, generated on-read.
CORPUS_MANIFEST_URI = "arxmcp://corpus-manifest"

#: Module-level live store (set by the lifespan via :func:`set_notebooks_store`,
#: mirroring ``server.tools.set_resources``). ``None`` until startup wires it.
_notebooks_store: NotebooksStore | None = None


def set_notebooks_store(store: NotebooksStore) -> None:
    """Wire the live :class:`NotebooksStore` for the resource callbacks.

    Called from the FastAPI lifespan right after the store opens — the same
    discipline as ``server.tools.set_resources``.
    """
    global _notebooks_store  # noqa: PLW0603  (module-singleton wiring, mirrors set_resources)
    _notebooks_store = store


def reset_notebooks_store_for_tests() -> None:
    """Drop the module store reference (test isolation)."""
    global _notebooks_store  # noqa: PLW0603
    _notebooks_store = None


def _require_store() -> NotebooksStore:
    if _notebooks_store is None:
        # Pathological: a resources/read before the lifespan wires the store.
        # `assert` is project-banned (CLAUDE.md 4.7) — raise instead.
        raise NotebookError("notebooks store not ready")
    return _notebooks_store


def _configured_application_paths() -> ApplicationPaths | None:
    """Return the live Config layout; permit isolated callback unit tests."""
    try:
        paths = get_resources().config.application_paths
    except ResourcesNotReadyError:
        return None
    store_path = getattr(_notebooks_store, "_db_path", None)
    if store_path is not None and Path(store_path).resolve() != (
        paths.notebooks_db.resolve()
    ):
        # A separately mounted resource callback (notably an isolated test)
        # must not inherit an unrelated process-global Resources instance.
        return None
    return paths


def _wrap_json(payload: dict[str, Any], *, kind: str = "notebook") -> str:
    """Canonical-JSON the payload and wrap it as untrusted retrieved data.

    ``kind`` selects the delimiter tag (``"notebook"`` -> the two
    notebook resources; ``"manifest"`` -> ``arxmcp://corpus-manifest``,
    source-truth-m3). This outer wire serialization (``ensure_ascii=False``)
    is a SEPARATE pass from the ``content_hash`` canonicalization the
    manifest computes over ``snapshot`` alone — the two are unrelated and
    need not match (the hash is fixed the moment ``snapshot`` is fixed).
    """
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return wrap_retrieved_text(text, kind=kind)


async def _notebook_metadata(slug: str) -> dict[str, Any]:
    """Build one notebook's read payload. ``validate_slug`` FIRST.

    Raises :class:`NotebookError` on a malformed/traversal slug (before any
    store/FS access) OR on an unknown slug (resource not found). FastMCP
    surfaces the raised error to the client.
    """
    validate_slug(slug)  # path-traversal guard — MUST be first
    store = _require_store()
    notebook = await store.get_notebook(slug)
    if notebook is None:
        raise NotebookError(f"notebook {slug!r} not found")
    papers = await store.list_papers(slug)
    paths = _configured_application_paths()
    # is_ingested: does the on-disk LanceDB dir exist? Conveys ingestion state
    # WITHOUT leaking the absolute lancedb_path (m4 synthesis D3). notebook_dir
    # runs the m6 symlink-containment check; treat any rejection as "not
    # ingested" rather than leaking the failure to the agent.
    try:
        is_ingested = (
            notebook_dir(
                slug, base=paths.notebooks if paths is not None else None
            ) / "lancedb"
        ).is_dir()
    except NotebookError:
        # m4-rect F2: a containment/symlink rejection here (m6 F3 hardening) is
        # a security signal — an out-of-band tamper at var/arxmcp/notebooks/<slug>.
        # Surface it server-side at WARNING (slug is validate_slug'd, so safe to
        # log) but still return is_ingested=False to the agent (do NOT leak the
        # resolved path / failure detail — m10 F5 side-channel discipline).
        logger.warning(
            "notebook %r: lancedb-dir containment check rejected "
            "(possible symlink tamper); reporting is_ingested=False",
            slug,
        )
        is_ingested = False
    # m4-rect F4: this return dict is an EXPLICIT ALLOWLIST (allowlist-by-
    # projection). The store row also carries lancedb_path / parse_error /
    # parsed_html_path — those MUST NEVER be added here (lancedb_path is an
    # absolute host path = info-leak, D3; the others are internal ops state).
    return {
        "slug": notebook["slug"],
        "display_name": notebook.get("display_name", ""),
        "notebook_kind": notebook.get("notebook_kind", "arxiv"),
        "created_at": notebook.get("created_at", ""),
        "parse_status": notebook.get("parse_status", ""),
        "paper_count": len(papers),
        "is_ingested": is_ingested,
    }


def register_resources(mcp_server: FastMCP) -> None:
    """Register the notebook MCP resources on ``mcp_server``.

    MUST be called AFTER ``register_all_tools`` and BEFORE ``mount_mcp`` in
    ``server.main.create_app`` (the same snapshot-at-mount constraint as tools).
    Registers NO tools — the frozen tool surface + ``tools/list`` bytes + the
    BP1/BP2 prompt-cache hashes are untouched (the guard test pins this).
    """

    @mcp_server.resource(
        NOTEBOOKS_INDEX_URI,
        name="notebooks",
        description=(
            "Index of all notebooks (corpora) available on this arXMCP server. "
            "resources/read returns {count, notebooks:[{slug, display_name, "
            "uri}]}. Read a per-notebook arxmcp://notebooks/<slug> for metadata."
        ),
        mime_type="text/plain",
    )
    async def _notebooks_index() -> str:
        store = _require_store()
        rows = await store.list_notebooks()
        listing = {
            "count": len(rows),
            "notebooks": [
                {
                    "slug": row["slug"],
                    "display_name": row.get("display_name", ""),
                    "uri": f"arxmcp://notebooks/{row['slug']}",
                }
                for row in rows
            ],
        }
        return _wrap_json(listing)

    @mcp_server.resource(
        NOTEBOOK_TEMPLATE_URI,
        name="notebook",
        description=(
            "Metadata for one notebook: slug, display_name, notebook_kind, "
            "created_at, parse_status, paper_count, is_ingested. Read-only; "
            "no chunk content. Notebook mutation lives on the /ui/api surface."
        ),
        mime_type="text/plain",
    )
    async def _notebook_detail(slug: str) -> str:
        return _wrap_json(await _notebook_metadata(slug))

    @mcp_server.resource(
        CORPUS_MANIFEST_URI,
        name="corpus-manifest",
        description=(
            "Content-addressed provenance manifest of every notebook's "
            "corpus state: per-revision raw-source + parse-artifact "
            "checksums, license status, active/withdrawn/superseded status, a "
            "3-way license census, the corpus-version epoch + chunker/embedder "
            "stamps, a revisions rollup digest, and the operator "
            "license-unknown override flag. resources/read returns "
            "{manifest_version, generated_at, content_hash, "
            "snapshot:{notebooks:{<slug>}}}; content_hash is sha256 over the "
            "snapshot alone. Read-only; generated on-read (no persisted file)."
        ),
        mime_type="text/plain",
    )
    async def _corpus_manifest() -> str:
        # build_manifest reaches the SAME module store the two notebook
        # resources use; base + settings-db paths default to production
        # (var/arxmcp/…). The payload is wrapped as <retrieved_manifest>
        # (Threat 2); the three operator-authored fields (override.set_by /
        # set_at / note) are all neutralized by the payload-wide
        # escape-on-emit (and str-coerced in _read_override).
        paths = _configured_application_paths()
        payload = await corpus_manifest.build_manifest(
            _require_store(),
            base=paths.notebooks if paths is not None else None,
            settings_db_path=(
                paths.notebooks_db if paths is not None else None
            ),
        )
        return _wrap_json(payload, kind="manifest")


__all__ = [
    "CORPUS_MANIFEST_URI",
    "NOTEBOOKS_INDEX_URI",
    "NOTEBOOK_TEMPLATE_URI",
    "register_resources",
    "reset_notebooks_store_for_tests",
    "set_notebooks_store",
]

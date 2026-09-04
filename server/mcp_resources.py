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
from datetime import UTC, datetime
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
#: contract-v1 (derived-alg-geo-lean #175): the pinned formalization a notebook
#: serves, and one record out of it. TEMPLATES on ``{notebook}``, which is what
#: makes a SECOND topic repo cost zero arXMCP code.
#:
#: RESOURCES, never tools. That is the whole reason this ships without a
#: schema-version bump or a prompt-cache invalidation: ``resources/read`` is a
#: different JSON-RPC method from ``tools/call``, so ``tools/list`` bytes --
#: and therefore ``EXPECTED_TOOL_SCHEMA_SHA256`` and the BP1 prefix -- are
#: untouched. ``tests/test_formal_resource.py`` asserts that mechanically
#: rather than the PR description asserting it in prose.
FORMAL_INDEX_TEMPLATE_URI = "arxmcp://formal/{notebook}"
FORMAL_RECORD_TEMPLATE_URI = "arxmcp://formal/{notebook}/{key}"

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


def _utc_iso() -> str:
    """The repo's timestamp convention, second-resolution, `Z`-suffixed.

    Local rather than imported from ``corpus_manifest``: that one is private
    to its module and reaching through it would make an unrelated refactor
    there break this census stamp.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Caveats are GENERATED, never authored: each is a mechanical consequence of a
#: field in the pin, so a record cannot be served with a caveat somebody forgot
#: to write. Ordered by severity, and ``withdrawn`` is always first when it
#: applies -- a reader who stops after one line must read that one.
def _caveats(pin: dict[str, Any], key: str, withdrawn: dict[str, Any] | None) -> list[str]:
    caveats: list[str] = []
    if withdrawn is not None:
        caveats.append(
            f"WITHDRAWN. The producer retracted this record at "
            f"{withdrawn.get('withdrawn_at', 'an unrecorded date')}"
            + (f": {withdrawn['reason']}" if withdrawn.get("reason") else "")
            + f". The withdrawal was read from tag "
            f"{pin.get('withdrawals_tag') or 'unknown'}, which may be NEWER "
            f"than the pinned {pin.get('tag')} -- withdrawals are the one "
            f"channel allowed to travel forward in time, because they can "
            f"only remove trust."
        )
    if pin.get("digest_provenance") != "git_rooted":
        caveats.append(
            "digest_provenance is self_attested_only: the artifact set agrees "
            "with itself and nothing outside it was consulted for the attest "
            "digests. That is a state a file copy also reaches. It is neither "
            "a pass nor a fail."
        )
    if not pin.get("resolution_json"):
        caveats.append(
            "No corpus resolution accompanies this pin, so nothing here says "
            "whether the quoted statements still appear in any corpus. Absent, "
            "not passing."
        )
    if not pin.get("review_json"):
        caveats.append(
            "No human faithfulness review accompanies this pin. Nobody has "
            "read this mathematics against its source."
        )
    if not key:
        caveats.append(
            "Coverage is a dated census, not a property of this response: a "
            "registry of N entries against a notebook of many thousands of "
            "chunks has covered a fraction of it, and `census` says which."
        )
    return caveats


def _withdrawn_keys(pin: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = pin.get("withdrawals_json")
    if not raw:
        return {}
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("formal resource: withdrawals_json is not JSON; ignoring")
        return {}
    return {
        item["key"]: item
        for item in (document.get("withdrawals") or [])
        if isinstance(item, dict) and item.get("key")
    }


def _pin_header(pin: dict[str, Any]) -> dict[str, Any]:
    """What was pinned. Never a verdict about it."""
    return {
        "repo": pin.get("repo"),
        "tag": pin.get("tag"),
        "tag_object_sha": pin.get("tag_object_sha"),
        "commit_sha": pin.get("commit_sha"),
        "registry_id": pin.get("registry_id"),
        "registry_sha256": pin.get("registry_sha256"),
        "env_digest": pin.get("env_digest"),
        "digest_provenance": pin.get("digest_provenance"),
        "withdrawals_tag": pin.get("withdrawals_tag"),
        "pinned_at": pin.get("pinned_at"),
    }


async def _formal_index(notebook: str) -> dict[str, Any]:
    """``arxmcp://formal/{notebook}`` — what this notebook pins, and how little.

    A notebook that pins nothing gets ``pinned: false`` rather than an error:
    "this corpus has no formalization" is an answer, and the overwhelming
    majority of notebooks are in that state.
    """
    validate_slug(notebook)          # FIRST, before any store or FS access
    pin = await _require_store().get_formal_release(notebook)
    if pin is None:
        return {
            "notebook": notebook,
            "pinned": False,
            "reason": (
                "no formal release is pinned for this notebook. arXMCP hosts "
                "no formalization of its own; a record appears here only once "
                "an operator pins a topic repo's release."
            ),
        }
    registry = json.loads(pin["registry_json"])
    entries = registry.get("entries") or {}
    withdrawn = _withdrawn_keys(pin)
    papers = sorted({
        f"{(e.get('source') or {}).get('scheme')}:"
        f"{(e.get('source') or {}).get('id')}"
        f"{(e.get('source') or {}).get('version') or ''}"
        for e in entries.values()
    })
    return {
        "notebook": notebook,
        "pinned": True,
        "pin": _pin_header(pin),
        "census": {
            "entries": len(entries),
            "withdrawn": len(set(entries) & set(withdrawn)),
            "papers_covered": len(papers),
            "papers": papers,
            # The denominator this census needs to MEAN anything, and it is
            # not computed here: it costs a LanceDB read on every
            # resources/read, and derived-alg-geo-lean #179 owns the census.
            # Null rather than absent, so the field a reader looks for is
            # present and visibly unanswered instead of quietly missing.
            "corpus_chunks": None,
            "corpus_chunks_note": (
                "not measured on this response; without it `entries` is a "
                "count and not a coverage fraction (#179)"
            ),
            "generated_at": _utc_iso(),
        },
        "keys": sorted(entries),
        "caveats": _caveats(pin, "", None),
    }


async def _formal_record(notebook: str, key: str) -> dict[str, Any]:
    """``arxmcp://formal/{notebook}/{key}`` — one record, re-served verbatim.

    ADR-0004's asymmetry is the whole permission model: arXMCP MAY downgrade an
    axis from its own fresher resolution, and has NO code path that raises one.
    So the entry is passed through exactly as the producer published it and
    every judgement this server adds arrives as a generated ``caveats[]`` entry
    beside it, never as an edit to the record.
    """
    validate_slug(notebook)
    pin = await _require_store().get_formal_release(notebook)
    if pin is None:
        raise ValueError(f"notebook {notebook!r} pins no formal release")
    registry = json.loads(pin["registry_json"])
    entry = (registry.get("entries") or {}).get(key)
    if entry is None:
        raise ValueError(f"no entry {key!r} in the release pinned for {notebook!r}")
    withdrawn = _withdrawn_keys(pin).get(key)
    return {
        "notebook": notebook,
        "key": key,
        "pin": _pin_header(pin),
        # Verbatim. Not reshaped, not summarized, not annotated in place.
        "entry": entry,
        "withdrawn": withdrawn is not None,
        "caveats": _caveats(pin, key, withdrawn),
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

    @mcp_server.resource(
        FORMAL_INDEX_TEMPLATE_URI,
        name="formal",
        description=(
            "The formalization release pinned for one notebook: the topic "
            "repo, tag, tag-object and commit shas, registry digest, "
            "digest_provenance, the citation keys it carries, and a DATED "
            "COVERAGE CENSUS. resources/read returns {notebook, pinned, pin, "
            "census, keys, caveats}. A notebook that pins nothing returns "
            "pinned:false, which is an answer and not an error. Read "
            "arxmcp://formal/<notebook>/<key> for one record."
        ),
        mime_type="text/plain",
    )
    async def _formal_index_resource(notebook: str) -> str:
        return _wrap_json(await _formal_index(notebook), kind="formal")

    @mcp_server.resource(
        FORMAL_RECORD_TEMPLATE_URI,
        name="formal-record",
        description=(
            "One statement record out of the release pinned for a notebook, "
            "re-served VERBATIM as the producer published it. resources/read "
            "returns {notebook, key, pin, entry, withdrawn, caveats}. Every "
            "judgement this server adds is a generated caveat beside the "
            "record, never an edit to it: arXMCP may DOWNGRADE a trust axis "
            "from its own fresher information and has no path that raises one. "
            "A withdrawn record is served with `withdrawn` first in caveats[]."
        ),
        mime_type="text/plain",
    )
    async def _formal_record_resource(notebook: str, key: str) -> str:
        return _wrap_json(await _formal_record(notebook, key), kind="formal")


__all__ = [
    "CORPUS_MANIFEST_URI",
    "FORMAL_INDEX_TEMPLATE_URI",
    "FORMAL_RECORD_TEMPLATE_URI",
    "NOTEBOOKS_INDEX_URI",
    "NOTEBOOK_TEMPLATE_URI",
    "register_resources",
    "reset_notebooks_store_for_tests",
    "set_notebooks_store",
]

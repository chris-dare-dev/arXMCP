"""``/api/v1/capabilities`` — capability-profile CRUD (stage2/arx-a23, WS-A A2).

Operator-plane management surface over the ``capability_profiles``
document in ``operator_settings`` (see :mod:`server.capabilities`).
JSON-only, loopback-bound, in-scope for the issue-#9 audit amendment.

Routes:

- ``GET    /api/v1/capabilities/profiles``          — list (hashes, never tokens)
- ``PUT    /api/v1/capabilities/profiles/{name}``   — upsert one profile
- ``DELETE /api/v1/capabilities/profiles/{name}``   — remove one profile

Token discipline (AC-A.10): the PUT body accepts ``token_sha256``
ONLY. A request carrying a raw ``token`` member is rejected 422 with
a pointed message — the operator hashes locally (e.g.
``python -c "import hashlib;print(hashlib.sha256(b'<tok>').hexdigest())"``)
so the token value never crosses even the loopback HTTP surface.

Writes invalidate the in-process profile cache inline, so changes
made through this surface are effective on the very next tool call
(AC-A.7's runtime-mutability, without waiting out the TTL).

Deleting or disabling ``default`` is allowed — that is how an
operator LOCKS DOWN unauthenticated loopback access. Deleting
``default`` merely restores the synthesized permissive default;
to restrict, define ``default`` with the desired policy.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from server.capabilities import (
    CAPABILITY_DOC_VERSION,
    parse_profiles_document,
    read_raw_document,
    write_raw_document,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["capabilities"])

FORMAT_VERSION: int = 1

#: Profile names: same shape discipline as notebook slugs — lowercase
#: alphanumeric + hyphen, bounded. Keeps names log-safe and URL-safe.
_PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

_TOKEN_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProfileUpsert(BaseModel):
    """PUT body for one profile. ``extra="forbid"`` is the AC-A.10
    tripwire: a raw ``token`` member is an unknown field → 422."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    token_sha256: str | None = Field(
        default=None,
        description=(
            "SHA-256 hex digest of the bearer token. NEVER the token "
            "value. Omit for the token-less default profile."
        ),
    )
    tools: list[str] | None = Field(
        default=None, description="Tool allowlist; null = all tools."
    )
    caps: dict[str, int] | None = Field(
        default=None,
        description=(
            "Per-tool per-session caps (tool -> max calls), superseding "
            "the built-in 3-search/4-chunk constants."
        ),
    )
    notebooks: list[str] | None = Field(
        default=None,
        description="Notebook-slug allowlist; null = unscoped.",
    )


def _validate_name(name: str) -> None:
    if not _PROFILE_NAME_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"profile name {name!r} is invalid (want "
                f"^[a-z][a-z0-9-]{{0,63}}$)"
            ),
        )


def _serialize_profiles(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Render the PARSED view (synthesized default included) so the
    operator sees the policy that is actually in force."""
    import json  # noqa: PLC0415

    parsed = parse_profiles_document(json.dumps(doc))
    rows = []
    for name in sorted(parsed):
        p = parsed[name]
        rows.append(
            {
                "name": p.name,
                "enabled": p.enabled,
                "token_sha256": p.token_sha256,
                "tools": sorted(p.tool_allow) if p.tool_allow is not None else None,
                "caps": dict(sorted(p.tool_caps.items())),
                "notebooks": (
                    sorted(p.notebook_allow)
                    if p.notebook_allow is not None
                    else None
                ),
            }
        )
    return rows


@router.get("/capabilities/profiles")
async def list_profiles() -> dict[str, Any]:
    """List effective profiles (the synthesized ``default`` included
    when the operator has not overridden it)."""
    doc = await read_raw_document()
    rows = _serialize_profiles(doc)
    return {
        "format_version": FORMAT_VERSION,
        "items": rows,
        "total": len(rows),
    }


@router.put("/capabilities/profiles/{name}")
async def upsert_profile(name: str, body: ProfileUpsert) -> dict[str, Any]:
    """Create or replace one profile; effective immediately (cache
    invalidated inline)."""
    _validate_name(name)
    if body.token_sha256 is not None and not _TOKEN_SHA256_RE.match(
        body.token_sha256.lower()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "token_sha256 must be a 64-char lowercase hex SHA-256 "
                "digest of the token — never the token value itself"
            ),
        )
    if body.caps is not None:
        for tool, cap in body.caps.items():
            if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"cap for tool {tool!r} must be a non-negative integer",
                )
    doc = await read_raw_document()
    entry: dict[str, Any] = {"enabled": body.enabled}
    if body.token_sha256 is not None:
        entry["token_sha256"] = body.token_sha256.lower()
    if body.tools is not None:
        entry["tools"] = {"allow": sorted(body.tools)}
    if body.caps is not None:
        entry["caps"] = dict(sorted(body.caps.items()))
    if body.notebooks is not None:
        entry["notebooks"] = {"allow": sorted(body.notebooks)}
    doc.setdefault("profiles", {})[name] = entry
    doc["format_version"] = CAPABILITY_DOC_VERSION
    try:
        await write_raw_document(doc)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    logger.info("capability profile %r upserted (enabled=%s)", name, body.enabled)
    return {"format_version": FORMAT_VERSION, "name": name, "result": "upserted"}


@router.delete("/capabilities/profiles/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(name: str) -> None:
    """Remove one profile. Deleting an operator-defined ``default``
    restores the synthesized permissive default. 404 when absent."""
    _validate_name(name)
    doc = await read_raw_document()
    profiles = doc.get("profiles", {})
    if name not in profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"profile {name!r} not found",
        )
    del profiles[name]
    doc["format_version"] = CAPABILITY_DOC_VERSION
    try:
        await write_raw_document(doc)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    logger.info("capability profile %r deleted", name)


__all__ = ["FORMAT_VERSION", "router"]

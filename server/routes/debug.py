"""``GET /debug/cache-stats`` — operational view of the 3-tier cache (E08_S03).

Returns a JSON document with per-tier counters and byte-usage
estimates. The same numbers are visible at ``/metrics`` in the
Prometheus exposition format; this endpoint is the human-readable
surface for `curl | jq` debugging.

Body shape:

```json
{
  "tier1": {"lookups_total": <int>, "hits_total": <int>,
            "evictions_total": <int>, "bytes_used": <int>},
  "tier2": { ... same keys ... },
  "tier3": { ... same keys ... }
}
```

The endpoint is reachable WITHOUT authentication (the server binds
to loopback only — Threat 4 from
``.claude/notes/08-security-observability-ops.md``). It returns 200
with all-zero counters when the cache singleton is uninitialized
(server still in startup) so the endpoint is safe to scrape during
the warm-up window.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from server.cache import get_cache
from server.metrics import TIER_1, TIER_2, TIER_3

router = APIRouter(tags=["debug"])


def _empty_stats() -> dict[str, dict[str, int]]:
    """Return the all-zero stats document used when the cache
    singleton is not yet initialized."""
    zero = {
        "lookups_total": 0,
        "hits_total": 0,
        "evictions_total": 0,
        "bytes_used": 0,
    }
    return {f"tier{tier}": dict(zero) for tier in (TIER_1, TIER_2, TIER_3)}


@router.get("/cache-stats")
async def cache_stats() -> JSONResponse:
    """Return per-tier cache stats as JSON.

    The body is small (well under 1 KB for any reasonable tier
    state), so it does NOT need to be exempted from the global 256
    KB body-size cap.
    """
    cache = get_cache()
    if cache is None:
        return JSONResponse(status_code=200, content=_empty_stats())
    return JSONResponse(status_code=200, content=cache.stats())


__all__ = ["router"]

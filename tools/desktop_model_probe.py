"""Real-model output probe for the desktop distribution gate
(desktop-distribution-m8 AC4).

Runs the PRODUCTION encode and rerank chains — ``server.query_encoder`` and
``server.retrieval.rerank``, never a re-implementation — over a fixed input
set and writes the resulting vectors and scores as JSON on stdout. The gate
test compares that output against a committed golden fixture: loading weights
proves the files parsed, not that the loaded weights are the intended ones.

Runs as its OWN process on purpose. ``tests/conftest.py`` sets
``KMP_DUPLICATE_LIB_OK=TRUE`` for the whole pytest session, and the desktop
launch contract forbids it; a probe that inherited the runner's environment
could not honestly assert the variable's absence. :data:`FORBIDDEN_ENV` is
re-checked here so the assertion is made by the process that does the compute.

Reads ``{"queries": [...], "pairs": [[query, body], ...]}`` on stdin. Model
weights are resolved from the ambient HuggingFace cache (``$HF_HOME``, else
``~/.cache/huggingface``) — outside any application bundle by construction.
No writes outside the HF cache; no network when the pinned revisions are
already cached.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

#: Mirrors ``tools/desktop_sidecar_spike.py``'s launch contract, prefixes
#: included: a narrower set here would let the golden vectors be produced under
#: a loader override the frozen probe refuses. Pinned equal by
#: ``tests/test_desktop_package.py``.
FORBIDDEN_ENV = ("KMP_DUPLICATE_LIB_OK", "PYTHONHOME", "PYTHONPATH")
FORBIDDEN_ENV_PREFIXES = ("DYLD_", "LD_")


def validate_environment(env: dict[str, str] | None = None) -> None:
    """Reject a compute environment carrying a forbidden or loader override."""
    source = os.environ if env is None else env
    bad = [
        key
        for key in source
        if key in FORBIDDEN_ENV or key.startswith(FORBIDDEN_ENV_PREFIXES)
    ]
    if bad:
        raise RuntimeError(f"forbidden environment keys: {sorted(bad)}")


def probe(queries: list[str], pairs: list[list[str]]) -> dict[str, object]:
    """Encode ``queries`` and score ``pairs`` through the production chains."""
    import torch

    from ingest.embedder import BGE_M3_COMMIT_SHA
    from server.model_loader import _huggingface_cache_root
    from server.query_encoder import _encode_query_sync
    from server.resources import _load_reranker_or_raise
    from server.retrieval.rerank import (
        BGE_RERANKER_COMMIT_SHA,
        RERANKER_MODEL_ID,
        _rerank_sync,
    )

    vectors = {query: _encode_query_sync(query).tolist() for query in queries}
    model, tokenizer = asyncio.run(_load_reranker_or_raise())
    # ONE batched forward pass over all bodies, exactly as RerankPhase does.
    raw_scores = _rerank_sync(model, tokenizer, pairs[0][0], [body for _, body in pairs])
    return {
        "vectors": vectors,
        "rerank_scores": [
            {"query": query, "body": body, "score": score}
            for (query, body), score in zip(pairs, raw_scores, strict=True)
        ],
        "embedder_revision": BGE_M3_COMMIT_SHA,
        "reranker_id": RERANKER_MODEL_ID,
        "reranker_revision": BGE_RERANKER_COMMIT_SHA,
        "hf_cache_root": _huggingface_cache_root().resolve().as_posix(),
        "torch_version": torch.__version__,
        "torch_threads": torch.get_num_threads(),
    }


def main() -> int:
    validate_environment()
    payload = json.load(sys.stdin)
    pairs = [list(pair) for pair in payload["pairs"]]
    if len({query for query, _ in pairs}) != 1:
        raise RuntimeError("all rerank pairs must share one query (single forward pass)")
    result = probe(list(payload["queries"]), pairs)
    json.dump(result, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

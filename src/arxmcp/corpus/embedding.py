"""Where a paper's embeddings live on disk and how their sidecar is read.

Each embedded paper has a directory under :data:`EMBEDDINGS_DIR` holding
the vectors (:data:`EMBEDDINGS_NPZ_NAME`) and a JSON sidecar
(:data:`EMBEDDINGS_MANIFEST_NAME`) that records which chunks were embedded
under which embedder version and input policy. Ingest writes both; the
store reads them when it loads a paper into LanceDB.
"""

from __future__ import annotations

import json
from pathlib import Path

from arxmcp.settings import ApplicationPaths

EMBEDDINGS_DIR: Path = ApplicationPaths.resolve().corpus / "embeddings"

# Constant filename for the NPZ + sidecar — co-located under
# ``var/arxmcp/corpus/embeddings/<paper_id>/``. The naming mirrors
# ``chunk_manifest.json`` so a future maintainer immediately understands
# the role from the path alone.
EMBEDDINGS_NPZ_NAME = "embeddings.npz"
EMBEDDINGS_MANIFEST_NAME = "embeddings_manifest.json"


def read_embeddings_manifest(out_path: Path) -> dict | None:
    """Return the sidecar dict, or ``None`` if absent / corrupt.

    A corrupt sidecar (any exception during read or parse) is treated
    as absent — the paper will be re-embedded, regenerating a clean
    sidecar in the process. This is the same self-healing discipline
    ``preamble._read_existing_preamble`` uses (see preamble.py F2 fix).
    """
    if not out_path.exists():
        return None
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # Corrupt sidecar => re-embed (regenerates a clean sidecar).
        return None


__all__ = [
    "EMBEDDINGS_DIR",
    "EMBEDDINGS_MANIFEST_NAME",
    "EMBEDDINGS_NPZ_NAME",
    "read_embeddings_manifest",
]

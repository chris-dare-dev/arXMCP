"""Frozen-bundle verification probe entry point (desktop-distribution-m7 AC2,
extended for m8's OpenMP consolidation).

Built as ``arxmcp-desktop-probe`` into the SAME onedir COLLECT as the
production child, so what it resolves is exactly what the child ships. Reads
one JSON object on stdin and writes one JSON object on stdout. Two modes:

``latex`` (default when the payload carries ``latex``)
    Converts the given LaTeX and reports the bundled symbol table's digest —
    proving the data hook shipped the real table, not merely that an import
    survived.

``omp``
    Runs a real FAISS add+search followed by real multi-threaded Torch
    compute in ONE process and reports every OpenMP image dyld actually
    mapped. Two mapped images is the ``OMP: Error #15`` abort, which happens
    before this can report anything — so the evidence is the exit status
    first and the image list second.

Refuses to run un-frozen, with any runtime path escaping the bundle, or with
any of :data:`FORBIDDEN_ENV` set — ``KMP_DUPLICATE_LIB_OK`` in particular
would suppress the very abort the OpenMP mode exists to detect.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import multiprocessing
import os
import re
import sys
from pathlib import Path

#: Mirrors ``tools/desktop_sidecar_spike.py``'s launch contract. Dynamic-loader
#: overrides are rejected by prefix in :func:`_validate_environment`; both
#: tuples are pinned equal across the three copies by
#: ``tests/test_desktop_package.py``, which the frozen probe cannot share code
#: with (it cannot import the driver).
FORBIDDEN_ENV = ("KMP_DUPLICATE_LIB_OK", "PYTHONHOME", "PYTHONPATH")
FORBIDDEN_ENV_PREFIXES = ("DYLD_", "LD_")

#: OpenMP runtime filenames. Kept byte-identical to ``desktop_package.py``'s
#: ``LIBOMP_PATTERN`` — the bundle cannot import the driver, and a filesystem
#: count that disagrees with the loaded-image count would silently split the
#: two halves of the m8 evidence. ``tests/test_desktop_package.py`` pins the
#: two patterns equal.
LIBOMP_NAME = re.compile(
    r"\Alib(omp|iomp5|gomp)(-[0-9a-f]+)?[.0-9]*\.(dylib|so[.0-9]*)\Z"
)


def _validate_frozen_containment() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("probe must run inside the frozen bundle")
    bundle = Path(sys.executable).resolve().parent
    candidates = [Path(sys.executable), *(Path(item) for item in sys.path if item)]
    escaped = [str(p) for p in candidates if not p.resolve().is_relative_to(bundle)]
    if escaped:
        raise RuntimeError(f"runtime path escaped bundle: {escaped}")
    return bundle


def _validate_environment() -> None:
    bad = [
        key
        for key in os.environ
        if key in FORBIDDEN_ENV or key.startswith(FORBIDDEN_ENV_PREFIXES)
    ]
    if bad:
        raise RuntimeError(f"forbidden environment keys: {sorted(bad)}")


def _loaded_openmp_images() -> list[str]:
    """Paths of the OpenMP images dyld has mapped into THIS process.

    Reads dyld's live image list rather than the on-disk tree: a second copy
    that is present but never mapped is a packaging defect, while a second
    copy that IS mapped is an abort. Only the second is visible here. Returns
    an empty list off macOS, where the loader exposes no equivalent call.
    """
    if sys.platform != "darwin":
        return []
    libc = ctypes.CDLL(None)
    libc._dyld_image_count.restype = ctypes.c_uint32
    libc._dyld_get_image_name.restype = ctypes.c_char_p
    libc._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    names = [
        libc._dyld_get_image_name(index).decode()
        for index in range(libc._dyld_image_count())
    ]
    return sorted(name for name in names if LIBOMP_NAME.match(Path(name).name))


def _run_latex(payload: dict, bundle: Path) -> dict:  # noqa: ARG001
    import latex2mathml.converter as converter_mod

    symbol_table = Path(converter_mod.__file__).resolve().parent / "unimathsymbols.txt"
    latex_inputs = payload["latex"]
    if not isinstance(latex_inputs, list) or not latex_inputs:
        raise RuntimeError("payload must carry a non-empty 'latex' list")
    return {
        "conversions": {latex: converter_mod.convert(latex) for latex in latex_inputs},
        "symbol_table_sha256": hashlib.sha256(symbol_table.read_bytes()).hexdigest(),
        "symbol_table_bytes": symbol_table.stat().st_size,
    }


def _run_openmp(payload: dict, bundle: Path) -> dict:
    """FAISS add+search then multi-threaded Torch compute, same process.

    ``import faiss`` pulls the real wrapper out of the PYZ (never the raw SWIG
    extension), so the OpenMP initialisation order is the one production
    takes. Sizes are payload-tunable to let a caller push past a small-workload
    false negative.
    """
    import faiss
    import numpy as np
    import torch

    rows = int(payload.get("rows", 2048))
    dim = int(payload.get("dim", 128))
    matrix = int(payload.get("matrix", 512))
    iterations = int(payload.get("iterations", 20))
    threads = int(payload.get("threads", 4))

    rng = np.random.default_rng(0)
    vectors = rng.random((rows, dim), dtype=np.float32)
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)
    distances, neighbours = index.search(vectors[:8], 4)

    torch.set_num_threads(threads)
    tensor = torch.randn(matrix, matrix)
    for _ in range(iterations):
        tensor = torch.mm(tensor, torch.randn(matrix, matrix))
        tensor = tensor / tensor.norm()

    faiss_so = Path(faiss._swigfaiss.__file__).resolve()
    return {
        "faiss_neighbours": neighbours[:, 0].tolist(),
        "faiss_self_distance_max": float(distances[:, 0].max()),
        "torch_checksum_finite": bool(torch.isfinite(tensor).all()),
        "torch_threads": torch.get_num_threads(),
        "torch_version": torch.__version__,
        "faiss_extension": faiss_so.relative_to(bundle).as_posix(),
        "openmp_images": _loaded_openmp_images(),
    }


_MODES = {"latex": _run_latex, "omp": _run_openmp}


def main() -> int:
    bundle = _validate_frozen_containment()
    _validate_environment()
    payload = json.load(sys.stdin)
    mode = payload.get("mode", "latex")
    if mode not in _MODES:
        raise RuntimeError(f"unknown probe mode {mode!r}; expected {sorted(_MODES)}")
    result = _MODES[mode](payload, bundle)
    json.dump(result, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())

"""Frozen-bundle verification probe entry point (desktop-distribution-m7 AC2).

Built as ``arxmcp-desktop-probe`` into the SAME onedir COLLECT as the
production child, so its latex2mathml conversion resolves the SAME
``_internal`` data tree the child ships — proving the data hook shipped the
real symbol table, not merely that an import survived. Reads
``{"latex": [...]}`` JSON on stdin; writes conversions plus the bundled
symbol table's SHA-256 as JSON on stdout. Refuses to run un-frozen or with
any runtime path escaping the bundle.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import sys
from pathlib import Path


def _validate_frozen_containment() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("probe must run inside the frozen bundle")
    bundle = Path(sys.executable).resolve().parent
    candidates = [Path(sys.executable), *(Path(item) for item in sys.path if item)]
    escaped = [str(p) for p in candidates if not p.resolve().is_relative_to(bundle)]
    if escaped:
        raise RuntimeError(f"runtime path escaped bundle: {escaped}")
    return bundle


def main() -> int:
    _validate_frozen_containment()
    import latex2mathml.converter as converter_mod

    symbol_table = Path(converter_mod.__file__).resolve().parent / "unimathsymbols.txt"
    payload = json.load(sys.stdin)
    latex_inputs = payload["latex"]
    if not isinstance(latex_inputs, list) or not latex_inputs:
        raise RuntimeError("payload must carry a non-empty 'latex' list")
    result = {
        "conversions": {latex: converter_mod.convert(latex) for latex in latex_inputs},
        "symbol_table_sha256": hashlib.sha256(symbol_table.read_bytes()).hexdigest(),
        "symbol_table_bytes": symbol_table.stat().st_size,
    }
    json.dump(result, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())

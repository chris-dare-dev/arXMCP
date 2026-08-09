"""Scan a PyInstaller executable's embedded archives for byte needles.

Runs under the BUILD venv (needs ``PyInstaller.archive.readers``), invoked by
``desktop_package.py``. The onedir executable embeds a CArchive whose PYZ
member holds every collected module's ``.pyc`` zlib-compressed — a raw byte
grep over the file cannot see a ``co_filename`` build path inside it, so this
helper decompresses each entry and scans the marshalled bytes.

argv: ``EXE_PATH NEEDLES_JSON`` where NEEDLES_JSON maps label -> base64 bytes.
stdout: JSON ``{"entries_scanned": n, "pyc_entries": n, "hits": {entry: [labels]}}``.
"""

from __future__ import annotations

import base64
import json
import marshal
import sys


def _to_bytes(obj: object) -> bytes:
    if isinstance(obj, bytes):
        return obj
    if isinstance(obj, bytearray | memoryview):
        return bytes(obj)
    try:
        return marshal.dumps(obj)
    except ValueError as exc:
        raise RuntimeError(f"unscannable archive entry type {type(obj)!r}") from exc


def main() -> int:
    from PyInstaller.archive.readers import CArchiveReader

    exe_path, needles_json = sys.argv[1], sys.argv[2]
    needles = {
        label: base64.b64decode(encoded)
        for label, encoded in json.loads(needles_json).items()
    }
    archive = CArchiveReader(exe_path)
    entries_scanned = 0
    pyc_entries = 0
    hits: dict[str, list[str]] = {}

    def scan(entry_name: str, data: bytes) -> None:
        found = sorted(label for label, needle in needles.items() if needle in data)
        if found:
            hits[entry_name] = found

    for name, (_, _, _, _, typecode) in archive.toc.items():
        entries_scanned += 1
        if typecode == "z":
            pyz = archive.open_embedded_archive(name)
            for module_name in pyz.toc:
                entries_scanned += 1
                pyc_entries += 1
                data = _to_bytes(pyz.extract(module_name))
                scan(f"{name}/{module_name}", data)
        else:
            scan(name, _to_bytes(archive.extract(name)))
    json.dump(
        {
            "entries_scanned": entries_scanned,
            "pyc_entries": pyc_entries,
            "hits": hits,
        },
        sys.stdout,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

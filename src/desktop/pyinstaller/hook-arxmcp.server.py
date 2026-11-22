"""Ship the ``arxmcp.server`` package's data files.

PyInstaller's module scan collects only ``.py``, so the wheel's package-data —
``router_patterns.yaml``, ``src/arxmcp/server/schemas/*.json`` and the operator console's
``src/arxmcp/server/frontend/{templates,static}`` — was absent from the bundle and the
frozen child died inside ``create_app()`` on the missing static directory
(measured at desktop-distribution-m8; m7's gate never reached app construction
because its only launch was a rejected one). ``src/arxmcp/server/router.py`` and
``src/arxmcp/server/tools.py`` raise on the other two.

This is CLAUDE.md §4.5b's rule one layer down: declaring the package ships its
modules and nothing else, at BOTH the wheel and the freeze boundary. One hook
per box package named in ``[tool.setuptools.package-data]`` —
``hook-arxmcp.ingest.py`` / ``hook-arxmcp.ops.py`` / ``hook-arxmcp.tools.py`` are the siblings, and
the gate test derives the list from that table rather than repeating it.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("arxmcp.server")

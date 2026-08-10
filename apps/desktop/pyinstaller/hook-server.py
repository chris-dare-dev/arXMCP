"""Ship the arxmcp ``server`` package's data files.

PyInstaller's module scan collects only ``.py``, so the wheel's package-data —
``router_patterns.yaml``, ``server/schemas/*.json`` and the operator console's
``server/frontend/{templates,static}`` — was absent from the bundle and the
frozen child died inside ``create_app()`` on the missing static directory
(measured at desktop-distribution-m8; m7's gate never reached app construction
because its only launch was a rejected one). ``server/router.py`` and
``server/tools.py`` raise on the other two.

This is CLAUDE.md §4.5b's rule one layer down: declaring the package ships its
modules and nothing else, at BOTH the wheel and the freeze boundary.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("server")

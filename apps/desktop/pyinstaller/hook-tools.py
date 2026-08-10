"""Ship the arxmcp ``tools`` package's data files when it is frozen.

Sibling of ``hook-server.py``: PyInstaller's module scan collects only
``.py``, so every top-level package declaring wheel package-data needs a hook
of its own or its data is silently absent from the bundle — the
``11b93e1`` class of bug, one package over. Inert when the frozen child never
imports ``tools``; the pairing is asserted from
``[tool.setuptools.package-data]`` by
``tests/test_desktop_package.py::test_bundle_ships_every_wheel_data_file_of_every_frozen_package``.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("tools")

"""Ship the ``arxmcp.settings`` package's data files when it is frozen.

Sibling of ``hook-arxmcp.server.py``: PyInstaller's module scan collects only
``.py``, so the vendored arXiv CA bundle (``src/arxmcp/settings/ca/``) would be
absent from the bundle and ``ARXMCP_PIN_ARXIV_CA=1`` would fail ``Config``
validation in the frozen child. The pairing is asserted from
``[tool.setuptools.package-data]`` by
``tests/test_desktop_package.py::test_bundle_ships_every_wheel_data_file_of_every_frozen_package``.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("arxmcp.settings")

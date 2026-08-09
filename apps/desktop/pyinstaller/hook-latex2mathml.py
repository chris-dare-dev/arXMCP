"""Ship latex2mathml's package data (``unimathsymbols.txt``, 216 KB).

PyInstaller's module scan collects only ``.py`` files; without this hook the
frozen converter silently degrades on the missing symbol table instead of
raising (spike-1's one bounded spec correction). No upstream
pyinstaller-hooks-contrib hook exists for this package.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("latex2mathml")

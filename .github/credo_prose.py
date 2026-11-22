"""Every tracked Markdown file is on the allow-list in CREDO.md.

Prose that is not a standard repository file belongs in the wiki, the issue or
the pull request.

Usage: python3 .github/credo_prose.py
Standard library only, so CI needs no install.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

ROOT_FILES = frozenset({
    "AGENTS.md",
    "CHANGES.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "CONTRIBUTORS.md",
    "CREDO.md",
    "OWNERS.md",
    "README.md",
    "SECURITY.md",
})

# A navigational README.md is allowed anywhere under these.
README_DIRS = frozenset({"deploy", "src", "tests"})

OTHER_FILES = frozenset({
    ".github/pull_request_template.md",
    "src/arxmcp/server/frontend/static/VENDORED.md",
})


def is_markdown(path: str) -> bool:
    return path.lower().endswith((".md", ".markdown", ".mdx"))


def allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return path in ROOT_FILES
    if parts[-1] == "README.md" and parts[0] in README_DIRS:
        return True
    return path in OTHER_FILES


def main() -> int:
    tracked = subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    errors = [p for p in tracked if is_markdown(p) and not allowed(p)]
    for path in errors:
        print(f"::error::{path}: Markdown outside the CREDO.md allow-list; "
              "put it in the wiki, the issue or the pull request")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

"""No change adds or edits Markdown outside the allow-list in CREDO.md.

Prose that is not a standard repository file belongs in the wiki, the issue
or the pull request. LEGACY is the exceptions list: Markdown that predates the
rule. It may stay until it is deleted, but it is never added to or edited, and
LEGACY only shrinks.

Usage: python3 .github/credo_prose.py BASE
Compares BASE with HEAD. Standard library only, so CI needs no install.
"""

from __future__ import annotations

import ast
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
README_DIRS = frozenset({
    "apps", "docker", "infra", "ingest", "ops", "server", "shim", "tests", "tools",
})

OTHER_FILES = frozenset({
    ".github/pull_request_template.md",
    "server/frontend/static/VENDORED.md",
})

LEGACY = (
    ".claude/TIER-GATES.md",
    ".claude/agents/",
    ".claude/commands/",
    ".claude/docs/",
    ".claude/notes/",
    ".claude/references/",
    ".claude/roadmap-briefs/",
    ".claude/roadmap/",
    ".claude/skills/",
    "docs/",
    "plans/",
)

THIS_FILE = ".github/credo_prose.py"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def is_markdown(path: str) -> bool:
    return path.lower().endswith((".md", ".markdown", ".mdx"))


def allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return path in ROOT_FILES
    if parts[-1] == "README.md" and parts[0] in README_DIRS:
        return True
    return path in OTHER_FILES


def in_legacy(path: str, legacy: tuple[str, ...]) -> bool:
    """An entry ending in / names a directory; any other names one file."""
    return any(
        path.startswith(entry) if entry.endswith("/") else path == entry
        for entry in legacy
    )


def legacy_at(rev: str) -> set[str] | None:
    """LEGACY as BASE defined it, or None if BASE predates this file."""
    try:
        source = git("show", f"{rev}:{THIS_FILE}")
    except subprocess.CalledProcessError:
        return None
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "LEGACY" for t in node.targets
        ):
            return set(ast.literal_eval(node.value))
    return set()


def main(base: str) -> int:
    errors = []

    changed = git(
        "diff", "--name-only", "--no-renames", "--diff-filter=AMT", base, "HEAD", "--"
    ).splitlines()
    flagged = {p for p in changed if is_markdown(p) and not allowed(p)}
    for path in sorted(flagged):
        errors.append(f"{path}: Markdown outside the CREDO.md allow-list; "
                      "put it in the wiki, the issue or the pull request")

    tree = [p for p in git("ls-files").splitlines() if is_markdown(p)]
    for path in tree:
        if path not in flagged and not allowed(path) and not in_legacy(path, LEGACY):
            errors.append(f"{path}: Markdown outside the allow-list and not in LEGACY")
    for entry in LEGACY:
        if not any(in_legacy(path, (entry,)) for path in tree):
            errors.append(f"LEGACY entry {entry!r} names no Markdown; delete it")

    before = legacy_at(base)
    if before is not None:
        for entry in sorted(set(LEGACY) - before):
            errors.append(f"LEGACY entry {entry!r} is new; LEGACY only shrinks")

    for error in errors:
        print(f"::error::{error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

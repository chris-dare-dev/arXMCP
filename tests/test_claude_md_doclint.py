"""Doc-lint: CLAUDE.md must not regress to known-stale claims.

Stage-1 finding 211 §4 established that the stale-CLAUDE.md hazard is
systemic: two separate planning errors traced to agents trusting
CLAUDE.md §3/§6/§7 prose (a "7 tools" count, a `cite_neighbors` "v1
STUB" claim, macOS-only paths) over code. The stage2/arx-ws0 refresh
fixed the prose; this test (the WS-0 acceptance-criteria AC-0.1
test-plan seed) keeps it fixed mechanically.

Patterns banned from the live doc:

- ``7 tools`` / ``7-tool``  — the surface is 8 tools (`server/tools.py::ALL_TOOLS`).
- ``stub``                  — no tool handler is a stub; deferrals are
                              described as deferrals with code citations
                              (CLAUDE.md §7). If a *real* stub ever ships,
                              describe it with different words or amend
                              this test in the same commit — that is the
                              point: the claim must be re-argued, not
                              inherited.
- ``/Users/chris.dare``     — macOS-only absolute paths presented as
                              current commands (Windows is tier-1).

Plus positive checks that pin count claims to their own cited sources
so they cannot silently drift:

- the tool count stated in CLAUDE.md §6 must match ``len(ALL_TOOLS)``
  (so the doc cannot silently drift when a ninth tool lands);
- the ``TOOL_SCHEMA_VERSION = N`` claim in CLAUDE.md §6 must match
  ``server.tools.TOOL_SCHEMA_VERSION`` (Stage-3 finding
  ``stale-onboarding-docs-and-doclint-blind-spot``: at edc4aff the doc
  still said 16 while code said 17 — the one deliberate BP1 byte event
  of Stage 2 — and NO gate caught it because the version claim was not
  pinned. This is the fix.);
- the test-marker count and names in §4.5 must match
  ``pyproject.toml [tool.pytest.ini_options].markers`` (Stage-2 WS-0
  verification caught the doc claiming "Six" while the registry held
  eight — same hazard class, same fix pattern);
- every top-level entry of ``docs/`` must appear in the §5 directory
  tree (the same verification caught §5 showing ``docs/`` with only
  ``install.md`` while the real tree held 12 entries);
- every top-level *source* directory of the repo (dot-dirs and the
  gitignored ``var/`` data tree excepted — see ``_TREE_SKIP_TOP_LEVEL``)
  must appear in the §5 directory tree (Stage-3 finding above: §5 omitted
  ``frontend-app/``, ``contracts/``, ``ops/`` and ``plans/`` — whole
  Stage-2 workstreams — while claiming to be the repo's directory map);
- ``README.md`` must NOT claim the frontend has "no SPA" / "no Node
  build chain" (Stage-3 finding above: README.md asserted exactly that,
  the direct negation of ADR-0001 and the shipped ``frontend-app/`` SPA).
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

from server.tools import ALL_TOOLS, TOOL_SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
README_MD = REPO_ROOT / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
DOCS_DIR = REPO_ROOT / "docs"

#: Top-level directories that are NOT source the §5 tree must document
#: (generated/gitignored data trees, VCS/CI/tooling dot-dirs, editor +
#: language caches). Everything else at the repo root is required in §5
#: by :func:`test_claude_md_tree_lists_every_top_level_dir`. Skipping
#: dot-dirs keeps the rule to the *product* layout; ``.claude/`` is the
#: one dot-dir §5 documents anyway and is not required by this rule.
_TREE_SKIP_TOP_LEVEL = frozenset({
    "var", "__pycache__", ".venv", "venv", "node_modules", ".ruff_cache",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".idea", "htmlcov",
})

_BANNED = [
    # (human label, compiled pattern)
    ("stale tool count '7 tools'/'7-tool'", re.compile(r"\b7[ -]tools?\b", re.IGNORECASE)),
    ("'stub' claim", re.compile(r"\bstubs?\b", re.IGNORECASE)),
    ("macOS-only path '/Users/chris.dare'", re.compile(r"/Users/chris\.dare")),
]


def _read() -> str:
    return CLAUDE_MD.read_text(encoding="utf-8")


def test_claude_md_has_no_stale_claim_patterns():
    text = _read()
    offenders: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pat in _BANNED:
            if pat.search(line):
                offenders.append(f"CLAUDE.md:{lineno} [{label}]: {line.strip()[:120]}")
    if offenders:
        raise AssertionError(
            "CLAUDE.md regressed to a known-stale claim pattern "
            "(finding 211 §4; WS-0 AC-0.1). Fix the prose against code "
            "ground truth — do not weaken this test without re-arguing "
            "the claim:\n  " + "\n  ".join(offenders)
        )


def test_claude_md_tool_count_matches_code():
    text = _read()
    n = len(ALL_TOOLS)
    claim = f"{n} frozen tool meta records"
    if claim not in text:
        raise AssertionError(
            f"CLAUDE.md §6 must state '{claim}' (len(ALL_TOOLS) == {n}); "
            "the doc's tool count has drifted from server/tools.py"
        )


def test_claude_md_names_every_tool():
    text = _read()
    missing = [t.name for t in ALL_TOOLS if f"`{t.name}`" not in text]
    if missing:
        raise AssertionError(
            "CLAUDE.md no longer names these registered MCP tools: "
            f"{missing} — §6 must list the full surface"
        )


def _registered_marker_names() -> list[str]:
    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    return [entry.split(":", 1)[0].strip() for entry in markers]


def test_claude_md_marker_count_matches_pyproject():
    text = _read()
    n = len(_registered_marker_names())
    claim = f"{n} test markers exist"
    if claim not in text:
        raise AssertionError(
            f"CLAUDE.md §4.5 must state '{claim}' — pyproject.toml "
            f"[tool.pytest.ini_options].markers registers {n} markers; "
            "the doc's marker count has drifted from its own cited "
            "source (stage2/arx-ws0 verification regression)"
        )


def test_claude_md_names_every_pytest_marker():
    text = _read()
    missing = [m for m in _registered_marker_names() if f"`{m}`" not in text]
    if missing:
        raise AssertionError(
            "CLAUDE.md no longer names these pytest markers registered "
            f"in pyproject.toml: {missing} — §4.5 must list the full "
            "registry (stage2/arx-ws0 verification regression)"
        )


def _section_5() -> str:
    text = _read()
    start = text.index("\n## 5. ")
    end = text.index("\n## 6. ", start)
    return text[start:end]


def _tracked_top_level_dirs() -> list[str]:
    """Top-level directory names that git TRACKS (gitignored artifacts
    excluded by construction).

    Primary source is ``git ls-tree -d --name-only HEAD`` — authoritative
    and immune to build by-products (``arxmcp.egg-info/``, ``var/``,
    ``.venv/`` …). Falls back to a filesystem walk minus
    ``_TREE_SKIP_TOP_LEVEL`` + ``*.egg-info`` if git is somehow
    unavailable, so the check still runs (just less precisely) outside a
    normal checkout.
    """
    try:
        out = subprocess.run(
            ["git", "ls-tree", "-d", "--name-only", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
        names = [line.strip() for line in out.splitlines() if line.strip()]
        if names:
            return names
    except (OSError, subprocess.SubprocessError):
        pass
    # Fallback: filesystem walk, excluding known artifacts + any egg-info.
    return [
        e.name
        for e in REPO_ROOT.iterdir()
        if e.is_dir()
        and e.name not in _TREE_SKIP_TOP_LEVEL
        and not e.name.endswith(".egg-info")
    ]


def test_claude_md_tree_lists_every_docs_entry():
    section = _section_5()
    missing = []
    for entry in sorted(DOCS_DIR.iterdir()):
        token = f"{entry.name}/" if entry.is_dir() else entry.name
        if token not in section:
            missing.append(token)
    if missing:
        raise AssertionError(
            "CLAUDE.md §5 directory tree no longer lists these top-level "
            f"docs/ entries: {missing} — the docs/ subtree must reflect "
            "the real chapter set (stage2/arx-ws0 verification "
            "regression; §1's placement table and §5 must agree)"
        )


def test_claude_md_tool_schema_version_matches_code():
    """CLAUDE.md §6's ``TOOL_SCHEMA_VERSION = N`` claim must equal
    ``server.tools.TOOL_SCHEMA_VERSION``.

    Stage-3 finding ``stale-onboarding-docs-and-doclint-blind-spot``: at
    edc4aff the doc said ``TOOL_SCHEMA_VERSION = 16`` while code said 17
    (the single deliberate BP1 byte event of Stage 2). The doc's own
    trust-discipline rule (§3) says fix the doc in the SAME change as the
    code — but nothing enforced it, so the stale claim shipped green. Pin
    it, like the tool count and marker registry above.
    """
    text = _read()
    # Accept any spacing around ``=``; capture the claimed integer.
    m = re.search(r"TOOL_SCHEMA_VERSION\s*=\s*(\d+)", text)
    if m is None:
        raise AssertionError(
            "CLAUDE.md §6 no longer states a 'TOOL_SCHEMA_VERSION = N' "
            f"claim — it must pin the live value ({TOOL_SCHEMA_VERSION}) "
            "so the BP1 byte-freeze version cannot silently drift from "
            "server/tools.py (finding stale-onboarding-docs-and-doclint-"
            "blind-spot)"
        )
    claimed = int(m.group(1))
    if claimed != TOOL_SCHEMA_VERSION:
        raise AssertionError(
            f"CLAUDE.md §6 claims TOOL_SCHEMA_VERSION = {claimed} but "
            f"server.tools.TOOL_SCHEMA_VERSION == {TOOL_SCHEMA_VERSION}. "
            "Fix the doc in the SAME change as any schema-version bump "
            "(CLAUDE.md §3 trust-discipline rule; finding "
            "stale-onboarding-docs-and-doclint-blind-spot)."
        )


def test_claude_md_tree_lists_every_top_level_dir():
    """Every top-level *source* directory of the repo must appear in the
    §5 directory tree.

    Stage-3 finding ``stale-onboarding-docs-and-doclint-blind-spot``: §5
    claimed to be the repo's directory map yet omitted ``frontend-app/``,
    ``contracts/``, ``ops/`` and ``plans/`` — entire Stage-2 workstreams.
    The pre-existing ``docs/``-entry pin (above) proved the pattern; this
    is the same pin one level up.

    Scope = git-**tracked** top-level directories only (dot-dirs also
    excepted). Filtering to tracked dirs is what makes the gate robust:
    it inherently ignores every gitignored artifact — ``var/`` (data),
    ``arxmcp.egg-info/`` (an editable-install builds this at the repo
    root during a full ``pytest`` run), ``.venv/``, ``__pycache__/``,
    ``node_modules/`` — so the gate never false-fires on a build
    by-product. ``.claude/`` is the one dot-dir §5 documents anyway and
    is not required here.
    """
    section = _section_5()
    missing = []
    for name in _tracked_top_level_dirs():
        if name.startswith(".") or name in _TREE_SKIP_TOP_LEVEL:
            continue
        if f"{name}/" not in section:
            missing.append(f"{name}/")
    if missing:
        raise AssertionError(
            "CLAUDE.md §5 directory tree no longer lists these top-level "
            f"source directories: {sorted(missing)} — §5 claims to be the "
            "repo's directory map, so a whole new top-level dir (a "
            "workstream) cannot land undocumented (finding "
            "stale-onboarding-docs-and-doclint-blind-spot)."
        )


#: README.md must not resurrect the "no SPA / no Node build chain" claim.
#: Matches the assertion whether phrased "no SPA", "no Node build chain",
#: or "no build chain" — the direct negation of ADR-0001 + frontend-app/.
_README_BANNED = [
    ("'no SPA' claim", re.compile(r"no\s+SPA", re.IGNORECASE)),
    ("'no Node build chain' claim", re.compile(r"no\s+Node\s+build\s+chain", re.IGNORECASE)),
]


def test_readme_has_no_no_spa_claim():
    """README.md must NOT claim the frontend has 'no SPA' / 'no Node build
    chain'.

    Stage-3 finding ``stale-onboarding-docs-and-doclint-blind-spot``:
    README.md:114 asserted "no SPA, no Node build chain" — the direct
    negation of ADR-0001 (build-time Node/Vite permitted) and the shipped
    ``frontend-app/`` SPA served at ``/app``. The runtime invariant is
    "no build chain AT RUNTIME"; the bare "no SPA / no Node build chain"
    claim is false and is what misled. If you must describe the runtime
    posture, say "no build chain at runtime" (which this pattern allows).
    """
    text = README_MD.read_text(encoding="utf-8")
    offenders: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pat in _README_BANNED:
            if pat.search(line):
                offenders.append(f"README.md:{lineno} [{label}]: {line.strip()[:120]}")
    if offenders:
        raise AssertionError(
            "README.md regressed to the 'no SPA / no Node build chain' "
            "claim — the direct negation of ADR-0001 and the shipped "
            "frontend-app/ SPA (finding stale-onboarding-docs-and-doclint-"
            "blind-spot). Describe the RUNTIME posture ('no build chain at "
            "runtime') instead:\n  " + "\n  ".join(offenders)
        )

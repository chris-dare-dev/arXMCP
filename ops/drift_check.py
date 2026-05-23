"""LaTeXML version-drift detector (E10_S04).

Daily-cron utility that compares freshly-rendered MathML against
checked-in baselines so a LaTeXML version bump cannot silently
corrupt the equation TED index. Each LaTeXML container upgrade can
change MathML byte-for-byte (whitespace, attribute ordering, even
element insertions like ``<mrow>``); the stored
``mathml_tree_json`` column rooted in pre-upgrade output would no
longer compare cleanly against query-time renders.

**Reads from checked-in fixtures, NOT the live equations table.**
The seed corpus's equations table is empty (only 2/50 papers have
raw TeX and both have failed LaTeXML conversions per E10_S03b's
Phase-1 finding); diffing against the table is unreachable at v1.
The fixtures under ``tests/fixtures/latexml-drift/`` ARE the
baseline.

**Diffs extracted ``<math>`` elements, NOT raw HTML.** Researcher 2
verified empirically that ``latexmlc`` output is NOT byte-stable
across runs of the same version — there are two timestamp injection
points (an XML comment and a visible ``<div class="ltx_page_logo">``)
that move with every invocation. ``--nocomments`` only suppresses
the XML comment, not the div. Stable comparison requires
BeautifulSoup-extracting ``<math>`` tags and serializing them as a
canonical string before diff.

**Counter exposure**: increments
:data:`server.metrics.LATEXML_DRIFT_DETECTED_COUNTER` inside the
cron process. Production ``/metrics`` exposure is deferred to E14;
the v1 operator signal is the cron job's stderr ERROR log,
non-zero exit code, and the sentinel file at
``var/arxmcp/ops/drift-detected.flag``.

**CLI:**

* ``python -m ops.drift_check`` — run all fixtures, exit 0 on no
  drift, exit 1 on any drift.
* ``python -m ops.drift_check --update-fixtures`` — regenerate the
  ``.expected.mathml`` baselines for every fixture (operator
  workflow after a deliberate LaTeXML upgrade).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from server.metrics import LATEXML_DRIFT_DETECTED_COUNTER

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE_DIR: Path = REPO_ROOT / "tests" / "fixtures" / "latexml-drift"
DEFAULT_SENTINEL_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "drift-detected.flag"
)

#: Per-fixture timeout for ``latexmlc`` invocation. Standalone
#: ``.tex`` fixtures with no ``\input{}`` deps render in well under
#: 1 second; 15 seconds catches hangs without false-positive
#: timeouts on slow CI nodes.
LATEXML_FIXTURE_TIMEOUT_SECONDS: int = 15

#: Suffix of the baseline files. Each ``.tex`` fixture is paired
#: with a ``<name>.expected.mathml`` file containing the canonical
#: extracted-MathML string. Comparison is byte-for-byte.
EXPECTED_SUFFIX: str = ".expected.mathml"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriftResult:
    """One fixture's drift-check outcome."""

    name: str
    drifted: bool
    actual: str
    expected: str
    message: str


# ---------------------------------------------------------------------------
# LaTeXML invocation
# ---------------------------------------------------------------------------


def _require_latexmlc() -> str:
    """Return the absolute path to ``latexmlc`` or raise.

    Mirrors ``tools/arxiv_fetch.py::_require_latexmlc`` discipline —
    operator-facing error message tells the user how to install on
    macOS / Debian.
    """
    path = shutil.which("latexmlc")
    if path is None:
        raise RuntimeError(
            "latexmlc not found on PATH. Install LaTeXML "
            "(macOS: `brew install latexml`; "
            "Debian/Ubuntu: `apt install latexml`) and re-run."
        )
    return path


def render_fixture(tex_path: Path) -> str:
    """Run ``latexmlc`` on ``tex_path`` and return the HTML output.

    The input ``.tex`` is COPIED into a fresh tmpdir before
    invocation so that ``latexmlc``'s alongside-input log file
    (``<name>.latexml.log``) lands in the tmpdir and gets cleaned
    up automatically. Using the fixture's own directory as cwd
    would litter the checked-in fixtures with regenerated log
    files on every run.

    Returns the contents of the rendered ``index.html``. Raises
    :class:`RuntimeError` if ``latexmlc`` is absent, exits non-zero,
    times out, or produces an empty output file.
    """
    if not tex_path.is_file():
        raise RuntimeError(f"fixture {tex_path} does not exist")

    latexmlc = _require_latexmlc()
    with tempfile.TemporaryDirectory(prefix="arxmcp-drift-") as tmpdir:
        tmp = Path(tmpdir)
        staged_tex = tmp / tex_path.name
        staged_tex.write_text(
            tex_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        out_html = tmp / "index.html"
        cmd = [
            latexmlc,
            str(staged_tex.name),
            f"--dest={out_html}",
            "--format=html5",
        ]
        # E13_S03b — Threat 3 sandbox wiring. Apply the same
        # production sandbox (sandbox-exec on macOS / bwrap on
        # Linux) used by ``tools/arxiv_fetch.py::parse_with_latexml``.
        # render_fixture runs latexmlc on potentially-untrusted
        # .tex fixtures (drift-check inputs), so the same
        # mitigation applies. ``_build_sandbox_cmd`` returns
        # ``cmd`` unchanged when no sandbox layer is available
        # (degraded path; Windows + un-installed bwrap fall
        # through cleanly).
        from tools.arxiv_fetch import _build_sandbox_cmd

        sandbox_tmpdir = tmp / "_sandbox_tmp"
        sandbox_tmpdir.mkdir(exist_ok=True)
        cmd = _build_sandbox_cmd(
            cmd,
            source_dir=tmp,
            output_dir=tmp,
            tmpdir_subdir=sandbox_tmpdir,
        )
        try:
            # E13_S03b F4 rectification — synthesis D6 required
            # ``start_new_session=True`` for parity with
            # ``parse_with_latexml``'s process-group-kill discipline.
            # The implementation initially dropped this; F4 adds it
            # so a hostile fixture whose ``latexmlc`` forks Perl
            # helpers cannot leave grandchildren behind on
            # ``TimeoutExpired``.
            proc = subprocess.run(  # noqa: S603 — argv form, no shell
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=LATEXML_FIXTURE_TIMEOUT_SECONDS,
                check=False,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"latexmlc timed out after "
                f"{LATEXML_FIXTURE_TIMEOUT_SECONDS}s on {tex_path.name}"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"latexmlc exited {proc.returncode} on {tex_path.name}: "
                f"{proc.stderr.strip()[:500]}"
            )
        if not out_html.is_file():
            raise RuntimeError(
                f"latexmlc produced no output for {tex_path.name}"
            )
        return out_html.read_text(encoding="utf-8")


def extract_canonical_mathml(html: str) -> str:
    """Extract every ``<math>`` element from ``html`` and serialize
    a canonical string for diff.

    The canonical form is the per-element ``str(tag)`` outputs
    joined by ``"\\n"``. Empty when the HTML carries no MathML
    (e.g., LaTeXML failed silently or the fixture compiles to a
    non-math output like a tikz-cd SVG).

    Researcher 2 verified this is byte-stable across runs of the
    same LaTeXML version, even though raw HTML is not. The
    timestamp noise lives in HTML comments and a visible
    ``ltx_page_logo`` div — neither inside ``<math>`` elements.

    **F5 (E10_S04 critique) limitation.** Whitespace INSIDE the
    ``<math>`` body is preserved verbatim. A LaTeXML upgrade that
    changes indentation between elements (without semantic AST
    change) WILL trigger drift. BeautifulSoup's ``html.parser``
    alphabetizes attributes at serialization, so attribute-order
    changes are absorbed — but inter-element whitespace is not.
    The operator inspecting a drift diff should sanity-check
    whether the change is whitespace-only before running the full
    rebase pipeline. A v2 enhancement could normalize runs of
    whitespace; v1 ships strict.
    """
    soup = BeautifulSoup(html, "html.parser")
    parts = [str(m) for m in soup.find_all("math")]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Fixture iteration
# ---------------------------------------------------------------------------


def list_fixtures(fixture_dir: Path) -> list[Path]:
    """Return the ``.tex`` fixtures in ``fixture_dir``, sorted by name.

    The drift-detector contract: every ``.tex`` in this directory is
    a fixture; every ``.tex`` is paired with a ``<name>.expected.mathml``.
    """
    if not fixture_dir.is_dir():
        raise RuntimeError(f"fixture dir {fixture_dir} does not exist")
    return sorted(fixture_dir.glob("*.tex"))


def expected_path_for(tex_path: Path) -> Path:
    """Return the paired ``<name>.expected.mathml`` path."""
    return tex_path.with_suffix(EXPECTED_SUFFIX)


def _read_expected(tex_path: Path) -> str:
    """Read the baseline MathML or return ``""`` if absent.

    Treating absent as empty lets the drift detector flag any
    fixture that was added without a baseline (an operator forgot
    to run ``--update-fixtures``). The empty baseline will never
    match real MathML, so the next check trips correctly.
    """
    p = expected_path_for(tex_path)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_fixture(tex_path: Path) -> DriftResult:
    """Render the fixture, extract MathML, compare to baseline.

    Returns a :class:`DriftResult` describing the outcome. Drift is
    reported AND the counter is incremented; the caller decides
    whether to also write the sentinel + exit non-zero.
    """
    name = tex_path.stem
    html = render_fixture(tex_path)
    actual = extract_canonical_mathml(html)
    expected = _read_expected(tex_path)
    if actual == expected:
        return DriftResult(
            name=name,
            drifted=False,
            actual=actual,
            expected=expected,
            message=f"{name}: ok",
        )
    LATEXML_DRIFT_DETECTED_COUNTER.labels(fixture=name).inc()
    return DriftResult(
        name=name,
        drifted=True,
        actual=actual,
        expected=expected,
        message=(
            f"{name}: DRIFT detected "
            f"(expected {len(expected)} bytes, got {len(actual)} bytes)"
        ),
    )


def check_all_fixtures(
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
) -> list[DriftResult]:
    """Run :func:`check_fixture` for every fixture in the directory.

    Returns a list of per-fixture results. The caller is
    responsible for the operator signal (logs, sentinel file, exit
    code) — keeping this function side-effect-free at the
    summary level makes the unit tests simpler.
    """
    return [check_fixture(p) for p in list_fixtures(fixture_dir)]


def update_fixtures(
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    *,
    allow_empty: bool = False,
) -> list[str]:
    """Regenerate every ``.expected.mathml`` baseline.

    Operator workflow after a LaTeXML upgrade: confirm the new
    version is intentional, run this to write the new baselines,
    then commit the result. Analogous to
    ``pytest --update-tool-schema-hash``.

    **F2 (E10_S04 critique) close.** Refuses to write an empty
    baseline by default. A broken ``latexmlc`` (silently exits 0
    without producing math, a buggy Homebrew formula, a malformed
    flag) would otherwise rebase every fixture to ``""``, causing
    subsequent ``--check`` runs to silent-pass against
    ``"" == ""`` — the exact corruption mode the drift detector
    exists to prevent. Pass ``allow_empty=True`` to override (no
    current v1 fixture is math-free; the escape hatch is reserved
    for a future fixture-class that may legitimately render
    without ``<math>``).

    Returns the list of fixture names that were updated (for the
    CLI summary).
    """
    updated: list[str] = []
    empty_fixtures: list[str] = []
    for tex_path in list_fixtures(fixture_dir):
        html = render_fixture(tex_path)
        actual = extract_canonical_mathml(html)
        if not actual and not allow_empty:
            empty_fixtures.append(tex_path.stem)
            continue
        out = expected_path_for(tex_path)
        out.write_text(actual, encoding="utf-8")
        updated.append(tex_path.stem)
    if empty_fixtures:
        raise RuntimeError(
            "refusing to write empty baselines for "
            f"{empty_fixtures}: latexmlc produced no <math> elements. "
            "Verify the LaTeXML install and inspect the fixture .tex "
            "files. Pass allow_empty=True if a math-free fixture is "
            "intended."
        )
    return updated


def write_sentinel(path: Path = DEFAULT_SENTINEL_PATH) -> None:
    """Write the drift-detected sentinel flag file.

    Idempotent — creating the file repeatedly is a no-op. The
    operator clears the flag manually after rectifying.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("drift-detected\n", encoding="utf-8")


def clear_sentinel(path: Path = DEFAULT_SENTINEL_PATH) -> None:
    """Remove the sentinel flag file. No-op if absent."""
    if path.is_file():
        path.unlink()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="LaTeXML version-drift detector (E10_S04).",
    )
    parser.add_argument(
        "--fixture-dir",
        default=str(DEFAULT_FIXTURE_DIR),
        help="Directory holding *.tex fixtures + *.expected.mathml baselines",
    )
    parser.add_argument(
        "--update-fixtures",
        action="store_true",
        help="Regenerate every .expected.mathml baseline from current "
        "latexmlc output. Use after a deliberate LaTeXML upgrade.",
    )
    parser.add_argument(
        "--sentinel-path",
        default=str(DEFAULT_SENTINEL_PATH),
        help="Path to the drift-detected sentinel flag file.",
    )
    args = parser.parse_args(argv)

    fixture_dir = Path(args.fixture_dir)
    sentinel_path = Path(args.sentinel_path)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.update_fixtures:
        updated = update_fixtures(fixture_dir)
        for name in updated:
            print(f"updated {name}")
        print(f"regenerated {len(updated)} fixture baseline(s)")
        return 0

    results = check_all_fixtures(fixture_dir)
    drifted = [r for r in results if r.drifted]
    for r in results:
        if r.drifted:
            logger.error("%s", r.message)
        else:
            logger.info("%s", r.message)

    if drifted:
        write_sentinel(sentinel_path)
        print(
            f"DRIFT detected on {len(drifted)} of {len(results)} fixture(s). "
            f"See sentinel {sentinel_path} and "
            f"docs/ops/latexml-drift-runbook.md.",
            file=sys.stderr,
        )
        return 1

    clear_sentinel(sentinel_path)
    print(f"ok: {len(results)} fixture(s) match baseline")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "DEFAULT_FIXTURE_DIR",
    "DEFAULT_SENTINEL_PATH",
    "DriftResult",
    "EXPECTED_SUFFIX",
    "LATEXML_FIXTURE_TIMEOUT_SECONDS",
    "check_all_fixtures",
    "check_fixture",
    "clear_sentinel",
    "expected_path_for",
    "extract_canonical_mathml",
    "list_fixtures",
    "render_fixture",
    "update_fixtures",
    "write_sentinel",
]

"""The macOS support floor is DECLARED at 14.0 and UNVERIFIED — keep both honest.

desktop-distribution-m9. The floor is inherited, not chosen: `faiss_cpu 1.13.2`
publishes exactly one arm64 macOS wheel (`macosx_14_0_arm64`), so nothing below
macOS 14 can run the closure. Three places declare that floor and must agree:
`tauri.conf.json`'s `bundle.macOS.minimumSystemVersion`, the repo-root
`.cargo/config.toml` `MACOSX_DEPLOYMENT_TARGET` pin, and the
`apps/desktop/README.md` "Supported boundary" section.

Declarations agreeing with each other is not the same as the ARTIFACT agreeing
with them, so the built binaries are read too: `minos` off `LC_BUILD_VERSION`
under `make desktop-conformance`, where they exist.

The floor has never been exercised: no component has ever run on macOS 14, the
development hardware cannot boot it, and `minos` is a build-time declaration
dyld does not enforce. So no shipped document, and no user-visible string or
event payload, may carry a claim-shaped sentence about macOS 14 compatibility.
When a real macOS 14 run finally happens, the change recording its evidence
must revise this gate in the same commit — until then, an unearned claim in one
of the known claim shapes fails the suite. That scan is a best-effort regex
calibrated against the corpus in `TestScannerControls`, not a parser: a clean
run means "no claim in the known shapes", never "no claim".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOOR = "14.0"
TAURI_CONF = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "tauri.conf.json"
CARGO_CONFIG = REPO_ROOT / ".cargo" / "config.toml"
DESKTOP_README = REPO_ROOT / "apps" / "desktop" / "README.md"

#: "macOS 14", "macOS 14.x", "macos14" — the version the claim would be about.
_MACOS_14 = r"mac\s?os\s*x?\s*14(?:\.\d+)?"

#: Evidence language, split by grammatical role so the shapes below compose.
_EVIDENCE_VERB = (
    r"(?:test|verif|validat|confirm|certif|prov|exercis|execut|benchmark"
    r"|install|qualif|smoke[- ]?test)\w*"
)
_EVIDENCE_ADJ = (
    r"(?:tested|verified|validated|confirmed|supported|certified|proven|working"
    r"|covered|exercised|green|passing|good|fine)"
)
_RUN_VERB = (
    r"(?:works?|worked|working|runs?|running|ran|passes|passed|passing|succeed\w*"
    r"|boots?|booted|launche[sd]|launching|installs?|installed|starts?|started)"
)
#: Up to three intervening tokens, so "tested successfully on macOS 14" and
#: "ran the full suite on macOS 14.4" read as the same claim as "tested on
#: macOS 14". Measured against the m9 critique's ten realistic phrasings.
_GAP = r"(?:\s+\w+){0,3}\s+"

#: Claim shapes: <evidence verb> on macOS 14 / macOS 14 is <evidence adjective>.
#: Scoped to evidence language — "release target" / "support floor" phrasing
#: deliberately does not match, because a target is not a claim. This is a
#: best-effort regex over prose, not a parser: it is calibrated against the
#: corpus in :class:`TestScannerControls` and will miss phrasings no one has
#: written down yet. Treat a clean run as "no claim in the known shapes".
_CLAIM_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"\b{_EVIDENCE_VERB}{_GAP}(?:on|against|under)\s+{_MACOS_14}\b",
        rf"\b{_RUN_VERB}{_GAP}on\s+{_MACOS_14}\b",
        rf"\b{_MACOS_14}\s+(?:is|was|are|were|has\s+been|have\s+been)\s+{_EVIDENCE_ADJ}\b",
        rf"\b{_MACOS_14}\s+(?:support|compatibility|readiness|coverage)\b"
        rf"(?:\s+(?:is|was|are|were|has\s+been|have\s+been))?\s+{_EVIDENCE_ADJ}\b",
        rf"\bsupported\s+on\s+{_MACOS_14}\b",
        rf"\bcompatib\w*\s+with\s+{_MACOS_14}\b",
        # Markdown support-matrix cell: | macOS 14 | tested |
        rf"\|\s*{_MACOS_14}\s*\|\s*(?:{_EVIDENCE_ADJ}|yes|✅)\s*\|",
    )
)

_NEGATION_CUES = re.compile(
    r"\b(?:not|never|no|none|nothing|cannot|can't|hasn't|haven't|has not|have not"
    r"|without|unverified|untested)\b",
    re.IGNORECASE,
)

_SENTENCE_STOPS = (". ", ".\n", "! ", "? ", "\n\n")

#: A negation cue only exempts a match it GOVERNS. Cutting the lookback window
#: at the nearest preceding clause boundary is what stops an unrelated cue from
#: laundering a real claim: in "There is no CI yet, and the app runs on macOS
#: 14." the "no" governs the CI clause, not the run claim.
_CLAUSE_BOUNDARY = re.compile(
    r"[,;:—–]|\b(?:and|but|or|so|yet|then|however|although|though|while|because"
    r"|whereas|meanwhile)\b",
    re.IGNORECASE,
)


def _governing_window(text: str, start: int) -> str:
    """Text from the nearest clause boundary before ``start`` to ``start``."""
    window = text[max(0, start - 160) : start]
    for stop in _SENTENCE_STOPS:
        cut = window.rfind(stop)
        if cut != -1:
            window = window[cut + len(stop) :]
    last_boundary = 0
    for boundary in _CLAUSE_BOUNDARY.finditer(window):
        last_boundary = boundary.end()
    return window[last_boundary:]


def _find_unearned_claims(text: str) -> list[str]:
    """Claim-pattern matches carrying no negation cue in their own clause."""
    findings: list[str] = []
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            window = _governing_window(text, match.start())
            if _NEGATION_CUES.search(window) or _NEGATION_CUES.search(match.group(0)):
                continue
            findings.append(match.group(0))
    return findings


#: Agent-facing, never shipped to a user — excluded from the scan by name so
#: adding a shipped root doc cannot silently land outside the gate.
_AGENT_DOCS = frozenset({"CLAUDE.md", "AGENTS.md"})


def _shipped_docs() -> list[Path]:
    """Every shipped Markdown file, DERIVED from the tree, not enumerated.

    Every other honesty gate in this repo (``test_wheel_packaging``,
    ``test_assert_ban``, ``test_marker_doc_consistency``) derives its surface
    from the on-disk tree precisely so a new file is covered by default.
    """
    docs = [p for p in REPO_ROOT.glob("*.md") if p.name not in _AGENT_DOCS]
    docs.extend((REPO_ROOT / "docs").rglob("*.md"))
    docs.extend(p for p in (REPO_ROOT / "apps").rglob("*.md") if p.name not in _AGENT_DOCS)
    return sorted({p for p in docs if p.is_file()})


def _shipped_event_sources() -> list[Path]:
    """AC4 reads "no document OR EVENT" — this is the event half.

    User-visible supervisor strings and lifecycle-event payloads live in the
    Rust shell and the Python child adapter, so a compatibility claim emitted
    at runtime is scanned by the same patterns as one written in prose.
    """
    sources = list((REPO_ROOT / "apps" / "desktop" / "crates").rglob("*.rs"))
    child = REPO_ROOT / "server" / "desktop_child.py"
    if child.is_file():
        sources.append(child)
    return sorted(p for p in sources if p.is_file())


#: Sentences that MUST be flagged. The first eight are the m9 critique's
#: measured bypasses (H2): every one of them passed the shipped scanner, which
#: had been calibrated to the two phrasings its author demonstrated against.
_MUST_FLAG = (
    "macOS 14 support is verified.",
    "The supervisor was tested successfully on macOS 14.",
    "The app runs fine on macOS 14.",
    "macOS 14 compatibility confirmed on the release runner.",
    "We ran the full suite on macOS 14.4 and it was green.",
    "The bundle installs cleanly on macOS 14.",
    "| macOS 14 | tested |",
    "There is no CI yet, and the app runs on macOS 14.",
    "The supervisor was tested on macOS 14.",
    "Everything works on macOS 14 out of the box.",
    "macOS 14 is supported by this bundle.",
    "This release is compatible with macOS 14.",
)

#: Sentences that must NOT be flagged. A keyword sweep would catch all of them:
#: the README's own honest prose necessarily contains the same words while
#: explicitly DENYING verification, so over-firing is as much a defect as
#: under-firing — it would make the honest text unwritable.
_MUST_NOT_FLAG = (
    "macOS 14 or newer on Apple Silicon is the first release target.",
    "No component of this workspace has ever been executed on macOS 14.",
    "The floor has never been exercised: no component has ever run on macOS 14.",
    "The machine itself cannot boot macOS 14 at all, including in a VM.",
    "Nothing in this workspace has been tested on macOS 14.",
    "Discharging this requires a Mac still on macOS 14 or a hosted macOS 14 runner.",
    "This gate fails if a macOS 14 compatibility claim lands in the shipped docs "
    "without a recorded macOS 14 test run.",
    'Until then, "macOS 14 or newer" above means DECLARED, not exercised.',
    "This has not been verified on macOS 14.",
    "The supervisor was never run on macOS 14.",
)


class TestScannerControls:
    """A scanner that reports zero because it is broken looks exactly like a
    scanner that reports zero because the docs are clean — so prove both arms,
    over a corpus rather than over the phrasings the author happened to try."""

    @pytest.mark.parametrize("sentence", _MUST_FLAG)
    def test_flags_a_claim(self, sentence: str):
        assert _find_unearned_claims(sentence), (
            f"unearned macOS 14 claim not detected: {sentence!r}"
        )

    @pytest.mark.parametrize("sentence", _MUST_NOT_FLAG)
    def test_accepts_an_honest_statement(self, sentence: str):
        assert _find_unearned_claims(sentence) == [], (
            f"honest statement wrongly flagged as a claim: {sentence!r}"
        )

    def test_negation_in_an_earlier_sentence_does_not_launder_a_claim(self):
        text = "It was not signed before. The app runs on macOS 14."
        assert _find_unearned_claims(text)

    def test_the_shipped_readme_is_in_the_negative_corpus(self):
        """The corpus above must describe the REAL doc, not a paraphrase of it."""
        text = DESKTOP_README.read_text(encoding="utf-8")
        assert "has ever been executed on macOS 14" in text
        assert "cannot boot macOS 14" in text


class TestDeclaredFloorAgreement:
    def test_tauri_conf_declares_the_floor(self):
        conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
        declared = conf.get("bundle", {}).get("macOS", {}).get("minimumSystemVersion")
        assert declared == FLOOR, (
            f"tauri.conf.json declares minimumSystemVersion={declared!r}; without an "
            f"explicit {FLOOR!r} Tauri's bundler default advertises 10.13 — four majors "
            f"below the floor the faiss_cpu macosx_14_0_arm64 wheel imposes"
        )

    def test_cargo_config_pins_the_deployment_target(self):
        cfg = tomllib.loads(CARGO_CONFIG.read_text(encoding="utf-8"))
        pin = cfg.get("env", {}).get("MACOSX_DEPLOYMENT_TARGET")
        assert isinstance(pin, dict), (
            ".cargo/config.toml must pin MACOSX_DEPLOYMENT_TARGET so the Rust binaries "
            "declare minos at the floor instead of rustc's 11.0 default"
        )
        assert pin.get("value") == FLOOR
        assert pin.get("force") is True, (
            "force = true is required: an ambient MACOSX_DEPLOYMENT_TARGET would "
            "silently desync the built minos from the declared floor"
        )

    def test_readme_states_inherited_hard_and_unverified(self):
        text = DESKTOP_README.read_text(encoding="utf-8")
        assert "macosx_14_0_arm64" in text, "the wheel citation is what makes the floor HARD"
        assert "INHERITED" in text and "HARD" in text
        assert "UNVERIFIED" in text
        assert "build-time declaration" in text and "not a runtime gate" in text
        assert f'`MACOSX_DEPLOYMENT_TARGET = "{FLOOR}"`' in text, (
            "the README must quote the same floor the build config pins"
        )


#: Both are exported by ``make desktop-conformance`` (Makefile), so the gate
#: arms the artifact check for free.
_BINARY_ENV = ("DESKTOP_SUPERVISOR_BIN", "ARXMCP_FIXTURE_SIDECAR")

_MINOS = re.compile(r"^\s*minos\s+(\S+)\s*$", re.MULTILINE)


def _declared_minos(binary: Path) -> list[str]:
    """Every ``minos`` a Mach-O's build-version load commands declare.

    RAISES rather than returning empty on any failure. An empty parse is
    indistinguishable from a clean read of a binary with no build version, and
    this whole milestone exists because a silently-wrong artifact looked fine.
    """
    otool = shutil.which("otool")
    if otool is None:
        raise RuntimeError(
            "otool is required to read LC_BUILD_VERSION off the built binaries; "
            "it ships with the Xcode command line tools (xcode-select --install)"
        )
    result = subprocess.run(
        [otool, "-l", str(binary)], capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"otool -l {binary} failed: {result.stderr.strip()!r}")
    found = _MINOS.findall(result.stdout)
    if not found:
        raise RuntimeError(
            f"no minos found in otool -l {binary}: an absent LC_BUILD_VERSION / "
            f"LC_VERSION_MIN_MACOSX is an evidence failure, not a passing floor"
        )
    return found


@pytest.mark.requires_desktop_stack
class TestBuiltArtifactDeclaresTheFloor:
    """Pinning three DECLARATIONS proves they agree with each other, not with
    the thing that ships. The implementer hit exactly that drift by hand — a
    warm cargo cache kept ``fixture-sidecar`` at ``minos 11.0`` while every
    declaration read 14.0 — and cargo discovers ``.cargo/config.toml`` by
    walking up from the CWD, not from ``--manifest-path``, so an invocation
    started outside the repo root still builds at rustc's 11.0 default.

    Following the ``requires_latexmlc`` / m6 ``lsof`` precedent this carries NO
    secondary skip guard: inside ``make desktop-conformance`` a missing env
    var, a missing binary, or a missing ``otool`` RAISES, because a check that
    degrades to a silent skip is the failure mode it exists to catch.
    """

    @pytest.mark.parametrize("env_name", _BINARY_ENV)
    def test_binaries_report_the_declared_minos(self, env_name: str):
        raw = os.environ.get(env_name)
        if not raw:
            raise RuntimeError(
                f"{env_name} is unset; this test reads the BUILT artifact and "
                f"`make desktop-conformance` exports it (see Makefile)"
            )
        binary = Path(raw)
        if not binary.is_file():
            raise RuntimeError(f"{env_name}={raw!r} does not name a built binary")
        declared = _declared_minos(binary)
        assert set(declared) == {FLOOR}, (
            f"{binary.name} declares minos {sorted(set(declared))}, not {FLOOR!r}. The "
            f"artifact disagrees with .cargo/config.toml, tauri.conf.json and the "
            f"README. Most likely a warm cargo target dir, or a cargo invocation whose "
            f"CWD was outside the repo root so the [env] pin was never discovered."
        )


class TestNoUnearnedClaimInShippedDocs:
    def test_doc_set_is_derived_and_covers_the_shipped_surface(self):
        docs = _shipped_docs()
        assert DESKTOP_README in docs
        assert REPO_ROOT / "README.md" in docs
        assert REPO_ROOT / "CLAUDE.md" not in docs, "agent-facing docs are not shipped"
        assert len(docs) >= 3, "an empty scan set is a broken scan, not a clean result"

    def test_event_source_set_is_nonempty_and_covers_the_supervisor(self):
        sources = _shipped_event_sources()
        assert sources, "an empty scan set is a broken scan, not a clean result"
        names = {p.name for p in sources}
        assert "lifecycle.rs" in names, "the supervisor's event emitter must be scanned"

    def test_shipped_docs_carry_no_unearned_macos14_claim(self):
        offenders = {
            str(doc.relative_to(REPO_ROOT)): found
            for doc in _shipped_docs()
            if (found := _find_unearned_claims(doc.read_text(encoding="utf-8")))
        }
        assert offenders == {}, (
            f"macOS 14 compatibility claims with no recorded macOS 14 test run: "
            f"{offenders}. A claim may land only together with the run evidence and a "
            f"revision of this gate (apps/desktop/README.md, 'Supported boundary')."
        )

    def test_shipped_events_carry_no_unearned_macos14_claim(self):
        """AC4's "no document OR EVENT" half — the event vocabulary."""
        offenders = {
            str(src.relative_to(REPO_ROOT)): found
            for src in _shipped_event_sources()
            if (found := _find_unearned_claims(src.read_text(encoding="utf-8")))
        }
        assert offenders == {}, (
            f"macOS 14 compatibility claims in user-visible strings or event "
            f"payloads with no recorded macOS 14 test run: {offenders}"
        )

"""The macOS support floor is DECLARED at 14.0 and UNVERIFIED — keep both honest.

desktop-distribution-m9. The floor is inherited, not chosen: `faiss_cpu 1.13.2`
publishes exactly one arm64 macOS wheel (`macosx_14_0_arm64`), so nothing below
macOS 14 can run the closure. Three places declare that floor and must agree:
`tauri.conf.json`'s `bundle.macOS.minimumSystemVersion`, the repo-root
`.cargo/config.toml` `MACOSX_DEPLOYMENT_TARGET` pin, and the
`apps/desktop/README.md` "Supported boundary" section.

The floor has never been exercised: no component has ever run on macOS 14, the
development hardware cannot boot it, and `minos` is a build-time declaration
dyld does not enforce. So no shipped document may carry a claim-shaped sentence
about macOS 14 compatibility. When a real macOS 14 run finally happens, the
change recording its evidence must revise this gate in the same commit — until
then, an unearned claim anywhere in the shipped doc set fails the suite.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOOR = "14.0"
TAURI_CONF = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "tauri.conf.json"
CARGO_CONFIG = REPO_ROOT / ".cargo" / "config.toml"
DESKTOP_README = REPO_ROOT / "apps" / "desktop" / "README.md"

#: "macOS 14", "macOS 14.x", "macos14" — the version the claim would be about.
_MACOS_14 = r"mac\s?os\s*x?\s*14(?:\.\d+)?"

#: Claim shapes: <evidence verb> on macOS 14 / macOS 14 is <evidence adjective>.
#: Scoped to evidence language — "release target" / "support floor" phrasing
#: deliberately does not match, because a target is not a claim.
_CLAIM_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"\b(?:test|verif|validat|confirm|certif|prov|exercis|execut|benchmark)\w*"
        rf"\s+(?:on|against|under)\s+{_MACOS_14}\b",
        rf"\b(?:works?|working|runs?|running|ran|passes|passed|passing|succeed\w*"
        rf"|boots?|booted|launche[sd]|launching)\s+on\s+{_MACOS_14}\b",
        rf"\b{_MACOS_14}\s+(?:is|was|are|were|has\s+been)\s+(?:tested|verified|validated"
        rf"|confirmed|supported|certified|proven|working|covered|exercised)\b",
        rf"\bsupported\s+on\s+{_MACOS_14}\b",
        rf"\bcompatib\w*\s+with\s+{_MACOS_14}\b",
    )
)

_NEGATION_CUES = re.compile(
    r"\b(?:not|never|no|none|nothing|cannot|can't|hasn't|haven't|has not|have not"
    r"|without|unverified|untested)\b",
    re.IGNORECASE,
)

_SENTENCE_STOPS = (". ", ".\n", "! ", "? ", "\n\n")


def _find_unearned_claims(text: str) -> list[str]:
    """Claim-pattern matches whose own sentence carries no negation cue."""
    findings: list[str] = []
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - 160) : match.start()]
            for stop in _SENTENCE_STOPS:
                cut = window.rfind(stop)
                if cut != -1:
                    window = window[cut + len(stop) :]
            if _NEGATION_CUES.search(window) or _NEGATION_CUES.search(match.group(0)):
                continue
            findings.append(match.group(0))
    return findings


def _shipped_docs() -> list[Path]:
    docs = [REPO_ROOT / "README.md", REPO_ROOT / "CHANGES.md", DESKTOP_README]
    docs.extend(sorted((REPO_ROOT / "docs").rglob("*.md")))
    return [p for p in docs if p.is_file()]


class TestScannerControls:
    """A scanner that reports zero because it is broken looks exactly like a
    scanner that reports zero because the docs are clean — so prove both arms."""

    def test_flags_a_bare_test_claim(self):
        assert _find_unearned_claims("The supervisor was tested on macOS 14.")

    def test_flags_a_works_claim(self):
        assert _find_unearned_claims("Everything works on macOS 14 out of the box.")

    def test_flags_a_supported_claim(self):
        assert _find_unearned_claims("macOS 14 is supported by this bundle.")

    def test_accepts_a_negated_statement(self):
        assert not _find_unearned_claims("No component has ever been executed on macOS 14.")

    def test_accepts_the_release_target_phrasing(self):
        assert not _find_unearned_claims(
            "macOS 14 or newer on Apple Silicon is the first release target."
        )

    def test_negation_in_an_earlier_sentence_does_not_launder_a_claim(self):
        text = "It was not signed before. The app runs on macOS 14."
        assert _find_unearned_claims(text)


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


class TestNoUnearnedClaimInShippedDocs:
    def test_doc_set_is_nonempty_and_covers_the_desktop_readme(self):
        docs = _shipped_docs()
        assert DESKTOP_README in docs
        assert len(docs) >= 3, "an empty scan set is a broken scan, not a clean result"

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

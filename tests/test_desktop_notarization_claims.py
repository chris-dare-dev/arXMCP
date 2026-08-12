"""No artifact this project produces may be called notarization-ready.

desktop-distribution-m15, AC2. The bundle-assembly ADR
(`.claude/docs/adr-desktop-bundle-assembly.md`, Decision 3, Accepted) records
the notarization question as **OPEN**: nothing in this repository can settle
whether the assembled `.app` survives Apple's notary service, because closing
it needs a build-and-submit trial under a Developer ID Application certificate
that does not exist here. Decision 3 therefore states a binding language rule,
and this module is that rule's regression.

The four questions Decision 3 keeps apart, and who can answer them:

| # | question | answerable by |
|---|---|---|
| a | does the artifact assemble | m15 — yes, measured |
| b | does it launch | m15 — measured for the resolution it performs |
| c | is the payload signed at all | only with a certificate; m15 signs ad-hoc |
| d | does Apple's notary accept it | e4, with the certificate |

A claim that collapses (a) or (c) into (d) is the failure this gate exists to
catch. It is the same discipline m9 applied to the macOS 14 floor and the same
§4.9 rule against a bare status token that merges distinct trust questions.

**Scan scope is a decision, recorded here** (ADR "does NOT decide" item 7).
m9's compatibility scanner reads root `*.md`, `docs/**`, `apps/**.md` and
`apps/desktop/crates/**/*.rs` — and deliberately NOT `.claude/`. That scope is
wrong for this claim: the single most likely place to write "the bundle is
notarization-ready" is the ADR that decides the bundle layout, which lives in
`.claude/docs/`. So this scan ADDS `.claude/docs/**.md`, this milestone's own
notes, `plans/**.md` (where the acceptance criteria are written) and
`apps/desktop/pyinstaller/**.py` (where the signing code and its docstrings
live) on top of m9's set. Widening m9's own scan instead was rejected: its
corpus and its calibration are about a different claim, and merging them would
make each scanner's controls answer for the other's.

Like m9's, this is a best-effort regex over prose calibrated against the
corpus below, not a parser. A clean run means "no claim in the known shapes",
never "no claim".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ADR = REPO_ROOT / ".claude" / "docs" / "adr-desktop-bundle-assembly.md"

#: Whatever the claim would be ABOUT. Kept to concrete artifact nouns so a
#: sentence about someone else's dylibs in the evidence ledger is not this
#: project's claim about its own bundle.
_ARTIFACT = (
    r"(?:the\s+|this\s+|our\s+)?"
    r"(?:arXMCP\.app|\.app(?:\s+bundle)?|app\s+bundle|application\s+bundle"
    r"|assembled\s+bundle|bundle|artifact|payload|release)"
)

#: Compound readiness adjectives. These exist ONLY as claims — there is no
#: honest use of "notarization-ready" that is not asserting readiness — so
#: they are flagged wherever they appear without a disclaiming cue.
_READY = (
    r"(?:notari[sz]ation[-\s]ready|notari[sz]e[-\s]ready|gatekeeper[-\s]ready"
    r"|signable[-\s]as[-\s]is|ready\s+(?:to|for)\s+notari[sz]\w+"
    r"|ready\s+for\s+gatekeeper)"
)

_CLAIM_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"\b{_READY}\b",
        # "the bundle is notarized" / "the app has been notarized"
        rf"\b{_ARTIFACT}\s+(?:is|was|are|were|has\s+been|have\s+been|will\s+be)"
        rf"\s+(?:successfully\s+|fully\s+)?"
        rf"(?:notari[sz]ed|gatekeeper[-\s]approved|signed\s+for\s+distribution)\b",
        # "signing works" / "the signature is valid for distribution"
        r"\b(?:code)?signing\s+(?:works|is\s+working|is\s+complete|is\s+done)\b",
        r"\bpasses\s+(?:apple'?s\s+)?notari[sz]\w+\b",
        r"\bnotari[sz]ation\s+(?:is\s+)?(?:passes|passed|succeeds|succeeded|complete)\b",
        # --- added by m15 critique M3/M7: phrasings the adversary reached the
        # gate with, all of which MISSED. The m9 lesson recurring — a guard
        # calibrated to the phrasings it was demoed against.
        r"\bwill\s+notari[sz]e\b",
        r"\b(?:should|would)\s+notari[sz]e\b",
        r"\bnotari[sz]able\b",
        r"\bready\s+to\s+ship\s+to\s+(?:apple'?s\s+)?notary\b",
        r"\bready\s+for\s+distribution\b",
        r"\bsatisfies\s+(?:apple'?s\s+)?notari[sz]ation\s+requirements\b",
    )
)

#: A disclaiming cue anywhere in the SENTENCE exempts the match.
#:
#: Sentence-level, NOT m9's clause-level window, and that difference is
#: deliberate. m9 cuts the lookback at the nearest clause boundary so an
#: unrelated negation cannot launder a claim. The sentences this gate must
#: tolerate are the opposite shape — meta-statements that NAME the forbidden
#: phrases in order to forbid them ("no document may assert that the artifact
#: is notarization-ready, Gatekeeper-ready, ...") — where every comma is a
#: clause boundary and a clause-level window would strip the governing "no"
#: and flag the prohibition itself. The cost is a wider exemption; the
#: controls below are what bound it.
#: Narrowed by m15 critique M3/M7. The original set included `must`, `may`,
#: `would`, `if`, `open` and `question`, and any occurrence ANYWHERE in the
#: sentence exempted it — so "the artifact is notarization-ready, if you want
#: to ship it" scanned clean on the strength of one `if`. Two changes bound
#: that:
#:
#: 1. The weak cues are gone. What remains either negates or governs: an
#:    explicit negation, or a verb of forbidding/refusing.
#: 2. The cue must appear BEFORE the claim it is supposed to disclaim (see
#:    `_find_unearned_claims`). That is what the tolerated shape actually
#:    looks like — "**no** document may assert that the artifact is
#:    notarization-ready" — and a trailing cue can no longer launder a claim
#:    that was already made earlier in the sentence.
_DISCLAIM_CUES = re.compile(
    r"\b(?:not|never|no|none|nothing|neither|nor|cannot|can't|without"
    r"|unverified|untested|unanswered|unresolved|unknown|whether"
    r"|forbid\w*|refus\w*|prohibit\w*|block\w*|prevent\w*|preclud\w*"
    r"|claim\s+that)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n\n+")


def _find_unearned_claims(text: str) -> list[str]:
    """Claim-pattern matches not GOVERNED by an earlier disclaiming cue.

    Position matters (critique M3/M7): a cue exempts only the claims that
    follow it in the same sentence. A cue after the claim did not disclaim
    anything — it just happened to be nearby, which is how one stray word
    used to switch the whole gate off for that sentence.
    """
    findings: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        cue = _DISCLAIM_CUES.search(sentence)
        cue_at = cue.start() if cue else None
        for pattern in _CLAIM_PATTERNS:
            for match in pattern.finditer(sentence):
                if cue_at is not None and cue_at < match.start():
                    continue
                findings.append(match.group(0))
    return findings


_AGENT_DOCS = frozenset({"CLAUDE.md", "AGENTS.md"})


def scanned_files() -> list[Path]:
    """The scan set, DERIVED from the tree so a new file is covered by default.

    Same derivation discipline as `test_desktop_support_floor._shipped_docs`
    and `test_wheel_packaging`: enumerating filenames would let the next
    document land outside the gate silently.
    """
    paths: list[Path] = [p for p in REPO_ROOT.glob("*.md") if p.name not in _AGENT_DOCS]
    paths.extend((REPO_ROOT / "docs").rglob("*.md"))
    paths.extend(p for p in (REPO_ROOT / "apps").rglob("*.md") if p.name not in _AGENT_DOCS)
    paths.extend((REPO_ROOT / "apps" / "desktop" / "crates").rglob("*.rs"))
    paths.extend((REPO_ROOT / "apps" / "desktop" / "pyinstaller").rglob("*.py"))
    paths.extend((REPO_ROOT / "plans").rglob("*.md"))
    paths.extend((REPO_ROOT / ".claude" / "docs").rglob("*.md"))
    paths.extend(
        (REPO_ROOT / ".claude" / "notes" / "milestones" / "desktop-distribution-m15").rglob(
            "*.md"
        )
    )
    # Critique artifacts are EXCLUDED, and only critique artifacts. An
    # adversarial critic must be able to write "the pre-fix gate returned MISS
    # for 'the artifact is ready for notarization'" — quoting a forbidden
    # phrasing is how a bypass gets reported at all, and gating that would
    # make the finding unwriteable. They are analysis of the project, not
    # claims by it, and nothing ships from them. research/, implement/ and
    # rectify/ stay in scope: those DO speak for the project.
    return sorted(
        {p for p in paths if p.is_file() and p.parent.name != "critique"}
    )


#: Sentences that MUST be flagged.
_MUST_FLAG = (
    "The assembled bundle is notarization-ready.",
    "arXMCP.app is Gatekeeper-ready after assembly.",
    "The payload is signable-as-is.",
    "The artifact is ready for notarization.",
    "The bundle has been notarized.",
    "Code signing works.",
    "The app passes Apple's notarization.",
    # --- m15 critique M3/M7: every one of these reached the pre-fix gate and
    # returned MISS. The first is the positional case: the claim is made, then
    # a cue appears AFTER it.
    "The artifact is ready for notarization and needs no layout change.",
    "The app bundle will notarize as-is.",
    "The bundle should notarize without further work.",
    "Assembly produces a notarizable .app.",
    "The payload is signed and ready for distribution.",
    "The artifact satisfies Apple's notarization requirements.",
    "The assembled bundle is notarization-ready, so no further work is needed.",
    "arXMCP.app is Gatekeeper-ready and must be shipped as-is.",
)

#: Sentences that must NOT be flagged — every one is either a real sentence
#: from the ADR/briefs or the honest phrasing this milestone has to be able to
#: write. Over-firing would make the honest text unwritable, which is the same
#: defect as under-firing.
_MUST_NOT_FLAG = (
    "No document, string, comment, commit message or acceptance claim may assert "
    "that the artifact is notarization-ready, Gatekeeper-ready, signable-as-is, "
    "or that its signing works.",
    "Whether the assembled bundle is notarization-ready is OPEN and unanswerable here.",
    "Nothing in this repository can settle whether any layout in this ADR survives "
    "Apple's notary service.",
    "The bundle is not notarized and this milestone does not claim it is.",
    "dylibs shipped through the macOS frameworks mechanism are signed and do notarize.",
    "A PyInstaller app notarizes as --onefile but fails Apple's notary as --onedir.",
    "Closing it requires a build-and-submit trial under a Developer ID certificate.",
    "The payload is signed ad-hoc, which is not a distribution signature.",
    # The live case that calibrated the "block" cue: m15's own research
    # synthesis says the milestone is BLOCKED from claiming readiness, which a
    # negation-only cue set read as the claim itself.
    "It blocks m15 from claiming the layout is notarization-ready.",
)


class TestScannerControls:
    """A scanner reporting zero because it is broken looks exactly like one
    reporting zero because the corpus is clean — prove both arms."""

    @pytest.mark.parametrize("sentence", _MUST_FLAG)
    def test_flags_a_claim(self, sentence: str):
        assert _find_unearned_claims(sentence), (
            f"unearned notarization claim not detected: {sentence!r}"
        )

    @pytest.mark.parametrize("sentence", _MUST_NOT_FLAG)
    def test_accepts_an_honest_statement(self, sentence: str):
        assert _find_unearned_claims(sentence) == [], (
            f"honest statement wrongly flagged: {sentence!r}"
        )


class TestScanScope:
    def test_the_adr_is_inside_this_scan_set(self):
        """The scope decision recorded in this module's docstring, asserted.

        m9's scanner does NOT cover `.claude/docs/`; if a later refactor
        re-points this module at m9's `_shipped_docs`, the document most
        likely to carry the claim would leave the gate silently.
        """
        files = scanned_files()
        assert ADR in files, ".claude/docs/ must be in scope; that is the whole scope delta"
        assert REPO_ROOT / "apps" / "desktop" / "README.md" in files
        assert (
            REPO_ROOT / "apps" / "desktop" / "pyinstaller" / "desktop_package.py"
        ) in files, "the signing code's own docstrings are in scope"
        assert REPO_ROOT / "CLAUDE.md" not in files, "agent-facing docs stay excluded"

    def test_scan_set_is_not_vacuous(self):
        assert len(scanned_files()) >= 10, "an empty scan set is a broken scan, not a clean run"


class TestNoUnearnedNotarizationClaim:
    def test_no_scanned_file_claims_notarization_readiness(self):
        offenders = {
            str(path.relative_to(REPO_ROOT)): found
            for path in scanned_files()
            if (found := _find_unearned_claims(path.read_text(encoding="utf-8")))
        }
        assert offenders == {}, (
            f"notarization/Gatekeeper readiness claims with no notary submission "
            f"behind them: {offenders}. Decision 3 of the bundle-assembly ADR "
            f"forbids these until a build-and-submit trial under a Developer ID "
            f"certificate has run; such a claim may land only together with the "
            f"notary log and a revision of this gate."
        )

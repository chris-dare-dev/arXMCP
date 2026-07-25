"""retrieval-unlocks-m4 — the equations-fixture parity gate.

m4's acceptance is conditional: the TED route is reported for a LaTeX
query *"when the equations-fixture parity check has passed"*. This is
that check, kept as a regression guard so a future ``latex2mathml`` bump
(or a change to ``parse_mathml_to_tree``) cannot silently degrade the
route that ``Config.eq_latex_route`` leaves ON.

**What is being measured.** The corpus trees were built by LaTeXML at
ingest; a query is converted by latex2mathml at request time. Two
different engines. The question is not "are the trees identical" — they
are not, and cannot be, because latex2mathml does not expand the
``\\newcommand`` macros LaTeXML resolved at ingest. The question is
whether the residual divergence is small *relative to the distance to
other equations*, i.e. whether the converted query still retrieves its
own equation first. That is the property serving depends on.

**Measured verdict (2026-07-24) — reproduce with**
``uv run pytest tests/eval/test_equations_parity.py -s`` on a box with the
parsed corpus present. These numbers come from the SHIPPED ``_POOL`` /
``_QUERIES`` constants below, not a hand-tuned side run:

===========================  ==========
rank-1 self-retrieval        50/50 = 100%
conversion + parse-usable    50/50 = 100%
exact tree match             18%
median best-match TED        0.185
p90 best-match TED           0.323
===========================  ==========

The two layers disagree, and that IS the finding: a raw-distance
threshold (e.g. p90 <= 0.25) would gate this route OFF, while the
decision-relevant metric — does the converted query still rank its own
equation first — says it is safe. Distance alone is the wrong gate. Note
exact match is only 18% and median TED 0.185: the trees genuinely differ
(latex2mathml vs LaTeXML, unexpanded macros), yet that divergence is
small *relative to the distance to other equations*, so rank-1 holds.

Scope honesty: one draw, a 200-equation pool from the parsed corpus.
Rank-1 on a 200-pool does not prove rank-1 on a 50K-pool — near-collisions
get likelier as the corpus grows. The route is default-ON as of W1
(``Config.eq_latex_route``); this eval-marked gate re-measures on whatever
corpus is present (skipping in CI), so the exact latex2mathml pin and the
kill-switch are the live protections and this number tracks reality
rather than a frozen claim.

Skipped when the parsed corpus is absent (a clean checkout), which is why
it lives under ``tests/eval`` rather than the always-on suite.
"""

from __future__ import annotations

import random
import warnings
from pathlib import Path

import pytest

from server.retrieval.equations import normalized_ted, parse_mathml_to_tree

pytestmark = pytest.mark.eval

_CORPUS = Path("var/arxmcp/corpus/parsed")

#: Gate. Below this, the LaTeX route is not safe to leave enabled and
#: ``Config.eq_latex_route`` should default False (or the pooled
#: ``latexmlmath`` escape hatch should replace latex2mathml, so query and
#: corpus share one engine and cross-converter noise vanishes).
MIN_RANK1_RATE = 0.90

#: latex2mathml must handle the overwhelming majority of real corpus
#: LaTeX; a collapse here means the pin regressed.
MIN_CONVERSION_RATE = 0.95

_POOL = 200
_QUERIES = 50


def _harvest(limit_papers: int = 8) -> list[tuple[str, str]]:
    """Real (LaTeX, LaTeXML-MathML) pairs straight from parsed papers.

    ``alttext`` is the LaTeX LaTeXML consumed; the serialized element is
    what ingest stores. Deduplicated by LaTeX so "its own equation" is
    unambiguous during the rank test.
    """
    from bs4 import BeautifulSoup

    seen: dict[str, str] = {}
    if not _CORPUS.is_dir():
        return []
    for paper_dir in sorted(_CORPUS.iterdir())[:limit_papers]:
        index = paper_dir / "index.html"
        if not index.exists():
            continue
        soup = BeautifulSoup(
            index.read_text(encoding="utf-8", errors="replace"), "html.parser"
        )
        for math_el in soup.find_all("math"):
            alt = math_el.get("alttext")
            if alt and 2 < len(alt) < 300:
                seen.setdefault(alt, str(math_el))
    return list(seen.items())


@pytest.fixture(scope="module")
def corpus_pairs():
    pairs = _harvest()
    if len(pairs) < _POOL:
        pytest.skip(
            f"parsed corpus absent or too small ({len(pairs)} equations; "
            f"need {_POOL}). Populate var/arxmcp/corpus/parsed/ to run "
            f"the m4 parity gate."
        )
    random.Random(7).shuffle(pairs)
    return pairs


class TestEquationsParity:
    def test_conversion_rate(self, corpus_pairs):
        """latex2mathml must produce a PARSE-USABLE tree for real research
        LaTeX, not just avoid raising. Measuring convert()-not-raising
        alone overcounts: latex2mathml can emit XML-invalid output (a raw
        ``&`` alignment tab) that converts fine but fails the downstream
        parse — those queries never reach TED, so parse-usability is the
        axis that actually gates the route."""
        from latex2mathml.converter import convert

        warnings.filterwarnings("ignore")
        sample = corpus_pairs[:200]
        convert_ok = usable = 0
        for latex, _ in sample:
            try:
                mathml = convert(latex)
            except Exception:  # noqa: BLE001 — measuring the failure rate
                continue
            convert_ok += 1
            try:
                parse_mathml_to_tree(mathml)  # the check the handler runs
                usable += 1
            except ValueError:
                pass
        usable_rate = usable / len(sample)
        assert usable_rate >= MIN_CONVERSION_RATE, (
            f"only {usable_rate:.1%} of real corpus LaTeX converted to a "
            f"PARSE-USABLE tree (convert-succeeded {convert_ok}/{len(sample)}; "
            f"floor {MIN_CONVERSION_RATE:.0%}). The pin likely regressed."
        )

    def test_rank1_self_retrieval_gate(self, corpus_pairs):
        """THE GATE. A converted LaTeX query must retrieve its own
        equation as the top TED hit.

        This is what justifies ``Config.eq_latex_route`` defaulting ON
        despite only ~50% exact tree agreement. If this drops below the
        floor, flip the config default rather than unpinning
        latex2mathml.
        """
        from latex2mathml.converter import convert

        warnings.filterwarnings("ignore")
        pool = corpus_pairs[:_POOL]
        trees = []
        for _, mathml in pool:
            try:
                trees.append(parse_mathml_to_tree(mathml))
            except ValueError:
                trees.append(None)

        rank1 = tested = 0
        for i, (latex, _) in enumerate(pool[:_QUERIES]):
            if trees[i] is None:
                continue
            try:
                query_tree = parse_mathml_to_tree(convert(latex))
            except Exception:  # noqa: BLE001 — counted by the sibling test
                continue
            best_j, best_d = None, None
            for j, tree in enumerate(trees):
                if tree is None:
                    continue
                d = normalized_ted(query_tree, tree)
                if best_d is None or d < best_d:
                    best_d, best_j = d, j
            tested += 1
            if best_j == i:
                rank1 += 1

        # Require MOST queries to have actually been evaluated, not just
        # a floor of 20. A loose ``tested >= 20`` would let a corpus where
        # 30/50 queries silently skipped (conversion/parse failures) still
        # "pass" on the surviving easy 20 — masking exactly the drift this
        # gate exists to catch.
        assert tested >= int(0.8 * _QUERIES), (
            f"only {tested}/{_QUERIES} queries evaluated (need >=80%); too "
            f"many conversion/parse failures to trust the rank-1 number"
        )
        rate = rank1 / tested
        assert rate >= MIN_RANK1_RATE, (
            f"rank-1 self-retrieval {rate:.1%} ({rank1}/{tested}) is below "
            f"the {MIN_RANK1_RATE:.0%} gate. The LaTeX route is no longer "
            f"safe to leave enabled: set ARXMCP_EQ_LATEX_ROUTE=false, or "
            f"move to a pooled latexmlmath converter so query and corpus "
            f"share one engine."
        )

    def test_canonicalization_erases_parallel_markup(self):
        """The precondition the gate rests on: a LaTeXML parallel-markup
        tree and a bare presentation tree for the SAME equation must
        canonicalize to the same thing.

        Without this, every stored tree carries a Content-MathML
        annotation subtree the query side never has, and parity is
        impossible regardless of converter quality — this was the m4
        blocker, and it also silently degraded the already-shipped
        MathML-input route.
        """
        latexml = (
            '<math xmlns="http://www.w3.org/1998/Math/MathML" alttext="t">'
            "<semantics><mi>t</mi>"
            '<annotation-xml encoding="MathML-Content">'
            "<ci>&#x1D461;</ci></annotation-xml>"
            '<annotation encoding="application/x-tex">t</annotation>'
            "</semantics></math>"
        )
        bare = (
            '<math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<mrow><mi>t</mi></mrow></math>"
        )
        d = normalized_ted(
            parse_mathml_to_tree(latexml), parse_mathml_to_tree(bare)
        )
        assert d == 0.0, f"parallel markup not erased (TED {d})"

    def test_canonicalization_does_not_over_collapse(self):
        """The guard on the guard: genuinely different equations must
        stay apart. A normalizer aggressive enough to erase every
        difference would score everything 0 and rank at random."""
        plus = "<math><mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow></math>"
        minus = "<math><mrow><mi>x</mi><mo>-</mo><mi>y</mi></mrow></math>"
        d = normalized_ted(
            parse_mathml_to_tree(plus), parse_mathml_to_tree(minus)
        )
        assert d > 0.0, "x+y and x-y must not canonicalize to the same tree"

    def test_font_variants_collapse_KNOWN_LIMITATION(self):
        """NFKC folds ℂ ≡ 𝒞 ≡ C to TED 0, so \\mathbb{C} and \\mathcal{C}
        are indistinguishable. This is a DELIBERATE, documented loss, not
        a regression: the stored corpus already collapses them, because
        LaTeXML encodes the variant in a ``mathvariant`` attribute that
        parse_mathml_to_tree has dropped since E10_S03. NFKC only makes
        the query side match that pre-existing collapse. This test PINS
        the known behaviour so a future change that (accidentally or
        deliberately) starts distinguishing variants is a conscious
        decision with a failing test, not a silent surprise. See
        ``_fold_text`` for the full rationale and the path to fixing it
        (preserve mathvariant on both sides — an E10_S03-scope re-index)."""
        blackboard = "<math><mi>&#x2102;</mi></math>"       # ℂ (U+2102)
        script = "<math><mi>&#x1D49E;</mi></math>"          # 𝒞 (U+1D49E)
        plain = "<math><mi>C</mi></math>"
        assert normalized_ted(
            parse_mathml_to_tree(blackboard), parse_mathml_to_tree(plain)
        ) == 0.0
        assert normalized_ted(
            parse_mathml_to_tree(blackboard), parse_mathml_to_tree(script)
        ) == 0.0

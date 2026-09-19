"""Bridging graduate-textbook proposals (WS-E v0).

The proposed notebook manifest carries "bridging graduate textbooks"
alongside the papers (workstreams.md §WS-E) — the texts an operator
would ingest through the textbook lane (``tools/notebook_textbook_ingest``)
to give agents the background a 3-12-month paper window presumes.

v0 heuristic: a CURATED table keyed by arXiv category (the project's
target categories plus the harmonic-analysis pair the fourier-duality
notebooks exercise), refined by topic-keyword overlap. Deterministic,
LLM-free, and honest about being a curated table — every proposal's
``source`` string says exactly that (AC-E.4 applies to textbooks too:
no unexplained entries).

This is data-as-code on purpose: the table is small, reviewed in
diffs, and versioned with the pipeline. If it outgrows code (or wants
per-notebook overrides), it moves to contract data — the same
data-not-code path Stage 1 chose for calibration thresholds (WS-C).
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.exploration.sources import informative_tokens

#: Default number of textbook proposals per manifest.
DEFAULT_TEXTBOOK_CAP = 4


@dataclass(frozen=True)
class TextbookEntry:
    """One curated bridging-textbook row."""

    title: str
    author: str
    topics: frozenset[str]


#: Curated per-category graduate-textbook table (v0).
BRIDGING_TEXTBOOKS: dict[str, tuple[TextbookEntry, ...]] = {
    "math.AG": (
        TextbookEntry(
            "Algebraic Geometry",
            "R. Hartshorne",
            frozenset({"scheme", "schemes", "sheaf", "sheaves", "cohomology", "varieties"}),
        ),
        TextbookEntry(
            "Fourier-Mukai Transforms in Algebraic Geometry",
            "D. Huybrechts",
            frozenset(
                {"derived", "category", "categories", "fourier", "mukai", "stability",
                 "bridgeland", "moduli"}
            ),
        ),
        TextbookEntry(
            "The Geometry of Moduli Spaces of Sheaves",
            "D. Huybrechts and M. Lehn",
            frozenset({"moduli", "sheaves", "stability", "bundles", "surfaces"}),
        ),
    ),
    "math.NT": (
        TextbookEntry(
            "Algebraic Number Theory",
            "J. Neukirch",
            frozenset({"ideal", "ideals", "ramification", "adele", "adeles", "zeta"}),
        ),
        TextbookEntry(
            "The Arithmetic of Elliptic Curves",
            "J. H. Silverman",
            frozenset({"elliptic", "curves", "rational", "points", "heights", "isogeny"}),
        ),
        TextbookEntry(
            "A Course in Arithmetic",
            "J.-P. Serre",
            frozenset({"quadratic", "forms", "modular", "dirichlet", "primes"}),
        ),
    ),
    "math.CA": (
        TextbookEntry(
            "A Course in Abstract Harmonic Analysis",
            "G. B. Folland",
            frozenset({"harmonic", "duality", "pontryagin", "locally", "compact", "abelian",
                       "haar"}),
        ),
        TextbookEntry(
            "An Introduction to Harmonic Analysis",
            "Y. Katznelson",
            frozenset({"fourier", "series", "harmonic", "transform", "convolution"}),
        ),
    ),
    "math.FA": (
        TextbookEntry(
            "Functional Analysis",
            "W. Rudin",
            frozenset({"banach", "hilbert", "operator", "operators", "spectral", "duality"}),
        ),
    ),
    "math-ph": (
        TextbookEntry(
            "Methods of Modern Mathematical Physics I: Functional Analysis",
            "M. Reed and B. Simon",
            frozenset({"operator", "operators", "spectral", "quantum", "hamiltonian"}),
        ),
        TextbookEntry(
            "Geometry, Topology and Physics",
            "M. Nakahara",
            frozenset({"gauge", "bundles", "topology", "manifolds", "index"}),
        ),
    ),
    "hep-th": (
        TextbookEntry(
            "Mirror Symmetry",
            "K. Hori et al. (Clay Mathematics Monographs)",
            frozenset({"mirror", "symmetry", "branes", "calabi", "yau", "strings"}),
        ),
    ),
}


def propose_textbooks(
    categories: list[str],
    topic_text: str,
    *,
    cap: int = DEFAULT_TEXTBOOK_CAP,
) -> list[dict[str, str]]:
    """Curated bridging-textbook proposals for the manifest.

    Entries from the requested categories (in request order), ranked
    topic-matches first (matches = overlap between the entry's topic
    tokens and the informative tokens of ``topic_text``), stable
    within rank. Unknown categories contribute nothing (recorded by
    the caller via the empty result, not an error — a new category is
    a table gap, not a pipeline failure).
    """
    if cap < 1:
        raise ValueError(f"cap must be >= 1, got {cap}")
    topic_tokens = informative_tokens(topic_text)

    matched: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    seen: set[str] = set()
    for category in categories:
        for entry in BRIDGING_TEXTBOOKS.get(category, ()):
            if entry.title in seen:
                continue
            seen.add(entry.title)
            overlap = sorted(entry.topics & topic_tokens)
            source = f"curated bridging-textbook table v0: category {category}"
            if overlap:
                shown = ", ".join(overlap[:4])
                matched.append(
                    {
                        "title": entry.title,
                        "author": entry.author,
                        "source": f"{source}; topic match {{{shown}}}",
                    }
                )
            else:
                unmatched.append(
                    {"title": entry.title, "author": entry.author, "source": source}
                )
    return (matched + unmatched)[:cap]


__all__ = [
    "BRIDGING_TEXTBOOKS",
    "DEFAULT_TEXTBOOK_CAP",
    "TextbookEntry",
    "propose_textbooks",
]

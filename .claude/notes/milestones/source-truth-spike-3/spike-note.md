---
milestone_id: "source-truth-spike-3"
injection_attempts: 0
---

# Spike 3 — is the m2 span-anchor scheme stable across LaTeXML re-parses?

Roadmap acceptance criterion (`R1-source-truth.md` "should" assumption, lines 85-88): re-parse
5 papers through LaTeXML, diff `(element_id, char_offsets, normalized_text_hash)` anchors;
instability moves the anchor to `(revision_checksum + normalized_text_hash)` only.

## Method

**Papers used** (all 5 are new-style arXiv IDs on `bridgeland-stability`'s `papers.txt`, each
confirmed to have raw source on disk at `var/arxmcp/corpus/raw/<id>/` and an original parse at
`var/arxmcp/corpus/parsed/<id>/index.html`):

| paper_id | raw source | title (from parsed HTML) |
|---|---|---|
| 0705.3794 | `0705.3794.tex` (60 KB) | Stability conditions on curves |
| 0708.2247 | `0708.2247.tex` (104 KB) | Bridgeland-stable moduli spaces for K-trivial surfaces |
| 0711.1734 | `0711.1734.tex` (128 KB) | (Bridgeland-stability corpus paper) |
| 0712.1083 | `large-volume-stability.tex` (228 KB) | Large volume stability conditions |
| 0808.3351 | `0808.3351.tex` (72 KB) | (Bridgeland-stability corpus paper) |

**Toolchain grounding.** Confirmed `latexmlc` (LaTeXML 0.8.8, Strawberry Perl) is installed and
functional on this box, but *only* through the repo's own wrapper. A bare `latexmlc --version`
invoked directly from the shell fails (`Can't locate File/Which.pm in @INC`) because the shell's
`PATH` resolves the extensionless `latexmlc` script to Git Bash's bundled msys2 `perl`
(`/usr/bin/perl`), which lacks LaTeXML's XS dependencies — this is a live reproduction of the
exact landmine documented in `tools/arxiv_fetch.py::_find_perl_for_latexmlc` (lines 554-574) and
`_latexmlc_argv_prefix` (lines 577-605), which a concurrent session added specifically to route
around it (resolves `C:\Strawberry\perl\bin\perl.exe` next to the Strawberry `site/bin/latexmlc`
script and invokes `[perl.exe, <script>]` directly). Confirmed that path resolves correctly on
this box. Per the spike's instructions, all re-parses below went through this wrapper
in-process (`tools.arxiv_fetch.parse_with_latexml`), not a shell call, to "match production."

**Isolation.** Each paper's raw source tree was copied to
`<scratch>/spike3/source_copies/<id>/` *before* any LaTeXML invocation; `parse_with_latexml`'s
`cwd` and `--dest` both pointed only at scratch paths. Verified afterward that
`var/arxmcp/corpus/raw/<id>/` and `var/arxmcp/corpus/parsed/<id>/index.html` kept their original
(2026-06-03/04) mtimes — the live corpus was never written to.

**A wrinkle that reshaped the comparison design.** The "original" `parsed/<id>/index.html` files
are *not* local-latexmlc output. Their `<head>` carries ar5iv branding (ar5iv CSS/JS, `og:url`
pointing at `ar5iv.labs.arxiv.org`) and an explicit
`<!--Generated on ... by LaTeXML (version 0.8.8) http://dlmf.nist.gov/LaTeXML/.-->` stamp dated
**March 2024** — confirmed against `ingest/ar5iv_fetch.py` (module docstring, lines 3-34;
`AR5IV_BASE_URL = "https://ar5iv.labs.arxiv.org/html"` at line 60), which is what actually
populated this notebook's `parsed/` tree: a **remote** ar5iv pre-render, not this repo's local
`latexmlc` lane. This is exactly the second scenario the spike brief itself names ("new LaTeXML
build, **or ar5iv→local re-ingest**"), and `ingest/chunker_types.py`'s planned `parser_used`
column (lines 142-147: enum `{"ar5iv", "latexml", "mineru+latexml"}`) confirms the corpus is
knowingly mixed-provenance. So instead of one diff, this spike ran **two**, isolating the two
named risk scenarios:

- **`original` vs `reparse_A`** — ar5iv-remote (2024) vs local `latexmlc` 0.8.8 (today), same raw
  source. Tests the "ar5iv→local re-ingest" scenario.
- **`reparse_A` vs `reparse_B`** — the *same* local `latexmlc` 0.8.8 build invoked twice,
  back-to-back, on the identical source copy. The closest available proxy for "new LaTeXML
  build" stability (only one LaTeXML version is installed on this box, so a genuine
  cross-version diff wasn't possible — recorded as a limitation, not worked around).

All 10 local `latexmlc` invocations (5 papers × 2 runs) succeeded (`exit_code=0`,
`mathml_node_count>0`); wall time ranged 33s–111s per run. For every paper, run A and run B
produced **byte-identical output file size and MathML node count**.

**Anchor extraction.** Reused the real chunker code, not a reimplementation: imported
`ingest.chunker._element_text` (the math-fidelity-preserving text extractor, lines 328-362),
`_THEOREM_CLASS_RE` (line 99), and `_SECTION_DIV_CLASSES` (lines 154-161) directly. For each of
the 3 HTML variants per paper, sampled up to 8 evenly-spaced blocks each of `section`, `theorem`
(any `ltx_theorem_*` div), and `paragraph` (`<p class="ltx_p">`) — fewer when a paper had fewer
than 8 of a kind (e.g. 0708.2247 has only 5 sections). Blocks were matched **across variants by
ordinal position** (1st theorem, 2nd theorem, …), not by id, since id stability is exactly what's
under test. For each sampled block: `element_id` = the tag's `id` attribute;
`normalized_text_hash` = `sha256(_element_text(block))`; `char_offset` — m2 has not implemented
span extraction yet, so this spike defines it operationally as the index of
`_element_text(block)` as a substring of `_element_text(<body>)` (the whole-document text
stream), located with a forward-advancing per-kind cursor to reduce false matches on repeated
short strings. Block *collection* used simple `soup.find_all` rather than replaying the
chunker's full sibling-pairing state machine — a documented simplification that does not affect
id/offset/hash extraction, which calls the real `_element_text`.

Driver scripts (kept in scratch, not the repo): `reparse_driver.py`, `diff_anchors.py`,
`compare_report.py`.

## Measurements

**Structural block counts — identical across all 3 variants for every paper** (no blocks
gained, lost, split, or merged by either re-parse):

| paper_id | sections | theorems | paragraphs |
|---|---|---|---|
| 0705.3794 | 9 | 33 | 148 |
| 0708.2247 | 5 | 35 | 270 |
| 0711.1734 | 28 | 47 | 224 |
| 0712.1083 | 35 | 31 | 298 |
| 0808.3351 | 8 | 36 | 243 |

**Per-component match rate — `original` (ar5iv remote) vs `reparse_A` (local latexmlc):**

| paper_id | n sampled | element_id match | char_offset match | text_hash match |
|---|---|---|---|---|
| 0705.3794 | 24 | 67% | 17% | 71% |
| 0708.2247 | 21 | 62% | 10% | 52% |
| 0711.1734 | 24 | 67% | 8% | 38% |
| 0712.1083 | 24 | 67% | 12% | 75% |
| 0808.3351 | 24 | 67% | 8% | 46% |
| **all 5 (n=117)** | | **66%** | **11%** | **56%** |

**Per-component match rate — `reparse_A` vs `reparse_B` (same LaTeXML 0.8.8 build, same
source, run twice):**

| paper_id | n sampled | element_id match | char_offset match | text_hash match |
|---|---|---|---|---|
| 0705.3794 | 24 | 100% | 100% | 100% |
| 0708.2247 | 21 | 100% | 100% | 100% |
| 0711.1734 | 24 | 100% | 100% | 100% |
| 0712.1083 | 24 | 100% | 100% | 100% |
| 0808.3351 | 24 | 100% | 100% | 100% |
| **all 5 (n=117)** | | **100%** | **100%** | **100%** |

**`original` vs `reparse_A`, broken down by block kind (aggregated across all 5 papers)** — the
kind matters more than paper identity:

| kind | n | element_id | char_offset | text_hash |
|---|---|---|---|---|
| section | 37 | 100% | 16% | 16% |
| theorem | 40 | 100% | 5% | 62% |
| paragraph | 40 | **0%** | 12% | 88% |

**Char-offset drift magnitude** (`original` vs `reparse_A`, 117 sampled blocks): only 13/117
(11%) matched exactly (delta = 0); 1 was off by 1-5 chars; 43 (37%) were off by 6-50 chars; 60
(51%) were off by 51-500 chars; max drift observed was 418 characters. This is not
whitespace-collapsing noise — it is large enough to resolve to the wrong sentence or an
adjacent block entirely.

**Concrete examples:**

- *Paragraph ids are pipeline-added, not LaTeXML-core.* ar5iv assigns explicit paragraph ids
  (`S2.p6.2`, `S3.SS1.p5.2`, `S3.Thmtheorem9.p3.1`, …); the bare local `latexmlc --format=html5`
  invocation (`tools/arxiv_fetch.py`'s exact production command) assigns **no id at all** to any
  `<p>` tag, in every one of the 40 sampled paragraphs across all 5 papers. Section/theorem
  auto-ids (`S3.Thmthm1`, `Thmdefix1`, …), by contrast, matched exactly in 100% of samples —
  those come from LaTeXML's own environment counters, not ar5iv's postprocessing.
- *Content-level drift, not just repositioning.* 0708.2247 ordinal 8 (Lemma 3.1): the first
  70 characters are identical between `original` and `reparse_A`, but the full block text
  diverges deeper in — `reparse_A` embeds a literal stray `% ` token into a math `alttext`
  right next to a `\cO` (`\def\cO{{\mathcal O}}`, source line 107) macro expansion, where
  `original` has none. Traced to macro/comment-handling in that pipeline difference; exact
  mechanism not fully isolated, but it demonstrates real (not merely positional) text
  divergence between ar5iv and a bare local `latexmlc` run of nominally the same LaTeXML
  version.
- *Offset drift compounds through the document.* 0708.2247's theorem-block offsets drift from
  +38 chars (1st sampled theorem) to +216 chars (8th sampled theorem) — small per-block
  rendering differences accumulate monotonically as the document progresses.

## Verdict

**The full `(element_id, char_offsets, text_hash)` anchor is UNSTABLE**, per the roadmap's own
decision rule (element-id or char-offset drift → unstable). `char_offset` is the clear failure:
only 11% of sampled blocks kept the same offset across an ar5iv→local re-ingest, with drift up
to 418 characters — nowhere close to usable for direct resolution. This alone triggers the
fallback clause regardless of the id result.

The instability is **cross-pipeline, not inherent to LaTeXML**: `reparse_A` vs `reparse_B` (same
installed build, same source, run twice) matched on **all three components for all 117 sampled
blocks with zero exceptions** — full byte-level determinism when the pipeline is held fixed. The
drift observed in `original` vs `reparse_A` comes from ar5iv's postprocessing differing from a
bare local `latexmlc --format=html5` run (paragraph-id injection, and small but real alttext
rendering differences that compound across a document) — not from LaTeXML re-parsing the same
source nondeterministically. One caveat: because both sides happen to report LaTeXML version
0.8.8, this spike could not test drift from an actual *LaTeXML version upgrade* — only one build
is installed on this box, so element-id robustness against a real version bump remains
unvalidated, not confirmed safe.

**Recommendation: anchor on `(revision_checksum + normalized_text_hash)` only**, per the
roadmap's fallback clause, with two refinements the data supports:

1. `normalized_text_hash` itself is only reliable at **fine (chunk-body) granularity** —
   88% stable for paragraphs, 62% for individual theorem statements, but only 16% for whole
   sections. Hash at the same grain the chunker already persists as `body_text`
   (`ingest/chunker.py`'s per-theorem / per-proof-window / per-paragraph units), never at
   whole-section grain.
2. `element_id` is not reliable enough to be authoritative (0% for un-id'd content like
   paragraphs, and its 100% showing for section/theorem anchors is not yet proven safe across a
   genuine LaTeXML version change) but costs nothing to store as a best-effort debug hint
   alongside the checksum+hash pair.

## Implication for m2

`source_span` should NOT persist `char_offsets` as a resolving field — store `element_id` only
as a non-authoritative hint, and make `(source_revision_id checksum, sha256(normalized
body-grain text))` the sole resolving key, computed at the same block granularity the chunker
already emits (never whole-section). Because that composite key can legitimately fail to
resolve against a differently-piped re-parse (as this spike demonstrates for real, non-adversarial
content), a resolution miss must surface as `source_span: null` / abstention — never a
best-guess offset — consistent with the project's fail-closed, abstention-first trust policy
(`.claude/docs/trust-language-policy.md`; CLAUDE.md §4.9). Given the corpus is confirmed
mixed-provenance (ar5iv-remote vs local-latexmlc vs future mineru+latexml), `source_span`
resolution should also consult the already-planned `parser_used` column
(`ingest/chunker_types.py:142-147`) so a re-anchor attempt against a stale ar5iv-sourced row can
flag "cross-provenance, verify before trusting" rather than silently accepting or rejecting a
hash match with no context for *why* it might legitimately differ.

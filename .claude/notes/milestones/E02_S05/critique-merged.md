# Critique — E02_S05

**Critic:** adversary
**Generated:** 2026-05-07T14:35:00Z
**Commit range:** 0528501..767174b
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: 1 CRITICAL, 3 HIGH, 4 MEDIUM, 1 LOW. The fixture suite reproduces byte-identically across all 10 papers and all 123 chunker tests pass in 2.25s, but the most marquee fixture (2307.00010 "MathML alttext preservation") locks in fake LaTeX content (literal `\\langle` two-char escape, never produced by real LaTeXML), so its chunk_ids encode behavior on input that real arXiv papers will never feed the chunker.
- Highest-risk file: `tests/fixtures/chunker/2307.00010/index.html:11` (alttext attribute uses double-backslash, see F1).
- The byte-stability lock works (re-running the chunker reproduces every chunk_id), so the *mechanical* contract is sound; the issue is that several fixtures encode the wrong scenario despite their docstrings/table claiming otherwise (F1, F2, F3).
- `kind_counts` pinning only stmt/proof/section/definition leaves 5 of 10 chunks unaccounted for in 2307.00002 — confusing and silently lets lemma/corollary/remark/example drift undetected (F4).
- The "60-second budget" headroom assumes a warm BGE-M3 tokenizer cache; first-run cold-start downloads ~5 MB at test time and is undocumented (F5).
- Cross-axis pattern: docs/chunker-fixtures.md describes scenarios the test surface does NOT actually verify (section_path correctness for nested fixture, document-order for appendix-after-main fixture). The fixtures cover scenarios in name only — F2 + F3.
- Regeneration runbook is missing the "do NOT regenerate the HTML, only the expected.json" guard rail (F6) and leaks tempdirs (F7).
- `_resolve_preamble_doc` patched to None for ALL fixtures forecloses any future fixture exercising the preamble-prepended embedding-input view — a deliberate but undocumented design lock-in (F9).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — alttext fixture uses literal `\\langle` (double-backslash), not real LaTeX

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** tests/fixtures/chunker/2307.00010/index.html:11
- **What:** The `<math alttext="...">` attributes in 2307.00010 use double-backslash escapes (`\\langle\\cdot,\\cdot\\rangle`, `\\bullet`, `\\omega_X = \\bigwedge^{\\dim X} \\Omega_X^1`). When BeautifulSoup reads these attributes (`node.get("alttext")` at `ingest/chunker.py:280`), the resulting Python string is the literal two-character sequence backslash-backslash-l-a-n-g-l-e — NOT the LaTeX command `\langle`. Verified by re-running the chunker: body_text for this fixture's section chunk is `'... the $\\\\langle\\\\cdot,\\\\cdot\\\\rangle$ element ...'` (eight characters of literal `\\langle`), and the locked chunk_ids are derived from that wrong text. The matching `TestF1MathMLPreservation` unit tests at `tests/test_chunker.py:879-907` correctly use single-backslash, so the fixture and the unit tests are testing different things despite both claiming to exercise F1.
- **Why it matters:** This is the marquee fixture for the "math fidelity DP1" mission claim — the project's reason-for-being. Real LaTeXML output writes `alttext="\langle\cdot,\cdot\rangle"` (HTML attribute single-backslash literal). The fixture pretends to lock in math-fidelity behavior while encoding content that no real paper produces. If the chunker ever broke single-backslash handling, the fixture wouldn't catch it; if F1 ever regressed in the opposite direction (stripping backslashes), the fixture's chunk_ids might still match by coincidence on broken double-backslash input. The byte-stability lock here is meaningless because the input it locks is fake.
- **Proposed fix:** Replace every double-backslash in `tests/fixtures/chunker/2307.00010/index.html` with a single backslash (e.g. `\\langle` → `\langle`). Re-bootstrap `2307.00010.expected.json` (chunk_ids will all change). Add a regression assertion to the fixture suite that for paper 2307.00010, the section chunk's body_text contains the substring `$\langle\cdot,\cdot\rangle$` (single-backslash) — that single assertion mechanically prevents this class of fixture-content fakery.
- **Regression guard:** New test `test_alttext_fixture_uses_real_latex` in `TestFixtureSuite` that loads 2307.00010 fixture, chunks it, and asserts `r"$\langle\cdot,\cdot\rangle$" in section_chunk.body_text`. The raw-string `r"..."` literal disambiguates from the bug.

### F2 — Deeply-nested section_path fixture is not actually tested for section_path

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_chunker.py:1296-1333
- **What:** Fixture 2307.00006 is described in `docs/chunker-fixtures.md:20` as "Deeply nested section path (3 levels)" and the HTML at `tests/fixtures/chunker/2307.00006/index.html:24-50` does correctly produce a 3-element section_path on the buried theorem (verified: `['1. Deep section nesting', '1.1 Outer subsection', '1.1.1 Inner subsubsection']`). But the parametrized `TestFixtureSuite` only asserts `chunk_count`, `kind_counts`, `expected_chunk_ids` membership, and `chunker_version` — none of which read `chunk.section_path`. If the section-path walker silently dropped the deepest level (e.g. `['1. Deep section nesting', '1.1 Outer subsection']`), the body_text would change → chunk_id would change → `test_expected_chunk_ids_present` would fire. So the byte-stability lock catches it INDIRECTLY via chunk_id drift. But the test failure message (`expected chunk_id ... not found in emitted ids — chunker output drift?`) gives zero hint that the actual problem is a missing section level. An operator debugging a section-path regression starting from "chunk_id drift in 2307.00006" must reverse-engineer the cause from chunk bodies.
- **Why it matters:** The fixture's pedagogical purpose (lock in section_path correctness for nested cases) is undermined by the lack of direct assertion. Worse, `body_text` does NOT actually include the section_path — the section_path is a separate ChunkRecord field. So in fact a section-path drift would NOT change chunk_id (chunk_id depends on body_text + preamble_text only, see `_compute_chunk_id` at `ingest/chunker.py:955`). The fixture is doubly broken: it neither asserts section_path directly NOR does the chunk_id hash incorporate section_path, so a section_path regression on this fixture is invisible to the entire test suite.
- **Proposed fix:** Add a test `test_deeply_nested_section_path` in `TestFixtureSuite` that runs 2307.00006, finds the stmt chunk, and asserts `chunk.section_path == ['1. Deep section nesting', '1.1 Outer subsection', '1.1.1 Inner subsubsection']` byte-exactly. (Three matching tests for stmt, proof — both should have the same path.)
- **Regression guard:** The new test itself.

### F3 — Appendix-after-main fixture has no document-order assertion

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_chunker.py:1321-1333
- **What:** Fixture 2307.00009 is described as "Appendix section after main (document-order check)" but `test_expected_chunk_ids_present` checks SUBSET membership (`for expected_id in expected["expected_chunk_ids"]: assert expected_id in emitted`), not order. If the chunker emitted appendix chunks before main chunks (e.g. someone refactored to bucket by class), the `chunk_count`, `kind_counts`, and `chunk_ids` would all still match — the test would pass while document order silently broke. Verified by reading the test: line 1325 builds `emitted = {c.chunk_id for c in chunks}` (a SET), discarding order. The `expected_chunk_ids` list IS in document order in the fixture file, but nothing checks that.
- **Why it matters:** Document order is the *named* purpose of this fixture per its docstring and the doc table. A regression in document-order emission (e.g. F4 from prior critique resurfacing) would not be caught. Section-2 lemma chunks emitted before section-1 theorem chunks is exactly the kind of drift this fixture exists to prevent, and the fixture cannot detect it.
- **Proposed fix:** Add a parametrized assertion `test_chunk_ids_in_document_order(paper_id)` that checks `[c.chunk_id for c in chunks] == expected["expected_chunk_ids"]` (list equality, not subset). This single change converts the entire suite from a subset-lock to an order-lock at near-zero cost. Or add a dedicated `test_2307_00009_appendix_order_preserved` if conservative.
- **Regression guard:** The list-equality assertion replaces or augments the current subset check.

### F4 — kind_counts schema leaves half the chunks unaccounted in 2307.00002

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/fixtures/chunker/2307.00002.expected.json:11-20
- **What:** The schema pins exactly four keys (`stmt`, `proof`, `section`, `definition`) per the brief. Verified emitted distribution for 2307.00002: `{stmt:1, proof:2, section:1, definition:1, lemma:1, corollary:1, example:1, remark:2}` = 10 chunks total. The expected.json records `chunk_count: 10` but `kind_counts` sums to 5. An operator reading the file sees half the chunks unidentified — confusing for code review, fixture audits, and future ML/eval-team handoffs. More importantly: a chunker change that flipped a `lemma` chunk to `theorem` (which doesn't exist as a kind, but bear with me) or replaced a `remark` with another chunk would not be caught by `test_kind_counts_match`, since it explicitly only counts kinds in the 4-element actual dict (`if c.kind in actual: actual[c.kind] += 1`, line 1314). Drift in lemma/corollary/remark/example/proposition/conjecture counts is invisible at the kind level — the only catch is via `expected_chunk_ids`, which is order-blind (F3).
- **Why it matters:** The brief literally specifies these 4 keys, but the implementation summary's design choice 2 ("kind_counts pins exactly 4 canonical kinds. Other kinds are emitted but not pinned per-fixture — the expected_chunk_ids list still locks them in via byte-stability") is over-confident given F2 and F3 above. Once you remove the section-path-via-chunk-id assumption (F2) and the order-lock assumption (F3), the chunk_id list does NOT in fact lock kind drift. Pinning ALL emitted kinds in `kind_counts` (e.g. `{stmt:1, proof:2, section:1, definition:1, lemma:1, corollary:1, remark:2, example:1}`) is a one-line change and makes drift visible in the test failure message rather than hidden in a chunk_id diff.
- **Proposed fix:** In the bootstrap procedure (docs/chunker-fixtures.md lines 76-79), replace the fixed-keys dict with a full Counter over emitted kinds. Re-bootstrap all 10 expected.json files; the existing 4 keys remain (just with siblings added). Update the `test_kind_counts_match` test to compare full dicts.
- **Regression guard:** The expanded `kind_counts` dict + matching test.

### F5 — Cold-start CI risk: BGE-M3 tokenizer download undocumented

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/chunker-fixtures.md:107
- **What:** Implementation summary claims "~2.5 seconds" — verified locally at 2.25s with a warm `~/.cache/huggingface`. On a fresh CI runner with no HuggingFace cache, the first call to `_get_tokenizer()` (`ingest/chunker.py:222`) downloads BGE-M3's tokenizer files (~5 MB tokenizer.json + sentencepiece). On a constrained CI network this can take 10-30s. The 60-second budget remains met in practice, but the "comfortably under" framing in the doc is misleading for cold runs and offers no explicit guidance ("pre-warm cache via X" or "skip these tests in offline CI").
- **Why it matters:** A future CI environment without internet (offline test mode, supply-chain-locked corp CI) will fail every parametrized fixture-suite test with a HuggingFace download error rather than a clean skip. The brief's "60s budget" risk note is unaddressed for that scenario.
- **Proposed fix:** Add a section to docs/chunker-fixtures.md noting (a) the suite requires HuggingFace access for first run, (b) the cache lives at `~/.cache/huggingface`, (c) for fully-offline CI, set `HF_HUB_OFFLINE=1` and pre-populate the cache with `python -c "from ingest.chunker import _get_tokenizer; _get_tokenizer()"` in a bootstrap step. No code change required.
- **Regression guard:** N/A (documentation finding).

### F6 — Regeneration runbook missing "do not regenerate HTML" guard rail

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/chunker-fixtures.md:96-103
- **What:** The "Regenerating after a chunker change" section says "Re-bootstrap all 10 expected.json files using the procedure above". The procedure above (lines 52-89) starts with step 1 "Author the HTML at tests/fixtures/chunker/<paper_id>/index.html" — which a future engineer following the runbook for an existing paper might re-execute, overwriting the committed static HTML with a fresh hand-edit and breaking determinism. Specifically risky for 2307.00007 (the multi-window-proof fixture) where the long body is committed verbatim in the HTML; a regeneration that "looks the same but slightly different word ordering" would silently produce different chunk_ids and the engineer would not realize the goldens changed for the wrong reason.
- **Why it matters:** The CHUNKER_VERSION-bump workflow described in the doc requires byte-exact re-bootstrapping, and the only thing keeping that byte-exact is the committed static HTML. A doc that conflates "bootstrap a NEW fixture" with "regenerate goldens for an EXISTING fixture" makes mistakes inevitable.
- **Proposed fix:** Add a step 0 to the "Regenerating" section: "**Do NOT modify any committed `index.html` files.** Regeneration only refreshes `<paper_id>.expected.json` from the existing committed HTML. To change a fixture's input, follow the bootstrap procedure as if it were a new fixture and update both files in lockstep with the eval-harness queries."
- **Regression guard:** N/A (documentation finding).

### F7 — Bootstrap procedure leaks tempdirs

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/chunker-fixtures.md:64
- **What:** The runbook calls `tempfile.mkdtemp()` and never cleans up. After bootstrapping all 10 fixtures, ten orphan directories remain under `/var/folders/.../e02_s05_bootstrap_*` (or wherever `mkdtemp` resolves). Implementation summary mentions only that the tmp directory is "left behind"; no explicit guidance to clean up.
- **Why it matters:** Operators following the runbook on shared infrastructure (CI runners, dev VMs) accumulate tens-of-MB of orphaned chunks and parsed HTML each regeneration. Low-impact, but trivially avoidable.
- **Proposed fix:** Wrap the runbook's example in `with tempfile.TemporaryDirectory() as tmp_str: tmp = Path(tmp_str)` so cleanup is automatic, OR add an explicit `shutil.rmtree(tmp)` at the end. Either way, fix the doc snippet.
- **Regression guard:** N/A.

### F8 — chunker_version test is parametrized but tests one constant

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_chunker.py:1335-1344
- **What:** `test_chunker_version_matches_constant` is `@pytest.mark.parametrize("paper_id", _FIXTURE_SUITE_IDS)` — 10 separate test invocations. Each loads a fixture, reads `chunker_version`, compares to `CHUNKER_VERSION`. If the constant bumps, ALL TEN tests fail with the same message. Pytest output becomes 10 redundant failure reports for one underlying issue, drowning out other genuine failures in the same test run. Also: the test does not call `_run` and so doesn't actually invoke the chunker — making the parametrization purely a fixture-loader, which is wasteful.
- **Why it matters:** Test signal-to-noise. A CI failure from a CHUNKER_VERSION bump should report once, not ten times.
- **Proposed fix:** Move `test_chunker_version_matches_constant` out of `TestFixtureSuite` (or into a new non-parametrized test that loops the fixture IDs in one assertion with a precise diff). Drop the `tmp_path` argument since it's unused.
- **Regression guard:** Refactor as part of the fix; existing assertion semantics preserved.

### F9 — _resolve_preamble_doc patched to None forecloses preamble-aware fixtures

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_chunker.py:1388
- **What:** `TestFixtureSuite._run` unconditionally patches `_resolve_preamble_doc` to return None for every fixture. Per implementation summary design choice 3, this is intentional because synthetic 2307.0000NN paper IDs have no `.tex` source. But this design lock means no fixture in the suite can ever exercise the preamble-prepended-to-body branch of `_compute_chunk_id` (chunker.py:955-980 region) — a critical invariant of E02_S02's preamble integration. A future engineer wanting to lock in preamble behavior cannot add a fixture without modifying the test infrastructure.
- **Why it matters:** The chunker's chunk_id formula is `sha256((preamble_text + NFC(body_text)).encode())[:16]` — preamble is half the input. The fixture suite covers exactly half of that input space. A regression in preamble handling (e.g. preamble_text dropped silently when set, or wrong preamble served for paper X) would not be caught by any fixture in this suite.
- **Proposed fix:** Document this design choice explicitly in `docs/chunker-fixtures.md` under a "Coverage gaps" section. Optionally: add one fixture whose `_run` allows a real preamble (by NOT patching `_resolve_preamble_doc` and instead pre-populating the preamble file under a patched `PREAMBLE_DIR`). Even a single such fixture closes the most glaring gap.
- **Regression guard:** Documented gap + (optional) one preamble-aware fixture.

### F10 — Doc table for 2307.00005 understates proposition count

- **Severity:** LOW
- **Source:** adversary
- **File:** docs/chunker-fixtures.md:19
- **What:** The scenario table says 2307.00005 emits "Other kinds: proposition, conjecture" without counts. Re-running shows 2 propositions + 1 conjecture (from the HTML's two `<div class="ltx_theorem ltx_theorem_proposition">` plus one conjecture div). The table's `Stmt | Proof | Section | Definition` columns show `0 | 1 | 1 | 0` correctly, but a reader scanning the table would assume one proposition + one conjecture from the singular phrasing. Cosmetic.
- **Why it matters:** Minor doc accuracy; trivially confusing.
- **Proposed fix:** Update the row to read "proposition × 2, conjecture × 1" explicitly. (Or apply F4's full-distribution `kind_counts` change so the table can read straight from expected.json.)
- **Regression guard:** N/A.

## What was done well

- **Byte-identical reproducibility verified end-to-end.** Re-running the chunker on all 10 fixtures with `_resolve_preamble_doc` patched to None reproduces every chunk_id from the committed expected.json files — zero drift across all 10 papers.
- **Tests genuinely fast.** Full chunker test suite (123 tests including 42 parametrized fixture-suite cases) runs in 2.25s on a warm cache, well inside the 60-second budget.
- **Test isolation done right.** Each parametrized case creates its own `tmp_path / "parsed"` and `tmp_path / "chunks"` — no cross-paper bleed possible. The patch context manager scopes the directory overrides cleanly.
- **Acceptance criteria mapping is explicit.** The implementation summary's table directly cross-references each acceptance criterion to a passing test; multi-window proof (2307.00007 → 3 proof chunks) and no-proof (2307.00008 → 0 proof chunks) both have dedicated assertion methods, not just byte-stability via chunk_ids.
- **The 600-word proof body is REAL prose, not placeholder.** 2307.00007's HTML contains actual mathematical-sounding word salad ("furthermore ideal divisor canonical submodule stalk...") committed verbatim, so the bootstrap is reproducible from the static HTML — no random seed buried in the runbook to tempt regeneration drift.
- **Pre-existing fixtures (2307.0000{1,2,3,4}) brought into the suite without HTML modification.** The new `_FIXTURE_SUITE_IDS` extends rather than rewrites prior coverage; existing `TestTwoTheoremGolden` / `TestMultiKindEnvironments` tests remain green and complement the new golden lock.
- **Hand-crafted HTML sidesteps LaTeXML version pinning.** The brief's risk note about LaTeXML drift is correctly addressed by using direct-authored HTML; the "real-corpus fixtures + LaTeXML pin" deferral is documented in docs/chunker-fixtures.md:109-111.
- **Chunker_version constant centralized.** `CHUNKER_VERSION` lives in one place (`ingest/chunker_types.py:28`) and the fixture test reads it directly — the deliberate single point of truth means a version bump fails fast.
- **Synthetic paper IDs use a clearly-fake namespace.** `2307.0000{01..10}` cannot collide with real arXiv submissions (real IDs of that form would already be archived in the corpus and have preamble.json files), making `_resolve_preamble_doc → None` patching safe.
- **Schema lives at fixture-file level (not embedded in test code).** `kind_counts`, `chunk_count`, `expected_chunk_ids`, `chunker_version`, `paper_id` keys are sorted, JSON-formatted, indent=2 — diff-friendly for code review and for `git blame` when a chunk_id changes.

## Recommended rectification order

1. **F1** (CRITICAL) — fix 2307.00010 fixture content first; this re-bootstraps that paper's expected.json. Highest reputational risk because it's the marquee math-fidelity fixture.
2. **F4** (HIGH) — expand `kind_counts` schema to include all emitted kinds; this requires re-bootstrapping all 10 expected.json files, so do it AFTER F1 to avoid two re-bootstraps. Coordinate with eval-harness owner per the doc's lockstep note.
3. **F3** (HIGH) — convert `test_expected_chunk_ids_present` from subset check to ordered-list-equality check. Single-line fix; closes the document-order gap for 2307.00009 and globally hardens the suite.
4. **F2** (HIGH) — add direct section_path assertion for 2307.00006. ~10 LOC; closes the nested-section gap that chunk_ids cannot detect (chunk_id hash does not include section_path).
5. **F8** (MEDIUM) — refactor `test_chunker_version_matches_constant` out of parametrize. Single test, single failure, no parametrization overhead.
6. **F6, F7** (MEDIUM) — doc-only fixes; batch into one commit.
7. **F5** (MEDIUM) — append to docs/chunker-fixtures.md; same commit as F6/F7.
8. **F9** (MEDIUM) — document the preamble coverage gap; optionally land a preamble-aware fixture in a follow-up if scope permits.
9. **F10** (LOW) — table-text update; piggyback on the F4 commit since F4 changes the table anyway.

## Rectification status (filled by Phase 4)

Re-verify gate: 0 of 4 CRITICAL+HIGH findings invalidated (0% — well below 40% threshold).

- F1 (CRITICAL) — fixed: `tests/fixtures/chunker/2307.00010/index.html` rewritten to use single-backslash LaTeX in every `<math alttext>` attribute (real LaTeXML output form); fixture re-bootstrapped. Regression guard: `TestFixtureSuite::test_2307_00010_alttext_uses_real_latex` asserts `r"$\langle\cdot,\cdot\rangle$"` is present in body_text and that no double-backslash literal survives.
- F2 (HIGH) — fixed: `TestFixtureSuite::test_2307_00006_section_path_three_levels_deep` directly asserts the buried theorem's `section_path == ['1. Deep section nesting', '1.1 Outer subsection', '1.1.1 Inner subsubsection']` byte-exactly. Closes the gap that chunk_id hashing cannot catch (section_path is not in the hash input).
- F3 (HIGH) — fixed: `test_expected_chunk_ids_present` renamed to `test_expected_chunk_ids_in_document_order` and converted from subset (`for id in expected: assert id in emitted`) to list-equality (`emitted == expected["expected_chunk_ids"]`). Document-order regressions now fail with a precise diff.
- F4 (HIGH) — fixed: all 10 `expected.json` files re-bootstrapped with full `kind_counts` Counter (every emitted kind is now pinned, not just the four canonical ones). The `TestFixtureSuite::test_kind_counts_match` now compares full dicts via `Counter`; drift in lemma/corollary/remark/example/proposition/conjecture counts is visible in the test failure message.
- F5 (MEDIUM) — fixed: new "Cold-start CI note (BGE-M3 tokenizer download)" section in `docs/chunker-fixtures.md` documenting the one-time ~5 MB cache population, with offline-CI bootstrap recipe.
- F6 (MEDIUM) — fixed: new step 0 in the "Regenerating after a chunker change" section explicitly forbids re-authoring committed `index.html` files during a chunker_version bump.
- F7 (MEDIUM) — fixed: bootstrap snippet wrapped in `with tempfile.TemporaryDirectory() as tmp_str` so the staging area is cleaned up automatically.
- F8 (MEDIUM) — fixed: `test_chunker_version_matches_constant` removed from `parametrize`; replaced with a single `test_chunker_version_matches_constant_globally` that loops `_FIXTURE_SUITE_IDS` and reports all mismatches in one assertion.
- F9 (MEDIUM) — DOCUMENTED: new "Coverage gaps (deliberate, deferred)" section in `docs/chunker-fixtures.md` calls out the `_resolve_preamble_doc=None` lock and points at the follow-up path for adding preamble-aware fixtures.
- F10 (LOW) — fixed: scenario-table row for 2307.00005 updated from "proposition, conjecture" to "proposition × 2, conjecture × 1".

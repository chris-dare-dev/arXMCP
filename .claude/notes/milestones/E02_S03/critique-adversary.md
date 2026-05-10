# E02_S03 Adversary Critique — `body_tokens` regex pre-tokenizer

**Critic:** adversary
**Generated:** 2026-05-07
**Commit range:** `27206d4..0f465e0`
**Verdict:** REQUEST CHANGES

## Executive summary

- Verdict: REQUEST CHANGES.
- Findings: 0 CRITICAL, 3 HIGH, 7 MEDIUM, 3 LOW.
- Highest-risk file: `ingest/tokenizer.py` (docstring/spec drift on subscript handling, Unicode word-loss, empty-string-vs-None semantics for downstream BM25).
- Spec drift: docstring lines 24–25 and implementation summary's "Drop complex sub/superscripts. H^{n+1} produces only H" are FALSE. Actual: `H^{n+1}` → `H_n`, `H_{i,j}` → `H_i j`. Spec and observable behavior diverge.
- Unicode word-loss: `étale` (NFC, single char é) tokenizes to `tale` — the leading `é` and any subsequent letters before the next ASCII run are silently dropped. Affects étale, fibré, Poincaré, Hörmander, Möbius, Schrödinger — common math vocabulary. Acceptance criterion would treat this as "non-null body_tokens" and pass, but the term recall is broken.
- Acceptance test for the 50-paper criterion is deferred and the substitute test only covers a 4-chunk fixture (2 stmt + 2 proof). No `body_tokens` assertion runs against `kind="section"`, `definition`, `lemma`, `remark`, `example`, `corollary`, or `proof`-window-split chunks (none of these are even covered by the chunker test in `TestMultiKindEnvironments`).
- The `H_{i,j}` case emits `H_i j` — the regex `id_base+id_sep+\{?id_script\}?` matches the OPENING brace as optional and then `[A-Za-z0-9]+` greedily consumes `i`, but `\}?` is optional → match ends before the closing brace. Then `,j}` is left for re-scan and `j` matches the word branch. The closing `}` is silently dropped. That's brittle behavior, not "drops to base identifier."
- Compiled regex `_TOKENIZER_RE` is a private symbol; tests import it directly. Module-level state on the byte-stability hot path with no version pinning — a future regex tweak silently invalidates the BM25 cache key contract (BP1) without bumping `chunker_version`.

## Severity calibration

| Severity | Definition |
|---|---|
| CRITICAL | Data loss, security boundary breach, broken cache-byte invariant, broken project mission invariant. |
| HIGH | Wrong behavior on the common path; ships visible bugs to users; spec/docs diverge from observable behavior. |
| MEDIUM | Subtle correctness, missing test coverage on a contract surface, future-cache-invalidating choices not yet realized. |
| LOW | Style, doc tightening, naming. |

## Findings

### F1 — Docstring and design-summary claim about subscript/superscript fallback is FALSE [HIGH]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:24-25`
**Also:** `.claude/notes/milestones/E02_S03/implementation-summary.md:45` ("Drop complex sub/superscripts. H^{n+1} produces only H.")

The module docstring says: "For non-alphanumeric script content (`H^{n+1}`, `H_{i,j}`) emit only the base identifier." Confirmed by direct execution:

- `tokenize_body("H^{n+1}")` returns `"H_n"`, NOT `"H"`. The id branch matches `H^{n` (script=`n`), then `+1` is dropped (no token), then later `H` does not appear again.
- `tokenize_body("H_{i,j}")` returns `"H_i j"`, NOT `"H"`. The id branch matches `H_{i` (script=`i`, closing brace not required because `\}?` is optional), then `,j}` re-scans → `j` matches as a word.

The acceptance test `test_complex_subscript_drops_to_base` only asserts "no `+` in any token" — that passes for `H_n`, so the test doesn't catch the spec violation. The implementation summary's design-choice bullet is wrong, the docstring is wrong, and the spec contract for "exotic LaTeX recall loss" is undefined. Either the docstring or the regex must change. Recommend: update docstring to match actual behavior (partial-prefix match on alphanumeric content) since the actual behavior is more recall-friendly than what the docstring claims.

### F2 — Unicode-bearing words silently truncated at the first non-ASCII letter [HIGH]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:74` (word branch char class)

The word-branch regex is `[A-Za-z][A-Za-z\-]*`. After NFC normalization, `étale` is a single precomposed character `é` (U+00E9) followed by `tale`. `é` is not in `[A-Za-z]`, so the word match starts at `t`:

- `tokenize_body("étale cohomology")` returns `"tale cohomology"`.
- `tokenize_body("Poincaré conjecture")` returns `"Poincar conjecture"` (the `é` terminates the word at `Poincar`, then `é` is dropped, then ` conjecture` matches normally).
- Same affects `fibré`, `Möbius`, `Hörmander`, `Schrödinger`, `Hölder`, every common math name.

This breaks BM25 recall for a very common vocabulary in algebraic geometry, number theory, and analysis. The determinism test `test_nfc_and_nfd_yield_identical_tokens` asserts `tokenize_body(nfc) == tokenize_body(nfd)` — but only because BOTH yield the broken `"tale cohomology"`. The test passes for the wrong reason.

Fix: use `\w` (Python's default Unicode-aware word class) or `[^\W\d_]` for the letter class, OR explicitly allow Latin-1 and Latin-Extended-A blocks. Confirm that whichever fix lands does not regress on math identifiers (LaTeX command names remain ASCII — the cmd_arg/cmd_bare branches don't need to change).

### F3 — Acceptance criterion "non-null body_tokens on every chunk" not exercised on most chunk kinds [HIGH]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/tests/test_chunker.py:162`
**Also:** `tests/test_chunker.py:224` (TestMultiKindEnvironments has no body_tokens assertion)

The 50-paper acceptance test is deferred. The substitute is `test_body_tokens_populated`, which runs ONLY against `TestTwoTheoremGolden` — a fixture with 4 chunks, all `kind in {stmt, proof}`. The corpus has chunks of kind `definition`, `lemma`, `proposition`, `corollary`, `remark`, `example`, `claim`, `fact`, `conjecture`, `hypothesis`, `observation`, `problem`, `question`, `exercise`, `assumption`, `convention`, `notation`, and `section` — NONE of these are body_tokens-asserted in the test suite.

`TestMultiKindEnvironments` exists and exercises definition/remark/lemma/corollary/example kinds against fixture `2307.00002`, but the class adds zero body_tokens assertions. `TestProofWindowSplitting` similarly does not check body_tokens on the multi-window proof chunks.

A `kind="section"` chunk is the highest-risk because section prose is generally NFC-clean Latin-1 and includes étale/Poincaré-style words (see F2) — a section chunk that body-tokenizes to a 2-word output from a 200-word paragraph is a real and silent failure mode. Add body_tokens-non-empty assertions to TestMultiKindEnvironments and TestProofWindowSplitting.

### F4 — Empty-string `body_tokens` for math-only chunks satisfies "non-null" but is semantically wrong [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:114`
**Also:** `tests/test_chunker.py:174` (the assertion)

`tokenize_body("$$$$")` returns `""`. After dollar-strip the buffer is empty, the regex emits nothing, the join produces an empty string. The test guards against this by skipping the assertion when `body_text.strip()` is empty, but a real chunk with `body_text="$\\,$"` or `body_text="$$"` (whitespace-stripped non-empty, but tokenizer-empty) would set `body_tokens=""` — passes the "non-null" assertion since `"" is not None`, but fails the actual contract (BM25 needs at least one term). 

The contract is currently undefined: should `body_tokens=""` be `None` instead? The schema says `str | None`. E04_S04's `rank_bm25.BM25Okapi.__init__(corpus)` will crash or return garbage on a document with zero tokens. Define the contract explicitly: either (a) emit `None` when empty, (b) emit a sentinel placeholder, or (c) document that downstream must filter empty strings. The current behavior leaks the choice onto E04_S04.

### F5 — `H_{i,j}` brace-mismatch behavior leaks unbalanced tokens and a stray `j` [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:72`

The id branch regex is `[A-Za-z][_^]\{?[A-Za-z0-9]+\}?`. The `\{?` and `\}?` are independently optional. For input `H_{i,j}`:
- Match consumes `H_{i` (open brace matched, script=`i`, close brace optional but absent at this position because next char is `,`).
- Remaining: `,j}`. The `,` is dropped, `j` matches the word branch, `}` is dropped.
- Result: `H_i j`.

This is brittle: `H_{ij}` correctly emits `H_ij` (close brace consumed), but `H_{i,j}` emits a token `H_i` that the user never wrote and that semantically conflates `H_i` with `H_i,j`. In a paper that genuinely has both `H_i` and `H_{i,j}` indexed identifiers, BM25 cannot distinguish them. Recommend tightening the regex to require matching brace pairs: replace `\{?[A-Za-z0-9]+\}?` with two alternatives — `\{[A-Za-z0-9]+\}` OR `[A-Za-z0-9]` — so unbalanced braces fall to the bare-base + drop-script path.

### F6 — `_TOKENIZER_RE` is on the cache-byte-stability path with no version pinning [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:64`
**Cite:** `.claude/notes/07-multi-agent-caching.md` § BP1 ("Tool result payloads are canonicalized") and the chunker's BP1 contract.

The chunker's docstring (`ingest/chunker.py:36-41`) and `ChunkRecord.to_dict` (`chunker_types.py:81`) document that chunk JSON output is byte-stable — that is the BP1 contract. `body_tokens` is now part of every chunk's serialized output. A future `re.compile` change to `_TOKENIZER_RE` (e.g. changing the word-branch char class to fix F2) silently produces different `body_tokens` strings for the same `body_text` — which means a different chunk JSON, a different chunk_id under E02_S04's content-addressable hashing, and a cold BM25 index after rebuild.

There is no `tokenizer_version` constant, no test that pins `sha256(tokenize_body("…known input…"))`, and no test of the kind `assert sha256(serialize_tools()) == EXPECTED_HASH` that 07-multi-agent-caching.md prescribes. The `chunker_version="v1.0"` constant (`chunker_types.py:74`) does NOT capture tokenizer changes since the tokenizer lives in a different module. Bump policy is undocumented.

Recommend: (a) add a `TOKENIZER_VERSION = "v1.0"` constant to `ingest/tokenizer.py`; (b) include it in `ChunkRecord.to_dict()` or fold it into `chunker_version`; (c) add a regression test that asserts `tokenize_body(GOLDEN_INPUT) == GOLDEN_OUTPUT` so any regex tweak forces a deliberate version bump.

### F7 — Performance test loose-bound (5ms) is 5× the brief's 1ms target — undefeats the purpose [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/tests/test_tokenizer.py:228`
**Cite:** milestone brief: "Tokenizer performance: ≤ 1ms per 512-token chunk."

The test asserts `elapsed < 5e-3`. The brief's acceptance criterion is `≤ 1ms`. The test's loose bound means the criterion would technically pass at 4× the brief target before failing — and on a slow CI runner could pass at 4.99ms while shipping a 5× regression to production. The implementation summary acknowledges typical run is ~0.1ms, so a tight bound (e.g. 1.5ms or 2ms) would still absorb CI jitter while catching real regressions.

Even if the bound stays at 5ms for CI safety, an additional warning-tier assertion that prints (without failing) when elapsed > 1ms would surface the brief's contract.

### F8 — `_extract_section_chunks` calls `tokenize_body` on a docstring-claimed pure body but the section "body" is a `_element_text` join with `$…$` math wrappers [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/chunker.py:820-821`

`tokenize_body` is called on every chunk's `body_text`. For section chunks, `body_text` is the join of paragraph `_element_text` outputs, each of which wraps `<math alttext="…">` payloads as `$alttext$` (chunker.py:269). The tokenizer strips `$` and runs the regex. But the tokenizer only matches `\command{arg}` and `\command` patterns — it does NOT understand that mathematical Unicode in alttext (e.g. `\geq`, `\to`, `\in`, fractions) might be relevant. For a section paragraph that is mostly prose with one `<math alttext="\\mathbb{R}^n">`, the tokenizer correctly emits prose tokens + `mathbb_R` + `n`. For a paragraph that is `_element_text`-joined with multiple math fragments, no test verifies the joined-text tokenization yields the expected combined token stream.

Risk is moderate (section prose is mostly safe), but no test exists. Add an integration test: a section fixture with mixed prose + alttext math, assert specific tokens appear in `body_tokens`.

### F9 — `\@addtoreset{eq}{section}` emits `@addtoreset_eq` and a free-floating `section` token [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:67,69`

The cmd_arg branch matches `\@addtoreset{eq}` and emits `@addtoreset_eq`. Then `{section}` is left over — `{` is dropped, `section` matches the word branch. So `section` becomes a BM25 token. In a paper that uses many `\@addtoreset{eq}{...}` or similar two-arg internals, free-floating arg-2 tokens leak into the prose token bucket where they don't belong (a user searching for the section keyword finds matches in irrelevant `\@addtoreset` arguments).

Lower-priority because `\@`-internal commands are rare in arXiv source and most are stripped by LaTeXML. But the failure mode is: arg-2 of any two-arg command becomes a phantom prose token. Document or suppress.

### F10 — `1H` in prose drops the `1` and emits `H` only — number+letter prose tokens partially lost [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:74`

The word branch requires `[A-Za-z]` start. `tokenize_body("Section 1 Introduction")` returns `"Section Introduction"` — `1` is dropped (non-issue, BM25 doesn't index plain integers). But `tokenize_body("1H NMR")` returns `"H NMR"` — the chemistry/physics-style alphanumeric `1H` (proton NMR) becomes `H`, a different identifier. Same applies to `2D`, `3D`, `4-vector`. For a math-AG / math.AT paper with "12-Sphere" or "K3 surface", the `K` is correctly emitted but `3` is dropped — `K3` is no longer searchable as one token; only `K` remains. This is a recall hit in algebraic topology specifically.

Acceptable trade if documented; the docstring at lines 23–26 doesn't mention this case. Add a docstring sentence about leading-digit identifiers, or change the word branch to allow leading digits when followed by a letter.

### F11 — Trailing-hyphen tokens emitted: `well-` is a token [MEDIUM]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:74`

`tokenize_body("well- known")` emits `well-` as one token and `known` as another. The regex `[A-Za-z][A-Za-z\-]*` allows trailing hyphens. Tokens like `well-`, `strange--`, `--strange` (with leading double-dash, the second branch starts on the next letter and consumes `strange--`) end up in the index. BM25 will not match `well-` against a query `well-known` or `well`. This is a clean bug: change the regex to `[A-Za-z]([A-Za-z\-]*[A-Za-z])?` so terminal hyphens are excluded.

Verified: `tokenize_body("well- and --strange-- end")` returns `"well- and strange-- end"`.

### F12 — `import` of `tokenize_body` inside `_chunk_paper_impl` [LOW]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/chunker.py:819`

The implementation summary lists "Top-level import of tokenize_body in chunker.py (no circular-import risk)" as a design choice, but the actual code imports inside `_chunk_paper_impl`. The implementation summary disagrees with the implementation. Move the import to module top to match the documented choice (and avoid per-paper import-machinery cost — minor, but a free win).

### F13 — Test `test_alphanumeric_arg` accepts `label_thm1` as a useful BM25 token without justification [LOW]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/tests/test_tokenizer.py:62-63`

`\label{thm1}` emits `label_thm1` — confirmed. But `\label{...}` is metadata, not body content. LaTeXML usually elides `\label` from rendered HTML output anyway, so this branch may never fire in practice. Either remove the test (false signal of coverage) or add a comment explaining why `label_*` tokens are useful for BM25 retrieval. Lower-severity because the path is rarely exercised on real LaTeXML output.

### F14 — `re` module (no `regex`) — POSIX char class semantics on Python <3.13 [LOW]

**File:** `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/worktrees/gallant-blackburn-b89422/ingest/tokenizer.py:56`

The module uses stdlib `re`. Behavior is stable across Python 3.10–3.13 for this regex (no atomic groups, no possessive quantifiers, ASCII char classes only). However, the determinism docstring says "same input → same output on any Python version" — verify by adding a stdlib-version-pin test or a comment that `re`'s behavior is documented to be stable for the constructs used. This is a paper-trail issue, not a real risk.

## What was done well

- The core regex strategy is well-chosen: a single compiled alternation with explicit branch ordering avoids Tantivy-Rust complexity and ships immediately. The H4 closure rationale is correctly captured.
- NFC normalization is at the function entry — exactly the right layer (matches F6 from E02_S02).
- `re.finditer` is the right primitive for left-to-right document order; no list materialization beyond the token list itself.
- Module-level compilation is correct and tested.
- The `cmd_arg` branch precedes the bare-cmd branch in the alternation — a subtle correctness point that ensures `\mathbb{Z}` is not stripped to `mathbb` then `Z`.
- Determinism documentation is comprehensive (no randomness, no set iteration order, no locale dependency).
- Test surface is well-organized into named classes with one concern each.
- The schema fix from `list[str] | None` to `str | None` is correct and aligns with LanceDB's column type expected by E04_S04.
- Performance is genuinely sub-millisecond on real input — the regex avoids catastrophic backtracking despite the 4-branch alternation.
- `tokenize_body` is pure (no I/O, no logging, no global mutable state outside the compiled pattern).

## Recommended rectification order

1. **F1** — fix the docstring/spec to match actual `H^{n+1}` and `H_{i,j}` behavior (or change the regex to actually drop to base). 30-minute fix.
2. **F2** — fix the word-branch char class to admit Unicode letters; add étale/Poincaré tests. Highest user-visible impact.
3. **F3** — extend `TestMultiKindEnvironments` and `TestProofWindowSplitting` with body_tokens assertions; add a section-kind body_tokens assertion. Cheap and closes acceptance-criterion coverage gap.
4. **F4** — define empty-string contract: `None` vs `""` vs sentinel. Document or change.
5. **F5** — tighten brace-pair handling in id branch; add `H_{i,j}` test that asserts the actual emitted tokens.
6. **F6** — add `TOKENIZER_VERSION` constant and a golden-output regression test.
7. **F7** — tighten the perf bound to 1.5ms or 2ms.
8. **F11** — fix trailing-hyphen tokens.
9. **F8** — add a section+math integration tokenization test.
10. **F10**, **F9** — document or suppress; lower priority.
11. **F12**, **F13**, **F14** — style/cleanup.

## Rectification status

(empty — pending rectification phase)

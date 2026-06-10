# Critique — textbook-markdown-chunker-m1

**Critic:** adversary
**Generated:** 2026-06-10T22:59:59Z
**Commit range:** 0932065f89e888391d6080b15e83f2f54763cc10..bb29b868c8dfe69f3ff1eeaf04c47ff7b108a219
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the chunker is sound on the math-fidelity HOT path (verbatim LaTeX preserved, oversized `$$` blocks emitted whole, never truncated), but the chunker-selection WIRING is entirely untested and the two chunkers behind the one flag have divergent error envelopes.
- Findings: 0 CRITICAL, 0 HIGH, 5 MEDIUM, 2 LOW.
- Highest-risk path: `tools/notebook_textbook_ingest.py:189` — `chunker="markdown"` raises an uncaught `FileNotFoundError` (HTML path returns `[]`), so a missing-markdown paper aborts the whole batch with a raw traceback.
- Math-fidelity verdict per probed case: (a) escaped `\$` mis-parity, (b) `$`/`$$` in code fence/inline-code mis-parity, (c) unbalanced-`$` runaway → all MIS-GROUP chunk boundaries but do NOT corrupt or drop math/content bytes. (d) oversized `$$` block → emitted WHOLE, math intact (parity-merge verified). (e) identical short bodies → second silently dropped (content loss, mirrors existing HTML-path contract).
- Cross-axis pattern: `_inline_math_open` is a naive `$`-count parity that is correct for clean MinerU math but wrong for any literal/escaped/code-fenced `$` — one root cause behind findings F1, contributing to coarsened retrieval granularity, not data corruption.
- Cache/MCP/no-fork/local-first axes are clean; `EXPECTED_TOOL_SCHEMA_SHA256` and the server tool surface are untouched (ingest-only change).
- Tier-sequencing clean: depends on m7 chunk_id/source_kind/store contract (shipped) and mirrors `_compute_textbook_chunk_id` + dedup exactly, so the m9 `textbook:` prefix invariant holds.
- Test sweep: all observed `test_store` / `test_notebook_textbook_ingest` / `test_chunker_ids` failures are pre-existing Windows/missing-dep artifacts (`No module named 'lancedb'`/`'prometheus_client'`, cp1252 decode, `\U` path-escape). 16 new chunker tests pass. Zero NEW real failures.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Divergent error envelope: markdown chunker raises, HTML returns []

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_markdown_chunker.py:82
- **What:** `chunk_textbook_markdown` raises `FileNotFoundError` when no `**/auto/*.md` exists (`_markdown_path`, line 82), and never wraps per-paper failures. The HTML peer `chunk_textbook` (`ingest/textbook_chunker.py:302-313`) catches `PER_PAPER_FAILURE_EXCEPTIONS` (incl. `FileNotFoundError`) and returns `[]`. Both are selected by the same `--chunker` flag, but `tools/notebook_textbook_ingest.py:298-306` `main()` only catches `NotebookError`.
- **Why it matters:** On a plausible operator path — a notebook where some papers are parsed and some are not — `--chunker markdown` produces a raw traceback through `run` → `main` and ABORTS the whole multi-paper batch at the first missing markdown, instead of the HTML path's graceful per-paper `WARNING` + `{"chunks": 0}` + continue. Same flag, two contracts; the milestone's own ingest tool regresses batch resilience for the markdown branch.
- **Proposed fix:** Wrap the `chunk_fn(slug, paper_id)` call at `tools/notebook_textbook_ingest.py:193` (or inside `chunk_textbook_markdown`) in the same `PER_PAPER_FAILURE_EXCEPTIONS` envelope used by `chunk_textbook`, logging a per-paper failure and returning `[]` so the existing `if not chunks:` warn-branch (line 195) handles it uniformly.
- **Regression guard:** Add `test_markdown_chunker_missing_markdown_returns_empty_not_raises` (or `run()` with one missing-markdown paper_id returns exit-1-but-no-traceback and still processes the remaining paper_ids). No lancedb needed if the chunker returns `[]` and `dry_run=True`.

### F2 — --chunker selection wiring is completely untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/notebook_textbook_ingest.py:194
- **What:** The one-line router `chunk_fn = chunk_textbook_markdown if chunker == "markdown" else chunk_textbook` (line 194), the `chunker=` kwarg threading through `ingest_textbook_paper`/`run` (lines 177, 227, 255), and the `--chunker` argparse choice (line 282) have ZERO test coverage. `grep "chunker=" tests/test_notebook_textbook_ingest.py` returns nothing; the 16 new tests only drive `_chunk_markdown_impl` directly.
- **Why it matters:** Routing to the new chunker is the literal user-facing point of the milestone. A future refactor could flip the ternary, drop the kwarg, or change the default, and every test still passes. The existing `TestIngestTextbookPaper`/`TestRunExitCodes` tests that DO touch `run()` all require lancedb (skipped/erroring on this workstation), so the wiring is unverified on the green path too.
- **Proposed fix:** Add a test that monkeypatches `chunk_textbook` and `chunk_textbook_markdown` to record which was called, then asserts `ingest_textbook_paper(slug, pid, chunker="markdown", dry_run=True)` invoked the markdown one (and `chunker="html"` / default invoked HTML). `dry_run=True` keeps it lancedb-free.
- **Regression guard:** The monkeypatch-and-assert-callee test above; also assert `main(["--chunker", "markdown", slug, pid])` parses and forwards `chunker="markdown"` into `run`.

### F3 — Naive $-parity miscounts escaped \$, code fences, inline-code spans

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_markdown_chunker.py:94
- **What:** `_inline_math_open` (line 94) counts every literal `$`/`$$` with no awareness of LaTeX-escaped `\$`, fenced code blocks, or inline-code spans. Verified live: `$x = \$5$` (a literal dollar inside math) → 3 `$` → reported "open" (wrong); a code fence containing `x = $PATH` merges with the following paragraph; a single stray `$` in prose swallows all following blocks until balanced or EOF (`_paragraph_blocks` merge loop, lines 152-154).
- **Why it matters:** This MIS-GROUPS chunk boundaries — distinct paragraphs get merged into one chunk, and in the genuinely-unbalanced case the document tail collapses into a single oversized chunk (degraded retrieval granularity, the exact m12 defect this milestone exists to fix, reintroduced on a narrower trigger). Probed cases confirm content is PRESERVED verbatim in `body_text` (no math corruption, no dropped bytes), so this is a granularity-correctness foot-gun, not data loss. Common in CS/programming and applied textbooks (`$PATH`, `$5`), rarer in pure math.AG/NT.
- **Proposed fix:** Strip fenced code blocks (```` ```...``` ````) and inline-code spans (`` `...` ``) before the parity count, and ignore `\$` (preceded by an odd run of backslashes). A minimal mitigation: in `_paragraph_blocks`, cap the merge run length so an unbalanced `$` cannot swallow the entire remaining document.
- **Regression guard:** `test_lone_dollar_in_code_fence_does_not_swallow_doc` (assert a `$PATH`-in-fence + 3 following paragraphs produce > 1 block) and `test_escaped_dollar_in_math_not_treated_as_open` (assert `$x = \$5$ holds` is one balanced block).

### F4 — body-only dedup drops distinct chunks differing only by section context

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_markdown_chunker.py:245
- **What:** `_compute_textbook_chunk_id(slug, "", body)` (line 245) hashes only `body_text`; `section_path`/`chapter` are excluded. The dedup loop (lines 246-256) then drops the SECOND chunk with an identical body. Verified live: `# Theorem A\n\nProof. Omitted.` + `# Theorem B\n\nProof. Omitted.` yields ONE chunk, attributed to `["Theorem A"]` — Theorem B's proof is silently lost AND mis-attributed.
- **Why it matters:** The markdown chunker emits MANY fine-grained chunks (vs the HTML path's one-per-section-div), so short identical bodies ("Proof.", "Proof. Omitted.", "$\\square$", boilerplate definitions) collide far more often than on the HTML path. This is real content loss with wrong section attribution. NOTE: this exactly mirrors the EXISTING m7 FM-4 textbook-chunk-id contract (`ingest/textbook_chunker.py:399-412` dedupes on body identically), so it is a faithfully-inherited limitation, not a new divergence — which is why this is MEDIUM, not HIGH.
- **Proposed fix:** Fold a section discriminator into the hash input (e.g. `_compute_textbook_chunk_id(slug, "\x00".join(section_path), body)` reusing the `preamble_text` slot, or extend the helper). This must be a DELIBERATE contract decision since it changes textbook chunk_id derivation; if kept body-only for cross-section dedup-by-design, document the trade-off and add an explicit test asserting the drop is intended.
- **Regression guard:** `test_identical_body_distinct_sections_both_kept` (or, if the body-only contract is intentional, an explicit `test_identical_body_distinct_sections_deduped_by_design` documenting the accepted loss).

### F5 — read_text(errors="replace") silently masks markdown encoding corruption

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_markdown_chunker.py:293
- **What:** `_markdown_path(...).read_text(encoding="utf-8", errors="replace")` (lines 293-295) silently substitutes U+FFFD for any non-UTF-8 bytes in the MinerU markdown, with no log or counter.
- **Why it matters:** MinerU output is normally clean UTF-8, but a corrupted/mis-encoded parse would have math symbols silently replaced by `�` and embedded verbatim into `body_text` — a math-fidelity degradation (note 04 / note 01) that ships into LanceDB invisibly. `errors="replace"` converts a loud failure into silent corruption on the math hot path.
- **Proposed fix:** Either read with `errors="strict"` and let the per-paper failure envelope (see F1) catch `UnicodeDecodeError` as a logged parse failure, or keep `replace` but count/log replacement chars and surface a WARNING when any are present.
- **Regression guard:** `test_non_utf8_markdown_is_logged_not_silently_replaced` (feed bytes with an invalid sequence; assert a warning/raise rather than silent `�` in `body_text`).

### F6 — glob "**/auto/*.md" follows directory symlinks under parsed/<flat>/

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/textbook_markdown_chunker.py:80
- **What:** `base.glob("**/auto/*.md")` (line 80) where `base = nb_dir/"parsed"/flat`. `pathlib.glob` follows directory symlinks during recursive `**` traversal. `_resolve_notebook_dir` validates the slug + refuses symlinks at the notebook-dir level and `_validate_paper_id` blocks traversal in `paper_id`, but a symlinked subdir UNDER `parsed/<flat>/` is not re-checked.
- **Why it matters:** Threat is bounded to a local operator who already has write access to their own gitignored `var/arxmcp/notebooks/<slug>/parsed/` tree on a loopback-only server (note 08 threat model). An attacker who can plant a symlink there can already write the markdown directly. This matches the existing HTML-path posture (`_textbook_html_path` builds `parsed/<flat>/index.html` with no symlink recheck under `parsed/`). Essentially clean; recorded as residual.
- **Proposed fix:** Optional hardening — after picking `mds[0]`, assert `mds[0].resolve()` is within `nb_dir.resolve()` (containment recheck) before reading. Low priority.
- **Regression guard:** `test_markdown_symlink_escaping_notebook_dir_rejected` (only if F6 is actioned).

### F7 — "missing parsed HTML?" warning is wrong for the markdown branch

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/notebook_textbook_ingest.py:197
- **What:** The empty-result warning hardcodes "missing parsed HTML? run the PDF upload + parse first" (lines 197-198). When `chunker="markdown"` produces `[]` (or, post-F1-fix, when the markdown is missing), the remediation text points the operator at the wrong artifact (HTML, not MinerU markdown).
- **Why it matters:** Operator confusion only — points at LaTeXML HTML when the markdown path needs the MinerU `**/auto/*.md`. No correctness impact.
- **Proposed fix:** Branch the message on `chunker`, or make it generic ("no chunks produced — confirm the PDF was parsed (MinerU markdown / LaTeXML HTML present) for this paper").
- **Regression guard:** None required (LOW, message-only).

## What was done well

- Math hot path is genuinely safe: an oversized `$$...$$` display block with no internal sentence boundary is emitted WHOLE (verified `_split_oversized` returns 1 piece, both `$$` intact), and the parity-merge in `_split_oversized` keeps a `$$` block whole even when it contains internal `. ` punctuation — math is never cut mid-equation.
- The `body_tokens` field is correctly a STRING (`tokenize_body(body)` output), matching `ChunkRecord.body_tokens: str | None` and the downstream `body_tokens.split()` contract — no int/str mismatch.
- Chunk-identity contract is faithfully mirrored from the HTML path: `_compute_textbook_chunk_id` + `source_kind="textbook"` + `preamble_text=""` + the SHA-prefix-collision raise, so the m9 `textbook:` prefix ↔ source_kind invariant and the store write contract hold.
- Version/parser lineage is correctly isolated (`tmd0.1` / `mineru+markdown`, distinct from `tv0.1` / `mineru+latexml`), so a markdown-chunker change never forces arXiv or HTML-textbook re-embedding; no `v1.1`/tokenizer-version literal leaked into the new module (passes the `test_chunker_ids` single-source guard where readable).
- `_ALLOWED_PARSER_USED` was updated in lockstep with the new `parser_used` value, and a test (`test_store_allows_mineru_markdown_parser`) pins the requirement so a future store write cannot silently reject the new chunks.
- `section_path` is rebuilt per flush (`[t for (_,t) in stack]` inside `flush()`), producing a fresh list per chunk — no aliasing of one mutable list across multiple chunks of the same section.
- Empty/whitespace-only input is handled cleanly (`_group_blocks([]) == []`, whitespace doc → `[]`, heading-only doc → `[]`); no empty-string chunk is producible.
- Heading-less giant `$$`-only documents are handled (one whole chunk, `kind="section"`, `section_path=[]`, `chapter=None`) — the mid-chapter page-segment case the module docstring calls out.
- No new runtime dependency (stdlib `re`/`pathlib` + existing ingest imports only), no forked markdown-parser code (hand-rolled regex), MCP/tool-schema surface untouched — cache, MCP-spec, local-first, and no-fork axes all clean.
- Paper_id traversal is rejected before path use (`_validate_paper_id` runs before `_markdown_path` in `chunk_textbook_markdown`; `textbook:../../etc` and `a/../../b` rejected by the regex).

## Recommended rectification order

1. F1 (error-envelope divergence) — highest blast radius: a batch-aborting traceback on a common partially-parsed-notebook path. Fix the chunker selection call site once; it also subsumes the F7 message branch and pairs naturally with the F5 strict-decode option.
2. F2 (wiring test) — cheap, lancedb-free, locks the milestone's core deliverable (chunker routing) against silent regression.
3. F3 (parity hardening) — bound the merge run to stop document-tail swallowing; the full code-fence/escaped-`\$` strip is a larger change and may be partially deferred.
4. F4 (dedup section context) — requires a deliberate chunk-id contract decision; if kept body-only, replace with an explicit "loss is intended" test rather than a code change.
5. F5 (encoding masking) — fold into the F1 envelope (strict decode → caught as a per-paper failure).
6. F7 (warning text) — trivial; bundle with F1.
7. F6 (symlink containment recheck) — defer; matches existing posture, loopback-only local-operator threat.

## Rectification status

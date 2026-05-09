# Critique — E05_S03

**Critic:** adversary
**Generated:** 2026-05-09T01:36:49Z
**Commit range:** b2c3b6a..4449a1d
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The 5 ACs are nominally met, but the AC sentence
  "Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80 after
  BM25 hybrid is active." is wrapped across a markdown line break in
  TIER-GATES.md (`TIER-GATES.md:31-32`). A literal `grep -F` on disk
  fails — this would be a false-green for any future regression test
  modeled on `tests/test_bm25.py::test_docstring_h4_remediation_sentence`.
- 0 CRITICAL, 0 HIGH, 6 MEDIUM, 4 LOW. No security, data-loss, or
  cache-stability issues; this is a docs milestone and the adversary
  surface is content fidelity and source attribution drift.
- Highest-risk file: `TIER-GATES.md:31` (the wrapped AC sentence) and
  `TIER-GATES.md:181-183` (mis-attributed 30 % source).
- Cross-axis pattern: source-attribution drift. TIER-GATES.md
  attributes both the 0.70 / 0.80 thresholds and the 30 % cache
  bound to design notes that do not actually contain those numbers
  (`09-feature-priorities.md` is qualitative-only;
  `07-multi-agent-caching.md` has no 30 % anywhere). The numbers come
  from the brief itself / the new roadmap, not from the constitution.
- Missing regression guard: no test asserts the verbatim AC sentence
  is present in TIER-GATES.md (E04_S04 set the precedent in
  `tests/test_bm25.py:149`; E05_S03 did not follow it). Combined
  with the line-wrap above, the AC "lives" only in the brief.
- README.md still links to root `ROADMAP.md` (line 18) which is the
  OLD numbering (E05 = "Storage & Indexing", E07 = "MCP Server
  Surface", E08 = "Multi-Agent Caching"). TIER-GATES.md cites the
  NEW numbering (E05 = Eval, E07 = Hybrid, E08 = Caching). Reader
  who follows README → ROADMAP.md gets stale info; reader who follows
  README → TIER-GATES.md gets the correct gates with mismatched
  epic labels. Pre-existing drift, but E05_S03 is the first
  milestone whose docs explicitly assume the new numbering at the
  root level.
- Owner approval per the brief's risk note is unverified: the commit
  body has no `Approved-by:` trailer and TIER-GATES.md asserts
  sign-off "is recorded in the commit-trailer of the `feat(eval)`
  commit that lands this file" — circular. See F4.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — AC sentence wrapped across a line break; literal-grep fails

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** TIER-GATES.md:31-32
- **What:** The AC-mandated verbatim sentence — "Reranker activation
  in E07 is conditional on nDCG@5 ≥ 0.80 after BM25 hybrid is
  active." — is split across two lines in TIER-GATES.md (the word
  "after" ends line 31, and "BM25 hybrid is active." opens line 32,
  separated by a markdown soft-break / `\n`). A whitespace-collapsed
  match passes; a strict `grep -F "Reranker activation in E07 is
  conditional on nDCG@5 ≥ 0.80 after BM25 hybrid is active."` does
  NOT.
- **Why it matters:** The AC says the file *states* the sentence.
  The brief verbatim is a single-line sentence; the natural
  enforcement is a string-equality check. A future reviewer
  (human or automated) who greps the literal AC text will believe
  the AC is unmet, or — worse — the precedent set by
  `tests/test_bm25.py:149` (the H4 remediation sentence test) was
  to use `" ".join(doc.split())` for exactly this reason. Without
  that normalization, a regression test would false-fail; with it,
  the file format is silently fragile.
- **Proposed fix:** Reflow paragraph at TIER-GATES.md:31 so the
  full AC sentence sits on one source line, e.g.:
  ```
  **Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80 after BM25 hybrid is active.** If the hybrid pipeline alone reaches the 0.80 bar, ...
  ```
  (Markdown rendering is unaffected; the body text wraps at the
  reader's column width.)
- **Regression guard:** add `tests/test_tier_gates_doc.py::TestTierGatesDoc::test_reranker_sentence_verbatim`
  that does `assert REQUIRED in TIER_GATES_PATH.read_text()` (NOT
  whitespace-collapsed — the AC names a literal string). Mirror
  `tests/test_bm25.py:149`'s structure but tighten to bytewise
  equality. Without the test, F1 reappears the next time the
  paragraph is reflowed.

### F2 — TIER-GATES.md attributes 0.70 / 0.80 to wrong source

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** TIER-GATES.md:221-224
- **What:** The History section claims the 0.70 / 0.80 threshold
  values come from `.claude/notes/09-feature-priorities.md`
  § "Tier 0 exit criterion". That section (line 36) reads
  *"Exit criterion: a Claude agent in this repo can answer 'find
  the theorem about X in this corpus' with a non-trivial chunk_id
  and snippet."* — qualitative only, no numbers. `grep '0.70\|0.80'
  09-feature-priorities.md` returns no matches. The 0.70 / 0.80
  numbers are first introduced in `.claude/roadmap/E05-eval-harness.md`
  (epic header line 5 and AC tables).
- **Why it matters:** The history section is the audit trail for
  *why* the threshold is what it is. A misattributed source means
  a future reader chasing the "where did 0.70 come from" question
  follows the link, finds no answer, and has to re-derive the
  decision from scratch — exactly the kind of decision-archeology
  TIER-GATES.md is supposed to prevent.
- **Proposed fix:** Replace the citation in TIER-GATES.md:221-224
  with `.claude/roadmap/E05-eval-harness.md` (the actual source).
  Keep the `09-feature-priorities.md` reference only as the
  retired qualitative criterion (which it correctly cites earlier
  at TIER-GATES.md:9-13).
- **Regression guard:** include the threshold provenance in the
  same `test_tier_gates_doc.py` regression test — assert that
  TIER-GATES.md mentions `E05-eval-harness.md` at least once.

### F3 — TIER-GATES.md attributes the 30 % cache bound to wrong note

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** TIER-GATES.md:180-183
- **What:** The Tier-2 → Tier-3 section says *"Lower bound 30 %
  comes from the multi-agent caching design note
  (`07-multi-agent-caching.md`) — anything below that means the
  cache-key discipline (BP1 byte-stability) has drifted."*
  `grep '30%\|30 %' .claude/notes/07-multi-agent-caching.md` returns
  no matches. The 30 % number lives only in the E05_S03 brief and
  in `.claude/roadmap/E05-eval-harness.md:134` /
  `.claude/roadmap/README.md:38`.
- **Why it matters:** Same as F2 — a fabricated provenance
  citation in the doc that is *supposed to be* the audit trail.
  Worse than F2 because the 30 % bound has no upstream grounding
  yet (E08 hasn't shipped); a future operator pushing back on the
  threshold ("why 30 % and not 25 %?") would chase the citation,
  find nothing, and either drop the bound or invent justification.
- **Proposed fix:** Replace the cite at TIER-GATES.md:181-183 with
  one of: (a) honest "set in E05_S03 as a placeholder; E08 will
  re-derive against real telemetry"; (b) cite the actual roadmap
  source (`.claude/roadmap/E05-eval-harness.md:134`); or (c) defer
  the rationale until E08 lands.
- **Regression guard:** same regression test as F2; assert that
  any `7-multi-agent-caching.md` reference in TIER-GATES.md is
  paired with a real grep-able anchor sentence in that note. Or
  drop the cite entirely.

### F4 — Owner-approval mechanism is circular and unverified

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** TIER-GATES.md:228-233
- **What:** The "Owner approval" section says *"Owner sign-off is
  recorded in the commit-trailer of the `feat(eval)` commit that
  lands this file."* The commit that lands the file is `4449a1d`
  ("docs(eval): TIER-GATES.md + make eval + README link
  (E05_S03)") and its trailers are: `Co-Authored-By: Claude Opus
  4.7 (1M context) <noreply@anthropic.com>`. No `Approved-by:` or
  similar trailer. The brief's risk note explicitly requires
  owner review *before Tier-1 work begins* — TIER-GATES.md is
  asserting a sign-off mechanism that the very commit landing the
  file does not satisfy.
- **Why it matters:** The doc declares its own ratification
  mechanism, simultaneously fails it, and ships. A reader checking
  "is the gate approved?" greps the commit trailer, finds nothing,
  and either (a) believes the file is not yet authoritative, or
  (b) trusts the doc's existence as approval. Either way, the
  ratification mechanism documented in the file is dead-on-arrival.
- **Proposed fix:** Either (a) drop the Owner approval section
  entirely (the brief's risk note is a process directive, not an
  AC; the implementer cannot self-approve), OR (b) reword to
  *"Owner sign-off MUST be recorded as an `Approved-by:` trailer
  on a follow-up commit before any Tier-1 milestone (E06, E07)
  begins."* Option (b) is preferred — it preserves the brief's
  risk-note intent without making the landing commit retroactively
  the approval.
- **Regression guard:** N/A (process gate, not code). Optionally
  add a note in `.claude/roadmap/README.md` calling out that
  Tier-1 epics (E06 / E07) must not start before the trailer
  exists.

### F5 — No regression test locks any TIER-GATES.md AC

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/ (absence)
- **What:** E04_S04 set a project precedent for "lock the literal
  AC sentence in a test" via
  `tests/test_bm25.py:149::test_docstring_h4_remediation_sentence`.
  E05_S03 has 5 ACs (TIER-GATES.md exists, defines 4 transitions,
  contains the verbatim reranker sentence, README links to it,
  no subjective criteria) and zero tests. A reviewer editing
  TIER-GATES.md to fix a typo could accidentally drop the
  reranker sentence, the 4-row table, or the README link, and
  CI would not notice.
- **Why it matters:** The brief's risk note explicitly requires
  owner approval before Tier-1 begins. The tests are the only
  thing that survives a commit-message edit, a doc reflow, or
  a future "let me reorganize TIER-GATES.md" PR. Without tests,
  AC drift is silent.
- **Proposed fix:** Add `tests/test_tier_gates_doc.py` with
  five small tests, one per AC:
  1. `TIER-GATES.md` exists at repo root.
  2. Lists all four transitions (grep for "Tier-0 → Tier-1",
     "Tier-1 → Tier-2", "Tier-2 → Tier-3", "Tier-5 cutover").
  3. Contains the verbatim reranker sentence (exact bytewise
     match — see F1; whitespace-collapsed is the fallback).
  4. README.md contains a markdown link to TIER-GATES.md.
  5. (Reasonable proxy for "no subjective criteria") TIER-GATES.md
     does NOT contain "vibes-check", "looks coherent", "demo
     transcript", or similar subjective markers, EXCEPT inside
     the History / supersession discussion.
- **Regression guard:** the test file IS the regression guard;
  it converts the implementation summary's ad-hoc AC mapping into
  CI-enforced contract.

### F6 — README.md routes readers into a stale ROADMAP.md

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** README.md:18, ROADMAP.md (the file linked)
- **What:** README.md:18 says *"The roadmap is at
  [`ROADMAP.md`](ROADMAP.md) (15 epics, Tier 0 → Tier 7) with
  per-epic detail under [`.claude/roadmap/`](.claude/roadmap/)."*
  ROADMAP.md uses the OLD epic numbering (E05 = "Storage &
  Indexing", E07 = "MCP Server Surface", E08 = "Multi-Agent
  Caching") and has no SUPERSEDED banner. The new
  `.claude/roadmap/README.md` (line 1: *"This index supersedes
  ... and the old `epic-01-*.md` through `epic-15-*.md` files"*)
  uses the NEW numbering (E05 = Eval Harness, E07 = Hybrid
  Retrieval, E08 = Agent Runtime + Caching). TIER-GATES.md cites
  the NEW numbering. A reader landing on README.md → ROADMAP.md
  will see "E07 is MCP Server Surface" then read TIER-GATES.md
  saying "Tier-1 → Tier-2 ... in E07 (Hybrid Retrieval)" and have
  no way to reconcile.
- **Why it matters:** This is pre-existing drift that E05_S03
  did not create. But E05_S03 *is* the milestone that put NEW
  epic IDs in the README's prose ("Tier exit gates" section
  references TIER-GATES.md, which uses new IDs), making the
  inconsistency reachable from a single page. The new README
  section co-exists with a link to a stale file in the same
  README, creating internal contradiction.
- **Proposed fix:** Cheapest: add a one-line note at top of
  ROADMAP.md *"SUPERSEDED 2026-05; see `.claude/roadmap/README.md`
  for the authoritative epic table."* (mirrors the existing
  banner on `09-feature-priorities.md`). Even cheaper: change
  README.md:18 to point at `.claude/roadmap/README.md` instead
  of `ROADMAP.md`. The brief did not require this fix, but it
  is the kind of cheap MEDIUM that the rectification phase exists
  to clean up while the docs are open.
- **Regression guard:** none required for the SUPERSEDED banner
  approach; for the link-swap approach, add to
  `tests/test_tier_gates_doc.py` an assertion that README.md's
  roadmap link resolves to a file that does NOT carry "15 epics,
  Tier 0 → Tier 7" language (the OLD ROADMAP.md fingerprint).

### F7 — TIER-GATES.md FAIL-output block has wrong error class FQN

- **Severity:** LOW
- **Source:** adversary
- **File:** TIER-GATES.md:80
- **What:** The fail block shows `tests.eval.metrics.ThresholdNotMetError:`
  as the traceback header. Pytest's actual short-traceback render
  uses the class's `__module__` qualified by import path, which is
  `tests.eval.metrics.ThresholdNotMetError` only when pytest's
  rootdir + sys.path arrangement causes it. With the project's
  current layout (no `tests/__init__.py` boundary games — pytest
  collects via rootdir discovery), pytest typically shows the
  full traceback ending in `E   tests.eval.metrics.ThresholdNotMetError:
  nDCG@5 mean ...`. The `0.62NN` placeholder is documentation
  shorthand (acceptable). The `0.4f` formatter on the threshold
  side renders as `0.7000`, which matches the doc.
- **Why it matters:** Documentation drift more than correctness;
  but the expected-output blocks are presented as something an
  operator can pattern-match against. If the FAIL block doesn't
  match what pytest actually emits in the failure case, a tired
  on-call who sees a different traceback header thinks the test
  is malformed and starts debugging the wrong thing.
- **Proposed fix:** Either (a) verify against a real failure run
  (force `ndcg_min` to fail) and paste the actual traceback head;
  or (b) replace the precise rendering with a more abstract
  "the failure ends with a `ThresholdNotMetError` carrying the
  measured `nDCG@5 mean X.XXXX is below the threshold Y.YYYY`
  message" so the doc isn't promising bytewise format.
- **Regression guard:** N/A (LOW; ship-as-is acceptable).

### F8 — "make eval" shorthand-or-direct framing is contradicted by the brief

- **Severity:** LOW
- **Source:** adversary
- **File:** TIER-GATES.md:42-57, brief AC #2
- **What:** TIER-GATES.md:50-57 reads *"Or via Make: ```sh make
  eval ``` `make eval` is exactly the same invocation; it exists
  so contributors don't have to memorize the pytest path."* The
  brief AC #2 says simply *"`make eval` runs `pytest
  tests/eval/test_retrieval_quality.py --ndcg-min=0.70`."* —
  i.e., `make eval` is THE operator-facing command, not a
  shorthand. The framing slightly downplays it; in practice
  `make eval` also enforces the Python version guard (Makefile:54-56)
  which the bare pytest does not. So the two are NOT equivalent —
  `make eval` is strictly stricter.
- **Why it matters:** Cosmetic, but if a contributor on Python
  3.10 follows the doc's "exactly the same invocation" claim and
  runs the bare pytest, they get a confusing pytest stack trace
  instead of the version-guard message. The doc's claim is wrong.
- **Proposed fix:** Soften the language: *"`make eval` runs the
  same pytest invocation, plus the Python ≥ 3.11 guard from
  `make test`. Use `make eval` unless you need to pass extra
  pytest flags."*
- **Regression guard:** N/A (LOW).

### F9 — README "Tier exit gates" duplicates pytest-pass message inconsistently

- **Severity:** LOW
- **Source:** adversary
- **File:** README.md:42-44
- **What:** *"`make eval` must report `1 passed` (not `1 skipped`)
  for ANN-only retrieval at nDCG@5 ≥ 0.70."* TIER-GATES.md says
  the same with more nuance (the SKIP block is its own subsection).
  The README sentence is correct but conflates two checks: the
  pytest result AND the threshold. The threshold is checked by
  the test internally; if it passes, the test reports `1 passed`,
  yes. But the wording "for ANN-only retrieval at nDCG@5 ≥ 0.70"
  could be read as "the test must report nDCG@5 ≥ 0.70 in
  addition to passing", which it does not — it just reports
  pass/fail.
- **Why it matters:** README is the front door. Users will
  scan-read the sentence; ambiguity in the front-door doc that
  TIER-GATES.md exists to resolve is a small but real loss.
- **Proposed fix:** *"`make eval` must report `1 passed` (not
  `1 skipped`); failure means nDCG@5 fell below the 0.70 ANN-only
  threshold."*
- **Regression guard:** N/A (LOW).

### F10 — "Active gate" framing in TIER-GATES.md and README will rot

- **Severity:** LOW
- **Source:** adversary
- **File:** TIER-GATES.md:42, README.md:44
- **What:** TIER-GATES.md:42 says *"Tier-0 → Tier-1 gate (the
  active one)"* and README.md:44 says *"The active gate today
  is Tier-0 → Tier-1"*. There is no automated mechanism to
  promote the "active" label when Tier-0 is closed and Tier-1
  becomes active. Both phrases will need manual edits each
  promotion.
- **Why it matters:** Stale "active gate" claims in the front
  door will mislead future operators. Once Tier-0 → Tier-1 is
  closed, the next reader will see "the active one" pointing
  at a closed gate.
- **Proposed fix:** Either (a) remove the "active" framing
  (just call it "Tier-0 → Tier-1 gate"; the gates table is
  already the canonical view), OR (b) gate the labels behind
  a per-gate `Status:` line (NEW / ACTIVE / PASSED / SUPERSEDED)
  so the doc is auditable. (a) is cheaper.
- **Regression guard:** N/A (LOW; documentation hygiene).

## What was done well

- The AC-mandated reranker sentence appears in the doc in the
  visually-correct place (under the gates table, bolded). Modulo
  F1's line-wrap, the sentence is present and prominent.
- TIER-GATES.md correctly enumerates all four transitions from the
  brief in a single canonical table at the top.
- The SKIP-is-not-a-pass section (TIER-GATES.md:93-117) closes a
  real false-green failure mode that no AC required. The
  implementer correctly read the E05_S02 cold-start contract
  (`tests/eval/test_retrieval_quality.py:14-22`) and surfaced it
  as an explicit operator warning. This is the strongest part of
  the doc.
- The operator prerequisite checklist (TIER-GATES.md:119-138) maps
  the implicit prerequisites of `make eval` to concrete
  human-checkable steps. Each step references the right tool
  (`tools/validate_eval_fixtures.py`, `tools/fetch_seed.py`) and
  the right marker file path (`var/arxmcp/index/lancedb/corpus-version.json`,
  verified against `server/corpus.py`).
- The Makefile `eval` target mirrors `make test` discipline:
  Python version guard with `MIN_PY_MINOR := 11` matching
  `pyproject.toml:5` (`requires-python = ">=3.11"`) — no drift.
  `eval` is in `.PHONY`. `make help` carries the new target with
  a one-line description that points at TIER-GATES.md.
- The README placement is correct: a new top-level section
  between "Hard constraints" and "Quick start", visible above the
  fold without scrolling, with the link as a real markdown link
  (`[`TIER-GATES.md`](TIER-GATES.md)`), not a bare filename.
- The Quick-start code block carries a `make eval` row alongside
  `make help` / `make bootstrap` / `make test`, so the gate is
  one keystroke away from someone reading the README's first
  page.
- The History section explicitly retires E01_S10 and points at
  `.claude/roadmap/E01-shipped.md` (verified — that file does
  carry the `SUPERSEDED_BY E05_S03` note at its line 165). The
  retirement is recorded in two places (the shipped epic file
  and the new TIER-GATES.md) — appropriate for a breaking
  process change.
- The Tier-3 → Tier-4 / Tier-4 → Tier-5 omission is called out
  explicitly as "scope cutovers, not metric gates" rather than
  silently absent. This forecloses the future "the table missed
  two transitions" critique.
- No subjective language anywhere in TIER-GATES.md (except the
  retired qualitative criterion in the History section, which
  is the *target* of supersession, not the new spec). AC #5 is
  cleanly met.

## Recommended rectification order

1. **F1** — reflow the AC sentence onto one source line. Smallest
   change, biggest fidelity payoff. Do this BEFORE F5 so the
   regression test in F5 can use bytewise equality.
2. **F5** — add `tests/test_tier_gates_doc.py` locking all five
   ACs as CI-enforced contracts. With F1 done, the reranker test
   uses bytewise equality (matching the AC's literal-string
   wording).
3. **F2 + F3** — fix the two source-attribution drifts in one
   pass; both are textual edits in TIER-GATES.md History +
   Tier-2 → Tier-3 sections. Do these together because they're
   the same class of issue.
4. **F4** — drop or reword the Owner-approval section. Cheapest
   to drop entirely; if kept, reword per the proposed fix.
5. **F6** — add SUPERSEDED banner to ROADMAP.md (one-line edit)
   OR redirect README.md:18's roadmap link to
   `.claude/roadmap/README.md`. Defer if rectification budget is
   tight (pre-existing drift, not introduced by E05_S03).
6. **F7–F10** — LOW; record under `deferred_findings` unless the
   reflow for F1 happens to touch the same lines.

## Rectification status

**Phase 4 commit:** see `state.json` `rectification_commit` field.

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| F1 — AC sentence wrapped across line break | MEDIUM | **fixed** | `TIER-GATES.md`: reflowed the bolded sentence onto a single source line. Locked by `tests/test_tier_gates_doc.py::TestRerankerActivationSentence::test_verbatim_sentence_present` (bytewise `in` check) AND `test_sentence_is_on_one_source_line` (single-line invariant). |
| F2 — TIER-GATES.md attributes 0.70/0.80 to wrong source | MEDIUM | **fixed** | `TIER-GATES.md` § History: citation now points at `.claude/roadmap/E05-eval-harness.md` (the actual source); `.claude/notes/09-feature-priorities.md` is correctly retained as the citation for the retired qualitative criterion only. |
| F3 — TIER-GATES.md attributes 30% cache bound to wrong note | MEDIUM | **fixed** | `TIER-GATES.md` § Tier-2 → Tier-3: replaced the fabricated `07-multi-agent-caching.md` citation with an honest "set in this milestone (E05_S03) and the E05 epic header as a placeholder; E08 will re-derive against real telemetry." |
| F4 — Owner-approval mechanism is circular and unverified | MEDIUM | **fixed** | `TIER-GATES.md`: dropped the standalone `## Owner approval` section. The History section now carries a paragraph explaining that owner review is a process gate external to this commit; an `Approved-by:` trailer on a follow-up commit (or sign-off in the project tracker) is the right place to record it. |
| F5 — No regression test locks any TIER-GATES.md AC | MEDIUM | **fixed** | NEW `tests/test_tier_gates_doc.py` with 8 tests across 5 classes (one class per AC). Locks: file existence at root, all 4 transitions named, `eval` in `.PHONY`, `make eval` recipe contains the right pytest path + flag, verbatim reranker sentence (bytewise + single-line), README markdown link, and no subjective markers in the gate-spec region. |
| F6 — README.md routes readers into a stale ROADMAP.md | MEDIUM | **fixed** | `ROADMAP.md`: added a SUPERSEDED 2026-05-08 banner at the top pointing readers at `.claude/roadmap/README.md` for current epic numbering and at `TIER-GATES.md` for tier promotion conditions. Mirrors the banner pattern on `09-feature-priorities.md`. |
| F7 — TIER-GATES.md FAIL block has wrong error class FQN | LOW | **fixed (softened)** | `TIER-GATES.md` § Expected output — fail: replaced the bytewise traceback example with an abstract "the failure ends with a `ThresholdNotMetError` carrying the message ..." paragraph. Tells operators what to look for without promising bytewise format. |
| F8 — "make eval is exactly the same invocation" claim is wrong | LOW | **fixed** | `TIER-GATES.md`: reworded to "`make eval` runs the same pytest invocation, plus the Python ≥ 3.11 guard from `make test`." |
| F9 — README "Tier exit gates" sentence is ambiguous | LOW | **fixed** | `README.md`: reworded to "`make eval` must report `1 passed` (not `1 skipped`); failure means nDCG@5 fell below the 0.70 ANN-only threshold." |
| F10 — "Active gate" framing in TIER-GATES.md and README will rot | LOW | **fixed** | `TIER-GATES.md`: dropped "(the active one)" qualifier from the Tier-0 → Tier-1 section header. `README.md`: removed "The active gate today is" framing. |
| IS1 — `make eval` is a strict subset of `make test` | LOW | **acknowledged** | Intentional per brief; no action needed. The infra-safety critic explicitly recommended ship-as-is. |
| IS2 — `make eval` does not depend on `bootstrap` | LOW | **N/A** | Verified: the test creates `var/arxmcp/ops/eval/` on demand via `mkdir(parents=True, exist_ok=True)`. No missing-directory failure mode exists. |
| IS3 — Side effects in working tree | LOW | **acknowledged** | The `var/arxmcp/ops/eval/*` writes ARE the documented drift baseline (E11_S04). Atomic-write discipline is correct. |
| IS4 — `make eval` is not idempotent across corpus versions | LOW | **acknowledged** | Intentional per E11_S04's drift-detection plan (historical aggregates are the baseline). |

**New regression tests added in this rectification batch:**
- `TestTierGatesExists::test_file_at_repo_root` (AC #1, F5)
- `TestTierGatesExists::test_lists_all_four_transitions` (AC #1, F5)
- `TestMakeEvalTarget::test_eval_target_in_phony` (AC #2, F5)
- `TestMakeEvalTarget::test_eval_recipe_invokes_correct_pytest_path` (AC #2, F5)
- `TestRerankerActivationSentence::test_verbatim_sentence_present` (AC #3, F1 + F5)
- `TestRerankerActivationSentence::test_sentence_is_on_one_source_line` (AC #3, F1 belt + suspenders)
- `TestReadmeLinksTierGates::test_markdown_link_present` (AC #4, F5)
- `TestNoSubjectiveCriteria::test_subjective_markers_only_appear_in_history` (AC #5, F5)

**Suite at rectification time:** 587 passed, 3 skipped, ruff clean.

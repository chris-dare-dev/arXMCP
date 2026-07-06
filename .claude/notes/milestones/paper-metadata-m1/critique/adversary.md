# Critique — paper-metadata-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** b97e1a2..9caaab8
**Diff stats:** 7 files, 1944 LOC (1943 insertions, 1 deletion)

## Verdict

SHIP-WITH-FIXES

The three modules are well-built against the research briefs — every live-verified arXiv hazard (Retry-After: 0, plain-text 429s, max_results=10 truncation, poisoned id_list feeds, the old-style prefix-drop) has both an implementation and an offline test, and I independently reproduced 43/43 new tests, 91 adjacent tests, both frozen-hash pins, and a clean repo-wide `ruff check .` on this checkout. What blocks an unqualified SHIP: the milestone's headline acceptance (a hydrated bridgeland-stability notebook at ≥95%) has not actually been executed — no `paper_metadata.db` exists on disk — and all four commits verify unsigned against CLAUDE.md §4.3. Both are cleanly rectifiable in Phase 4 without touching the implementation code.

## Executive summary

- [CRITICAL] All four range commits verify unsigned (`git log --format=%G?` → `N`) while CLAUDE.md §4.3 mandates GPG signing and forbids `--no-gpg-sign`; the implementer flagged it, but it is unresolved at critique time.
- [HIGH] AC1's live leg never ran: `var/arxmcp/notebooks/bridgeland-stability/` contains no `paper_metadata.db`, no ≥95% coverage number is recorded, and brief-2's recorded spike re-run URL is still unexecuted.
- [HIGH] Auto-finding: 1943 inserted LOC (≈896 production) is ~5× the 400-LOC defect-detection cliff; not waivable.
- [MEDIUM] The machine-parseable summary line's `total=` counts raw papers.txt lines while `hydrated=` counts deduped normalized ids — versioned/duplicate lines deflate the exact hydrated/total ratio AC1 coverage is measured from.
- [MEDIUM] CLAUDE.md §7 still asserts "no `papers` metadata table at v1" and the §5 layout tree omits both new files — the diff creates that table's store with no doc touch.
- [MEDIUM] The t-ingest-hook descope is recorded only in the implement synthesis — no GitHub issue, unlike the repo's E13 follow-up precedent.
- [LOW] Three nits: email resolved before slug validation in `run()`; the non-retryable-HTTP give-up branch has no covering test; the synthesis's per-file test-count breakdown (18/21/24) sums to 63, not the actual 43.

## Findings

### CRITICAL — Milestone commits unsigned; CLAUDE.md §4.3 signing mandate broken

**Where:** `.claude/notes/milestones/paper-metadata-m1/implement/synthesis.md:75`
**Anchor:** `Commits made with `--no-gpg-sign` per th`
**What:** All four commits in b97e1a2..9caaab8 verify as unsigned (`%G?` = `N`) while CLAUDE.md §4.3 states "GPG signing is enabled (`commit.gpgsign=true`). **Never** `--no-gpg-sign`", and no doc update records an exception.
**Why it matters:** Pushing unsigned commits permanently breaks the repo's signed-history guarantee, and the CLAUDE.md contract is contradicted by the diff with no doc update — the exact CRITICAL analog in the severity rubric.
**Proposed fix:** Resolve before any Phase-4 push: either provision the signing key on this Windows checkout and re-create the four commits signed, or — if the orchestrator dispatch waiver the implementer cites is real and user-ratified — amend CLAUDE.md §4.3 in the rect commit to record the Windows-checkout signing exception (and refresh the stale pinned trailer text there: §4.3 still mandates `Claude Opus 4.7 (1M context)` while every commit since b0e70b6, including this range, uses `Claude Fable 5`). Note for Phase 4: the deviation is pre-existing (the ~8 commits before this range are also `N`, spanning k3s-rancher-deploy-m1) and was transparently flagged — if the dispatch record confirms authorization, invalidate or downgrade this finding with that citation.
**Regression-guard:** A pre-push gate in the Phase-4 checklist: `git log --format='%G?' origin/main..HEAD` must contain only `G`/`E` — or the documented exception that makes the gate match reality.
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

### HIGH — AC1 live hydration never executed; notebook has no metadata DB

**Where:** `tools/notebook_metadata_backfill.py:272`
**Anchor:** `def run(`
**What:** Roadmap acceptance 1 ("Given the bridgeland-stability notebook, when the backfill driver runs, then >=95% of its arxiv-kind paper_ids have a metadata row with non-NULL title and authors") has not been executed — `var/arxmcp/notebooks/bridgeland-stability/` contains no `paper_metadata.db` and no coverage number is recorded anywhere.
**Why it matters:** The milestone's namesake state ("Existing notebook hydrated with arXiv metadata") is not true on disk, and the ~6-id failure budget (14 old-style ids, future-dated ids, withdrawn papers) is precisely the part only a live run can validate — the offline mocks by construction cannot fail it.
**Proposed fix:** Before `state -> complete`, run `uv run python tools/notebook_metadata_backfill.py bridgeland-stability` (needs the persisted contact email; ~3 polite GETs plus backoffs), paste the `hydrated= skipped= missing= malformed= total=` line into the milestone synthesis, and confirm hydrated ≥ 121/127 (≥ 120/126 under brief-2's ingested-ids denominator). Execute brief-2's recorded spike re-run URL into the spike note in the same session. If arXiv is still degraded, the milestone must not be finalized as complete with AC1 unverified.
**Regression-guard:** The recorded summary line in the milestone note; optionally an env-gated live test (`requires_*` marker + `ARXMCP_RUN_LIVE_ARXIV=1`, mirroring `requires_full_corpus`) asserting hydrated/total ≥ 0.95 against the real notebook.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

### HIGH — Diff exceeds the 400-LOC review-quality cliff (auto-finding)

**Where:** no specific file
**Anchor:** `7 files changed, 1943 insertions(+), 1 deletion(-)`
**What:** The range lands 1943 inserted lines (≈896 production LOC across one new store, one new CLI, and 215 lines added to `tools/_arxiv_api.py`) in a single milestone — roughly 5× the 400-LOC threshold.
**Why it matters:** Reviewer defect-detection drops sharply past 400 LOC; this finding is logged automatically per contract and is not waivable by the implementer.
**Proposed fix:** No retroactive code change; the mitigations are this critique's file-by-file pass and Phase 4 treating the MEDIUMs as in-scope rather than deferred. For the rest of this epic (m2), keep the store-wiring slice separate from any hook work — the three-way `feat` commit split used here already helps per-commit review and should be repeated.
**Regression-guard:** Orchestrator-level diff-size gate at dispatch time (process, not a test).
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size

### MEDIUM — Summary `total=` counts raw lines, skewing the AC1 coverage ratio

**Where:** `tools/notebook_metadata_backfill.py:322`
**Anchor:** `f"total={len(raw_lines)}"`
**What:** `total` is the raw uncommented papers.txt line count while `hydrated`/`skipped`/`missing` are computed over version-stripped, deduplicated ids, so with a versioned duplicate (`X` plus `Xv1`) the counters cannot sum to `total` — the diff's own test pins `hydrated=1 total=2` for exactly this input.
**Why it matters:** AC1's ≥95% gate is measured off this machine-parseable line, and a papers.txt with duplicate/versioned lines silently deflates apparent coverage below the gate while the run is actually complete.
**Proposed fix:** Emit the deduped denominator — e.g. add `unique=<len(valid_ids)>` to the summary line (or redefine `total` as `len(valid_ids) + len(malformed)`), and update the two summary-line assertions in `tests/test_notebook_metadata_backfill.py`. ≤ 10 LOC.
**Regression-guard:** Extend `test_versioned_and_duplicate_lines_normalize_to_one_row` to assert `hydrated + skipped + missing == unique`.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

### MEDIUM — CLAUDE.md §7 "no papers metadata table at v1" now stale

**Where:** `CLAUDE.md:417`
**Anchor:** `- **`get_paper`** returns NULL for `aut`
**What:** The diff introduces exactly the papers-metadata store (plus its backfill CLI) that §7 says does not exist, and neither the §7 stub bullet nor the §5 layout tree (which omits `server/paper_metadata_store.py` and `tools/notebook_metadata_backfill.py`) was updated.
**Why it matters:** CLAUDE.md is the load-bearing session-start document; the m2 implementer will either re-derive the store's existence from scratch or plan it a second time.
**Proposed fix:** Amend the §7 bullet to "per-notebook `paper_metadata.db` store + backfill CLI shipped by paper-metadata-m1; `get_paper` still returns NULLs until m2 wires it" and add the two new files to the §5 tree. ≤ 10 LOC, fits the rect commit. (Demoted from the CRITICAL doc-contradiction analog because the bullet's operative claim — `get_paper` returns NULLs — remains true until m2.)
**Regression-guard:** n/a (doc; MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

### MEDIUM — t-ingest-hook descope has no tracked follow-up

**Where:** `.claude/notes/milestones/paper-metadata-m1/implement/synthesis.md:44`
**Anchor:** `- **t-ingest-hook: DESCOPED** to a follo`
**What:** The should-priority roadmap task `paper-metadata-t-ingest-hook` is descoped with a sound rationale, but the only record is the synthesis's Deferred section — no GitHub issue and no durable trace outside this milestone's notes.
**Why it matters:** Repo precedent files descopes as issues (E13 follow-ups `chris-dare-dev/arXMCP#1`–`#6`, UI audit `#9`); untracked, every paper ingested after m1 silently lacks metadata until an operator remembers the backfill CLI exists.
**Proposed fix:** File a `chris-dare-dev/arXMCP` issue for the best-effort, non-blocking ingest-time hydration hook (linking the synthesis rationale), or record the deferral through the pipeline's progress mechanism. Do NOT hand-edit `plans/paper-metadata/roadmap.yaml` item status — one-writer rule.
**Regression-guard:** n/a (tracking; MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

### LOW — Contact email resolved before slug validation in run()

**Where:** `tools/notebook_metadata_backfill.py:287`
**Anchor:** `contact_email = resolve_contact_email(N`
**What:** `run()` resolves the operator email (which opens the operator-settings SQLite DB) before `validate_slug(slug)`, deviating from the documented `_notebook_common` convention that slug validation "is the FIRST check every script's main() performs".
**Why it matters:** A bad-slug invocation surfaces the wrong error first and does needless settings-DB I/O; no security impact since no path is constructed from the slug before validation (`notebook_dir` re-validates).
**Proposed fix:** Swap the two statements.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

### LOW — Non-retryable HTTP give-up branch has no covering test

**Where:** `tools/notebook_metadata_backfill.py:143`
**Anchor:** `if exc.code not in (429, 503) or attemp`
**What:** The immediate-give-up path for non-retryable HTTP statuses (e.g. 400/500 → `_FetchFailure("http_400")` after exactly one attempt) is the only `_polite_fetch` branch without a test; 503, 429, network, and budget-exhaustion all have one.
**Why it matters:** A refactor could silently start retrying non-retryable statuses (burning the 3-attempt budget and politeness sleeps on hopeless requests) or crash instead of degrading to a per-id miss.
**Proposed fix:** One test: stub `_fetch_url` to raise HTTPError 400; assert exactly 1 attempt, exit code 1, and `reason=http_400` on stderr.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

### LOW — Synthesis test-count breakdown is wrong arithmetic

**Where:** `.claude/notes/milestones/paper-metadata-m1/implement/synthesis.md:109`
**Anchor:** `- +43 tests across 3 new files (18 stor`
**What:** The per-file breakdown "(18 store / 21 mapper+builder / 24 driver — 43 total)" sums to 63; the actual collected counts are 9 store / 20 mapper+builder / 14 driver = 43 (the total is correct — I reproduced 43 passed).
**Why it matters:** Milestone records feed future research briefs; wrong evidence numbers erode trust in otherwise-accurate notes.
**Proposed fix:** Correct the three per-file numbers in the rect pass.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

## What was done well

- The research's single most load-bearing finding — the `parse_atom_feed` prefix-drop that alone would cap coverage at ~89% and fail AC1 — is handled exactly right: a fully additive `parse_atom_metadata` / `extract_paper_id_from_abs_url` path, with `TestLegacyCandidateStability` pinning the legacy divergence and the fix side by side.
- Every live-verified arXiv hazard from brief-2 has both an implementation and an offline test: the `Retry-After: 0` clamp (I verified `parse_retry_after` really does `max(seconds, default)`), the ≥60 s 429 cool-down, the `max_results`-default-10 truncation guard, poisoned-batch per-id fallback, and a bounded retry budget that degrades to per-id misses instead of wedging.
- The silent-zero failure mode (empty `notebook_papers` junction table) is guarded twice: membership comes from papers.txt, and a structural test forbids any `NotebooksStore` import in the driver.
- AC2 is proven two independent ways: at runtime (`lancedb.connect` monkeypatched to raise across a cold reopen) and structurally (no lancedb / `server.corpus` / chunks imports in the store source).
- t-store-schema exceeds the letter of its acceptance: the crash-window shape (`user_version` reset behind existing tables) is explicitly re-migrated in a test, migrations are wrapped in BEGIN/COMMIT on the autocommit connection, and `DROP TABLE` is structurally banned.
- Storage placement (research open question 1) was decided with a four-point rationale recorded in the commit message, the module docstring, and the synthesis — and the m2 wiring cost of option B is honestly acknowledged rather than hidden.
- Frozen surfaces respected end to end: `server/tools.py`, `handlers/`, `prompts.py` untouched; I re-ran `tests/test_server_tool_schema.py` + `tests/test_prompts.py` (green) and 91 adjacent `_arxiv_api`/identifiers/notebook tests (green); repo-wide ruff clean; no `assert` in any of the three production files; no Markdown outside `.claude/`.
- Zero new dependencies; `defusedxml` reused for all XML parsing; every id regex-validated before URL construction; the per-notebook DB lands under gitignored `var/`, and the diff performs no external write of any kind.
- The politeness contract is test-pinned at the exact ToU boundary — a sleep before every request except the run's first, email enforced at `run()` entry with a zero-egress assertion — and the idempotent re-run is proven as zero network egress, not merely zero writes.

## Recommended rectification order

1. C1 — resolve the signing contract (re-sign or record the ratified exception in CLAUDE.md §4.3) before any push
2. H1 — execute the live backfill against bridgeland-stability and record the ≥95% numbers (plus the spike re-run URL)
3. H2 — acknowledge in Phase-4 notes (no code action; treat MEDIUMs as in-scope)
4. M1 — fix the summary-line denominator (+ regression assert)
5. M2 — CLAUDE.md §7/§5 refresh
6. M3 — file the t-ingest-hook follow-up issue
7. L1, L2, L3 — cheap nits, in that order

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

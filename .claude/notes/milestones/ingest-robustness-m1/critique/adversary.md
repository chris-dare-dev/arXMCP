# Critique — ingest-robustness-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 23b8628..b2352c0
**Diff stats:** 18 files, 953 insertions / 22 deletions (~975 LOC)
**Critique format version:** 1.0

Severity counts: C0 H1 M1 L3

## Verdict

SHIP-WITH-FIXES. The four ACs are implemented cleanly, each with dedicated
tests, and the highest-risk axes are clean: no external writes, no one-writer
violations, no dependency changes, all six commits GPG-signed with the mandated
co-author trailer, and the AC1 fallback is provably byte-identical for
sectioned papers. The only substantive actionable is a MEDIUM test gap: the two
new server-side ingest-env registrations have no covering rejection test. The
lone HIGH is the mandated, non-waivable diff-size auto-finding (the diff is
mostly tests + docs and is cleanly partitioned per-AC, so practical review risk
is moderate).

## Executive summary

- [HIGH] Diff is ~953 insertions across 18 files — over the 400-LOC
  defect-detection cliff; mandated non-waivable size auto-finding (H1).
- [MEDIUM] `server/main.py`'s new `ARXMCP_MINERU_BIN` / `ARXMCP_MINERU_TIMEOUT_S`
  carve-out entries have no test pinning their tailored rejection hint, unlike
  the CONTACT_EMAIL / LATEXML_TIMEOUT_S peers (M1).
- [LOW] The AC4 ar5iv WARN and the AC4 bulk_ingest diagnostic key on divergent
  structure-signal sets (ar5iv omits `ltx_chapter`) (L1).
- [LOW] Broad `except Exception` in the operator-settings resolver tier can
  silently mask a real settings-store bug as "binary not found" (L2).
- [LOW] One commit subject is past-tense ("shipped …") rather than imperative
  (L3).
- [clean] AC1 chunk_id determinism verified: the `if not all_chunks` guard and
  the shared content-addressable post-pass + dedup make the fallback incapable
  of perturbing a sectioned paper's output.
- [clean] External-write boundary, one-writer rule, dependency hygiene, and
  banned-pattern checks (assert/BaseHTTPMiddleware/anthropic/claude-opus) all
  pass.

## Findings

**H1 — Milestone diff exceeds the 400-LOC review-quality threshold** (HIGH)

**Where:** no specific file
**Anchor:** `git diff 23b8628..b2352c0`
**What:** The diff adds ~953 insertions across 18 files, past the 400-LOC defect-detection cliff.
**Why it matters:** Large single-review diffs statistically hide defects; this is the mandated, non-waivable size auto-finding.
**Proposed fix:** No code change is required for this milestone — the work is already partitioned into six per-AC commits (f49bd05 AC1, 386490e AC4, f31916e AC3, a7f6972 AC2, bbfb955 AC3-make, b2352c0 docs), and ~416 LOC are tests plus ~60 LOC docs, leaving ~477 LOC of production code split cleanly per-AC. For future milestones bundling independent ACs, prefer separate merge units so each review stays under the cliff.
**Regression-guard:** Per-AC commit partitioning (already present) is the mitigation; optionally add a pre-merge advisory LOC check that surfaces diffs > 400 LOC for reviewer attention.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size

**M1 — New ingest-env registrations in server/main.py have no covering test** (MEDIUM)

**Where:** `server/main.py:310`
**Anchor:** `    "ARXMCP_MINERU_BIN": (`
**What:** The two new `_KNOWN_INGEST_ENV_VARS` entries (`ARXMCP_MINERU_BIN`, `ARXMCP_MINERU_TIMEOUT_S`) added to the unknown-var scan have no test pinning their tailored carve-out message, whereas `ARXMCP_CONTACT_EMAIL` and `ARXMCP_LATEXML_TIMEOUT_S` each have a dedicated rejection test in `tests/test_server_startup.py`.
**Why it matters:** A removed key or a typo (e.g. `ARXMCP_MINERU_BINN`) would silently regress the friendly "unset it for the server" hint to a generic close-match suggestion — the exact operator footgun AC3 exists to prevent — and nothing in the suite would catch it.
**Proposed fix:** Add a test mirroring `test_latexml_timeout_env_var_rejected` that sets each MinerU var, calls `_scan_unknown_arxmcp_env_vars(Config())`, and asserts it raises `ValueError` whose message names the var and the ingest path (`textbook_parser` / MinerU). Better: parametrize a single rejection test over `_KNOWN_INGEST_ENV_VARS.keys()` so every future carve-out is covered automatically.
**Regression-guard:** tests/test_server_startup.py::test_mineru_env_vars_rejected (new)
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**L1 — AC4 ar5iv WARN and bulk_ingest diagnostic use divergent signal sets** (LOW)

**Where:** `ingest/ar5iv_fetch.py:306`
**Anchor:** `    if not any(sig in body for sig in ("l`
**What:** The ar5iv no-sections WARN keys on `("ltx_section", "ltx_theorem", "ltx_proof")` while `bulk_ingest._diagnose_empty_render` (bulk_ingest.py:268) keys on the same three plus `"ltx_chapter"`, so a chapter-only render is flagged "may be unchunkable" by one AC4 site but classified `chunker_returned_empty` (not `render_unchunkable_no_sections`) by the other.
**Why it matters:** Observability-only inconsistency — a chapter-structured render (rare for ar5iv article renders, possible for chapter-based LaTeXML output) emits a misleading WARN while its recorded failure_reason stays generic; the two AC4 signals should agree.
**Proposed fix:** Add `"ltx_chapter"` to the ar5iv WARN tuple, or hoist a shared `_STRUCTURE_SIGNALS = ("ltx_section", "ltx_theorem", "ltx_proof", "ltx_chapter")` constant consumed by both sites so they cannot drift again.
**Regression-guard:** optional
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness (consistency)

**L2 — Broad except Exception in the operator-settings tier can mask a store bug** (LOW)

**Where:** `ingest/textbook_parser.py:194`
**Anchor:** `    except Exception:  # noqa: BLE001 — deg`
**What:** `_mineru_bin_from_operator_settings` swallows every `Exception` and returns `None`, so a genuine defect in `get_setting` / `get_mineru_bin` (e.g. schema drift, a corrupt `notebooks.db`) degrades silently to `shutil.which` instead of surfacing.
**Why it matters:** An operator who persisted a valid `mineru_bin` could then hit a confusing "mineru binary not found" instead of the real store error; likelihood is low and the broad catch is the deliberate mechanism that keeps `ingest` decoupled from the `server` package, so this is acceptable as-is.
**Proposed fix:** Acceptable and tested (`test_operator_settings_read_error_degrades`); if tightening is desired, log the swallowed exception at DEBUG before returning `None` so it stays diagnosable, or narrow the catch to `(ImportError, OSError, sqlite3.Error)` and let unexpected exceptions propagate.
**Regression-guard:** optional (existing degrade-path test covers the intended behavior)
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness (error handling)

**L3 — Non-imperative commit subject "shipped …"** (LOW)

**Where:** no specific file
**Anchor:** `a7f6972 feat(tools): shipped MinerU Stage-1`
**What:** Commit a7f6972's subject `feat(tools): shipped MinerU Stage-1 PDF parse CLI` uses past tense; the convention is an imperative subject ("ship …").
**Why it matters:** Cosmetic convention drift with no functional impact; noted for completeness of the commit-hygiene sweep.
**Proposed fix:** Defer — not worth a mid-milestone history rewrite (the repo discourages `--amend`/rebase on landed history); adopt imperative mood on future subjects.
**Regression-guard:** optional
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

## What was done well

- **AC1 byte-identity is structurally guaranteed, not merely tested.** The
  `if not all_chunks:` guard (chunker.py:1019) means the fallback can only fire
  when both structural passes returned zero, so a sectioned paper's output is
  provably untouched — the BP1 golden-fixture hazard the brief flagged cannot
  occur, and a dedicated test (`test_sectioned_fixture_does_not_trigger_fallback`)
  pins it.
- **Fallback chunk_id determinism and collision-safety are inherited, not
  reinvented.** Placeholder ids are replaced by the existing content-addressable
  post-pass (chunker.py:1062) that rewrites every chunk_id regardless of kind,
  then run through the same dedup/collision-raise logic; the test asserts the
  16-char hash suffix and that math `alttext` survives into the body.
- **AC3 resolution precedence matches the brief exactly** (arg > env >
  operator_settings > which > raise), with each present-but-stale tier raising
  loudly rather than silently falling through, and the `server` dependency kept
  lazy so `ingest` never hard-imports it at module load.
- **conftest isolation was extended correctly** — `get_mineru_bin` is added to
  the operator-settings redirect list, preventing a real persisted `mineru_bin`
  on the dev box from leaking into the resolver tests.
- **AC2 CLI is well-shaped**: idempotent (skip-unless-`--force`), per-paper
  failure isolation, a clean exit-code contract, and unit tests that mock both
  the MinerU and the LaTeXML-render seams so no GPU/LaTeXML run is required.
- **Every commit is GPG-signed, conventional, ≤50-char subject, and carries the
  mandated `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer.**
- **Clean on the CRITICAL axes**: no push/publish/network, no
  `plans/*/roadmap.yaml` or checkbox edits, no new dependencies, and no banned
  patterns (`assert`-for-invariants, `BaseHTTPMiddleware`, `anthropic` at
  runtime, `server/` referencing `claude-opus`).
- **Docs are accurate**: install.md/usage.md reference an anchor that exists
  (`#optional-textbook-ingest-dep--mineru`) and a tool that exists
  (`tools/notebook_textbook_ingest.py`) — no doc drift introduced.
- **Negative and edge cases are genuinely covered per AC** — empty render stays
  empty, stale persisted path raises, missing HTML degrades to the generic
  reason, invalid paper_id raises, missing PDF is a clean failure.

## Recommended rectification order

M1, L1, L2, L3, H1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

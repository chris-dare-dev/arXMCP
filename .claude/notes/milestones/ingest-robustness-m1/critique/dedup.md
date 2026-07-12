# Critique — ingest-robustness-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 23b8628..b2352c0
**Diff stats:** 18 files, 953 insertions / 22 deletions (~975 LOC)
**Critique format version:** 1.0


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


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **L1, M2** at `ingest/ar5iv_fetch.py:306-306` (MEDIUM): AC4 ar5iv WARN and bulk_ingest diagnostic use divergent signal sets; AC4 structure-signal lists drift across three call sites

## Recommended rectification order

M1, L1, L2, L3, H1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:


# Critique — ingest-robustness-m1 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 23b8628..b2352c0
**Diff stats:** 18 files, ~975 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The load-bearing AC1 invariant is intact: the `if not all_chunks:` guard makes the section-less fallback provably incapable of perturbing a sectioned paper's chunk_ids (BP1 byte-stability holds, and the pre-existing 10-fixture `expected_chunk_ids` suite still pins it). One HIGH ships a real batch-resilience defect — the shipped MinerU CLI does not catch `subprocess.TimeoutExpired`, so a timeout on the single most-likely failure mode aborts the whole batch. The remaining three MEDIUM / one LOW are observability drift, a fallback math-fidelity gap, and a missing determinism guard — all cheap to close and none block the core recovery path.

## Executive summary

- [HIGH] `tools/notebook_pdf_parse.py` catches only `(RuntimeError, OSError)`, but `run_mineru_sandboxed` re-raises `subprocess.TimeoutExpired` (neither subclass) — a MinerU wall-timeout aborts the entire `--paper-id` batch instead of being aggregated as a per-paper failure.
- [MEDIUM] AC4 structure-signal drift: three hardcoded class lists (ar5iv 3 sigs, bulk_ingest 4 sigs, chunker `_SECTION_DIV_CLASSES` 6 classes) disagree; ar5iv omits `ltx_chapter`/subsection classes so it false-WARNs on chapter-only renders and bulk mis-categorizes subsection-only ones.
- [MEDIUM] Fallback math fidelity: `_extract_body_fallback_chunks` harvests only `ltx_para`/`ltx_p`/`p` blocks ≥80 chars, so a section-less render's top-level display-math containers (`ltx_equation`/`ltx_equationgroup`) and short standalone equations are silently dropped.
- [MEDIUM] No regression guard pins the fallback's emitted chunk_ids — a future token-packing change would silently alter the chunk_ids of every paper the fallback rescues, with nothing to catch it (the golden suite only covers sectioned papers).
- [LOW] Cross-module import of the private `_flat_paper_id` from `ingest.textbook_renderer` into `tools/notebook_pdf_parse.py`.
- [CLEAN] Axis 1 prompt-cache byte-stability: `server/tools.py` / `server/prompts.py` untouched; no tool-schema or result-envelope mutation.
- [CLEAN] Axis 7 no-fork: no submodules, no fork pins, no vendored arxiv-mcp lifts; `pyproject.toml`/`requirements*.txt` untouched.
- [CLEAN] Axis 5 local-first: unit tests mock MinerU and ar5iv `urlopen`; no external network/S3 surface added.

## Findings

**H2 — MinerU timeout aborts the whole PDF-parse batch** (HIGH)
**Where:** `tools/notebook_pdf_parse.py:92`
**Anchor:** `except (RuntimeError, OSError) as exc:`
**What:** `_parse_one` wraps `run_mineru_sandboxed` in `except (RuntimeError, OSError)`, but that function explicitly re-raises `subprocess.TimeoutExpired` (textbook_parser.py:492) on wall-timeout, and `TimeoutExpired` subclasses `subprocess.SubprocessError`/`Exception` — not `RuntimeError` and not `OSError`.
**Why it matters:** A timeout is the single most-likely per-paper failure (it is exactly why the wall-clock cap exists); leaving it uncaught propagates through `run()`/`main()` (which only catches `NotebookError`), so one pathological PDF aborts the batch with a traceback and every later `--paper-id` is skipped — violating the tool's documented "aggregates failures rather than aborting the whole batch" contract.
**Proposed fix:** Add `subprocess.TimeoutExpired` to the caught tuple: `except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:` (import `subprocess`), so a timed-out paper is logged and recorded in `failures` like any other recoverable per-paper error.
**Regression-guard:** `tests/test_notebook_pdf_parse.py::test_timeout_is_clean_per_paper_failure` — patch `run_mineru_sandboxed` to `side_effect=subprocess.TimeoutExpired(cmd="mineru", timeout=1)` for one of two paper-ids and assert `run(...) == 1`, the other paper still parsed, no exception escapes.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage (resource-cap / MinerU-sandbox timeout handling)

**M2 — AC4 structure-signal lists drift across three call sites** (MEDIUM)
**Where:** `ingest/ar5iv_fetch.py:306`
**Anchor:** `if not any(sig in body for sig in ("ltx`
**What:** The ar5iv no-sections WARN scans only `("ltx_section", "ltx_theorem", "ltx_proof")`, `bulk_ingest._diagnose_empty_render` (bulk_ingest.py:268) scans those plus `"ltx_chapter"`, and the chunker actually chunks all six `_SECTION_DIV_CLASSES` (`ltx_chapter`/`ltx_section`/`ltx_subsection`/`ltx_subsubsection`/`ltx_paragraph`/`ltx_subparagraph`); the three gates disagree and none is derived from the chunker's real gate.
**Why it matters:** A chapter-only or subsection-only render that the chunker successfully chunks trips ar5iv's "may be unchunkable" WARN (false positive), and a subsection-only render that returns empty is mis-labelled `chunker_returned_empty` instead of `render_unchunkable_no_sections` — degrading the AC4 operator-routing signal, and the two lists will silently drift further apart on any future gate change.
**Proposed fix:** Export one shared tuple next to `_SECTION_DIV_CLASSES` (e.g. `STRUCTURE_SIGNAL_CLASSES = tuple(_SECTION_DIV_CLASSES) + ("ltx_theorem", "ltx_proof")`) and import it at both signal sites so the observability heuristic tracks the chunker's actual structural gate.
**Regression-guard:** A test asserting the ar5iv WARN list and the bulk `_diagnose_empty_render` list are the same object / equal, so they cannot drift independently.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan (AC4 signal fidelity / tier drift)

**M3 — Fallback drops top-level display math and sub-80-char equation blocks** (MEDIUM)
**Where:** `ingest/chunker.py:873`
**Anchor:** `for b in doc.find_all("div", class_="lt`
**What:** `_extract_body_fallback_chunks` harvests prose only from `ltx_para` → `ltx_p` → `p` blocks and skips any block whose `_element_text` is <80 chars, so a section-less render's display equations rendered as top-level `ltx_equation`/`ltx_equationgroup` containers (not wrapped in an `ltx_para`) and any short standalone equation block contribute no `<math>` payload.
**Why it matters:** On the exact old-format renders this fallback exists to rescue, math content that lives outside prose paragraphs is silently lost — a partial violation of the project's math-fidelity-over-coverage mission (DP1), even though recovering the paper at all is still net-positive over dropping it entirely.
**Proposed fix:** After collecting prose, also gather top-level `ltx_equation`/`ltx_equationgroup`/`ltx_equationmix` blocks (via `_element_text`) into document-order position, and reconsider the 80-char floor for blocks whose text is dominated by `$...$` alttext; at minimum document the known drop so it is a deliberate, tested limitation.
**Regression-guard:** `tests/test_chunker.py` case: a section-less fixture with a top-level `<table class="ltx_equation"><math alttext="\\int f">…` and asserts the alttext survives into some emitted chunk's `body_text`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M4 — No byte-stability/determinism guard pins the fallback's chunk_ids** (MEDIUM)
**Where:** `tests/test_chunker.py:1629`
**Anchor:** `def test_section_less_render_recovers_prose`
**What:** The fallback tests assert `len(chunks) >= 1`, `kind == "section"`, id shape, and that `Z(E)` survives — but nothing pins the exact emitted chunk_ids or re-runs the chunk to assert equality, so the token-packing output has no byte-stability regression guard (the 10-fixture `expected_chunk_ids` suite only exercises sectioned papers, which by construction never reach the fallback).
**Why it matters:** The fallback feeds the same content-addressable chunk cache (BP1); a future change to `MIN_BLOCK_CHARS`, block tiering, or the `" ".join` packing would silently change the chunk_ids of every paper the fallback rescues, invalidating cached embeddings corpus-wide with no failing test.
**Proposed fix:** Add a golden fixture for the section-less shape with a pinned `expected_chunk_ids` list (list-equality, mirroring `test_expected_chunk_ids_in_document_order`), or at minimum run `_run(...)` twice and assert the two chunk_id sequences are identical.
**Regression-guard:** The pinned `expected_chunk_ids` assertion above.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability / test surface

**L4 — Cross-module import of a private helper** (LOW)
**Where:** `tools/notebook_pdf_parse.py:47`
**Anchor:** `from ingest.textbook_renderer import _flat`
**What:** The CLI imports the underscore-private `_flat_paper_id` from `ingest.textbook_renderer` (the tools→ingest direction is allowed, but reaching into a private symbol couples the CLI to an internal name).
**Why it matters:** A rename of `_flat_paper_id` inside `textbook_renderer` silently breaks this consumer; the private prefix signals "no external callers."
**Proposed fix:** Promote `_flat_paper_id` to a public `flat_paper_id` (keeping a private alias if needed) or re-export it explicitly, so the cross-module dependency is on a supported surface.
**Regression-guard:** (optional)
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan

## What was done well

- AC1 guard is airtight: `if not all_chunks:` runs the fallback only when both structural passes returned zero, so it provably cannot alter any already-chunked (sectioned) paper's chunk_ids — the BP1 corpus-wide hazard the brief flagged is closed by construction, and `test_sectioned_fixture_does_not_trigger_fallback` plus the pre-existing 10-fixture `expected_chunk_ids` suite pin it.
- Fallback chunks are given placeholder `idN` ids and then routed through the same `_compute_chunk_id` (sha256(preamble+NFC(body))[:16]) post-pass and dedup/collision loop as every other chunk, so they inherit content-addressable determinism and collision-safety unchanged.
- Math fidelity in the harvested prose is preserved: `_extract_body_fallback_chunks` uses `_element_text`, which emits `<math alttext>` as `$…$`, and the test asserts the `Z(E)` LaTeX payload survives into `body_text`.
- AC3 import direction respected: ingest resolves the binary via `server.operator_settings.get_mineru_bin` (not `tools/`), and the local import + broad `except Exception` degrade lets `ingest` import with no hard `server` dependency and fall through to `shutil.which` on any read error (tested by `test_operator_settings_read_error_degrades`).
- conftest isolation was correctly extended: `get_mineru_bin.__defaults__` is re-pointed in the autouse `_patched_operator_settings_db` fixture, so a machine with a persisted `mineru_bin` cannot leak into the resolver tests.
- No-fork clean: no submodules, no fork/vendored lifts, no arxiv-mcp headers; `pyproject.toml`/`requirements*.txt` are untouched (no new-dependency surface).
- Local-first preserved: unit tests mock `run_mineru_sandboxed`/`render_mineru_to_html` and ar5iv `urlopen`, so the suite makes no GPU/LaTeXML/network calls.
- Security hygiene on the new CLI: `run()` validates the slug (`validate_slug`) and every `paper_id` (`is_valid_paper_id`) before building any filesystem path, and the underlying MinerU subprocess keeps its scrubbed-env + RLIMIT + wall-timeout + process-group-kill sandbox.
- Resolution-tier RuntimeErrors are precise and actionable (explicit-override, env, and operator_settings each get a distinct message pointing at `make init MINERU_BIN=…`), and the Makefile threads `MINERU_BIN` via `$(if $(strip …))` so EMAIL and MINERU_BIN stay independent and correctly quoted.
- Docs (usage.md / install.md) accurately describe the explicit→env→settings→which→raise order, the two-stage headless lane, and the server's ARXMCP_* unknown-var rejection.


## Recommended rectification order

H1, M1, M3, M2, L1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:


# Critique — ingest-robustness-m1 — milestone-infra-safety-critic

**Critic:** milestone-infra-safety-critic
**Commit range:** 23b8628..b2352c0
**Diff stats:** 18 files, 975 LOC (+953/−22); infra scope: Makefile (+7/−5)
**Critique format version:** 1.0

## Verdict

DO-NOT-SHIP. The new `make init` recipe embeds a literal `$(if $(strip ...))` inside an `@#` recipe-line comment; GNU make expands `$(...)` on recipe lines even in shell comments, and that expansion is a one-argument `if` call, which is a fatal make error. `make init` now aborts on EVERY invocation — the milestone's own AC3 feature (`make init MINERU_BIN=`) cannot run, and the previously-working `make init NOTEBOOK= EMAIL=` path is broken too. This is a hard regression against a shipped onboarding verb and must be fixed before merge.

## Executive summary

- [CRITICAL] `Makefile:479` — an `@#` comment containing `$(if $(strip ...))` makes `make init` fail with `*** insufficient number of arguments (1) to function 'if'` on every call; the target never runs.
- [CRITICAL] This is a regression: the pre-diff `init` target expanded and ran correctly; the base checkout was verified working.
- [MEDIUM] The milestone's new tests exercise `notebook_init.run(...)` in-process but never dry-run the `make init` recipe, so nothing guards the Make wrapper — that gap is exactly what let this CRITICAL through.
- [CLEAN] The functional recipe (line 481) is itself correct: quoting is intact, `.PHONY: init` is declared, the line is tab-indented, and `$(if $(strip ...))` emits each flag independently for NEITHER / EMAIL / MINERU_BIN / BOTH.
- [CLEAN] The new subprocess path (`tools/notebook_pdf_parse.py` → `run_mineru_sandboxed`) preserves sandbox discipline: `shell=False` fixed argv, scrubbed env, `start_new_session`, wall-timeout + `killpg`, no new privilege.

## Findings

**C1 — `make init` fatally broken: `$(if ...)` expanded inside a recipe comment** (CRITICAL)
**Where:** `Makefile:479`
**Anchor:** `@# $(if $(strip ...)) emits each flag onl`
**What:** The `@#` recipe-line comment contains a literal `$(if $(strip ...))`, and GNU make expands `$(...)` references on recipe lines (comments included) before handing them to the shell, so make parses it as an `if` function with a single argument and aborts with `makefile:479: *** insufficient number of arguments (1) to function 'if'. Stop.`
**Why it matters:** `make init` — a first-class onboarding verb — now fails at expand time on 100% of invocations (verified: NEITHER, EMAIL-only, MINERU_BIN-only, and BOTH all abort identically), so the milestone's headline AC3 feature is unrunnable and the previously-working `EMAIL=` path is a regression.
**Proposed fix:** Escape the dollar signs in the comment so make emits them literally instead of expanding: change line 479 to `@# $$(if $$(strip ...)) emits each flag only when its var is non-empty, so` (or reword the prose to drop the `$(...)` code-literal entirely, e.g. "make's conditional-flag idiom emits each flag only when its var is non-empty"). Verified: escaping to `$$(if $$(strip ...))` clears the error and the recipe then expands correctly in all four var combinations. The functional recipe on line 481 needs no change.
**Regression-guard:** Add a Make-level smoke test (extend `tests/tools/test_notebook_scripts.py`) that shells `make -n init NOTEBOOK=demo MINERU_BIN=/x PYTHON=python3`, asserts exit 0, and asserts the captured stdout contains `--mineru-bin`; it fails today and passes after the fix. A pure-Python `notebook_init.run()` test cannot catch a broken Make recipe.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Makefile / build script discipline

**M5 — New tests never dry-run the `make init` recipe (Make wrapper unguarded)** (MEDIUM)
**Where:** `tests/tools/test_notebook_scripts.py:226`
**Anchor:** `def test_init_persists_mineru_bin(notebooks`
**What:** The two added tests (`test_init_persists_mineru_bin`, `test_init_rejects_missing_mineru_bin`) call `notebook_init.run(...)` directly and assert the Python side effect, but no test invokes the `make init` target that AC3 actually ships, leaving the Make wrapper — where C1 lives — entirely uncovered.
**Why it matters:** The Make recipe is the documented operator entry point (`make init NOTEBOOK=<slug> MINERU_BIN=<path>`), so a break in the recipe layer ships green through the whole suite, as C1 demonstrates.
**Proposed fix:** Add one `make -n init ...` dry-run test (see C1 Regression-guard); gate it on `shutil.which("make")` so it skips cleanly on boxes without make rather than hard-failing CI.
**Regression-guard:** The dry-run test in C1 doubles as this guard.
**Source critic:** milestone-infra-safety-critic
**Source axis:** Makefile / build script discipline

## What was done well

- The functional AC3 recipe (line 481) uses `$(if $(strip $(EMAIL)),...)` / `$(if $(strip $(MINERU_BIN)),...)` correctly: EMAIL and MINERU_BIN are independent optional flags, and behavior for NEITHER / EMAIL-only exactly matches the pre-diff if/else (no behavior regression in the recipe itself).
- Both interpolations stay shell-quoted (`--email "$(EMAIL)"`, `--mineru-bin "$(MINERU_BIN)"`), so values containing a space or comma pass through as a single argv token; the make-function comma-splitting happens before expansion, so a comma inside a value is safe.
- The `init` target is properly declared `.PHONY` (line 19) and the recipe lines are genuine tabs, so no "missing separator" or phony-collision hazard.
- The subprocess sandbox contract is preserved end-to-end: `tools/notebook_pdf_parse.py` delegates to `run_mineru_sandboxed`, which uses a fixed-argv `shell=False` Popen, a scrubbed env whitelist (proxies + AWS/GCP/Azure/HF creds stripped), per-invocation `TMPDIR` confinement, `start_new_session`, RLIMIT_AS on Linux, and a wall-timeout with `os.killpg` — no `shell=True`, no privilege escalation, no new egress.
- Timeout handling is sound: `--timeout-s` defaults to None (module-configured value), out-of-range values raise rather than silently clamp, and the CLI aggregates per-paper failures into a non-zero exit instead of aborting the batch mid-run.
- The binary-resolution extension (`explicit → env → operator_settings → which → raise`) validates each candidate is an existing file and degrades on any operator_settings read error via a local import, so `ingest/` gains no hard import dependency on `server/`.
- Documentation was kept honest: the Makefile `help` text, `docs/install.md`, and `docs/usage.md` were updated alongside the new `MINERU_BIN` var.


## Recommended rectification order

C1, M1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>

Severity counts: C1 H2 M5 L4

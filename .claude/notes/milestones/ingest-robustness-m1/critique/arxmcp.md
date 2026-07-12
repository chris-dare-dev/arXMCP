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

**H1 — MinerU timeout aborts the whole PDF-parse batch** (HIGH)

**Where:** `tools/notebook_pdf_parse.py:92`
**Anchor:** `except (RuntimeError, OSError) as exc:`
**What:** `_parse_one` wraps `run_mineru_sandboxed` in `except (RuntimeError, OSError)`, but that function explicitly re-raises `subprocess.TimeoutExpired` (textbook_parser.py:492) on wall-timeout, and `TimeoutExpired` subclasses `subprocess.SubprocessError`/`Exception` — not `RuntimeError` and not `OSError`.
**Why it matters:** A timeout is the single most-likely per-paper failure (it is exactly why the wall-clock cap exists); leaving it uncaught propagates through `run()`/`main()` (which only catches `NotebookError`), so one pathological PDF aborts the batch with a traceback and every later `--paper-id` is skipped — violating the tool's documented "aggregates failures rather than aborting the whole batch" contract.
**Proposed fix:** Add `subprocess.TimeoutExpired` to the caught tuple: `except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:` (import `subprocess`), so a timed-out paper is logged and recorded in `failures` like any other recoverable per-paper error.
**Regression-guard:** `tests/test_notebook_pdf_parse.py::test_timeout_is_clean_per_paper_failure` — patch `run_mineru_sandboxed` to `side_effect=subprocess.TimeoutExpired(cmd="mineru", timeout=1)` for one of two paper-ids and assert `run(...) == 1`, the other paper still parsed, no exception escapes.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage (resource-cap / MinerU-sandbox timeout handling)

**M1 — AC4 structure-signal lists drift across three call sites** (MEDIUM)

**Where:** `ingest/ar5iv_fetch.py:306`
**Anchor:** `if not any(sig in body for sig in ("ltx`
**What:** The ar5iv no-sections WARN scans only `("ltx_section", "ltx_theorem", "ltx_proof")`, `bulk_ingest._diagnose_empty_render` (bulk_ingest.py:268) scans those plus `"ltx_chapter"`, and the chunker actually chunks all six `_SECTION_DIV_CLASSES` (`ltx_chapter`/`ltx_section`/`ltx_subsection`/`ltx_subsubsection`/`ltx_paragraph`/`ltx_subparagraph`); the three gates disagree and none is derived from the chunker's real gate.
**Why it matters:** A chapter-only or subsection-only render that the chunker successfully chunks trips ar5iv's "may be unchunkable" WARN (false positive), and a subsection-only render that returns empty is mis-labelled `chunker_returned_empty` instead of `render_unchunkable_no_sections` — degrading the AC4 operator-routing signal, and the two lists will silently drift further apart on any future gate change.
**Proposed fix:** Export one shared tuple next to `_SECTION_DIV_CLASSES` (e.g. `STRUCTURE_SIGNAL_CLASSES = tuple(_SECTION_DIV_CLASSES) + ("ltx_theorem", "ltx_proof")`) and import it at both signal sites so the observability heuristic tracks the chunker's actual structural gate.
**Regression-guard:** A test asserting the ar5iv WARN list and the bulk `_diagnose_empty_render` list are the same object / equal, so they cannot drift independently.
**Source critic:** milestone-arxmcp-critic
**Source axis:** open scan (AC4 signal fidelity / tier drift)

**M2 — Fallback drops top-level display math and sub-80-char equation blocks** (MEDIUM)

**Where:** `ingest/chunker.py:873`
**Anchor:** `for b in doc.find_all("div", class_="lt`
**What:** `_extract_body_fallback_chunks` harvests prose only from `ltx_para` → `ltx_p` → `p` blocks and skips any block whose `_element_text` is <80 chars, so a section-less render's display equations rendered as top-level `ltx_equation`/`ltx_equationgroup` containers (not wrapped in an `ltx_para`) and any short standalone equation block contribute no `<math>` payload.
**Why it matters:** On the exact old-format renders this fallback exists to rescue, math content that lives outside prose paragraphs is silently lost — a partial violation of the project's math-fidelity-over-coverage mission (DP1), even though recovering the paper at all is still net-positive over dropping it entirely.
**Proposed fix:** After collecting prose, also gather top-level `ltx_equation`/`ltx_equationgroup`/`ltx_equationmix` blocks (via `_element_text`) into document-order position, and reconsider the 80-char floor for blocks whose text is dominated by `$...$` alttext; at minimum document the known drop so it is a deliberate, tested limitation.
**Regression-guard:** `tests/test_chunker.py` case: a section-less fixture with a top-level `<table class="ltx_equation"><math alttext="\\int f">…` and asserts the alttext survives into some emitted chunk's `body_text`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M3 — No byte-stability/determinism guard pins the fallback's chunk_ids** (MEDIUM)

**Where:** `tests/test_chunker.py:1629`
**Anchor:** `def test_section_less_render_recovers_prose`
**What:** The fallback tests assert `len(chunks) >= 1`, `kind == "section"`, id shape, and that `Z(E)` survives — but nothing pins the exact emitted chunk_ids or re-runs the chunk to assert equality, so the token-packing output has no byte-stability regression guard (the 10-fixture `expected_chunk_ids` suite only exercises sectioned papers, which by construction never reach the fallback).
**Why it matters:** The fallback feeds the same content-addressable chunk cache (BP1); a future change to `MIN_BLOCK_CHARS`, block tiering, or the `" ".join` packing would silently change the chunk_ids of every paper the fallback rescues, invalidating cached embeddings corpus-wide with no failing test.
**Proposed fix:** Add a golden fixture for the section-less shape with a pinned `expected_chunk_ids` list (list-equality, mirroring `test_expected_chunk_ids_in_document_order`), or at minimum run `_run(...)` twice and assert the two chunk_id sequences are identical.
**Regression-guard:** The pinned `expected_chunk_ids` assertion above.
**Source critic:** milestone-arxmcp-critic
**Source axis:** cache byte-stability / test surface

**L1 — Cross-module import of a private helper** (LOW)

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

Severity counts: C0 H1 M3 L1

## Recommended rectification order

H1, M1, M3, M2, L1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

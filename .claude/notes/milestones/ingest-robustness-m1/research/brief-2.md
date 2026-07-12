---
milestone_id: "ingest-robustness-m1"
researcher_role: "general"
external_writes_required:
  - "git merge ingest-robustness-m1 -> main (LOCAL only; end-of-milestone, after user authorization)"
  # No network/publish/deploy writes. No `git push`, no package publish, no
  # deploy, no mutating API. This is single-workstation local-first work
  # (CLAUDE.md §4.1). All corpus re-ingest is explicitly OUT OF SCOPE
  # (operational, done later against the main-tree var/ corpus).
sources: []   # no web research needed — all four ACs are internal-code work;
              # MinerU CLI surface + LaTeXML class semantics are already pinned
              # in-repo (ingest/textbook_parser.py, ingest/chunker.py).
injection_attempts: 0
---

# Research brief (general) — ingest-robustness-m1

Scope of this brief (general role): concrete implementation approach per AC,
the explicit external-writes list, the Windows test-baseline procedure, and a
diff-size / file-count estimate to drive the inline-vs-delegated Phase-2
decision. All line numbers are from the worktree snapshot at
`C:/Users/cedar/Documents/Personal Projects/Source Code/_worktrees/ingest-robustness-m1`.

## Verified ground truth (read, not assumed)

- **Chunker** `ingest/chunker.py`: two passes feed `all_chunks` at
  `:901` — `_extract_chunks_from_container` (`:554`, theorem/proof pairing on
  `ltx_theorem_*`/`ltx_proof`) and `_extract_section_chunks` (`:740`, keyed on
  `_SECTION_DIV_CLASSES` at `:154`). `_SECTION_DIV_CLASSES` = `ltx_chapter,
  ltx_section, ltx_subsection, ltx_subsubsection, ltx_paragraph,
  ltx_subparagraph` — note `ltx_para` (hep-th/0002037's block class) is NOT in
  the list, so a section-less/`ltx_para`-only render yields `[]` from BOTH
  passes. Dedup + content-addressable `chunk_id` are assigned in a post-pass
  (`_chunk_paper_impl` `:940-961`) via `_compute_chunk_id(paper_id,
  preamble_text, body_text)` = `arxiv:<pid>:<sha256(preamble + NFC(body))[:16]>`
  (`:1026`). `STMT_MAX_TOKENS = 1920` (`:92`). Token-cap helper is
  `_truncate_to_token_budget(text, max_tokens) -> (text, truncated)` (`:527`).
  `_element_text` (`:316`) preserves `<math alttext>` as `$...$`.
- **Test harness** `tests/test_chunker.py`: patches
  `ingest.chunker.PARSED_DIR` + `CHUNKS_DIR` to a tmp dir seeded from
  `tests/fixtures/chunker/<pid>/index.html` (`:107-113`), and patches
  `ingest.chunker._resolve_preamble_doc` → `None` (`:942`, `:1569`) so no real
  preamble store is needed. Sectioned fixtures already exist at
  `tests/fixtures/chunker/2307.00001..00010/index.html`.
- **bulk_ingest** `ingest/bulk_ingest.py:303-306`: `chunks = chunk_paper(pid);
  if not chunks: outcome.failure_reason = "chunker_returned_empty"; return`.
  `PaperOutcome.failure_reason` is a free-form `str | None` (`:113`), surfaced
  to the report at `:148`. Other reasons in use: `no_parsed_html`,
  `embedder_failed:*`, `embedder_produced_no_record`.
- **ar5iv_fetch** `ingest/ar5iv_fetch.py`: `_MATH_SIGNAL_RE = re.compile(r"<math\b")`
  (`:85`). The `<math>` gate is at `:272` — on a 200 with no math it returns a
  miss (`reason="no_math_in_body"`); on a hit it writes both the cache and the
  canonical parsed path (`:296-297`) and returns `Ar5ivResult(hit=True,
  reason="ok")`. `Ar5ivResult.reason` is a free-form `str` (`:106`). There is
  currently NO section/structure inspection here — only the `<math\b` regex.
- **MinerU driver** `ingest/textbook_parser.py`: `_resolve_mineru_binary()`
  (`:181`) precedence today = `ARXMCP_MINERU_BIN` env (must be an existing
  file) → `shutil.which("mineru")` → `RuntimeError`. `run_mineru_sandboxed(pdf_path,
  output_dir, *, timeout_s=None) -> MinerUResult` (`:336`). Renderer
  `ingest/textbook_renderer.py::render_mineru_to_html(result, parsed_dir,
  paper_id) -> RenderResult` (`:326`) writes `parsed_dir/<flat>/index.html`;
  `_flat_paper_id` (`:316`) maps `textbook:my-book` → `textbook_my-book`.
- **Exact chaining to mirror** `server/parse_tracker.py::_run_parse`
  (`:229-244`): lazy-import both helpers, `run_mineru_sandboxed(pdf_path,
  output_dir)` then `render_mineru_to_html(mineru_result, parsed_dir,
  paper_id)`. Upload route (`server/routes/notebooks.py:1934-1943`) sets
  `output_dir = nb_dir/parsed/<flat>/_mineru`, `parsed_dir = nb_dir/parsed`,
  and the input PDF lives at `nb_dir/pdfs/<flat>.pdf` (`:1825`, `:1851`).
- **operator_settings** `server/operator_settings.py`: sync helpers
  `get_setting(key, db_path=DEFAULT_DB_PATH)`, `set_setting(key, value, ...)`,
  and a typed convenience `get_contact_email(...)` (`:354`) importable directly
  by `ingest/` modules (avoids the `ingest/→tools/` import direction the m2
  synthesis flagged). `resolve_contact_email` (the priority chain) lives in
  `tools/_notebook_common.py:150`. Persistence at init is
  `tools/notebook_init.py::_persist_email` (`:204`) → `set_setting("contact_email", …)`,
  wired to `make init NOTEBOOK=… EMAIL=…` (`Makefile:466-480`).

## Implementation approach per acceptance criterion

### AC1 — Chunker section-less fallback

**Detection ("both passes empty AND salvageable body present").**
In `_chunk_paper_impl`, after `all_chunks = theorem_chunks + section_chunks`
(`:901`), add: `if not all_chunks: fallback = _extract_body_fallback_chunks(root,
paper_id, counter); all_chunks = fallback`. Fire the fallback ONLY when
`all_chunks == []` — this is the structural guarantee that sectioned papers are
untouched (a sectioned paper always yields ≥1 chunk from pass 1 or 2, so the
`if not all_chunks` branch is never entered for them). No need to inspect for
"salvageable body" as a separate gate first — the fallback itself harvests
top-level prose and simply returns `[]` when there is genuinely nothing (which
preserves the existing `chunker_returned_empty` outcome for truly-empty renders,
feeding AC4).

**What to harvest.** Walk the `ltx_document` container (the `root` already used
by pass 1 — `body = soup.find("body")`), collecting direct/top-level content
blocks whose text is non-trivial: `ltx_para`, `ltx_p`, and bare `<p>`. Reuse
`_element_text` (math-fidelity preserving) per block. Two viable granularities:
(a) one chunk per `ltx_para` block, or (b) accumulate blocks up to
`STMT_MAX_TOKENS` and flush (fewer, denser chunks). Recommend **(b) token-packed
accumulation** — it produces fewer chunks, mirrors `_extract_section_chunks`'s
`MIN_SECTION_TEXT_CHARS = 80` triviality filter, and each flush is capped via
the existing `_truncate_to_token_budget(prose, STMT_MAX_TOKENS)`. A single
oversized `ltx_para` (>1920 tokens) is truncated with the `truncated=True` flag,
matching pass-2 behavior.

**kind label.** Reuse the existing `kind="section"` with an EMPTY
`section_path` (`[]`). Rationale: `"section"` is already in
`ingest.store._ALLOWED_KINDS` (pass 2 emits it), so no schema change and no
`EmbedRecord`/`write_chunks` validation risk; the embedder routes non-`"proof"`
kinds to `embedding_stmt`, which is correct for prose. A NEW `"body"` kind would
require touching `_ALLOWED_KINDS` and the schema — avoid. If a distinguishable
provenance marker is wanted, set `section_path=["(untitled body)"]` rather than
inventing a kind (cosmetic only; confirm it doesn't perturb any golden fixture).

**Deterministic, non-colliding chunk_id.** Emit the fallback chunks into the
SAME `counter`/`all_chunks` list BEFORE the existing post-pass at `:940-961`, so
they flow through the identical `_compute_chunk_id(paper_id, preamble_text,
body_text)` hashing + the identical dedup rule (same `(preamble, body)` →
dropped; 64-bit prefix collision on distinct content → raise). No bespoke id
scheme. Because the fallback only runs when both passes returned `[]`, there is
zero chance of colliding with a pass-1/pass-2 chunk from the same paper.

**Sectioned-paper invariant.** Guaranteed structurally by the `if not
all_chunks` guard. Add an explicit regression test (below) so a future edit that
weakens the guard fails loudly.

**Positive test.** Add a section-less, body-rich fixture (a trimmed
`ltx_document` with several `ltx_para`/`ltx_p` blocks + inline `<math alttext>`,
zero `ltx_section`/`ltx_theorem`) at e.g.
`tests/fixtures/chunker/hep-th_0002037/index.html` (path-safe dir name; pass
`"hep-th/0002037"` as the paper_id — the chunker validates old-style ids, and
the fixture loader keys on the dir). Assert `len(chunk_paper("hep-th/0002037"))
>= 1` with `PARSED_DIR`/`CHUNKS_DIR` patched and `_resolve_preamble_doc`→`None`.
(Note: the milestone AC says the on-disk `var/…/hep-th/0002037/index.html` must
yield ≥1 chunk; the fixtured copy is the CI-portable proof of the same code
path — the real on-disk verification is the operational out-of-scope step.)

### AC2 — Shipped MinerU Stage-1 CLI

**New file `tools/notebook_pdf_parse.py`.** Arg surface mirrors
`tools/notebook_textbook_ingest.py` (a `run(slug, paper_ids, …) -> int` pure
function + a thin `main(argv)` argparse shim, `NotebookError`→exit-1):

```
uv run python tools/notebook_pdf_parse.py <slug> --paper-id <id> [--paper-id ...]
    [--timeout-s N] [--force]
```

- `validate_slug(slug)` up front (raises `NotebookError`); validate each
  `paper_id` via `ingest.identifiers.is_valid_paper_id`.
- Per paper: `flat = _flat_paper_id(paper_id)`; locate the input PDF at
  `notebook_dir(slug)/"pdfs"/f"{flat}.pdf"` (the upload-route storage path,
  `notebooks.py:1825/1851`); `parsed_dir = notebook_dir(slug)/"parsed"`;
  `output_dir = parsed_dir/flat/"_mineru"` (mkdir).
- **Idempotency:** if `parsed_dir/flat/"index.html"` exists and `--force` not
  set, log a skip and count it as success (do NOT re-run the 30-min MinerU).
- Chain exactly as `parse_tracker._run_parse` does:
  `res = run_mineru_sandboxed(pdf_path, output_dir[, timeout_s=…]);
  render_mineru_to_html(res, parsed_dir, paper_id)`.
- Exit code convention like `notebook_textbook_ingest.run`: 0 = all produced an
  `index.html`; 1 = at least one failed/missing PDF; 2 = no `--paper-id`.

**Mocked-mineru test** (`tests/test_notebook_pdf_parse.py`). Two seams to
mock so no real GPU/LaTeXML run occurs:
- `patch("tools.notebook_pdf_parse.run_mineru_sandboxed", …)` returning a fake
  `MinerUResult` pointing at a tmp markdown file; and
- `patch("tools.notebook_pdf_parse.render_mineru_to_html", …)` that writes a
  stub `parsed/<flat>/index.html` and returns a fake `RenderResult`.
Precedent: `tests/test_notebook_api.py` / `tests/test_parse_tracker.py` already
mock these two functions. Assert: (a) a fake PDF present → both helpers called
with the right paths, index.html created, exit 0; (b) index.html pre-exists +
no `--force` → neither helper called (idempotent skip); (c) missing PDF → clean
`NotebookError`/exit 1, no traceback. If the CLI imports the helpers at module
top-level, patch the names in `tools.notebook_pdf_parse`; if it lazy-imports
(matching parse_tracker), patch them at the source module — decide and keep the
test's patch target aligned.

### AC3 — Standing ARXMCP_MINERU_BIN wiring

**Precedence chain in `_resolve_mineru_binary`** (`ingest/textbook_parser.py:181`),
extended to: **explicit arg > `ARXMCP_MINERU_BIN` env > operator_settings >
`shutil.which` > raise.** Two sub-decisions:

1. *operator_settings key name:* `mineru_bin` (parallel to `contact_email`).
   Add a typed convenience getter in `server/operator_settings.py`,
   `get_mineru_bin(db_path=DEFAULT_DB_PATH)` mirroring `get_contact_email`
   (`:354`) — this keeps the read importable directly from `ingest/` and avoids
   the `ingest/→tools/` import-direction the m2 synthesis explicitly rejected.
   In `_resolve_mineru_binary`, do a LOCAL import
   (`from server.operator_settings import get_mineru_bin`) inside the function,
   matching the module's existing lazy-import discipline, wrapped so a missing
   `server`/`notebooks.db` degrades to the next tier rather than raising.
2. *explicit-arg surface:* today `_resolve_mineru_binary()` takes no args. Add
   an optional `explicit: str | None = None` parameter (default `None`) so the
   documented precedence starts at "explicit arg". `run_mineru_sandboxed` can
   thread an optional override later; for this milestone the env/settings tiers
   are what matter, but the signature should reflect the full chain the AC
   specifies. Keep the existing "path must be an existing file" validation for
   BOTH the env value and the settings value (reject a stale persisted path with
   the same clear message as the env path).

**Persistence path** (mirror the email pattern). Two viable mechanisms; do BOTH
for parity with contact_email:
- `tools/notebook_init.py`: add `--mineru-bin <path>` → `_persist_mineru_bin`
  → `set_setting("mineru_bin", path)`, exactly like `--email`/`_persist_email`
  (`:204-213`). Validate the path is an existing file before persisting.
- `Makefile`: add a `MINERU_BIN ?=` var and thread it into the `init` recipe
  (`Makefile:466-480`) alongside `EMAIL`, so `make init NOTEBOOK=… MINERU_BIN=…`
  persists it. (The AC's "and/or a documented `make init MINERU_BIN=…`".)

**Docs:** `docs/install.md` already has the MinerU section (`:107-140`,
including the `ARXMCP_MINERU_BIN` env description at `:130`). Add a short
paragraph documenting the new precedence + the `make init … MINERU_BIN=…`
persistence path so operators no longer need a per-shell export. `docs/usage.md`
gets the `tools/notebook_pdf_parse.py` invocation from AC2.

**Test:** extend `tests/test_textbook_parser.py`'s `_resolve_mineru_binary`
class (already at `:108+`) with a case: env unset, `which` empty, but
`operator_settings.mineru_bin` set to an existing tmp file → resolves to it;
and settings pointing at a missing path → raises. Patch
`server.operator_settings.get_mineru_bin` (or a tmp `db_path`) so the test
never touches the real `notebooks.db`.

### AC4 — ar5iv structure gate (residual truly-unchunkable signal)

Fires ONLY for the residual case AFTER AC1: a render that passes the `<math>`
gate but produces zero chunks even from the new fallback (i.e. no harvestable
body at all — a math-but-no-prose render).

- **bulk_ingest** (`ingest/bulk_ingest.py:304-306`): when `chunk_paper` returns
  `[]`, inspect the parsed HTML to categorize. Add a small helper
  `_diagnose_empty_render(paper_id, parsed_dir) -> str` that reads the on-disk
  `index.html` and checks for section/theorem structure (substring/regex scan
  for `ltx_section`/`ltx_theorem`/`ltx_proof`, cheap — no full DOM parse needed,
  same spirit as ar5iv's `<math\b` regex). Set
  `failure_reason = "render_unchunkable_no_sections"` when math is present but
  no structural containers AND the fallback still emptied out; keep the generic
  `"chunker_returned_empty"` otherwise. This distinct string flows through
  `PaperOutcome.failure_reason` → the parser-failures report unchanged (it is a
  free-form field), so operators can grep/route to the PDF path.
- **ar5iv_fetch** (`ingest/ar5iv_fetch.py`): after the `<math>` gate passes at
  `:272` and BEFORE the cache/parsed write at `:294`, add a lightweight
  no-sections check on `body`: if `_MATH_SIGNAL_RE` matched but there is no
  `ltx_section`/`ltx_theorem` substring, `logger.warning("ar5iv: %s rendered
  with math but no section structure — may be unchunkable; PDF path may be
  needed", paper_id)`. Do NOT change `hit`/`reason` (still a hit — the render is
  cached and, post-AC1, usually chunkable); this is a pure observability signal.
  Optionally add a module-level `_SECTION_SIGNAL_RE = re.compile(r"ltx_(section|theorem|proof)\b")`
  to keep it consistent with the `<math\b` precedent.

**Test:** `tests/test_bulk_ingest.py` — patch `chunk_paper`→`[]` with an on-disk
fixture that has math + no sections → assert
`failure_reason == "render_unchunkable_no_sections"`; and a truly-empty render →
assert generic `"chunker_returned_empty"`. `tests/test_ar5iv_fetch.py` — a
200/math/no-section body → `caplog` contains the `no_sections` WARN and
`result.hit is True`.

## external_writes_required (explicit list)

- **`git merge ingest-robustness-m1 -> main`** — LOCAL git operation only, at
  the very end, AFTER explicit user authorization (CLAUDE.md §4.1: all work
  lands on `main`; single-workstation; no PRs). This is the ONLY external-ish
  write.
- **NO `git push`** — CLAUDE.md §4.4 makes push per-event, user-initiated; it
  is not part of implementing this milestone and is not pre-authorized here.
- **NO** package publish, deploy/release, container push, or mutating external
  API call. All corpus re-ingest (hep-th/0002037 recovery, 2602.24016 SQLite
  backfill) is explicitly OUT OF SCOPE (operational, run later against the
  main-tree `var/` corpus). Unit tests use a MOCKED mineru binary — no real
  MinerU/network run. Net: this is purely local code + tests + docs.

## Test strategy incl. Windows baseline

**Per-AC coverage** (all offline, no `requires_model`/`requires_latexmlc`
markers needed — the tokenizer is the only model touch and existing chunker
tests already exercise it):
- AC1: new section-less fixture → `chunk_paper` ≥1 chunk; regression guard that
  a sectioned fixture (`2307.00001`) yields byte-identical chunk_ids before/after
  (assert the fallback did NOT fire — compare against the committed golden or
  assert the produced chunk_ids match the existing test's expectation).
- AC2: `tests/test_notebook_pdf_parse.py` with mocked
  `run_mineru_sandboxed`/`render_mineru_to_html` (3 cases above).
- AC3: `tests/test_textbook_parser.py` precedence cases incl. the new
  operator_settings tier.
- AC4: `tests/test_bulk_ingest.py` + `tests/test_ar5iv_fetch.py` categorization
  / WARN cases.
- `ruff check .` must stay clean.

**Windows baseline procedure (add-no-new-failures).** CLAUDE.md §3/§8 documents
~29 pre-existing Windows-platform failures (`os.getpgid`, POSIX shell tests,
colons-in-filenames, symlinks). Establish the baseline BEFORE any edit and
compare AFTER, using the MAIN-TREE venv python with PYTHONPATH pinned to the
WORKTREE so the worktree source is what runs (the worktree has no `.venv`):

```bash
# From the worktree root. PYTHONPATH pin makes the worktree the import root.
PY="C:/Users/cedar/Documents/Personal Projects/Source Code/arXMCP/.venv/Scripts/python.exe"
WT="C:/Users/cedar/Documents/Personal Projects/Source Code/_worktrees/ingest-robustness-m1"

# BASELINE (before edits) — capture the failing set for the touched subset:
PYTHONPATH="$WT" "$PY" -m pytest \
  tests/test_chunker.py tests/test_bulk_ingest.py tests/test_ar5iv_fetch.py \
  tests/test_textbook_parser.py tests/test_notebook_textbook_ingest.py \
  tests/test_operator_settings.py tests/test_notebook_init.py \
  --tb=no -p no:warnings -q  2>&1 | tee /tmp/baseline.txt

# AFTER edits + new test files: re-run the same set PLUS the new test module,
# diff the failed-node list. The pass count must rise by the number of NEW
# tests and the FAILED set must be a subset of baseline (no new failures).
```

Recommended: run the full suite once at baseline
(`PYTHONPATH="$WT" "$PY" -m pytest --tb=no -p no:warnings -q`) to confirm the
~29-failure Windows number, then rely on the touched-subset diff for the tight
loop. Verify `ruff check .` from the worktree. macOS/Linux would show 0 of those
29 (informational only; the gate here is Windows-parity: no NEW failures).

*Caveat to flag:* AC2/AC3 exercise `ingest/textbook_parser.py`, which is one of
the modules implicated in the Windows landmines (killpg/symlink handling). The
tests mock the subprocess, so they should be platform-clean, but confirm the new
`test_notebook_pdf_parse.py` does not assert on POSIX-only path shapes (use
`Path`/`os.path`, not hardcoded `/`), or it will itself become failure #30.

## Diff-size / file-count estimate → Phase-2 routing

| Area | Files | Est. LOC |
|---|---|---|
| AC1 chunker fallback (`ingest/chunker.py`) | 1 | ~60 |
| AC1 fixture + tests (`tests/fixtures/chunker/hep-th_0002037/index.html`, `tests/test_chunker.py`) | 2 | ~90 |
| AC2 new CLI (`tools/notebook_pdf_parse.py`) | 1 | ~130 |
| AC2 test (`tests/test_notebook_pdf_parse.py`) | 1 | ~110 |
| AC3 resolver + getter + init + Makefile (`textbook_parser.py`, `operator_settings.py`, `notebook_init.py`, `Makefile`) | 4 | ~55 |
| AC3 tests (`tests/test_textbook_parser.py`, `test_notebook_init.py`) | 1-2 | ~50 |
| AC4 bulk_ingest + ar5iv (`ingest/bulk_ingest.py`, `ingest/ar5iv_fetch.py`) | 2 | ~35 |
| AC4 tests (`tests/test_bulk_ingest.py`, `test_ar5iv_fetch.py`) | 2 | ~55 |
| Docs (`docs/install.md`, `docs/usage.md`) | 2 | ~40 |
| **Total** | **~16 files** | **~600-650 LOC** |

**Routing decision: DELEGATED Phase-2.** Both thresholds cross the inline gate:
file count is ~16 (>5) and LOC ~600 (in the 300-800 band). `allow_large_diff` is
`false` in state.json and the estimate stays under 800, so no large-diff
escalation is needed — a single `milestone-implementer` dispatch fits. The four
ACs are loosely coupled (chunker vs MinerU-CLI vs settings-wiring vs
gate-signal) and could be staged in that order; AC4's bulk_ingest change should
land AFTER AC1 so the "residual" categorization is tested against the
post-fallback behavior.

## Risks and open questions (≤5)

1. **AC1 fallback granularity vs golden-fixture determinism.** If the fallback
   is ever mis-gated (fires on a paper that pass-2 already handled), it would
   silently change chunk_ids corpus-wide — the exact BP1 byte-stability hazard.
   Mitigation is the `if not all_chunks` structural guard + the sectioned
   regression test; the implementer must NOT relax that guard. Open: should the
   fallback also require a minimum total body-char count (e.g. reuse
   `MIN_SECTION_TEXT_CHARS`) to avoid emitting a chunk for a near-empty
   math-only render (which is exactly what AC4 wants left empty)?
2. **AC4 double-signal coupling.** The bulk_ingest `_diagnose_empty_render`
   re-reads the HTML that `chunk_paper` just parsed — a second file read + a
   regex that must agree with the chunker's own "no structure" verdict. If the
   two drift, an operator sees `render_unchunkable_no_sections` for a paper the
   chunker could actually handle. Lower-risk alternative: have `chunk_paper`
   surface WHY it returned empty (a sentinel/enum) instead of bulk_ingest
   re-deriving it — but that widens the chunker's return contract. Flagging for
   the implementer to pick; the regex-scan approach is the lighter diff.
3. **operator_settings read from `ingest/` at MinerU-resolve time.** Adding
   `get_mineru_bin` keeps the import direction clean, but `_resolve_mineru_binary`
   is called inside the sandboxed-subprocess path; a `notebooks.db` open there
   adds a SQLite touch on every parse. Confirm the local-import + missing-DB
   graceful-degrade (returns `None`, falls through to `which`) so a parse on a
   box with no `notebooks.db` still works.
4. **Windows parser-module tests as failure #30.** `textbook_parser.py` is in
   the Windows-landmine zone. The new CLI test mocks the subprocess, but any
   incidental POSIX-path assertion would add a Windows failure the milestone is
   forbidden to add. Keep all path assertions `Path`-based.
5. **hep-th/0002037 fixture fidelity.** The AC pins the real on-disk render
   (93 `ltx_para`, 321 `<math>`, zero `ltx_section`). The committed test fixture
   must faithfully reproduce that shape (section-less `ltx_document` with
   `ltx_para` blocks) or the positive test passes while the real render still
   fails. Recommend deriving the fixture by trimming the actual
   `var/arxmcp/corpus/parsed/hep-th/0002037/index.html` (available in the main
   tree) down to a representative subset, preserving the class structure.

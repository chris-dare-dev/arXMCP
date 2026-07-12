---
milestone_id: "ingest-robustness-m1"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — ingest-robustness-m1

Codebase context map for the four durable ingest-robustness fixes:
(1) chunker section-less fallback, (2) shipped MinerU Stage-1 CLI,
(3) standing `ARXMCP_MINERU_BIN` wiring, (4) ar5iv structure gate.
All line anchors verified against the worktree snapshot. `var/` is
gitignored and absent here — reasoning is from code + fixtures.

---

## Affected files / context (with anchors)

### AC1 — Chunker section-less fallback

`ingest/chunker.py`
- `STMT_MAX_TOKENS = 1920` — `:92` (token cap for the fallback prose chunks).
- `_SECTION_DIV_CLASSES` — `:154-161`. Contains `ltx_chapter/ltx_section/
  ltx_subsection/ltx_subsubsection/ltx_paragraph/ltx_subparagraph`.
  **Key fact:** `ltx_paragraph` (`:159`) is a *section-level* class; it is
  NOT the same as `ltx_para` (LaTeXML's prose content-block `<div class=
  "ltx_para">`). The chunker code never references `ltx_para`/`ltx_document`/
  `ltx_page_content` today (grep-confirmed; `ltx_para` appears only in
  `ingest/extract_equations.py:113,120` as `div.ltx_para` with a first `<p>`
  child). This is exactly why hep-th/0002037 drops its prose.
- `_get_classes(tag)` — `:312`; `_has_class(tag, cls)` — `:306`.
- `_element_text(tag)` — `:316-350`. Walks the subtree; replaces each
  `<math>` with `$<alttext>$`; collapses whitespace. **Reuse verbatim** to
  extract prose text (preserves the 321 `<math>` payloads in the fixture).
- `_truncate_to_token_budget(text, max_tokens) -> (text, truncated)` —
  `:527-546`. Offset-mapping substring slice + `truncated` flag. **Reuse** to
  cap each fallback block to `STMT_MAX_TOKENS`.
- `_extract_chunks_from_container(container, paper_id, counter, depth=0)` —
  `:554-732`. Pass 1. Recurses into `section/div/article` (`:635-637`),
  keyed on `ltx_theorem_*`/`ltx_proof`. Emits nothing for prose-only bodies.
- `_extract_section_chunks(soup, paper_id, counter)` — `:740-819`. Pass 2.
  `MIN_SECTION_TEXT_CHARS = 80` (`:754`); `_is_section_class` (`:763-766`);
  iterates `soup.find_all(True, class_=_is_section_class)` (`:768`) — i.e.
  only harvests `<p>/<div>` prose that sits *inside* an `ltx_section`-family
  element. Zero such elements ⇒ zero chunks. This is the exact prose-harvest
  shape the fallback should imitate, minus the section-membership gate.
- `chunk_paper(paper_id)` — `:827-862` (validate → resilience envelope).
- `_chunk_paper_impl(paper_id)` — `:865-985`. **The hook site.**
  - `soup`/`body`/`root` set at `:874-877` (`root = <body>` or `soup`).
  - stale-file cleanup at `:886-891` (runs first — good).
  - Pass 1 at `:896`; Pass 2 at `:899`; **combine at `:901`
    (`all_chunks = theorem_chunks + section_chunks`)** ← insert fallback here.
  - preamble_ref stamp `:909-912`; body_tokens `:918-919`;
    chunk_id + dedup loop `:930-961`; per-chunk JSON write `:965-975`;
    manifest `:983`.
- `_compute_chunk_id(paper_id, preamble_text, body_text)` — `:1026-1050`.
  `arxiv:<paper_id>:<sha256(preamble + NFC(body))[:16]>`. Fallback chunks
  flow through this unchanged if inserted before `:930`.

### AC2 — Shipped MinerU Stage-1 CLI (new `tools/*.py`)

`ingest/textbook_parser.py`
- `run_mineru_sandboxed(pdf_path, output_dir, *, timeout_s=None) ->
  MinerUResult` — `:336-479`. `MinerUResult` dataclass `:258-274`
  (`output_dir/markdown_path/content_list_path/stdout/stderr/wall_clock_s`).
- `_resolve_mineru_binary()` — `:181-211` (see AC3).

`ingest/textbook_renderer.py`
- `render_mineru_to_html(result, parsed_dir, paper_id) -> RenderResult` —
  `:326-459`. Writes `parsed_dir/<flat_paper_id>/index.html`.
  `_flat_paper_id` `:316-323` (`textbook:my-book` → `textbook_my-book`).
- `_build_latex_wrapper` `:273-313`.

`server/parse_tracker.py:229-244` — **the canonical two-call chain the CLI
should mirror** (server-side production caller):
`run_mineru_sandboxed(pdf_path, output_dir)` →
`render_mineru_to_html(mineru_result, parsed_dir, paper_id)`. Output path
scrubbed via `redact_html_path` (`:102-120`).

CLI shape model — `tools/notebook_textbook_ingest.py` (whole file): argparse,
`validate_slug` up front, `run()`/`main()` split, `NotebookError → exit 1`,
`raise SystemExit(main())`. Path helpers in `ingest/textbook_chunker.py`:
`_textbook_html_path(nb_dir, paper_id)` (`:122-124`) resolves
`nb_dir/parsed/<flat>/index.html` — the CLI's idempotency check
("skip if index.html exists") should probe this exact path.

`tools/_notebook_common.py`: `validate_slug` `:58-76`, `notebook_dir` `:79-123`
(slug regex + symlink refusal + containment), `notebook_lancedb_path` `:126-147`,
`resolve_contact_email` `:150-225` (the priority-chain pattern to mirror for AC3).

### AC3 — Standing `ARXMCP_MINERU_BIN` via operator_settings

`ingest/textbook_parser.py:_resolve_mineru_binary` — `:181-211`. Current
order: `ARXMCP_MINERU_BIN` env (`:193-201`) → `shutil.which("mineru")`
(`:202-204`) → `RuntimeError` (`:205-211`). Target order (brief AC3):
explicit arg > env > **operator_settings** > which > raise.

`server/operator_settings.py`: sync helpers `get_setting(key, db_path)` `:285`,
`set_setting(key, value, db_path)` `:309`, `delete_setting` `:334`,
`get_contact_email` `:354` (the convenience-reader precedent — add a peer
`get_mineru_bin`?). `DEFAULT_DB_PATH = var/arxmcp/cache/notebooks.db` `:91`.
`_RESERVED_KEYS` = `{__schema_version__}` only (`:100`) — a new `mineru_bin`
key is NOT reserved and needs NO migration (`SCHEMA_VERSION` stays `1`;
the table is a generic KV store).

`server/main.py:_KNOWN_INGEST_ENV_VARS` — `:280-306`. **Contains only
`ARXMCP_CONTACT_EMAIL` and `ARXMCP_LATEXML_TIMEOUT_S`. `ARXMCP_MINERU_BIN`
and `ARXMCP_MINERU_TIMEOUT_S` are ABSENT.** `_scan_unknown_arxmcp_env_vars`
(`:367-407`) **RAISES ValueError (fatal at startup)** for any `ARXMCP_*` env
var not declared on `Config` — the carve-out only softens the message, it
does NOT exempt the raise. So an operator who exports `ARXMCP_MINERU_BIN`
today FATALs `make up`. AC3's operator_settings path is precisely the escape:
persist the path, never export the env var. Companion change: add both MinerU
vars to `_KNOWN_INGEST_ENV_VARS` so an operator who *does* export them gets
the friendly "unset for the server; it is persisted via `make init`" hint.

`Makefile`: `init:` target `:466-478` calls `tools/notebook_init.py <slug>
--email <EMAIL>` (which persists `contact_email`). AC3's `make init
MINERU_BIN=...` variant would thread a `--mineru-bin` flag through the same
tool to `set_setting("mineru_bin", ...)`.

### AC4 — ar5iv structure gate

`ingest/ar5iv_fetch.py`: `_MATH_SIGNAL_RE = re.compile(r"<math\b")` `:85`;
`_AR5IV_ERROR_BANNER = "could not be processed"` `:90`. `try_cache` `:114-306`:
math gate at `:272` (`if not _MATH_SIGNAL_RE.search(body) or
_AR5IV_ERROR_BANNER in body: → miss`); parsed-path write at `:296-297`.
**Hook the `no_sections` warning right after `:272` passes** (fresh-fetch
path only). Caveat: the local-cache early-return at `:156-164` skips body
read entirely, so a `no_sections` warning here fires only on network fetch,
not on cache hits — acceptable per the brief (it is the secondary signal).
`Ar5ivResult` dataclass `:98-106` (has a `reason` str field).

`ingest/bulk_ingest.py`: `ingest_one_paper` `:249-333`;
`chunks = chunk_paper(paper_id)` `:303`; **`if not chunks: failure_reason =
"chunker_returned_empty"` at `:304-306`** ← AC4's primary categorized signal.
`_has_local_parsed_html(paper_id, parsed_dir)` `:235-246` gives the parsed
HTML path so `ingest_one_paper` can re-inspect the render to distinguish
`no_sections`/`render_unchunkable` from a generic empty. `PaperOutcome`
`:104-113` (`failure_reason: str | None`); `_log_parser_failure` `:140-152`
writes `bulk.jsonl` (`parsers_tried`/`failure_reason`/`timestamp`).

---

## Existing patterns to reuse

1. **Fallback should be a new pass that emits placeholder-id ChunkRecords,
   NOT a self-contained writer.** Insert it at `chunker.py:901` guarded by
   `if not all_chunks:`. Everything downstream — preamble_ref stamp,
   `tokenize_body`, `_compute_chunk_id`, the dedup loop, JSON write, manifest
   — then applies unchanged. This gives "same content-addressable chunk_id
   scheme + token-capped + deduped" **for free** and guarantees zero change
   for sectioned papers (the guard only fires when both passes yield nothing).
   Each fallback block: `_element_text(block)` → `_truncate_to_token_budget
   (text, STMT_MAX_TOKENS)` → `ChunkRecord(kind="section", section_path=[],
   theorem_name=None, theorem_label=None, body_text=..., truncated=...)`
   using the shared `counter`. `"section"` is in `store._ALLOWED_KINDS`
   (`ingest/store.py:145-169`) — no schema/enum change needed.
2. **Harvest target:** locate `ltx_document` (`soup.find(class_="ltx_document")`,
   typically `<article class="ltx_document">`; fall back to
   `ltx_page_content` then `root`), then iterate its `ltx_para` blocks
   (`div.ltx_para`), or `p.ltx_p` if no `ltx_para` exists. Reuse
   `MIN_SECTION_TEXT_CHARS = 80` to skip trivial blocks. One-chunk-per-block
   is the simplest deterministic reading of "prose chunks from top-level
   blocks"; grouping/windowing a giant single block is optional (existing
   section pass just truncates, so per-block+truncate matches precedent).
3. **CLI**: copy `tools/notebook_textbook_ingest.py`'s argparse/validate/
   run/main skeleton; chain `run_mineru_sandboxed` + `render_mineru_to_html`
   exactly as `server/parse_tracker.py:229-244`; derive `parsed_dir` as
   `notebook_dir(slug)/parsed`, `paper_id` default `textbook:<slug>`,
   `output_dir` a per-invocation scratch under `parsed_dir`. Idempotency:
   skip when `_textbook_html_path(nb_dir, paper_id)` exists.
4. **AC3 import direction (memory lesson, onboarding-uplift-m2):** `ingest/`
   must NOT import from `tools/`. `_resolve_mineru_binary` should read the
   persisted value via a lazy `from server.operator_settings import
   get_setting` (mirrors how `ingest/inspire_ingest.py` etc. read
   `get_contact_email` from `server.operator_settings`, per `_notebook_common`
   docstring `:186-192`).
5. **operator_settings test isolation is already provided:** `tests/conftest.py`
   autouse `_patched_operator_settings_db` (`:296-335`) redirects
   `DEFAULT_DB_PATH` AND re-points each helper's `__defaults__`. New AC3 tests
   that call `get_setting("mineru_bin")` inherit this redirect automatically.
6. **Mocked-mineru unit-test pattern (AC2):** `tests/test_textbook_parser.py`
   `_fake_proc()` (`:482-495`, MagicMock spec of `subprocess.Popen`),
   `_make_pdf_and_outputs` (`:501-514`, pre-creates the MinerU output tree),
   `patch.object(subprocess, "Popen", return_value=_fake_proc(...))`
   (`:521-525`), `_create_fake_bin` + `ARXMCP_MINERU_BIN` env. The CLI test
   should mock at the `run_mineru_sandboxed`/`render_mineru_to_html` seam (or
   the Popen+latexml seam) so no real 30-min GPU run occurs.

---

## Exact hook points (summary)

| AC | File:line | Action |
|----|-----------|--------|
| 1 | `ingest/chunker.py:901` | after `all_chunks = theorem_chunks + section_chunks`, add `if not all_chunks: all_chunks = _extract_fallback_prose_chunks(soup, paper_id, counter)`; new helper harvests `ltx_para`/`ltx_p` under `ltx_document`, token-caps via `_truncate_to_token_budget`, emits `kind="section"` ChunkRecords with placeholder ids. |
| 2 | new `tools/notebook_pdf_parse.py` | argparse CLI: `run_mineru_sandboxed` → `render_mineru_to_html`; idempotent skip on existing `index.html`. |
| 3 | `ingest/textbook_parser.py:181-211` | insert operator_settings lookup between env (`:201`) and `which` (`:202`), via lazy `server.operator_settings.get_setting("mineru_bin")`; add `--mineru-bin` persistence to `tools/notebook_init.py` + `make init`; register `ARXMCP_MINERU_BIN`/`ARXMCP_MINERU_TIMEOUT_S` in `server/main.py:_KNOWN_INGEST_ENV_VARS`. |
| 4 | `ingest/bulk_ingest.py:304-306` + `ingest/ar5iv_fetch.py:~272` | bulk_ingest: re-inspect parsed HTML on empty → set `failure_reason="render_unchunkable_no_sections"` vs generic; ar5iv: `logger.warning(... no_sections ...)` after the math gate passes on a fresh fetch. |

---

## Test / fixture inventory

- **`tests/test_chunker.py`** (1572 lines). Golden `TestFixtureSuite`
  (`:1407-1571`) pins `chunk_count`, full `kind_counts`, and document-ordered
  `expected_chunk_ids` for 10 fixtures via `_run` (`:1551-1571`, patches
  `PARSED_DIR`/`CHUNKS_DIR`/`_resolve_preamble_doc`). **This is the AC1
  regression guard** — all 10 fixtures are sectioned and produce ≥1 chunk, so
  the fallback (guarded on empty) must leave every expected id byte-identical.
  New AC1 test: stage a synthetic prose-only, section-less, theorem-less HTML
  (`<article class="ltx_document"><div class="ltx_para"><p class="ltx_p">…`)
  under a patched `PARSED_DIR` and assert `chunk_paper(...)` yields ≥1 chunk
  with valid `arxiv:<id>:<16hex>` ids. Reuse the `TestB2BudgetBump` /
  `TestF4` synthetic-HTML idiom (`:904-920`, `:1126-1150`).
- **`tests/test_chunker_ids.py`**: determinism/collision guards —
  `_compute_chunk_id` purity, two-run identity (`:140-149`), NFC
  (`:185-193`), fresh-process determinism (`:571-613`), dedup vs collision
  (`:457-563`). Fallback chunks inherit all of these automatically.
  `TestSingleVersionDefinition` (`:342-387`) scans every `ingest/*.py` for
  the `"v1.1"` literal — a new fallback helper/module must NOT hardcode the
  version literal (use the `ChunkRecord` default).
- **`tests/fixtures/chunker/2307.0000{1..10}/index.html` + `.expected.json`**
  — the golden set. Regeneration runbook: `.claude/docs/chunker-fixtures.md`.
- **`tests/conftest.py`**: autouse path redirects (`_patched_store_stats_path`
  `:159`, `_patched_operator_settings_db` `:296`). No autouse patch of
  `chunker.PARSED_DIR` — each test patches it locally.
- **`tests/test_textbook_parser.py`**: `TestResolveMineruBinary` (`:105-146`)
  pins the env→which→raise chain — **must be extended for the new
  operator_settings tier** (add a test: env unset, which empty, but
  operator_settings has `mineru_bin` → returns it). Mocked-Popen surface at
  `:498-548`.
- **`tests/test_textbook_renderer.py`, `tests/test_parse_tracker.py`** — model
  for the CLI's parser+renderer chaining assertions.
- **`tests/test_bulk_ingest.py`**: `failure_reason` tests (`:327-354`,
  `:400-447`); `_log_parser_failure` JSONL shape (`:68-96`). New AC4 test:
  a section-less-but-math-bearing render that (pre-AC1) would be empty →
  assert the distinct `failure_reason`.
- **`tests/test_ar5iv_fetch.py`**: math-gate tests (`:152-223`,
  `no_math_in_body`). Model for a `no_sections` warning/log test.
- **`tests/test_server_startup.py`** references `_KNOWN_INGEST_ENV_VARS` /
  the unknown-ARXMCP scan — **check it after adding the two MinerU vars**
  (it may assert the carve-out set or the rejection message).

---

## Regression risks

1. **Golden fixture drift (highest).** The 10-fixture suite pins exact
   `expected_chunk_ids` in document order. The `if not all_chunks:` guard
   makes the fallback unreachable for every sectioned paper, so no golden id
   should move. Verify by running `tests/test_chunker.py` unchanged.
2. **chunk_id determinism / collisions.** Fallback chunks must route through
   the existing `_compute_chunk_id` + dedup loop (`:930-961`) — do not
   compute ids inside the fallback helper. hep-th/0002037 is old-style, so
   ids are `arxiv:hep-th/0002037:<hex>` (valid per `identifiers.CHUNK_ID_
   PATTERN`, `ingest/identifiers.py:132-137`); filename is the hex suffix
   (no slash) so no path issue.
3. **`_PAPER_ID_RE` three-copy lock.** `chunker.py:111-121` is byte-locked to
   `identifiers._PAPER_ID_FULL_PATTERN` and `tools/validate_eval_fixtures.py`
   by `tests/test_identifiers.py::TestPaperIdRegex`. The fallback needs no
   regex change — leave these untouched.
4. **textbook_chunker does NOT inherit the fallback.**
   `ingest/textbook_chunker.py:349-353` reuses `_extract_chunks_from_container`
   + `_extract_section_chunks` but has its OWN `_chunk_textbook_impl`, not
   `_chunk_paper_impl`. A fallback added to `_chunk_paper_impl` will not apply
   to textbook chunking. That is acceptable for this milestone (textbook path
   gets sections via m6 markdown-heading→`\section` conversion). If shared
   coverage is later wanted, factor the fallback into a helper both call.
5. **AC3 server-startup fatal.** Registering the MinerU vars in
   `_KNOWN_INGEST_ENV_VARS` is a companion change, but note that carve-out
   membership does NOT prevent `_scan_unknown_arxmcp_env_vars` from raising —
   the only way to keep `make up` green is for the operator to NOT export the
   env var (rely on operator_settings). Do not add a `Config` field for it
   (memory lesson 2026-06-08: these are ingest-only vars, never server config).
6. **operator_settings default-arg binding.** `get_setting` binds
   `db_path=DEFAULT_DB_PATH` at def-time; tests rely on conftest's
   `__defaults__` re-point. Any new `get_mineru_bin(db_path=DEFAULT_DB_PATH)`
   convenience reader must follow the same single-default-arg shape or add
   itself to conftest's re-point loop (`conftest.py:333`).
7. **Windows caveats.** ~29 pre-existing Windows failures (colons-in-filenames,
   `os.getpgid`, symlinks — CLAUDE.md §3/§8). New tests must not assume POSIX;
   the mocked-mineru CLI test must not spawn a real binary. Establish the
   Windows baseline (green minus the 29) before claiming AC5.
8. **BP1 pinned hashes are NOT at risk.** `tests/test_server_tool_schema.py`
   (`EXPECTED_TOOL_SCHEMA_SHA256`) and `tests/test_prompts.py`
   (`EXPECTED_BP1_SHA256`) only move if `server/tools.py` or
   `server/prompts.py` change — this milestone touches neither.

---

## Acceptance criteria the implementer must meet

1. **Section-less fallback** in `chunker.py`: when both passes yield zero AND
   `ltx_para`/`ltx_p` body content exists under `ltx_document`, emit prose
   chunks (same `_compute_chunk_id` scheme, `STMT_MAX_TOKENS`-capped, deduped).
   `chunk_paper("hep-th/0002037")` on the on-disk HTML → ≥1 chunk. Zero change
   to any sectioned fixture's output.
2. **Shipped MinerU Stage-1 CLI** (`tools/notebook_pdf_parse.py` or similar):
   `run_mineru_sandboxed` + `render_mineru_to_html` → `parsed/<flat>/index.html`
   for a textbook notebook; idempotent (skip if `index.html` exists);
   unit-tested with a MOCKED mineru binary.
3. **Standing `ARXMCP_MINERU_BIN`**: `_resolve_mineru_binary` precedence
   arg > env > operator_settings > which > raise; persist via
   `operator_settings` (`make init MINERU_BIN=…`); register the env vars in
   `server/main.py:_KNOWN_INGEST_ENV_VARS`; document in `docs/install.md`.
4. **ar5iv structure gate**: bulk_ingest emits a distinct categorized
   `failure_reason` (e.g. `render_unchunkable_no_sections`) vs generic
   `chunker_returned_empty`; ar5iv_fetch logs a `no_sections` warning on the
   fresh-fetch path.
5. **Tests + gate**: per-AC tests; `ruff check .` clean; pytest green
   accounting for the ~29 pre-existing Windows failures — add no new failures.

---

## Risks and open questions (≤5)

1. **Fallback granularity.** One chunk per top-level `ltx_para`, or accumulate
   blocks up to `STMT_MAX_TOKENS`? Per-block is deterministic and matches the
   section pass's truncate-don't-window behavior; recommend per-block with the
   `MIN_SECTION_TEXT_CHARS=80` skip. A single oversized block is truncated
   (content loss flagged by `truncated=True`) — acceptable unless the team
   wants proof-style windowing.
2. **AC4 double-read cost.** Distinguishing `no_sections` in bulk_ingest
   means re-opening `parsed/<id>/index.html` after `chunk_paper` returns `[]`.
   Cheap at per-paper scale, but is a small helper `_classify_empty_reason
   (paper_id, parsed_dir)` (checks `<math` present + `ltx_section`/
   `ltx_theorem` absent) the right home, or should the chunker expose a
   structured diagnostic instead of `[]`? Changing `chunk_paper`'s return type
   is a large regression surface — recommend the helper.
3. **operator_settings key name + reader.** `"mineru_bin"` value = absolute
   path. Add a `get_mineru_bin()` convenience reader (peer of
   `get_contact_email`) so `ingest/textbook_parser.py` imports from
   `server.operator_settings` without a `tools/` cross-import. Should the
   persisted path be existence-validated at read time (like the env branch at
   `:195`) or only at spawn time?
4. **`make init MINERU_BIN=` plumbing.** Cleanest is a `--mineru-bin` flag on
   `tools/notebook_init.py` → `set_setting`. Confirm `notebook_init.py` is the
   right host (it already persists `--email`); a standalone
   `tools/set_operator_setting.py` is an alternative.
5. **hep-th/0002037 verification without `var/`.** The real render is absent
   in this worktree. AC1's `chunk_paper("hep-th/0002037")` assertion must be
   backed by a committed synthetic fixture reproducing the described shape
   (section-less/theorem-less, `ltx_document` + `ltx_para` + `<math>`), since
   the live file cannot be fixtured from `var/`. The operational re-ingest of
   the real paper is explicitly out of scope (done post-merge against the
   main tree).

# Textbook chunker golden-fixture runbook (textbook-ingest-m7)

Sibling of [`chunker-fixtures.md`](chunker-fixtures.md) for the
hierarchical textbook chunker (`ingest/textbook_chunker.py`).

## What the fixtures are

`tests/fixtures/textbook_chunker/<fixture_id>/` holds:

- `index.html` — a **project-original synthetic** HTML5+MathML document
  that mimics LaTeXML's `ltx_chapter` / `ltx_section` / `ltx_theorem` /
  `ltx_proof` output shape. NOT scraped from any real source (the live
  Stacks Project uses a custom MathJax renderer, not LaTeXML; running
  LaTeXML against its GPL+GFDL TeX source is impractical + license-
  encumbering for a committed fixture). Synthetic content avoids all
  redistribution questions and is stable across LaTeXML version drift.
- `expected.json` — the committed golden output: the JSON-serialized
  `ChunkRecord` list (`[r.to_dict() for r in chunk_textbook(...)]`),
  pretty-printed with `sort_keys=True`.

Current fixtures:

- `two-chapter-book/` — two `ltx_chapter` sections, each with one
  `ltx_section`, a theorem/lemma + paired proof, chapter-intro prose,
  and inline MathML. Exercises: chapter-label extraction, book/chapter/
  section granularity, theorem-pairing inside a chapter, cross-chapter
  pairing termination, the `tv0.1` version stamp.

## When `expected.json` must be regenerated

Regenerate ONLY when a textbook-chunker change is **intentional**:

- a change to `ingest/textbook_chunker.py`'s emission logic,
- a bump of `TEXTBOOK_CHUNKER_VERSION`,
- a change to a reused `ingest/chunker.py` primitive that alters
  textbook output (theorem pairing, section walking, tokenization),
- an edit to a fixture's `index.html`.

If the golden-diff test (`tests/test_textbook_chunker.py::TestGoldenFixture::test_matches_golden`)
fails on an UNINTENTIONAL change, that is the regression guard doing its
job — fix the code, do NOT regenerate.

## How to regenerate

```python
# scratch script — run via: uv run python <script>
import json, shutil, tempfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[?]  # repo root
fixture_id = "two-chapter-book"
slug = fixture_id
paper_id = f"textbook:{fixture_id}"
fx = REPO / "tests/fixtures/textbook_chunker" / fixture_id

with tempfile.TemporaryDirectory() as td:
    base = Path(td) / "notebooks"
    flat = paper_id.replace("/", "_").replace(":", "_")
    dest = base / slug / "parsed" / flat
    dest.mkdir(parents=True)
    shutil.copy(fx / "index.html", dest / "index.html")
    with patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base):
        from ingest.textbook_chunker import chunk_textbook
        records = chunk_textbook(slug, paper_id)
    (fx / "expected.json").write_text(
        json.dumps([r.to_dict() for r in records],
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
```

Then `git diff tests/fixtures/textbook_chunker/` and eyeball the change
before committing — confirm the diff matches the intended behavior change.

## Determinism guarantees

- `ChunkRecord.to_dict()` emits keys in alphabetical order; `expected.json`
  is written with `sort_keys=True` — no dict-ordering drift.
- `TEXTBOOK_CHUNKER_VERSION` is a module-level constant (`"tv0.1"`), never
  computed at runtime — no version drift between runs.
- `_compute_textbook_chunk_id` NFC-normalizes the body before hashing —
  chunk-ids are stable across hosts even if the HTML parser emits NFD.
- No timestamps in the output (BP1 byte-stability discipline).

The only external dependency is the BGE-M3 tokenizer vocab (loaded by the
reused `_count_tokens` primitive for the token-budget check). It is
revision-pinned to `BGE_M3_COMMIT_SHA`; a tokenizer-vocab rotation would
drift `body_tokens`, which is why that SHA is pinned (Threat 6).

## v0 scope reminders (deferred to m8 / e3-v1)

- `chapter` is populated; `page_start`/`page_end` stay `None` (page
  metadata is lost in the m6 markdown→LaTeX→LaTeXML render).
- Preamble is empty (`""`) — m8 adds per-chapter preamble inheritance.
- No definition/exercise chunk levels (e3-v1, after CAND-5 `defines` edge).
- **Identical chapter titles collapse (m7 F2).** `_collect_chapter_titles`
  returns a `set[str]`, so two `ltx_chapter` elements with the SAME title
  text (e.g. two chapters both titled "Introduction" in a multi-part
  volume) map to one entry — chunks from both resolve the same `chapter`
  label. The `chunk_id` stays unique (content-addressable), so this is a
  label-fidelity limit, NOT data loss or an id collision. Disambiguating
  identical titles (by chapter ordinal / element id) is m8 scope. Pinned
  by `test_identical_chapter_titles_collapse_v0_limitation`.

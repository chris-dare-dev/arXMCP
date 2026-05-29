# Critique — notebook-surface-expansion-m6

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** `55832d74a058e7cd2fc36f8d3bccd624514a86ac..be3a37d25c4625a001f54babaf30d7a633969c11`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- The byte-determinism contract holds (independently re-verified: USTAR + manual TarInfo with `mtime=0/uid=0/gid=0/uname=""/gname=""/mode=0o644/REGTYPE` produces byte-identical output across two calls, and the `sorted(rglob, key=relative-posix)` member order is stable on this filesystem). The synthesis D2/D3/D5 disciplines are honored in the diff.
- 0 CRITICAL, 1 HIGH, 3 MEDIUM, 1 LOW. The HIGH is a real exploit-by-existence: the preflight's `_EXPORT_USTAR_NAME_MAX = 255` is **wrong** — USTAR's `name` field is 100 chars, and a 150-char single-segment filename (well under POSIX `NAME_MAX=255`) causes `tarfile.addfile` to raise `ValueError: name is too long` → unhandled 500. Reproduced live: `server/routes/notebooks.py:1500-1513` admits names the format then refuses.
- Highest-risk file:line: `server/routes/notebooks.py:1505` (`_EXPORT_USTAR_NAME_MAX: int = 255` — wrong constant).
- The "narrow-suffix" BodySizeCap exemption (`server/main.py:134`) is broader than the synthesis claims: any path under `/ui/api/notebooks/` ending in `/export` — including multi-segment sub-routes like `/ui/api/notebooks/<slug>/papers/<pid>/export` — bypasses the cap. No such route exists today; MEDIUM as a foot-gun for the next milestone that adds an export-like sub-resource.
- The cross-notebook-leak test (`test_manifest_contains_only_requested_slug_rows`) only seeds `papers` rows for the other notebook, not `<slug>/` asset files, so the load-bearing claim "B's assets do not appear in A's tar" is not actually exercised. The byte-substring assertion `b"beta-nb" not in body` passes trivially because no `beta-nb/...` member was ever written.
- The slug-level symlink case (`<base>/<slug>` IS itself a symlink → `notebook_dir(slug)` raises NotebookError → 422) is handled in the route but UNTESTED — no test plants a symlink at the slug name to exercise the 422 branch.
- The over-long-name and control-char preflight branches at `_iter_safe_export_members` are both completely untested. Combined with the wrong-constant HIGH above, the absence of tests is what let the 100-vs-255 confusion ship.
- Byte-stability gates (`tests/test_server_tool_schema.py`, `tests/test_prompts.py`) green; the diff genuinely touches no MCP surface. Axis-1 + Axis-4 clean. Math fidelity (Axis 2), local-first (Axis 5), tier sequencing (Axis 6), and no-fork (Axis 7) all clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `_EXPORT_USTAR_NAME_MAX = 255` admits names tarfile refuses, → 500

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/routes/notebooks.py:1431` (constant) + `server/routes/notebooks.py:1500-1513` (preflight check) + `server/routes/notebooks.py:1614` (the `tar.addfile` call that raises)
- **What:** The preflight gates member names at 255 UTF-8 bytes, citing "USTAR's 255-byte limit." That conflates POSIX `NAME_MAX` (255 bytes — the filesystem limit, which is what produced the file in the first place) with USTAR's actual header layout: the `name` field is **100 chars**, with a 155-char optional `prefix` field. Python's `tarfile` writes USTAR via `_posix_split_name`, which splits the path at the last slash that fits the prefix. **A 150-char single-segment filename has no slash to split on**, so `tarfile.addfile()` raises `ValueError: name is too long` — propagated as an unhandled 500 to the operator. Reproduced live with a notebook + a single 150-char filename: `ValueError: name is too long` at `tarfile.py:1122` (`_posix_split_name`). The user prompt called this out preemptively and it is real.
- **Why it matters:** (a) Crash-by-existence — any notebook directory containing a single long-named file (PDF, ar5iv HTML with auto-generated long filename, MinerU output with a verbose stem) returns a 500 instead of a partial bundle. The synthesis D5 discipline ("partial bundle is better than 500-ing") is the named invariant being violated. (b) Silently changes the meaning of "valid notebook" — a user can ingest a paper whose ar5iv HTML filename happens to be long, succeed at parse, then fail at export. The failure mode is unrecoverable without manual filesystem surgery. (c) The synthesis (D5) AND the docstring of `_iter_safe_export_members` BOTH state "names exceeding USTAR's 255-byte field" — the synthesis got the size wrong too; the implementer faithfully implemented a wrong number.
- **Proposed fix:** Set `_EXPORT_USTAR_NAME_MAX = 100`. Update the comment + docstring. Add a regression test (see F4) seeding a 150-char filename and asserting `r.status_code == 200` (the file is skipped + WARN logged, not 500). Optional belt-and-braces: wrap the `tar.addfile(...)` site in a `try/except ValueError` that logs + skips, but the preflight fix is the load-bearing change.
- **Regression guard:** new test `test_filename_too_long_for_ustar_is_skipped`: create notebook, plant a single file with a 150-char single-segment name under `<base>/<slug>/`, GET export, assert 200 + tar opens + the long-named file is absent from `tar.getnames()` + a WARN log line matched `"skipping member name over USTAR limit"`.

### F2 — BodySizeCap exemption broader than the "narrow" synthesis claim

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/main.py:134`
- **What:** The exemption is `path.startswith("/ui/api/notebooks/") and path.endswith("/export")`. This is a **path-suffix** check, not a **segment-suffix** check. Verified live: `_is_exempt_path("/ui/api/notebooks/alpha-nb/papers/2401.00001/export")` returns `True`, as does any other sub-route under the notebooks subtree whose last segment is `export`. The synthesis (D1) describes this as "specifically paths matching `path.startswith("/ui/api/notebooks/") AND path.endswith("/export")`" with the framing "single export route, smallest possible widening" — but the rule actually exempts any future `…/export` sub-segment.
- **Why it matters:** Today there's only one such route. Tomorrow, a hypothetical `/ui/api/notebooks/<slug>/papers/<pid>/export` (e.g. per-paper sub-bundle) inherits the cap exemption automatically, silently. The cap is a defense-in-depth invariant — its widening should be explicit, not pattern-matched by suffix coincidence. The synthesis explicitly named "minimum possible widening" as the design rationale; the implementation is broader than that rationale.
- **Proposed fix:** Tighten the check to require `/export` to be the segment immediately following `<slug>`. One option: `path.startswith("/ui/api/notebooks/") and path.count("/") == 5 and path.endswith("/export")` (counts `/ui/api/notebooks/<slug>/export` precisely — 5 slashes from leading `/`). Or split: `parts = path.split("/"); return len(parts) == 6 and parts[1:5] == ["ui","api","notebooks", parts[4]] and parts[5] == "export"`. Either form rejects multi-segment matches.
- **Regression guard:** extend `TestByteCapExemption::test_export_path_is_exempt_but_other_notebook_paths_are_not` with explicit `assert _is_exempt_path("/ui/api/notebooks/alpha-nb/papers/2401.00001/export") is False` and `assert _is_exempt_path("/ui/api/notebooks/alpha-nb/sub/export") is False` rows. The current test does not catch this overreach.

### F3 — `test_manifest_contains_only_requested_slug_rows` is a weak no-leak guard

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_notebook_export.py:178-203`
- **What:** The cross-notebook-leak test creates `alpha-nb` and `beta-nb`, adds one paper to each via REST (writing rows to the SQLite store), then `GET /ui/api/notebooks/alpha-nb/export` and asserts `b"beta-nb" not in body` and `b"2401.00222" not in body`. **No on-disk asset files are seeded under either notebook's `<base>/<slug>/` directory** (verified by reading the test — only `_create_notebook` and `/papers` POST are called, no `_seed_asset`). So the load-bearing claim "B's assets cannot appear in A's tar" is never actually exercised — the tar has only a manifest, never any `<slug>/...` member at all. The byte-substring assertion is trivially true because no member name containing `beta-nb` was ever generated.
- **Why it matters:** The route iterates `nb_path.rglob("*")` rooted at `notebook_dir(slug)`. The actual containment is enforced by `notebook_dir` returning `<base>/<slug>` (already validated by F3 in m6's notebook-ops-hardening series); a regression that, say, used `notebook_dir(slug).parent` would silently include both notebooks' files. This test doesn't catch that class. The implementation IS correct today; the gap is in the regression guard, not the code — but a MEDIUM-strength test masquerading as a load-bearing one is exactly the shape of "test surface drift" the pipeline is supposed to catch.
- **Proposed fix:** Seed at least one on-disk asset under `<base>/beta-nb/some.html` before requesting `alpha-nb/export`. Assert `"beta-nb"` does not appear in `tar.getnames()` (much stronger than the byte-substring check) and `"alpha-nb/..."` member names appear normally. Also assert no member name starts with `beta-nb/`.
- **Regression guard:** the strengthened test itself is the guard.

### F4 — Untested preflight branches: over-long names, control chars, slug-level symlink

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_notebook_export.py` (whole file)
- **What:** The implementation has four preflight checks (`_iter_safe_export_members` at `server/routes/notebooks.py:1485-1521`): (a) under-slug symlink — TESTED; (b) over-long member name — UNTESTED; (c) control-char in name — UNTESTED; (d) `path.resolve()` escapes `nb_dir` — UNTESTED. The slug-level symlink case (`<base>/<slug>` is itself a symlink → `notebook_dir(slug)` raises → 422 at `server/routes/notebooks.py:1582-1587`) is also UNTESTED. Combined with F1's wrong constant, this is exactly the test-gap class that lets a wrong-number-in-a-constant ship.
- **Why it matters:** Preflight code that is never exercised against its skip branches degrades silently — future refactors (e.g. tightening or loosening the limit) have no regression signal. The slug-level symlink branch in particular is a Threat-1 path-traversal guard.
- **Proposed fix:** Add the four missing tests, parametrize where natural:
  1. `test_filename_too_long_for_ustar_is_skipped` (overlaps F1's regression guard).
  2. `test_filename_with_control_char_is_skipped` — plant `<base>/<slug>/has\x01control.html`, assert absent + WARN logged.
  3. `test_slug_dir_symlink_returns_422` — `(base / "evil-nb").symlink_to(tmp_path / "elsewhere")`; assert `GET /ui/api/notebooks/evil-nb/export` → 422 with the `NotebookError` string.
  4. `test_file_resolving_outside_nb_dir_is_skipped` — under-slug symlink whose `path.resolve()` escapes `<base>/<slug>`; assert skipped + WARN logged. (This is what the existing symlink test approximates but the wording is general "skipping symlink", not the specific "path escaping notebook_dir" log line.)
- **Regression guard:** the four new tests above.

### F5 — `parse_status: None` serializes as `null` in the manifest

- **Severity:** LOW
- **Source:** adversary
- **File:** `server/routes/notebooks.py:1448-1450` (`nb_dict = {k: notebook.get(k, "") for k in _EXPORT_NOTEBOOK_ALLOWLIST}`)
- **What:** `_build_export_manifest` uses `notebook.get(k, "")` — that default fires only when the key is **absent**, not when the value is `None`. `NotebooksStore.get_notebook` returns `parse_status: row[5]` which is `None` for any pre-textbook-ingest-m6 arxiv notebook with `parse_status` NULL in SQLite. Result: the manifest carries `"parse_status": null` instead of `"parse_status": ""`. Not a determinism break (same `None` → same `null` every run), not a correctness break (m7 will deserialize `null` consistently), but it leaks an internal SQLite-NULL-vs-empty-string detail into the operator-visible manifest schema.
- **Why it matters:** Defer-class. If m7 ever does `manifest["notebook"]["parse_status"].lower()` it'll AttributeError on the None; one defensive line later in m7 fixes that side. Worth noting because the docstring for `_EXPORT_NOTEBOOK_ALLOWLIST` does not mention nullability.
- **Proposed fix:** `nb_dict = {k: (notebook.get(k) if notebook.get(k) is not None else "") for k in _EXPORT_NOTEBOOK_ALLOWLIST}` (or drop the default entirely if the spec is "absent-or-null → empty string"). Update the `_EXPORT_NOTEBOOK_ALLOWLIST` doc to spell out the null-vs-empty contract.
- **Regression guard:** not required at LOW severity; if fixed, add a one-line assert to `test_export_streams_tar_with_manifest_and_assets` that `manifest["notebook"]["parse_status"]` is a string (never None).

## What was done well

- Synthesis D2 (USTAR + manual TarInfo) is honored field-for-field at `_make_deterministic_tarinfo`: `mtime=0`, `uid=0`, `gid=0`, `uname=""`, `gname=""`, `mode=0o644`, `type=tarfile.REGTYPE`. Independently re-verified to produce byte-identical streams across two runs in isolation.
- Synthesis D3 (manifest allowlist) is correct: `lancedb_path`, `parsed_html_path`, `parse_error` all OMITTED — the m4 D3 info-leak class is genuinely contained. `papers` sorted by `paper_id` independent of `list_papers`'s `added_at DESC` ordering — the right call for cross-export stability.
- The `_iter_safe_export_members` sort key is `str(path.relative_to(nb_path))` (not `path.name`, not `id(path)`) — stable across runs on the same notebook + filesystem.
- Slug-level symlink rejection is delegated to the existing `notebook_dir()` helper (which already raises NotebookError per the m6-ops-hardening F3 fix) — no duplication of the symlink guard.
- The `if nb_dir.is_dir():` guard around the asset walk correctly handles "notebook registered but never uploaded to" — returns a manifest-only bundle, not a 500. Tested.
- `validate_slug → 422` AND `get_notebook → 404` both fire BEFORE any filesystem read — defense ordering correct.
- Manifest JSON is built with `sort_keys=True, separators=(",", ":"), ensure_ascii=True` — three independent determinism levers, all activated.
- The `Content-Disposition: attachment; filename="<slug>.tar"` header is safe because `validate_slug` already constrains slug to `[a-z][a-z0-9-]{2,30}` — no quoting / RFC 6266 escape needed (no metacharacters possible).
- The `_BYTE_CAP_EXEMPT_PREFIXES` was NOT widened to include the whole `/ui/api/notebooks/` subtree — the narrow-vs-broad design choice (synthesis D1 over brief-2's recommendation) is correctly reflected in the diff. The intent is right even if F2 catches that the implementation is slightly broader than the framing.
- `ruff check .` clean; the 50 gate-relevant tests pass; the milestone touches NO MCP surface (`tools.py`, `EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_BP1_SHA256`) — byte-stability gates green.
- Three-commit pattern not yet visible (this is the `feat(...)` commit only; `rect(...)` will follow from this critique). Implementation summary clearly enumerates AC1–AC3 and deviation from brief.

## Recommended rectification order

1. **F1 (HIGH, ~3 LOC + 1 test)** — fix the constant to `100`, add the regression test. Highest leverage: closes the only reachable-on-common-path crash.
2. **F4 (MEDIUM, ~30 LOC of tests)** — close the four untested preflight branches (test 1 overlaps F1; tests 2/3/4 add ~25 LOC). Cheap, tightens the test surface that let F1 ship.
3. **F2 (MEDIUM, ~5 LOC of code + ~3 LOC of test)** — tighten the cap-exemption check to a strict segment-count match. Small, defensible, future-proofs the cap invariant.
4. **F3 (MEDIUM, ~10 LOC of test)** — strengthen the no-cross-notebook-leak test by seeding `beta-nb` on-disk assets. Test-only change.
5. **F5 (LOW)** — defer unless fixed opportunistically alongside F1 (one-line change in `_build_export_manifest`).

## Rectification status (filled by Phase 4)

Adversary SHIP-WITH-FIXES (0C/1H/3M/1L). ALL FIVE findings FIXED. Both HIGH and
the cap-overreach MEDIUM reproduced LIVE before fixing (F1: a 150-char single-
segment filename → ValueError from tar.addfile; F2: `_is_exempt_path(".../papers/
.../export")` returned True). m6 test count 8 → 14 (the existing cross-notebook
test was strengthened to actually seed on-disk assets — F3). ruff clean.

- **F1 (HIGH) — FIXED.** `_EXPORT_USTAR_NAME_MAX` corrected from 255 (POSIX
  NAME_MAX — the filesystem cap that produced the file) to **100** (USTAR's
  actual ``name`` field width). The constant doc now explains the conflation,
  the PAX/GNU tradeoff (which would drift mtime), and the partial-bundle
  discipline. Regression guard: `test_filename_too_long_for_ustar_is_skipped_not_500`
  seeds a 150-char single-segment filename and asserts 200 + the short file is
  in the tar + the long file is absent + a WARN is logged (pre-rect this
  produced a 500 ValueError).
- **F2 (MEDIUM) — FIXED.** `server/main.py::_is_exempt_path` is now segment-EXACT:
  `parts = path.split("/")` and `len(parts) == 6 and parts[5] == "export"` —
  ONLY `/ui/api/notebooks/<slug>/export` matches; a future multi-segment
  sub-route like `.../papers/<pid>/export` does NOT inherit the exemption.
  Regression guard: `test_multi_segment_export_path_not_exempt`.
- **F3 (MEDIUM) — FIXED.** `test_manifest_contains_only_requested_slug_rows`
  now seeds on-disk assets under BOTH notebooks (the original passed vacuously
  because no `<slug>/...` members were generated). New asserts: alpha-nb members
  ARE present + no member name starts with `beta-nb/` + the betas's asset bytes
  are absent from the body. The cross-notebook isolation is now genuinely
  exercised.
- **F4 (MEDIUM) — FIXED.** Added the missing preflight-branch tests:
  `test_filename_too_long_for_ustar_is_skipped_not_500` (overlaps F1),
  `test_filename_with_control_char_is_skipped` (`\x01` in the filename →
  skipped + WARN), `test_slug_level_symlink_returns_422` (the `<base>/<slug>`
  symlink → `notebook_dir` raises NotebookError → 422 branch — a Threat-1
  guard).
- **F5 (LOW) — FIXED (bundled).** `_build_export_manifest` now coerces
  `None → ""` for any allowlisted field (`dict.get(k, "")` returns None when
  the key is present-but-None — affects pre-textbook-ingest-m6 arxiv notebooks
  whose `parse_status` is SQL NULL). Regression guard:
  `test_build_manifest_coerces_none_to_empty` (direct unit test on the helper)
  + `test_null_parse_status_serializes_as_empty_string` (route-level type
  assertion).

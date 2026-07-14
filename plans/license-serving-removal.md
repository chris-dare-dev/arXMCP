# Standalone milestone briefs

Prose briefs the `/milestone-pipeline` command resolves via its legacy
`plans/*.md` fallback (see `.claude/scripts/milestone-pipeline-resolve-brief.py`).
These are deliberately NOT part of any `roadmap/1` thesis — they capture
one-off, corrective, or cross-cutting work that doesn't belong under a single
roadmap's goal. Run one with `/milestone-pipeline <id>` from a session rooted
in this repo.

### license-serving-removal-m1 — Remove license-based response truncation

**Kind:** milestone (standalone / corrective)
**Created:** 2026-07-13
**Supersedes:** `source-truth-e4` / `source-truth-m4` (both retired in
`plans/source-truth/roadmap.yaml` on 2026-07-13).

#### Owner ruling that motivates this

The owner ruled that licensing drives **no** serving decision in arXMCP: the
paper corpus is never redistributed (it lives in the gitignored `var/` data
tree and never leaves the machine, even if the software is open-sourced), so
there is no redistribution-license constraint on what the server surfaces to
its own local agents. Directive, verbatim in intent: *ignore licensing
completely, never truncate, never limit, treat all materials as owned.*

The retired `source-truth-m4` would have done the **opposite** — it would have
retired the blanket `arxiv-license` allowlist entry and repointed serving at
the three-way `license_ref`, activating 300-char truncation on ~76–86% of long
responses. This milestone instead **removes** the existing license-truncation
machinery so the "never truncate on license" invariant holds in code, not by
the accident that every current row happens to carry an allowlisted token.

#### Current behavior to remove (verified 2026-07-13)

- `server/license_policy.py` — the entire module is the license-truncation
  policy: `OA_ALLOWLIST` (exact-string allowlist), `LICENSE_TRUNCATION_CHARS =
  300`, and `is_open_access()` (fail-closed: `None`/`""`/any non-allowlisted
  token ⇒ truncate).
- `server/handlers/chunk.py` (~lines 94–97 + the flag emit ~150–154) —
  `handle_get_chunk` truncates a chunk's sanitized body to 300 chars when
  `not is_open_access(row["license"])`, and emits `truncated_for_license=True`.
  It imports `LICENSE_TRUNCATION_CHARS, is_open_access` from `license_policy`.
- Tests pinning the behavior: `tests/test_license_policy.py`,
  `tests/test_handlers_chunk.py`.
- Docs: `.claude/docs/snippet-contract.md` describes the license-truncation
  path.

This truncation is the **only** license-gated limit on the served surface
(`search_papers` snippet is a fixed 150-char preview independent of license;
`find_equation` / `get_definitions` / `find_lemma_by_name` return no body).

#### Scope

1. `get_chunk` returns the **full sanitized body for every chunk regardless of
   its `license` token** — including `null`, `""`, `copyrighted`,
   `author-distributed`, and any unknown token. No license value ever shortens
   or gates a response.
2. Remove the license-truncation gate from `server/handlers/chunk.py`, remove
   the `truncated_for_license` response field, and drop the now-unused
   `license_policy` import.
3. Retire `server/license_policy.py`'s truncation policy. **First grep every
   importer** of `server.license_policy` (initial scan: `chunk.py` + verify
   `server/tools.py`) and confirm none rely on its truncation before deleting
   the module + its test; if any legitimate non-truncation use exists, reduce
   the module to that instead of deleting.
4. **Keep** the `license` and `license_ref` fields as purely informational
   provenance metadata in the `get_chunk` payload — they drive nothing now, and
   `license_ref` is `source-truth-m5`'s advisory field. Do not remove them;
   that would touch the m5 surface and is out of scope.
5. The size-based safeguards are **unrelated to license and must stay**: the
   256 KB byte-cap and its `resource_link` full-body path, and body
   sanitization/`<retrieved_chunk>` wrapping, are untouched.

#### Acceptance criteria

1. Given a chunk whose `license` token is `null`, `""`, `copyrighted`,
   `author-distributed`, or any token not in the former allowlist, when
   `get_chunk` returns it, then the full sanitized body is returned and the
   response carries no `truncated_for_license` field.
2. Given the served `server/` package after the change, when it is grepped,
   then no license value gates body length or content anywhere (the
   `is_open_access` / 300-char path is gone), while the size-based byte-cap +
   `resource_link` path remains.
3. Given `server.license_policy`, when the change lands, then it is removed (or
   reduced to a non-truncation use with every importer verified), with no code
   path consuming its truncation behavior.
4. Given the `tools/list` surface, when the schema hash is checked, then
   `EXPECTED_TOOL_SCHEMA_SHA256` is **unchanged** — removing a *response* field
   is not a change to tool *meta* (input schema/description). If the critics
   show otherwise, re-pin per the CLAUDE.md §9 tool-add runbook and record why.
5. Given the full suite, when `make test` runs, then it is green (ruff clean +
   pytest), with a **new regression test** asserting full-body serving for a
   non-OA/unknown/`null` license token, and the obsolete license-truncation
   assertions removed.
6. Given `.claude/docs/snippet-contract.md`, when the change lands, then its
   license-truncation description is removed/corrected to reflect that
   `get_chunk` never truncates on license.

#### Out of scope

- The retired `source-truth-e4` / `source-truth-m4` cutover work (do not
  resurrect the `license_ref` three-way *serving* gate).
- The `license` / `license_ref` metadata fields (kept; informational only).
- Any ingest-side change to how license tokens are recorded.
- The 256 KB byte-cap / `resource_link` size path (size-based, not license).

#### Notes for the implementer

- Single-user, single-workstation repo: lands on `main` via the 4-phase
  pipeline (CLAUDE.md §4.2); expect the `feat` + `rect` + `chore` commit
  triple. Run the always-on `milestone-adversary-critic` plus the repo overlay
  critics (`milestone-arxmcp-critic`, `milestone-infra-safety-critic`).
- Blast radius is ~5 files; well under the delegated-path threshold, but the
  served trust boundary means the critics should confirm no other full-body
  leakage surface was relying on the license gate.

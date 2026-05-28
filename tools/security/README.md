# tools/security/ — vendored security helpers

This package holds **fresh implementations of well-known public-domain
security tools**, written in arXMCP's style rather than copied from
upstream sources. The no-fork policy from
[CLAUDE.md §4.7](../../CLAUDE.md) forbids importing or vendoring
external project source trees; algorithms are borrowed and the code
is written fresh in this repo.

This subdir lands with **textbook-ingest-m4** (pdf-ingest-2026
CAND-2) as the first vendoring example. Future security helpers
follow the same pattern.

---

## Discipline

When adding a new helper:

1. **Cite the algorithm + license in the module docstring.** The
   docstring names the upstream tool, its license (public domain,
   MIT, BSD-3-Clause are fine; AGPL needs explicit operator OK), and
   what part of the algorithm is borrowed. No copyright notice is
   transferred because the source is not copied.

2. **Re-implement, don't copy.** Read the upstream source for
   understanding, then close it and write a fresh implementation
   that matches arXMCP's style (PEP-8, no `assert` for invariants,
   `if … raise` patterns, frozensets / regexes as module-level
   constants).

3. **No new runtime dependencies.** Helpers under
   `tools/security/` must use only the Python standard library + the
   project's existing pinned dependencies. Adding a new dep is a
   roadmap decision, not a security-helper decision.

4. **Document the limitations.** Every security helper has known
   evasion cases (e.g. compressed-stream JS, hex-encoded tokens for
   `pdfid`). The docstring names them explicitly and identifies the
   downstream defense layer that backstops the evasion.

5. **Test against publicly-documented vectors.** The unit tests
   under `tests/test_pdfid.py` (and analogues for future helpers)
   include synthetic byte-payloads for each detection rule. Don't
   rely solely on positive cases — write the negative cases too.

---

## Current contents

| Module | Purpose | Algorithm credit |
|---|---|---|
| `pdfid.py` | Detect dangerous PDF name tokens (`/JS`, `/JavaScript`, `/OpenAction`, `/AA`, `/Launch`, `/SubmitForm`, `/ImportData`) | [Didier Stevens, `pdfid.py`](https://github.com/DidierStevens/DidierStevensSuite/blob/master/pdfid.py) — public domain. Algorithm: string-grep over PDF byte stream for the 7 dangerous name tokens. NOT a copy. |

---

## Pattern: defense-in-depth

These helpers are **first-defense-layer** checks at the upload
boundary. They are NOT meant to be the only defense. Each helper
documents its limitations and the downstream layer that catches the
evasion case.

For `pdfid.py` specifically:

- **Layer 1 (this module):** byte-grep over plain-text PDF object
  syntax. Rejects PDFs with obvious dangerous tokens.
- **Layer 2 (textbook-ingest-m5 sandbox):** MinerU subprocess runs
  with `RLIMIT_AS` + process-group kill + 30-min wall timeout. Even
  if a malicious PDF slips past Layer 1, its execution is bounded.
- **Layer 3 (per-notebook blast radius):** all textbook ingest
  artifacts live under `var/arxmcp/notebooks/<slug>/`; an exploited
  parser cannot reach the shared arXiv corpus or other notebooks
  (validated by `tests/test_textbook_notebook_isolation.py`).

The three layers are designed independently; each can fail without
the others necessarily failing.

---

## Cross-references

- [`.claude/docs/security-pdf-sandbox.md`](../../.claude/docs/security-pdf-sandbox.md) — full
  threat surface analysis + sandbox profile for textbook-ingest-e2.
- [`.claude/docs/security-cdm-sandbox.md`](../../.claude/docs/security-cdm-sandbox.md) — peer
  pattern for `pdflatex` + `pdftoppm` subprocess discipline.
- [`.claude/notes/08-security-observability-ops.md`](../../.claude/notes/08-security-observability-ops.md) — Threats 1–7
  (the project's threat-model spec).
- [CLAUDE.md §4.7](../../CLAUDE.md) — the no-fork policy.

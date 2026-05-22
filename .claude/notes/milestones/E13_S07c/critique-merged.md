# Critique — E13_S07c

**Critic:** adversary
**Generated:** 2026-05-22T00:00:00Z
**Commit range:** `52951ad2775ccf4b2da855ce2ad4027766fe5278..d66209f9956d1a828153b3faca447ffd1a6749da`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The factory + Config validator + vendored ISRG Root X1 PEM are correct, secure-by-default, and fail-closed at startup. The TLS-disable contract is preserved; banned patterns are absent; BP1 prompt-cache discipline is untouched.
- 0 CRITICAL, 2 HIGH, 3 MEDIUM, 2 LOW.
- Highest risk: **`ssl_context` parameter is threaded into the function signatures but NOT into any of the four existing callers** (`ingest/bulk_ingest.py:211`, `tools/notebook_fetch.py:89`, `tools/fetch_seed.py:115`, `tools/fetch_one_paper.py:40`). The operator opts in, sees the startup INFO log, and is told the pin is active — but every production ingest path silently uses the system trust store today.
- Doc-staleness: `.claude/docs/security-threat-model-coverage.md:308–313` contains six lines of pre-E13_S07c text (`"forward-compat plumbing stub today (the Config field exists but no code consumes it). Implement the SSL-context wiring..."`) that directly contradicts the "closed by E13_S07c" assertion on line 303.
- AC table claims the startup INFO log is covered ✅ but there is no `test_startup_log_emitted` test; the assertion is unverified.
- Config validator's existence-only `.is_file()` check accepts a non-PEM file (e.g. `/etc/passwd`); `ssl.create_default_context(cafile=...)` would fail at fetch time rather than load time. A defense-in-depth PEM-parse in the validator would close the gap.
- Caller scope-restriction discipline is consistent: `ingest/oai_delta.py` (oaipmh.arxiv.org) is left unthreaded, matching the documented Threat 7 scope of "arxiv.org + ar5iv.labs.arxiv.org" verbatim — but `oaipmh.arxiv.org` IS an arxiv-rooted host; the exclusion deserves an explicit rationale in the audit doc.
- Tests + lint clean per implementation summary (58 of relevant suites green; ruff clean).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — `ssl_context` plumbed but no production caller threads it

- **Severity:** HIGH
- **Source:** adversary
- **File:** `ingest/bulk_ingest.py:211`, `tools/notebook_fetch.py:89`, `tools/fetch_seed.py:115`, `tools/fetch_one_paper.py:40`
- **What:** `try_cache` and `fetch_eprint` now accept `ssl_context: ssl.SSLContext | None = None`, but every existing caller invokes them WITHOUT passing the context. `bulk_ingest.py:211` (`make ingest` pipeline), `notebook_fetch.py:89`, `fetch_seed.py:115` (seed-corpus loader), and `fetch_one_paper.py:40` (single-paper smoke test) all rely on the default `None` → system trust store. Setting `ARXMCP_PIN_ARXIV_CA=1` thus produces a **startup INFO log claiming the pin is active while leaving every actual ingest path on the system trust store**.
- **Why it matters:** This is the central operator-trust failure mode of a CA pin. Threat 7's whole rationale is that the system trust store is the threat (rogue CA, malicious system update); the pin defends against it by replacing the trust anchor. With this partial wiring, the documented "opt-in" behavior is silently a no-op for the bulk-ingest path. The implementation summary acknowledges this (item 3 — "the existing callers were NOT updated"; "a future operator … would NOT see the pin applied unless those scripts are updated") but defers the wiring to "a future milestone." For a milestone whose stated AC reads "`pin_arxiv_ca=True` causes both fetch sites to use the pinned SSLContext" (implementation-summary.md:76), this is a load-bearing gap on the common operator path.
- **Proposed fix:** Thread `ssl_context = build_arxiv_ssl_context(<config>)` through the four callers. For `bulk_ingest.py` and `notebook_fetch.py`, the call sites already have config access (or trivial access via `Config()`). For `fetch_seed.py` / `fetch_one_paper.py`, build the context from a fresh `Config()` at entry. Acceptable alternative: file a follow-up issue, and CLEARLY mark the operator-facing behavior in the audit doc — i.e. "today the flag affects only direct callers of `try_cache`/`fetch_eprint` that explicitly pass `ssl_context`; the bulk-ingest path is wired in a follow-up." The current audit doc claims the flag covers "the two arxiv-rooted fetch sites" without that operator caveat.
- **Regression guard:** Add `test_bulk_ingest_passes_ssl_context_when_flag_on` and `test_fetch_seed_passes_ssl_context_when_flag_on` (mock `try_cache`/`fetch_eprint`, assert the `ssl_context` kwarg is forwarded as a non-None SSLContext when `ARXMCP_PIN_ARXIV_CA=1`).

### F2 — Coverage doc contains stale pre-E13_S07c text contradicting the new "closed" claim

- **Severity:** HIGH
- **Source:** adversary
- **File:** `.claude/docs/security-threat-model-coverage.md:308-313`
- **What:** Lines 308–313 still say:

  > `ARXMCP_PIN_ARXIV_CA` is a forward-compat plumbing stub today (the Config field exists but no code consumes it). Implement the SSL-context wiring against a pinned CA bundle and an operator-refresh procedure when the arxiv.org CA rotation cadence is settled. Low priority because the system trust store + safe-by-default urllib is the production posture today.

  This is leftover text from the pre-E13_S07c version of the doc; the new diff only added the strikethrough-closed bullet on line 303 but did NOT delete the legacy explanatory paragraph. The result is a direct in-doc contradiction: line 303 says "**closed by E13_S07c**" with details, lines 308–313 say "forward-compat plumbing stub today … no code consumes it."
- **Why it matters:** This is the authoritative cumulative threat-model coverage doc — the document a future auditor reads to understand the security posture. The contradiction will confuse anyone who walks the doc top-to-bottom. The staleness gate (`test_threat_model_coverage.py`) is structural-only and will not catch this drift. It also indirectly weakens F1's audit trail: if a reader believes the "no code consumes it" prose, they may not investigate whether callers are wired.
- **Proposed fix:** Delete lines 308–313 (the entire trailing paragraph describing the deferred state), leaving only the strikethrough closed-bullet at lines 303–307. The closed-bullet already names all the wired components.
- **Regression guard:** Add a `test_threat_7_gap_closure_text_consistent` in `tests/security/test_threat_model_coverage.py` that asserts the substring `"forward-compat plumbing stub today"` does NOT appear in the doc once the gap is marked closed (or, more robustly, that closed-issue bullets are not followed by a paragraph in the same `- ` block describing the unclosed state).

### F3 — No test asserts the startup INFO log fires

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/security/test_source_ingest.py` (missing test); `server/main.py:699-707` (code under test)
- **What:** The implementation-summary AC table (`implementation-summary.md:78`) claims "Startup INFO log documenting the opt-in ✅" but the new `TestPinArxivCaWiring` class has six tests covering the factory + validator + threading, none of which assert the log line in `server/main.py:701–706` is emitted. Manual grep confirms no other test verifies this behavior.
- **Why it matters:** The startup log is the operator-visible signal that the pin is active (the audit doc literally quotes the expected log format at lines 248–254 of `security-threat-7-audit.md`). A future refactor that drops the log block (e.g. someone moves the pin into `create_app` and forgets the print) would silently regress operator visibility — and given F1, the operator's only signal that the flag was acted upon would be gone too.
- **Proposed fix:** Add `test_startup_log_fires_when_pin_enabled` using `caplog` and either (a) refactor the log block into a helper called from both `__main__` and `create_app`, or (b) parse-time test the `server.main` module by invoking the log-emitting helper with a stub Config.
- **Regression guard:** As above — `caplog.set_level("INFO")`; invoke the helper; assert `"ARXMCP_PIN_ARXIV_CA=1 set"` appears in `caplog.text`.

### F4 — Validator accepts existing-but-non-PEM file; failure deferred to fetch time

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/config.py:447`
- **What:** `validate_arxiv_ca_bundle` only calls `resolved.is_file()`. If the operator sets `ARXMCP_ARXIV_CA_BUNDLE_PATH=/etc/passwd` (or any other existing non-PEM file), Config-load passes. The failure surfaces at first fetch as an `ssl.SSLError` from `ssl.create_default_context(cafile=...)` inside `build_arxiv_ssl_context` — but only if the bundle is consumed by an updated caller, and only at fetch time, not startup.
- **Why it matters:** The validator's documented intent is "the exception fires at Config-load time (before uvicorn binds, before any fetch is attempted) so an operator sees the misconfiguration immediately." Existence-only check breaks that contract for the "valid path, invalid contents" case. The defense-in-depth claim in `ssl_pin.py:84` ("if you are seeing this at fetch time, the bundle was deleted post-Config-load") is now also wrong — fetch-time failure can occur even for paths that were never PEM-shaped.
- **Proposed fix:** In `validate_arxiv_ca_bundle`, after `resolved.is_file()` check, call `ssl.create_default_context(cafile=str(resolved))` and convert any raised exception into a `ValueError` with the remediation message. This is the same one-liner that runs at fetch time anyway; running it at startup converts a fetch-time corner-case into a startup-time fail-closed.
- **Regression guard:** Add `test_validator_rejects_non_pem_file_at_load_time` — write a non-PEM file (`tmp_path / "not-a-cert.pem"`) with arbitrary text, set the env vars, assert `ValidationError` at `Config()` construction.

### F5 — `oaipmh.arxiv.org` is left unpinned with no in-doc rationale

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/docs/security-threat-7-audit.md:115-117`, `ingest/oai_delta.py:336`
- **What:** The audit doc states the pin applies to "arxiv.org, ar5iv.labs.arxiv.org, and export.arxiv.org" — the three sites the Makefile target verifies. It explicitly excludes `api.openalex.org`, `inspirehep.net`, and `oaipmh.arxiv.org` (line 117). The first two are NOT arxiv-rooted; that exclusion is obvious. But `oaipmh.arxiv.org` IS an arxiv-rooted host — it appears under the `*.arxiv.org` umbrella exactly as `ar5iv.labs.arxiv.org` does. The doc gives no rationale for excluding it (the implementation-summary mentions "a separate subdomain that may or may not chain to the same root" but that uncertainty is not surfaced in the operator-facing audit doc).
- **Why it matters:** Threat 7's verbatim threat statement reads "We fetch from arxiv.org and ar5iv.labs.arxiv.org. If either is compromised, we ingest poisoned content." `oaipmh.arxiv.org` is the OAI-PMH delta-update fetch site — it pulls metadata for ALL incremental ingest. If the operator sets `ARXMCP_PIN_ARXIV_CA=1` believing they have hardened all arxiv-rooted fetches, the delta path silently uses the system trust store. An operator reading the threat statement and the audit doc cannot easily reason about this.
- **Proposed fix:** Either (a) extend the Makefile verification + bundle-doc to include `oaipmh.arxiv.org` and thread the context through `oai_delta.py::_fetch_endpoint` (preferred — single-line plumbing once F1 is in motion), or (b) add an explicit paragraph to `security-threat-7-audit.md` documenting why `oaipmh.arxiv.org` is out of scope (e.g. "Cornell-side load balancer with a separate cert chain; defer to E14"). The current "scope: arxiv.org + ar5iv.labs.arxiv.org ONLY" reads as if `oaipmh.arxiv.org` doesn't exist as an arxiv-rooted host.
- **Regression guard:** If (a) is taken: add `test_oai_delta_threads_ssl_context_to_urlopen` mirroring the existing two `test_*_threads_ssl_context_to_urlopen` tests. If (b) is taken: add an audit-doc text gate asserting the phrase `"oaipmh.arxiv.org"` appears with a documented out-of-scope rationale.

### F6 — `test_factory_builds_secure_context_when_flag_on` does not assert the system trust store was NOT additionally loaded

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/security/test_source_ingest.py:651-687`
- **What:** The test asserts `len(certs) == 1` and `cn == "ISRG Root X1"`, which is correct for `ssl.create_default_context(cafile=<vendored>)`'s observable surface — that function replaces, not augments, the trust store. But the assertion is implicit in the `cafile=...` semantics; if a future refactor switches to `load_verify_locations(cafile=...)` on a context that started with `set_default_verify_paths()`, the test still passes (the CN check is satisfied by ISRG being PRESENT, not by it being SOLE). The full Threat 7 contract is "pinned bundle is the ONLY trust anchor" (per `ssl_pin.py:101–103`).
- **Why it matters:** Low impact because `ssl.create_default_context(cafile=...)` is documented to be replacement, not additive; the refactor risk is small. But the comment in `ssl_pin.py` is explicit ("The CA store is replaced (not augmented)") and the test should pin that semantic strongly.
- **Proposed fix:** Strengthen the assertion: instead of `len(certs) == 1`, assert the cert list does NOT contain any CN matching common system roots (`"DigiCert"`, `"Amazon"`, `"GlobalSign"`, etc.). Or call `ctx.get_ca_certs(binary_form=False)` and check the cert count is exactly 1.
- **Regression guard:** Already covered by the proposed fix.

### F7 — `Makefile refresh-arxiv-ca` does not verify the downloaded PEM matches a known fingerprint

- **Severity:** LOW
- **Source:** adversary
- **File:** `Makefile:267-281`
- **What:** The target downloads `https://letsencrypt.org/certs/isrgrootx1.pem` then verifies it accepts the live cert chains of three hosts. This is a strong functional check — but if `letsencrypt.org` itself were ever compromised AND that compromise also affected one of the live arxiv hosts, the target would accept a forged bundle. The Makefile has no SHA-256 pin on the expected ISRG Root X1 fingerprint as a sanity check.
- **Why it matters:** Low because this attack chain is exotic (compromise of letsencrypt.org root-distribution endpoint plus collusion with arxiv operators). But the operator-runbook documents the target as the authoritative bundle-refresh procedure, and a one-line `openssl x509 -fingerprint -sha256 -in $$tmp -noout | grep -q "<expected_fingerprint>"` would defend against the corner case for free.
- **Proposed fix:** Add a fingerprint check after the download: `openssl x509 -fingerprint -sha256 -in $$tmp -noout` and grep for ISRG Root X1's known SHA-256 (`96:BC:EC:06:26:49:76:F3:74:60:77:9A:CF:28:C5:A7:CF:E8:A3:C0:AA:E1:1A:8F:FC:EE:05:C0:BD:DF:08:C6`). Refuse to overwrite if it doesn't match.
- **Regression guard:** Not a code regression — a Makefile shellcheck-style test could assert the fingerprint constant is referenced in the target.

## Findings (infra-safety)

### IS1 — Temp file not removed if `mv` fails at Makefile:282

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** Makefile:282
- **What:** After all three `openssl s_client` verifications pass, `mv $$tmp infra/ca/arxiv-ca-bundle.pem` is executed with no `|| { rm -f $$tmp; ... exit 1; }` guard. If `mv` fails (e.g., target directory permissions error), `$$tmp` is left as an orphaned temp file in `/tmp` and the operator receives no clear error that the bundle was NOT updated.
- **Why it matters:** The operator sees a successful-looking final `echo "OK: bundle refreshed..."` only if the `mv` succeeds (because the `echo` is chained after `mv` with `;`). However, if `mv` returns non-zero and the recipe line itself exits non-zero, Make will print an error — but `$$tmp` is never cleaned up, leaking a private temporary file containing the CA PEM in `/tmp` until OS cleanup. On a shared machine (low probability for this single-user project) this is an information leak; universally it's a resource leak.
- **Proposed fix:** Append an error handler to the `mv` line:
  ```
  mv $$tmp infra/ca/arxiv-ca-bundle.pem || { rm -f $$tmp; echo "ERROR: mv failed; bundle NOT updated" >&2; exit 1; }; \
  ```
- **Regression guard:** Manually test with `mv` failing (e.g., make `infra/ca/` read-only) and verify `$$tmp` is removed and the recipe exits non-zero.

### IS2 — Help line spacing inconsistent with other entries (LOW)

- **Severity:** LOW
- **Source:** infra-safety
- **File:** Makefile:22
- **What:** The new help entry `make refresh-arxiv-ca   Re-download...` uses three spaces between the target name and the description text. All other entries use consistent two-space or tab-aligned formatting (e.g., `make sbom        Generate...` uses 8 spaces to align descriptions). The `refresh-arxiv-ca` entry is noticeably shorter in padding than its neighbors.
- **Why it matters:** `make help` output readability; cosmetic only.
- **Proposed fix:** Align the description column consistently with other entries, e.g., `@echo "  make refresh-arxiv-ca    Re-download infra/ca/arxiv-ca-bundle.pem..."`.

### IS3 — PEM header comment uses `→` (Unicode arrow) — encoding assumption (LOW)

- **Severity:** LOW
- **Source:** infra-safety
- **File:** infra/ca/arxiv-ca-bundle.pem:4
- **What:** The header comment `# Valid:     2015-06-04 → 2035-06-04` uses a Unicode arrow character (U+2192). This is not an ASCII file despite the PEM body being pure ASCII/Base64.
- **Why it matters:** PEM files are conventionally 7-bit ASCII. Any tool that reads the comment block with strict ASCII parsing will fail on the arrow. The PEM _body_ is parsed correctly by all standard TLS libraries since they begin parsing at `-----BEGIN CERTIFICATE-----`; the comment is ignored. Risk is negligible in practice but worth noting for tooling compatibility.
- **Proposed fix:** Replace `→` with `to` or `-`: `# Valid:     2015-06-04 to 2035-06-04`.

## What was done well (infra-safety)

- **Write-only-after-verification invariant is rock-solid.** The target downloads to a temp file and only calls `mv` _after_ all three `openssl s_client -verify_return_error` checks pass. Every verification step has an explicit `|| { rm -f $$tmp; echo "ERROR..."; exit 1; }` guard that cleans up on failure. The critical path — never overwriting `infra/ca/arxiv-ca-bundle.pem` with an unverified bundle — is correctly implemented (Makefile:275-281).
- **No `sudo` anywhere in the new target.** The `command -v` checks, `curl`, `openssl`, and `mv` all run as the invoking user. Compliant with Makefile discipline axis.
- **Tool presence is checked before use.** Both `curl` and `openssl` are verified with `command -v ... || { echo "ERROR:..."; exit 1; }` before the recipe body begins (Makefile:270-271). The error messages include the tool name and write to stderr.
- **`mkdir -p infra/ca`** at Makefile:272 makes the target idempotent with respect to directory creation; a fresh clone where `infra/ca/` does not exist will not fail mid-recipe.
- **`make test` target is fully intact.** The `test` target at Makefile:54-59 still invokes `ruff check .` then `pytest`, unmodified by this diff. No regression.
- **`make ingest` stub is fully preserved.** The ingest target at Makefile:92-108 remains the E11 stub; it was not touched by this diff. The banned-pattern guard (`make ingest` stub replaced) is clean.
- **PEM file is well-formed.** `infra/ca/arxiv-ca-bundle.pem` has the canonical `-----BEGIN CERTIFICATE-----` / `-----END CERTIFICATE-----` delimiters at lines 13 and 43. The header comment documents source URL, fetch date, validity window, purpose, and the refresh procedure.
- **PEM body is the correct ISRG Root X1 certificate.** The base64 content begins with `MIIFazCCA1Og` and the serial number `IRAIIQz7DSQ` matches the well-known ISRG Root X1 DER encoding distributed by letsencrypt.org.
- **The `refresh-arxiv-ca` target is in the `.PHONY` list** (Makefile:1), preventing Make from treating a file named `refresh-arxiv-ca` as the target's output and silently skipping the recipe.
- **No secrets in the Makefile or PEM file.** No hardcoded credentials, API keys, or tokens were introduced in either file.

## What was done well

- The factory uses `ssl.create_default_context(cafile=...)` exclusively, preserving `check_hostname=True` and `verify_mode=CERT_REQUIRED` without any custom mutation of the context — the safest possible implementation.
- The Config validator's error message is exemplary: it names the path, the source ("vendored bundle" vs "ARXMCP_ARXIV_CA_BUNDLE_PATH"), the remediation (`make refresh-arxiv-ca`), the alternative env var, the AND the disable path. An operator who hits this in the wild has every piece of context they need.
- Two-layer fail-closed design (Config-load validator + factory runtime raise) cleanly separates startup-time and post-load-deletion concerns. The factory's runtime raise correctly uses `raise RuntimeError`, not `assert` (CLAUDE.md §4.7 compliance).
- The vendored PEM is non-secret material with a clear comment block documenting Subject, Issuer, validity window, source URL, fetch date, purpose, and refresh procedure. Self-auditable.
- The Makefile target's refusal to overwrite if ANY of three hosts fails verification is correctly fail-closed; the long inline shell comment explains cadence, refresh triggers, and the no-bypass rule. Useful operator runbook material.
- No banned patterns introduced. The implementation summary explicitly calls out the lesson learned about not citing banned-pattern literals in docstrings (item 5) — this is the kind of self-correction discipline that prevents repeat mistakes.
- `EXPECTED_TOOL_SCHEMA_SHA256` and `ALL_TOOLS` are untouched — BP1 prompt-cache discipline preserved.
- Scope-restriction discipline: the implementer correctly identified that this is a Config-driven feature and added the override field as a declared `Config` attribute (not a sidecar env var) to keep `extra="forbid"` intact.
- New file `server/ssl_pin.py` is small, single-responsibility, and uses `TYPE_CHECKING` to avoid circular imports — clean module-boundary discipline.
- Test names + docstrings are precise. Each test in `TestPinArxivCaWiring` clearly states which contract it pins and references the rectification context.

## Recommended rectification order

1. **F2** (doc-staleness contradiction) — 6-line delete; closes the audit-doc credibility gap before any operator reads it.
2. **F1** (caller threading) — thread `ssl_context` through the four callers OR explicitly document the operator-visible scope in the audit doc. If documenting only, the audit-doc edit MUST land in the same commit as F2.
3. **F3** (no startup-log test) — caplog-based test; ~15 LOC. Cheap defense against future regression.
4. **F4** (validator accepts non-PEM existing file) — convert fetch-time fail into load-time fail; one-line addition to validator + one test.
5. **F5** (oaipmh.arxiv.org rationale) — pick one of (a) extend pin to OAI-PMH or (b) document the exclusion. (a) is the higher-coverage choice if F1 is being addressed anyway.
6. **F6, F7** — defer to follow-up issue unless cheap to ship. Both are LOW-severity defense-in-depth refinements.

## Rectification status

- **F1 (HIGH) — FIXED via documented partial coverage (adversary's accepted alternative).**
  Threading ssl_context through the 4 existing callers (bulk_ingest, fetch_seed,
  fetch_one_paper, notebook_fetch) would cross a layer boundary
  (ingest -> server.config + server.ssl_pin) — a design decision that
  warrants its own review rather than silent introduction in a security
  milestone. Phase 4 chose the adversary's documented "acceptable
  alternative": (a) the audit doc now has a "Caller-side coverage"
  section explicitly stating the gap + operator workaround;
  (b) the startup INFO log now emits a paired WARN line when the flag
  is on, naming each unthreaded caller; (c) the coverage-doc closure
  bullet honestly cites the partial state. The full caller-side wiring
  is tracked as future work.
- **F2 (HIGH) — FIXED.** Deleted the stale "forward-compat plumbing stub
  today" paragraph at security-threat-model-coverage.md:308-313.
- **F3 (MEDIUM) — FIXED.** Added test_startup_log_fires_when_pin_enabled
  to TestPinArxivCaWiring; caplog asserts the INFO line emitted by the
  pin-enabled branch.
- **F4 (MEDIUM) — FIXED.** validate_arxiv_ca_bundle now PEM-parses the
  resolved bundle via ssl.create_default_context at config-load time;
  converts SSLError/OSError into ValueError. New test
  test_validator_rejects_non_pem_file_at_load_time pins the contract.
- **F5 (MEDIUM) — FIXED via documentation.** Added a Note paragraph to
  the audit doc explaining why oaipmh.arxiv.org is deliberately excluded
  (separate Cornell endpoint with potentially distinct cert chain; the
  redirect-host pin already provides equivalent assurance against
  cross-host redirects; tracked as future work).
- **IS1 (MEDIUM) — FIXED.** Added "|| { rm -f ; ... exit 1; }"
  guard to the mv line in the refresh-arxiv-ca Makefile target.
- **IS2 (LOW) — FIXED.** Aligned the help-line spacing to match peers.
- **IS3 (LOW) — FIXED.** Replaced the Unicode arrow in the PEM header
  with "to" for strict ASCII compliance.
- **F6 (LOW) — DEFERRED.** Strengthening the trust-anchor sole-CA
  assertion would harden a low-risk refactor surface; ssl.create_default_context(cafile=...) is documented as replacement-not-additive, and the CN check already pins ISRG Root X1.
- **F7 (LOW) — DEFERRED.** Makefile fingerprint pin on the downloaded
  PEM — the three-host live-cert verification chain already provides
  functional equivalent; the attack chain (letsencrypt.org compromise
  + arxiv.org compromise) is exotic.


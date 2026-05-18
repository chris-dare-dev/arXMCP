# Implementation Summary — E13_S05

**One-line summary:** Close Threat 5 — SecFetchSiteMiddleware + ARXMCP_ALLOWED_ORIGINS + ARXMCP_UNSAFE_NETWORK_BIND, with regression coverage for the existing E06_S05 Origin/Host defenses.
**Commit range:** 40576ef..HEAD (pending feat SHA)
**Branch:** main
**Date:** 2026-05-18

## What landed

Closes Threat 5 (Origin spoofing / DNS rebinding / localhost binding) from
`.claude/notes/08-security-observability-ops.md` § Threat 5.

Pre-milestone audit (both researchers verified):
- **Most defenses already shipped in E06_S05.** `OriginValidationMiddleware`,
  `HostValidationMiddleware`, and `reject_non_loopback` (bind-host validator)
  cover ACs 2 / 3 / 4 of the brief. The milestone adds REGRESSION GUARDS
  for these alongside three NEW hardening additions.
- **Three real gaps closed by this milestone:**
  1. `SecFetchSiteMiddleware` — defense-in-depth against browser-mediated
     DNS-rebinding probes.
  2. `ARXMCP_ALLOWED_ORIGINS` env var — operator-configurable extension to
     the hardcoded loopback Origin floor.
  3. `ARXMCP_UNSAFE_NETWORK_BIND` env var — escape hatch for container
     deployments, with startup WARN log.
- **`E07_S09` fictional** (E07 stops at S04) — same drift pattern as prior
  E13 milestones. `E07_S01` IS real but is "Phase 1: BM25" — the brief's
  attribution of E07_S01 as the Origin-pin source is wrong; Origin
  validation shipped in E06_S05.
- **No main `docker-compose.yml`** at v1 (E14 owns it). AC5 reframed to
  "design note documents the binding pattern" — a text-existence assertion
  against `08-security-observability-ops.md`.

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `server/config.py` | +30 LOC: `allowed_origins: list[str]`, `unsafe_network_bind: bool` fields. `@field_validator("bind_host")` → `@model_validator(mode="after")` so the validator can read both fields. Adds `Field` import. | D1 |
| `server/middleware.py` | +75 LOC: NEW `SecFetchSiteMiddleware` (pure-ASGI). Updated `OriginValidationMiddleware.__init__` to accept `allowed_origins` arg + normalize entries (lowercase, strip trailing slash, drop blanks). | D1 |
| `server/main.py` | +20 LOC: mount `SecFetchSiteMiddleware` between `SecurityHeaders` and `Origin` validation; pass `cfg.allowed_origins` into `OriginValidationMiddleware`; emit WARN log at startup when `unsafe_network_bind=True`. | wiring |
| `tests/security/test_origin_binding.py` | NEW, ~370 LOC. 23 tests across 6 test classes: Sec-Fetch-Site enforcement, allowed-origins env var, unsafe-bind escape hatch, Host validation regression, design-note documentation, SecFetchSite ASGI unit tests. | brief AC1–AC6 |
| `.claude/docs/security-threat-5-audit.md` | NEW operator-internal audit doc with per-mitigation status table, DNS-rebinding attack mechanics, Sec-Fetch-Site semantics, middleware mount order. | doc-placement reframe |
| `.claude/docs/security-binding.md` | NEW companion doc with strong warning on `ARXMCP_UNSAFE_NETWORK_BIND`, container-deployment guidance, operational checklist. | brief deliverable |

## Drift from brief (deliberate; same pattern as E13_S01–S04)

1. **Doc placement.** Brief said `docs/security/threat-5-audit.md` and
   `docs/security/binding.md`. CLAUDE.md §1: `docs/` is operator-only.
   Landed at `.claude/docs/security-threat-5-audit.md` and
   `.claude/docs/security-binding.md`.

2. **Fictional prerequisite reframe.** Brief named `E07_S01` and `E07_S09`
   as dependencies. `E07_S01` is real but is the BM25 milestone, NOT
   Origin validation (which shipped in E06_S05). `E07_S09` is fictional
   (E07 stops at S04). Same drift pattern as prior E13 milestones.

3. **AC2 + AC3 + AC4 reframe — already shipped.** Brief presents three
   ACs as new functionality (`public IP in Host → 403`,
   `attacker.localhost → 403`, `0.0.0.0 → refuse to start`). All three
   are already enforced by E06_S05's `HostValidationMiddleware` and
   `reject_non_loopback`. This milestone adds regression guards.

4. **AC5 reframe — no main docker-compose.yml.** The brief tests "docker
   compose `ports:` maps `127.0.0.1:7733:7733`" against infrastructure
   that doesn't ship at v1 (E14 owns the main compose). Reframed to a
   text-existence assertion against the design note (which DOES document
   the pattern). Same approach as E13_S03 D2.

5. **`-32602` AC ergonomics** — N/A here; this milestone returns HTTP
   `403` (forbidden Origin / Sec-Fetch-Site) and `421` (Misdirected
   Request for bad Host), not JSON-RPC errors.

6. **`field_validator` → `model_validator` refactor** for bind-host.
   Required to read both `bind_host` and `unsafe_network_bind` together.
   Existing `tests/test_security.py::TestStartupRejectsBadBind` uses
   subprocess exit codes (not exception types), so the refactor is
   transparent to existing tests. Verified by running the full suite.

7. **`OriginValidationMiddleware` constructor change** — added optional
   `allowed_origins` keyword arg with a default. Existing callers
   (e.g. test fixtures) that construct the middleware without the arg
   continue to work; explicit wiring in `create_app` passes
   `cfg.allowed_origins`.

## Test count delta

* Pre-milestone (post-E13_S04 — 40576ef): 2013 passed, 9 skipped, 1 xfailed.
* Post-feat: 2036 passed (+23 net):
  - 7 in `TestSecFetchSiteRejection` (absent/none/cross-site/same-site/same-origin/empty/garbage)
  - 4 in `TestAllowedOriginsEnvVar` (default empty, normalization, blank filtering, Config default)
  - 5 in `TestUnsafeNetworkBindEscapeHatch` (default-deny, escape hatch, loopback either-way, public-IP, LOOPBACK_HOSTS constant)
  - 4 in `TestHostValidationRegressionForThreat5` (public IP, attacker subdomain, nip.io wildcard, loopback accept)
  - 1 in `TestDesignNoteDocumentsLoopbackBinding` (text-existence AC5)
  - 2 in `TestSecFetchSiteMiddlewareUnit` (non-HTTP scope, truncated value)
* `ruff check .` — clean.

## Acceptance criteria status (reframed from brief)

- [x] **AC1** — `Sec-Fetch-Site` ≠ `none` and not absent → 403. NEW
  `SecFetchSiteMiddleware`.
- [x] **AC2** — Public IP in `Host` → 421 (existing
  `HostValidationMiddleware`). Regression-guarded.
- [x] **AC3** — `Host: attacker.localhost` → 421 (existing). Regression-guarded.
- [x] **AC4** — `ARXMCP_BIND_HOST=0.0.0.0` without
  `ARXMCP_UNSAFE_NETWORK_BIND=1` → `ValidationError` (server refuses to
  start). Existing rejection preserved + new escape hatch added.
- [~] **AC5** — REFRAMED. Main `docker-compose.yml` doesn't exist (E14
  owns it). Design note documents the binding pattern; verified by
  `TestDesignNoteDocumentsLoopbackBinding`.
- [x] **AC6** — `pytest tests/security/test_origin_binding.py` passes all
  23 cases.

## What this milestone does NOT cover

- **Authentication** — explicitly out of v1 scope per brief.
- **mTLS** — Tier-6+ hardening per brief.
- **Full bind regression test suite** — E13_S09 owns
  `tests/security/test_bind_regression.py` as the comprehensive suite.
  E13_S05 ships the audit + the new hardening; E13_S09 adds dedicated
  regression coverage.
- **Reverse-proxy `trusted_proxies` bypass** — documented in
  `.claude/docs/security-binding.md` as deferred future work.
- **Main `docker-compose.yml`** — E14 owns the production compose.

## External writes the orchestrator must authorize

**None — purely local.** Standard Phase 4 user-authorization for
`git push origin main` at end.

## Threat-coverage matrix snapshot

After E13_S05:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Indirect prompt injection | ✅ E13_S02 |
| 3. LaTeXML sandbox hostile input (Phase 1) | ✅ E13_S03 |
| 4. Resource exhaustion | ✅ E13_S04 |
| 5. Origin spoofing / DNS rebinding | ✅ E13_S05 |
| 6. Model SHA pinning / safetensors | ⏳ E13_S06 |
| 7. Source ingestion TLS | ⏳ E13_S07 |
| 8. Log redaction | ⏳ E13_S08 |
| 9. Localhost binding regression test | ⏳ E13_S09 (complements E13_S05) |

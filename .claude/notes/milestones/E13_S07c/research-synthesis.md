# Research Synthesis — E13_S07c

**Milestone:** E13_S07c — Implement `ARXMCP_PIN_ARXIV_CA` SSL-context wiring + refresh procedure
**Mode:** standard (2× researcher, parallel)
**Synthesized:** 2026-05-22 (orchestrator, main session)
**Briefs merged:** research-brief-1.md, research-brief-2.md

## One-line scope

Wire the existing `Config.pin_arxiv_ca: bool = False` forward-compat flag
into a real `ssl.SSLContext` consumer for the two arxiv-org-rooted fetch
sites (`ingest/ar5iv_fetch.py::try_cache`, `tools/arxiv_fetch.py::fetch_eprint`),
backed by a vendored ISRG Root X1 PEM bundle, a Makefile refresh target,
and a startup INFO log. Closes GitHub issue #5 / gap G5.

## Agreed facts (both briefs concur)

1. **SSL API**: `ssl.create_default_context(cafile=str(bundle_path))` is the
   correct form. It preserves `check_hostname=True` and
   `verify_mode=CERT_REQUIRED` (verified against Python 3.11 ssl docs and the
   existing `TestTlsCannotBeDisabled::test_no_insecure_sslcontext_in_production_code`
   walk — `cafile=` does NOT match any banned pattern).
   - `ssl.SSLContext.load_verify_locations(cafile=...)` is equivalent;
     `create_default_context(cafile=)` is more concise.
   - `urllib.request.urlopen(req, timeout=..., context=ctx)` is the
     non-deprecated injection (deprecated alternatives `cafile=`/`capath=`
     on `urlopen` itself are banned by Python 3.6+).

2. **Bundle content — ISRG Root X1.** arxiv.org / ar5iv.labs.arxiv.org chain
   to Let's Encrypt. ISRG Root X1 is valid until 2035-09-30; the chain root
   rotates on multi-year cadence, while Let's Encrypt leaf certs rotate
   every 60–90 days. **Pin the ROOT (X1), not the leaf or intermediate.**
   Bundle source: `https://letsencrypt.org/certs/isrgrootx1.pem` (canonical).

3. **Bundle source — VENDOR at `infra/ca/arxiv-ca-bundle.pem`.** Both briefs
   recommend Option A. arXMCP is single-user / single-workstation per
   `01-mission-and-context.md`; operator-supplied path adds friction with
   no security benefit for the solo-dev case. Bundle is non-secret public
   PEM material; ~2-3 KB; self-auditable via git history.

4. **In-scope fetch sites — ONLY 2**: `ingest/ar5iv_fetch.py::try_cache` and
   `tools/arxiv_fetch.py::fetch_eprint`. **NOT** `graph_ingest.py`,
   `inspire_ingest.py`, `oai_delta.py` — those target different hosts and
   different CAs; out of Threat 7 arxiv-CA-pin scope. Verified by reading
   their fetch URLs: api.openalex.org, inspirehep.net/api, oaipmh.arxiv.org
   (a different subdomain — note: ar5iv-CA pin applies to arxiv.org +
   ar5iv.labs.arxiv.org, NOT to export.arxiv.org or oaipmh.arxiv.org).

5. **Injection mechanism — explicit parameter**. Add
   `ssl_context: ssl.SSLContext | None = None` to both `try_cache` and
   `fetch_eprint`; thread `urlopen(req, timeout=..., context=ssl_context)`.
   No module-level mutable singleton (concurrency hazard; defeats DI).

6. **Fail-closed contract**. `pin_arxiv_ca=True` + missing bundle MUST
   raise `RuntimeError`/`ValueError`, NEVER silently fall back to the system
   trust store. Silent degrade would defeat the entire purpose of the pin.

7. **Startup INFO log location**: `server/main.py` `__main__` block,
   adjacent to the existing `unsafe_network_bind` WARN log (lines ~686-693).
   Same precedent: opt-in flag → log at startup so the operator can see it.

8. **Operator-refresh procedure**: `make refresh-arxiv-ca` Makefile target.
   Discovered via `make help`; uses `openssl s_client` or `curl` to fetch
   the canonical ISRG Root X1 PEM. Verify against a live arxiv.org fetch
   before writing.

9. **Test placement**: extend `tests/security/test_source_ingest.py`
   `TestPinArxivCaFlag` class (3 tests today) with new tests for the
   SSLContext factory + injection-point assertion. Plus a new test for the
   Config validator's fail-closed semantics. Keep the existing 3 tests as
   regression guards.

10. **Banned-pattern compliance**: `ssl.create_default_context(cafile=...)`
    is safe — does NOT trigger any line in `TestNoVerifyFalse`
    (`verify\s*=\s*False`) or `TestTlsCannotBeDisabled`
    (`check_hostname=False`, `verify_mode=ssl.CERT_NONE`,
    `verify_mode=ssl.CERT_OPTIONAL`, `_create_unverified_context`).

11. **No MCP-spec impact**: ingest-layer plumbing only.
    `EXPECTED_TOOL_SCHEMA_SHA256` untouched. BP1 cache discipline
    unaffected. No new MCP tools.

12. **`extra="forbid"` discipline**: `Config` uses
    `SettingsConfigDict(env_prefix="ARXMCP_", extra="forbid")`; any
    operator-supplied env var must be a declared field. If the design uses
    `ARXMCP_ARXIV_CA_BUNDLE_PATH` for override, it MUST be a declared
    Config field.

## Divergences resolved by orchestrator

### D1 — `arxiv_ca_bundle_path` Config field: add it or not?

- **Researcher-1**: explicitly recommends declaring
  `arxiv_ca_bundle_path: Path | None = None` (default None means "use the
  vendored bundle"). Reason: `extra="forbid"` makes any operator override
  impossible without a declared field; even if rarely used, the
  declared-field cost is one line and the safety valve is real.
- **Researcher-2**: does not address this question explicitly; vendor
  recommendation implies hardcoded path.

**Orchestrator decision: ADD the field.** Cost is trivial (one Config
field + one default); benefit is (a) operator-override path exists without
breaking `extra="forbid"`, (b) tests can pass a `tmp_path`-rooted PEM
without monkeypatching a module constant. Default `None` means "use the
vendored bundle at `infra/ca/arxiv-ca-bundle.pem`".

### D2 — fail-closed enforcement location: Config validator vs factory raise?

- **Researcher-1**: Config `model_validator(mode='after')` checks the
  bundle path at startup, mirroring the `bind_host` loopback validator.
  Pro: fails before uvicorn binds.
- **Researcher-2**: Factory (`build_arxiv_ssl_context()`) raises
  `RuntimeError` if bundle missing. Pro: localized to the SSL module.

**Orchestrator decision: BOTH.** They're complementary, not competing.
The Config validator is the primary fail-closed (startup-time, before any
fetch happens); the factory raise is defense-in-depth (catches the case
where the bundle is deleted post-startup, or where a future caller paths
around the validator). Test surface covers both.

### D3 — SSLContext construction timing: import-time vs lifespan vs first-call lazy?

- **Researcher-1**: builds at startup, threaded down explicitly.
- **Researcher-2**: lazy-singleton on first call in `server/ssl_pin.py`.

**Orchestrator decision: build at startup in `server/main.py` lifespan**
when `pin_arxiv_ca=True`. The factory `build_arxiv_ssl_context(bundle_path)`
is pure (no side effects beyond reading the PEM file), called once at
startup, returns an `ssl.SSLContext`. The context is stored on `Resources`
(or passed to the bulk-ingest orchestrator). Callers receive the
already-built context. Build-once-at-startup means:
- Single point of failure (visible in startup logs).
- Validator + factory raise on missing bundle BOTH fire pre-request.
- Thread-safe — `ssl.SSLContext` is safe for concurrent connections.
- Avoids global mutable state in `server/ssl_pin.py`.

## Implementation plan (INLINE — orchestrator, main session)

Size estimate: ~250 LOC (well under delegated-path threshold).

1. **`infra/ca/arxiv-ca-bundle.pem`** (new) — fetch `isrgrootx1.pem` from
   `https://letsencrypt.org/certs/isrgrootx1.pem`. Commit as the vendored
   bundle. Header comment in PEM (optional) noting `ISRG Root X1`,
   `valid until 2035-09-30`, `source: letsencrypt.org`.

2. **`server/ssl_pin.py`** (new, ~50 LOC) — exports:
   - `VENDORED_ARXIV_CA_BUNDLE: Path` — module-level constant for the
     vendored bundle path (`repo_root / "infra" / "ca" / "arxiv-ca-bundle.pem"`).
   - `resolve_arxiv_ca_bundle(config: Config) -> Path` — returns the
     bundle path: `config.arxiv_ca_bundle_path` if set, else the vendored
     constant. Raises `RuntimeError` if the resolved path does not exist.
   - `build_arxiv_ssl_context(config: Config) -> ssl.SSLContext | None` —
     returns `None` if `pin_arxiv_ca=False`; otherwise returns
     `ssl.create_default_context(cafile=str(resolve_arxiv_ca_bundle(config)))`.

3. **`server/config.py`** — add `arxiv_ca_bundle_path: Path | None = None`
   field with docstring. Add `model_validator(mode='after')`:
   if `pin_arxiv_ca=True`, the resolved bundle path (either supplied or
   vendored) must exist; otherwise raise `ValueError` at config-load time.

4. **`server/main.py`** — in `__main__` block, after config validation,
   before `uvicorn.run`: if `cfg.pin_arxiv_ca`, log INFO
   `"ARXMCP_PIN_ARXIV_CA=1 set; using pinned CA bundle at <path> for
   arxiv.org / ar5iv fetches"`. In the lifespan, build the SSLContext
   once via `build_arxiv_ssl_context(cfg)` and store on `Resources` (or
   pass to ingest entrypoints — see step 7).

5. **`ingest/ar5iv_fetch.py::try_cache`** — add
   `ssl_context: ssl.SSLContext | None = None` kwarg; thread to
   `urllib.request.urlopen(request, timeout=timeout_seconds, context=ssl_context)`.

6. **`tools/arxiv_fetch.py::fetch_eprint`** — same parameter + thread.

7. **Caller threading** — the bulk-ingest entrypoints (e.g. `make ingest`
   stub callers, or any code path that calls `try_cache`/`fetch_eprint`)
   must build the SSL context via `build_arxiv_ssl_context(cfg)` at
   startup and pass it down. For E13_S07c scope: instrument the existing
   callers we can find in `tools/fetch_seed.py` / `tools/fetch_one_paper.py`
   / any other call site. New callers added in future milestones must
   thread the context per the docstring contract.

8. **`Makefile`** — add `refresh-arxiv-ca` target. Recommended form (operator
   verifies before commit):
   ```make
   refresh-arxiv-ca:  ## Refresh infra/ca/arxiv-ca-bundle.pem from letsencrypt.org
   	@echo "Fetching ISRG Root X1 from letsencrypt.org..."
   	@curl -fsSL https://letsencrypt.org/certs/isrgrootx1.pem -o infra/ca/arxiv-ca-bundle.pem
   	@echo "Verifying chain against live arxiv.org cert..."
   	@openssl s_client -connect arxiv.org:443 -servername arxiv.org -CAfile infra/ca/arxiv-ca-bundle.pem -verify_return_error </dev/null >/dev/null && echo "OK: live arxiv.org cert verifies against new bundle" || (echo "FAIL: bundle does not verify the live arxiv.org chain — DO NOT COMMIT"; exit 1)
   	@echo "Review the diff and commit: git diff infra/ca/arxiv-ca-bundle.pem"
   ```

9. **`tests/security/test_source_ingest.py`** — extend `TestPinArxivCaFlag`
   with new tests (covering D2 fail-closed at BOTH Config-validator and
   factory layers):
   - `test_ssl_pin_factory_returns_none_when_flag_off` — pin_arxiv_ca=False
     → `build_arxiv_ssl_context()` returns None.
   - `test_ssl_pin_factory_builds_when_flag_on` — pin=True + bundle present
     → returns a real `SSLContext` with `check_hostname=True` and
     `verify_mode=CERT_REQUIRED`.
   - `test_ssl_pin_factory_raises_when_bundle_missing` — pin=True + bundle
     deleted → `RuntimeError` (factory layer).
   - `test_config_validator_rejects_pin_without_bundle` — Config
     construction with pin=True + nonexistent override path → `ValidationError`
     (Config layer).
   - `test_ar5iv_fetch_threads_ssl_context_through_urlopen` — call
     `try_cache(..., ssl_context=ctx)` with patched urlopen; assert
     `urlopen` was called with `context=ctx`.
   - `test_arxiv_fetch_threads_ssl_context_through_urlopen` — same for
     `fetch_eprint`.
   - `test_startup_log_emitted_when_pin_enabled` — caplog assertion on
     the `server/main.py` INFO line.

10. **`.claude/docs/security-threat-7-audit.md`** — rewrite the CA-pinning
    section (lines 104–133): remove "Forward-compatible placeholder. No
    current behavior." Replace with actual behavior: bundle source,
    pin contents (ISRG Root X1), failure modes, refresh procedure (link
    to Makefile target). Rewrite the operator runbook section
    (lines 200–213): replace "no current behavior" disclaimer with the
    real opt-in sequence + startup log line + refresh cadence guidance.

11. **`.claude/docs/security-threat-model-coverage.md`** — Threat 7 summary
    row + Gap-issue triage G5 row: mark closed by E13_S07c (mirror G1/G2
    closure pattern).

12. **`tests/security/test_threat_model_coverage.py`** — should still pass
    (no doc-citation changes; both audit docs are already cited).

## Failure-mode coverage (from research-brief-2)

The 7 failure modes (a)–(g) from researcher-2 are addressed by:
- (a) Flag=True + missing bundle → fail-closed at Config validator AND factory.
- (b) Bundle stale → clear `SSLCertVerificationError` + Makefile refresh target.
- (c) Wrong CA → Makefile target verifies against live arxiv.org cert before commit.
- (d) Bundle unreadable → `OSError` propagates with clear message.
- (e) Flag without bundle path env var (Option B) → eliminated by vendor approach.
- (f) Flag=False but SSLContext built anyway → factory returns None gating the call.
- (g) Pin applied to one site but not both → both regression tests assert the thread.

## Open questions

None. Implementation can proceed on the above plan. Both briefs converged.

## External writes required (deduped union)

| Type | Target | Why | Blocking |
|---|---|---|---|
| `WebFetch` (implementation-time) | `https://letsencrypt.org/certs/isrgrootx1.pem` | Source the vendored CA bundle | NO — read-only fetch by orchestrator during Phase 2 |
| `git push` | `main @ github.com/chris-dare-dev/arXMCP` | Land the feat+rect+chore commits | YES — per-event user authorization |
| `gh issue close` | `chris-dare-dev/arXMCP#5` | Close gap-issue G5 once the wiring lands | YES — Phase-4 gated |

## Orchestrator synthesis note

Strong agreement on all 12 load-bearing facts. Three divergences resolved:
(D1) add `arxiv_ca_bundle_path` Config field for `extra="forbid"`
compliance + test/override flexibility; (D2) fail-closed at BOTH Config
validator AND factory layers (complementary, not competing); (D3) build
SSLContext once at startup in `server/main.py` lifespan, thread to
callers — avoids global mutable state and gives single-point-of-failure
visibility at startup. The vendor-ISRG-Root-X1 decision is unanimous;
this is the operationally-cheapest correct pin for a Let's Encrypt-served
upstream like arxiv.org.

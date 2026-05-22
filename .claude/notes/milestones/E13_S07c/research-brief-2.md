# Research Brief — E13_S07c

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T23:40:00Z

## In-codebase context

### Design constitution — directly applicable notes

**`08-security-observability-ops.md` § Threat 7 (verbatim):**
> "We fetch from arxiv.org and ar5iv.labs.arxiv.org. If either is compromised, we ingest poisoned content.
> **Mitigations:**
> - Verify TLS certs (default for the HTTP client; do not disable).
> - Pin known fingerprint of arxiv.org's certificate authority chain (rotated periodically).
> - Content-length sanity checks (a single paper > 100 MB source is suspicious).
> - Sandbox the parser (Threat 3 mitigation covers downstream impact)."

The CA-pinning mitigation is what this milestone closes.

**`server/config.py` — existing `pin_arxiv_ca` field (verbatim docstring):**
> "E13_S07 (Threat 7) — opt-in CA pinning flag for arxiv.org. Default False: urllib.request uses the system trust store (safe-by-default; TLS verification cannot be disabled by any ARXMCP_* env var).
> **Forward-compatible placeholder. No current behavior.** Setting True is accepted by the config but does NOT yet change the SSL context — the field is plumbing for a future milestone that will validate the arxiv.org certificate chain against a pinned fingerprint. F1 rectification (E13_S07 adversary): the prior docstring claimed an INFO log was emitted on opt-in; no such log exists yet. The actual log line and the SSL-context wiring land together in the closure milestone."

**`07-multi-agent-caching.md` — MCP-surface irrelevance:** This milestone touches only ingest-layer plumbing (`ingest/ar5iv_fetch.py`, `tools/arxiv_fetch.py`), not any MCP tool schema or tool registration. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning. No BP1 cache invalidation risk.

**`06-mcp-server-design.md`** — confirms no MCP spec compliance issues (this is purely ingest-layer, not on the tool surface).

### Existing fetch site anatomy

**`ingest/ar5iv_fetch.py::try_cache`** uses `urllib.request.urlopen(request, timeout=timeout_seconds)` — **no `context=` kwarg is passed**. The urlopen call is inline inside the `with` block. There is no `ssl_context` parameter on the `try_cache` function. This means the function must be refactored to accept an optional `ssl_context` parameter and thread it into urlopen.

**`tools/arxiv_fetch.py::fetch_eprint`** uses `urllib.request.urlopen(request, timeout=timeout)` — same pattern, no `context=` kwarg. The function must also be refactored to accept an optional `ssl_context` parameter.

**Neither fetch site accepts an ssl_context injection point.** Both require a surgical refactor: add an optional `ssl_context: ssl.SSLContext | None = None` parameter, and pass `context=ssl_context` to `urlopen`.

**`08-security-observability-ops.md` § TLS (from audit):** `tests/security/test_source_ingest.py::TestTlsCannotBeDisabled::test_no_insecure_sslcontext_in_production_code` currently walks `ingest/`, `tools/`, `server/` and REFUSES any code with `check_hostname=False`, `verify_mode=ssl.CERT_NONE`, `verify_mode=ssl.CERT_OPTIONAL`, or `_create_unverified_context`. The new SSLContext factory MUST NOT trigger this walk — it must use `ssl.create_default_context(cafile=...)` (which sets `check_hostname=True` and `verify_mode=CERT_REQUIRED` by default, which do NOT match any forbidden pattern).

### Banned-pattern compliance

- **`assert` ban:** The SSLContext factory must use `if ... raise RuntimeError(...)` for invariant checks (e.g., bundle path missing), not `assert`.
- **`BaseHTTPMiddleware` ban:** Not relevant — this is ingest-layer, not middleware.
- **`anthropic` SDK ban:** Not relevant.
- **New `.md` outside `.claude/`:** The audit doc update must remain at `.claude/docs/security-threat-7-audit.md`. The threat-model-coverage doc at `.claude/docs/security-threat-model-coverage.md`. Neither moves to `docs/`.
- **`KMP_DUPLICATE_LIB_OK=TRUE`:** Not touched by this milestone.

### Scope boundary (load-bearing)

The milestone brief and threat model both explicitly restrict CA pinning to arxiv.org and ar5iv.labs.arxiv.org ONLY:
- `ingest/ar5iv_fetch.py` — AR5IV_BASE_URL = "https://ar5iv.labs.arxiv.org/html" — IN SCOPE
- `tools/arxiv_fetch.py` — ARXIV_EPRINT_URL = "https://export.arxiv.org/e-print/{paper_id}" — IN SCOPE
- `ingest/graph_ingest.py` (OpenAlex), `ingest/inspire_ingest.py` (INSPIRE-HEP), `ingest/oai_delta.py` (OAI-PMH) — OUT OF SCOPE

## Prior decisions and lessons

**Git log findings:** E13_S07b (`feat(ingest): redirect-host pin on graph + inspire`) was the most recent security milestone on E13. E13_S07 shipped `pin_arxiv_ca` as a forward-compat stub, and the adversary (F1) explicitly noted no INFO log was emitted — this was documented as a known gap in the audit doc. The adversary critique of E13_S07 produced the rectification note now verbatim in `config.py` and `security-threat-7-audit.md`.

**From `security-threat-7-audit.md` § Known gaps:**
> "- `Config.pin_arxiv_ca: bool = False` (the server/config.py field). When True, the value is accepted by Config but **has no current behavior**. The server today emits no startup INFO log on opt-in; the log line and the SSL-context wiring land together in the closure milestone..."
> "Default False is production-ready: the system trust store + the Content-Length cap already cover Threat 7's primary attack surface."

**From `security-threat-7-audit.md` operator runbook (verbatim):**
> "Enable opt-in CA pinning (forward-compat):
> `export ARXMCP_PIN_ARXIV_CA=1; make up`
> Today this is a forward-compat stub — the flag is accepted by Config but has **no current behavior**..."

**Pattern from E13_S05 (unsafe_network_bind):** The existing pattern for a WARNING log on risky opt-in is in `server/main.py` lifespan (`if cfg.unsafe_network_bind: logger.warning(...)`). The INFO log for `pin_arxiv_ca=True` should follow the same startup-log pattern. This means the log fires in `server/main.py` at startup, not inside a fetch site.

**`TestNoVerifyFalse` regex:** `re.compile(r"\bverify\s*=\s*False\b")` — the production-code walk. The new SSLContext factory does NOT introduce `verify=False`. But note: `_create_unverified_context` is also banned. The factory must use `ssl.create_default_context(cafile=bundle_path)` exclusively.

**`test_no_insecure_sslcontext_in_production_code` walk:** Explicitly bans `check_hostname=False`. The `ssl.create_default_context()` route sets `check_hostname=True` and `verify_mode=CERT_REQUIRED` — fully compliant with the walk.

## External sources

### Python `ssl` stdlib docs (Python 3.11)

**`ssl.create_default_context(purpose=Purpose.SERVER_AUTH, cafile=None, capath=None, cadata=None)`:**
- When `purpose=SERVER_AUTH` (the default for client use): sets `verify_mode=CERT_REQUIRED` and `check_hostname=True`. Uses `PROTOCOL_TLS_CLIENT` under the hood.
- The `cafile` parameter loads a PEM-format CA bundle file directly. Using `cafile=` is equivalent to calling `load_verify_locations(cafile=...)` after construction.
- This is the CORRECT form for CA pinning: `ctx = ssl.create_default_context(cafile="/path/to/bundle.pem")`. It replaces the system trust store with the specified bundle. `check_hostname` and `verify_mode` remain at their secure defaults.

**`ssl.SSLContext.load_verify_locations(cafile=None, capath=None, cadata=None)`:**
- Loads CA certificates used to validate peer certificates when `verify_mode != CERT_NONE`.
- Replaces (not appends to) the default system CAs when called on a context created with `create_default_context()`.

**Critical invariant:** `ssl.create_default_context(cafile=path)` does NOT weaken `check_hostname` or `verify_mode`. The production code walk (`TestTlsCannotBeDisabled`) only bans weakening patterns; using `cafile=` is safe.

### Python `urllib.request` docs (Python 3.11)

**`urllib.request.urlopen(url, data=None, [timeout,] *, cafile=None, capath=None, cadefault=False, context=None)`:**
- The `context` parameter accepts an `ssl.SSLContext` instance. This is the correct injection point.
- `cafile` and `capath` on `urlopen` itself are **deprecated since Python 3.6** — use `context=` instead.
- Usage: `urllib.request.urlopen(request, timeout=timeout, context=ssl_ctx)` where `ssl_ctx` is either `None` (use default system trust store) or a pinned SSLContext.

### CA pinning strategy — root vs. leaf

**Operational constraint (critical):** arxiv.org uses Let's Encrypt (ISRG Root X1 / X2 chain). Let's Encrypt leaf certs rotate every 60–90 days. The ISRG Root X1 cert is valid until 2035-09-30; ISRG Root X2 until 2035-09-17. Pinning the **root CA** means the bundle requires updating only when ISRG changes its root (years, not months). Pinning the **intermediate or leaf** would require manual bundle updates every 60–90 days — operationally toxic.

**Recommendation:** The bundle should contain the ISRG Root X1 (and X2 as a backup) PEM. Operators obtain this from https://letsencrypt.org/certificates/ or via `openssl s_client -connect arxiv.org:443 -showcerts`. The bundle is stable on a multi-year cadence.

**Command to capture the current chain (for the operator runbook):**
```bash
openssl s_client -connect arxiv.org:443 -servername arxiv.org -showcerts 2>/dev/null \
  | awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/' \
  | tail -n +$(($(grep -n "BEGIN" <<< "$(openssl s_client -connect arxiv.org:443 -servername arxiv.org -showcerts 2>/dev/null)" | tail -1 | cut -d: -f1) - 1))
```
Simpler form: `openssl s_client -connect arxiv.org:443 -showcerts 2>/dev/null | openssl x509 -noout -issuer -subject`

### Bundle source decision

**Option A — vendor `infra/ca/arxiv-ca-bundle.pem`:** The repo ships a static PEM file. Self-contained, no operator setup. Requires a periodic commit to update when ISRG rotates roots. Per the ISRG Root X1/X2 cadence, this is a years-level update. File size ~2-3 KB (root cert only).

**Option B — operator-supplied path via `ARXMCP_ARXIV_CA_BUNDLE_PATH`:** The operator points an env var at a PEM file they manage. Flexible but adds operational surface area. If the operator forgets to set the path when enabling the flag, startup must FAIL CLOSED.

Recommendation: **Option A (vendor the bundle)** for operational simplicity — the root CA rotates rarely, the file is tiny, and a committed bundle is self-auditable via git history.

## Recommendation

**Implement using `ssl.create_default_context(cafile=bundle_path)` injected as an optional `context=` parameter into both `try_cache` in `ingest/ar5iv_fetch.py` and `fetch_eprint` in `tools/arxiv_fetch.py`. Vendor the ISRG Root X1 bundle at `infra/ca/arxiv-ca-bundle.pem`. Build the SSLContext factory as a module-level function in a new `server/ssl_pin.py`.**

Reasoning:
1. `ssl.create_default_context(cafile=...)` is the only approach that preserves `check_hostname=True` and `verify_mode=CERT_REQUIRED` while replacing the CA store — it won't trigger the `TestTlsCannotBeDisabled` walk.
2. `urllib.request.urlopen(context=...)` is the correct non-deprecated injection API for Python 3.11.
3. Vendoring the root CA bundle at `infra/ca/arxiv-ca-bundle.pem` is operationally superior to operator-supplied paths: no env var to forget, no startup failure from missing path, self-auditable via git.
4. A shared factory in `server/ssl_pin.py` (not in `config.py`) keeps SSL logic isolated and testable.
5. The startup INFO log belongs in `server/main.py` adjacent to the existing `unsafe_network_bind` WARN log — both are startup-time opt-in notifications.

**Key implementation pattern:**
```python
# server/ssl_pin.py
import ssl
from pathlib import Path

ARXIV_CA_BUNDLE = Path(__file__).resolve().parent.parent / "infra" / "ca" / "arxiv-ca-bundle.pem"

def build_arxiv_ssl_context() -> ssl.SSLContext:
    if not ARXIV_CA_BUNDLE.is_file():
        raise RuntimeError(
            f"ARXMCP_PIN_ARXIV_CA=1 but CA bundle not found at "
            f"{ARXIV_CA_BUNDLE}. Refusing to fall back to system trust store. "
            f"Run 'make refresh-arxiv-ca' or disable the pin."
        )
    return ssl.create_default_context(cafile=str(ARXIV_CA_BUNDLE))
```

**Fail-closed requirement (load-bearing):** When `pin_arxiv_ca=True` but the bundle is missing, the factory MUST raise `RuntimeError` — NOT fall back to the system trust store. Silently degrading to the system store would defeat the entire purpose of the pin.

## Open questions

1. **Should `server/ssl_pin.py` be importable without affecting `TestNoVerifyFalse`?** Yes — the factory uses `ssl.create_default_context(cafile=...)` which contains no banned patterns. The test walk won't flag it.

2. **Where does the SSLContext get constructed — once at startup or per-call?** Build once at startup (in `server/main.py` lifespan or at module import time in `server/ssl_pin.py`) and pass the instance through. Constructing per-call is wasteful and adds latency. The `SSLContext` object is thread-safe for concurrent connections.

3. **Does `try_cache` in `ar5iv_fetch.py` need a Config dependency, or is the ssl_context injected by the caller?** Inject by the caller — `try_cache` already accepts kwargs (`cache_dir`, `parsed_dir`, `timeout_seconds`, `user_agent`). Add `ssl_context: ssl.SSLContext | None = None`. The caller (bulk ingest orchestrator) builds the context from Config and passes it in. This avoids importing Config into the ingest module (separation of concerns).

4. **`tools/arxiv_fetch.py::fetch_eprint` is in `tools/` not `ingest/`** — but the test walk covers `tools/`. The new `context=ssl_ctx` kwarg on urlopen is safe; it does not trigger any banned pattern.

No open questions block implementation — all can be answered from the above analysis.

## Failure-mode analysis

Seven plausible failure modes, grounded in `08-security-observability-ops.md` § Threat 7:

**(a) Flag=True but no bundle exists.**
- Trigger: `ARXMCP_PIN_ARXIV_CA=1` set but `infra/ca/arxiv-ca-bundle.pem` absent (deleted, never committed, fresh clone with gitignored bundle).
- Symptom: If not fail-closed, silently uses system trust store — DEFEATS the pin entirely.
- Mitigation: Factory MUST raise `RuntimeError` at bundle-load time (startup or first use). Message must tell operator to run `make refresh-arxiv-ca` or disable the flag.

**(b) Bundle stale — arxiv.org rotated past the pinned CA root.**
- Trigger: ISRG rotates Root X1/X2 (rare, but documented as occurring). All fetches fail with `ssl.SSLCertVerificationError`.
- Symptom: Every ar5iv and arxiv.org fetch fails; ingest stops.
- Mitigation: Error message in the exception must say "ARXMCP_PIN_ARXIV_CA is set; CA bundle may be stale. Run make refresh-arxiv-ca". The Makefile target must be documented.

**(c) Bundle contains wrong CA (operator copy-paste error).**
- Trigger: Operator supplies a PEM from DigiCert instead of ISRG, but arxiv.org uses Let's Encrypt.
- Symptom: Same as (b) — `ssl.SSLCertVerificationError` on every arxiv fetch.
- Mitigation: The `Makefile refresh-arxiv-ca` target should immediately test against a live fetch of `https://arxiv.org/`. Document this in the runbook.

**(d) Bundle path is unreadable (permissions error).**
- Trigger: The PEM file exists but `ssl.create_default_context(cafile=path)` raises `OSError` (e.g., 600 permissions on a root-owned file, operator running as www-data).
- Symptom: `OSError` propagated from `build_arxiv_ssl_context()`.
- Mitigation: The factory must let `OSError` propagate (don't suppress); `RuntimeError` wrapping is optional. The error message from Python's `ssl` module is already clear for permission errors.

**(e) Flag=True but bundle path env var not set (Option B only — not applicable if vendoring).**
- Trigger: Only relevant if using operator-supplied path. With Option A (vendored bundle), the path is hardcoded in `server/ssl_pin.py`. Eliminated by the vendor-bundle recommendation.

**(f) Flag=False (default) but SSLContext is constructed anyway.**
- Trigger: A future developer calls `build_arxiv_ssl_context()` unconditionally without checking the flag.
- Symptom: The vendored CA is ALWAYS used even when pin is off, silently restricting the trust store.
- Mitigation: The calling code must gate the factory call: `ssl_ctx = build_arxiv_ssl_context() if config.pin_arxiv_ca else None`. Tests must assert that `pin_arxiv_ca=False` results in `None` being passed to urlopen (no custom context).

**(g) Pin applied to ar5iv but not arxiv_fetch (or vice versa) — partial coverage.**
- Trigger: Implementation wires `ingest/ar5iv_fetch.py` but forgets `tools/arxiv_fetch.py`, or vice versa.
- Symptom: One fetch path uses the pinned CA, the other uses the system trust store. The pin contract is incomplete.
- Mitigation: Tests must assert BOTH paths use the SSLContext when the flag is set. The regression test should mock `urllib.request.urlopen` for both call sites and capture the `context=` kwarg.

**(h) SSLContext built at startup but fetch occurs before resources are warm.**
- Trigger: The SSLContext is constructed inside `Resources.startup()` but a fetch is triggered before startup completes (theoretical in this codebase).
- Symptom: `AttributeError` or `None`-context fetch if the context is stored on a Resources instance that hasn't been passed yet.
- Mitigation: Build the SSLContext at module import time in `server/ssl_pin.py` (lazy-singleton on first call), not inside `Resources`. It's a pure function of the Config flag and the vendored file path — no async dependencies.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `gh issue close` | `chris-dare-dev/arXMCP#5` | The milestone brief explicitly requires closing this GitHub issue once the implementation lands. Phase 4 main-thread action. |

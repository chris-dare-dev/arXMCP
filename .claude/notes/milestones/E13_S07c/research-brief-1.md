# Research Brief — E13_S07c

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T23:35:00Z

## In-codebase context

### Design notes applicable

Enumerated `.claude/notes/` at runtime: 01 through 10 plus `prompts-bp-discipline.md`,
`milestone-pipeline-conversion-critique.md`, `HANDOFF.md`, `README.md`.

Load-bearing notes for this milestone:
- `08-security-observability-ops.md` — Threat 7 verbatim mitigation
- `06-mcp-server-design.md` — server architecture (7-tool surface, no tool changes here)
- `07-multi-agent-caching.md` — no tool schema changes → no BP1 re-pin needed

### Threat 7 verbatim mitigation (from `08-security-observability-ops.md`)

> **Mitigations:**
> - Verify TLS certs (default for the HTTP client; do not disable).
> - Pin known fingerprint of arxiv.org's certificate authority chain (rotated
>   periodically).
> - Content-length sanity checks (a single paper > 100 MB source is suspicious).
> - Sandbox the parser (Threat 3 mitigation covers downstream impact).

### `server/config.py` — the `pin_arxiv_ca` field (verbatim docstring excerpt)

```python
#: E13_S07 (Threat 7) — opt-in CA pinning flag for arxiv.org.
#: Default ``False``: ``urllib.request`` uses the system trust
#: store (safe-by-default; TLS verification cannot be disabled
#: by any ``ARXMCP_*`` env var).
#:
#: **Forward-compatible placeholder. No current behavior.**
#: Setting ``True`` is accepted by the config but does NOT yet
#: change the SSL context — the field is plumbing for a future
#: milestone ...
pin_arxiv_ca: bool = False
```

The `Config` class has `model_config = SettingsConfigDict(env_prefix="ARXMCP_", extra="forbid")`.
This means any new env-var-backed configuration (e.g. a CA bundle path) MUST be declared as a
`Config` field — undeclared `ARXMCP_*` vars are caught at startup by `_scan_unknown_arxmcp_env_vars`
in `server/main.py` and raise `ValueError`.

Sibling pattern for an optional path field: `lean_repl_dir: Path | None = None` — used with
`enable_lean: bool = False`. This is the exact pattern to follow for a CA bundle path
that is only required when the feature is enabled.

### `ingest/ar5iv_fetch.py` — in-scope HTTP fetch site #1

The single `urlopen` call is at line 162:
```python
with urllib.request.urlopen(  # noqa: S310 — fixed https URL
    request, timeout=timeout_seconds
) as response:
```

The `urlopen` signature supports a `context=` keyword argument for an `ssl.SSLContext`.
The `try_cache` function signature is:
```python
def try_cache(
    paper_id: str,
    *,
    cache_dir: Path = DEFAULT_AR5IV_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    timeout_seconds: float = AR5IV_TIMEOUT_SECONDS,
    user_agent: str = "arxmcp-ingest/0.1",
) -> Ar5ivResult:
```

To inject the SSL context without disturbing the retry/timeout machinery, the implementer
adds an optional `ssl_context: ssl.SSLContext | None = None` parameter and passes it to
`urlopen(request, timeout=timeout_seconds, context=ssl_context)`.

The callers of `try_cache` must pass the context when `Config.pin_arxiv_ca=True`. The
context is built once at startup (or at call-site via a module-level factory) and passed
down. This avoids re-building the context per-request.

### `tools/arxiv_fetch.py` — in-scope HTTP fetch site #2

The fetch call is at line 228:
```python
with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
```

The `fetch_eprint` function does NOT currently accept an SSL context. The same
`ssl_context: ssl.SSLContext | None = None` parameter injection applies here.

Note: `tools/arxiv_fetch.py` is documented as "unsandboxed dev tooling." The comment
at line 9: *"Production ingestion (E11) will re-implement these in `ingest/` with
subprocess UID isolation per .claude/notes/08-security-observability-ops.md Threat 3
— for now this is unsandboxed dev tooling."*

### `server/main.py` lifespan — where the startup INFO log lands

The existing pattern for startup-time WARNING log (from `server/main.py` lines 686–693):
```python
if cfg.unsafe_network_bind:
    logger.warning(
        "ARXMCP_UNSAFE_NETWORK_BIND=1 is set; server binding to %r "
        "(non-loopback). ...",
        cfg.bind_host,
    )
logger.info(
    "Starting arxmcp-server on %s:%d", cfg.bind_host, cfg.bind_port
)
```

The INFO log for `pin_arxiv_ca=True` should land in the `__main__` block of `server/main.py`,
adjacent to the `unsafe_network_bind` warning (same section, same precedent pattern). It fires
AFTER the config is loaded and validated, BEFORE `uvicorn.run`. Alternatively it could land in
`Resources.startup` — but that is the server lifecycle; the CA pin applies to ingest tools too,
so the `__main__` block is the more natural place for server startup; ingest callers need a
separate log in their own entrypoints.

### `.claude/docs/security-threat-7-audit.md` — what needs editing

The CA pinning section (lines 104–114 of the audit doc) contains verbatim disclaimers that
become false after this milestone ships:

> When True, the value is accepted by Config but **has no current behavior**. The server
> today emits no startup INFO log on opt-in; the log line and the SSL-context wiring land
> together in the closure milestone...

And the operator runbook section (lines 200–213):

> Today this is a forward-compat stub — the flag is accepted by Config but has **no
> current behavior**. Setting it does not change the SSL context and does not produce
> any log line.

The implementer MUST remove both "no current behavior" disclaimers and replace them with
accurate documentation of the actual behavior and bundle path.

### `tests/security/test_source_ingest.py::TestPinArxivCaFlag`

Currently 3 tests (verified: file has 21 total test methods, and the class has 3):
1. `test_field_defaults_to_false` — default False assertion; still valid after this milestone.
2. `test_field_accepts_env_opt_in` — `ARXMCP_PIN_ARXIV_CA=1` accepted; still valid.
3. `test_audit_doc_documents_the_flag` — checks audit doc has `ARXMCP_PIN_ARXIV_CA` + `100 MB` +
   `Threat 7`; still valid (doc will still have these strings).

The new tests to add (4 minimum, per the brief ACs):
- Factory builds a valid `ssl.SSLContext` when `pin_arxiv_ca=True` and bundle file is present.
- Factory raises a clear error when `pin_arxiv_ca=True` but bundle file is absent or invalid.
- `ar5iv_fetch.try_cache` actually calls `urlopen` with a non-None `context=` arg when
  a CA context is injected.
- Server `__main__` startup log emits INFO containing "pin_arxiv_ca" or "CA pin" when the
  flag is set (caplog or monkeypatch).

### Scope discipline — files NOT in scope

`ingest/graph_ingest.py` — fetches `api.openalex.org` (different host, different CA).
`ingest/inspire_ingest.py` — fetches `inspirehep.net/api` (different host, different CA).
`ingest/oai_delta.py` — fetches `oaipmh.arxiv.org` (DIFFERENT subdomain from arxiv.org; the
  OAI-PMH endpoint is `export.arxiv.org/oai2` — same root domain, but the Threat 7 scope
  statement says "arxiv.org and ar5iv.labs.arxiv.org"; the brief explicitly says NOT oai_delta).

Verified by reading the files: all three use `urllib.request.urlopen` with default SSL context
(safe by default; no custom SSLContext anywhere in the codebase per the `TestTlsCannotBeDisabled`
test that walks the codebase).

## Prior decisions and lessons

**Git log (recent, relevant):**
- `feat(ingest): redirect-host pin on graph + inspire (E13_S07b)` — E13_S07b shipped 2026-05-??,
  closed #2. E13_S07c closes #5 on the same Threat 7 tree.
- `rect(ingest): close F1, F2, F3 from E13_S07b critique` — the F2 finding from E13_S07b was
  scheme-downgrade guard; similar discipline applies to the CA bundle path validation here.

**Memory — E13_S07 patterns:**
- `no-ingest-sources-directory-exists` (memory) — no `ingest/sources/`; actual sites are
  `ingest/ar5iv_fetch.py`, `tools/arxiv_fetch.py`, etc.
- `urllib-request-no-shared-client-needed` (memory) — urllib is safe-by-default; no httpx.
- `no-docker-compose-exists` (memory) — no docker-compose; Makefile is the build interface.

**Banned patterns to avoid:**
- `assert` for the "bundle not found" invariant — use `if ... raise RuntimeError(...)`.
- `BaseHTTPMiddleware` — not applicable here (no new middleware).
- No `anthropic` SDK — not applicable.

**No tool schema changes** — this milestone adds NO new MCP tools. `EXPECTED_TOOL_SCHEMA_SHA256`
does NOT need re-pinning. No BP1 cache impact.

**`tests/conftest.py` `KMP_DUPLICATE_LIB_OK=TRUE`** — this milestone does not touch it.

**Doc placement** — update goes in `.claude/docs/security-threat-7-audit.md` (already the
correct location, established by every prior E13 milestone). Do NOT create new files under
`docs/` or repo root.

## External sources

No MCP spec changes relevant (this milestone adds no new tools, no schema changes).
No prompt-caching docs relevant (no tool schema changes, BP1 unaffected).

**Python `ssl` module docs (standard library, Python 3.11+):**
- `ssl.create_default_context(cafile=...)` — creates a context with `check_hostname=True`,
  `verify_mode=CERT_REQUIRED`, and loads the CA bundle from `cafile` instead of the system
  store. This is the exact API to use for CA pinning.
- `ssl.SSLContext.load_verify_locations(cafile=...)` — alternative: create a context then
  load CAs explicitly.
- The cleanest API: `ssl.create_default_context(cafile="/path/to/bundle.pem")` — one call,
  keeps `check_hostname=True` and `CERT_REQUIRED` by default.

**Let's Encrypt / arxiv.org CA chain (context for bundle decision):**
- arxiv.org as of 2026-05 uses a Let's Encrypt certificate chain. The root CA is ISRG Root X1
  (self-signed; long-lived until 2035). The intermediate is `E5` or `R10` (short-lived, rotates
  ~90 days). Pinning the ROOT CA (ISRG Root X1) is rotation-stable; pinning the intermediate
  or leaf is operationally fragile.
- This means a vendored bundle containing ISRG Root X1 only is durable across Let's Encrypt
  intermediate rotations and would not need frequent updates.

## Recommendation

**Bundle source: vendor at `infra/ca/arxiv-ca-bundle.pem`** (option a). Rationale: arXMCP is
single-user / single-workstation per `01-mission-and-context.md`. An operator-supplied path
(`ARXMCP_ARXIV_CA_BUNDLE_PATH`) pushes operational burden to the person who is the developer.
Vendoring the bundle is friendlier for the solo-dev case and is self-contained. The bundle
should contain ONLY the ISRG Root X1 root CA PEM (the Let's Encrypt root currently used by
arxiv.org and ar5iv), which is stable across 90-day intermediate rotations and does not require
frequent updates. The bundle itself is public, non-secret PEM material from Let's Encrypt's
official distribution.

**BUT** — a second `Config` field `arxiv_ca_bundle_path: Path | None = None` MUST be declared
for operator override (even if the default is `None` meaning "use the vendored bundle"). This
keeps the `extra="forbid"` contract intact and gives operators a path to supply their own bundle
without code changes.

**Fail-closed semantics: use `model_validator(mode='after')` on Config** (option over
`resources.py::startup`). Rationale: the `pin_arxiv_ca=True` + missing bundle is a
configuration error, not a runtime error. Detecting it at `Config.__init__` time gives the same
"exits with code 1 before uvicorn binds" behavior as the `bind_host` loopback validator.
The validator should check: if `pin_arxiv_ca=True` AND `arxiv_ca_bundle_path` is set AND the
path does not exist → raise `ValueError`. If `pin_arxiv_ca=True` AND `arxiv_ca_bundle_path`
is None → check the vendored bundle at `infra/ca/arxiv-ca-bundle.pem` relative to repo root;
if missing → raise `ValueError`.

**SSL context factory: `server/ssl_pin.py`** (a new thin module, ~30 lines). It exports
`build_arxiv_ssl_context(config: Config) -> ssl.SSLContext | None` — returns `None` when
`pin_arxiv_ca=False` (callers pass `context=None` which is the urllib default = system trust
store). Returns a configured context when `True`. This keeps the factory testable in isolation.

**Refresh procedure: `make refresh-arxiv-ca`** (Makefile target). The Makefile already has
targets like `make sbom` that invoke local tooling. A `refresh-arxiv-ca` target that uses
`openssl s_client` to fetch the live arxiv.org cert chain and writes the root CA PEM to
`infra/ca/arxiv-ca-bundle.pem` is reproducible and discoverable via `make help`. The target
output must be deterministic enough that a developer can review the diff before committing.

**Startup INFO log: `server/main.py` `__main__` block**, adjacent to the existing
`unsafe_network_bind` warning pattern. Log line: `"ARXMCP_PIN_ARXIV_CA=1 is set; using
pinned CA bundle at %s for arxiv.org / ar5iv fetches"`.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one potential landmine: `ingest/ar5iv_fetch.py::try_cache` is a **production ingest
function**, and its callers (the bulk ingest orchestrator) do not currently pass any config
object down. The implementer must decide whether to (a) add a `ssl_context` parameter to
`try_cache` and thread it from callers, OR (b) implement a module-level singleton
`_arxiv_ssl_context: ssl.SSLContext | None = None` with a `set_arxiv_ssl_context(ctx)` setter
called at startup. Option (a) is cleaner but requires updating all callers. This is an
implementation detail the implementer resolves; the recommendation is option (a) — explicit
parameter threading is safer than module-level mutable state in a concurrent server.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `git push` | `main` | Land the implementation commit |
| `gh issue close` | `chris-dare-dev/arXMCP#5` | Brief mandates closing the tracked gap issue |

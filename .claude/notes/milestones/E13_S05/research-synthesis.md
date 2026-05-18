# Research Synthesis — E13_S05

**Milestone:** Threat-5 audit — Origin spoofing, DNS-rebinding, and localhost-binding hardening
**Generated:** 2026-05-18
**Inputs:** `research-brief-1.md` (in-codebase audit) + `research-brief-2.md` (external + failure-mode)

---

## Executive convergence

Both researchers converge cleanly. The headline finding: **Threat 5 is
largely already mitigated by E06_S05's `OriginValidationMiddleware` +
`HostValidationMiddleware` + `reject_non_loopback`**. The real
implementation gap is `Sec-Fetch-Site` enforcement; everything else is
audit / new env var work.

### Verified codebase facts (both researchers confirmed)

1. **`OriginValidationMiddleware` (E06_S05)** rejects any `Origin`
   not in `LOOPBACK_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}`.
   No-Origin requests pass (stdio shim path). Pure-ASGI.

2. **`HostValidationMiddleware` (E06_S05 F3 fix)** rejects any `Host`
   header not in `LOOPBACK_HOST_HEADER_HOSTS = {"127.0.0.1",
   "localhost", "::1", "testserver"}`. IPv6 bracket-stripping
   handled. Returns 421 Misdirected Request.

3. **`reject_non_loopback` validator** in `server/config.py` raises
   `ValidationError` when `ARXMCP_BIND_HOST` is not in
   `LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}`. Server
   refuses to start with non-loopback bind.

4. **`Sec-Fetch-Site` is NOT checked anywhere.** `grep -rn
   "Sec-Fetch-Site" server/` returns no matches. This is the only
   genuine implementation gap.

5. **`ARXMCP_ALLOWED_ORIGINS` env var does not exist.** Origin
   allow-list is hardcoded `LOOPBACK_ORIGIN_HOSTS`. The brief
   specifies an env-driven allow-list as a NEW feature.

6. **`ARXMCP_UNSAFE_NETWORK_BIND` env var does not exist.** The
   `reject_non_loopback` validator has no escape hatch. The brief
   specifies the escape hatch as a NEW feature.

7. **`E07_S01` real, `E07_S09` fictional.** E07 has S01–S04. The
   brief's `E07_S09` dependency is fictional (same drift pattern
   as E07_S12 in E13_S01, E07_S13 in E13_S02, E07_S10/E06_S07/S08
   in E13_S04). **`E07_S01` IS real but is "Phase 1: BM25 over
   body_tokens" — NOT Origin validation.** R1 finds Origin
   validation actually shipped in `E06_S05`. The brief's
   "E07_S01 (Origin pin)" attribution is wrong.

8. **No `docker-compose.yml`** at the repo root (E14 owns it). Only
   `infra/latexml/docker-compose.latexml.yml` exists. AC5 (Docker
   compose ports mapping) testing nonexistent infrastructure —
   same drift as E13_S03 D2 reframe.

9. **`tests/security/test_origin_binding.py`** does not exist;
   existing security tests at `tests/test_security.py` cover Origin,
   Host, and bind-host refusal. New file is the milestone deliverable.

10. **Doc placement** — same reframe as every E13 milestone:
    `docs/security/threat-5-audit.md` → `.claude/docs/security-threat-5-audit.md`;
    `docs/security/binding.md` → `.claude/docs/security-binding.md`.

11. **E13_S09 overlap.** R2 notes E13_S09 explicitly covers the bind
    regression test ("`tests/security/test_bind_regression.py`").
    E13_S05 delivers the binding doc artifact; E13_S09 owns the
    full regression suite. **Do not duplicate work here.**

---

## Convergent decisions (no divergence between researchers)

### Sec-Fetch-Site enforcement design

Both briefs converge:
- **Absent header** → allow (CLI tools / stdio shim don't send it)
- **`Sec-Fetch-Site: none`** → allow (browser top-level navigation)
- **Any other value** (`cross-site`, `same-site`, `same-origin`, or
  empty/garbage) → reject with 403

Mount as a NEW `SecFetchSiteMiddleware` (pure-ASGI), positioned
BEFORE `OriginValidationMiddleware` so the cheap header check
fires first.

### `ARXMCP_ALLOWED_ORIGINS` semantics

Both briefs converge with one resolved nuance (R1's OQ2):

- **Empty list (default)**: existing `LOOPBACK_ORIGIN_HOSTS` allow-
  list applies (no behavioral change vs E06_S05).
- **Non-empty list**: EXTENDS the loopback list — the listed origins
  are ALSO accepted alongside the loopback floor. The loopback list
  is a security floor that cannot be bypassed.

R1's OQ2 noted the brief is internally contradictory: "default
empty means only no-Origin requests accepted" vs. existing
behavior allows loopback Origin. Resolution: **keep existing
loopback behavior as the floor; `ARXMCP_ALLOWED_ORIGINS` extends
it.** Backward-compatible; documented in audit doc.

### `ARXMCP_UNSAFE_NETWORK_BIND` design

Both briefs converge:
- Add to `Config` as `unsafe_network_bind: bool = False`.
- Convert `@field_validator("bind_host")` → `@model_validator(mode="after")`
  so the validator can read both fields.
- When `unsafe_network_bind=True`, allow non-loopback bind host
  AND emit `logger.warning("...")` at startup.
- Mention the escape hatch in the binding doc with a strong
  warning.

R1 flagged the field-validator → model-validator refactor will
change the exception type. Existing tests in `tests/test_security.py
::TestStartupRejectsBadBind` use `subprocess.run` to assert exit
code, not exception class — so the type change is invisible at the
test layer. Verified by R1.

### Docker compose AC reframe

Both briefs agree this AC tests nonexistent infrastructure. Same
pattern as E13_S03 D2: ship a documentation artifact + static-
validation test instead of requiring a live `docker inspect`.

Two options surfaced:
- R1: assert that `08-security-observability-ops.md` §Docker
  deployment section contains the literal `127.0.0.1:7733:7733`
  text.
- R2: create a NEW standalone YAML artifact at
  `.claude/docs/security-docker-compose-ports.md`.

**Resolution: R1's approach.** Less new infrastructure. The
design note already documents the binding; a text-existence test
against the note suffices. The audit doc references the note
section.

---

## Implementation decision — INLINE path

Size estimate:
- `server/middleware.py` — +60 LOC for `SecFetchSiteMiddleware` (pure-ASGI)
- `server/main.py` — +5 LOC to mount the middleware in the chain
- `server/config.py` — +30 LOC for two new fields + model_validator refactor
- `tests/security/test_origin_binding.py` — NEW, ~250 LOC (6 ACs + sanity)
- `.claude/docs/security-threat-5-audit.md` — NEW, ~200 lines
- `.claude/docs/security-binding.md` — NEW, ~150 lines (binding escape-hatch warning)

**Total:** ~700 LOC across ~6 files. Over the 5-file decision-tree
threshold but tightly coupled (config + middleware + tests +
docs). **Path: INLINE.**

---

## Concrete implementation plan

### Step 1 — `server/config.py`: two new fields + model_validator refactor

```python
class Config(BaseSettings):
    ...
    bind_host: str = "127.0.0.1"
    ...
    #: E13_S05 — additional Origin values accepted beyond the
    #: hardcoded LOOPBACK_ORIGIN_HOSTS floor. Empty list = floor only.
    allowed_origins: list[str] = Field(default_factory=list)

    #: E13_S05 — escape hatch for non-loopback bind. When True,
    #: ARXMCP_BIND_HOST may be 0.0.0.0 (container deployments).
    #: Emits WARN at startup. Default False (server refuses non-loopback).
    unsafe_network_bind: bool = False

    @model_validator(mode="after")
    def _validate_bind_host(self) -> "Config":
        if self.bind_host not in LOOPBACK_HOSTS and not self.unsafe_network_bind:
            raise ValueError(
                f"ARXMCP_BIND_HOST must be a loopback address "
                f"({sorted(LOOPBACK_HOSTS)}); got {self.bind_host!r}. "
                f"Set ARXMCP_UNSAFE_NETWORK_BIND=1 to override (container "
                f"deployments only — emits a WARN log)."
            )
        return self
```

Remove the existing `@field_validator("bind_host")::reject_non_loopback`.

### Step 2 — `server/middleware.py`: `SecFetchSiteMiddleware`

```python
class SecFetchSiteMiddleware:
    """E13_S05 — reject any Sec-Fetch-Site value except `none` or
    absent. Browser top-level navigation sends `none`; CLI tools
    and the stdio shim omit the header entirely. Any other value
    means a web page (browser-mediated) initiated the request and
    should be rejected as a defense-in-depth layer alongside
    Origin and Host validation.

    Pure-ASGI. Mounted BEFORE OriginValidationMiddleware so the
    cheap byte-comparison fires first.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        value = _get_header(headers, b"sec-fetch-site")
        if value is not None and value != b"none":
            # Reject any other value (cross-site / same-site /
            # same-origin / "" / garbage). Absent header passes.
            await _send_security_403(
                send,
                code="sec_fetch_site_forbidden",
                message=(
                    f"Sec-Fetch-Site header value {value.decode('latin-1', 'replace')!r} "
                    f"is not permitted; only `none` (or absent) is accepted "
                    f"(E13_S05 Threat 5)"
                ),
            )
            return

        await self.app(scope, receive, send)
```

### Step 3 — `server/main.py`: mount the new middleware

Add `SecFetchSiteMiddleware` to the middleware chain, BEFORE
`OriginValidationMiddleware`. Update the request-flow comment.

### Step 4 — Wire `ARXMCP_ALLOWED_ORIGINS` into `OriginValidationMiddleware`

The middleware currently uses hardcoded `LOOPBACK_ORIGIN_HOSTS`.
Update to accept an additional `allowed_origins: frozenset[str]`
constructor arg, extending the hardcoded floor. Wire in
`server/main.py::create_app` from `config.allowed_origins`.

### Step 5 — `tests/security/test_origin_binding.py` (6 ACs)

```python
class TestSecFetchSite:
    def test_cross_site_rejected(self):
        ...
    def test_same_site_rejected(self):
        ...
    def test_none_value_allowed(self):
        ...
    def test_absent_header_allowed(self):
        ...

class TestAllowedOriginsEnvVar:
    def test_default_empty_keeps_loopback_floor(self):
        ...
    def test_non_empty_extends_floor(self):
        ...

class TestHostValidationRegressionForThreat5:
    # Existing HostValidationMiddleware behavior — guard against regression
    def test_public_ip_in_host_rejected(self):
        ...
    def test_subdomain_localhost_rejected(self):
        ...

class TestBindHostRefusal:
    def test_zero_host_rejected_without_unsafe_flag(self):
        ...
    def test_zero_host_accepted_with_unsafe_flag(self):
        ...

class TestDockerComposeNoteDocumentsLoopbackBinding:
    # AC5 reframe — assert the design note text
    def test_design_note_specifies_loopback_port_binding(self):
        ...
```

### Step 6 — `.claude/docs/security-threat-5-audit.md`

Per-mitigation table with status:
- ✅ Origin validation (E06_S05)
- ✅ Host validation (E06_S05 F3)
- ✅ Bind-host refusal (E06_S05)
- ✅ Sec-Fetch-Site enforcement (E13_S05)
- ✅ `ARXMCP_ALLOWED_ORIGINS` (E13_S05)
- ✅ `ARXMCP_UNSAFE_NETWORK_BIND` escape hatch (E13_S05)
- ⚠️ Docker compose port binding (documented in note 08; E14 wires it)

Plus DNS-rebinding attack mechanism + CVE backing (R2's
references) + Sec-Fetch-Site semantics for non-browser clients.

### Step 7 — `.claude/docs/security-binding.md`

Strong warning about `ARXMCP_UNSAFE_NETWORK_BIND`. Container
deployment guidance (`ports: "127.0.0.1:7733:7733"` mapping).
Cross-reference to E13_S09 for the full regression suite.

---

## Acceptance criteria status (reframed from brief)

- [x] **AC1** — `Sec-Fetch-Site` ≠ `none` (and not absent) → 403.
  New `SecFetchSiteMiddleware`.
- [x] **AC2** — Public IP in `Host` → 403/421. Already by
  `HostValidationMiddleware` (E06_S05). Regression-guarded.
- [x] **AC3** — `Host: attacker.localhost` → 403/421. Already by
  `HostValidationMiddleware`. Regression-guarded.
- [x] **AC4** — `ARXMCP_BIND_HOST=0.0.0.0` without
  `ARXMCP_UNSAFE_NETWORK_BIND=1` → refused.
  Currently refused unconditionally; the milestone adds the
  escape hatch and ensures the WITHOUT-flag path still refuses.
- [~] **AC5** — Docker compose maps `127.0.0.1:7733:7733`.
  REFRAMED: assert the design note in
  `08-security-observability-ops.md` documents this binding
  (main docker-compose.yml doesn't exist; E14 owns it).
- [x] **AC6** — `pytest tests/security/test_origin_binding.py`
  passes all cases.

---

## Open questions for the implementer

**None blocking.** All resolved by synthesis:

1. **`ARXMCP_ALLOWED_ORIGINS` semantics** — EXTENDS the loopback
   floor, never bypasses it. Empty list = current behavior.
2. **Validator refactor** — `@field_validator` → `@model_validator
   (mode="after")`. Exception class changes but existing tests use
   subprocess exit codes, not exception types. R1 verified.
3. **Docker AC** — text-existence assertion against the design
   note. No new YAML artifact.

---

## External writes the implementation will require

**None — purely local.** All deliverables are local file changes
and local commits. `git push` is the standard Phase 4 gated event.

---

## Threat-coverage matrix snapshot

After E13_S05:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Indirect prompt injection | ✅ E13_S02 |
| 3. LaTeXML sandbox hostile input (Phase 1) | ✅ E13_S03 |
| 4. Resource exhaustion | ✅ E13_S04 |
| 5. Origin spoofing / DNS rebinding | ✅ E13_S05 |
| 6–9 | ⏳ E13_S06 through E13_S09 |

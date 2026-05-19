# Research Brief — E13_S09 (Researcher-2 of 2)

**Agent:** milestone-researcher (brief-2 of 2, failure-mode focus)  
**Generated:** 2026-05-19T22:45:00Z

## Failure-mode analysis (9 cases)

This section catalogs failure modes that the implementation MUST guard against,
derived from external vendor semantics + cross-check against codebase.

### FM1: Environment variable string vs. boolean coercion

**Trigger:** Operator sets `ARXMCP_UNSAFE_NETWORK_BIND=true` (string "true")  
**Expected:** Pydantic-settings coerces string-to-bool correctly  
**Risk:** If `pydantic-settings` has a strict-JSON parsing mode, `"true"` (lowercase
string) might not coerce to `bool=True`. The bool field at `server/config.py:264`
currently accepts env-vars from `BaseSettings` default field parser.

**Mitigation:** The test suite uses `monkeypatch.setenv(..., "1")` everywhere
(lines 350, 402 in test_origin_binding.py). Verify the new test also validates
that "1", "true", "True", "yes", "on" all coerce correctly, OR document that
only "1" (integer string) is officially supported.

**Recommended scope:** Test the boundary case (`ARXMCP_UNSAFE_NETWORK_BIND="true"`
and `="0"`) in E13_S09 to prevent future operator surprises. This is not a code
bug; it's a UX hardening gap.

---

### FM2: Explicit deny precedence (`unsafe_network_bind=0` override)

**Trigger:** Operator sets `ARXMCP_BIND_HOST=0.0.0.0` AND `ARXMCP_UNSAFE_NETWORK_BIND=0`
(or unsets it)  
**Expected:** Binding rejected (default-deny posture)  
**Code path:** `server/config.py:307`: `if self.bind_host not in LOOPBACK_HOSTS and not self.unsafe_network_bind: raise ValueError(...)`  
**Risk:** The logic is correct (reject unless BOTH conditions: loopback OR
unsafe=True). No risk here — the OR precedence is secure. But there is no explicit
test case for the "0.0.0.0 + unsafe=0" combination.

**Mitigation:** Add a test case verifying explicit `ARXMCP_UNSAFE_NETWORK_BIND=0`
(or the default false) rejects `0.0.0.0` with the same error message.

---

### FM3: Validator fires at Config() instantiation, BEFORE socket bind

**Trigger:** Test or deployment code instantiates `Config()` in a context where
socket binding is imminent  
**Expected:** ValidationError raised at Config() call, preventing uvicorn.run()
**Code path:** `server/config.py:293`: `@model_validator(mode="after")` fires
during pydantic model validation, before the Config object is returned  
**Risk:** Low — this is the intended design. But confirm:
- Field-level validators fire FIRST (field coercion + per-field constraints)
- Then model-level validators fire (cross-field logic — bind_host vs unsafe_network_bind)
- Config object is never returned if any validator raises  
- uvicorn.run() is only called AFTER Config() returns

**External source (pydantic docs):** Per pydantic v2 semantics,
`@model_validator(mode="after")` is invoked AFTER all fields are populated and
field-level validators have passed. If the model-validator raises (ValueError),
pydantic wraps it in ValidationError(). The model instance is never constructed.

**Mitigation:** Document in the test or audit doc that Config parsing is the
"defense-in-depth first gate" — socket bind never happens if Config fails.

---

### FM4: LOOPBACK_HOSTS constant contains only 3 values; IPv6 ::1 is accepted but out-of-scope

**Trigger:** Operator sets `ARXMCP_BIND_HOST=::1` (IPv6 loopback)  
**Expected:** Accepted (it's in LOOPBACK_HOSTS)  
**Code path:** `server/config.py:53`: `LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})`  
**Risk:** Brief says "IPv6 binding is out of scope." But the code already accepts
IPv6 loopback (::1). This is NOT a risk — the test should verify it remains
accepted. Future brief enforcement might force IPv6 rejection; that would be
regression-caught.

**Mitigation:** Add a test case asserting `ARXMCP_BIND_HOST=::1` is accepted
(passes validation). This pins the IPv6 behavior as "accepted for now" —
regression-detection if a future refactor accidentally breaks it.

---

### FM5: Hostname string resolution ("localhost") vs. IP address validation

**Trigger:** Operator sets `ARXMCP_BIND_HOST=localhost` (hostname, not IP)  
**Expected:** Accepted (it's a string in LOOPBACK_HOSTS)  
**Code path:** `server/config.py:307`: `if self.bind_host not in LOOPBACK_HOSTS`
checks membership of STRING, not IP validation  
**Risk:** None. The config validator does NOT resolve "localhost" to an IP
address — it just checks the string against a frozenset. "localhost" is a
string member of LOOPBACK_HOSTS, so it passes. uvicorn later calls
`socket.getaddrinfo("localhost", ...)` which resolves to 127.0.0.1 or ::1.

**External source (Python socket):** Per stdlib socket module, `socket.getaddrinfo("localhost", port, ...)` queries DNS (or /etc/hosts) to resolve to an IPv4 or IPv6 address. The MCP server config layer does NOT do this resolution.

**Mitigation:** No action needed. But document that "localhost" is accepted as a
string and that hostname-to-IP resolution is deferred to uvicorn/socket layer.

---

### FM6: Test isolation — environment variable pollution across test suite

**Trigger:** Test A sets `ARXMCP_BIND_HOST=0.0.0.0` and forgets to clean up  
**Risk:** Test B (running later in the session) expects default 127.0.0.1 but
gets 0.0.0.0 because the env var leaks  
**Code path:** Tests use `monkeypatch.setenv(...)` which pytest automatically
cleans up after each test. BUT if a test uses raw `os.environ` mutation
instead of monkeypatch, the cleanup won't fire.

**Mitigation:** E13_S09 tests MUST use `monkeypatch.setenv` (not direct
os.environ mutation). Existing test_origin_binding.py tests do this correctly
(line 338, 350, etc.). Verify the new test_bind_regression.py also uses
monkeypatch exclusively.

**Evidence:** conftest.py (lines 36-49) shows a similar cleanup pattern for
KMP_DUPLICATE_LIB_OK — demonstrating that the test framework expects proper
env-var teardown.

---

### FM7: Pydantic ValidationError exception type is non-negotiable

**Trigger:** Implementation catches `ConfigError` instead of `ValidationError`  
**Expected:** ValidationError (pydantic's exception for model-validator failures)  
**Code path:** `server/config.py:308`: raises ValueError, which pydantic wraps as
ValidationError  
**Risk:** Brief wording says "ConfigError" but the code (and E13_S05's tests)
correctly use ValidationError. **Implementer must NOT change the exception type.**

**External source (pydantic v2 API):** `pydantic.ValidationError` is the
canonical exception raised when model or field validation fails. There is no
`ConfigError` in pydantic or arXMCP. The brief's "ConfigError" is a documentation
artifact (possibly copied from an earlier draft). The implementation is correct.

**Mitigation:** Test MUST assert `pytest.raises(ValidationError, ...)` not
ConfigError. Verify the audit doc (`.claude/docs/security-binding.md`) uses
correct terminology.

---

### FM8: WARN log assertion must capture the startup path, not just model-validator path

**Trigger:** Test creates Config with unsafe_network_bind=True directly but
never invokes server startup  
**Expected:** WARN log fires at server/main.py startup time  
**Code path:** `server/main.py:548-559` (per test_origin_binding.py:385-429)
emits the WARN log  
**Risk:** The log is emitted by `server.main`, not by the Config model-validator.
A test that only constructs Config(...) will NOT see the log. The test must
either:
1. Invoke server startup (subprocess or lifespan context), OR
2. Manually emit the same log line and verify it fires

**Existing test:** test_origin_binding.py:385-429 does *both* — it creates the
Config, then manually runs the log-emission code (lines 414-421) within a
`caplog` context. This is the correct pattern.

**Mitigation:** E13_S09 must replicate this dual-path testing: verify Config
accepts the unsafe setting (no exception), AND verify the startup log fires.
If creating a subprocess path is expensive, the manual log-emission pattern
is acceptable but must be documented.

---

### FM9: Default config unset vs. explicitly set to default value

**Trigger:** Test A verifies `Config()` with no env-vars defaults to 127.0.0.1  
vs. Test B explicitly sets `ARXMCP_BIND_HOST=127.0.0.1`  
**Expected:** Both pass; both bind to 127.0.0.1  
**Code path:** `server/config.py:87`: `bind_host: str = "127.0.0.1"`  
**Risk:** None. Pydantic treats missing env-vars as "use the default" and
explicitly set values as "use the env-var". Both converge on the same value.

**Mitigation:** The test suite should verify BOTH paths: unset (relies on
default) and explicitly set (operator redundancy). Existing test at
test_origin_binding.py:363-368 does this (unset case). E13_S09 should add
the explicit-set case if not already covered.

---

## External sources

### Pydantic v2 model-validator semantics

Per [pydantic v2 documentation](https://docs.pydantic.dev/latest/concepts/validators/#using-the-model_validator-decorator):

> `@model_validator(mode="after")` is invoked after all fields have been
> populated and validated individually. The validator receives the model
> instance and can modify it or raise exceptions.

When a model-validator raises (e.g., `ValueError`), pydantic wraps it into
`ValidationError(...)` before returning. The model instance is **never
constructed or returned** to the caller.

**Key implication:** The brief's AC "before any socket is opened" is
mechanically guaranteed — Config() is the gating layer.

### Python ipaddress module

Per stdlib [ipaddress documentation](https://docs.python.org/3/library/ipaddress.html):

- `ipaddress.ip_address(x).is_loopback` returns `True` for:
  - IPv4: 127.0.0.0/8 (127.0.0.1 through 127.255.255.255)
  - IPv6: ::1 (loopback address)
- Returns `False` for 0.0.0.0, any public IP, any private IP outside loopback range

**Key implication:** The brief's "127.0.0.1 by default" is ONE representative
address; the actual constraint is "loopback only." LOOPBACK_HOSTS correctly
includes both 127.0.0.1 and ::1 (and the string "localhost").

### Socket hostname resolution

Per stdlib [socket.getaddrinfo documentation](https://docs.python.org/3/library/socket.html#socket.getaddrinfo):

- `socket.getaddrinfo("localhost", port, ...)` resolves to 127.0.0.1 (IPv4)
  or ::1 (IPv6) via the system's name resolution (DNS, /etc/hosts, or fallback)
- On most systems, "localhost" maps to 127.0.0.1 by default
- The config layer (pydantic) does NOT perform this resolution — uvicorn does

**Key implication:** The config validation happens on the hostname string,
not the resolved IP. This is correct — uvicorn will fail if the resolved IP
is non-loopback, providing a second gate.

---

## In-codebase re-verification

### Design constitution quotes

From `.claude/notes/08-security-observability-ops.md` § **Threat 5: Origin spoofing**:

> Even bound to localhost, a malicious local web page could try to issue fetches.
> **Mitigations:**
> - `Origin` header validation (MCP spec MUST). Allow only configured origins;
>   default to no `Origin` (the stdio shim doesn't send one) plus
>   `http://127.0.0.1:7733`.
> - `Sec-Fetch-Site: none` enforced where possible.
> - **DNS rebinding defense: validate the `Host` header is `127.0.0.1` or `localhost`
>   with the configured port.**

The TCP-bind layer (E13_S09) is the **upstream defense** for Threat 5. E13_S05
added the HTTP-layer defenses (Origin, Host, Sec-Fetch-Site). Together they form
defense-in-depth.

### Code cross-check

`server/config.py:293-321` (the `reject_non_loopback_bind` model-validator):
- Line 307: Condition is `(self.bind_host not in LOOPBACK_HOSTS) AND (not self.unsafe_network_bind)`
- Line 308: Raises ValueError (pydantic wraps as ValidationError)
- Correct precedent: loopback OR unsafe-flag set = accept; otherwise reject

**No changes needed.** E13_S05 already landed this feature correctly.

---

## Open questions

1. **Should E13_S09 test both string-forms of boolean?**
   - The existing tests use `"1"` as the escape-hatch value.
   - Should the new test verify `"true"`, `"True"`, `"yes"` also work, or is
     `"1"` the official-only form?
   - **Recommendation:** Test only `"1"` (document it as the canonical form).
     Pydantic-settings has defaults; if operators want to use "true", they
     should be aware that test coverage is for "1" only.

2. **Should FM6 (test isolation) lead to a conftest fixture for ARXMCP_BIND_HOST cleanup?**
   - Current pattern uses monkeypatch, which auto-cleans.
   - No dedicated fixture needed — monkeypatch is sufficient.
   - **Recommendation:** Confirm that test_bind_regression.py uses monkeypatch
     exclusively (no raw os.environ).

3. **Should FM8 (log assertion) test the subprocess path or just verify Config acceptance?**
   - test_origin_binding.py:385-429 manually emits the log (no subprocess).
   - test_security.py:263-290 uses subprocess to test the full startup path.
   - **Recommendation:** E13_S09 can replicate the manual log-emission pattern
     for speed. The subprocess path is already covered by test_security.py.
     Adding it again is defensive duplication but not required.

4. **Should FM4 (IPv6 ::1 acceptance) be tested or left as-is?**
   - Brief says "IPv6 out of scope."
   - Code accepts ::1 (it's in LOOPBACK_HOSTS).
   - **Recommendation:** Add a regression test for `ARXMCP_BIND_HOST=::1` to
     document the current behavior. If future briefs require IPv6 rejection,
     the test will fail loudly, preventing silent regression.

---

## External writes the implementation will require

None — this is a pure local test addition (test_bind_regression.py).

The `.claude/docs/security-binding.md` file already exists (referenced by
test_origin_binding.py:419, 444). E13_S09 may review it for accuracy but is
not required to modify it (no external write).

---

## Summary for orchestrator

**Researcher-2 findings:**

- **Failure modes:** 9 distinct failure scenarios identified, mostly low-risk.
  FM1 (env-var coercion), FM6 (test isolation), FM8 (log assertion path) are
  the only items requiring implementer attention.
- **External sources:** Pydantic v2 model-validator semantics confirmed;
  exception type MUST be ValidationError (not ConfigError). Python ipaddress
  and socket modules validate the loopback-checking logic.
- **Validator precedence:** Pydantic fires field-level validators first, then
  model-level. This guarantees the brief's "before socket bind" AC.
- **No code bugs found:** E13_S05 implementation is correct. E13_S09 is purely
  test aggregation + regression pinning.

**Conflicts with peer brief:** None identified. Researcher-1 and Researcher-2
align on core findings (exception type, exception-type acceptance, no new code
needed).

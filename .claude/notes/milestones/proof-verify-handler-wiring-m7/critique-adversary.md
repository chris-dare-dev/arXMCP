# Critique — proof-verify-handler-wiring-m7

**Critic:** adversary
**Generated:** 2026-05-21T00:00:00Z
**Commit range:** 3b43a460698a0b1db3b1855ab7ec783245fb2aa1..18dcee81c4711177c9931bfb67ba55a4cf0aab22
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- The implementation is competent — slug validation is shared, schema isolation is correct, FK cascade fires, mkdir-after-INSERT prevents orphan dirs, prefix-not-substring carve-out is enforced and tested. The defect concentration is in a single axis: the carve-out's interaction with the rest of the security stack on the new `/ui/api/*` surface.
- 0 CRITICAL, 1 HIGH, 2 MEDIUM, 2 LOW.
- Highest-risk file:line: `server/middleware.py:483-498` + `server/main.py:461` — the `SecFetchSiteMiddleware` carve-out exempts ALL `Sec-Fetch-Site` values (not just `same-origin`) on `/ui/*`, which combined with `OriginValidationMiddleware`'s any-port-loopback policy enables cross-origin CSRF from any other local app the user happens to run.
- Tool schema invariant verified clean: `tests/test_server_tool_schema.py` passes without re-pinning (`pytest tests/test_server_tool_schema.py` → 9 passed). All 59 new tests pass.
- No banned patterns introduced (no `assert`, no `BaseHTTPMiddleware`, no `import anthropic`, no `"claude-opus"`, no kuzu pin drift, no `0.0.0.0` bind, no `--no-verify` / `--no-gpg-sign`).
- Cache byte-stability is preserved (AC #5): no changes to `server/tools.py::ALL_TOOLS`, no changes to `server/prompts.py`.
- mkdir-after-INSERT and lifespan-startup failure paths have edge cases that are off the common path but worth fixing cheaply (MEDIUM each).
- Tier-sequencing clean (m7 depends only on m6, which is complete) and no-fork policy clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `/ui/api/*` is CSRF-able from any other local-app port

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/middleware.py:483-498` + `server/main.py:461`
- **What:** The `SecFetchSiteMiddleware` carve-out (`exempt_prefixes=("/ui",)`) bypasses the Sec-Fetch-Site check ENTIRELY for `/ui/*` paths — not just for `same-origin` (which htmx legitimately needs), but also for `cross-site`, `same-site`, garbage values, and missing headers. The downstream `OriginValidationMiddleware._origin_is_allowed` (line 169-200) accepts ANY port on `127.0.0.1`/`localhost`/`::1`. With no auth and no CSRF token, the result is that another local app on port 9999 can forge a browser-initiated `fetch()` to `http://127.0.0.1:7733/ui/api/notebooks` and create / list / delete notebooks on behalf of the user. Empirically reproduced: a TestClient POST with `Origin: http://127.0.0.1:9999` and `Sec-Fetch-Site: cross-site` returns 201 + creates the row + creates the on-disk directory.
- **Why it matters:** The m7 brief synthesis Open Question 5 resolved that "the default `LOOPBACK_ORIGIN_HOSTS` already covers `http://127.0.0.1:7733`, which is the same-origin where htmx will come from. Zero config change needed." That resolution is correct for the happy path but ignores the cross-origin attack: any other localhost web app (a dev server, a JupyterLab instance, a casual Flask script running on `:5000`) becomes a CSRF launchpad. The implementer's `TestUiCarveoutAcceptsSameOrigin::test_ui_api_path_accepts_cross_site` test even ASSERTS this as intentional behavior (`tests/security/test_sec_fetch_site_carveout.py:112-126`), but the brief never required `cross-site` to be allowed — it required `same-origin` (the htmx case).
- **Proposed fix:** Two complementary defenses, either of which closes the hole:
  1. **Tighten the carve-out semantics.** Change `SecFetchSiteMiddleware` so `exempt_prefixes` does not bypass the header check entirely; instead, it relaxes the allow-set to `{none, same-origin}` while still rejecting `cross-site` / `same-site` / garbage. New shape:
     ```python
     if any(path == p or path.startswith(p + "/") for p in self._exempt_prefixes):
         _UI_ALLOWED = {b"none", b"same-origin"}
         if sec_fetch_site is None or sec_fetch_site in _UI_ALLOWED:
             await self.app(scope, receive, send); return
         # fall through to the rejection path with the existing 403 envelope
     ```
  2. **Pin the OriginValidationMiddleware port** for the `/ui/*` carve-out: only accept `Origin` headers whose port equals `cfg.bind_port`. Reuse the existing `_validate_host_header(host, allowed_port)` shape from line 203.
- **Regression guard:** Add a test to `tests/security/test_sec_fetch_site_carveout.py`:
  ```python
  def test_ui_api_path_rejects_cross_site(client):
      """A cross-site POST from another localhost app MUST be 403'd
      even on /ui/* — the carve-out is for same-origin htmx, not for
      arbitrary cross-app CSRF."""
      r = client.post(
          "/ui/api/notebooks",
          headers={"Origin": "http://127.0.0.1:9999",
                   "Sec-Fetch-Site": "cross-site"},
          json={"slug": "csrf-victim"},
      )
      assert r.status_code == 403
  ```
  Also: invert `test_ui_api_path_accepts_cross_site` to a rejection test, and document in `.claude/docs/security-threat-model-coverage.md` Threat 5 that the carve-out is `{none, same-origin}` only.

---

### F2 — `Resources` leak if `NotebooksStore.open` raises during lifespan startup

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/main.py:307-315`
- **What:** `NotebooksStore.open(...)` is awaited AFTER `Resources.startup(...)` (line 292) but BEFORE the `try:` block (line 321) that owns the `Resources.shutdown()` cleanup in its `finally`. If `NotebooksStore.open` raises (permission denied on `var/arxmcp/cache/`, full disk, SQLite library mismatch, parent-dir creation failure), the exception escapes the lifespan; `resources.shutdown()` is never invoked; BGE-M3 weights, LanceDB connections, and semaphores leak until process exit. The leak is harmless if uvicorn truly tears the process down (which it does on lifespan failure), but on a startup-retry loop (systemd, docker `restart: on-failure`) the partial cleanup can compound.
- **Why it matters:** The m7 synthesis D5 chose to keep `NotebooksStore` separate from `Resources` precisely because the UI surface is HTTP-only and shouldn't entangle with ML resources. That decision is correct; the implementation accidentally created a lifecycle-ordering bug as a side-effect. The fix is one indentation level.
- **Proposed fix:** Wrap the `NotebooksStore.open` call in a try/except that calls `await resources.shutdown()` before re-raising — or, more elegantly, move the `NotebooksStore.open` call INTO the existing try/finally:
  ```python
  try:
      app.state.notebooks_store = await NotebooksStore.open(
          config.notebooks_db_path
      )
      mcp_server = getattr(app.state, "mcp_server", None)
      if mcp_server is not None:
          async with mcp_server.session_manager.run():
              yield
      else:
          yield
  finally:
      # existing close logic; both notebooks_store and resources cleaned up
      ...
  ```
- **Regression guard:** Add a test in `tests/test_main_lifespan.py` (or similar) that monkeypatches `NotebooksStore.open` to raise and asserts `Resources.shutdown` is invoked exactly once. Pseudocode:
  ```python
  shutdown_called = False
  async def fake_shutdown(): nonlocal shutdown_called; shutdown_called = True
  monkeypatch.setattr(Resources, "shutdown", fake_shutdown)
  monkeypatch.setattr(NotebooksStore, "open", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
  with pytest.raises(OSError):
      with TestClient(create_app(cfg)) as _: pass
  assert shutdown_called
  ```

---

### F3 — POST mkdir-failure leaves SQLite row + missing dir → permanent 409

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/routes/notebooks.py:233-253`
- **What:** The handler INSERTs the SQLite row first (line 234), then `mkdir`s the on-disk directory (line 253). If the mkdir raises (permission denied, disk full, parent-directory race, filesystem readonly), the SQLite row is already committed but the on-disk directory is missing. Subsequent POSTs with the same slug return 409 ("already exists"), but the on-disk dir the operator's later tools expect is NOT there. The operator has to manually `DELETE /ui/api/notebooks/<slug>` (which is metadata-only, succeeds without checking disk state) and then re-POST. The implementer documented the ordering rationale ("AFTER the SQLite INSERT so a constraint violation doesn't leave an orphan directory") but did not address the dual failure mode.
- **Why it matters:** This is a low-frequency edge case on a single-user workstation but it leaves the user stuck with an unhelpful error ("already exists") when the truth is "row exists but disk is broken." The fix is a 5-line try/except.
- **Proposed fix:** Wrap the `mkdir` call:
  ```python
  try:
      nb_dir.mkdir(parents=True, exist_ok=True)
  except OSError as e:
      # Rollback the SQLite INSERT so a retry can succeed.
      await store.delete_notebook(body.slug)
      raise HTTPException(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          detail=f"created notebook row but mkdir failed: {e}",
      ) from e
  ```
- **Regression guard:** Add a test that monkeypatches `pathlib.Path.mkdir` to raise OSError on first call, asserts the response is 5xx, and confirms the SQLite row was rolled back (the next GET returns []). Without the guard, a future change might flip the order without anyone noticing the foot-gun.

---

### F4 — `test_ui_api_path_accepts_cross_site` is a brittle bug-asserting test

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/security/test_sec_fetch_site_carveout.py:112-126`
- **What:** The test asserts that a `Sec-Fetch-Site: cross-site` POST to `/ui/api/notebooks` is NOT 403'd. The test docstring says: "Carve-out applies to ALL Sec-Fetch-Site values on /ui/*, not just same-origin — the rationale is that the UI is not an MCP protocol surface and doesn't need the same browser-mediated-attack defense." This rationale contradicts the threat-model goal of the `SecFetchSiteMiddleware` (Threat 5 DNS-rebinding defense — see F1). The test pins the buggy-broad carve-out behavior, so the fix in F1 will require deleting / inverting this test.
- **Why it matters:** This is the test that, if the F1 fix lands, must be inverted. Calling it out so the rectifier doesn't accidentally "preserve test behavior" by reverting the fix.
- **Proposed fix:** When closing F1, invert this test to `test_ui_api_path_rejects_cross_site` (assert 403 with `sec_fetch_site_forbidden`).
- **Regression guard:** Not applicable — this IS the regression guard, just inverted.

---

### F5 — Inconsistent ordering reference between `state.json` and `app.state.notebooks_store` attribute name

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/notes/milestones/proof-verify-handler-wiring-m7/research-synthesis.md:122` vs `server/main.py:313`
- **What:** The synthesis at line 122 wrote `app.state.notebook_store` (singular); the implementation uses `app.state.notebooks_store` (plural). The code is internally consistent (the lifespan, the closing block, and the FastAPI dependency in `server/routes/notebooks.py:141` all use the plural form). The naming inconsistency is purely a docs/code divergence and has no functional impact.
- **Why it matters:** Future readers of the synthesis will grep for the wrong attribute name. Pure naming nit.
- **Proposed fix:** None required — defer. If touched in a follow-up, fix the synthesis doc to match the code.
- **Regression guard:** None.

---

## What was done well

- **Schema isolation** (`server/notebooks_store.py:7-9`) — separate DB file from `cache_sqlite.py` correctly prevents the Tier1Store's DROP-AND-RECREATE migration from clobbering notebook metadata. FM-6 closure earned its 6 lines of docstring.
- **`PRAGMA foreign_keys = ON` per connection** (`server/notebooks_store.py:107`) — the implementer caught SQLite's per-connection FK quirk explicitly. The pin is single-connection (`self._conn`), so the FK setting genuinely persists for the lifetime of the store. FM-7 cleanly closed.
- **Shared slug validation** (`server/routes/notebooks.py:46-50, 211, 279, 313, 345, 403`) — every handler that accepts a slug calls `validate_slug()` (or `notebook_dir()` which calls it) BEFORE any SQL or filesystem operation. No drift, no copy-pasted regex, and the m6 F1-CRITICAL path-traversal closure flows through correctly.
- **`is_valid_paper_id()` boundary check on `{paper_id:path}`** (`server/routes/notebooks.py:409`) — the `:path` converter could otherwise accept embedded `../`, but the boundary check fires BEFORE the SQL parameter bind. The `\Z` anchor from m1-rect-F3 is correctly reused.
- **Prefix-not-substring carve-out matching** (`server/middleware.py:493-498`) — `path == p or path.startswith(p + "/")` is the exact correct form. The test suite at `tests/security/test_sec_fetch_site_carveout.py:129-167` pins both the `/uiOTHER` and `/evil-ui/foo` rejection cases. FM-3 closure earned.
- **Test-seam monkeypatching of `_now_iso`** (`server/routes/notebooks.py:65-74` + `tests/test_notebook_api.py:78-81`) — factoring the ISO timestamp into a module-level helper for deterministic test assertions is a clean pattern, not a hack.
- **mkdir AFTER INSERT** (`server/routes/notebooks.py:249-253`) — chose orphan-dir-on-INSERT-failure as the better trade vs orphan-row-on-mkdir-failure. The choice is defensible and documented. (F3 is the suggestion for the dual failure mode.)
- **`SecFetchSiteMiddleware.exempt_prefixes` backward-compat default** (`server/middleware.py:462-463`) — `()` default tuple preserves every existing call site without forcing a same-commit migration. Pure-ASGI middleware, no `BaseHTTPMiddleware` introduced.
- **AC #5 verified empirically** — `pytest tests/test_server_tool_schema.py` passes without re-pinning. The byte-stability invariant of `tools/list` is preserved.
- **CHANGES.md + security-threat-model-coverage.md updated** — the threat-coverage doc cites the new test file so the threat-coverage invariant test sees it; the `## Unreleased` entry in CHANGES is detailed and accurate.

## Recommended rectification order

1. **F1** (HIGH) — tighten the carve-out to `{none, same-origin}` only, AND invert F4's test to assert rejection. Single edit in `server/middleware.py`, two edits in the test file. ~25 LOC.
2. **F2** (MEDIUM) — move `NotebooksStore.open` into the existing try/finally so a startup failure here invokes `resources.shutdown`. ~10 LOC.
3. **F3** (MEDIUM) — wrap the POST `mkdir` in try/except that rolls back the SQLite row. ~8 LOC + regression test.
4. **F4** — handled inline with F1.
5. **F5** (LOW) — defer; fix docs on next touch.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

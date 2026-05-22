# Critique — proof-verify-handler-wiring-m7 (merged)

**Critics fired:** adversary (1; infra-safety / oss-scout / frontend-UX
did not fire — no infra paths in diff, no OSS-scout opt-in, no frontend
exists by design).

**Verdict:** SHIP-WITH-FIXES (adversary).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | HIGH | adversary | `/ui/api/*` carve-out bypassed Sec-Fetch-Site entirely — CSRF-able from any other local-app port | CLOSED — carve-out tightened from "bypass" to "relax allow-set to `{none, same-origin}`"; `cross-site` / `same-site` / garbage are still rejected. Bug-asserting test inverted (F4). |
| F2 | MEDIUM | adversary | `Resources` leak if `NotebooksStore.open` raises during lifespan startup (called BEFORE the try/finally) | CLOSED — moved `NotebooksStore.open` INSIDE the existing try block in `server/main.py` so a startup failure here invokes `resources.shutdown` in the finally. |
| F3 | MEDIUM | adversary | POST mkdir-failure leaves SQLite row + missing dir → permanent 409 | CLOSED — wrapped `nb_dir.mkdir(...)` in try/except OSError that calls `store.delete_notebook(slug)` to roll back the row, then raises HTTP 500 with a descriptive message. Regression test pins the rollback invariant. |
| F4 | LOW | adversary | `test_ui_api_path_accepts_cross_site` pinned the buggy F1 behavior | CLOSED — inverted to `test_ui_api_path_rejects_cross_site` (assert 403 with `sec_fetch_site_forbidden`); also added `test_ui_api_path_rejects_same_site` for completeness. |
| F5 | LOW | adversary | Naming drift between synthesis (`app.state.notebook_store` singular) and implementation (`notebooks_store` plural) | **DEFERRED** — pure synthesis-doc nit. The implementation is internally consistent; the synthesis is a historical artifact. Re-opening it for a single-letter correction is anti-pattern (per CLAUDE.md state.json forward-only discipline). Tracked here for visibility. |

## Rectification artifacts

- `server/middleware.py` — `SecFetchSiteMiddleware`:
  - Added `_UI_ALLOWED_VALUES = frozenset({b"none", b"same-origin"})`
    class constant for the exempt-path allow-set.
  - Restructured `__call__` to split the exempt-path branch from
    the default branch:
    - **Exempt path (e.g. `/ui/*`):** pass through if header is
      absent OR in `_UI_ALLOWED_VALUES`; ELSE fall through to the
      standard 403 rejection envelope.
    - **Non-exempt path (e.g. `/mcp`):** pass through ONLY if
      header is absent OR exactly `none` (original behavior).
  - Constructor docstring updated to reflect the new "relax" (not
    "bypass") semantics.
- `server/main.py` — moved `app.state.notebooks_store = await
  NotebooksStore.open(...)` INSIDE the existing try block so a
  startup failure here invokes `resources.shutdown` in the finally
  (F2 closure).
- `server/routes/notebooks.py` — wrapped the `nb_dir.mkdir(...)`
  call in try/except OSError that calls `store.delete_notebook(body.slug)`
  to roll back the SQLite row, then raises HTTP 500 with a
  descriptive message (F3 closure).
- `tests/security/test_sec_fetch_site_carveout.py` — INVERTED
  `test_ui_api_path_accepts_cross_site` → `test_ui_api_path_rejects_cross_site`
  (now asserts 403 + `sec_fetch_site_forbidden`); ADDED
  `test_ui_api_path_rejects_same_site` for parity (F1 + F4
  closure).
- `tests/test_notebook_api.py` — added
  `TestMkdirFailureRollback::test_mkdir_failure_rolls_back_sqlite_row`
  (monkeypatches `Path.mkdir` to OSError on the per-notebook
  directory only; asserts 500 + empty `GET /notebooks` + successful
  retry after `monkeypatch.undo()`) (F3 regression guard).

## Final test count

`make test`: **2357 passed** (+2 from rect — F1 test inversion + F3
mkdir-rollback test; total +61 across m7 feat + rect), 9 skipped, 1
xfailed. Ruff clean.

## Deferred findings

- **F5 (LOW)** — synthesis-doc naming drift (`notebook_store` vs
  `notebooks_store`). Implementation is internally consistent; the
  drift is purely historical. Re-opening a closed synthesis for a
  single-letter correction is anti-pattern.

## Re-verify gate notes

All HIGH + MEDIUM findings re-verified before fixing:

- **F1** (HIGH): empirically reproduced — TestClient POST with
  `Sec-Fetch-Site: cross-site` to `/ui/api/notebooks` returned 201
  before the rect. The carve-out's `if any(prefix match): pass
  through` form bypassed the header check entirely, NOT relaxed
  it. The adversary's reading of the code at
  `server/middleware.py:493-498` was exact.
- **F2** (MEDIUM): inspected `server/main.py:307-326` — confirmed
  `await NotebooksStore.open(...)` was called BEFORE the `try:`
  block at line 321. If `open` raised, the lifespan would exit
  without `resources.shutdown` running.
- **F3** (MEDIUM): inspected `server/routes/notebooks.py:249-253` —
  confirmed `nb_dir.mkdir(parents=True, exist_ok=True)` had no
  try/except around it; an OSError would propagate to FastAPI's
  default 500 handler without rolling back the SQLite INSERT.

Zero findings invalidated. Adversary invalidation rate: **0 / 3
(0%)** (counting HIGH + MEDIUM only — F4 + F5 are LOW and outside
the re-verify gate scope). Well under the 40% threshold.

## Cross-critic agreement

N/A — only one critic fired (adversary). Infra-safety did not fire
(no infra paths in diff). OSS-scout is opt-in only. Frontend-UX
does not apply to arXMCP by design.

## Security threat-model coverage update

The carve-out semantics change (F1 closure) is a real security
improvement and the threat-model coverage doc was updated in the
feat commit to cite the new test file. The doc edit accurately
described the *intended* carve-out behavior (`{none, same-origin}`)
even though the original code did NOT match — the rect closes the
gap so the implementation now matches the doc claim. No follow-up
doc edit needed.

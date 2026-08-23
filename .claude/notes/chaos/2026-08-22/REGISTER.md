# arXMCP macOS desktop app — chaos engineering register

**Run date:** 2026-08-22 · **Target:** `arXMCP.app` (Tauri supervisor + PyInstaller child + FastAPI/htmx UI)
**Commit:** `3ba2d9a` on `main` · **Method:** 5 parallel adversarial agents, read-only on source, no fixes applied

## Totals

| severity | count |
|---|---|
| critical | 3 |
| high | 18 |
| medium | 23 |
| low | 22 |
| info | 34 |
| **total** | **100** |

By lane: supervisor 25 · frontend 23 · packaging 20 · api 18 · data 14.

Raw findings are in `findings-<lane>.jsonl`, one JSON object per line, schema in
`SCHEMA.md`. Every line carries a copy-pasteable `repro` and verbatim `observed`
output. Evidence under `evidence/<lane>/`.

## The headline: the shipped app cannot succeed, and cannot say so

Three findings compose into one fact. A user who double-clicks `arXMCP.app`
today gets **nothing at all**:

1. `CHAOS-PKG-02` — the self-authored launch plan points the data root at an
   empty `~/Library/Application Support/arXMCP`, and the bundle ships no ingest
   path. The child raises `CorpusNotIngestedError: corpus-version.json not
   found`. There is no first-run state of this artifact that can succeed. The
   remedy the error names (`make up-wizard`) does not exist inside a bundle.
2. `CHAOS-PKG-01` / `CHAOS-SUP-07` / `CHAOS-SUP-11` — the failure is invisible.
   `tauri.conf.json` declares `app.windows: []`, and every `fail()` path is
   `eprintln!` + `exit`. No Dock icon, no window, no dialog; `open` exits 0.
   The only trace is an NDJSON file in `~/Library/Application Support/arXMCP/logs/`.
3. `CHAOS-SUP-10` — that log is truncated on every launch, so the second
   double-click destroys the diagnostic from the first.

Fixing the corpus bootstrap without fixing the silence leaves the next failure
equally undiagnosable. Both halves are load-bearing.

## Theme 2: the UI's entire error-reporting layer is dead code

`CHAOS-FE-01` is the single highest-leverage frontend fix. The app's own CSP at
`server/middleware.py:172` sets `script-src 'self' 'unsafe-inline'` with no
`'unsafe-eval'`. htmx implements `hx-on::` through `new Function()`, which needs
`unsafe-eval`. Every browser load throws:

```
EvalError: Evaluating a string as JavaScript violates the following
Content Security Policy directive          htmx.min.js:2:44684
```

That kills all 12 `hx-on::` handlers — 7 `hx-on::response-error` and 5
`hx-on::after-request`, counted independently across `index.html` (3) and
`notebook_detail.html` (9). The UI detects errors correctly and then silently
drops them: `CHAOS-FE-02` (422/409 on create shows nothing) and much of
`CHAOS-FE-03` are downstream of this one line.

**Caveat that changes the fix:** repairing the CSP does *not* fix
`CHAOS-FE-03`. htmx fires `htmx:sendError` for connection failures, and no
handler listens for that event at all. Backend death stays invisible until
someone writes that listener.

## Theme 3: the containment story is inverted

`apps/desktop/README.md` documents a careful payload-containment model —
`resolve_inside`, symlink refusal, component-wise containment, a digest check.
All of it is real. All of it is reachable **only from the self-authored arm**.

- `CHAOS-PKG-06` / `CHAOS-SUP-03` (same defect, two lanes) — when
  `ARXMCP_DESKTOP_LAUNCH_PLAN` is set, `load_plan` at `main.rs:143-158` does
  `fs::read` → `serde_json` → `validate_plan` → return. It never calls
  `child_payload_candidates` or `resolve_inside`. Proved by executing
  `/usr/bin/touch` with attacker-chosen args, against the signed release bundle.
  The comment at `main.rs:145` says *"The self-authored plan is NOT trusted more
  than an external one"* — true, and backwards. The external plan is trusted
  **more**, because it skips the containment the self-authored arm submits to.
- `CHAOS-PKG-07` — the digest check is not a tamper check. `lifecycle.rs:109`
  hashes `plan.identity_file`, and the crate's own test at `main.rs:892` asserts
  `identity_file == child_argv[0]`. It hashes the file it is about to exec.
- `CHAOS-PKG-08` — a one-byte flip in the signed child Mach-O still executes.
  `codesign` catches every tamper; nothing runs `codesign` at launch. The
  5,300-file payload has no runtime integrity check.

## Theme 4: silent-wrong-answer failures in the data layer

Failures that a user cannot distinguish from working software:

- `CHAOS-DATA-01` — zero or truncate every LanceDB data fragment and the table
  still opens, `count_rows()` still returns the full 4279 (fragment metadata
  only), and the health path reports `DegradedState=None`. The server boots
  **READY** on a corpus that cannot answer a single query. A one-row smoke read
  at startup catches every case tested.
- `CHAOS-DATA-02` — the shipped `var/arxmcp/index/lancedb-staging` marker claims
  `chunk_count: 105 / paper_count: 1` against a table holding 4279 rows. At the
  5% tolerance that corpus is `degraded(chunk_count_diverged)` on every boot,
  desensitising the one signal that would catch real divergence.
- `CHAOS-DATA-05` — the marker's `embedder_version` is never compared against
  the loaded model, so a model swap yields silent wrong-vector-space retrieval.

## Cross-lane duplicates (merged, both ids kept)

| defect | ids |
|---|---|
| env launch-plan arm bypasses containment | `CHAOS-PKG-06` = `CHAOS-SUP-03` |
| machine-global single-instance socket kills other data roots | `CHAOS-PKG-09` = `CHAOS-SUP-04` |
| frozen child aborts on the startup-failure path | `CHAOS-PKG-03` = `CHAOS-SUP-14` |
| cold-start failure is user-invisible | `CHAOS-PKG-01` ≈ `CHAOS-SUP-07` ≈ `CHAOS-SUP-11` |

## What held up

Recorded so a future run can tell *tested-and-clean* from *never-looked-at*.

- **XSS / SSTI — clean.** Jinja autoescape verified empirically *and* statically;
  zero `|safe`, zero `Markup(`, every f-string fragment `html.escape`d.
- **Path traversal — clean.** 404 on all 7 encodings against `/static/` and slugs.
- **Server robustness — clean.** 200-concurrent load, slowloris, chunked
  overflow, malformed JSON, config hostility, SIGTERM drain: no crashes, hangs,
  500s, or orphans. CSRF/DNS-rebind properly defended (Origin 403 / Host 421 /
  Sec-Fetch-Site 403). Startup token compared with `hmac.compare_digest`.
- **Contract fuzzing — clean.** All 17 mutations rejected bounded, including a
  depth bomb, missing-LF, and concatenated frames.
- **Restart storm — clean.** 10× start/quit leaked no fds, temp dirs, ports, or
  processes.
- **Identifier collisions — clean.** No reachable `paper_id` flatten collision.
- **Bundle determinism — clean.** Both `assembly-report.json` claims verified
  against the artifact with no drift. Symlinked payload root refused correctly.

## Coverage gaps — untested, not clean

1. **MCP handler-level input validation.** Bootstrap mode short-circuits every
   tool to a stub envelope *before* the handler runs, so traversal / NUL /
   injection tests in `paper_id` and `chunk_id` never reached real code.
   `paper_id` validation is handler-level, not schema-level, so hostile ids do
   pass the JSON-schema gate. Needs a re-run against a live corpus. (`CHAOS-API-11`)
2. **Populated-corpus UI.** The notebook LanceDB dirs are empty on this
   checkout, so every populated search path in the frontend went untested.
3. **`--dry-run` write honesty.** `NOTEBOOKS_BASE` resolves at import from
   `ApplicationPaths`, so redirecting it required either writing under
   `var/arxmcp/` or editing `tools/` — both forbidden. Separately:
   `notebook_ingest.py` and `notebook_pdf_parse.py` have **no `--dry-run` at all**.
4. **BM25/dense skew, disk pressure, model failure modes, freshness mtimes** —
   timeboxed out of the data lane. BM25 skew is the highest-value next target.
5. **`hdiutil` read-only-volume launch** and the `LSMinimumSystemVersion` /
   identifier `Info.plist` arms — LaunchServices caching confounded them.

## Two corrections to prior project knowledge

- **The "3-calls-per-session limit" does not exist.** Real caps are **30**
  (`search_papers`) and **100** (`get_chunk`), boundary exact, clean
  `RETRIEVAL_CAP_REACHED` envelope on the 31st. The new-session-per-call bypass
  is real and marked deliberately non-security in `server/session.py`.
- **`server/session.py:24-31`'s docstring claims a second bypass** (omit
  `Mcp-Session-Id`) that is unreachable — the MCP layer 400s first.
  (`CHAOS-API-07`)

## Tracking

All **66** non-info findings are filed as GitHub issues **#425–#490** under epic **[#424](https://github.com/chris-dare-dev/arXMCP/issues/424)**. The 34 `info` lines are not filed — they are verified-clean passes and deliberately untested classes, kept as the record of what was looked at.

## Suggested fix order

1. `CHAOS-PKG-02` + `CHAOS-PKG-01` — give the bundle a first-run path that can
   succeed, and a window (or an `NSAlert`) that can report when it does not.
2. `CHAOS-FE-01` — the CSP/htmx conflict. One line restores 12 handlers.
   Then add an `htmx:sendError` listener for `CHAOS-FE-03`.
3. `CHAOS-PKG-06` — apply `resolve_inside` + the payload-root check to the env
   arm, or compile the env arm out of release builds.
4. `CHAOS-DATA-01` — a one-row smoke read at startup, so READY means answerable.
5. `CHAOS-SUP-05` / `CHAOS-SUP-06` — a child-death watchdog and a bound on the
   281 s SIGSTOP hang.

## Side effect left on disk

`~/Library/Application Support/arXMCP/` (logs + lock only), created by the app's
own first run during testing. `var/arxmcp/` is untouched — every lane worked on
`cp -Rc` APFS clones, mtimes unchanged. No processes left running; ports
7801-7805 and 7733 free.

---

## Full findings

### CRITICAL — 3

| issue | id | area | title | code ref |
|---|---|---|---|---|
| [#425](https://github.com/chris-dare-dev/arXMCP/issues/425) | `CHAOS-PKG-01` | packaging | Double-clicked .app dies in ~5-7s with zero user-visible feedback | `apps/desktop/crates/supervisor/src/main.rs:122 (fail: eprintln!+exit(2` |
| [#426](https://github.com/chris-dare-dev/arXMCP/issues/426) | `CHAOS-PKG-02` | server | First run on a clean machine always fails: cold-start corpus refusal | `apps/desktop/crates/supervisor/src/main.rs:508-527 (self_authored_plan` |
| [#427](https://github.com/chris-dare-dev/arXMCP/issues/427) | `CHAOS-PKG-06` | supervisor | ARXMCP_DESKTOP_LAUNCH_PLAN arm spawns any absolute binary, no containment | `apps/desktop/crates/supervisor/src/main.rs:151-157 (load_plan environm` |

### HIGH — 18

| issue | id | area | title | code ref |
|---|---|---|---|---|
| [#428](https://github.com/chris-dare-dev/arXMCP/issues/428) | `CHAOS-DATA-01` | data | Corrupt LanceDB fragments: table opens clean, count_rows lies, queries die | `server/resources.py:592` |
| [#429](https://github.com/chris-dare-dev/arXMCP/issues/429) | `CHAOS-DATA-02` | data | Shipped lancedb-staging marker says 105 chunks; table actually holds 4279 | `server/resources.py:626` |
| [#430](https://github.com/chris-dare-dev/arXMCP/issues/430) | `CHAOS-DATA-03` | server | Corrupt/locked/read-only Tier-1 cache DB is FATAL to startup and to corpus rebind | `server/resources.py:868` |
| [#431](https://github.com/chris-dare-dev/arXMCP/issues/431) | `CHAOS-FE-01` | frontend | All 12 hx-on:: handlers are dead: app CSP blocks htmx's eval | `server/middleware.py:170-173 (CONTENT_SECURITY_POLICY_UI) vs server/fr` |
| [#432](https://github.com/chris-dare-dev/arXMCP/issues/432) | `CHAOS-FE-02` | frontend | Server 4xx on create notebook shows nothing at all to the user | `server/frontend/templates/index.html:39,83` |
| [#433](https://github.com/chris-dare-dev/arXMCP/issues/433) | `CHAOS-FE-03` | frontend | Backend death is invisible: stale status badge, silent no-op controls | `server/frontend/templates/base.html:133` |
| [#434](https://github.com/chris-dare-dev/arXMCP/issues/434) | `CHAOS-PKG-04` | packaging | Quarantined bundle shows a 'Move to Trash' Gatekeeper dialog, undocumented | `—` |
| [#435](https://github.com/chris-dare-dev/arXMCP/issues/435) | `CHAOS-PKG-07` | supervisor | Identity digest check cannot detect payload tampering: it hashes the file it launches | `apps/desktop/crates/supervisor/src/lifecycle.rs:109-113, :485-489; app` |
| [#436](https://github.com/chris-dare-dev/arXMCP/issues/436) | `CHAOS-PKG-08` | packaging | One-byte flip in the signed child Mach-O still executes; no runtime seal check | `apps/desktop/crates/supervisor/src/main.rs (no codesign/verification c` |
| [#437](https://github.com/chris-dare-dev/arXMCP/issues/437) | `CHAOS-PKG-09` | supervisor | Machine-global single-instance socket silently kills launches from other data roots | `apps/desktop/crates/supervisor/src/main.rs:606-612 (SINGLE_INSTANCE_SO` |
| [#438](https://github.com/chris-dare-dev/arXMCP/issues/438) | `CHAOS-SUP-01` | supervisor | Live startup token persisted verbatim to logs/desktop-child.log (no scrub) | `apps/desktop/crates/supervisor/src/lifecycle.rs:150-162` |
| [#439](https://github.com/chris-dare-dev/arXMCP/issues/439) | `CHAOS-SUP-02` | supervisor | redact.rs scrub defeated by case shift: full live token in the event log | `apps/desktop/crates/supervisor/src/redact.rs:29-34 (sole caller lifecy` |
| [#440](https://github.com/chris-dare-dev/arXMCP/issues/440) | `CHAOS-SUP-03` | supervisor | Launch-plan env test seam ships enabled in the signed .app: arbitrary child exec | `apps/desktop/crates/supervisor/src/main.rs:145-160 (load_plan) and :52` |
| [#441](https://github.com/chris-dare-dev/arXMCP/issues/441) | `CHAOS-SUP-04` | supervisor | 2nd supervisor on a DIFFERENT data root exits 0 after logging owns_lock:true | `apps/desktop/crates/supervisor/src/main.rs:578-593 (fs2 lock), :597 (s` |
| [#442](https://github.com/chris-dare-dev/arXMCP/issues/442) | `CHAOS-SUP-05` | supervisor | SIGSTOP'd child hangs the supervisor 281s with zero events and no user feedback | `apps/desktop/crates/supervisor/src/lifecycle.rs:29 (BOUND_TIMEOUT), :4` |
| [#443](https://github.com/chris-dare-dev/arXMCP/issues/443) | `CHAOS-SUP-06` | supervisor | No child-death watchdog in production mode: dead server, live window, no error | `apps/desktop/crates/supervisor/src/lifecycle.rs:78-85` |
| [#444](https://github.com/chris-dare-dev/arXMCP/issues/444) | `CHAOS-SUP-07` | packaging | Assembled .app cold-start fails invisibly: exit 1, no window, no dialog | `apps/desktop/crates/supervisor/src/main.rs:129-132 (fail); lifecycle.r` |
| [#445](https://github.com/chris-dare-dev/arXMCP/issues/445) | `CHAOS-SUP-08` | supervisor | SIGTERM to supervisor skips RunEvent::Exit: no shutdown frame, grace or reap | `apps/desktop/crates/supervisor/src/main.rs:757-766 (RunEvent::Exit)` |

### MEDIUM — 23

| issue | id | area | title | code ref |
|---|---|---|---|---|
| [#446](https://github.com/chris-dare-dev/arXMCP/issues/446) | `CHAOS-API-01` | server | No HTTP auth on any route in standalone/make-up/Docker boot; startup token gates only GET /readyz and only under desktop-child | `server/desktop_child.py:121 (ReadyzStartupTokenMiddleware); server/mai` |
| [#447](https://github.com/chris-dare-dev/arXMCP/issues/447) | `CHAOS-DATA-04` | data | Marker paper_count is never reconciled against the table (9999 accepted silently) | `server/corpus_manifest.py:203` |
| [#448](https://github.com/chris-dare-dev/arXMCP/issues/448) | `CHAOS-DATA-05` | server | Marker embedder_version/chunker_version never checked against the loaded model | `server/resources.py:557` |
| [#449](https://github.com/chris-dare-dev/arXMCP/issues/449) | `CHAOS-DATA-06` | data | Marker version has no upper bound: version 999999 over a 181-version dataset accepted | `server/corpus.py:473` |
| [#450](https://github.com/chris-dare-dev/arXMCP/issues/450) | `CHAOS-FE-04` | frontend | After a successful create the empty-state row stays and the count is stale | `server/frontend/templates/index.html:38, index.html:86 (h2 count)` |
| [#451](https://github.com/chris-dare-dev/arXMCP/issues/451) | `CHAOS-FE-05` | frontend | Create form is never reset; a second click silently 409s | `server/frontend/templates/index.html:38` |
| [#452](https://github.com/chris-dare-dev/arXMCP/issues/452) | `CHAOS-FE-06` | frontend | slug pattern attribute is an invalid regex; client-side validation is off | `server/frontend/templates/index.html:44` |
| [#453](https://github.com/chris-dare-dev/arXMCP/issues/453) | `CHAOS-FE-07` | frontend | View-transition InvalidStateError fires on every htmx swap, forever | `server/frontend/templates/base.html:66-75` |
| [#454](https://github.com/chris-dare-dev/arXMCP/issues/454) | `CHAOS-FE-08` | frontend | Whole page scrolls horizontally on mobile (375px) from the LanceDB path | `server/frontend/templates/notebook_detail.html (LanceDB path <dd>) + s` |
| [#455](https://github.com/chris-dare-dev/arXMCP/issues/455) | `CHAOS-FE-09` | frontend | Long unbroken token in a topic breaks desktop layout (1280px h-scroll) | `server/frontend/templates/notebook_detail.html:361 (#topic-block) + ap` |
| [#456](https://github.com/chris-dare-dev/arXMCP/issues/456) | `CHAOS-FE-10` | frontend | 404 / 422 for a notebook URL renders raw JSON, not an HTML page | `server/routes/ui.py:424-496 (ui_notebook_detail raises HTTPException)` |
| [#457](https://github.com/chris-dare-dev/arXMCP/issues/457) | `CHAOS-FE-11` | frontend | Unbounded 2s polling forever on a never-ingested notebook | `server/frontend/templates/notebook_detail.html:298,544 + base.html:133` |
| [#458](https://github.com/chris-dare-dev/arXMCP/issues/458) | `CHAOS-PKG-03` | packaging | Frozen child dies with a Fatal Python error on the startup-failure path | `server/desktop_child.py (stdin reader teardown)` |
| [#459](https://github.com/chris-dare-dev/arXMCP/issues/459) | `CHAOS-PKG-10` | supervisor | Hardlinked child_argv[0] escapes payload containment; symlink is refused | `apps/desktop/crates/supervisor/src/main.rs:272-293 (resolve_inside)` |
| [#460](https://github.com/chris-dare-dev/arXMCP/issues/460) | `CHAOS-PKG-11` | supervisor | chmod 000 on the payload dir reports 'bundled child executable missing' | `apps/desktop/crates/supervisor/src/main.rs:286-288` |
| [#461](https://github.com/chris-dare-dev/arXMCP/issues/461) | `CHAOS-PKG-12` | supervisor | Exec bit stripped from child: plan validates, launch fails silently at spawn | `apps/desktop/crates/supervisor/src/main.rs:272-293; lifecycle.rs (chil` |
| [#462](https://github.com/chris-dare-dev/arXMCP/issues/462) | `CHAOS-PKG-14` | supervisor | 'launch plan malformed' is the single message for 13+ distinct failure shapes | `apps/desktop/crates/supervisor/src/main.rs:151-157` |
| [#463](https://github.com/chris-dare-dev/arXMCP/issues/463) | `CHAOS-SUP-09` | supervisor | Child that dies outside shutdown_child is never reaped: permanent zombie | `apps/desktop/crates/supervisor/src/lifecycle.rs:415-436` |
| [#464](https://github.com/chris-dare-dev/arXMCP/issues/464) | `CHAOS-SUP-10` | supervisor | logs/desktop-child.log truncated every launch, destroying the crash diagnostic | `apps/desktop/crates/supervisor/src/lifecycle.rs:150-153 vs events.rs:5` |
| [#465](https://github.com/chris-dare-dev/arXMCP/issues/465) | `CHAOS-SUP-11` | supervisor | Every fail() path is stderr-only on a windowless app: refusals are invisible | `apps/desktop/crates/supervisor/src/main.rs:129-132; apps/desktop/crate` |
| [#466](https://github.com/chris-dare-dev/arXMCP/issues/466) | `CHAOS-SUP-12` | supervisor | --print-child-plan writes any path given: unvalidated arbitrary file overwrite | `apps/desktop/crates/supervisor/src/main.rs:466-489 (emit_child_plan_pr` |
| [#467](https://github.com/chris-dare-dev/arXMCP/issues/467) | `CHAOS-SUP-13` | supervisor | Grandchild survives the full grace/TERM/KILL/reap ladder, reparented to PID 1 | `apps/desktop/crates/supervisor/src/process_control.rs:11-18` |
| [#468](https://github.com/chris-dare-dev/arXMCP/issues/468) | `CHAOS-SUP-14` | server | Frozen child aborts at interpreter shutdown instead of exiting cleanly | `server/desktop_child.py:254-258 (_watch_stdin), started at :325` |

### LOW — 22

| issue | id | area | title | code ref |
|---|---|---|---|---|
| [#469](https://github.com/chris-dare-dev/arXMCP/issues/469) | `CHAOS-API-02` | server | GET /ui/api/notebooks leaks absolute filesystem paths unauthenticated (home dir, source tree, stale pytest tmp path) | `server/routes/notebooks.py:313 (GET /notebooks handler)` |
| [#470](https://github.com/chris-dare-dev/arXMCP/issues/470) | `CHAOS-API-03` | server | /metrics/ ASGI app answers 200 to every HTTP verb incl TRACE/DELETE/PATCH/PUT/HEAD/OPTIONS | `server/main.py:900 (app.mount('/metrics', metrics_wrapper))` |
| [#471](https://github.com/chris-dare-dev/arXMCP/issues/471) | `CHAOS-API-04` | server | No inbound URL-length or header-size cap: 60 KB URL and 90 KB header value both accepted | `server/middleware.py:821 (RequestBodySizeLimitMiddleware — body only)` |
| [#472](https://github.com/chris-dare-dev/arXMCP/issues/472) | `CHAOS-API-05` | server | MCP validation/error responses leak internal pydantic + handler class names | `server/tools.py (FastMCP tool wrappers); mcp streamable_http layer` |
| [#473](https://github.com/chris-dare-dev/arXMCP/issues/473) | `CHAOS-API-06` | server | MCP initialize accepts garbage/wrong-type protocolVersion (int 12345, '9999-99-99') with HTTP 200 | `mcp streamable_http initialize handler (library)` |
| [#474](https://github.com/chris-dare-dev/arXMCP/issues/474) | `CHAOS-API-07` | server | session.py docstring claims omitting Mcp-Session-Id skips cap enforcement ('known bypass'); MCP layer 400s first, making the comment stale/misleading | `server/session.py:24-31 (docstring); server/middleware.py:1069 (Sessio` |
| [#475](https://github.com/chris-dare-dev/arXMCP/issues/475) | `CHAOS-API-08` | server | Startup config errors dump full Python traceback; 0.0.0.0 rejection leaks entire Config dict incl. data_dir path | `server/main.py:449 (_scan raise ValueError); server/config.py bind_hos` |
| [#476](https://github.com/chris-dare-dev/arXMCP/issues/476) | `CHAOS-DATA-07` | server | LanceDB errors leak the upstream CI build machine's Rust source paths to operators | `server/corpus.py:175` |
| [#477](https://github.com/chris-dare-dev/arXMCP/issues/477) | `CHAOS-DATA-08` | ingest | notebook_pdf_parse leaves an empty parsed/<flat>/_mineru/ dir behind on every failure | `tools/notebook_pdf_parse.py:120` |
| [#478](https://github.com/chris-dare-dev/arXMCP/issues/478) | `CHAOS-FE-12` | frontend | App root / returns raw JSON 404 instead of redirecting to /ui/ | `server/main.py:865 (ui_router mounted at /ui with no root redirect)` |
| [#479](https://github.com/chris-dare-dev/arXMCP/issues/479) | `CHAOS-FE-13` | frontend | Absolute host filesystem path (incl. user home) shown in the notebook UI | `server/frontend/templates/notebook_detail.html (LanceDB path <dd>)` |
| [#480](https://github.com/chris-dare-dev/arXMCP/issues/480) | `CHAOS-FE-14` | frontend | Empty papers table renders a header row under the 'no papers' message | `server/frontend/templates/notebook_detail.html:196-211` |
| [#481](https://github.com/chris-dare-dev/arXMCP/issues/481) | `CHAOS-FE-15` | frontend | Slug input has pattern but no title, so the browser hint is generic | `server/frontend/templates/index.html:43-44` |
| [#482](https://github.com/chris-dare-dev/arXMCP/issues/482) | `CHAOS-FE-16` | frontend | No hx-push-url anywhere: htmx swaps never change the URL | `server/frontend/templates/index.html, notebook_detail.html` |
| [#483](https://github.com/chris-dare-dev/arXMCP/issues/483) | `CHAOS-FE-17` | frontend | UI CSP allows script-src 'unsafe-inline' | `server/middleware.py:170-176` |
| [#484](https://github.com/chris-dare-dev/arXMCP/issues/484) | `CHAOS-PKG-13` | supervisor | Deleting arxmcp-desktop-probe, _internal Mach-O, or _CodeSignature is undetected at plan time | `apps/desktop/crates/supervisor/src/main.rs:436-472 (child_plan_probe)` |
| [#485](https://github.com/chris-dare-dev/arXMCP/issues/485) | `CHAOS-PKG-15` | supervisor | Data-root derivation accepts a regular file or a nonexistent path as $HOME | `apps/desktop/crates/supervisor/src/main.rs:210-233, :645-667` |
| [#486](https://github.com/chris-dare-dev/arXMCP/issues/486) | `CHAOS-SUP-15` | supervisor | Post-bound stdout drain is unbounded: a spewing child is read forever | `apps/desktop/crates/supervisor/src/lifecycle.rs:231-244` |
| [#487](https://github.com/chris-dare-dev/arXMCP/issues/487) | `CHAOS-SUP-16` | supervisor | Raw child-controlled bytes, incl. NUL, persisted into the event log | `apps/desktop/crates/supervisor/src/lifecycle.rs:254-258` |
| [#488](https://github.com/chris-dare-dev/arXMCP/issues/488) | `CHAOS-SUP-17` | supervisor | Supervisor log files are created world-readable (0644) | `apps/desktop/crates/supervisor/src/lifecycle.rs:152; apps/desktop/crat` |
| [#489](https://github.com/chris-dare-dev/arXMCP/issues/489) | `CHAOS-SUP-18` | supervisor | Spurious duplicate-activation recorded during strictly sequential restarts | `apps/desktop/crates/supervisor/src/main.rs:597, :700-706` |
| [#490](https://github.com/chris-dare-dev/arXMCP/issues/490) | `CHAOS-SUP-19` | supervisor | await_bound leaks its blocked reader thread on every timeout path | `apps/desktop/crates/supervisor/src/lifecycle.rs:225-250` |

### INFO — 34 (verified-clean passes, untested classes, recorded behaviour — not filed)

| id | title |
|---|---|
| `CHAOS-API-09` | 3-calls-per-session limit is STALE: real caps are 30 (search_papers) / 100 (get_chunk); boundary exact, error shape clean |
| `CHAOS-API-10` | Session retrieval cap trivially bypassed by new-session-per-call (counter resets to zero) |
| `CHAOS-API-11` | Bootstrap mode masks handler-level input validation — traversal/injection/NUL in paper_id/chunk_id all short-circuit to the stub envelope |
| `CHAOS-API-12` | Duplicate initialize on an already-initialized MCP session returns 200 (re-init allowed) |
| `CHAOS-API-13` | no-repro: HTTP-layer abuse |
| `CHAOS-API-14` | no-repro: Concurrency / load / lifecycle |
| `CHAOS-API-15` | no-repro: Degraded-state / health honesty |
| `CHAOS-API-16` | no-repro: Config hostility |
| `CHAOS-API-17` | no-repro: Information disclosure via schema / OpenAPI |
| `CHAOS-API-18` | no-repro: Auth timing + CSRF/DNS-rebind defenses |
| `CHAOS-DATA-09` | verified-fixed: notebook_pdf_parse.py exit-code contract now returns 1 on parse failure |
| `CHAOS-DATA-10` | no-repro: path hostility on identifiers — no reachable paper_id path collision |
| `CHAOS-DATA-11` | no-repro: absent / empty / invalid-JSON corpus-version.json all handled cleanly |
| `CHAOS-DATA-12` | no-repro: deleted LanceDB tip manifest fails with a precise, actionable message |
| `CHAOS-DATA-13` | untested: --dry-run honesty — only notebook_textbook_ingest.py has the flag at all |
| `CHAOS-DATA-14` | untested: BM25/dense skew, concurrency, disk pressure, model failure, freshness mtimes |
| `CHAOS-FE-18` | no-repro: XSS / template injection |
| `CHAOS-FE-19` | no-repro: path traversal via /ui/static and via slug |
| `CHAOS-FE-20` | no-repro: asset integrity (all static assets 200, htmx 2.0.10) |
| `CHAOS-FE-21` | no-repro: accessibility basics (labels, alt, headings, focus, landmarks) |
| `CHAOS-FE-22` | no-repro: light/dark theming and desktop/tablet layout |
| `CHAOS-FE-23` | First-run experience in bootstrap mode is reasonable but the badge is alarming |
| `CHAOS-PKG-05` | Confirmed: ad-hoc seal verifies locally and is rejected by spctl |
| `CHAOS-PKG-16` | Determinism claims in assembly-report.json VERIFIED against the artifact on disk |
| `CHAOS-PKG-17` | no-repro: path hostility (spaces, unicode, emoji, 250-char, trailing dot, #/?) |
| `CHAOS-PKG-18` | no-repro: Info.plist damage is caught by LaunchServices, but results are cache-confounded |
| `CHAOS-PKG-19` | no-repro: symlinked payload root refusal behaves exactly as the README documents |
| `CHAOS-PKG-20` | no-repro: read-only Contents/Resources and read-only-volume launch |
| `CHAOS-SUP-20` | no-repro: startup-token leakage via child argv, environment, or ps |
| `CHAOS-SUP-21` | no-repro: supervisor SIGKILL with a cooperating child - no orphan, no port leak |
| `CHAOS-SUP-22` | no-repro: 10x restart storm - no leaked processes, ports, sockets or temp dirs |
| `CHAOS-SUP-23` | no-repro: contract fuzzing - 17 malformed bound frames all rejected bounded |
| `CHAOS-SUP-24` | no-repro: port squatting / bind TOCTOU is not reachable in this design |
| `CHAOS-SUP-25` | no-repro: misbehaving-child exit paths are detected and reaped correctly |

# Critique — E14_S03

**Critic:** adversary
**Generated:** 2026-05-16T04:55:09Z
**Commit range:** 7cf092e..3395d0e
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES — one CRITICAL bind-mount-path bug guarantees
  the brief AC #1 fails out of the box; everything else is contained.
- The compose file's `./var/arxmcp/observability/phoenix:/mnt/data`
  resolves to `infra/observability/var/arxmcp/observability/phoenix`
  (Compose v2 resolves relative paths against the COMPOSE FILE
  directory), NOT the `var/arxmcp/observability/phoenix/` that `make
  bootstrap` creates. Phoenix will write its SQLite trace store to an
  auto-created stray subtree inside `infra/`.
- Findings: 1 CRITICAL, 2 HIGH, 5 MEDIUM, 4 LOW.
- Highest-risk file: `infra/observability/phoenix-compose.yml:76`.
- Cache byte-stability: clean. `openinference.span.kind` lives on OTel
  spans only — `structuredContent` / `tools/list` bytes are untouched,
  `TOOL_SCHEMA_VERSION` stayed at 6, schema-hash test still passes.
- `test_compose_file_parses` runs `config --quiet` WITHOUT
  `--profile phoenix`, so the validator sees a services-empty file
  (`name: observability\nservices: {}`) and trivially returns 0 —
  the test passes for a compose file with no Phoenix service at all.
- `restart: unless-stopped` re-launches Phoenix at host reboot, which
  means session-id-bearing spans get re-served on 127.0.0.1:6006
  silently after every reboot on a shared workstation.
- Cross-axis pattern: the relative-path resolution bug AND the
  profile-stripped `config --quiet` smoke test both indicate the
  validation surface treats the compose file as inert text rather
  than as an executable artifact. The runbook's claim that the
  smoke test "validates the FULL Compose Spec semantics" is wrong.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Bind-mount path resolves under `infra/`, not repo root

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** infra/observability/phoenix-compose.yml:76
- **What:** The compose spec uses `./var/arxmcp/observability/phoenix:/mnt/data`. Compose v2 resolves relative bind-mount paths against the COMPOSE FILE's directory, not the operator's CWD. `docker compose -f infra/observability/phoenix-compose.yml --profile phoenix config` confirms the resolved source is `/Users/.../arXMCP/infra/observability/var/arxmcp/observability/phoenix` (verified live in this critique run). `make bootstrap` creates `/Users/.../arXMCP/var/arxmcp/observability/phoenix` — a DIFFERENT directory.
- **Why it matters:** Phoenix on first start will silently auto-create a stray `infra/observability/var/arxmcp/observability/phoenix/` subtree (Compose's `create_host_path: true` is the default), write its SQLite trace store there, NOT under the project's gitignored `var/arxmcp/` root. Three downstream consequences: (a) the runbook + `make clean` documentation lie — `./var/arxmcp/observability/phoenix/` will be empty on the operator's filesystem after a successful Phoenix run; (b) `infra/` is NOT in `.gitignore` for `var/`, so a future `git add infra/` could accidentally stage trace data containing `mcp.session_id` values; (c) the `make bootstrap` mkdir is dead code — it creates a directory nothing actually uses. AC #1 ("starts Phoenix without error") is technically met by Docker auto-creating the wrong path, but the operator's mental model is wrong from the start.
- **Proposed fix:** Replace line 76 with an absolute path resolved at compose time (`${PWD}/var/arxmcp/observability/phoenix:/mnt/data` IF the runbook commits to `cd $REPO_ROOT` before invocation, OR a path like `../../var/arxmcp/observability/phoenix:/mnt/data` keyed to the compose-file location). The `../../` form is the more robust choice — it's stable regardless of CWD because Compose resolves relative-to-file. Add a regression-guard test that `docker compose config` resolves the bind-mount `source:` to a path with `arXMCP/var/arxmcp/observability/phoenix` as its tail (NOT `arXMCP/infra/observability/var/...`).
- **Regression guard:** New test in `tests/test_compose_phoenix.py` that runs `docker compose -f <path> --profile phoenix config` (with `--profile`!) and asserts the resolved volume source ends with `/var/arxmcp/observability/phoenix` AND does NOT contain `/infra/observability/var/`.

### F2 — `config --quiet` smoke test passes for a services-empty file

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_compose_phoenix.py:118
- **What:** `test_compose_file_parses` runs `docker compose -f ... config --quiet` WITHOUT `--profile phoenix`. The Phoenix service is gated behind `profiles: ["phoenix"]`, so the post-filter compose graph is `services: {}` (verified live: `docker compose -f infra/observability/phoenix-compose.yml config` returns `name: observability\nservices: {}`). The validator returns 0 because there's nothing left to validate.
- **Why it matters:** The runbook's docstring says the test "validates the FULL Compose Spec semantics" — it does not. A typo in `image:`, an invalid healthcheck `interval:`, a malformed `ports:` entry, or a profiles-typo (`profiles: ["pheonix"]`) would all pass this test. The CRITICAL F1 bind-mount bug was undetected by it. The brief AC #1 is currently demonstrated only by the (skipped on no-Docker) `config --quiet` invocation — and that invocation isn't actually proving anything about the Phoenix service.
- **Proposed fix:** Add `"--profile", "phoenix"` to the subprocess args at `tests/test_compose_phoenix.py:127`. Also parse the JSON/YAML output of `config` (drop `--quiet`, capture stdout) and assert `services.phoenix.image` startswith `arizephoenix/phoenix:` AND `services.phoenix.volumes[0].source` ends with `/var/arxmcp/observability/phoenix`.
- **Regression guard:** The assertion above is the guard — it pins both that the profile-gated service materializes AND that the bind-mount path resolves to the project's expected location.

### F3 — `restart: unless-stopped` silently relaunches Phoenix on host reboot

- **Severity:** HIGH
- **Source:** adversary
- **File:** infra/observability/phoenix-compose.yml:95
- **What:** `restart: unless-stopped` causes Docker to restart Phoenix on host boot unless the operator explicitly ran `docker compose down`. The Brief Risk note flags `mcp.session_id` as the load-bearing secret; loopback-binding is the documented defense. After a reboot, Phoenix is back up on 127.0.0.1:6006 serving accumulated traces — without the operator necessarily knowing.
- **Why it matters:** On a multi-user workstation (Chris's primary work machine is `me@chrisdare.net`'s single user but the threat model in `08-security-observability-ops.md` §Threat 4 acknowledges other local UIDs as in-scope adversaries), any local user can `curl http://127.0.0.1:6006/v1/traces` and exfiltrate `mcp.session_id` values — Phoenix's default config has **no authentication** (Brief 2 §2.2: `PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD=admin`, no auth required for read-only `/v1/traces` endpoints). A reboot silently reopens this read path. The runbook documents `docker compose down` but the average operator will treat reboot as "tear-down" — losing the explicit `down` step.
- **Proposed fix:** Change `restart: unless-stopped` to `restart: no` (or `on-failure: 3`). Document in the runbook that the operator must explicitly bring Phoenix back up after a reboot — matches the "opt-in dev tool" posture rather than the "long-running production service" framing. Alternatively, leave `unless-stopped` but require `PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD` to be set to something non-default in the compose file. The first option is lower-risk.
- **Regression guard:** Add an assertion in `tests/test_compose_phoenix.py` that `services.phoenix.restart` is in `{"no", "on-failure", None}`. NOT a loud test name — name it `test_phoenix_does_not_silently_relaunch_on_reboot` so the threat model is captured in the test name.

### F4 — Phoenix has no authentication; loopback alone is the only defense

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/observability/phoenix-compose.yml:39-62
- **What:** Phoenix 15.x ships with no required auth on the trace-read endpoints (`/v1/traces`, the UI). The compose file does not set `PHOENIX_ENABLE_AUTH`, `PHOENIX_SECRET`, or any equivalent. The single defensive layer is the `127.0.0.1:` host port binding. On a single-user macOS workstation that's defensible. On a shared box (someone runs `claude-code` over SSH; a teammate `ssh -L`s into the host; a malicious local script binds-and-forwards) it's not.
- **Why it matters:** CLAUDE.md §12 says "single-workstation local-first" — but that's the project posture, not a hard guarantee about every operator's environment. The threat model note (`08-security-observability-ops.md`) does not enumerate "Phoenix container with no auth" as a documented residual risk. A future operator who runs this on a shared Linux dev box gets a session-id leak without any warning.
- **Proposed fix:** Either (a) add `PHOENIX_ENABLE_AUTH=true` + `PHOENIX_SECRET=$(openssl rand -hex 32)` to the compose env, and document the credential-creation step in the runbook, OR (b) explicitly extend the runbook's §Security section to enumerate the residual risk: "Phoenix has no auth; loopback-only binding is the SOLE defense; do NOT run this profile on a shared host or with any port-forward arrangement." The runbook today only warns about the LAN, not local-user-on-the-same-host.
- **Regression guard:** Add a runbook section + an assertion in `tests/test_compose_phoenix.py` that either `PHOENIX_ENABLE_AUTH` is set (option a) or that the compose-file header comment includes the literal substring "no authentication" (option b — captures the doc-discipline trail).

### F5 — `OPENINFERENCE_SPAN_KIND` constant duplicates an upstream stable name

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/tracing.py:107
- **What:** The constant `OPENINFERENCE_SPAN_KIND: str = "openinference.span.kind"` is defined project-locally. The `openinference-semantic-conventions` Python package (PyPI) ships the exact same constant as `openinference.semconv.trace.SpanAttributes.OPENINFERENCE_SPAN_KIND` and lists supported values as a typed enum. We pinned the attribute name to a magic string literal.
- **Why it matters:** Two drift modes: (a) a future contributor adds another span helper and mistypes the literal in a new location (no test fires); (b) the upstream OpenInference semconv adds new SPAN_KIND values (e.g., a "PROMPT" sub-kind) — we have no way to discover them without a manual semconv re-read. The current behavior also passes one of the brief's stretch criteria for "no-fork" only narrowly: we're not lifting code, but we are duplicating a constant that exists in an OSS package.
- **Proposed fix:** Add `openinference-semantic-conventions` as a runtime dep (pyproject.toml; package is BSD-3-Clause, ~5 KB) and replace the project-local constant with `from openinference.semconv.trace import SpanAttributes; OPENINFERENCE_SPAN_KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND`. OR pin the project-local constant with a unit test that imports the upstream package (mark `requires_optional_dep`) and asserts the string matches — defers the dep but pins the contract.
- **Regression guard:** A test that imports `openinference.semconv.trace.SpanAttributes` and asserts `OPENINFERENCE_SPAN_KIND == SpanAttributes.OPENINFERENCE_SPAN_KIND`. Skip-gated on import failure if the dep isn't added.

### F6 — Healthcheck `wget --spider` availability in `arizephoenix/phoenix:15.10` not verified

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/observability/phoenix-compose.yml:82
- **What:** The compose file's healthcheck runs `["CMD", "wget", "--spider", "-q", "http://127.0.0.1:6006/healthz"]`. The synthesis (D3) states "Phoenix 15.x images bundle wget but not all bundle curl" — but this claim is sourced from Brief 2 §unknown-line and was NOT live-verified against the actual `arizephoenix/phoenix:15.10` image during this milestone. If wget isn't present, the healthcheck reports unhealthy forever; Docker still keeps the container running, but `docker compose ps` (which the runbook tells the operator to check at troubleshooting step 3) is misleading.
- **Why it matters:** A false-unhealthy reading triggers a confused operator path: they run `docker logs` (which works), see no app errors, and either re-tag the image (waste of time) or disable the healthcheck (bad). The brief's AC #1 is unaffected — the container starts — but the operator's first-troubleshooting-step is broken.
- **Proposed fix:** Live-verify wget's presence: `docker run --rm --entrypoint wget arizephoenix/phoenix:15.10 --version`. If wget is missing, switch the healthcheck to a Python liveness check the image is guaranteed to have: `["CMD-SHELL", "python -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:6006/healthz\")'"]`. If wget IS present, add a one-line comment in the compose noting the verification date.
- **Regression guard:** No test surface possible without Docker-in-CI. Add a runbook §Troubleshooting note: "If `docker compose ps` shows `unhealthy` despite the UI working, run `docker exec <id> which wget` to verify wget is present; absence means a Phoenix-image regression."

### F7 — `arizephoenix/phoenix:15.10` is a floating minor tag

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/observability/phoenix-compose.yml:31
- **What:** The image pin is `arizephoenix/phoenix:15.10`, a minor-version tag. Docker Hub allows the publisher to overwrite a minor tag (push `15.10.1`, `15.10.2`, etc., all under the same tag), and `docker compose pull` will fetch the new image silently. The runbook calls this a "minor pin" — accurate in the SemVer sense but misleading in the supply-chain sense.
- **Why it matters:** Per `08-security-observability-ops.md` §Threat 6, supply-chain integrity is a documented project concern: "Pin model commit SHAs in configuration, not just names." That discipline applies to model weights; the equivalent for a Docker image is `image: arizephoenix/phoenix@sha256:<digest>`. A future Phoenix image push (compromised builder, malicious commit landing in their CI) can silently land on every operator who runs `docker compose pull`. No SBOM check, no signature verification, no digest pin.
- **Proposed fix:** Replace `image: arizephoenix/phoenix:15.10` with `image: arizephoenix/phoenix:15.10@sha256:<digest>`. Resolve the digest with `docker buildx imagetools inspect arizephoenix/phoenix:15.10` and pin it. Document the bump procedure in the runbook (re-resolve digest, update compose, commit). The dual tag+digest form is human-readable AND pinned.
- **Regression guard:** Assert in `tests/test_compose_phoenix.py` that `services.phoenix.image` contains `@sha256:` (digest-pin discipline). Add a runbook section "Updating the Phoenix image" that lists the digest-resolution command.

### F8 — No resource limits; SQLite store + 14d retention can stress the host

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/observability/phoenix-compose.yml:26-95
- **What:** The compose file declares no `mem_limit`, `mem_reservation`, `cpus`, or `pids_limit` on the Phoenix service. With 14-day retention and a busy retrieval-evaluation session (each `search_papers` call produces 4+ spans; agent pipelines can fire dozens per minute), the SQLite store can grow to a few GB, and Phoenix's in-memory query path will scale with it.
- **Why it matters:** On a development workstation that's a "fan-spin-up surprise" rather than a hard failure, but: Phoenix is opt-in for retrieval-quality eyeballing; the operator probably isn't watching `docker stats`; a runaway Phoenix can starve the MCP server's BGE-M3 worker. The runbook's §Disk pressure section addresses storage but says nothing about memory/CPU.
- **Proposed fix:** Add `deploy.resources.limits.memory: 2g` and `deploy.resources.limits.cpus: "1.5"` to the compose. Phoenix's docs suggest 2 GB is comfortable for the trace volumes a single workstation will produce. Document the limit in the runbook so the operator knows where to bump it.
- **Regression guard:** Add a test that `services.phoenix.deploy.resources.limits` is non-empty. (Optional — MEDIUM-fixable-if-cheap.)

### F9 — `infra/README.md` rewrite loses the "two-service target" framing

- **Severity:** LOW
- **Source:** adversary
- **File:** infra/README.md:1-21
- **What:** The pre-milestone README said "Two-service target: `server` (the MCP HTTP server) and `ingest` (the ingestion process). Both bind only to `127.0.0.1`." The post-milestone rewrite drops that statement entirely and only mentions the base stack as "not yet shipped — tracked as future work." The architectural intent of the future stack is no longer explicit.
- **Why it matters:** A future agent picking up E14_S07 (the base compose stack) loses the brief's `127.0.0.1`-only binding constraint. Recovering it requires re-reading `08-security-observability-ops.md` §Docker deployment. Low-severity because the constraint is captured elsewhere; flagging because the rewrite was a net info loss.
- **Proposed fix:** Restore one sentence in the "future work" paragraph: "When shipped, both `server` and `ingest` services will bind only to `127.0.0.1` (per `.claude/notes/08-security-observability-ops.md` §Docker deployment)."
- **Regression guard:** None needed — doc-only.

### F10 — Implementation summary's "test count delta" claim drifts by +1

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/milestones/E14_S03/implementation-summary.md:71-77
- **What:** Summary claims "+9" tests (4 OpenInference + 5 compose). Actual: `tests/test_compose_phoenix.py` has 5 tests (`test_compose_path_exists`, `test_loopback_only_port_bindings`, `test_no_phoenix_telemetry`, `test_retention_policy_bounded`, `test_compose_file_parses`) — verified via `pytest --collect-only`. `TestOpenInferenceSpanKind` has 4 tests. Total 9 ✓. The full-suite count went 1778 → 1787 (+9), matching. **Clean here on revisit** — initial flag retracted.
- **Why it matters:** N/A — withdrawn.
- **Proposed fix:** None.
- **Regression guard:** None.

### F11 — `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS` stringified value not verified

- **Severity:** LOW
- **Source:** adversary
- **File:** infra/observability/phoenix-compose.yml:58
- **What:** The compose file passes `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS: "14"` (quoted string). The test parses it as `int(retention)`. Phoenix's env-var parser may or may not accept stringified ints (most Python apps using `os.environ` cast manually). The synthesis didn't verify Phoenix's parsing behavior against a real container.
- **Why it matters:** If Phoenix's startup logic does `int(os.environ["PHOENIX_DEFAULT_RETENTION_POLICY_DAYS"])`, the quoted "14" works fine. If it does `os.environ.get(..., 0)` then strict type-check, the quoted form might silently become 0 (infinite retention). The disk-pressure bound the synthesis (D3) treats as load-bearing then doesn't exist.
- **Proposed fix:** Live-verify on first `docker compose up` by checking Phoenix's container logs for a retention-init line. Document the verification in the runbook. Optionally drop the quotes (`PHOENIX_DEFAULT_RETENTION_POLICY_DAYS: 14`) — Compose serializes both forms identically into env-var bytes; the quotes are redundant.
- **Regression guard:** None (untestable without live container).

### F12 — Runbook overstates `compose config --quiet` coverage

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_compose_phoenix.py:118-122
- **What:** The docstring states `config --quiet` "validates the full Compose Spec semantics that yaml.safe_load alone won't catch (interpolation, profile syntax, port-mapping shape)." This is technically true but materially misleading: in this milestone's invocation (without `--profile phoenix`), the validator runs against an empty-services graph and validates none of the listed semantics for Phoenix specifically.
- **Why it matters:** Doc-discipline. A reader of the test trusts the docstring; the docstring is currently puffed.
- **Proposed fix:** Truncate the docstring to "Runs the Compose Spec validator with the phoenix profile activated; catches profile-syntax errors and bind-mount-path resolution drift." This statement is true only after F2 is fixed; pair the doc fix with the test fix.
- **Regression guard:** Captured by F2.

## What was done well

- Real recognition that the brief specified an "Updated `docker-compose.yml`" file that doesn't exist; D1 ships a standalone compose file with a tracked-defer to E14_S07 rather than fabricating the base stack.
- The OpenInference span-kind addition is correctly scoped to span attributes (in-process, not on the MCP wire surface), preserving `TOOL_SCHEMA_VERSION` at 6 — verified post-implementation by re-running `tests/test_server_tool_schema.py` (passes; live-checked).
- `127.0.0.1:` prefix on every host port binding + the regression-guard test `test_loopback_only_port_bindings`. The "magic string `127.0.0.1:`" check is exactly the right granularity — pins the load-bearing defense without coupling to YAML schema specifics.
- `PHOENIX_TELEMETRY_ENABLED: "false"` + the regression guard `test_no_phoenix_telemetry`. The phone-home is a real concern; the test prevents accidental re-enabling.
- The synthesis correctly DROPPED the brief's factually-wrong "Phoenix as Prometheus scraper" line and tracked the actual Prometheus work to E14_S09.
- Span-kind tests use the public constant via the helper API rather than hard-coding the literal in test assertions — wait, actually they DO hard-code `"openinference.span.kind"`. Half-credit: the production code uses the constant, the tests don't. (Captured separately as F5's tangent.)
- Operator runbook docs the ELv2 license callout — defends against a future contributor's "open-source = Apache-2.0" assumption.
- The runbook §Verify section is concrete (curl `/metrics`, inspect span hierarchy in Phoenix UI) rather than hand-wavy "look around the UI."
- `make bootstrap` gained the new directory creation in the correct ordering position (before any docker compose invocation would need it). Note that the bind-mount-path bug (F1) makes this addition dead in practice, but the discipline is right.
- 1787 passing tests post-milestone matches the +9 claim. `ruff check .` clean. No skipped tests other than the documented Docker-gated one.

## Recommended rectification order

1. **F1** — fix the bind-mount path resolution. Drives F2's test
   shape (the regression guard explicitly checks F1's fix).
2. **F2** — add `--profile phoenix` to the smoke test AND parse +
   assert the resolved bind-mount source. This both fixes the test
   AND becomes F1's regression guard.
3. **F3** — `restart: no` (or `on-failure`). One-line change in
   the compose; closes the silent-reboot-relaunch threat surface.
4. **F4** — runbook §Security extension OR `PHOENIX_ENABLE_AUTH`.
   Recommend the runbook extension (cheaper, captures the threat
   model in writing). The auth-on path is a larger UX shift and
   should be its own ticket.
5. **F7** — pin the image digest. One-line compose change + a
   runbook update on the bump procedure. Low effort, high
   supply-chain payoff.
6. **F6** — live-verify wget; doc the verification date in a
   one-line comment OR switch to a Python liveness check.
7. **F8** — add `mem_limit` + `cpus`. Defensive; <5 LOC.
8. **F5** — pin against `openinference-semantic-conventions` (or
   add the contract test). Optional — track as a follow-up if it
   inflates this milestone's diff.
9. **F9**, **F11**, **F12** — bundle as a doc-touch-up commit.

## Rectification status

- **F1** (CRITICAL — bind-mount path resolves under `infra/`):
  fixed. Changed the path to `../../var/arxmcp/observability/phoenix`
  so it walks up from the compose-file directory to the repo root.
  Live-verified via `docker compose ... config` — source now
  resolves to
  `/.../arXMCP/var/arxmcp/observability/phoenix`. Regression guard
  in `tests/test_compose_phoenix.py::test_compose_file_parses_with_profile`
  asserts the resolved source ends with
  `/var/arxmcp/observability/phoenix` and does NOT contain
  `/infra/observability/var/`.
- **F2** (HIGH — `config --quiet` ran without `--profile phoenix`):
  fixed. Renamed to `test_compose_file_parses_with_profile`; the
  subprocess now passes `--profile phoenix` and the test parses
  the rendered YAML to assert (a) the phoenix service materializes,
  (b) the image carries an `@sha256:` digest pin, (c) the bind-
  mount source resolves correctly. The same test now serves as
  F1's regression guard.
- **F3** (HIGH — `restart: unless-stopped` silently re-launches on
  reboot): fixed. Changed to `restart: "no"`. Guard at
  `tests/test_compose_phoenix.py::test_restart_policy_is_no`.
- **F4** (MEDIUM — Phoenix has no auth): fixed via runbook
  documentation. New §"Residual risk — same-host other users"
  enumerates the threat and the two safe modes (sole-user host vs
  shared host with tracing disabled). Auth-on Phoenix is tracked
  as out-of-scope for v1.
- **F5** (MEDIUM — `OPENINFERENCE_SPAN_KIND` duplicates upstream
  constant): DEFERRED. Adding a new runtime dep for one string
  constant is wasteful; the project-local constant is documented
  in `tracing.py:107` with the OpenInference semconv citation, and
  the value matches the upstream literal. If the upstream
  `openinference-semantic-conventions` package gains a SpanKind
  enum extension we want to honor, we re-evaluate.
- **F6** (MEDIUM — wget availability not live-verified): DEFERRED.
  Live verification requires running the container; covered by
  the runbook's troubleshooting note (§Troubleshooting). The
  `start_period: 20s` masks short-lived first-pull issues.
- **F7** (MEDIUM — minor-pinned tag, no digest): fixed. Image
  pinned to `arizephoenix/phoenix:15.10@sha256:34464e86...`. The
  runbook's "Upgrading Phoenix" section now documents
  `docker buildx imagetools inspect ... | grep '^Digest:'` as
  the re-resolve procedure. Guard at
  `test_compose_file_parses_with_profile` (asserts `@sha256:`
  presence in the image string).
- **F8** (MEDIUM — no resource limits): fixed. `mem_limit: 2g` +
  `cpus: 2.0`. Guard at
  `tests/test_compose_phoenix.py::test_resource_limits_set`.
- **F9** (LOW — `infra/README.md` lost the "two-service target"
  framing): fixed. Restored the sentence about both `server` and
  `ingest` binding to 127.0.0.1 (with a cite to note 08).
- **F10** (LOW — test-count drift): WITHDRAWN by the critic on
  re-verify; no action needed.
- **F11** (LOW — retention env-var stringified value not
  verified): DEFERRED. Live container check; documented in the
  runbook §Troubleshooting.
- **F12** (LOW — runbook overstates `config --quiet` coverage):
  fixed. The test's docstring now accurately describes what it
  validates after F2's rectification.

Plus the infra-safety findings (full list in
`critique-infra-safety.md`):

- **IS1** (MEDIUM — root user): DEFERRED. Adding `user:` requires
  live-container validation that Phoenix's entrypoint succeeds
  under non-root — out of scope for this rectification window.
  Documented in the runbook as a known posture.
- **IS2** — covered by F8.
- **IS3** — covered by F7.
- **IS4** (MEDIUM — writable rootfs): DEFERRED. Same live-container
  validation gap as IS1; Phoenix may write outside `/mnt/data`
  (logs, `/tmp`, etc.) and `read_only: true` without an
  exhaustive `tmpfs:` list would break startup.
- **IS5** (MEDIUM — no cap_drop / no-new-privileges): fixed.
  `cap_drop: ["ALL"]` + `security_opt: ["no-new-privileges:true"]`.
  Guard at `tests/test_compose_phoenix.py::test_capability_hardening`.
  If Phoenix's entrypoint fails under this hardening, the next
  `docker compose up -d` will surface it and we add the
  specific cap with `cap_add:`.
- **IS6** — covered by F1.
- **IS7** (LOW — healthcheck doesn't validate gRPC port): DEFERRED.
  Documented in the runbook §Troubleshooting; both listeners share
  one Phoenix process so the "process up but one listener down"
  failure mode is rare.
- **IS8** (LOW — no `init: true`): fixed. `init: true` on the
  service. Guard at
  `tests/test_compose_phoenix.py::test_init_for_pid1_reaping`.

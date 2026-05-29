# Critique — notebook-ops-hardening-m3

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** 12edf982d0a4ae476d1138182803f2f3c111c138..55e4e8830881ab4e0929ebd063780eb64533d970
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the compose file, sha256 pins, and static test are structurally correct and `docker compose config` resolves the bind-mount + loopback host_ip exactly as claimed — but the *documented* AC1 happy-path (`make bootstrap` → `up --wait` → `/readyz` 200) will crash the container at startup for a fresh operator with no ingested corpus, and the docs give no corpus prerequisite for the compose flow.
- Finding counts: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 1 LOW.
- Highest-risk file:line: `docs/install.md:167-206` (Docker Compose section documents a flow that never reaches a healthy server without a prior ingest) cross-referenced with `server/config.py:113-114` (`CorpusNotIngestedError` when the default corpus is empty) and `server/corpus.py:291` (`FileNotFoundError` on a missing dataset).
- Cross-axis pattern: the static test mirrors phoenix's test well but DROPS phoenix's `test_restart_policy_is_no()` guard, leaving the m3 recorded judgment-call config (`restart: "no"`) unprotected against silent regression to `unless-stopped`.
- Local-first / loopback contract verified end-to-end with live `docker compose config` on Compose v2.39.2: `host_ip: 127.0.0.1`, in-container `0.0.0.0` only, both bind-override env vars present, bind source = repo-root `var/arxmcp`. No LAN-exposure hole.
- The sha256 digest `a3ab0b96…` was confirmed against the live `python:3.11-slim` multi-arch manifest (`docker buildx imagetools inspect`) — a real, resolvable, multi-arch digest. curl IS in the runtime image (`docker/Dockerfile.server:96`) so the healthcheck is functional.
- Math fidelity / cache byte-stability / MCP-spec / no-fork axes are all clean (no parser, no tool surface, no prompt/schema surface, no vendored code).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Documented compose flow crashes at startup without a corpus

- **Severity:** HIGH
- **Source:** adversary
- **File:** docs/install.md:167-206 (new "Run via Docker Compose" section); root cause at server/config.py:104,113-114 + server/corpus.py:291
- **What:** The documented happy-path is `make bootstrap` → `docker compose up --wait` → `curl /readyz` (expects 200). But `make bootstrap` (Makefile:44-45) creates only an EMPTY `var/arxmcp/index/lancedb` directory — no LanceDB dataset, no `corpus-version.json`. `Resources.startup` opens the chunks table at the default `lancedb_path` (config.py:104), and `open_chunks_table` raises `FileNotFoundError` on a missing dataset (corpus.py:291); config.py:113-114 explicitly documents the `CorpusNotIngestedError` "when that corpus is empty". The exception propagates through the lifespan, so the container exits at startup. With `restart: "no"`, `docker compose up --wait` reports the service unhealthy and exits non-zero — `/readyz` is never reachable.
- **Why it matters:** This is AC1's documented happy-path. A first-time operator following the new section verbatim sees a crashed container, not a healthy server. The synthesis (research-synthesis.md FM-b) under-stated this as "/readyz 503"; the real failure is a hard startup crash. The existing 503-troubleshooting hint that DOES name "run the ingest pipeline first" lives at docs/install.md:287 — in the bare-metal section, NOT the new compose section, and it describes a graceful 503, not the crash. The compose section (167-206) has no corpus-prerequisite line at all.
- **Proposed fix:** In `docs/install.md` after the `make bootstrap` step (~line 190), add an explicit prerequisite: the server requires a populated corpus before it can become healthy — either an ingested shared corpus at `var/arxmcp/index/lancedb` (e.g. via the seed-fetch + ingest path) OR a notebook corpus served via `ARXMCP_NOTEBOOK=<slug>` (config.py:106-118). State that with an empty `var/arxmcp` the container will EXIT at startup (not 503), and point to the existing line-287 note. Mirror the same one-liner into `infra/README.md` so the compose entry there is not misleading.
- **Regression guard:** Add a test asserting the compose section in `docs/install.md` contains a corpus-prerequisite marker string (e.g. asserts the section text mentions "ingest" or "ARXMCP_NOTEBOOK" within the "Run via Docker Compose" block). A doc-grep test in `tests/test_compose_server.py` is sufficient and matches the existing static-inspection pattern.

### F2 — Static test drops phoenix's restart-policy guard

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_compose_server.py (no restart assertion anywhere; compare tests/test_compose_phoenix.py:189-202)
- **What:** `infra/docker-compose.yml:1169` sets `restart: "no"` — a recorded judgment call (research-synthesis.md RESOLVED #2; diverges from 08-security's "always-on" framing). The phoenix test suite guards its equivalent with `test_restart_policy_is_no()`. The m3 test suite has NO assertion on `restart` at all, even though the synthesis test-plan listed "restart present" as an intended assertion (research-synthesis.md "Test plan").
- **Why it matters:** The load-bearing config value that the synthesis explicitly flagged as a judgment call (and the resource-pressure reason behind it) can silently regress to `unless-stopped` — exactly the value 08-security wanted and an operator might re-add — with zero test failure. A copy of an existing config from phoenix that drops its guard is a coverage gap, not a refactor.
- **Proposed fix:** Add `test_restart_policy_present()` to `tests/test_compose_server.py` asserting `svc.get("restart") == "no"` (or `in ("no", "unless-stopped")` if you want to permit the documented override — but pin it to the chosen v0 default `"no"` to make a regression visible). ≤ 8 LOC.
- **Regression guard:** The test itself is the guard.

### F3 — Bind-mounting the entire var/arxmcp exposes notebooks.db + uploaded PDFs into the capability-dropped container

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/docker-compose.yml:1123 (`- ../var/arxmcp:/app/var/arxmcp`)
- **What:** The compose bind-mounts the ENTIRE repo-root `var/arxmcp` tree read-write into the container. That tree includes `var/arxmcp/cache/notebooks.db` (config.py:150), per-notebook LanceDB corpora under `var/arxmcp/notebooks/<slug>/`, uploaded textbook PDFs, the retrieval cache, and the restic-relevant ops tree. The server-only v0 needs read access to the corpus index + write access to the cache/ops subset, but it does not need write access to (e.g.) uploaded PDFs or other notebooks' corpora.
- **Why it matters:** On the loopback-only single-workstation threat model this is low blast-radius (the operator owns the host and the data), so it is NOT a security regression — hence MEDIUM not HIGH. But it is broader than the documented scope ("the MCP server ONLY") and means a future compromise inside the container (e.g. via a malicious uploaded PDF processed by an ingest path that lands in v1) would have write reach over the whole data tree including backups. The Dockerfile's `IS7` read-only-FS posture (Dockerfile.server:129-132) is silently undercut by a full read-write bind.
- **Proposed fix:** Document the broad-mount decision explicitly in the compose comment (it is currently justified only as "matches WORKDIR/VOLUME"), OR narrow the mount to the subset the server-only v0 actually reads/writes (e.g. `index/`, `cache/`, `ops/`) and add the others in the v1 ingest increment. At minimum, note in `docs/install.md` that the whole data tree (incl. uploads + backups) is mounted writable. A one-line comment is the cheap fix; narrowing the mount is the thorough one.
- **Regression guard:** If narrowed, add an assertion in `tests/test_compose_server.py` that the bind sources are the intended subset; if documented-as-is, no test needed.

### F4 — sha256 pin re-resolution drifts the digest comment out of date with no guard

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docker/Dockerfile.server:40,83 (same digest hardcoded in two FROM lines + two prose comments)
- **What:** The digest `a3ab0b96…` is hardcoded in both FROM lines, and the comment at line 82 says "Keep both stages on the SAME digest." There is no test asserting the two FROM lines carry the *same* digest — the existing test (`test_dockerfile_base_images_are_sha256_pinned`, tests/test_compose_server.py:1335) only asserts each line contains `@sha256:`, not that they match each other. A future hand-edit bumping one stage but not the other would pass the test while building the builder and runtime on divergent base images.
- **Why it matters:** Divergent builder/runtime base images is a subtle reproducibility/supply-chain foot-gun: the wheel is built against one libc/openssl and run against another. Not on the common path (requires a careless manual bump), so MEDIUM. The "Keep both on the SAME digest" comment is a promise the test does not enforce.
- **Proposed fix:** Strengthen `test_dockerfile_base_images_are_sha256_pinned` to extract the `@sha256:<hex>` from each `FROM python:` line and assert all extracted digests are identical (`len(set(digests)) == 1`). ≤ 6 LOC.
- **Regression guard:** The strengthened assertion is the guard.

### F5 — `test_in_container_bind_override_env` tolerates values the field cannot parse

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_compose_server.py:1293 (`assert env.get("ARXMCP_UNSAFE_NETWORK_BIND") in ("1", "true", "True")`)
- **What:** The test accepts `"1"`, `"true"`, or `"True"` as valid for `ARXMCP_UNSAFE_NETWORK_BIND`. The compose actually uses `"1"` (infra/docker-compose.yml:1136) and `unsafe_network_bind` is a pydantic `bool` (config.py:366) which parses `"1"`/`"true"`/`"True"` fine — so the test is not wrong today. But the assertion is looser than the compose value it guards: if someone changed the compose to a value pydantic rejects (e.g. `"yes"` is NOT a pydantic-settings bool truthy), the test's permissive set would still let some non-canonical strings slip relative to the actual single value in use.
- **Why it matters:** Style/precision only — the binding works today. Listed for completeness; tightening removes a latent ambiguity between "what the test allows" and "what the container actually sets".
- **Proposed fix:** Either pin the assertion to the exact compose value (`== "1"`) or add a comment that the accepted set must remain a subset of pydantic-settings bool-truthy strings. ≤ 2 LOC. Defer — not load-bearing.
- **Regression guard:** n/a (LOW; deferred).

## What was done well

- The load-bearing RESOLVED #1 conflict (`../` vs `../../`) was resolved correctly AND empirically: `docker compose config` resolves the bind source to exactly `<repo-root>/var/arxmcp`, and the docker-gated test (tests/test_compose_server.py:1355) asserts this against `REPO_ROOT / "var" / "arxmcp"` — the strongest possible guard for an F1-class trap.
- The sha256 digest is a real, current, multi-arch manifest-list digest (verified live against `docker buildx imagetools inspect python:3.11-slim`) — not a fabricated or single-arch hash; both Apple-Silicon and amd64 resolve.
- curl is genuinely present in the runtime image (docker/Dockerfile.server:96), so the `/readyz` healthcheck the compose relies on for `--wait` actually works — a real correctness risk that was checked and is clean.
- The loopback contract holds end-to-end: host `127.0.0.1:7733:7733` + in-container `0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1`, confirmed via live `docker compose config` showing `host_ip: 127.0.0.1`. No LAN-exposure hole, no compose-version host_ip-default surprise on v2.39.2.
- The spike-1 gate was genuinely run live and RESOLVED, and its finding (chown is Linux-only, NOT macOS) correctly OVERRIDES the brief's wrong AC wording — and the docs reflect the corrected guidance (docs/install.md:991-997).
- Both bind-override env vars are present, so the container will not crash on the config validator (`reject_non_loopback_bind`, config.py:518-537) — the FM-c failure mode is correctly avoided.
- `ARXMCP_CONTACT_EMAIL` is correctly omitted given the server Config's `extra="forbid"` (config.py:82) — setting it would have raised a ValidationError at parse time; the test even guards its absence (tests/test_compose_server.py:1299).
- Scope discipline: exactly the 5 deliverable files changed, no Makefile churn, no server/ingest code touched, no banned pattern introduced, no tool-schema/prompt surface — so no BP1/cache re-pin needed (correctly noted in the briefs).
- The compose file is heavily and accurately commented, with every hardening line traced to its originating phoenix/E14_S03 critique finding — strong operator-facing provenance.

## Recommended rectification order

1. **F1 (HIGH)** — add the corpus-prerequisite to the compose section of `docs/install.md` (+ `infra/README.md`); the documented AC1 path is otherwise non-functional for a fresh operator. Highest leverage: it fixes the one thing that makes the milestone's headline flow fail.
2. **F2 (MEDIUM)** — add the restart-policy test; cheap (≤ 8 LOC) and closes a deliberate-judgment-call regression hole.
3. **F4 (MEDIUM)** — strengthen the sha256 test to assert both FROM digests match; cheap (≤ 6 LOC) and enforces the comment's promise.
4. **F3 (MEDIUM)** — document (cheap) or narrow (thorough) the full-tree bind mount; do the one-line comment at minimum.
5. **F5 (LOW)** — defer; tighten the env-value assertion opportunistically if touching the test file for F2/F4.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

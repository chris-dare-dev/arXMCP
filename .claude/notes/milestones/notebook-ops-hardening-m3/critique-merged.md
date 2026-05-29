# Merged Critique — notebook-ops-hardening-m3

**Critics:** adversary (`critique-adversary.md`) + infra-safety
(`critique-infra-safety.md`)
**Commit range:** 12edf982d0a4ae476d1138182803f2f3c111c138..55e4e8830881ab4e0929ebd063780eb64533d970

## Orchestrator executive summary

- **Adversary: SHIP-WITH-FIXES** (0 CRITICAL, 1 HIGH, 3 MEDIUM, 1 LOW).
- **Infra-safety: SHIP** (0 findings — all 4 axes clean: curl confirmed in the
  runtime stage so the `/readyz` healthcheck works; both FROM stages carry the
  same real multi-arch `@sha256` digest; `docker compose config` resolves the
  bind to repo-root `var/arxmcp` + `host_ip: 127.0.0.1`; `cap_drop:[ALL]` +
  `no-new-privileges` + `init`; `mem_limit`/`cpus` not `deploy.resources`; no
  CI/Makefile change in range).
- The one load-bearing issue is the HIGH F1: the **documented** AC1 happy-path
  (`make bootstrap` → `up --wait` → `/readyz` 200) CRASHES the container at
  startup for a fresh operator with no corpus — verified: `server/main.py:285`
  ("startup failure raises and uvicorn exits non-zero") + `server/corpus.py:291`
  (`FileNotFoundError` on a missing dataset). It is a hard crash, not the
  graceful 503 the synthesis FM-b assumed. Doc-only fix + a doc-grep guard.
- The compose/Dockerfile structure, sha256 pins, loopback contract, and bind
  resolution are all verified-correct and clean across both critics.

## Findings (IDs preserved)

See `critique-adversary.md` for full text. Summary:

- **F1 (HIGH)** — documented compose flow crashes at startup without a corpus
  (`docs/install.md` compose section + `infra/README.md`; root cause
  `server/main.py:285` + `server/corpus.py:291`). Fix: document the corpus
  prerequisite (ingested shared corpus OR `ARXMCP_NOTEBOOK=<slug>`); add a
  doc-grep regression test.
- **F2 (MEDIUM)** — static test drops phoenix's restart-policy guard
  (`tests/test_compose_server.py`). Fix: assert `restart == "no"` (≤8 LOC).
- **F3 (MEDIUM)** — the whole `var/arxmcp` is bind-mounted read-write (broader
  than "server only"; undercuts the read-only-FS posture). Low blast radius
  (loopback single-workstation, operator owns the data). Fix: document the
  broad-mount decision in the compose comment + `docs/install.md`.
- **F4 (MEDIUM)** — the sha256 test asserts each FROM line has `@sha256:` but
  NOT that the two digests match (the comment promises "same digest"). Fix:
  assert `len(set(digests)) == 1` (≤6 LOC).
- **F5 (LOW)** — `test_in_container_bind_override_env` accepts a looser set than
  the compose uses. Opportunistic tighten to `== "1"`.

Infra-safety: NONE.

## Cross-critic agreement

No overlap requiring dedupe: infra-safety returned 0 findings; the adversary's
findings are doc + test-coverage + a mount-scope note, all outside the
container-hygiene axes infra-safety cleared. No finding was flagged by both.

## Combined "What was done well"

- RESOLVED #1 (`../` vs `../../`) resolved correctly AND empirically; the
  docker-gated test asserts the bind resolves to `REPO_ROOT/var/arxmcp` — the
  strongest guard for the F1-class trap.
- The `@sha256` digest is a real, current, multi-arch manifest-list digest
  (verified live); both stages share it; curl is present so the healthcheck
  works.
- Loopback contract holds end-to-end (`host_ip: 127.0.0.1` + in-container
  `0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1`); no LAN-exposure hole.
- spike-1 gate genuinely run + resolved; its finding (chown Linux-only) correctly
  overrides the brief's wrong macOS wording, reflected in the docs.
- `ARXMCP_CONTACT_EMAIL` correctly omitted (server Config `extra="forbid"`);
  absence even guarded by a test.
- Scope discipline: exactly the deliverable files; no Makefile/CI churn; no
  server/ingest code; no banned pattern; no BP1/tool-schema surface.
- Heavily + accurately commented compose with provenance tracing to the
  phoenix/E14_S03 findings.

## Recommended rectification order

1. **F1 (HIGH)** — corpus prerequisite in `docs/install.md` (+ `infra/README.md`)
   + doc-grep guard. Fixes the headline flow.
2. **F2 (MEDIUM)** — restart-policy test (≤8 LOC).
3. **F4 (MEDIUM)** — same-digest assertion (≤6 LOC).
4. **F3 (MEDIUM)** — document the full-tree mount (compose comment + install.md).
5. **F5 (LOW)** — tighten the env-value assertion opportunistically.

## Rectification status

All 5 adversary findings fixed (infra-safety: 0 findings). Re-verify gate: F1's
crash-not-503 premise was confirmed at `server/main.py:285` ("startup failure
raises and uvicorn exits non-zero") + `server/corpus.py:291` (`FileNotFoundError`
on a missing dataset) before fixing.

- **F1 (HIGH) — FIXED.** Added a "Corpus prerequisite (required)" callout to the
  `docs/install.md` compose section (server warms eagerly → empty `var/arxmcp`
  makes the container EXIT at startup, not 503; populate via ingest OR
  `ARXMCP_NOTEBOOK=<slug>` first) + a `make bootstrap` inline note, and mirrored
  the prerequisite into `infra/README.md`. Regression guard:
  `tests/test_compose_server.py::test_install_doc_states_corpus_prerequisite`
  (scoped doc-grep asserting the section names the prerequisite, the
  ingest/ARXMCP_NOTEBOOK path, and the "exit" warning).
- **F2 (MEDIUM) — FIXED.** Added
  `test_restart_policy_is_no` asserting `restart == "no"` (closes the
  judgment-call regression hole the phoenix test guarded but m3's dropped).
- **F3 (MEDIUM) — FIXED (documented).** Documented the whole-tree read-write
  mount in the `infra/docker-compose.yml` volume comment (F3 SCOPE) + a
  "Bind-mount scope" note in `docs/install.md`. Not narrowed: under the
  loopback-only single-workstation threat model the blast radius is low
  (operator owns host + data); narrowing is scoped to the v1 ingest increment
  when the per-service read/write split is clear. (adversary offered document
  OR narrow; chose document for v0.)
- **F4 (MEDIUM) — FIXED.** Strengthened
  `test_dockerfile_base_images_are_sha256_pinned` to extract the digest from
  each `FROM python:` line and assert `len(set(digests)) == 1` — enforces the
  "Keep both stages on the SAME digest" comment.
- **F5 (LOW) — FIXED (opportunistic).** Tightened
  `test_in_container_bind_override_env` from a looser set to `== "1"` (the exact
  compose value), with a comment that it must stay a pydantic bool-truthy value.

Net: 1 HIGH + 3 MEDIUM + 1 LOW all fixed; 0 deferred; 0 invalidated. m3 compose
test count 11 → 13. infra-safety SHIP (no findings). ruff clean.

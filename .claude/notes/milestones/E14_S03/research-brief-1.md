# E14_S03 — Research brief 1: in-codebase context

**Scope:** In-codebase wiring for Phoenix integration. Peer brief 2 owns
external (Phoenix images, OTLP intake config, port semantics).

---

## 1. In-codebase context

### 1.1 `docker-compose.yml` does NOT exist at repo root

Confirmed: `ls /Users/chris.dare/Personal/SourceCode/arXMCP/` shows no
`docker-compose.yml`, no `compose.yaml`. `find -name 'docker-compose*'`
returns nothing. **The brief's deliverable "Updated `docker-compose.yml`"
references a file that has never existed.**

`infra/README.md` (the only file in `infra/`) names the target but
defers the work:

> Empty until [E14](../.claude/roadmap/epic-14-observability-ops.md) and
> the docker-compose layout from [`.claude/notes/08-security-observability-ops.md`](../.claude/notes/08-security-observability-ops.md) § Docker deployment land.

The E14 roadmap (`E14-observability-ops.md`) has no milestone that ships
the base `docker-compose.yml`. **E14_S03 (this one), E14_S05 (backup +
failure modes), and E14_S09 (Grafana) all assume compose exists.** Each
references compose profiles (`--profile phoenix`, `--profile grafana`).
No earlier milestone creates the base file.

### 1.2 `make up` is real, not a stub

Confirmed `Makefile:78-82`:

```
up:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), ..."
	$(PYTHON) -m server.main
```

This is bare-metal `python -m server.main`. **No compose invocation
today.** This differs from `make ingest`, which is a real driver
(E11_S01 shipped) — both targets are real, not stubs (CLAUDE.md §7's
"make ingest is a stub" wording is now stale post-E11_S01).

### 1.3 `docker/Dockerfile.server` is the only Docker artifact

Multi-stage builder + runtime. Runtime stage: non-root `arxmcp` user
(UID 1000), `tini` as PID 1, `EXPOSE 7733`, `HEALTHCHECK` curls
`http://127.0.0.1:7733/readyz`, entrypoint `python -m server.main`.
File comment at line 26 says:

> Out of scope per the brief: the docker-compose file (lands in E06_S05).

E06_S05 actually shipped security hardening, NOT compose — the deferral
sticker was never satisfied.

### 1.4 `server/config.py::otel_endpoint` already accepts Phoenix

Line 205: `otel_endpoint: str | None = None`. The
`validate_otel_endpoint_loopback` model-validator (lines 292-366)
accepts:

> Hostnames in :data:`LOOPBACK_HOSTS` (``127.0.0.1``, ``::1``, ``localhost``).

`LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})`. Phoenix
on `http://127.0.0.1:4317` (the documented Phoenix OTLP default — see
`.claude/docs/observability-tracing.md:39`) is accepted. **Zero
server/config.py changes needed.**

Note however the field comment says:

> Default port 4317 matches Phoenix's OTLP intake.

**but the default value of `otel_endpoint` is `None`, not
`http://127.0.0.1:4317`.** The brief claims:

> the `ARXMCP_OTEL_ENDPOINT` default points at the Phoenix OTLP collector port.

That is **false today.** Either (a) the brief expects this milestone to
flip the default, OR (b) the operator sets the env var before
`make up`. The `.claude/docs/observability-tracing.md` runbook walks
operators through `export ARXMCP_OTEL_ENDPOINT=...`. Recommendation:
**keep default at `None`** (tracing-disabled-by-default is load-bearing
for the E14_S02 zero-allocation guarantee), and document the export
step in the new Phoenix runbook. Don't silently flip the default — that
breaks E14_S02 invariants tested by `tests/test_tracing.py`.

### 1.5 `server/observability/tracing.py` is Phoenix-agnostic

The module uses pure OTLP/gRPC (`OTLPSpanExporter` from
`opentelemetry.exporter.otlp.proto.grpc`). Nothing couples to Phoenix.
The `_probe_endpoint` does a 1-second TCP connect (line 286 onward) —
when Phoenix is down, **the probe fails but the exporter is registered
anyway** so spans flow when Phoenix wakes mid-process. That's the
"server starts normally; no connection errors in the log" AC already
satisfied at the SDK layer.

### 1.6 `.claude/notes/08-security-observability-ops.md` compose snippet — ASPIRATIONAL

Lines 269-315 contain a `services:` snippet with `arxmcp-server` and
`arxmcp-ingest`. The `server/config.py` docstring lines 19-27 explicitly
flag this as drift:

> Note on docker-compose drift. `08-security-observability-ops.md` line
> 261 shows a docker-compose example setting `ARXMCP_BIND_HOST=0.0.0.0`
> inside the container ... The E06_S01 brief AC overrides this for v1:
> reject non-loopback at the config layer with no exception.

So the constitution-note snippet is **aspirational and drift** — its
`ARXMCP_BIND_HOST=0.0.0.0` would fail the Config validator. Treat the
snippet as inspiration, NOT a contract.

### 1.7 Doc-layout rule precedent — `docs/ops/` exists with 7 runbooks

CLAUDE.md §1 says `docs/` is restricted to "user-facing documentation
referenced by the root `README.md`. Today: just `docs/install.md`."

But `ls docs/ops/` shows 7 runbooks from E11
(`bulk-ingest-runbook.md`, `cutover-runbook.md`, `delta-loop.md`,
`drift-watchdog.md`, `re-embed-runbook.md`, `latexml-drift-runbook.md`,
`backup-restore.md`). These are operator-facing, linked from Makefile
comments. **They violate the strict CLAUDE.md §1 wording but match the
brief precedent.** The E14 roadmap creates ~10 more `docs/ops/*.md` and
`docs/observability/*.md` files.

E14_S02 chose differently: it shipped
`.claude/docs/observability-tracing.md` (per the E14_S02 synthesis
finding 10 quoted above). So we have **two competing precedents**:
- E11 ops runbooks → `docs/ops/*.md`
- E14_S02 tracing reference → `.claude/docs/observability-tracing.md`

### 1.8 No yamllint / compose-config test pattern exists

`grep -r "yamllint\|docker compose config" tests/` returns nothing.
`ls tests/` has no `test_infra*` or `test_compose*`. There is no
established CI hook for compose-file validation. This milestone is the
first to introduce a compose file; we should add a minimal smoke test
that runs `docker compose -f <path> config --quiet` if Docker is on PATH
(skipped otherwise — same pattern as the `requires_model` marker).

---

## 2. Prior decisions and lessons

### 2.1 HANDOFF.md compose mention

`.claude/notes/HANDOFF.md:310` mentions "Phoenix retrieval-quality
views, daily" in the context of remaining work, but there is no prior
compose-related deferral note.

### 2.2 Recent git log — no compose touches

`git log --all -- docker-compose.yml infra/` shows only one ancient
commit `8633cc6 feat(infra): scaffold mono-repo layout`. Nothing under
`infra/` has been touched since. The 14 most recent commits are
E11/E14_S01/E14_S02 — all server-side.

### 2.3 Loopback-only port binding — confirmed Compose syntax

E06_S01 (`server/config.py::reject_non_loopback`), E08_S04, E14_S01,
E14_S02 all enforce 127.0.0.1-only binding. The compose syntax that
binds to loopback is:

```yaml
ports:
  - "127.0.0.1:6006:6006"     # Phoenix UI
  - "127.0.0.1:4317:4317"     # Phoenix OTLP/gRPC intake
```

Plain `"6006:6006"` binds to `0.0.0.0` on the host. The constitution-
note snippet at `08-...md:286` already shows the correct form
(`"127.0.0.1:7733:7733"`). The brief's named risk note —

> The Phoenix container must be localhost-only (no external port binding)

— is satisfied by the `127.0.0.1:` prefix. The compose file must use it
on both Phoenix ports.

### 2.4 Prometheus scrape target — brief asks for it but Phoenix is not a scraper

The brief says:

> The compose profile also starts a Prometheus scrape target for the
> `/metrics` endpoint, making E14_S01 metrics visible in Phoenix's
> metrics pane.

This is **incorrect**: Phoenix does not embed a Prometheus scraper.
Phoenix's "metrics pane" displays span-derived metrics from OTel data,
not Prometheus scrapes. To get Prometheus scraping the server's
`/metrics`, we'd need a separate Prometheus container, which is exactly
what **E14_S09 ships** ("`docker compose --profile grafana up -d` starts
Grafana ... and Prometheus at http://localhost:9090"). **Recommendation:
defer the Prometheus scrape to E14_S09 and remove that line from the
Phoenix AC.** Keep this milestone focused on OTel-span-only Phoenix.

---

## 3. External sources (minimal — researcher 2 owns this lane)

Pointers only:
- Arize Phoenix Docker image: `arizephoenix/phoenix:latest` (already
  named in `.claude/docs/observability-tracing.md:39`).
- Phoenix OTLP intake: gRPC 4317, HTTP 6006 (UI). The OTel SDK already
  in use (`opentelemetry-exporter-otlp-proto-grpc`) is wire-compatible.
- Phoenix env vars and persistent-state volume — researcher 2.

---

## 4. Recommendations (opinionated)

1. **Ship Phoenix as STANDALONE compose, NOT a profile on a non-existent
   base.** Deliver `infra/observability/phoenix-compose.yml`. Invocation:
   `docker compose -f infra/observability/phoenix-compose.yml up -d`.
   Document the standalone form in the runbook; defer base-compose to a
   new E14_S07 milestone (or fold into E14_S05 — see open Q1).
2. **Land the operator doc at `.claude/docs/observability-phoenix.md`** to
   match the E14_S02 precedent. The brief's path
   `docs/observability/phoenix.md` would create a brand-new `docs/`
   subtree with no other operator-facing rationale. Update CLAUDE.md §1
   in the same commit to clarify `docs/ops/` is grandfathered and new
   observability docs land under `.claude/docs/`.
3. **Drop the Prometheus-scrape AC line** from this milestone's scope.
   Phoenix is not a scraper. Move that work to E14_S09.
4. **Verify with `docker compose config --quiet`**, not a live container.
   Live-container UI rendering is a manual smoke test documented in the
   runbook. Add a `tests/test_compose_phoenix.py` that runs
   `docker compose -f infra/observability/phoenix-compose.yml config
   --quiet` when `shutil.which("docker")` is truthy, skipped otherwise.
5. **Keep `otel_endpoint` default at `None`.** Do NOT flip the default
   to `http://127.0.0.1:4317`. Document the export step in the runbook.

---

## Open questions

1. **Does this milestone create the BASE `docker-compose.yml` or only the
   Phoenix layer?** **Recommendation: Phoenix-only, standalone at
   `infra/observability/phoenix-compose.yml`.** The brief deliverable
   "Updated `docker-compose.yml` — Phoenix profile integrated" cannot be
   satisfied — no base exists. Carrying the base into this milestone is
   scope creep (`make up`, ingest service, healthchecks, volumes). File a
   new milestone E14_S07 — "Base docker-compose stack" — as a sibling
   prereq for E14_S05 and E14_S09. Phoenix today: standalone compose
   file, invoked with `docker compose -f infra/observability/phoenix-compose.yml up -d`.
2. **Doc location:** `docs/observability/phoenix.md` (brief literal) OR
   `.claude/docs/observability-phoenix.md` (E14_S02 precedent)?
   **Recommendation: `.claude/docs/observability-phoenix.md`.** Phoenix
   is an opt-in dev/eyeball tool, not a v1 operator runbook on par with
   ingest/cutover.
3. **Phoenix Prometheus scrape:** in scope here or E14_S09?
   **Recommendation: E14_S09.** Phoenix has no embedded scraper; the
   brief is factually wrong on that line.
4. **Automated verification of "Phoenix UI shows spans":**
   `docker compose config --quiet` for YAML + service validation;
   document the live-UI step as a manual smoke section in the runbook.
   Optional: add a `tests/test_otel_phoenix_roundtrip.py` that runs the
   server against an in-process OTLP receiver (NOT real Phoenix) and
   asserts span attribute presence — this is mostly E14_S02 coverage
   already.

---

## External writes the implementation will require

- Pull the `arizephoenix/phoenix:<pinned-tag>` image from Docker Hub
  (researcher 2 names the tag). Egress to docker.io.
- No GitHub, GitLab, or registry writes. All commits land on `main`.
- The Phoenix container writes persistent state to a named docker
  volume; no host-mount required for v1. No filesystem writes outside
  Docker's managed volume tree.

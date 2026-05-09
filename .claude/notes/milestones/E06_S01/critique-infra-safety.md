# Infra-safety critique — E06_S01

**Scope.** The infra diff in commit range `80dfac3..ad8b956`:
- `Makefile` (modified — added `make up` recipe).
- `docker/Dockerfile.server` (NEW — multi-stage runtime image).

No docker-compose, no CI workflow, no other infra files were shipped in this
range (confirmed via `git diff --stat`). Compose lands in E06_S05 per the
brief; this critique treats the Dockerfile as a self-sufficient
single-container artifact.

This critic walks four axes: container hygiene, compose correctness (N/A),
CI safety (N/A), and Makefile/build-script discipline. Severities follow
the hard limits in the prompt: CRITICAL = data loss / security / broken
invariant. HIGH = wrong behavior on common path. MEDIUM = subtle correctness
or missing test. LOW = style.

---

## What was done well

- **Multi-stage build with separate `builder` and `runtime` stages.** The
  builder pulls `build-essential`, `git`, `ca-certificates` for compiling
  torch/pyarrow wheels; the runtime stage starts from a fresh
  `python:3.11-slim` and copies only the populated venv plus source. Final
  image does NOT carry gcc/g++ toolchain — that alone shaves ~700 MB and
  removes a meaningful attack surface (Threat 3 surface reduction).
- **Base image pinned to `python:3.11-slim`.** Major.minor pinning matches
  `requires-python = ">=3.11"` in `pyproject.toml`. A future bump to 3.12
  is a deliberate, single-line change. (A digest pin `@sha256:…` would be
  stricter but is rarely done at Tier-0; flagged below as LOW.)
- **Non-root user.** `arxmcp` UID/GID 1000 created in the runtime stage,
  ownership flipped via `chown -R arxmcp:arxmcp /app`, then `USER arxmcp`
  drops privileges before `EXPOSE`/`ENTRYPOINT`. Order is correct: mkdir →
  chown (as root) → USER. CIS Docker Benchmark 4.1 satisfied.
- **`tini` as PID 1 with explicit `ENTRYPOINT ["/usr/bin/tini", "--"]`.**
  This is the right pattern for FastAPI lifespan shutdown — `docker stop`
  sends SIGTERM to PID 1 (tini), which forwards to uvicorn, which triggers
  the lifespan exit (and the 30-s drain mandated by the brief). Without
  tini, uvicorn-as-PID-1 runs in a context where signal forwarding is
  flaky (SIGTERM gets dropped if no handler is registered, container only
  dies after the 10-s `docker stop --time` SIGKILL).
- **Layer-cache-friendly COPY ordering in builder.** `COPY pyproject.toml`
  precedes the `pip install -e .` layer, so dependency installs are cached
  across source-only edits. Then `COPY server/ ingest/ tools/` invalidates
  only the source-copy layer on a code change. Correct discipline.
- **`apt-get update && install && rm -rf /var/lib/apt/lists/*` chained in
  ONE `RUN` in BOTH stages.** Without the chain, `apt-get update` would
  cache an index in a lower layer and `rm` would only mask it in the
  upper layer (image still ships the full apt index). Both stages get this
  right.
- **Loopback-only bind preserved in `make up`.** `--host 127.0.0.1` is
  explicit; container deployments expose via `-p 127.0.0.1:7733:7733`.
  Threat 4 mitigation is consistent across both deployment modes.
- **No secrets in env.** The only `ENV` declarations are
  `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `PATH`, and the bind
  host/port. No HF tokens, no API keys, no credentials. Operators wanting
  HF tokens at runtime should pass `-e HF_TOKEN=...` at `docker run` time
  (out of scope for this image but worth a doc note).
- **Surface-reduction discipline.** `--no-install-recommends` on every
  apt install. `PIP_NO_CACHE_DIR=1` and `PIP_DISABLE_PIP_VERSION_CHECK=1`
  in the builder. `--no-access-log` on the uvicorn CMD (Prometheus is the
  source of truth for request observability, per the brief).
- **`.PHONY` updated correctly.** The line `.PHONY: help bootstrap test
  eval up ingest` already includes `up`, so the new recipe doesn't
  collide with a hypothetical file called `up`.
- **Python-version guard mirrors `make test` and `make eval`.** The
  `@$(PYTHON) -c "import sys; assert sys.version_info >= ..."` preamble
  on `make up` is byte-for-byte the same idiom as the other targets.
  Discipline is consistent.
- **Makefile comment on `make up` documents loopback-only and the BGE-M3
  cold-start (~5–30 s).** Operators know what to expect before they run
  the recipe.

---

## Findings

### IS1 — `pip install -e .` in builder stage breaks at runtime [CRITICAL]

**The bug.** In the builder stage:

```dockerfile
WORKDIR /build
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -e .
COPY server/ ./server/
COPY ingest/ ./ingest/
COPY tools/ ./tools/
```

Then in the runtime stage:

```dockerfile
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/server ./server
COPY --from=builder /build/ingest ./ingest
COPY --from=builder /build/tools ./tools
```

The runtime stage's `WORKDIR` is `/app`, so the source tree lands at
`/app/server`, `/app/ingest`, `/app/tools`. But the venv at `/opt/venv`
was populated by `pip install -e .` run from `WORKDIR /build`. PEP 660
editable installs (the modern default for `pip install -e .` against a
PEP 517 backend) write a `__editable__.arxmcp-0.1.0.pth` file (or a
`MetaPathFinder` shim) into
`/opt/venv/lib/python3.11/site-packages/` whose payload is the
absolute path `/build` — the directory `pip install -e .` was run from.

When the runtime container starts uvicorn, Python's import machinery
walks the `.pth` files, adds `/build` to `sys.path`, and looks for
`server/__init__.py` at `/build/server/__init__.py`. That path does
not exist in the runtime image (only `/app/server/__init__.py` does),
so `import server.main` fails with `ModuleNotFoundError`. uvicorn
crashes before binding the socket; `docker run` exits non-zero.

**Worse:** because `pyproject.toml` has NO `[build-system]` section
(verified via `grep build-system pyproject.toml` — no matches) and no
`[tool.setuptools]` packages declaration, the editable-install behavior
is whatever pip's fallback backend does. Recent pip (≥21.3) defaults to
PEP 660 with a backend-chosen `__editable__` mechanism; without explicit
`packages = [...]` declaration, setuptools auto-discovers `server`,
`ingest`, `tools` as top-level packages and writes `.pth` entries
pointing at `/build`. Either way, the path is baked at install time
and does not survive the stage transition.

**Why this wasn't caught.** No `docker build && docker run` smoke test
runs in CI for this milestone (CI was N/A per the brief). The unit
tests in `tests/test_server_startup.py` exercise `create_app()`
directly via in-process Python — they never go through the Docker
build path. So the broken image is undetectable by `make test`.

**Fix options (pick one):**

1. **Move `WORKDIR` to `/app` in the builder so paths match runtime.**
   Change `WORKDIR /build` → `WORKDIR /app`, and update the `COPY
   --from=builder /build/...` lines to `COPY --from=builder /app/...`.
   Then the editable install's `.pth` file points at `/app`, which
   exists in the runtime image.
2. **Build a wheel in builder, install it in runtime.** Drop `pip
   install -e .` entirely; instead `pip wheel . -w /wheels`, then in
   the runtime stage `pip install /wheels/*.whl`. The runtime stage no
   longer depends on source layout — the wheel ships a self-contained
   `arxmcp-0.1.0` install. (This is the cleanest fix and matches
   typical production discipline.)
3. **Re-run `pip install -e .` in the runtime stage from `/app`.** Adds
   ~15 s to the build, requires keeping `pip` + a build backend in the
   runtime image. Works but feels hacky.

**Recommendation: option 2.** A wheel install is the canonical
multi-stage Python pattern; Tier-0 can absorb the slightly longer
builder runtime. As a bonus, it removes the tacit assumption that the
`/build` path string is load-bearing.

**Also fix:** add a `[build-system]` section to `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["server", "ingest", "tools"]
```

Without `[tool.setuptools.packages]`, setuptools' auto-discovery
fights with the `var/`, `tests/`, `docs/`, `infra/`, `shim/` siblings
and will refuse to build (the "multiple top-level packages discovered
in a flat-layout" error). The current `pip install -e .` works in dev
because `bootstrap` happens to run with auto-discovery quirks
tolerating it; under a fresh `pip wheel` invocation in a Docker
builder, it will likely fail.

**Severity rationale.** This is CRITICAL by the prompt's definition:
"broken invariant" — the image does not run. Anyone who follows the
README's `docker run --rm -p 127.0.0.1:7733:7733 …` invocation gets a
crashed container. Closing this is the gate for E06_S01 to be
considered shipped.

### IS2 — No `.dockerignore` ships with the build context [HIGH]

**The bug.** `find . -maxdepth 2 -name .dockerignore` returns nothing.
Without one, `docker build .` ships the ENTIRE working directory as
build context: `var/arxmcp/` (LanceDB blobs, downloaded papers,
parser failures), `.git/` (full repo history), `.claude/` (notes,
state, sub-agent outputs), `tests/`, `docs/`, `infra/`, the `shim/`
tree.

Today the worktree's `var/` is only 344 KB (verified), but a real
deployment with the seed corpus indexed will ship 100s of MB to GBs
into the build context. Three concrete impacts:

1. **Build performance.** Every `docker build` walks the entire tree
   to construct the tar context. With LanceDB blobs in `var/`, this
   is multi-second overhead on every iteration.
2. **Image bloat risk.** The Dockerfile's selective `COPY
   server/ ingest/ tools/` mitigates this (the bloat doesn't reach
   the final image), BUT a future `COPY . .` regression would silently
   ship `var/arxmcp/` into the image. A `.dockerignore` is defense
   in depth against that footgun.
3. **Secret leakage risk.** `.git/` in the build context means git
   blobs are visible to any builder process. If a developer ever
   commits a secret and immediately rotates it (a common scenario),
   the secret is still in `.git/objects` and ships into every build
   context. A `.dockerignore` excluding `.git/` closes this.

**Fix.** Add a `.dockerignore` at the repo root:

```
.git/
.claude/
var/
tests/
docs/
infra/
**/__pycache__/
**/*.pyc
**/*.pyo
.venv/
.ruff_cache/
.pytest_cache/
*.egg-info/
```

**Severity rationale.** HIGH because (a) build performance degrades
silently as the corpus grows, and (b) the missing `.dockerignore` is
a footgun for future `COPY . .` patterns. Not CRITICAL because today's
selective COPY does not actually leak `var/` into the image.

### IS3 — `make up` hardcodes 7733, ignores `ARXMCP_BIND_PORT` [HIGH]

**The bug.** The recipe is:

```makefile
$(PYTHON) -m uvicorn server.main:app --host 127.0.0.1 --port 7733 --lifespan on
```

But `server/config.py`'s `Config.bind_port` honors `ARXMCP_BIND_PORT`
(it's the canonical knob), and the recipe's preceding comment
explicitly says "Override the bind via ARXMCP_BIND_PORT". Today, an
operator who exports `ARXMCP_BIND_PORT=7700` and runs `make up` gets
the server bound to 7733 — the env var is silently ignored because
uvicorn's `--port` CLI flag wins over the config-file value.

This is a wrong-behavior-on-the-common-path bug. Two scenarios:

1. **Multi-server local dev.** A developer runs two arxmcp instances
   side-by-side (e.g. one against the prod corpus, one against a
   test corpus); they expect `ARXMCP_BIND_PORT=7700 make up` to
   move the second to 7700. It doesn't.
2. **Conflict with a colocated service.** If 7733 is already taken
   on the host (some other dev tool), the operator can't move
   arxmcp out of the way without editing the Makefile.

**Fix.** Two reasonable shapes:

**Option A (let server/main.py read Config and bind itself).** Drop
`--host` and `--port` from the uvicorn invocation; `server/main.py`
already has a `__main__` block (lines 280–293) that calls
`uvicorn.run(...)` with `cfg.bind_host, cfg.bind_port`. Change `make
up` to `$(PYTHON) -m server.main`. The Config class then governs both
the dev path and the container path.

**Option B (Makefile vars).** Add `ARXMCP_BIND_HOST ?= 127.0.0.1` and
`ARXMCP_BIND_PORT ?= 7733` at the top of the Makefile and interpolate
into the recipe: `--host $(ARXMCP_BIND_HOST) --port
$(ARXMCP_BIND_PORT)`. This honors `make up
ARXMCP_BIND_PORT=7700` directly and falls back to the canonical
defaults. (Slightly worse than option A because the loopback-only
validator in `Config` doesn't fire on the make path — an operator who
sets `ARXMCP_BIND_HOST=0.0.0.0` would bypass the Threat 4 guard.)

**Recommendation: option A.** Routes both dev and container through
`Config()`, which is the only place the loopback-only check fires.
The single source of truth wins.

**Severity rationale.** HIGH because (a) the Makefile comment
explicitly advertises the env-var override, (b) the user-visible
behavior contradicts the documentation, and (c) option A's fix also
closes a latent Threat 4 bypass on the dev path.

### IS4 — Dockerfile `ARXMCP_BIND_PORT` env is set but uvicorn CMD hardcodes 7733 [HIGH]

**The bug.** Same shape as IS3. The runtime stage declares:

```dockerfile
ENV ARXMCP_BIND_HOST=127.0.0.1 \
    ARXMCP_BIND_PORT=7733
```

…suggesting the env vars are the canonical knobs. But the CMD
hardcodes them again:

```dockerfile
CMD ["uvicorn", "server.main:app", \
     "--host", "127.0.0.1", \
     "--port", "7733", \
     "--lifespan", "on", \
     "--no-access-log"]
```

An operator who runs:

```sh
docker run --rm -e ARXMCP_BIND_PORT=7700 -p 127.0.0.1:7700:7700 arxmcp-server:dev
```

gets a container that reads `ARXMCP_BIND_PORT=7700` from env (and
`Config.bind_port` reflects 7700), but uvicorn binds to 7733 because
the CLI flag wins. The host port-mapping `127.0.0.1:7700:7700` then
fails to forward (nothing listening on 7700 inside the container);
healthcheck against `http://127.0.0.1:7733/readyz` succeeds, but
external connectivity is broken. Confusing.

**Fix.** Change the CMD to `["python", "-m", "server.main"]` (or an
entrypoint shim that reads the env vars and constructs the uvicorn
invocation). `server/main.py`'s `__main__` block already handles this.
Same fix as IS3 — both call sites should defer to `Config`.

Alternatively, drop the `ARXMCP_BIND_PORT`/`ARXMCP_BIND_HOST` ENV
declarations from the Dockerfile entirely (they're misleading) and
document that the container always binds to 7733; operators move the
port at the host-mapping level. That's a smaller change but worse UX.

**Severity rationale.** HIGH for the same reasons as IS3. Pairs with
IS3 — fix them together.

### IS5 — Healthcheck `--start-period=60s` may be tight for first-run model download [MEDIUM]

**The bug.** `HEALTHCHECK --start-period=60s` gives the container 60 s
of grace before unhealthy probes start counting. The Dockerfile's own
comment acknowledges the risk:

> 30-second health budget — well under uvicorn's default startup, but
> the eager BGE-M3 load can take longer on first run. Operators with
> slow model downloads should set `--start-period=2m` at deploy time.

But `HEALTHCHECK` is baked into the image; operators cannot override
`--start-period` from `docker run` (only from compose/swarm/k8s
deployment manifests). On a clean build with no HF cache mounted,
BGE-M3 downloads ~2.3 GB of safetensors over the network — at 50
Mbps that's ~6 minutes, vastly exceeding 60 s. The container will
flap unhealthy → restart → unhealthy → restart on a slow link, never
becoming healthy.

**Fix.** Pick the worst-case first-run number (2 minutes covers a
gigabit link; 5 minutes covers most home broadband) and set
`--start-period=5m`. Or document that the image expects the HF cache
to be pre-populated via a bind mount (`-v
~/.cache/huggingface:/home/arxmcp/.cache/huggingface`) and the
60 s budget assumes a warm cache. The doc-only path is acceptable but
the AC should call out the requirement.

Better: log a warning at startup if `transformers` is downloading
weights at lifespan time (it logs progress to stderr by default; the
operator can see it but `/readyz` doesn't reflect it). A future
milestone could add a "downloading model" sub-state to `/readyz`.

**Severity rationale.** MEDIUM. Affects only the first-run path on a
slow link without a pre-populated HF cache; warm-cache restarts are
fine. Not CRITICAL because the operator can work around it via
compose/k8s overrides.

### IS6 — `chown -R arxmcp:arxmcp /app` is heavier than needed [LOW]

The runtime stage runs `chown -R arxmcp:arxmcp /app` after creating
`/app/var/arxmcp/...`. This recursively chowns every file in `/app`,
including the source tree (`/app/server`, `/app/ingest`, `/app/tools`)
and `pyproject.toml`/`README.md`. Source files don't need to be owned
by `arxmcp` — they only need to be readable, and root-owned files are
world-readable by default.

The chown adds a writable layer with every inode duplicated (since
chown rewrites ownership metadata), inflating image size by ~10–50 MB
depending on dep tree. A more surgical pattern is:

```dockerfile
RUN mkdir -p /app/var/arxmcp/index/lancedb \
            /app/var/arxmcp/corpus/chunks \
            /app/var/arxmcp/ops \
    && chown -R arxmcp:arxmcp /app/var
```

Source tree stays root-owned (still readable to `arxmcp`); only `/app/var`
is writable. Combined with `docker run --read-only --tmpfs /tmp` at
runtime (operator's choice), this gives a properly read-only container
with `/app/var` as the only writable bind mount.

**Severity rationale.** LOW. Image is functional today; this is an
optimization + a stepping stone to enforced read-only FS in E06_S05.

### IS7 — Image does not enforce `--read-only` posture [LOW]

The brief mentions read-only FS as a hardening axis. The Dockerfile
makes no declarative claim about read-only — it doesn't `VOLUME
/app/var/arxmcp` (which would document the expected writable mount
point) and it doesn't enforce the `--read-only` flag from the image.

Adding `VOLUME /app/var/arxmcp` would (a) document the writable
mount-point contract and (b) make `docker run --read-only` work
(the volume continues to be writable while the rest of the FS is
read-only). With IS6's narrower chown, this would land cleanly.

**Severity rationale.** LOW. Documentation/UX improvement; doesn't
block the milestone.

### IS8 — `pip` and apt-installed `git` linger in the runtime image [LOW]

The runtime image inherits `pip` from `python:3.11-slim` (acceptable —
removing it would break `pip --user` workflows for operators who
shell into the container). `git` is NOT installed in the runtime
stage (only in builder), so that's correct.

But the runtime stage installs `tini`, `curl`, `ca-certificates` and
keeps the `apt-get` machinery. `curl` is required by the HEALTHCHECK;
it's the lightest acceptable choice. An alternative is to drop `curl`
in favor of a pure-Python healthcheck:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7733/readyz', timeout=4).status==200 else 1)" \
        || exit 1
```

…which removes `curl` (saving ~5 MB and a CVE-prone binary). Worth
considering for E06_S05's hardening pass; not load-bearing today.

**Severity rationale.** LOW. Minor surface reduction.

### IS9 — Image lacks an `OCI` label set for provenance [LOW]

No `LABEL org.opencontainers.image.source`, `…revision`, `…version`,
or `…licenses` declarations. Operators inspecting the image with
`docker inspect` get no metadata about which commit produced it. For
a Tier-0 dev image, this is acceptable; for E06_S05's production
hardening pass, OCI labels populated from build args (`--build-arg
GIT_SHA=...`) become important for incident response.

**Severity rationale.** LOW. Tier-0 acceptable; flag for E06_S05.

### IS10 — Base image not pinned by digest [LOW]

`FROM python:3.11-slim` resolves to whichever `3.11-slim` tag is current
at build time. A future docker-hub repush could silently change the
underlying contents (e.g. a CVE patch that also bumps a transitive lib
version). Pinning by digest (`FROM python:3.11-slim@sha256:…`) makes
builds bit-reproducible.

This is rarely done at Tier-0 because the digest churn becomes a
maintenance burden (renovate-bot territory). Acceptable as-is for
v1; flag for the supply-chain hardening pass.

**Severity rationale.** LOW.

### IS11 — `EXPOSE 7733` is documentation-only; README doesn't include port-mapping example [LOW]

The Dockerfile's docstring shows `docker run --rm -p 127.0.0.1:7733:7733
-v "$PWD/var/arxmcp:/app/var/arxmcp" arxmcp-server:dev` — that's the
correct invocation. But `server/README.md` § "Run in Docker" only
points at the Dockerfile and doesn't reproduce the run command. An
operator who reads the README without opening the Dockerfile won't
see the port-mapping requirement.

**Fix.** Copy the `docker run` example into `server/README.md`. Tiny
docs touch; closes a friction point for first-time operators.

**Severity rationale.** LOW.

### IS12 — `--lifespan on` flag is uvicorn default since 0.18; redundant [LOW]

`make up` and the Dockerfile CMD both pass `--lifespan on`. Since
uvicorn 0.18 (released 2022-05), `lifespan="auto"` is the default and
upgrades to `on` automatically when the ASGI app exposes a lifespan
context (FastAPI does). The explicit flag is harmless but noisy.

Worth keeping if the goal is to make the lifespan dependency obvious
to readers; worth dropping if the goal is minimal CLI noise. Either
way is fine; flagging only because the prompt asked for a careful
review.

**Severity rationale.** LOW (style).

### IS13 — Healthcheck `curl` runs every 30 s under `arxmcp` user; auth boundary [LOW]

The HEALTHCHECK runs `curl` inside the container as the `arxmcp` user
(USER directive applies to HEALTHCHECK since Docker 20.10). The `curl`
hits `http://127.0.0.1:7733/readyz` — no auth, no body, response is
small. The 30-s cadence is reasonable; under load, that's negligible
compared to the actual MCP traffic.

One minor concern: `curl -fsS` exits non-zero on HTTP 503, which is
the intended pre-warm state. During the `--start-period=60s` window
this is fine (Docker doesn't count failures during start-period).
After 60 s, three consecutive 503s flip the container unhealthy —
this is the IS5 risk on slow-download paths. No additional fix
beyond IS5.

**Severity rationale.** LOW. Documenting the chain of behavior so a
future critic sees it.

---

## Summary table

| ID  | Severity  | Area                | One-liner                                                            |
|-----|-----------|---------------------|----------------------------------------------------------------------|
| IS1 | CRITICAL  | Dockerfile          | `pip install -e .` from `/build` breaks imports at `/app` runtime    |
| IS2 | HIGH      | Build context       | No `.dockerignore` — ships `var/`, `.git/`, `.claude/` into context  |
| IS3 | HIGH      | Makefile            | `make up` hardcodes 7733; ignores `ARXMCP_BIND_PORT`                 |
| IS4 | HIGH      | Dockerfile          | Container CMD hardcodes 7733; ignores `ARXMCP_BIND_PORT` env         |
| IS5 | MEDIUM    | Dockerfile          | `--start-period=60s` tight for first-run BGE-M3 download             |
| IS6 | LOW       | Dockerfile          | `chown -R /app` heavier than needed; chown only `/app/var`           |
| IS7 | LOW       | Dockerfile          | No `VOLUME` declaration; no read-only-FS posture documented          |
| IS8 | LOW       | Dockerfile          | `curl` for healthcheck could be replaced by pure-Python urllib       |
| IS9 | LOW       | Dockerfile          | No OCI labels for provenance                                          |
| IS10| LOW       | Dockerfile          | Base image not pinned by digest                                       |
| IS11| LOW       | Docs                | README missing the `docker run` example with port mapping             |
| IS12| LOW       | Both                | `--lifespan on` is uvicorn default since 0.18; redundant              |
| IS13| LOW       | Dockerfile          | Healthcheck `curl` is fine; documenting the 503 chain for future     |

---

## Verification checklist for the rectifier

Before declaring IS1 closed, the rectifier MUST:

1. Build the image locally: `docker build -f docker/Dockerfile.server
   -t arxmcp-server:e06s01-test .`
2. Run it without a corpus (expect a fast-fail with the
   `corpus-version.json missing` message, NOT `ModuleNotFoundError:
   No module named 'server'`):
   `docker run --rm arxmcp-server:e06s01-test`
3. With a stub corpus mount, confirm `/healthz` returns 200 within
   5 s and `/readyz` flips to 200 within 60 s on a warm HF cache.
4. `docker stop` the running container and time the SIGTERM →
   process-exit window. The 30-s drain mandated by the brief should
   complete in under 5 s for an idle container.

For IS3 + IS4: `ARXMCP_BIND_PORT=7700 make up` and `docker run -e
ARXMCP_BIND_PORT=7700 -p 127.0.0.1:7700:7700 arxmcp-server:test
curl http://127.0.0.1:7700/healthz` should both return 200.

For IS2: `du -sh $(docker build --no-cache -f
docker/Dockerfile.server . 2>&1 | grep 'Sending build context' )` —
verify the context size is bounded after `.dockerignore` lands.

Pass these and IS1–IS5 are demonstrably closed.

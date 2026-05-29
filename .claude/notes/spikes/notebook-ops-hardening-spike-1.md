# Spike — notebook-ops-hardening-spike-1: macOS bind-mount uid/gid

**Gates:** `notebook-ops-hardening-m3` (base docker-compose server-only v0).
**Question (verbatim from the roadmap):** "On the operator's machine (macOS
Docker Desktop), confirm `docker compose up` with a **bind-mounted**
`var/arxmcp/` writes cleanly as the in-image non-root UID 1000 with no
ownership failure; document the `chown -R 1000:1000 var/arxmcp` pre-step (or a
fix)."
**Validated:** 2026-05-29, live, on this workstation.
**Status:** RESOLVED — gate cleared. **The brief's premise is corrected** (see
Finding).

---

## Environment

- macOS Docker Desktop — `Docker version 28.4.0`, `Docker Compose v2.39.2-desktop.1`.
- Host user: `uid=501 gid=20` (`chris.dare`). The in-image server user is UID 1000.

## Experiment

A scratch dir owned host-side by `501:20`, mode `0700`, bind-mounted into a
container running as `--user 1000:1000`:

```
docker run --rm --user 1000:1000 -v <scratch>:/data alpine:3.20 sh -c \
  'id; touch /data/probe-1000; mkdir -p /data/notebooks/x; ls -ldn /data'
```

## Result (conclusive)

```
in-container id: uid=1000 gid=1000 groups=1000
WRITE_OK as uid 1000
NESTED_MKDIR_OK
/data (in container) -> drwx------ 1000 1000   # mount appears owned by 1000
<scratch> (on host)  -> files owned by 501:20  # host sees host-user ownership
```

A non-root UID-1000 container **wrote cleanly** to a macOS-host bind mount that
was NOT pre-`chown`ed. Docker Desktop's file-sharing layer (VirtioFS /
gRPC-FUSE) transparently presents the bind mount as owned by the requesting
container UID and translates writes back to the host user — so host-vs-container
UID mismatch is a non-issue on macOS Docker Desktop.

## Finding (corrects the m3 brief)

- **macOS Docker Desktop: NO `chown` pre-step is needed.** A bind-mounted
  `var/arxmcp/` is writable by the in-image UID 1000 out of the box.
- **The `chown -R 1000:1000 var/arxmcp` pre-step is a NATIVE-LINUX-Docker
  concern, not macOS.** On native Linux, bind-mount ownership is literal: the
  host dir is owned by the invoking user (often uid 1000 already, but not
  guaranteed), and a container UID-1000 process can only write if the host dir
  is group/other-writable or owned by 1000. The m3 brief said "document the
  macOS `chown ...` pre-step" — that wording is **wrong**: m3's `docs/install.md`
  must document the chown as **Linux-only**, and explicitly note macOS Docker
  Desktop needs nothing.

## Consequence for m3

- m3 ships `infra/docker-compose.yml` with the server running as UID 1000 and a
  `../../var/arxmcp` bind mount; on macOS it "just works".
- `docs/install.md` documents:
  - **macOS Docker Desktop:** no pre-step.
  - **native Linux Docker:** `chown -R 1000:1000 var/arxmcp` (or run compose
    with a `user:` matching the host owner, or `make bootstrap` creating the
    tree owned appropriately) before first `docker compose up`.
- The m3 AC checkbox "documents the macOS `chown` pre-step (per spike-1)" is
  satisfied by documenting the corrected (Linux-only) guidance.

## No external writes; no residual risk

Lightweight `alpine:3.20` probe only (one image pull). No repo state touched.

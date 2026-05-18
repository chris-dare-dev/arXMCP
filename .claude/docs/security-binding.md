# `ARXMCP_BIND_HOST` and `ARXMCP_UNSAFE_NETWORK_BIND` — binding discipline

This document explains the localhost-only binding rule, the
container-deployment escape hatch, and the operational guidance that
goes with the escape hatch.

**TL;DR**

- **By default** arXMCP refuses to bind to anything except
  `127.0.0.1`, `::1`, or `localhost`. Setting `ARXMCP_BIND_HOST=0.0.0.0`
  raises `ValidationError` at config parse — the server refuses to
  start.
- **For container deployments**, set `ARXMCP_UNSAFE_NETWORK_BIND=1`
  ALONGSIDE `ARXMCP_BIND_HOST=0.0.0.0`. The container's internal bind
  is then permitted; the SAFETY then depends on the Docker host-port
  mapping pinning the host side to 127.0.0.1.
- **Never** set `ARXMCP_UNSAFE_NETWORK_BIND=1` on a bare-metal
  network-reachable host. That trivially exposes the unauthenticated
  MCP API to the network.

---

## Why localhost-only is the default

The MCP 2025-06-18 spec recommends:

> When running locally, servers **SHOULD** bind only to localhost
> (127.0.0.1) rather than all network interfaces (0.0.0.0).

arXMCP v1 is a **single-user, single-workstation, unauthenticated**
deployment per `.claude/notes/01-mission-and-context.md`. There is no
authentication layer; the API exposes the user's research corpus, query
embeddings, and tool surface to whoever can reach the port.

If the server binds `0.0.0.0` on a network-reachable host (laptop on
public Wi-Fi, dev workstation on a corp LAN, cloud VM with an open
firewall), any neighbor on the network can connect and use the API.
The `Origin` / `Host` / `Sec-Fetch-Site` defenses block BROWSER
attacks (DNS rebinding, cross-site fetches) but do nothing against
direct HTTP clients (curl, custom scripts).

The default-deny posture is enforced at config parse:

```python
# server/config.py
@model_validator(mode="after")
def reject_non_loopback_bind(self) -> "Config":
    if self.bind_host not in LOOPBACK_HOSTS and not self.unsafe_network_bind:
        raise ValueError(...)
    return self
```

Setting `ARXMCP_BIND_HOST=0.0.0.0` without the escape hatch raises
`ValidationError`, which `server/main.py` catches and exits with code 1.
The operator sees a clear error message pointing at this document.

---

## When the escape hatch IS appropriate

**Containerized deployments where Docker pins the host port to
127.0.0.1.**

A typical compose snippet (this is what the main `docker-compose.yml`
will look like when E14 ships it; today the design note documents the
pattern):

```yaml
services:
  arxmcp-server:
    image: arxmcp/server:0.1.0
    environment:
      - ARXMCP_BIND_HOST=0.0.0.0
      - ARXMCP_UNSAFE_NETWORK_BIND=1   # explicit opt-in for container
    ports:
      - "127.0.0.1:7733:7733"          # host-side pin to loopback
    # ... other config
```

Why this is safe:

1. The **container internal** binds 0.0.0.0 — but that's the container's
   isolated network namespace, not the host's.
2. The **host-side port mapping** is `127.0.0.1:7733:7733`. Docker
   listens on the host's 127.0.0.1:7733 and forwards to the container's
   0.0.0.0:7733. Network traffic from outside the host CANNOT reach the
   container — Docker only forwards from the loopback interface.
3. The `ARXMCP_UNSAFE_NETWORK_BIND=1` flag makes the trade-off
   **explicit**: the operator is acknowledging that the container's
   internal bind is non-loopback and that the host-side pinning is the
   actual security perimeter.

A WARN log fires at startup whenever the flag is set:

```
WARNING ARXMCP_UNSAFE_NETWORK_BIND=1 is set; server binding to '0.0.0.0'
        (non-loopback). Container deployments only — the host-side port
        mapping MUST still pin to 127.0.0.1.
```

---

## When the escape hatch is NEVER appropriate

- **Bare-metal deployments.** Running arXMCP directly on a host without
  a container around it. If you set `ARXMCP_UNSAFE_NETWORK_BIND=1` here,
  you are exposing the unauthenticated API to the network.

- **Container deployments without host-port pinning.** A compose with
  `ports: "7733:7733"` (no `127.0.0.1:` prefix) maps to the host's
  0.0.0.0:7733. Setting `ARXMCP_UNSAFE_NETWORK_BIND=1` in this
  combination is equivalent to a bare-metal 0.0.0.0 bind — exposed.

- **Multi-user / multi-tenant** deployments. v1 is single-user. If you
  need multi-user, you need authentication first (out of v1 scope) and
  then a different binding strategy.

- **CI / cloud-VM deployments** where the host's network interface is
  reachable from outside. Even with `127.0.0.1:` host-side pinning, the
  cloud VM's firewall rules become the perimeter — a misconfigured
  security group can expose port 7733 to the world.

---

## Reverse-proxy deployments (deferred)

If arXMCP is deployed behind nginx / traefik / Caddy (e.g. for TLS
termination), the proxy rewrites the `Host` header. The current
`HostValidationMiddleware` rejects requests whose Host is not in the
loopback set — which a proxy-forwarded request will fail (the proxy
forwards the upstream service's hostname).

**v1 does not support reverse-proxy deployments.** The discipline is
"single-user, single-workstation, no proxy." If a reverse-proxy
deployment is needed, a future milestone should add a `trusted_proxies`
configuration knob to bypass the Host check for whitelisted upstream
IPs. Filed as future work in the threat-5 audit.

---

## Operational checklist for container deployments

Before flipping `ARXMCP_UNSAFE_NETWORK_BIND=1`:

- [ ] The deployment is INSIDE a Docker / Podman / containerd container.
- [ ] The container compose / Kubernetes / nomad config pins the host-
  side port mapping to `127.0.0.1:7733` (or the equivalent loopback IP
  in the host network namespace).
- [ ] The host is NOT a public-facing server. If the host's network
  interface is reachable from the internet, the firewall is your
  perimeter — verify it independently.
- [ ] The WARN log at startup is being captured (not silently dropped).
  If the operator can't see the WARN, the trade-off is invisible.

After flipping the flag:

- [ ] Verify the host port mapping with `docker ps` / `kubectl get
  services` — confirm 127.0.0.1 in the host-side address.
- [ ] Verify the host's firewall rejects external connections to
  port 7733 (e.g. `nc -v <public-ip> 7733` from another host should fail).
- [ ] Confirm the startup WARN log fired in the container's log
  pipeline.

---

## Regression coverage

The full regression suite for this binding discipline lives at
`tests/security/test_bind_regression.py` (owned by **E13_S09**).
E13_S05 ships these initial guards in
`tests/security/test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch`:

- `test_bind_zero_zero_rejected_without_unsafe_flag` — Config raises
  ValidationError on `ARXMCP_BIND_HOST=0.0.0.0` alone.
- `test_bind_zero_zero_accepted_with_unsafe_flag` — Config validates
  successfully when both env vars are set.
- `test_loopback_bind_accepted_with_or_without_unsafe_flag` — the flag
  only matters for non-loopback values.
- `test_public_ip_bind_rejected_without_unsafe_flag` — same default-deny
  for public IPs.
- `test_loopback_hosts_includes_expected_set` — regression guard on the
  `LOOPBACK_HOSTS` constant.

The existing `tests/test_security.py::TestStartupRejectsBadBind` covers
the subprocess-level startup-refusal path (running `python -m server.main`
with `ARXMCP_BIND_HOST=0.0.0.0` and asserting a non-zero exit code).

---

## References

- `.claude/notes/08-security-observability-ops.md` § Threat 5
- `.claude/docs/security-threat-5-audit.md` — companion audit
- `server/config.py::reject_non_loopback_bind` — the validator
- MCP 2025-06-18 spec — Streamable HTTP Security Warning
- E13_S09 — full bind regression test suite (pending milestone)

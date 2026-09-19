#!/usr/bin/env python3
"""Live-server soundness smoke for the hardened ``lean_verify``
(stage2/arx-d2 — WS-D D-2/D-4 integration instrument).

Drives the REAL MCP wire against a running arxmcp server (loopback
only): ``initialize`` → ``notifications/initialized`` → three
``tools/call lean_verify`` probes, then applies the proven-formal
award predicate exactly as the proving lane will:

1. **Kernel positive control** — ``kat-tf-05``-shaped snippet
   (``1 + 1 = 2``); must award ``proven-formal`` (axiom audit ok,
   empty closure).
2. **AC-D.1 axiom canary** — ``axiom cheat : …``; must be REJECTED by
   the snippet guard with the award denied. Any award here means the
   soundness hardening is not live on the wire — exit loud.
3. **Mathlib positive control** — ``irrational_sqrt_two``; must award
   ``proven-formal`` with the closure inside the standard trust base
   and non-null toolchain + mathlib-rev provenance. Skipped (honestly)
   when the server's REPL has no mathlib (pass ``--no-mathlib``).

Wire contract mirrors ``shim/arxmcp_shim.py``: JSON response mode,
``Mcp-Session-Id`` echo after initialize, ``Mcp-Protocol-Version:
2025-06-18``, POST ``/mcp/``. Loopback host enforced (Threat 4).

Exit codes: 0 = all live probes behaved; 1 = a probe misbehaved
(details printed); 2 = transport/handshake failure.

Usage (server already running with ``ARXMCP_ENABLE_LEAN=true``)::

    python -m tools.soundness_smoke [--server http://127.0.0.1:7733]
                                    [--no-mathlib]
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import urllib.parse
from typing import Any

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Mcp-Protocol-Version": "2025-06-18",
}

_KERNEL_POSITIVE = {
    "snippet": "theorem smoke_pos : 1 + 1 = 2 := rfl",
    "imports": [],
}
_AXIOM_CANARY = {
    "snippet": (
        "axiom cheat : (1 : Nat) + 1 = 3\n"
        "theorem smoke_canary : (1 : Nat) + 1 = 3 := cheat"
    ),
    "imports": [],
}
_MATHLIB_POSITIVE = {
    "snippet": (
        "theorem smoke_sqrt2 : Irrational (Real.sqrt 2) := irrational_sqrt_two"
    ),
    "imports": ["Mathlib.NumberTheory.Real.Irrational"],
}


class _Wire:
    """Minimal JSON-mode Streamable-HTTP MCP client (smoke-grade)."""

    def __init__(self, url: str, timeout: float = 120.0) -> None:
        p = urllib.parse.urlparse(url)
        host = (p.hostname or "").lower()
        if p.scheme != "http" or host not in LOOPBACK_HOSTS:
            raise SystemExit(
                f"FATAL: --server must be http:// on a loopback host "
                f"({sorted(LOOPBACK_HOSTS)}); got {url!r}"
            )
        self._conn = http.client.HTTPConnection(
            host, p.port or 80, timeout=timeout
        )
        self._sid: str | None = None
        self._next_id = 0

    def post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        body = json.dumps(payload).encode("utf-8")
        headers = {**HEADERS, "Content-Length": str(len(body))}
        if self._sid is not None:
            headers["mcp-session-id"] = self._sid
        self._conn.request("POST", "/mcp/", body=body, headers=headers)
        resp = self._conn.getresponse()
        raw = resp.read()
        self._sid = resp.getheader("mcp-session-id") or self._sid
        if resp.status not in (200, 202):
            raise SystemExit(
                f"FATAL: /mcp/ returned HTTP {resp.status}: {raw[:400]!r}"
            )
        if not raw:
            return None  # notifications get 202/empty
        return json.loads(raw)

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._next_id += 1
        frame: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        if params is not None:
            frame["params"] = params
        out = self.post(frame)
        if out is None or "error" in out:
            raise SystemExit(f"FATAL: {method} failed: {out!r}")
        return out["result"]

    def notify(self, method: str) -> None:
        self.post({"jsonrpc": "2.0", "method": method})

    def call_lean_verify(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.rpc(
            "tools/call", {"name": "lean_verify", "arguments": arguments}
        )
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise SystemExit(
                f"FATAL: lean_verify returned no structuredContent: {result!r}"
            )
        return structured


def _award(result: dict[str, Any]) -> tuple[bool, list[str]]:
    from server.lean_soundness import formal_award_ok

    return formal_award_ok(result)


def _brief(result: dict[str, Any]) -> str:
    s = result.get("soundness") or {}
    p = result.get("provenance") or {}
    return (
        f"status={result.get('status')} guard={s.get('guard')} "
        f"audit={s.get('audit_status')} closure={s.get('axiom_closure')} "
        f"closure_ok={s.get('axiom_closure_ok')} flags={s.get('flags')} "
        f"toolchain={p.get('lean_toolchain')} "
        f"mathlib_rev={str(p.get('mathlib_rev'))[:12]} "
        f"transcript={str(p.get('transcript_sha256'))[:16]}…"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="soundness-smoke")
    ap.add_argument("--server", default="http://127.0.0.1:7733")
    ap.add_argument(
        "--no-mathlib",
        action="store_true",
        help="skip the mathlib positive control (kernel-only REPL)",
    )
    args = ap.parse_args(argv)

    wire = _Wire(args.server)
    init = wire.rpc(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "soundness-smoke", "version": "1"},
        },
    )
    server_info = init.get("serverInfo", {})
    print(f"server: {server_info.get('name')} {server_info.get('version')}")
    wire.notify("notifications/initialized")

    failures: list[str] = []

    # 1 — kernel positive control must award.
    res = wire.call_lean_verify(_KERNEL_POSITIVE)
    ok, reasons = _award(res)
    print(f"[kernel-positive] {_brief(res)}")
    if not ok:
        failures.append(f"kernel positive control did not award: {reasons}")

    # 2 — the AC-D.1 canary must be rejected, never awarded.
    res = wire.call_lean_verify(_AXIOM_CANARY)
    ok, _ = _award(res)
    soundness = res.get("soundness") or {}
    print(f"[axiom-canary]    {_brief(res)}")
    if ok:
        failures.append(
            "RED ALARM: the axiom canary was AWARDED proven-formal — "
            "the soundness hardening is not live on this server"
        )
    if soundness.get("guard") != "rejected":
        failures.append(
            f"canary was not rejected by the snippet guard "
            f"(guard={soundness.get('guard')!r})"
        )

    # 3 — mathlib positive control (skippable, honestly reported).
    if args.no_mathlib:
        print("[mathlib-positive] SKIPPED (--no-mathlib)")
    else:
        res = wire.call_lean_verify(_MATHLIB_POSITIVE)
        if res.get("status") == "timeout":
            # Cold olean tower — one retry against the respawned REPL.
            print("[mathlib-positive] first call timed out (cold cache); retrying")
            res = wire.call_lean_verify(_MATHLIB_POSITIVE)
        ok, reasons = _award(res)
        print(f"[mathlib-positive] {_brief(res)}")
        if not ok:
            failures.append(f"mathlib positive control did not award: {reasons}")
        elif (res.get("provenance") or {}).get("mathlib_rev") is None:
            failures.append("mathlib control awarded but mathlib_rev is null")

    if failures:
        print("SOUNDNESS SMOKE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SOUNDNESS SMOKE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

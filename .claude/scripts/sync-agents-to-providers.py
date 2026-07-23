#!/usr/bin/env python3
"""sync-agents-to-providers.py -- Codex TOML mirrors for BESPOKE agent overlays.

Usage:
  python3 sync-agents-to-providers.py [--repo <path>] [--source <dir>]
                                      [--out <dir>] [--check | --self-test]

Runs LOCALLY inside one consumer repo (--repo defaults to cwd), transforming
the repo's OWN bespoke `.claude/agents/*.md` overlays into
`.codex/agents/<stem>.toml` via the transform imported from the sibling
synced sync-repos.py -- never a duplicated emitter: same lenient-description
parsing, same tripwires (.Codex, authority text, tomllib round-trip),
LF-only, byte-stable across reruns. Division of turf (D7/m7): canon is
sync's -- a source .md recorded in .claude/.registry-manifest.json is
SKIPPED (sync owns its mirror) and any OUTPUT rel recorded there is REFUSED
loudly (exit 1). This script NEVER writes the manifest: recording repo-owned
rels would hand them to sync's removal pass, which would DELETE them next
run as "no longer produced" -- a live footgun. No local manifest either
(deliberate): outputs are deterministic, sources git-tracked -- regenerate
on demand; hand edits belong in the source .md, never in a generated .toml.

Local tier rows (canon's 3-tier gate in sync-repos.py is UNCHANGED; these
exist only for bespoke overlays): haiku+no-effort -> "low"; opus+max ->
"xhigh". "low" verified against the local Codex build 2026-07-22 (binary
enum scan: none/minimal/low/medium/high/xhigh/max/ultra). Any other
non-canon combo (e.g. opus + no effort) still fails loud per file.

README.md is skipped with a notice. A DIFFERING existing output is
overwritten in write mode BY DESIGN (regeneration; the adoption flow --
tools/codex-adopt.py, SYNC-RUNBOOK.md section 6 -- backs up hand TOMLs
first). --check is a report-only byte-compare. Stale outputs (no matching
source .md, no manifest record) are reported, never deleted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_SYNC_PATH = Path(__file__).resolve().with_name("sync-repos.py")


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_repos", _SYNC_PATH)
    if spec is None or spec.loader is None:
        sys.exit(f"cannot load sibling module: {_SYNC_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SYNC = _load_sync_module()


def _extended_resolve(fm: dict, _canon=SYNC._resolve_effort):
    """Bespoke tier rows on top of the canon allowlist (module docstring)."""
    model, effort = fm.get("model"), fm.get("effort")
    if model == "haiku" and effort is None:
        return "low"
    if model == "opus" and effort == "max":
        return "xhigh"
    return _canon(fm)


# _generate_agent_toml resolves _resolve_effort through its module globals,
# so patching THIS loaded instance extends the tier table locally without
# weakening the registry gate (sync-repos.py itself is untouched; its own
# runs keep the strict 3-tier allowlist).
SYNC._resolve_effort = _extended_resolve


def _repo_rel(path: Path, repo: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return None


def generate(repo: Path, source: Path, out: Path, check: bool) -> int:
    """Returns the problem count (refusals + per-file emit failures)."""
    mpath = repo / ".claude" / SYNC.MANIFEST_NAME
    manifest = (json.loads(mpath.read_text(encoding="utf-8-sig"))
                if mpath.is_file() else {})
    if not source.is_dir():
        print(f"  ERROR   source dir not found: {source}")
        return 1
    problems = 0
    produced: set[str] = set()
    for md in sorted(source.glob("*.md")):
        if md.name == "README.md":
            print(f"  SKIP    {md.name} (README, not an agent)")
            continue
        src_rel = _repo_rel(md, repo)
        if src_rel is not None and src_rel in manifest:
            print(f"  CANON   {md.name} (registry-synced; sync owns its mirror)")
            continue
        dest = out / f"{md.stem}.toml"
        dest_rel = _repo_rel(dest, repo)
        if dest_rel is not None and dest_rel in manifest:
            print(f"  REFUSE  {dest_rel} (registry-managed output rel)")
            problems += 1
            continue
        try:
            blob = SYNC._generate_agent_toml(md)
        except SYNC.CodexEmitError as e:
            print(f"  ERROR   {md.name} ({e})")
            problems += 1
            continue
        except Exception as e:  # noqa: BLE001 -- per-file isolation, as in sync
            print(f"  ERROR   {md.name} (unexpected: {type(e).__name__}: {e})")
            problems += 1
            continue
        produced.add(dest.name)
        if dest.is_file() and dest.read_bytes() == blob:
            print(f"  OK      {dest.name} (unchanged)")
            continue
        verb = "UPDATE" if dest.is_file() else "CREATE"
        if not check:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
        print(f"  {verb}  {dest.name}" + (" (check only)" if check else ""))

    # Stale report: *.toml with no matching source .md and no registry
    # manifest record. Hand canon TOMLs pending adoption stem-match a synced
    # source .md, so they are NOT reported here (that is adoption's turf).
    if out.is_dir():
        for t in sorted(out.glob("*.toml")):
            if t.name in produced or (source / f"{t.stem}.md").is_file():
                continue
            t_rel = _repo_rel(t, repo)
            if t_rel is not None and t_rel in manifest:
                continue
            print(f"  STALE   {t.name} (no matching source .md;"
                  " deletion is user-gated)")
    return problems


# ---------------------------------------------------------------------------
# Offline self-test: tempdir fake consumer repos.
# ---------------------------------------------------------------------------


def _self_test() -> int:
    import contextlib
    import io
    import tempfile
    import tomllib

    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)

    def run(argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def agent_md(name: str, model: str, effort: str | None,
                 desc: str = "plain description") -> bytes:
        fm = [f"name: {name}", f"description: {desc}", f"model: {model}"]
        if effort is not None:
            fm.append(f"effort: {effort}")
        return ("---\n" + "\n".join(fm) + "\n---\n\nBody of "
                + name + ". CLAUDE.md wins.\n").encode()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # repo A: happy path (extended tiers, lenient fm, README, canon skip,
        # stale orphan, byte-stable rerun, manifest never written)
        a = root / "repoA"
        ag = a / ".claude" / "agents"
        ag.mkdir(parents=True)
        (ag / "worker.md").write_bytes(
            agent_md("worker", "haiku", None, "Inputs: a and b (lenient)"))
        (ag / "synth.md").write_bytes(agent_md("synth", "opus", "max"))
        (ag / "plain.md").write_bytes(agent_md("plain", "sonnet", None))
        (ag / "README.md").write_bytes(b"# not an agent\n")
        (ag / "canon-agent.md").write_bytes(agent_md("canon-agent", "sonnet", None))
        mpath_a = a / ".claude" / SYNC.MANIFEST_NAME
        mpath_a.write_bytes(json.dumps(
            {".claude/agents/canon-agent.md": "0" * 64}).encode())
        man_a = mpath_a.read_bytes()
        (a / ".codex" / "agents").mkdir(parents=True)
        (a / ".codex" / "agents" / "orphan.toml").write_bytes(b"# hand orphan\n")

        code, out = run(["--repo", str(a)])
        check("A exit 0", code == 0)
        worker = a / ".codex" / "agents" / "worker.toml"
        p_worker = tomllib.loads(worker.read_text(encoding="utf-8"))
        p_synth = tomllib.loads(
            (a / ".codex" / "agents" / "synth.toml").read_text(encoding="utf-8"))
        p_plain = tomllib.loads(
            (a / ".codex" / "agents" / "plain.toml").read_text(encoding="utf-8"))
        check("haiku+none maps low",
              p_worker.get("model_reasoning_effort") == "low")
        check("lenient description == raw source line",
              p_worker["description"] == "Inputs: a and b (lenient)")
        check("opus+max maps xhigh",
              p_synth.get("model_reasoning_effort") == "xhigh")
        check("sonnet+none omits effort",
              "model_reasoning_effort" not in p_plain)
        check("body verbatim", "CLAUDE.md wins" in p_worker["developer_instructions"])
        check("LF-only emission", b"\r" not in worker.read_bytes())
        check("README skipped", "SKIP    README.md" in out)
        check("canon source skipped", "CANON   canon-agent.md" in out
              and not (a / ".codex" / "agents" / "canon-agent.toml").exists())
        check("stale orphan reported not deleted", "STALE   orphan.toml" in out
              and (a / ".codex" / "agents" / "orphan.toml").read_bytes()
              == b"# hand orphan\n")
        check("manifest never written", mpath_a.read_bytes() == man_a)

        before = worker.read_bytes()
        code, out = run(["--repo", str(a)])
        check("rerun exit 0 + unchanged", code == 0
              and "OK      worker.toml (unchanged)" in out)
        check("rerun byte-stable", worker.read_bytes() == before)

        # repo B: check-mode writes nothing; manifest-rel refusal; fail-loud tier
        b = root / "repoB"
        bg = b / ".claude" / "agents"
        bg.mkdir(parents=True)
        (bg / "plain2.md").write_bytes(agent_md("plain2", "sonnet", None))
        (bg / "collide.md").write_bytes(agent_md("collide", "sonnet", None))
        (bg / "badtier.md").write_bytes(agent_md("badtier", "opus", None))
        mpath_b = b / ".claude" / SYNC.MANIFEST_NAME
        mpath_b.write_bytes(json.dumps(
            {".codex/agents/collide.toml": "0" * 64}).encode())
        man_b = mpath_b.read_bytes()
        code, out = run(["--repo", str(b), "--check"])
        check("check reports CREATE and writes nothing", code == 1
              and "CREATE  plain2.toml (check only)" in out
              and not (b / ".codex").exists())
        code, out = run(["--repo", str(b)])
        check("B exit 1", code == 1)
        check("registry-managed output rel refused",
              "REFUSE  .codex/agents/collide.toml" in out
              and not (b / ".codex" / "agents" / "collide.toml").exists())
        check("opus+none fails loud",
              "ERROR   badtier.md" in out and "tier" in out
              and not (b / ".codex" / "agents" / "badtier.toml").exists())
        check("B manifest never written", mpath_b.read_bytes() == man_b)

    if failures:
        print("self-test FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".",
                    help="consumer repo root (default: cwd)")
    ap.add_argument("--source", help="overlay dir (default: <repo>/.claude/agents)")
    ap.add_argument("--out", help="output dir (default: <repo>/.codex/agents)")
    ap.add_argument("--check", action="store_true",
                    help="report-only byte-compare; writes nothing")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    repo = Path(args.repo).resolve()
    source = Path(args.source).resolve() if args.source \
        else repo / ".claude" / "agents"
    out = Path(args.out).resolve() if args.out else repo / ".codex" / "agents"
    print(f"{repo.name}: bespoke agent mirrors"
          f" ({'check' if args.check else 'write'} mode)")
    return 1 if generate(repo, source, out, args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

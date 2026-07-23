#!/usr/bin/env python3
"""sync-repos.py — copy-sync registry data tiers into consuming repos.

Usage:
  python3 sync-repos.py [--check] [--dry-run] [--repo <path> ...] [--codex]
  python3 sync-repos.py --self-test

Without --repo, targets every repo listed in repos-manifest.txt (one path per
line, relative to the Source Code directory two levels above this registry,
'#' comments allowed). A line may carry a trailing `no-codex` token: that
repo's generated Codex class is suppressed in EVERY mode (check/dry/sync,
with or without --codex), exactly as running without --codex behaves today.
The annotation also applies when the repo is addressed via --repo.

Interpreter floor: Python 3.11+ (tomllib, module-level import — every mode,
not only --codex). Both fleet machines run 3.11+; stdlib + PyYAML otherwise.

Mapping (registry -> consumer):
  data/commands/*.md    -> .claude/commands/
  data/agents/*.md      -> .claude/agents/
  data/references/*.md  -> .claude/references/
  data/scripts/*        -> .claude/scripts/
  data/skills/<name>/** -> .claude/skills/<name>/**
  data/github/**        -> .github/**  (issue/PR templates; subtree)
  data/agents/*.md      -> .codex/agents/*.toml  (GENERATED; --codex only)

The first four tiers are FLAT: top-level files only, subdirectories are ignored
(prefix-namespace instead, e.g. `frontend-uplift-phase-1.md`). `skills/` is the
one exception -- Claude Code discovers a skill as `.claude/skills/<name>/SKILL.md`,
so a skill is a DIRECTORY and its whole tree (SKILL.md plus any assets/) is synced.
Manifest keys are destination-relative paths, so nested entries work unchanged.

Every synced file is recorded (sha256) in .claude/.registry-manifest.json in
the consumer. Rules:
  - files NOT in the manifest are repo-local overlays: never touched
  - files in the manifest whose local hash differs from the last-synced hash
    have local edits: --check reports them; sync refuses to clobber and lists
    them (fix by editing the registry copy, then re-sync)
  - files removed from the registry are deleted from the consumer on sync
--check reports drift without writing. --dry-run prints planned actions.

Generated Codex surface (--codex, decision D7): every canon agent .md is
transformed in-memory to .codex/agents/<name>.toml (body verbatim as
developer_instructions; tier map: standard -> omit model_reasoning_effort,
heavy -> "high", deep -> "xhigh"), written LF-only, and recorded in the same
manifest by content hash. Emit gates (tomllib round-trip, raw-source
fidelity, zero .Codex, authority text preserved, strict tier allowlist) fail
loud PER FILE: that file is skipped, counted as a problem (exit 1), and a
previously generated copy is never REMOVEd. First-contact guard: an emitted
rel not in the old manifest whose destination already exists is ADOPTed when
byte-identical (recorded, not written) or reported ADOPT-PENDING when
different (skipped, never overwritten, not a problem -- adoption is a
user-gated per-repo transaction; see SYNC-RUNBOOK.md section 6 and
tools/codex-adopt.py). Without --codex the .codex class is untouched end-to-end: no
emission, and previously recorded .codex rels are neither removed nor
dropped from the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path

import yaml

REGISTRY = Path(__file__).resolve().parents[2]  # .../claude-registry
TIERS = {
    "commands": ".claude/commands",
    "agents": ".claude/agents",
    "references": ".claude/references",
    "scripts": ".claude/scripts",
}
SKILLS_TIER = "skills"
SKILLS_DEST = ".claude/skills"
GITHUB_TIER = "github"
GITHUB_DEST = ".github"
CODEX_ROOT = ".codex"
CODEX_DEST = ".codex/agents"
MANIFEST_NAME = ".registry-manifest.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def registry_files() -> dict[str, Path]:
    """rel-dest-path -> registry source path"""
    out: dict[str, Path] = {}
    for tier, dest in TIERS.items():
        src_dir = REGISTRY / "data" / tier
        if not src_dir.is_dir():
            continue
        for f in sorted(src_dir.iterdir()):
            if f.is_file():
                out[f"{dest}/{f.name}"] = f

    # skills/ is dir-per-skill, not flat: Claude Code discovers
    # `.claude/skills/<name>/SKILL.md`, and a skill may carry assets/ alongside.
    # Sync the whole subtree; a skill dir without SKILL.md is not a skill, skip it.
    skills_dir = REGISTRY / "data" / SKILLS_TIER
    if skills_dir.is_dir():
        for skill in sorted(skills_dir.iterdir()):
            if not skill.is_dir() or not (skill / "SKILL.md").is_file():
                continue
            for f in sorted(skill.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(skills_dir).as_posix()
                    out[f"{SKILLS_DEST}/{rel}"] = f

    # .github subtree (issue/PR templates): mirror data/github/** -> .github/**.
    # A consumer's own .github/workflows and dependabot.yml are not under
    # data/github, so they are overlays and are never touched.
    github_dir = REGISTRY / "data" / GITHUB_TIER
    if github_dir.is_dir():
        for f in sorted(github_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(github_dir).as_posix()
                out[f"{GITHUB_DEST}/{rel}"] = f
    return out


KNOWN_ANNOTATIONS = {"no-codex"}


def _manifest_entries() -> dict[Path, set[str]]:
    """repos-manifest.txt: resolved repo path -> annotation set.

    Line format: `<path> [annotation ...]`. Only trailing tokens from
    KNOWN_ANNOTATIONS are peeled off, so paths containing spaces survive;
    an unknown trailing token stays part of the path and fails loud later
    as a MISSING repo."""
    manifest = REGISTRY / "data" / "scripts" / "repos-manifest.txt"
    if not manifest.is_file():
        return {}
    source_code = REGISTRY.parent
    entries: dict[Path, set[str]] = {}
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        annots: set[str] = set()
        while len(tokens) > 1 and tokens[-1] in KNOWN_ANNOTATIONS:
            annots.add(tokens.pop())
        entries[(source_code / " ".join(tokens)).resolve()] = annots
    return entries


def target_repos(cli_repos: list[str]) -> list[tuple[Path, set[str]]]:
    """(repo path, annotation set) pairs; annotations apply to --repo too."""
    entries = _manifest_entries()
    if cli_repos:
        return [(p, entries.get(p, set()))
                for p in (Path(r).resolve() for r in cli_repos)]
    return list(entries.items())


# ---------------------------------------------------------------------------
# Codex emitter (--codex, decision D7). Ported from the spike-1 prototype
# (md2codex.py); per-file gate failures raise CodexEmitError instead of
# exiting so one bad canon body cannot brick the rest of the sync.
# ---------------------------------------------------------------------------


class CodexEmitError(Exception):
    """Per-file emit-gate failure: skip the file, count a problem."""


def _parse_agent_md(path: Path) -> tuple[dict, str]:
    """Split ONLY the first frontmatter fence pair; bodies contain --- hr
    lines, so a naive split truncates them."""
    text = path.read_text(encoding="utf-8-sig")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise CodexEmitError("no opening frontmatter fence")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise CodexEmitError("frontmatter fence never closes") from None
    fm_lines = lines[1:end]
    try:
        fm = yaml.safe_load("\n".join(fm_lines))
    except yaml.YAMLError:
        # 5/14 canon agents carry single-line plain-scalar descriptions with
        # unquoted ": " -- invalid strict YAML that Claude Code's lenient
        # parser accepts. Fallback: take the description line raw, parse the
        # rest strictly (wrapped second-stage parse).
        desc = None
        rest = []
        for ln in fm_lines:
            if desc is None and ln.startswith("description:"):
                desc = ln[len("description:"):].strip()
            else:
                rest.append(ln)
        try:
            fm = yaml.safe_load("\n".join(rest))
        except yaml.YAMLError as e:
            raise CodexEmitError(
                f"frontmatter invalid beyond the description line: {e}") from None
        if desc is not None:
            fm["description"] = desc
            # Source-fidelity gate: the fallback value must equal the raw
            # source line, not merely survive its own emit/parse loop.
            raw = next(ln for ln in fm_lines if ln.startswith("description:"))
            if desc != raw[len("description:"):].strip():
                raise CodexEmitError("description fallback != raw source line")
    if not isinstance(fm, dict) or "name" not in fm:
        raise CodexEmitError("frontmatter is not a mapping with a name key")
    body = "\n".join(lines[end + 1:]).lstrip("\n").rstrip("\n")
    return fm, body


def _resolve_effort(fm: dict) -> str | None:
    """Strict tier allowlist (CLAUDE.md tier table); anything else fails the
    file loud -- no best-effort mapping, no silent default."""
    model, effort = fm.get("model"), fm.get("effort")
    if model == "sonnet" and effort is None:
        return None            # standard -> inherit the session default
    if model == "sonnet" and effort == "high":
        return "high"          # heavy -> explicit floor
    if model == "opus" and effort == "high":
        return "xhigh"         # deep -> the strongest expressible value
    raise CodexEmitError(
        f"unknown tier combination (model={model!r}, effort={effort!r})")


def _escape_ml(text: str) -> str:
    """Escape content for a TOML multiline basic string. Backslash doubling
    also neutralizes the silent line-ending-backslash continuation hazard."""
    if '"""' in text or "'''" in text:
        raise CodexEmitError("content embeds a triple quote")
    return text.replace("\\", "\\\\")


def _emit_codex_toml(fm: dict, body: str) -> str:
    desc = str(fm.get("description", "")).rstrip("\n")
    parts = [f'name = "{fm["name"]}"']
    if "\n" in desc:
        parts.append(f'description = """\n{_escape_ml(desc)}"""')
    else:
        esc = desc.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'description = "{esc}"')
    effort = _resolve_effort(fm)
    if effort is not None:
        parts.append(f'model_reasoning_effort = "{effort}"')
    parts.append(f'developer_instructions = """\n{_escape_ml(body)}"""')
    return "\n".join(parts) + "\n"


def _generate_agent_toml(src: Path) -> bytes:
    """Transform one canon agent .md to Codex TOML bytes, all gates applied."""
    fm, body = _parse_agent_md(src)
    toml_text = _emit_codex_toml(fm, body)
    # Hard-rule tripwires (DESIGN section 3): verbatim emission is the
    # mechanism; these asserts are the tripwire.
    if ".Codex" in toml_text:
        raise CodexEmitError(".Codex path appeared in output")
    # Spot-check tripwire only (1/14 agents carries the literal phrase);
    # AC2's actual mechanism is verbatim body emission.
    if "CLAUDE.md wins" in body and "CLAUDE.md wins" not in toml_text:
        raise CodexEmitError("doc-authority text altered")
    # Round-trip: the escaping gate. Catches invalid escapes AND the silent
    # line-continuation corruption. Values chain to the RAW .md source: body
    # is raw-derived and a fallback description is gate-checked above.
    try:
        parsed = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as e:
        raise CodexEmitError(f"emitted TOML does not parse: {e}") from None
    if parsed["name"] != fm["name"]:
        raise CodexEmitError("round-trip mismatch: name")
    if parsed["description"] != str(fm.get("description", "")).rstrip("\n"):
        raise CodexEmitError("round-trip mismatch: description")
    if parsed["developer_instructions"] != body:
        raise CodexEmitError("round-trip mismatch: developer_instructions")
    if parsed.get("model_reasoning_effort") != _resolve_effort(fm):
        raise CodexEmitError("round-trip mismatch: model_reasoning_effort")
    return toml_text.encode("utf-8")  # LF-only by construction


def generated_files() -> tuple[dict[str, bytes], set[str], int]:
    """Codex provider surface: data/agents/*.md -> .codex/agents/<name>.toml.

    Computed once per run (repo-invariant). Returns (rel -> emitted bytes,
    rels that failed an emit gate, problem count). Failed rels are excluded
    from every consumer's REMOVE set so a transient canon defect never
    deletes a consumer's last good copy."""
    gen: dict[str, bytes] = {}
    failed: set[str] = set()
    problems = 0
    agents_dir = REGISTRY / "data" / "agents"
    if not agents_dir.is_dir():
        return gen, failed, problems
    for f in sorted(agents_dir.iterdir()):
        if not f.is_file() or f.suffix != ".md":
            continue
        rel = f"{CODEX_DEST}/{f.stem}.toml"
        try:
            gen[rel] = _generate_agent_toml(f)
        except CodexEmitError as e:
            print(f"codex-emit: ERROR {rel} ({e})")
            failed.add(rel)
            problems += 1
        except Exception as e:  # noqa: BLE001 -- per-file isolation is the contract:
            # a malformed canon file (non-dict frontmatter, undecodable bytes)
            # must skip THIS file loudly, never brick the whole fleet sync.
            print(f"codex-emit: ERROR {rel} (unexpected: {type(e).__name__}: {e})")
            failed.add(rel)
            problems += 1
    return gen, failed, problems


def sync_repo(repo: Path, files: dict[str, Path | bytes], check: bool,
              dry: bool, codex: bool, failed: set[str]) -> int:
    """Returns number of problems (drift under --check, refusals under sync)."""
    mpath = repo / ".claude" / MANIFEST_NAME
    old = json.loads(mpath.read_text()) if mpath.exists() else {}
    problems = 0
    pending = 0
    new_manifest: dict[str, str] = {}
    actions: list[str] = []

    for rel, src in files.items():
        dest = repo / rel
        generated = isinstance(src, bytes)
        src_hash = hashlib.sha256(src).hexdigest() if generated else sha(src)
        new_manifest[rel] = src_hash
        if dest.exists():
            local = sha(dest)
            if local == src_hash:
                if generated and rel not in old:
                    # identical unmanaged file: adopt into the manifest, no write
                    actions.append(f"  ADOPT   {rel} (identical content, now managed)")
                continue  # up to date
            if rel in old and old[rel] != local:
                # local edits on a synced file — never clobber
                actions.append(f"  DRIFT   {rel} (locally edited since last sync)")
                problems += 1
                new_manifest[rel] = old[rel]  # keep old record until resolved
                continue
            if generated and rel not in old:
                # First-contact guard: NEVER overwrite an unmanaged existing
                # file at an emitted path -- adoption is user-gated (see
                # SYNC-RUNBOOK.md section 6). Recording a hash for content
                # never written would poison the manifest.
                actions.append(f"  ADOPT-PENDING  {rel} (unmanaged local file differs)")
                del new_manifest[rel]
                pending += 1
                continue
            actions.append(f"  UPDATE  {rel}")
        else:
            actions.append(f"  ADD     {rel}")
        if not check and not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if generated:
                dest.write_bytes(src)
            else:
                shutil.copy2(src, dest)

    # removals: previously synced, no longer produced this run. A rel that
    # failed an emit gate, or any .codex rel when --codex is off, keeps its
    # old record and is never removed (a transient canon defect or a plain
    # no-flag run must not delete a consumer's generated copies).
    pruned: set[Path] = set()
    for rel in sorted(set(old) - set(files)):
        if rel in failed or (not codex and rel.startswith(f"{CODEX_DEST}/")):
            new_manifest[rel] = old[rel]
            continue
        dest = repo / rel
        if dest.exists():
            actions.append(f"  REMOVE  {rel}")
            if not check and not dry:
                dest.unlink()
                pruned.add(dest.parent)

    # a removed skill or generated TOML leaves an empty dir that would still
    # be scanned; prune empty dirs under the skills/.codex roots (deepest
    # first), never the roots themselves.
    prune_roots = (repo / SKILLS_DEST, repo / CODEX_ROOT)
    for d in sorted(pruned, key=lambda p: len(p.parts), reverse=True):
        if any(r in d.parents for r in prune_roots) and d.is_dir() \
                and not any(d.iterdir()):
            d.rmdir()

    if actions:
        print(f"{repo.name}:")
        print("\n".join(actions))
    else:
        print(f"{repo.name}: clean")
    if pending:
        print(f"  adopt-pending: {pending} unmanaged local file(s) untouched"
              " (adoption is gated; SYNC-RUNBOOK.md section 6)")
    if not check and not dry:
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(new_manifest, indent=2, sort_keys=True) + "\n")
    return problems


# ---------------------------------------------------------------------------
# Offline self-test: tempdir fake registry + fake consumers.
# ---------------------------------------------------------------------------


def _self_test() -> int:
    import contextlib
    import io
    import tempfile

    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)

    def run(argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    strict_md = (
        "---\n"
        "name: strict\n"
        "description: Strict-YAML agent\n"
        "model: sonnet\n"
        "---\n"
        "\n"
        "Body with an hr below. CLAUDE.md wins.\n"
        "\n"
        "---\n"
        "\n"
        "a line ending in a backslash \\\n"
        "last line.\n")
    lenient_md = (
        "---\n"
        "name: lenient\n"
        "description: Inputs: slug and id (strict-invalid)\n"
        "model: sonnet\n"
        "effort: high\n"
        "---\n"
        "\n"
        "Lenient body referencing .claude/notes/ paths.\n")
    deep_md = (
        "---\n"
        "name: deep\n"
        "description: Deep-tier agent\n"
        "model: opus\n"
        "effort: high\n"
        "---\n"
        "\n"
        "Deep body.\n")

    global REGISTRY
    real_registry = REGISTRY
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fake = root / "registry"
        agents = fake / "data" / "agents"
        agents.mkdir(parents=True)
        (fake / "data" / "commands").mkdir()
        (fake / "data" / "commands" / "cmd.md").write_bytes(b"# a command\n")
        (agents / "strict.md").write_bytes(strict_md.encode())
        (agents / "lenient.md").write_bytes(lenient_md.encode())
        (agents / "deep.md").write_bytes(deep_md.encode())
        c1, c2, c3 = (root / n for n in ("c1", "c2", "c3"))
        for c in (c1, c2, c3):
            c.mkdir()
        REGISTRY = fake
        try:
            # 1. emission + manifest keys (+ normal tier still syncs)
            code, out = run(["--codex", "--repo", str(c1)])
            strict_toml = c1 / ".codex" / "agents" / "strict.toml"
            lenient_toml = c1 / ".codex" / "agents" / "lenient.toml"
            deep_toml = c1 / ".codex" / "agents" / "deep.toml"
            check("run1 exit 0", code == 0)
            check("run1 emits three TOMLs", strict_toml.is_file()
                  and lenient_toml.is_file() and deep_toml.is_file())
            check("run1 syncs normal tier",
                  (c1 / ".claude" / "commands" / "cmd.md").is_file())
            p_strict = tomllib.loads(strict_toml.read_text(encoding="utf-8"))
            p_lenient = tomllib.loads(lenient_toml.read_text(encoding="utf-8"))
            p_deep = tomllib.loads(deep_toml.read_text(encoding="utf-8"))
            check("standard omits effort",
                  "model_reasoning_effort" not in p_strict)
            check("heavy maps high",
                  p_lenient.get("model_reasoning_effort") == "high")
            check("deep maps xhigh",
                  p_deep.get("model_reasoning_effort") == "xhigh")
            check("lenient description == raw source line",
                  p_lenient["description"] == "Inputs: slug and id (strict-invalid)")
            check("body verbatim (hr + backslash + authority)",
                  "---" in p_strict["developer_instructions"]
                  and "backslash \\" in p_strict["developer_instructions"]
                  and "CLAUDE.md wins" in p_strict["developer_instructions"])
            check("LF-only emission", b"\r" not in strict_toml.read_bytes())
            man = json.loads((c1 / ".claude" / MANIFEST_NAME).read_text())
            check("manifest records codex rel by content hash",
                  man.get(".codex/agents/strict.toml")
                  == hashlib.sha256(strict_toml.read_bytes()).hexdigest())

            # 2. byte-stable no-op re-run
            before = strict_toml.read_bytes()
            code, out = run(["--codex", "--repo", str(c1)])
            check("run2 clean no-op", code == 0 and "c1: clean" in out)
            check("run2 byte-stable", strict_toml.read_bytes() == before)

            # 3. DRIFT refusal on a MANAGED generated TOML
            orig = strict_toml.read_bytes()
            strict_toml.write_bytes(orig + b"# hand edit\n")
            code, out = run(["--codex", "--repo", str(c1)])
            check("drift reported", code == 1
                  and "DRIFT   .codex/agents/strict.toml" in out)
            check("drift never clobbered",
                  strict_toml.read_bytes() == orig + b"# hand edit\n")
            man = json.loads((c1 / ".claude" / MANIFEST_NAME).read_text())
            check("drift keeps old record",
                  man[".codex/agents/strict.toml"]
                  == hashlib.sha256(orig).hexdigest())
            strict_toml.write_bytes(orig)  # restore

            # 4. first-contact guard: ADOPT identical / ADOPT-PENDING differing
            (c2 / ".codex" / "agents").mkdir(parents=True)
            (c2 / ".codex" / "agents" / "strict.toml").write_bytes(orig)
            (c2 / ".codex" / "agents" / "deep.toml").write_bytes(b"hand file\n")
            code, out = run(["--codex", "--repo", str(c2)])
            check("first-contact exit 0 (pending is not a problem)", code == 0)
            check("adopt identical line",
                  "ADOPT   .codex/agents/strict.toml" in out)
            check("adopt-pending line",
                  "ADOPT-PENDING  .codex/agents/deep.toml" in out)
            check("adopt-pending summary count", "adopt-pending: 1" in out)
            check("unmanaged file never overwritten",
                  (c2 / ".codex" / "agents" / "deep.toml").read_bytes()
                  == b"hand file\n")
            man2 = json.loads((c2 / ".claude" / MANIFEST_NAME).read_text())
            check("adopted rel recorded", ".codex/agents/strict.toml" in man2)
            check("pending rel not recorded",
                  ".codex/agents/deep.toml" not in man2)

            # 5. no-flag regression: no emission, and managed TOMLs untouched
            code, out = run(["--repo", str(c3)])
            man3 = json.loads((c3 / ".claude" / MANIFEST_NAME).read_text())
            check("no-flag emits nothing", code == 0
                  and not (c3 / ".codex").exists()
                  and not any(k.startswith(".codex/") for k in man3)
                  and ".codex" not in out)
            code, out = run(["--repo", str(c1)])
            man = json.loads((c1 / ".claude" / MANIFEST_NAME).read_text())
            check("no-flag keeps managed TOMLs + records", code == 0
                  and strict_toml.is_file() and "REMOVE" not in out
                  and ".codex/agents/strict.toml" in man)

            # 6. emit-gate failure: loud line, problem, last good copy kept
            lenient_good = lenient_toml.read_bytes()
            (agents / "lenient.md").write_bytes(
                lenient_md.replace("Lenient body", 'Broken """ body').encode())
            (agents / "badtier.md").write_bytes(
                b"---\nname: badtier\ndescription: x\nmodel: opus\n---\n\nbody\n")
            code, out = run(["--codex", "--repo", str(c1)])
            check("gate failures exit 1", code == 1)
            check("triple-quote ERROR line",
                  "codex-emit: ERROR .codex/agents/lenient.toml" in out)
            check("bad tier ERROR line",
                  "codex-emit: ERROR .codex/agents/badtier.toml" in out
                  and "tier" in out)
            check("failed rel keeps last good copy",
                  lenient_toml.read_bytes() == lenient_good
                  and "REMOVE  .codex/agents/lenient.toml" not in out)
            man = json.loads((c1 / ".claude" / MANIFEST_NAME).read_text())
            check("failed rel record carried forward",
                  ".codex/agents/lenient.toml" in man)
            # M1 guard: a name-less file whose only frontmatter line is a
            # strict-invalid description leaves fm non-dict -- must be a
            # per-file ERROR, never an uncaught TypeError bricking the run.
            (agents / "nameless.md").write_bytes(
                b"---\ndescription: Inputs: x\n---\n\nbody\n")
            code, out = run(["--codex", "--repo", str(c1)])
            check("unexpected exception isolated per-file", code == 1
                  and "codex-emit: ERROR .codex/agents/nameless.toml" in out
                  and "unexpected" in out and strict_toml.is_file())
            (agents / "nameless.md").unlink()
            (agents / "lenient.md").write_bytes(lenient_md.encode())
            (agents / "badtier.md").unlink()

            # 7. REMOVE on canon deletion + empty-dir pruning
            (agents / "deep.md").unlink()
            code, out = run(["--codex", "--repo", str(c1)])
            check("canon deletion removes generated toml",
                  "REMOVE  .codex/agents/deep.toml" in out
                  and not deep_toml.exists())
            check("canon deletion removes synced md",
                  not (c1 / ".claude" / "agents" / "deep.md").exists())
            (agents / "strict.md").unlink()
            (agents / "lenient.md").unlink()
            code, out = run(["--codex", "--repo", str(c1)])
            check("empty .codex/agents pruned",
                  not (c1 / ".codex" / "agents").exists())

            # 8. no-codex manifest annotation suppresses the codex class
            (fake / "data" / "scripts").mkdir(parents=True)
            (fake / "data" / "scripts" / "repos-manifest.txt").write_text(
                "# fixture\nc4 no-codex\nc5\n", encoding="utf-8")
            (agents / "strict.md").write_bytes(strict_md.encode())
            c4, c5 = root / "c4", root / "c5"
            c4.mkdir()
            c5.mkdir()
            code, out = run(["--codex"])  # fleet mode from the fixture manifest
            check("annotated fleet run exit 0", code == 0)
            check("no-codex repo gets no emission",
                  not (c4 / ".codex").exists()
                  and "c4: codex class suppressed" in out)
            check("unannotated repo still emits",
                  (c5 / ".codex" / "agents" / "strict.toml").is_file())
            man4 = json.loads((c4 / ".claude" / MANIFEST_NAME).read_text())
            check("no-codex repo still syncs normal tiers, no codex keys",
                  not any(k.startswith(".codex/") for k in man4)
                  and (c4 / ".claude" / "commands" / "cmd.md").is_file())
            code, out = run(["--codex", "--repo", str(c4)])
            check("annotation applies to --repo too", code == 0
                  and not (c4 / ".codex").exists()
                  and "codex class suppressed" in out)
        finally:
            REGISTRY = real_registry

    if failures:
        print("self-test FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--codex", action="store_true",
                    help="emit .codex/agents/<name>.toml per canon agent (D7)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    files: dict[str, Path | bytes] = dict(registry_files())
    base = dict(files)  # codex-suppressed view for no-codex annotated repos
    failed: set[str] = set()
    problems = 0
    if args.codex:
        gen, failed, gen_problems = generated_files()
        files.update(gen)
        problems += gen_problems
    for repo, annots in target_repos(args.repo):
        if not repo.is_dir():
            print(f"{repo}: MISSING — skipped")
            problems += 1
            continue
        suppress = "no-codex" in annots
        if args.codex and suppress:
            print(f"{repo.name}: codex class suppressed (no-codex annotation)")
        problems += sync_repo(repo, base if suppress else files, args.check,
                              args.dry_run, args.codex and not suppress, failed)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

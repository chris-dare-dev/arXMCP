# Runtime contract

How scripts, commands, and agents resolve paths on the personal fleet. The
scripts are the enforcement; this file documents the intent every ported
command and agent may cite instead of re-deriving it. Read it when you need
to know how a path, an interpreter, or a branch name is chosen.

## The model in one sentence

Each repo is a standalone git clone. `sync-repos.py` COPIES
`data/{commands,agents,references,scripts}` from this registry into each
consumer repo's `.claude/{commands,agents,references,scripts}` (recording a
sha256 per file in `.claude/.registry-manifest.json`). There is NO shared
workspace tier, NO platform tier, and NO symlink above the repo -- so
`git rev-parse --show-toplevel` always resolves to a real repo root.

## REPO_ROOT resolution

Every script and command anchors on a single variable, `REPO_ROOT`. Because a
command runs from inside a consumer repo and a synced script self-locates,
resolution always succeeds -- there is no repo-less directory to special-case.

Bash (three-tier fallback, as in `milestone-pipeline-init-state.sh`):

```bash
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
# Full form used inside scripts that also accept --repo-root:
#   1. --repo-root PATH          (explicit override for tests / CI)
#   2. git -C "$SCRIPT_DIR" rev-parse --show-toplevel
#   3. walk up from $SCRIPT_DIR until a directory contains .git
```

Python (as in `milestone-pipeline-resolve-brief.py`):

```python
def repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except Exception:
        # A synced script lives at <root>/.claude/scripts/<this-file>,
        # so parents[2] is the repo root. This fallback only fires when
        # git is unavailable; it is never the primary path.
        return Path(__file__).resolve().parents[2]
```

`--repo-root` is the only sanctioned override, and it exists for tests and CI
-- never to reach a sibling repo at runtime.

## Script self-location and sibling shell-out

A script that shells out to another script must locate the sibling
RELATIVE TO ITSELF, never by an absolute or shared path. Scripts are copied
per-repo by `sync-repos.py`, so the only stable handle a script has on its
siblings is its own directory.

Bash:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/milestone-pipeline-status.sh"          # sibling .sh
"$PY" "$SCRIPT_DIR/milestone-pipeline-resolve-brief.py"  # sibling .py
```

Python:

```python
sibling = Path(__file__).resolve().parent / "milestone-pipeline-record-progress.py"
```

Do NOT hardcode an install path and do NOT climb to a parent directory to
find a shared copy -- there is no shared copy.

## Interpreter resolution

| Extension | Invocation |
|---|---|
| `.py` | ALWAYS `python3 <path>` -- never `bash <path>` |
| `.sh` | ALWAYS `bash <path>` (POSIX sh; runs under Git Bash on Windows) |

Prefer the repo's virtualenv interpreter when present, falling back to a
`python3` on PATH:

```bash
PY="$REPO_ROOT/.venv/Scripts/python.exe"   # Windows venv layout
[ -x "$PY" ] || PY="$REPO_ROOT/.venv/bin/python"   # POSIX venv layout
[ -x "$PY" ] || PY="python3"
```

This is why the bootstrap script is `roadmap-init.py` (invoked
`python3 .../roadmap-init.py`) and not a shell script: roadmap tooling is
standardized on Python (stdlib + PyYAML), so it obeys the `.py` rule above.

## Default branch (derive, never hardcode)

No script or command may assume a fixed integration branch. Derive it:

```bash
DEFAULT_BRANCH="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|origin/||')"
[ -n "$DEFAULT_BRANCH" ] || DEFAULT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
```

Most personal repos default to `main`. The known exception is
`options-signal-engine`, which uses `master`. Both are handled by the
derivation above; neither is hardcoded. Every external-write example in this
document reads `git push origin "$DEFAULT_BRANCH"` -- and still stops for
user authorization (see "External-write boundary").

## Untracked write surface

Pipeline state and per-milestone artifacts live under `.claude/notes/...`
(for example `.claude/notes/milestones/<id>/state.json`). That whole subtree
is ephemeral: gitignore it, treat it as scratch. The durable, committed
evidence is the `*.md` under `research/`, `implement/`, `critique/`, and
`rectify/` for milestones, plus `plans/<slug>/roadmap.yaml` and the
append-only journals at `plans/<slug>/progress/*.jsonl` for roadmaps.

The canonical roadmap register is `plans/<slug>/roadmap.yaml`. Its items are
read by `milestone-pipeline-resolve-brief.py`, validated by
`roadmap-validate.py`, and progress is appended by
`milestone-pipeline-record-progress.py` -- never by editing item status in
place (one writer per file).

Because the milestone write surface is untracked, worktree isolation buys it
nothing. See `pipeline-pattern-v2.md` for why an untracked-notes agent must
NOT run under `isolation: worktree`.

## Windows realities

The fleet spans Windows and POSIX. Every `.py` script must:

- Read files that may carry a BOM (a hand-saved `roadmap.yaml`) with
  `encoding="utf-8-sig"`.
- Reconfigure stdout once at startup so ASCII-safe text never crashes on a
  cp1252 console:
  ```python
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  ```
- Emit ASCII-only output (no smart quotes, no box-drawing, no arrows).
- Use pathlib context managers for file writes (ruff SIM115), not a bare
  `open(...)` handle.
- Never import `fcntl` unconditionally -- it does not exist on Windows.
  Serialize via an atomic temp-file-plus-`os.replace` in the target's own
  directory and the existing `.claude/notes/milestones/.lock`, not POSIX
  file locks. Guard any optional `fcntl` use behind `try: import fcntl`.

`data/scripts/*.py` are held ruff-clean (this registry's HEAD is a ruff
fixed-point): no unused imports, no bare `except`, no f-string without a
placeholder, no unused loop variables, lines under 100 characters.

## Sync and drift

`sync-repos.py` copies `data/{commands,agents,references,scripts}` into each
consumer's `.claude/` and records a sha256 per file in
`.claude/.registry-manifest.json`:

- A file NOT in the manifest is a repo-local overlay -- sync never touches it.
- A managed file whose local hash differs from the last-synced hash is
  reported as DRIFT; sync refuses to clobber it. `--check` reports drift
  without writing; `--dry-run` prints planned actions.

The rule that follows: edit definitions HERE in the registry and re-sync.
Never edit a synced copy inside a consumer repo -- the edit is lost on the
next sync and shows up as drift in the meantime.

## External-write boundary

No script, command, or agent runs `git push`, `git commit`, `git add`,
`gh issue create`, a publish, a deploy, or any mutating external API on its
own. The user authorizes each external write. The `--github` path emits
issue-body files under `plans/<slug>/github/<item-id>.md` for review; the
actual `gh issue create` and `git push origin "$DEFAULT_BRANCH"` STOP and ask
first. After any errored external mutation, re-read the resource state before
concluding it failed. This boundary is shared with, and restated in,
`pipeline-pattern-v2.md`.

## Errata guard

If you are porting or reviewing a script and you see any of the following,
it is WRONG for this fleet -- fix it before shipping:

- A shared workspace-root or platform-root environment variable, or any
  symlink tier ABOVE the repo. The only root variable is `REPO_ROOT`,
  resolved per-invocation from `git rev-parse --show-toplevel`.
- A caveat about `git rev-parse` failing at a non-repo parent. Downstream you
  are always inside a real repo; that case does not exist.
- A hardcoded integration branch (for example a literal `dev` default, or a
  push to a fixed branch name). Derive the branch as shown above.
- A `.py` script invoked with `bash`, or an absolute/shared path to a sibling
  script. Use `python3` and repo-relative self-location.
- Any reference to a milestones register file or its merge/status/validate
  helpers. `plans/<slug>/roadmap.yaml` is the register; `roadmap-validate.py`
  validates it.

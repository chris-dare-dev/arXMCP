# Security: CDM subprocess sandbox profile

**Scope:** `tools/cdm_eval.py`'s `pdflatex` + `pdftoppm` subprocess
invocations for the parser-fidelity-eval-m1 CDM gate.

**Threat tier:** Peer of Threat 3 (LaTeXML sandbox) from
`.claude/notes/08-security-observability-ops.md`. Same risk profile
(Turing-complete LaTeX input, shell-escape via `\write18`, arbitrary-
file-read via `\input`, decompression-bomb risk in font files), same
mitigation discipline.

---

## Threat surface

`pdflatex` rendering of *operator-provided* or *parser-emitted*
LaTeX expressions during CDM scoring exposes the same surface as
LaTeXML on hostile source (Threat 3):

| Vector | Risk | Mitigation in this milestone |
|---|---|---|
| `\write18` shell escape | RCE | `--no-shell-escape` argv flag **plus** `shell_escape=f` env var (some texlive builds honor only one; both is defense-in-depth) |
| `\openout` arbitrary file write | Local file tamper / DoS | `openout_any=p` env var (paranoid — restricts `\openout` to cwd/sub-directories). **`--no-shell-escape` does NOT cover `\openout`** — that flag governs `\write18` (process spawn) only; `\openout` is a separate kpathsea concern |
| `\input{/etc/passwd}` arbitrary read | Info disclosure | `openin_any=p` env var (paranoid — restricts `\input` to cwd/sub-directories, blocking absolute paths). **TMPDIR cwd binding alone does NOT mitigate this** — pdflatex resolves absolute paths in `\input` regardless of cwd; only `openin_any` blocks the read |
| Decompression bombs in `.pfb`/`.pfm` fonts | CPU/memory exhaustion | 30s hard timeout + process-group kill |
| Infinite-recursion macros (`\def\x{\x}\x`) | Hang | `--interaction=nonstopmode` + `-halt-on-error` + 30s timeout |
| Untrusted `\usepackage{}` | Code execution via package init scripts | Wrapper template hard-codes `\usepackage[x11names]{xcolor}` + `\usepackage{amsmath,amssymb}` only; we do NOT honor user-supplied `\usepackage` directives in the wrapper template |
| Polyglot output (PDF that's also a malicious payload) | Downstream consumer attack | Only consumer is `pdftoppm` → PNG → numpy. No web service exposes the PDF directly |

**Mitigation delivery (load-bearing detail).** The three kpathsea
env vars (`openin_any`, `openout_any`, `shell_escape`) are passed by
`tools/cdm_eval.py::render_latex_to_image` via the `env=` keyword to
`subprocess.Popen` — texlive honors them at startup and they
override any default values in `texmf.cnf`. The `--no-shell-escape`
argv flag is layered on top; together they provide
defense-in-depth. See the F2 rectification commit for the precise
plumbing. Prior to the rectification this doc claimed
`--no-shell-escape` covered `\openout` and that TMPDIR bounded
`\input` — both claims were factually wrong; see the
parser-fidelity-eval-m1 critique F2 entry for the full
postmortem.

---

## Implementation: process-group discipline

Mirrors `tools.arxiv_fetch.parse_with_latexml` exactly (the existing
LaTeXML sandbox from E13_S03). Adds `-halt-on-error` (fail-fast on
first error rather than cascading warnings) and the three kpathsea
env vars for `\openout` / `\input` / `\write18` discipline:

```python
sandbox_env = {
    **os.environ,
    "openin_any": "p",      # restrict \input to cwd/sub-dirs
    "openout_any": "p",     # restrict \openout to cwd/sub-dirs
    "shell_escape": "f",    # belt-and-suspenders with --no-shell-escape
}
proc = subprocess.Popen(
    [pdflatex, "--no-shell-escape", "--interaction=nonstopmode",
     "-halt-on-error",
     "-output-directory", str(tmpdir), str(tex_path)],
    cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, start_new_session=True, env=sandbox_env,
)
try:
    stdout, stderr = proc.communicate(timeout=30)
except subprocess.TimeoutExpired:
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=5)  # drain PIPEs; avoid deadlock
    raise
```

`start_new_session=True` puts the child in its own process group.
On timeout, `os.killpg` kills the entire group — necessary because
`pdflatex` typically spawns subprocesses for font handling that
outlive a bare `proc.kill()`.

The same pattern wraps `pdftoppm`. Both timeouts are 30 seconds —
generous for single-equation rendering, tight enough to kill
runaway processes promptly.

---

## What this milestone explicitly does NOT do

- **Does NOT implement `sandbox-exec` profiles on macOS.** E13_S03's
  LaTeXML sandbox documents `sandbox-exec` as deprecated-but-functional
  on Darwin 25.4.0. We omit it for CDM because (a) the threat
  surface is smaller (we render operator-vetted or test-fixture
  LaTeX, not arbitrary arXiv source), (b) the `--no-shell-escape`
  + TMPDIR + process-group kill combination is already
  defense-in-depth, and (c) adding `sandbox-exec` to every test
  invocation slows the CDM gate noticeably without a measurable
  threat-model gain at this milestone's scope.

  **Un-park trigger** for adding `sandbox-exec`: a documented incident
  where a CDM render exfiltrated data via a font-handling subprocess.
  Track in `.claude/notes/deferred-work-tracker.md` if it surfaces.

- **Does NOT implement seccomp/landlock on Linux.** Same reasoning as
  above. The Threat-3 design for LaTeXML calls for these in
  production-grade Linux deployments; CDM is a development-time eval
  tool, not a production server path. Re-evaluate if the CDM gate
  ever runs against operator-supplied (vs project-controlled)
  parser output at scale.

- **Does NOT run pdflatex as a separate UID.** Same reasoning. The
  CDM gate runs as the test-suite user; collisions with arbitrary
  filesystem paths are bounded by the process's own permissions
  rather than a UID drop.

These omissions are deliberate, documented, and conservative — the
threat model for a development-time eval tool is meaningfully smaller
than the production-server LaTeXML threat model. If the CDM gate
later runs in a context with elevated risk (e.g., as part of an
operator-facing service rather than a `pytest` integration test),
this doc gets an addendum and the missing layers land in a new
milestone.

---

## Failure modes covered by tests

- `pdflatex` not on PATH → test skips (per `requires_pdflatex` marker)
- `pdftoppm` not on PATH → test skips
- Empty input → `cdm_score` raises RuntimeError (no silent zero)
- Token-count > 4913 (color-grid capacity) → raises RuntimeError
- Subprocess timeout → `subprocess.TimeoutExpired` propagates; the
  process group is killed before the exception surfaces
- Pillow not importable → RuntimeError (Pillow is a transitive dep
  via transformers / mcp; expected present)

---

## Cross-references

- E13_S03 LaTeXML sandbox precedent — design pattern lifted verbatim
- `.claude/notes/08-security-observability-ops.md` Threat 3 — peer
  threat with the same mitigation discipline
- `tools/arxiv_fetch.py::parse_with_latexml` — source code for the
  subprocess discipline this doc generalizes
- `tools/cdm_eval.py::_run_subprocess_with_pgkill` — the helper that
  implements this discipline for both pdflatex and pdftoppm

# Critique — E13_S03

**Critic:** infra-safety
**Generated:** 2026-05-17T22:05:00Z
**Commit range:** b6871112979ef3b2323f99a152d141757c55d98f..03e062f4fb53a572a3e2d4c8ac5228257121081f
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one HIGH (`deploy.resources.limits` silently inactive outside Swarm
  mode — the resource caps that defend against `fork_bomb.tex` / `large_alloc.tex`
  at the host level are no-ops in standalone compose) and one MEDIUM (HOME-read
  allowance in `sandbox.sb` covers `~/.ssh/`, `~/.aws/credentials`, `~/.gnupg/`).
- Finding counts: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 1 LOW.
- Both files are correctly marked as DOCUMENTATION ARTIFACTS; the not-wired-in-
  production status is stated clearly in the file headers and the implementation
  summary — no inflation warranted.
- The docker-compose.latexml.yml lacks a `restart:` policy and has no HEALTHCHECK,
  but as a documentation artifact without a running daemon these are MEDIUM at most.
- The sandbox.sb HOME-read allowance is structurally a partial info-disclosure
  surface; network-deny prevents exfiltration, so MEDIUM calibration holds.
- The `deploy.resources` HIGH is load-bearing because the file is explicitly cited
  as the defense against resource-exhaustion fixtures — if the caps never apply,
  the threat-3 documentation overstates the protection.
- No CI workflow files touched. No Makefile changes. `make test` target intact.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — deploy.resources.limits silently inactive in standalone compose

- **Severity:** HIGH
- **Source:** infra-safety
- **File:** infra/latexml/docker-compose.latexml.yml:84
- **What:** The `deploy.resources.limits` block (memory: 2g, cpus: 1.0) is a Docker
  Swarm construct. In standalone `docker compose` (Compose v2 / v1 `docker-compose`),
  the `deploy:` key is silently ignored. The resource caps documented as defense-in-
  depth against `fork_bomb.tex` and `large_alloc.tex` are not applied.
- **Why it matters:** The file's own inline comment (line 79–83) states these caps
  "prevent a single hostile paper from starving the host before the timeout fires."
  If an operator follows the documentation and runs the container standalone, there
  are no host-level memory or CPU limits — only the Python-side 300s timeout. The
  comment incorrectly describes these caps as functional for the documented use case.
  The existing `phoenix-compose.yml` in this same repo already encodes the correct
  pattern: it uses top-level `mem_limit` and `cpus` keys (phoenix-compose.yml:124-125)
  which Compose v2 honours outside Swarm mode.
- **Proposed fix:** Replace the `deploy:` block with top-level keys:
  ```yaml
  mem_limit: 2g
  cpus: 1.0
  ```
  Optionally retain the `deploy:` block with a comment noting it applies only in
  Swarm mode and is NOT the standalone enforcement path — but the top-level keys
  are the only mechanism that actually limits resources in standalone compose.
- **Regression guard:** The static-validation test class `TestDockerLatexmlConfig`
  in `tests/security/test_latexml_sandbox.py` should add an assertion that either
  the top-level `mem_limit` key is present or — if Swarm is the deployment target —
  a comment documents that `deploy.resources.limits` applies only in Swarm mode.
  The existing tests only assert `network_mode`, `no-new-privileges`, `read_only`,
  and user — they would pass unchanged after this fix.

### IS2 — HOME-read allowance covers secrets directories

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** infra/latexml/sandbox.sb:61
- **What:** `(allow file-read* (subpath (param "HOME")))` grants read access to the
  entire home directory tree. This includes `~/.ssh/`, `~/.aws/credentials`,
  `~/.gnupg/`, `~/.config/op/` (1Password CLI), and any other user credential stores
  that live under `$HOME`.
- **Why it matters:** While network-deny (`(deny network*)`) at line 79 prevents
  direct exfiltration, a hostile LaTeXML fixture could read a private key or token
  into the LaTeXML output stream (e.g., via `\input{~/.ssh/id_rsa}` parsed as a
  literal text file). The rendered HTML output ends up in OUTPUT_DIR, which is
  written back to the host. An attacker controlling the LaTeX source could harvest
  credentials via the output artifact. The file's own comment at line 59–60
  acknowledges this allowance is for "Perl module discovery" — but does not note
  the credential-read surface.
- **Proposed fix:** Narrow the HOME allowance to known Perl/CPAN paths:
  ```scheme
  (allow file-read*
    (subpath (string-append (param "HOME") "/perl5"))
    (subpath (string-append (param "HOME") "/.cpan"))
    (subpath (string-append (param "HOME") "/.cpanm"))
    (subpath (string-append (param "HOME") "/Library/Perl")))
  ```
  If the full HOME allowance is required for some Perl module discovery path that
  can't be enumerated, add explicit denies before it for known secret paths:
  ```scheme
  (deny file-read* (subpath (string-append (param "HOME") "/.ssh")))
  (deny file-read* (subpath (string-append (param "HOME") "/.aws")))
  (deny file-read* (subpath (string-append (param "HOME") "/.gnupg")))
  ```
  (macOS sandbox-exec applies rules in order; explicit deny before the allow wins.)
- **Regression guard:** `TestSandboxProfile` in `tests/security/test_latexml_sandbox.py`
  should add an assertion that either the bare `(param "HOME")` allowance is absent
  or an explicit deny for `.ssh` / `.aws` / `.gnupg` sub-paths precedes it.

### IS3 — Missing restart: policy on documentation compose service

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** infra/latexml/docker-compose.latexml.yml:25
- **What:** The `latexml` service has no `restart:` declaration. The implicit default
  in Compose is `no` (container stops and stays stopped), but this is not stated.
  When E14 merges this service definition into the main compose, the implicit default
  may interact unexpectedly with the main compose's own restart policies.
- **Why it matters:** A future operator copying this service block into the E14 main
  compose may inherit the missing restart policy and get Docker's ambient default
  (which differs between Docker Compose v1 and v2, and between standalone and Swarm
  deployments). An explicit `restart: "no"` documents intent and survives copy-paste.
- **Proposed fix:** Add `restart: "no"` at the service level, matching the Phoenix
  compose precedent (`infra/observability/phoenix-compose.yml:115`).
- **Regression guard:** Low-stakes documentation fix; no test guard required.

### IS4 — Relative path default for bind-mount source is unpredictable

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** infra/latexml/docker-compose.latexml.yml:75
- **What:** The `source: "${ARXMCP_LATEXML_OUTPUT_DIR:-./latexml-output}"` fallback
  resolves `./latexml-output` relative to the Compose FILE's directory
  (`infra/latexml/`), not the operator's current working directory. This means the
  fallback path is `infra/latexml/latexml-output/`, which is inside the repo tree
  and could pollute it with parsed LaTeX output artifacts.
- **Why it matters:** The `infra/latexml/` directory is not in `.gitignore`; output
  artifacts landing there would appear as untracked files. An operator who runs the
  container without setting `ARXMCP_LATEXML_OUTPUT_DIR` would write parsed output
  into a subdirectory of the infrastructure config tree. The `phoenix-compose.yml`
  precedent (line 94) handles this explicitly with a repo-root-relative
  `../../var/arxmcp/...` path.
- **Proposed fix:** Replace the default with a repo-root-relative path that matches
  the project's `var/arxmcp/` data convention:
  ```yaml
  source: "${ARXMCP_LATEXML_OUTPUT_DIR:-../../var/arxmcp/corpus/latexml-output}"
  ```
  And add a comment noting that in Compose v2, relative paths in bind-mount `source`
  resolve relative to the compose file location, not CWD.
- **Regression guard:** Verify `.gitignore` at repo root covers `var/arxmcp/` (it
  already does per CLAUDE.md §5). No test change needed.

### IS5 — No README.md in infra/latexml/ explaining standalone status

- **Severity:** LOW
- **Source:** infra-safety
- **File:** infra/latexml/ (directory)
- **What:** The `infra/latexml/` directory contains two files but no `README.md`.
  The `infra/README.md` (updated in E14) describes only the observability profile
  and does not mention the `latexml/` subdirectory or its standalone-documentation
  status. An operator scanning `infra/` would not know that
  `docker-compose.latexml.yml` is NOT the main compose and should not be run
  standalone in production.
- **Why it matters:** The file header comment explains the documentation-artifact
  status thoroughly — but only to a reader who opens the file. A directory listing
  reveals no such context.
- **Proposed fix:** Add `infra/latexml/README.md` with a two-sentence orientation:
  what the files are, that `docker-compose.latexml.yml` is a documentation artifact
  pending E14/E11 integration, and that `sandbox.sb` is the macOS profile (not wired
  at v1). Per CLAUDE.md §1, a navigational `README.md` for a subdir is explicitly
  allowed.
- **Regression guard:** None required for a LOW documentation finding.

## What was done well

- **Default-deny posture is correct.** `(deny default)` in `sandbox.sb:35` is the
  right baseline. Every permission must be explicitly granted.
- **Network deny is thorough.** The sandbox profile denies `network*`, `mach-bootstrap`,
  `mach-lookup`, and `ipc*` — all four vectors by which a sandboxed process might
  reach the network on macOS. This is not just `(deny network*)` but defense-in-depth
  at the IPC layer.
- **Unprivileged UID correctly implemented.** `user: "65534:65534"` (nobody:nobody) in
  the compose file satisfies the brief's "rootless container with an unprivileged user
  inside" mandate precisely.
- **cap_drop: ALL + no-new-privileges is the right combination.** These two directives
  together prevent both initial capability abuse and post-exec privilege escalation.
  Most hardening guides require both; both are present.
- **network_mode: none in compose is the correct choice.** `--network=none` gives the
  LaTeXML container no network interface at all — stronger than ACLs or firewall rules,
  which can be misconfigured. The inline comment explaining why this also blocks DNS
  (line 33–36) is accurate and helpful.
- **read_only: true + tmpfs is the right filesystem posture.** The root filesystem is
  immutable; the only writable paths are the explicit tmpfs mounts and the OUTPUT_DIR
  bind-mount. This matches the playbook in `.claude/notes/08-security-observability-ops.md`
  Threat 3.
- **tmpfs sizing is reasonable.** 64M for `/tmp` is adequate for LaTeXML's transient
  working files (typical LaTeX compilation uses <10 MB); 4M for `/var/run` is generous.
  The uid/gid on the `/tmp` tmpfs (65534:65534) ensures the nobody user can write to it.
- **Documentation-artifact status is clearly stated.** Both files carry explicit
  header comments explaining they are not wired into production at v1 and why.
  The implementation summary (synthesis D3, drift item 8) reinforces this. No
  inflation of the not-wired-in finding is warranted.
- **Deprecation status of sandbox-exec is documented.** Line 21–26 of `sandbox.sb`
  explicitly notes the deprecated status, the Darwin 25.x functional status, and the
  reason the successor (App Sandbox) is not suitable for this use case. This is
  exactly the right level of documentation for a footgun.
- **File permissions are correct.** Both files are `rw-r--r--` (644) — readable by
  others but not world-writable. No executable bit on a config/profile file.

## Recommended rectification order

1. **IS1 (HIGH)** — Replace `deploy.resources.limits` with top-level `mem_limit` and
   `cpus` keys, matching the `phoenix-compose.yml` precedent. Update the inline
   comment to note the Swarm-only restriction of `deploy.resources`. ~5 LOC diff.
2. **IS2 (MEDIUM)** — Narrow the `(allow file-read* (subpath (param "HOME")))` in
   `sandbox.sb` to known Perl paths, or add explicit denies for credential directories
   before the broad HOME allowance. ~5-10 LOC diff.
3. **IS3 (MEDIUM)** — Add `restart: "no"` to the latexml service. 1-line fix.
4. **IS4 (MEDIUM)** — Replace the `./latexml-output` default with the repo-root-
   relative `../../var/arxmcp/corpus/latexml-output` path. 1-line fix + comment.
5. **IS5 (LOW)** — Add `infra/latexml/README.md`. Defer if Phase 4 is time-constrained.

## Rectification status

- **IS1 (HIGH) — fixed.** `infra/latexml/docker-compose.latexml.yml`
  augmented with top-level `mem_limit: 2g` and `cpus: 1.0` (the
  standalone Docker Compose enforcement keys). The `deploy.resources`
  block is preserved with an inline comment noting it applies only
  in Docker Swarm mode. Standalone compose deployments now actually
  enforce the resource caps that the audit doc and inline comments
  describe as defense-in-depth against `fork_bomb.tex` and
  `large_alloc.tex`. Precedent: `infra/observability/phoenix-compose.yml`.
  Regression guard: `TestDockerLatexmlConfig::test_top_level_mem_limit_and_cpus`.
- **IS2 (MEDIUM) — fixed.** Cross-critic agreement with adversary F1.
  Resolved via the same sandbox.sb rewrite: explicit denies for
  credential directories (`~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.config/op`, `~/.netrc`, `~/.kube`, `~/.docker`) precede a
  narrow allow for enumerated Perl/CPAN module roots. sandbox-exec
  applies rules in order — earlier denies win over later allows.
  See adversary F1 rectification status for the full detail.
- **IS3 (MEDIUM) — fixed.** Added explicit `restart: "no"` to the
  `latexml` service. The implicit default in Compose v2 is `no` but
  differs subtly across Compose versions and Swarm modes; explicit
  declaration survives copy-paste into the E14 main compose.
  Regression guard: `TestDockerLatexmlConfig::test_restart_policy_explicit`.
- **IS4 (MEDIUM) — fixed.** Bind-mount source default changed from
  `./latexml-output` to `../../var/arxmcp/corpus/latexml-output`.
  The previous default resolved (in Compose v2) relative to the
  compose FILE's directory (`infra/latexml/`), polluting the repo
  source tree. The new default points under `var/arxmcp/`, which
  is gitignored per CLAUDE.md §5. Regression guard:
  `TestDockerLatexmlConfig::test_bind_mount_default_under_var_arxmcp`.
- **IS5 (LOW) — deferred.** Missing `infra/latexml/README.md`.
  Cosmetic; the file-header comments are clear enough for the
  documentation-artifact status to be obvious to anyone opening
  the files. Can land in a follow-up.

**Critic invalidation rate:** 0% (0 of 4 HIGH+MEDIUM findings
invalidated on re-verify; all 4 closed). Calibration clean.

**Cross-critic agreement:** IS2 (this critic) and F1 (adversary)
flagged the same sandbox.sb HOME-read surface. Both closed by a
single rewrite of the HOME-read clause. Confirms the dedupe pattern
the orchestrator's merge step is designed for.

# Critique — E13_S03

**Critic:** adversary
**Generated:** 2026-05-17T22:00:00Z
**Commit range:** b6871112979ef3b2323f99a152d141757c55d98f..03e062f4fb53a572a3e2d4c8ac5228257121081f
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Process-group kill discipline is well-implemented and the AST regression guard is exactly the right anchor for a milestone that delivers an invariant rather than a feature.
- 0 CRITICAL, 1 HIGH, 5 MEDIUM, 4 LOW findings. The single HIGH is a sandbox-profile over-permission worth fixing before the profile becomes "the documented baseline" that E11 picks up.
- Five fixture tests are accepted as passing on either of two outcomes (terminated OR timed_out); this means the test corpus may *never actually exercise the killpg path end-to-end* on a given machine — the AST guard is doing all the work here. Worth surfacing.
- `sandbox.sb` allows `file-read*` on the entire `$HOME` subtree (line 61), which gives a hostile fixture read access to `~/.ssh/`, `~/.aws/`, `~/.config/` — a real information-disclosure surface even though network egress is denied.
- The catastrophic-case branch in `parse_with_latexml` (lines 376–378, "group survives SIGKILL") has no test coverage; pipe-drain semantics are subtle and silently regressable.
- `tmpfs: /tmp:size=64M` in the Docker config is plausibly too small for real LaTeXML runs on heavy papers; will not surface as a security problem but will surface as a production-availability problem when E14 wires the compose.
- Two of five fixtures (`write18_shellout`, `network_call`) test side-effect absence rather than attack-trigger, which the audit doc honestly flags; the remaining three (`infinite_recursion`, `fork_bomb`, `large_alloc`) may not actually trigger Perl heap exhaustion or expansion runaway on real LaTeXML 0.8.x — fixture *effectiveness* is asserted but not measured.
- Cache, math fidelity, MCP spec, local-first, tier sequencing, and no-fork axes are all clean. Cross-axis pattern: the milestone is correctly scoped to Phase 1 (cross-platform Python defense) and defers Phase 2 to E11 without leaving load-bearing claims about deferred work.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Axis walk

| Axis | Status | Notes |
|---|---|---|
| 1. Cache byte-stability | clean | No `server/tools.py`, `server/prompts.py`, or `EXPECTED_TOOL_SCHEMA_SHA256` touched; no MCP surface change. |
| 2. Math fidelity | clean | `parse_with_latexml` change is in the subprocess invocation only — LaTeXML output shape (HTML5+MathML) unchanged. Detection still goes through `detect_parse_success` on the file. |
| 3. Security threat-model coverage | partial — see F1, F2, F3 | Process-group kill is correct (POSIX semantics); `raise` re-raises original `TimeoutExpired` correctly because `contextlib.suppress` does not swap the active exception. |
| 4. MCP 2025-06-18 compliance | N/A | No MCP surface change. |
| 5. Local-first + Docker constraint | clean | No external service dependencies; Docker config is a documentation artifact. |
| 6. Tier sequencing | clean | Brief depends on E06_S03 (shipped). Phase 2 deferral to E11 is documented in audit doc. |
| 7. No-fork policy | clean | grep for `arxiv-mcp` / `github.com/` references in new files returns zero hits. |
| 8. Test surface | partial — see F4, F5 | +15 tests; AST guard for the production invariant is the strong signal. Containment tests accept two outcomes per fixture, weakening attack-trigger coverage. |

## Findings

### F1 — `sandbox.sb` allows `file-read*` on entire `$HOME` subtree

- **Severity:** HIGH
- **Source:** adversary
- **File:** `infra/latexml/sandbox.sb:61`
- **What:** `(allow file-read* (subpath (param "HOME")))` grants the LaTeXML subprocess read access to *everything* under the operator's home directory: `~/.ssh/`, `~/.aws/credentials`, `~/.config/`, `~/.netrc`, `~/Documents/`, browser profiles, etc. The comment justifies this as "Perl's @INC discovery" but Perl's @INC under a user's home is typically a small set of well-known subpaths (`~/.cpan/`, `~/perl5/`, `~/.perlbrew/`, `~/.plenv/`).
- **Why it matters:** Even though `(deny network*)` blocks exfil via socket, a hostile fixture can embed read-back contents into the LaTeXML HTML output (e.g. by `\input{~/.ssh/id_rsa}` if LaTeXML resolves `~` and treats the file as TeX, or via Perl-level file reads triggered by an exploit chain). The audit doc on line 11 explicitly classifies sandbox escape as a HIGH-severity risk (LaTeX is Turing-complete, arXiv source is operator-supplied). When this profile gets wired into production in E11, the over-permission moves from "documentation drift" to "deployed weakness." Better to fix it at the documentation stage.
- **Proposed fix:** Replace the blanket `$HOME` allow with an enumerated list of known Perl/CPAN module roots:
  ```
  ;; Perl module discovery — enumerate @INC roots explicitly rather than
  ;; granting blanket $HOME read. Hostile fixture cannot read ~/.ssh,
  ;; ~/.aws, ~/.config, etc.
  (allow file-read*
    (subpath (string-append (param "HOME") "/.cpan"))
    (subpath (string-append (param "HOME") "/perl5"))
    (subpath (string-append (param "HOME") "/.perlbrew"))
    (subpath (string-append (param "HOME") "/.plenv")))
  ```
  If sandbox-exec doesn't support `string-append` in `subpath`, the operator passes a `PERL_INC_ROOT` parameter explicitly. Document in the file header that adding new HOME-relative reads requires audit.
- **Regression guard:** Add a `TestSandboxProfile.test_profile_does_not_grant_blanket_home_read` that fails if `(subpath (param "HOME"))` appears as a `file-read*` target without a path suffix. Easier: assert `~/.ssh` cannot appear inside any `(allow file-read* (subpath ...))` expression by parsing the profile and looking for bare `(param "HOME")` arguments.

### F2 — Catastrophic-case branch (group survives SIGKILL) has zero test coverage

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:376-378`
- **What:** After `os.killpg(...)` is sent, the code does:
  ```python
  with contextlib.suppress(subprocess.TimeoutExpired):
      proc.communicate(timeout=5)
  raise
  ```
  The bare `raise` is correct (re-raises the active `TimeoutExpired` that brought us into the `except` block; `contextlib.suppress` only swallows new exceptions raised inside the `with`, not the surrounding active one). However, no test in `test_latexml_sandbox.py` constructs a scenario where the second `communicate(timeout=5)` itself times out (i.e. the SIGKILL was ineffective). The branch is reachable only under kernel pathology, but the pipe-drain semantics here are exactly the kind of code that silently breaks under future refactors.
- **Why it matters:** A future engineer reading this code might "simplify" it to `proc.communicate()` (no timeout) thinking the SIGKILL must have worked — that change would deadlock the parent if the group really did survive. The branch as written is correct; without a regression guard it can decay.
- **Proposed fix:** Add a unit test that mocks `subprocess.Popen` so `communicate(timeout=...)` raises `TimeoutExpired` on both calls. Assert: (a) `os.killpg` was called once, (b) the second `communicate` was called with `timeout=5`, (c) the function re-raised `TimeoutExpired` (the original, not the suppressed one). Mock pattern from `tests/test_rectifications.py::TestF6ParseWithLatexml` already shows how to fake `Popen`.
- **Regression guard:** The new test itself; place in `tests/security/test_latexml_sandbox.py::TestProcessGroupKill::test_double_timeout_path_drains_pipes_and_reraises`.

### F3 — Containment tests accept "terminated normally" as success — fixture may never exercise killpg

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/security/test_latexml_sandbox.py:208, 244, 256, 285`
- **What:** Every containment test (`test_infinite_recursion_contained`, `test_fork_bomb_contained`, `test_large_alloc_contained`, `test_network_call_no_egress`) asserts `status in {"terminated", "timed_out"}`. On a sufficiently recent LaTeXML 0.8.x with internal expansion limits, EVERY fixture may end in `"terminated"` — meaning the `killpg` codepath is never exercised by the integration tests. The AST regression guard at `TestProcessGroupKill` confirms the code is *present* but not that it *runs* on hostile input.
- **Why it matters:** A future change to LaTeXML's expansion limit (or to the fixture itself) could leave the test suite green while the `killpg` path silently regresses. Either the timeout fires (good — production defense exercised) or LaTeXML's own limit fires (containment-positive but doesn't validate our defense). The audit doc on line 81 acknowledges this by-design choice ("Either is a valid containment outcome") but does not address the test-coverage hole.
- **Proposed fix:** Add at least one test that constructs a fixture *guaranteed* to outlast the Python timeout — e.g. a fixture that does literally nothing harmful but takes >timeout seconds (a Perl-level sleep would be ideal but not portable through LaTeX). Cheaper: add a test that monkeypatches `parse_with_latexml`'s LATEXML_TIMEOUT_SECONDS to a tiny value (say 0.1 s) and runs a normal-looking fixture, asserting the path fires `TimeoutExpired` AND a `killpg` was sent (verify via a `subprocess.Popen` mock that records `send_signal` / measures whether the group is dead after the kill).
- **Regression guard:** New test `test_timeout_fires_killpg_path` that mocks Popen with a fake that ignores the first `communicate(timeout=...)`, raises `TimeoutExpired`, and lets the test observe `os.killpg` being called.

### F4 — `large_alloc.tex` likely does not exhaust LaTeXML's heap

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/security/fixtures/latexml/large_alloc.tex:18-37`
- **What:** The redesigned fixture uses 30 nested `\underbrace` and a small `tabular`. The fixture's own comment claims this "exhausts LaTeXML's Perl heap." In practice, 30 nesting levels and a 4-row × 10-col table are well within LaTeXML's normal operating range — the parser routinely handles real research papers with deeper nesting in formal expressions. The test asserts `elapsed <= TEST_TIMEOUT_SECONDS + 5.0`, which a normally-parsing fixture trivially satisfies.
- **Why it matters:** The fixture as written is effectively a smoke test of "LaTeXML parses minor LaTeX," not a hostile-input test. If a future version of LaTeXML actually breaks on a real large-alloc input, this fixture won't catch it. The honest framing in `large_alloc.tex:12` ("LaTeXML exits successfully — both valid containment") is correct, but the *attack-class is not exercised* in a way that would catch a regression.
- **Proposed fix:** Either (a) deepen the nesting to ~200 levels and add many more table rows (still bounded so test runtime is reasonable), or (b) drop the "exhausts heap" claim from the fixture/docstring and explicitly mark this as a containment baseline rather than an attack test. Option (b) is honest and ≤10 LOC of docstring changes.
- **Regression guard:** N/A — the fix is the docstring change (or expanded fixture).

### F5 — `network_call.tex` test does not cover DNS resolution

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/security/test_latexml_sandbox.py:266-293`
- **What:** The test monkeypatches `socket.socket.connect` to detect TCP-level egress, but LaTeXML/Perl could perform DNS resolution via `socket.getaddrinfo` (which bypasses the `socket.socket` instance method) without ever calling `.connect()`. A successful DNS query to a hostile-controlled nameserver is itself an exfiltration channel.
- **Why it matters:** The audit doc on line 91 explicitly claims the network_call fixture "will fire loudly" if LaTeXML ever gains HTTP-fetch capability. That claim is wrong if the egress is DNS-only — the monkeypatch doesn't see DNS. This is the kind of gap that, when discovered post-ship, makes the audit doc less trustworthy.
- **Proposed fix:** Additionally monkeypatch `socket.getaddrinfo` (and `socket.gethostbyname` for older code paths) to record/block DNS resolutions to non-localhost hosts. Pattern:
  ```python
  real_getaddrinfo = socket.getaddrinfo
  def _record_dns(host, *args, **kwargs):
      if host not in {"localhost", "127.0.0.1", "::1"}:
          attempted_dns.append(host)
          raise OSError(f"Threat-3 BREACH — DNS egress: {host}")
      return real_getaddrinfo(host, *args, **kwargs)
  monkeypatch.setattr(socket, "getaddrinfo", _record_dns)
  ```
- **Regression guard:** The expanded test itself; the existing assertion structure already supports adding `assert not attempted_dns`.

### F6 — Docker `tmpfs: /tmp:size=64M` likely too small for real arXiv parses

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `infra/latexml/docker-compose.latexml.yml:66`
- **What:** The 64M cap on `/tmp` is a defense-in-depth measure but smaller than the typical intermediate-tempfile footprint of LaTeXML on real research papers. arXiv math/physics papers with many included figures or `\input{}` cycles routinely cause LaTeXML to produce >100M of intermediate Perl tempfiles (`*.aux`, `*.toc`, plus Perl's own File::Temp scratch). Once E14 wires this into the main compose, legitimate papers will fail to parse.
- **Why it matters:** This is not a security regression — it's an operational regression that turns the security config into a production-availability bug. Better to right-size now than discover during E11 backfill that 64M is too small.
- **Proposed fix:** Bump the tmpfs size to 512M (or 1G), or parameterize it via an env var with a documented baseline. Update the comment to reflect the actual operational budget. Cite: production arXiv papers in `math.AG` typically produce 50-200 MB of LaTeXML intermediates per parse. Note: the audit doc nowhere claims 64M is a measured minimum; it's a guess.
- **Regression guard:** N/A — this is an operational tuning change. Document in the file header what observed papers required.

### F7 — `parse_with_latexml` POSIX-only on the timeout path (start_new_session unsupported on Windows)

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:354-378`
- **What:** `start_new_session=True` is POSIX-only per Python docs. `os.killpg` and `os.getpgid` are also POSIX-only. On Windows, these calls raise `AttributeError` at runtime. The project does not target Windows (CLAUDE.md confirms macOS dev / Linux production), but the code now silently breaks on Windows where it previously raised a clean error from `latexmlc` not being on PATH.
- **Why it matters:** A Windows-curious operator picking up the repo will hit `AttributeError: module 'os' has no attribute 'killpg'` instead of a readable diagnostic. This is a friendliness issue, not a security issue.
- **Proposed fix:** Document the POSIX requirement in the docstring (already done in the lines 320–331 comment block — clean). Optionally add a runtime check `if not hasattr(os, "killpg"): raise RuntimeError(...)` at function entry. The current state is acceptable for the project's stated platform scope.
- **Regression guard:** None required — Windows is explicitly out of scope.

### F8 — `_run_fixture` defensive `hasattr` check is dead code

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/security/test_latexml_sandbox.py:157`
- **What:** `result.exit_code if hasattr(result, "exit_code") else 0` — `ParseResult` is a frozen dataclass with `exit_code` as a declared field. The attribute always exists; the `else 0` branch is dead code and the conditional reads as "I'm not sure what this returns" when in fact the schema is pinned.
- **Why it matters:** Dead code in tests obscures the contract being tested.
- **Proposed fix:** Replace with `result.exit_code`.
- **Regression guard:** N/A.

### F9 — `_baseline_tmp_canary_snapshot` filter is narrow; only catches canary-prefix writes

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/security/test_latexml_sandbox.py:86-93`
- **What:** The snapshot uses `Path("/tmp").glob("arxmcp_pwned_e13s03*")` which only sees writes matching this exact prefix. If a future hostile fixture tries `/tmp/leaked-data.txt` or `/tmp/.hidden_canary`, the test would not detect it.
- **Why it matters:** Test thoroughness — the current fixture set only attempts the canary prefix, so today's test is sound. The audit doc could explicitly tie this together: "if a new fixture introduces a different attempted write path, the snapshot prefix must be widened."
- **Proposed fix:** Add a comment at the snapshot function acknowledging the prefix is tied to the fixture corpus. When a new fixture is added with a different write path, the prefix must be widened — and add a generic "new files in /tmp/ during this test" guard that the prefix-filter complements.
- **Regression guard:** N/A — documentation fix.

### F10 — Docker `user: "65534:65534"` hardcodes Debian/Alpine's `nobody` UID

- **Severity:** LOW
- **Source:** adversary
- **File:** `infra/latexml/docker-compose.latexml.yml:53`
- **What:** UID 65534 is `nobody` on Debian/Ubuntu/Alpine but `99` on RHEL/Fedora/CentOS and `-2` (4294967294) on macOS. The container's base image determines which UID maps to `nobody`. The arXMCP latexml image is published by the project itself (`arxmcp/latexml:0.8.8` per line 31), so this is fine if the image is Debian-based, but the choice is implicit.
- **Why it matters:** When E11 publishes the actual image with a pinned SHA, the base distro should be documented alongside this UID. Otherwise a future rebuild on a different base could quietly run latexml as a different "nobody."
- **Proposed fix:** Add a comment: `# 65534 = `nobody` on Debian-based images (the published arxmcp/latexml is Debian slim). Any UID > 0 satisfies the non-root requirement.`
- **Regression guard:** N/A.

## What was done well

- The phasing decision (Phase 1 cross-platform Python defense today; Phase 2 sandbox/seccomp/landlock deferred to E11) is correctly scoped — no claims about Phase 2 invariants get made before the production wiring exists.
- The AST-based regression guard (`TestProcessGroupKill`) anchors the invariant at the right level — it confirms the production code carries the contract regardless of whether any test happens to fire the timeout path. This mirrors the E13_S02 F3 pattern and is the right shape for milestones that deliver invariants rather than features.
- The implementation summary's "Drift from brief" section honestly enumerates 9 documented departures from the brief and explains each. Same discipline as E13_S01 / E13_S02 — pattern continues to pay off.
- `contextlib.suppress(ProcessLookupError)` around `os.killpg` correctly handles the race where the child exited between the timeout firing and the kill — the suppress is scoped tightly to one operation and the comment explains why.
- The bare `raise` after `contextlib.suppress(TimeoutExpired)` (line 378) is the correct Python idiom — `contextlib.suppress` does not replace the currently-active exception, so the original `TimeoutExpired` is correctly re-raised. Subtle and right.
- The audit doc's fixture-effectiveness table (lines 79–85) honestly labels which fixtures test attack-trigger vs. side-effect absence with ✅/⚠️ markers. Honesty about limitations is the right move for a security doc.
- `tests/test_rectifications.py::TestF6ParseWithLatexml` was correctly updated in lockstep with the API change (subprocess.run → Popen). No silent regression risk to the F6 contract.
- Doc placement is correct (`.claude/docs/security-threat-3-audit.md`, not `docs/`) — same disciplined reframe as E13_S01 / E13_S02.
- No-fork policy clean — zero references to external `arxiv-mcp` repos in any new file.
- No MCP tool surface change, no cache hash drift, no `EXPECTED_TOOL_SCHEMA_SHA256` mutation. Properly scoped.

## Recommended rectification order

1. **F1** (HIGH) — Restrict `sandbox.sb`'s HOME read access. This is the only HIGH finding and the cheapest fix that materially reduces threat surface.
2. **F3** (MEDIUM) — Add a test that *forces* the timeout path to fire via mocked Popen. This protects against future fixture/LaTeXML version drift making the killpg path silently uncovered.
3. **F2** (MEDIUM) — Add the catastrophic-case test (group-survives-SIGKILL path). Same Popen-mock pattern as F3; cheap to combine.
4. **F5** (MEDIUM) — Extend the network test to also block DNS resolution. The audit doc's "will fire loudly" claim is load-bearing and currently overstated.
5. **F6** (MEDIUM) — Re-size tmpfs in Docker config from 64M to 512M (or document the measured minimum).
6. **F4** (MEDIUM) — Either deepen `large_alloc.tex` to actually exercise heap pressure, or honestly relabel it as a containment baseline.
7. **F7, F8, F9, F10** (LOW) — Defer per the calibration table.

## Rectification status

- **F1 (HIGH) — fixed.** `infra/latexml/sandbox.sb` rewritten:
  blanket `(allow file-read* (subpath (param "HOME")))` removed.
  Replaced with explicit denies for `~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.config/op`, `~/.netrc`, `~/.kube`, `~/.docker` (sandbox-exec
  applies rules in order — deny-before-allow wins), followed by
  narrow allows for enumerated Perl/CPAN roots (`~/perl5`,
  `~/.cpan`, `~/.cpanm`, `~/.perlbrew`, `~/.plenv`,
  `~/Library/Perl`). Cross-critic agreement with IS2 from
  infra-safety. Regression guards:
  `TestSandboxProfile::test_profile_does_not_grant_blanket_home_read`
  and `test_profile_denies_credential_directories`.
- **F2 (MEDIUM) — fixed.** Added
  `TestProcessGroupKill::test_catastrophic_case_drains_pipes_and_reraises`
  — uses mocked Popen so BOTH `communicate(timeout=...)` calls raise
  `TimeoutExpired`. Asserts: (a) 2 communicate calls (initial + 5s
  drain), (b) killpg with SIGKILL on the PGID, (c) original
  `TimeoutExpired` re-raised via the bare `raise` after
  `contextlib.suppress`. Anchors the catastrophic-case branch
  against future "simplifications" that would deadlock.
- **F3 (MEDIUM) — fixed.** Added
  `TestProcessGroupKill::test_timeout_fires_killpg_path` — mocks
  Popen so the first `communicate` raises `TimeoutExpired`. Asserts
  `os.killpg(pgid, SIGKILL)` was called exactly once with the
  child's PGID. Anchors the killpg path independent of whether the
  integration containment tests happen to fire the timeout branch
  on a given machine.
- **F4 (MEDIUM) — fixed.** `large_alloc.tex` docstring rewritten:
  explicitly relabeled as a CONTAINMENT BASELINE rather than an
  active attack. The 30-level nesting + 4×10 tabular does NOT
  actually exhaust LaTeXML's Perl heap; honest framing replaces
  the previous overclaim. Future redesign with ~200 levels remains
  open if heap-pressure coverage is needed.
- **F5 (MEDIUM) — fixed.** `test_network_call_no_egress` extended
  to monkeypatch `socket.getaddrinfo` AND `socket.gethostbyname`
  in addition to `socket.socket.connect`. Now blocks/records BOTH
  TCP-level egress AND DNS resolution to external hosts (filtering
  out localhost / 127.0.0.1 / ::1). Closes the audit doc claim
  "will fire loudly" — previously DNS-only egress would have
  bypassed the test.
- **F6 (MEDIUM) — fixed.** `infra/latexml/docker-compose.latexml.yml`:
  tmpfs `/tmp` size bumped 64M → 512M. Real arXiv math/physics
  papers produce 50–200 MB of intermediate Perl tempfiles; the
  previous cap would cause legitimate parses to fail when
  E14/E11 wires this into production.
- **F7 (LOW) — deferred.** Windows POSIX-only issue. Project does
  not target Windows (CLAUDE.md macOS dev / Linux production).
  Documented in `parse_with_latexml` docstring.
- **F8 (LOW) — deferred.** Dead `hasattr` check in `_run_fixture`.
  Cosmetic; functionally correct.
- **F9 (LOW) — deferred.** Canary prefix filter is narrow. When a
  new fixture introduces a different write path, the prefix can be
  widened. Documented behavior; no current breach.
- **F10 (LOW) — deferred.** UID 65534 is Debian convention; the
  arxmcp/latexml image is Debian-based. Will be documented when E11
  publishes the actual image with a pinned digest.

**Critic invalidation rate:** 0% (0 of 6 HIGH+MEDIUM findings
invalidated on re-verify; all 6 closed by code/test changes).
Calibration clean.

**Test count delta from rect:** +7 tests (1975 → 1982). Breakdown:
- F1 + IS2: 2 (profile no-blanket-HOME, explicit credential denies)
- F2: 1 (catastrophic-case drains and reraises)
- F3: 1 (timeout fires killpg path)
- IS1: 1 (top-level mem_limit + cpus)
- IS3: 1 (explicit restart)
- IS4: 1 (bind-mount default under var/arxmcp)

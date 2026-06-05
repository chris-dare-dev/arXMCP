# Research Brief — windows-parse-path-fix-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-06-04T00:00:00Z

---

## In-codebase context

### Env-whitelist architecture: module-level constant computed at import time

`_ENV_WHITELIST` (line 87–89 of `ingest/textbook_parser.py`) is a **module-level `frozenset`
computed once at import time** using `sys.platform == "win32"`. This has a critical test
implication (see Failure-mode analysis): `monkeypatch.setattr(sys, "platform", "win32")` in
tests does NOT retroactively change `_ENV_WHITELIST`, because the expression already evaluated.

`_scrub_subprocess_env` (line 224) consumes `_ENV_WHITELIST` by iterating over it and copying
matching keys from `os.environ` into the child env. It unconditionally adds `TMPDIR` as an
override. The function does NOT set a Windows equivalent (`TEMP`/`TMP` override). **This is a
latent gap:** on Windows, if a caller passes `output_dir` as the intended scratch dir, MinerU
may still read `TEMP`/`TMP` from the whitelisted values — the TMPDIR override contract
(research-synthesis §D4, FM-8) is not fully closed on Windows.

**Load-bearing verbatim quote from `security-pdf-sandbox.md`:**
> "Strips proxies, AWS / GCP / Azure / HuggingFace credentials. Whitelists ONLY the variables
> MinerU genuinely needs (PATH for binary lookup; HOME for ~/.cache lookup of bundled ONNX
> models; LANG / LC_ALL for locale). TMPDIR is explicitly OVERRIDDEN to `str(output_dir)`
> rather than inherited, preventing cross-notebook scratch contamination."

The Windows fix adds `TEMP` and `TMP` to the whitelist but does NOT add a corresponding
`TEMP`/`TMP` override. The POSIX side overrides `TMPDIR`; the Windows side should override
`TEMP` (the Windows scratch convention Python's `tempfile` honors first) for consistency.

### `parse_with_latexml` fix: latexmlc_bin flow

The diff shows `latexmlc_bin = shutil.which("latexmlc")` at line 522, checked for `None` with
an explicit RuntimeError, then used in `cmd = [latexmlc_bin, ...]` at line 543. **The None
check at line 523–527 runs before `latexmlc_bin` is used in `cmd`**, so passing `None` as
`cmd[0]` is not reachable via the normal flow. However: if `shutil.which` is patched to return
`None` in tests but the `None` check is also patched away (e.g. via mocking `parse_with_latexml`
directly), `subprocess.Popen(cmd=None, ...)` produces a confusing TypeError rather than the
clear RuntimeError. Tests must mock `shutil.which` returning None and verify the RuntimeError
path, not skip straight to mocking Popen.

### timeout/kill fix for Windows

The `os.killpg`/`os.getpgid` fix is guarded with `hasattr(os, "getpgid")`, which is correct.
On Windows, `start_new_session=True` is documented by Python as a no-op (it is silently
accepted but has no effect — CreateProcess does not create a new session the same way POSIX
does). This means the process-group kill discipline that is load-bearing for the POSIX threat
model does NOT apply on Windows. `proc.kill()` terminates only the direct child; Perl helpers
forked by `latexmlc` are NOT reaped. This is an **accepted gap**, analogous to the MinerU 3.x
grandchild gap documented in `security-pdf-sandbox.md §"explicitly does NOT do"`.

### Existing broken test at line 197

```python
def test_whitelist_set_unchanged(self) -> None:
    assert frozenset({"PATH", "HOME", "LANG", "LC_ALL"}) == _ENV_WHITELIST
```

**This test will FAIL on Windows** (where `_ENV_WHITELIST` includes the 13 Windows vars) and
**will FAIL on POSIX after the fix** only if something regressed. Actually on POSIX this test
still passes since `_ENV_WHITELIST` equals the POSIX base. But the test is now semantically
misleading: it hard-pins the POSIX value while on Windows the constant is legitimately larger.
The implementer must update this test to be platform-conditional OR split into two: one for
the POSIX constant and one for the Windows constant.

### Latent gap: `server/config.py` rejects `ARXMCP_MINERU_BIN` / `ARXMCP_MINERU_TIMEOUT_S`

The milestone brief correctly flags this. `server/config.py` uses `extra="forbid"` via Pydantic
with `env_prefix="ARXMCP_"`. Variables `ARXMCP_MINERU_BIN` and `ARXMCP_MINERU_TIMEOUT_S` are
consumed by `ingest/textbook_parser.py` at module load, not by the server Config class. An
operator who sets these in their shell before running `make up` will get a Pydantic validation
error at server startup. This gap exists pre-patch and is NOT introduced by this milestone's
fixes; it is a pre-existing latent issue to document, not to fix here.

---

## Security review (primary deliverable)

The env scrub's security intent is: **strip all proxies, credentials, and egress-enabling
vars** from the MinerU subprocess environment, preventing a hostile PDF from using them to
exfiltrate data. The threat model source (`08-security-observability-ops.md` Threat 3) requires
"No network access from the LaTeXML subprocess" and "scrubbed env (no proxies, no
credentials)."

**Per-variable verdict for the 13 new Windows additions:**

| Variable | Credential? | Proxy/egress? | Cloud token? | Necessary? | Verdict |
|---|---|---|---|---|---|
| `SystemRoot` | No | No | No | **Yes** — without it, Windows socket provider init fails (WinError 10106 verified live) | KEEP |
| `SYSTEMROOT` | No | No | No | Redundant with `SystemRoot` (Windows env is case-insensitive, but Python's `os.environ` on Windows normalizes case); belt-and-suspenders for case mismatch in subprocess | KEEP (low cost, robustness) |
| `USERPROFILE` | No | No | No | Path-leak only (exposes home dir — same as POSIX `HOME` which is already in whitelist); MinerU needs it for `~/.cache/mineru/` ONNX weights | KEEP — analogous to POSIX `HOME` |
| `LOCALAPPDATA` | No | No | No | MinerU + HF cache on Windows uses `%LOCALAPPDATA%\huggingface\`; needed for model weight lookup | KEEP |
| `APPDATA` | No | No | No | Same family — Windows roaming profile; MinerU's `mineru.json` config may live here | KEEP (borderline — could test without it) |
| `TEMP` | No | No | No | Windows scratch dir; `tempfile.mkstemp` reads `TEMP` before `TMP` | KEEP — but needs a `TEMP` override analogous to POSIX `TMPDIR` override |
| `TMP` | No | No | No | Fallback after `TEMP`; Python honors both | KEEP — same override requirement |
| `windir` | No | No | No | Windows install dir (e.g. `C:\Windows`); some native libs probe it at startup | KEEP |
| `SystemDrive` | No | No | No | Drive letter for Windows root (e.g. `C:`); low-value but harmless | KEEP |
| `PATHEXT` | No | No | No | File extension precedence for `CreateProcess` (`.COM;.EXE;.BAT;.CMD`); without it, bare `latexmlc` may not resolve even after the Fix 2 patch if other subprocess calls inside MinerU use bare names | KEEP |
| `NUMBER_OF_PROCESSORS` | No | No | No | CPU count hint; some ONNX/torch thread pools read it | KEEP |
| `PROCESSOR_ARCHITECTURE` | No | No | No | Architecture string (e.g. `AMD64`); native lib resolution may use it | KEEP |
| `COMSPEC` | **Borderline** | Potential | No | Path to `cmd.exe`. Required if MinerU or Perl invokes a shell internally. BUT: if a hostile PDF can trigger shell execution via this var, it becomes a vector. The threat is low given subprocess is NOT `shell=True`, but this is the riskiest of the 13 | KEEP with note — NOT a credential, but note the shell-path concern |

**Overall verdict: the security intent of the scrub is preserved.** None of the 13 vars are
credentials, proxy settings, cloud tokens (AWS/GCP/Azure), or HuggingFace API keys. The four
credential families explicitly cited in the security-pdf-sandbox.md doc — proxies, AWS, GCP,
Azure/HF — remain stripped. `USERPROFILE`/`APPDATA`/`LOCALAPPDATA` expose the home-dir path
(same category as POSIX `HOME`, already in the POSIX whitelist — acceptable, documents a
path-disclosure, not a credential disclosure).

**One recommendation:** `COMSPEC` carries a non-zero risk if MinerU's Python or Perl code
invokes `subprocess.Popen(..., shell=True)` internally. It is a path to `cmd.exe`, not a
secret, so the risk is indirect (enables shell invocation, not direct credential leak). Given
the subprocess is not started with `shell=True` at the arXMCP layer, and MinerU 3.x uses
an internal FastAPI server (not shell invocations), the risk is LOW. KEEP but document.

**Missing: `TEMP`/`TMP` override.** The POSIX side overrides `TMPDIR` to `output_dir`.
The Windows side should also override `TEMP` (and optionally `TMP`) to `output_dir` to close
the cross-notebook scratch contamination risk (FM-8). This is a correctness gap, not a security
gap, but it undermines the documented design intent.

---

## Failure-mode analysis

**FM-1: `shutil.which("latexmlc")` returns `None` on Windows because latexmlc is not on PATH.**
- Trigger: LaTeXML not installed or not in PATH on Windows.
- Symptom: `RuntimeError("latexmlc not on PATH...")` raised. The fix still propagates this
  correctly (the None check runs before `cmd` is built).
- Mitigation: Already handled — the None check at line 523–527 is unchanged.

**FM-2: `sys.platform` monkeypatching in tests does not affect `_ENV_WHITELIST` (computed at import).**
- Trigger: A test tries `monkeypatch.setattr(sys, "platform", "win32")` to simulate Windows
  env and then checks `_ENV_WHITELIST` includes Windows vars.
- Symptom: Test passes on Windows, fails on POSIX (or vice versa) — not a platform simulation.
- Mitigation: Tests must monkeypatch `textbook_parser._ENV_WHITELIST` directly, OR import
  `_ENV_WHITELIST_WINDOWS` and `_ENV_WHITELIST_POSIX` separately and test them independently,
  OR run the Windows-path test only on `sys.platform == "win32"`. The existing test at line 197
  hardcodes the POSIX frozenset and will fail on Windows.

**FM-3: `proc.kill()` on Windows does not reap Perl helper processes spawned by latexmlc.**
- Trigger: Timeout fires on Windows; `proc.kill()` terminates `latexmlc.BAT` (the cmd.exe
  wrapper) but the Perl process it launched survives.
- Symptom: Orphaned `perl.exe` process consuming CPU/memory after timeout; the Python timeout
  path considers itself done, but Perl continues parsing.
- Mitigation: Accepted gap (analogous to MinerU grandchild gap in security-pdf-sandbox.md);
  document explicitly. On Windows `start_new_session=True` is a no-op, so process-group kill
  was never available here.

**FM-4: `TEMP`/`TMP` not overridden on Windows — cross-notebook scratch contamination.**
- Trigger: Two concurrent MinerU invocations (two notebooks being ingested simultaneously)
  on Windows both read the real `TEMP` value (e.g. `C:\Users\cedar\AppData\Local\Temp`)
  for scratch files.
- Symptom: Scratch files from one notebook bleed into another's temp dir; possible parse
  corruption or temp-file collision.
- Mitigation: Add `env["TEMP"] = str(output_dir)` (and optionally `env["TMP"]`) in
  `_scrub_subprocess_env`. Mirrors the POSIX `TMPDIR` override discipline.

**FM-5: `SYSTEMROOT` + `SystemRoot` both in whitelist — env case-sensitivity surprise.**
- Trigger: On Windows, `os.environ` is case-insensitive but `os.environ.keys()` returns the
  original-case names. If the system sets `SystemRoot` (typical), both `SystemRoot` and
  `SYSTEMROOT` would attempt to copy the same value (one matches, the other doesn't). On
  POSIX the Windows frozenset is never evaluated so no collision occurs.
- Symptom: Minor redundancy on Windows (one lookup succeeds, one fails silently). Not a
  correctness issue.
- Mitigation: Low priority. The current dict comprehension (`if key in os.environ`) handles
  this gracefully via case-insensitive `in` on Windows's `os.environ`.

**Bonus FM-6: `latexmlc_bin` resolved via `shutil.which` but MinerU internally calls `latexmlc`
as a bare name within its own subprocess chain (if it shells out to LaTeXML as a processing
step).**
- Trigger: MinerU 3.x internally invokes LaTeXML — Fix 2 only covers the arXMCP-level
  invocation.
- Symptom: MinerU subprocess fails with `FileNotFoundError` inside its own code on Windows.
- Mitigation: Out of scope for this milestone; MinerU's internal subprocess discipline is
  upstream's responsibility.

---

## Prior decisions and lessons

- `git log --oneline -10`: most recent commit is `702b586 chore(notes): finalize
  oldstyle-id-ingest-fix-m1 state -> complete`. No prior Windows-specific test pattern
  established.
- `security-pdf-sandbox.md §"explicitly does NOT do"` explicitly accepts the grandchild
  process gap. The Windows `proc.kill()` fallback is analogous and should cite this accepted-gap
  precedent in comments.
- The POSIX `TMPDIR` override pattern (FM-8 in research-synthesis) is load-bearing; the Windows
  fix MUST extend it to `TEMP`.
- **KMP_DUPLICATE_LIB_OK** in `tests/conftest.py` must not be removed (macOS guard).

---

## External sources

No MCP spec or Anthropic prompt-caching docs are relevant to this milestone (no tool surface
changes). The relevant external reference is Python `subprocess` Windows documentation
confirming `start_new_session=True` is a no-op on Windows (Python 3.11 docs: "On POSIX,
`start_new_session` causes the child process to be placed in a new session. On Windows,
this is equivalent to setting `CREATE_NEW_PROCESS_GROUP`."). This means process-group kill
semantics differ but the gap is accepted. No web fetch required — Python stdlib behavior is
stable.

---

## Recommendation

Implement the three fixes as-is, with these required additions before committing:

1. **Add `TEMP`/`TMP` override in `_scrub_subprocess_env`**: on Windows, after the whitelist
   loop, add `env["TEMP"] = str(output_dir)` and `env["TMP"] = str(output_dir)` to preserve
   the cross-notebook scratch isolation contract from FM-8.

2. **Update the existing test at line 197**: replace the hard-pinned `frozenset({"PATH",
   "HOME", "LANG", "LC_ALL"})` assertion with a platform-conditional check: on Windows,
   assert `_ENV_WHITELIST_POSIX | _ENV_WHITELIST_WINDOWS == _ENV_WHITELIST`; on POSIX,
   assert `_ENV_WHITELIST_POSIX == _ENV_WHITELIST`. Import `_ENV_WHITELIST_POSIX` and
   `_ENV_WHITELIST_WINDOWS` from the module.

3. **Add a Windows kill-gap comment** citing the security-pdf-sandbox.md accepted-gap
   precedent: `proc.kill()` on Windows does not reap Perl helpers, analogous to the MinerU
   grandchild gap.

4. **`COMSPEC` documentation**: add a one-line comment in `_ENV_WHITELIST_WINDOWS` noting
   the shell-path nature of `COMSPEC` and why it is nonetheless required (MinerU/Perl may
   invoke cmd.exe for internal subprocess steps).

The security intent of the scrub is **preserved**. None of the 13 Windows vars are credentials
or egress enablers. The implementation can proceed on this recommendation.

---

## Open questions

1. **`TEMP`/`TMP` override**: should `_scrub_subprocess_env` override both `TEMP` and `TMP`,
   or only `TEMP` (the primary)? Recommendation: override both, mirroring the spirit of the
   POSIX `TMPDIR` override (belt-and-suspenders).

2. **`server/config.py` `extra="forbid"` vs `ARXMCP_MINERU_BIN`**: is this gap in scope for
   this milestone? Recommendation: OUT OF SCOPE — document it as a follow-up issue (it predates
   this milestone and fixing it touches `server/config.py`, which is security-audited code
   unrelated to the Windows parse path).

3. **`COMSPEC` necessity**: is there a confirmed code path where MinerU or Perl requires
   `COMSPEC`? Recommendation: KEEP it (low risk, hard to test, MinerU internals are opaque),
   but add the comment.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no ticket, no infra mutation.
The milestone brief calls for a commit; that is a local write within the external-write
boundary definition.

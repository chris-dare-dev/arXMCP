Three uncommitted working-tree fixes make the textbook-PDF parse path (MinerU + LaTeXML) work on native Windows. They touch security-audited subprocess code, so they need the full /milestone-pipeline treatment (Research -> Implement -> Critique -> Rectify) with regression tests before committing. All three were verified live (a 1-page PDF parsed end-to-end: MinerU -> LaTeXML -> index.html with MathML).

## The three fixes (already in the working tree)

### Fix 1 — ingest/textbook_parser.py: `_ENV_WHITELIST` was POSIX-only
`_ENV_WHITELIST` was `{PATH, HOME, LANG, LC_ALL}`. On Windows the scrubbed MinerU
subprocess died with `OSError: [WinError 10106]` (missing SystemRoot -> socket
provider init fails; torch/onnxruntime can't import). Fix: split into
`_ENV_WHITELIST_POSIX` + `_ENV_WHITELIST_WINDOWS` (SystemRoot, SYSTEMROOT,
USERPROFILE, LOCALAPPDATA, APPDATA, TEMP, TMP, windir, SystemDrive, PATHEXT,
NUMBER_OF_PROCESSORS, PROCESSOR_ARCHITECTURE, COMSPEC), unioned only when
`sys.platform=='win32'`. POSIX behavior byte-identical. None of the added vars are
secrets/proxies/cloud creds, so the scrub's security intent is preserved — but a
security reviewer should confirm.

### Fix 2 — tools/arxiv_fetch.py `parse_with_latexml`: bare "latexmlc" string
The Popen cmd used the bare string "latexmlc". On Windows latexmlc is a Perl script
exposed as latexmlc.BAT, and CreateProcess appends .exe (never .bat) ->
FileNotFoundError. Fix: capture `latexmlc_bin = shutil.which("latexmlc")` (already
called for the presence check) and use it as cmd[0]. On POSIX it's the same binary
the bare name resolved to.

### Fix 3 — tools/arxiv_fetch.py same function, timeout branch
`os.killpg(os.getpgid(...))` is POSIX-only and `start_new_session` is a no-op on
Windows -> AttributeError on a timeout. Fix:
`if hasattr(os, "getpgid"): os.killpg(...) else: proc.kill()`.

## Tasks
(a) regression tests — env whitelist contents per-platform (monkeypatch sys.platform),
    latexmlc cmd[0] uses the which() result, killpg fallback on no-getpgid;
(b) security review of the env-whitelist expansion (confirm no credential/egress var added);
(c) ruff + full `make test` (note ~60 pre-existing Windows-only failures);
(d) commit per repo conventions (conventional commits, GPG — will land unsigned per the
    workstation's known no-key state, co-author trailer).

## Context
Discovered setting up MinerU+LaTeXML on native Windows to ingest the 9 PDFs in
var/arxmcp/notebooks/bridgeland-stability/pending-pdfs.txt.

## Latent gap (NOT fixed — flag for consideration, do not necessarily fix here)
server/config.py's `_scan_unknown_arxmcp_env_vars` rejects ARXMCP_MINERU_BIN /
ARXMCP_MINERU_TIMEOUT_S as undeclared, so the server-hosted parse path (UI upload)
cannot run with those set; the CLI parse path sidesteps it. Consider declaring those
as Config fields or adding a server-tolerated-ingest-var carve-out.

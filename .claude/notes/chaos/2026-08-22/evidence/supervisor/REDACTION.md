# Redaction note

`CHAOS-SUP-01-child-log-token.txt` and `CHAOS-SUP-02-events-uppercase-token.ndjson` are the
evidence for findings `CHAOS-SUP-01` / `CHAOS-SUP-02` (GitHub #438 / #439): a live supervisor
startup token reaching the log files verbatim, and the case-shift that defeats `redact.rs::scrub`.

**Two captured token values were replaced before this register was committed**, because this is a
public repository:

| placeholder | what it was |
|---|---|
| `redacted-startup-token-a-xxx…` | the live token written verbatim into `logs/desktop-child.log` (SUP-01) |
| `REDACTED-STARTUP-TOKEN-C-XXX…` | the token whose UPPERCASE copy passed `scrub` untouched (SUP-02) |

**The placeholders preserve length (64 hex chars, and the 32-char prefix where that was what
leaked) and case**, so both findings stay provable from the files as committed. SUP-02 in
particular still reads correctly: the scrubber's own `[REDACTED]` appears on the lowercase
occurrences while the uppercase slot passed through unredacted, which *is* the bug.

Nothing else was altered. One value initially caught by the redaction sweep — the 64-hex string
under `executable.sha256` in the launch frame — is the fixture-sidecar binary's digest, not a
secret, and was **restored** to its real value.

The tokens were ephemeral: generated per supervisor launch, and those processes are long dead.
Nothing live was exposed. They were removed as hygiene, not as incident response. The unredacted
captures were never committed and no longer exist.

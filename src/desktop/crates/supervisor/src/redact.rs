//! Active scrub-before-persist for the one secret the supervisor handles.
//!
//! Coverage is CALL-SITE discipline, not a writer property: `Recorder::record`
//! does not scrub, and `scrub` has exactly one production caller — the
//! `bound-frame-invalid` diagnostic in `lifecycle.rs`. The other raw-child
//! sink, `logs/desktop-child.log`, is the child's own stderr fd and is
//! defended independently by the Python `RedactionFilter`. **Any new event
//! field carrying a child-derived string MUST route through `scrub` itself**;
//! nothing structural enforces that yet.
//!
//! **`scrub` alone is NOT sufficient for child-controlled text (#439).** Its
//! exact-match semantics are correct for what it is — removing a known secret
//! without corrupting legitimate digests — but the CASING of an echoed copy is
//! chosen by the child, not by this supervisor, so "a 64-hex `StartupToken` is
//! lowercase by construction" constrains only what we write, never what a
//! hostile or buggy child writes back. Measured: an UPPERCASE copy and a
//! 32-char prefix both survived `scrub` and were persisted verbatim, and
//! `tr A-F a-f` recovered the live capability. Route child-derived strings
//! through [`scrub_child_text`], which adds hex-run redaction on top.
//!
//! Behavior is pinned by `contract-fixtures/redaction-vectors.jsonl`, which
//! Python consumes too — so an intentional change must be re-approved in the
//! Rust implementation, in the Python reference semantic, and in the
//! `fixtures.sha256` pin. That is a shared-vector lock, NOT cross-language
//! parity: Python ships no production substring scrubber to compare against
//! (its `RedactionFilter` drops named structured-log fields, a different
//! mechanism for a surface Rust does not have).

/// Replace every exact occurrence of `secret` in `input` with `[REDACTED]`.
///
/// Exact match only: a partial or case-shifted near-miss is NOT redacted
/// (a 64-hex `StartupToken` is lowercase by construction, and over-eager
/// substring stripping would corrupt legitimate digests in diagnostics).
/// Callers must scrub the FULL string before any truncation so a boundary
/// cut cannot leave a partial secret behind.
pub fn scrub(input: &str, secret: &str) -> String {
    if secret.is_empty() {
        return input.to_owned();
    }
    input.replace(secret, "[REDACTED]")
}

/// Minimum run length treated as a possible secret by [`scrub_child_text`].
///
/// 32, not 64: the measured leak included a 32-char PREFIX of the token, which
/// is a full AES-128-worth of the capability and quite enough to be worth
/// hiding. `events.rs`'s own contract already says the event log carries
/// "structural fields only — never the startup capability and never any 64-hex
/// digest", so redacting long hex runs from child-derived text is that promise
/// being kept rather than a new policy.
pub const HEX_RUN_MIN: usize = 32;

/// Scrub text that a CHILD chose the contents of.
///
/// `scrub` removes the exact secret; this additionally replaces every run of
/// [`HEX_RUN_MIN`] or more hex digits, in either case. That covers the three shapes
/// #439 measured — an uppercase copy, a truncated prefix, and any other 64-hex
/// digest — none of which exact matching can reach.
///
/// Deliberately NOT folded into `scrub` itself: `scrub` is a shared primitive
/// pinned across two languages by `redaction-vectors.jsonl`, and its
/// exact-match semantics remain correct for scrubbing OUR OWN strings, where
/// over-eager stripping would corrupt legitimate digests in diagnostics. The
/// distinction is who chose the bytes.
pub fn scrub_child_text(input: &str, secret: &str) -> String {
    redact_hex_runs(&scrub(input, secret))
}

fn redact_hex_runs(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(input.len());
    let mut index = 0_usize;
    while index < bytes.len() {
        if bytes[index].is_ascii_hexdigit() {
            let start = index;
            while index < bytes.len() && bytes[index].is_ascii_hexdigit() {
                index += 1;
            }
            if index - start >= HEX_RUN_MIN {
                out.push_str("[REDACTED-HEX]");
            } else {
                out.push_str(&input[start..index]);
            }
            continue;
        }
        // Advance one whole char: a non-ASCII byte is never a hex digit, and
        // slicing mid-codepoint would panic.
        let start = index;
        index += 1;
        while index < bytes.len() && !input.is_char_boundary(index) {
            index += 1;
        }
        out.push_str(&input[start..index]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::{scrub, scrub_child_text, HEX_RUN_MIN};

    // ---- issue #439: child-chosen casing defeats exact matching ----------

    const TOKEN: &str = "13f7e5bc3420046bd0d28be56d0e24a5eae57989d91bbf6e6470bff75b08fd4d";

    #[test]
    fn scrub_child_text_catches_the_uppercase_copy() {
        // The measured leak: `tr A-F a-f` on the persisted event log
        // recovered the live capability.
        let input = format!("UPPER {}", TOKEN.to_uppercase());
        let out = scrub_child_text(&input, TOKEN);
        assert!(!out.to_lowercase().contains(TOKEN), "{out}");
        assert_eq!(out, "UPPER [REDACTED-HEX]");
    }

    #[test]
    fn scrub_child_text_catches_a_truncated_prefix() {
        let input = format!("partial {}", &TOKEN[..32]);
        let out = scrub_child_text(&input, TOKEN);
        assert_eq!(out, "partial [REDACTED-HEX]");
    }

    #[test]
    fn scrub_child_text_reproduces_the_measured_frame_prefix() {
        // Verbatim from #439's event log, which persisted the last two.
        let input = format!(
            "{{TOKEN={t}}} and again {t} and UPPER {u} and partial {p}",
            t = TOKEN,
            u = TOKEN.to_uppercase(),
            p = &TOKEN[..32],
        );
        let out = scrub_child_text(&input, TOKEN);
        assert!(
            !out.to_lowercase().contains(&TOKEN[..HEX_RUN_MIN]),
            "no recoverable fragment may survive: {out}"
        );
    }

    #[test]
    fn scrub_child_text_leaves_short_hex_alone() {
        // Ports, pids, exit codes and short ids must stay readable, or the
        // diagnostic stops being one.
        let out = scrub_child_text("port 61519 pid 4a2f code -1", TOKEN);
        assert_eq!(out, "port 61519 pid 4a2f code -1");
    }

    #[test]
    fn scrub_child_text_is_utf8_safe() {
        // Child stderr is arbitrary bytes; slicing mid-codepoint would panic.
        let input = format!("héllo 🧨 {} ünïcode", TOKEN.to_uppercase());
        let out = scrub_child_text(&input, TOKEN);
        assert_eq!(out, "héllo 🧨 [REDACTED-HEX] ünïcode");
    }

    /// The shared vector file is the lock; both languages must pass
    /// independently after any intentional `fixtures.sha256` update.
    #[test]
    fn scrub_matches_every_shared_redaction_vector() {
        let vectors = include_str!("../../../contract-fixtures/redaction-vectors.jsonl");
        let mut count = 0_usize;
        for line in vectors.lines().filter(|line| !line.is_empty()) {
            let vector: serde_json::Value =
                serde_json::from_str(line).expect("redaction vector line is JSON");
            let input = vector["input"].as_str().expect("vector input");
            let secret = vector["secret"].as_str().expect("vector secret");
            let expected = vector["expected"].as_str().expect("vector expected");
            assert_eq!(scrub(input, secret), expected, "vector: {line}");
            count += 1;
        }
        // Exact, not a floor: >= 7 against 9 shipped vectors let two be
        // deleted with neither language noticing.
        assert_eq!(count, 9, "redaction vector set changed");
    }
}

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

#[cfg(test)]
mod tests {
    use super::scrub;

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

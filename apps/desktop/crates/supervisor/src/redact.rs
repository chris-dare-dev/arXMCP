//! Active scrub-before-persist for the one secret the supervisor handles.
//!
//! The Python side's `RedactionFilter` drops named structured-log fields; the
//! supervisor never carries those fields, so its equivalent of "the same
//! standard" is this exact-match scrub applied to every persisted string
//! derived from raw child output. Behavior is pinned by the shared
//! `contract-fixtures/redaction-vectors.jsonl`, which Python consumes too —
//! two independent implementations that can drift are the failure mode.

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

    /// Parity with Python rides the shared vector file; both languages must
    /// pass independently after any intentional `fixtures.sha256` update.
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
        assert!(count >= 7, "redaction vector set shrank to {count}");
    }
}

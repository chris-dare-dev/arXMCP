use arxmcp_desktop_contract::{
    canonicalize_frame, generate_startup_token, parse_frame, ChildControlState, ContractError,
    Frame, StartupToken, FRAME_LIMIT,
};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

const POSITIVE_FIXTURES: &[&str] = &[
    "launch-v1.jsonl",
    "bound-v1.jsonl",
    "shutdown-v1.jsonl",
    "launch-v1-minor-compatible.jsonl",
];

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../contract-fixtures")
}

fn fixture(name: &str) -> Vec<u8> {
    fs::read(fixtures().join(name)).expect("read desktop contract fixture")
}

#[test]
fn positive_fixtures_round_trip_byte_for_byte() {
    for name in POSITIVE_FIXTURES {
        let original = fixture(name);
        let canonical = canonicalize_frame(&original).expect("canonical fixture");
        assert_eq!(canonical, original, "fixture drift: {name}");
    }
}

#[test]
fn compatible_minor_preserves_namespaced_additions() {
    let frame = parse_frame(&fixture("launch-v1-minor-compatible.jsonl"))
        .expect("compatible minor fixture");
    let Frame::Launch(launch) = frame else {
        panic!("expected launch fixture");
    };
    assert_eq!(launch.contract.minor, 9);
    assert!(launch.extensions.contains_key("org.arxmcp.future"));
}

#[test]
fn incompatible_major_wins_before_missing_core_fields() {
    let error = parse_frame(&fixture("incompatible-major.jsonl"))
        .expect_err("unknown major must be rejected");
    assert_eq!(error, ContractError::UnsupportedMajor(2));
}

#[test]
fn negative_fixtures_are_rejected() {
    for name in [
        "duplicate-core-field.jsonl",
        "unknown-core-field.jsonl",
        "wildcard-bound.jsonl",
        "mismatched-url-bound.jsonl",
        "oversized-frame.jsonl",
    ] {
        assert!(parse_frame(&fixture(name)).is_err(), "accepted {name}");
    }
    assert_eq!(fixture("oversized-frame.jsonl").len(), FRAME_LIMIT + 1);
}

#[test]
fn framing_rejects_crlf_missing_lf_and_floats() {
    for bytes in [
        b"{}".as_slice(),
        b"{}\r\n".as_slice(),
        b"{\"contract\":{\"major\":1,\"minor\":0.0}}\n".as_slice(),
    ] {
        assert!(parse_frame(bytes).is_err());
    }
}

#[test]
fn capability_has_full_entropy_shape_and_redacted_debug() {
    let token = generate_startup_token().expect("secure token");
    let second = generate_startup_token().expect("second secure token");
    assert_eq!(token.expose().len(), 64);
    assert_ne!(token, second);
    assert!(!format!("{token:?}").contains(token.expose()));

    let launch = parse_frame(&fixture("launch-v1.jsonl")).expect("launch");
    let fixture_token = "0".repeat(64);
    assert!(!format!("{launch:?}").contains(&fixture_token));
    assert!(StartupToken::parse("A".repeat(64)).is_err());
}

#[test]
fn child_control_state_rejects_sequence_violations() {
    let launch = parse_frame(&fixture("launch-v1.jsonl")).expect("launch");
    let bound = parse_frame(&fixture("bound-v1.jsonl")).expect("bound");
    let shutdown = parse_frame(&fixture("shutdown-v1.jsonl")).expect("shutdown");
    let mut state = ChildControlState::default();
    assert_eq!(state.accept(&bound), Err(ContractError::InvalidSequence));
    state.accept(&launch).expect("initial launch");
    assert_eq!(state.accept(&launch), Err(ContractError::InvalidSequence));
    state.accept(&shutdown).expect("running shutdown");
    assert_eq!(state.accept(&shutdown), Err(ContractError::InvalidSequence));
}

#[test]
fn fixture_set_has_pinned_aggregate_digest() {
    let mut paths: Vec<_> = fs::read_dir(fixtures())
        .expect("read fixture directory")
        .map(|entry| entry.expect("fixture entry").path())
        .filter(|path| path.extension().is_some_and(|suffix| suffix == "jsonl"))
        .collect();
    paths.sort_by_key(|path| path.file_name().map(|name| name.to_owned()));

    let mut digest = Sha256::new();
    for path in paths {
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .expect("UTF-8 fixture name");
        digest.update(name.as_bytes());
        digest.update([0]);
        digest.update(fs::read(path).expect("fixture bytes"));
    }
    let actual = format!("{:x}", digest.finalize());
    let expected = fs::read_to_string(fixtures().join("fixtures.sha256"))
        .expect("fixture digest")
        .trim()
        .to_owned();
    assert_eq!(actual, expected);
}

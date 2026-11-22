use sha2::{Digest, Sha256};
use std::{env, fs, path::Path, path::PathBuf};

const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "build.rs",
    "run_spike.py",
    "tauri.conf.json",
    "src/lib.rs",
    "src/main.rs",
    "src/bin/fixture_sidecar.rs",
];

const RGBA_ICON: &[u8] = &[
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
    0x89, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x44, 0x41, 0x54, 0x78, 0xda, 0x63, 0x64, 0xf8, 0xcf, 0xf0,
    0x1f, 0x00, 0x05, 0xfe, 0x02, 0xfe, 0x47, 0x4c, 0x2a, 0x59, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
    0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
];

fn source_digest(root: &Path) -> String {
    let mut digest = Sha256::new();
    for relative in SOURCE_FILES {
        println!("cargo:rerun-if-changed={relative}");
        digest.update(relative.as_bytes());
        digest.update([0]);
        digest.update(fs::read(root.join(relative)).expect("read tracked spike source"));
        digest.update([0]);
    }
    format!("{:x}", digest.finalize())
}

fn main() {
    let root = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("Cargo must set manifest"));
    let source_sha256 = source_digest(&root);
    println!("cargo:rustc-env=ARXMCP_SPIKE_SOURCE_SHA256={source_sha256}");
    let icon = PathBuf::from(env::var_os("OUT_DIR").expect("Cargo must set OUT_DIR"))
        .join("headless-spike-icon.png");
    fs::write(&icon, RGBA_ICON).expect("write generated Tauri icon");
    let override_json = format!(r#"{{"bundle":{{"icon":["{}"]}}}}"#, icon.display());
    env::set_var("TAURI_CONFIG", &override_json);
    println!("cargo:rustc-env=TAURI_CONFIG={override_json}");
    tauri_build::build()
}

fn main() {
    // Same relink guard as fixture-sidecar's build.rs: [env] deployment-target
    // changes are invisible to cargo's linker fingerprint on a warm cache.
    println!("cargo:rerun-if-env-changed=MACOSX_DEPLOYMENT_TARGET");
    tauri_build::build()
}

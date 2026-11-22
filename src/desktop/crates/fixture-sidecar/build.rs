// Relink when MACOSX_DEPLOYMENT_TARGET changes: cargo does not fingerprint it
// for the linker, so a warm cache
// otherwise keeps a binary declaring a stale minos (observed 11.0 vs 14.0).
fn main() {
    println!("cargo:rerun-if-env-changed=MACOSX_DEPLOYMENT_TARGET");
}

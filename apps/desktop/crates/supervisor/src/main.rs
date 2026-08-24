//! Production desktop supervisor: single-instance arbitration, one real
//! child lifecycle (launch -> bound -> ready -> MCP smoke -> window), and
//! bounded normal shutdown.
//!
//! A launch plan reaches this process by exactly one of two arms, and only
//! the first is a test seam:
//!
//! - **Environment-supplied** (`ARXMCP_DESKTOP_LAUNCH_PLAN`) — unchanged
//!   since m5. Every m5/m6/m8 gate drives this arm.
//! - **Self-authored** (m10) — taken when that variable is ABSENT, which is
//!   the shape a double-clicked application has. The supervisor derives the
//!   plan from its own on-disk layout.
//!
//! Both arms then run through the SAME `validate_plan`.
//!
//! The self-authored arm is the one place this binary comes near
//! reimplementing `ApplicationPaths`, and it deliberately ports exactly ONE
//! function: `platform_data_root` mirrors
//! `server/application_paths.py::_platform_data_root` (:81-89). The two are
//! held together by RUNNING BOTH across an env-var matrix
//! (`tests/test_desktop_self_authored_launch.py`), never by inspection —
//! a hand-copied port with no executable pin is the silent-drift hazard both
//! m10 research briefs named. The canonicalize-then-contain check on the
//! derived `child_argv[0]` mirrors `server/application_paths.py::_inside`
//! (:59-67); it is component-wise, not a string prefix test.

mod events;
mod http;
mod lifecycle;
mod process_control;
mod redact;

use events::Recorder;
use fs2::FileExt;
use serde::Deserialize;
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::Manager;

/// Test-only zero-delay launch barrier (Spike-3 technique): when set, wait
/// for the named file to appear before contending for the supervisor lock.
const BARRIER_ENV: &str = "ARXMCP_DESKTOP_LAUNCH_BARRIER";
const PLAN_ENV: &str = "ARXMCP_DESKTOP_LAUNCH_PLAN";

/// m7's PyInstaller onedir directory name AND the executable inside it —
/// both are `arxmcp_desktop.spec`'s `name="arxmcp-desktop-child"` (the `EXE`
/// at :153 and the `COLLECT` at :209 share it, which is what makes the
/// onedir layout `<root>/arxmcp-desktop-child/arxmcp-desktop-child`).
const CHILD_PAYLOAD_DIR: &str = "arxmcp-desktop-child";
/// The component name the frozen child reports as its own identity
/// (`server/desktop_child.py::COMPONENT`). A self-authored plan must name it
/// exactly, or `lifecycle`'s bound-identity comparison refuses the child.
const CHILD_COMPONENT: &str = "arxmcp-server-desktop-child";
/// Diagnostic-only argv flag: prints the Rust-derived `_platform_data_root`
/// equivalent and exits 0. It exists so the cross-language parity assertion
/// can RUN both implementations rather than eyeball them; it authors no plan,
/// spawns nothing, and touches no filesystem state.
const DATA_ROOT_PROBE_ARG: &str = "--print-data-root";
/// Diagnostic-only argv flag (m15): prints, as JSON, the values the
/// self-authoring arm derives from this binary's own on-disk location —
/// `std::env::current_exe()`, WHICH of the two layouts
/// [`child_payload_layout`] selected, the payload root it selected, and
/// either the contained `child_argv[0]` or the exact refusal reason
/// [`resolve_inside`] produced. It authors no plan, spawns nothing,
/// creates no data root and touches no filesystem state beyond the optional
/// output file below.
///
/// It exists because m15's AC4 must be MEASURED against a real assembled
/// `.app` rather than inferred from the fact that `child_payload_root`'s body
/// did not change. Without it the only way to observe the resolution is to
/// launch the whole application, which loads models; with it the assertion is
/// a subprocess that exits immediately.
const CHILD_PLAN_PROBE_ARG: &str = "--print-child-plan";
/// Where [`CHILD_PLAN_PROBE_ARG`] writes when stdout is not reachable — the
/// Gatekeeper-path-translocation measurement launches the bundle through
/// `open(1)`, which detaches stdout AND forwards no environment. So the
/// destination is taken from `argv[2]` first and only then from this
/// variable; `open -a App --args --print-child-plan /path/out.json` is the
/// one shape that reaches a translocated launch at all. Deliberately NOT
/// `ARXMCP_`-prefixed: the server FATALs on unknown `ARXMCP_*` vars in an
/// operator shell (`DESKTOP_SUPERVISOR_BIN` precedent).
const CHILD_PLAN_PROBE_OUT_ENV: &str = "DESKTOP_CHILD_PLAN_OUT";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    /// Child argv; element 0 is the program. Never carries the capability.
    pub child_argv: Vec<String>,
    pub component: String,
    /// Wire-style absolute path (POSIX `/...`), already resolved by the
    /// plan author (Python `ApplicationPaths` is the sole layout owner).
    pub data_root: String,
    /// File whose SHA-256 is the expected child executable identity.
    pub identity_file: String,
    /// true: exit 0 after one full launch->ready->smoke->shutdown cycle.
    pub smoke: bool,
    pub version: String,
    /// Test-only (m6 fault matrix): shrinks the supervisor's local bound-frame
    /// wait. Never forwarded to the child.
    #[serde(default)]
    pub test_bound_timeout_ms: Option<u64>,
    /// Test-only: fault name inserted under the `org.arxmcp.test-fault`
    /// extension key. Read ONLY by the fixture sidecar; the production child
    /// never inspects extensions, so a production launch is unaffected.
    #[serde(default)]
    pub test_fault: Option<String>,
    /// Test-only: build the main window ordered-out (`.visible(false)`), the
    /// measured negative control for issue #423. The ONLY committed way to
    /// reach the post-navigate visibility gate's failing arm.
    #[serde(default)]
    pub test_hide_window: Option<bool>,
    /// Test-only: shrinks the supervisor's LOCAL grace/force budgets so the
    /// escalation ladder runs at test speed. The wire frame keeps the
    /// contract-mandated MIN_GRACE_MS floor — these never change what the
    /// child is promised, only how long this process waits.
    #[serde(default)]
    pub test_shutdown_force_after_ms: Option<u64>,
    #[serde(default)]
    pub test_shutdown_grace_ms: Option<u64>,
}

/// #465: put a PRE-WINDOW refusal on screen.
///
/// Every refusal in the self-authoring arm — missing payload, symlinked
/// payload root, escaping child executable, uncreatable or unresolvable data
/// root, no HOME — reaches `fail()`, which was `eprintln!` plus exit. On a
/// LaunchServices-started bundle stderr goes nowhere a person will look and
/// `tauri.conf.json` declares `app.windows: []`, so all of it presented as
/// "the icon bounced and nothing happened". These strings are carefully
/// worded and named by cause; none of them reached anyone.
///
/// `fail()` runs BEFORE the Tauri app exists, so there is no window to render
/// into — #425's failure page is unreachable this early. A native alert is
/// the only surface available at that point.
///
/// Release builds only, for the same reason as #427 and #436: the gates drive
/// the debug binary through these refusal paths deliberately, and a dialog
/// per refusal would be noise at best. Spawned and NEVER waited on —
/// `display alert` blocks until dismissed, and `fail()` must still exit
/// promptly; osascript outlives this process, so the alert stays up after the
/// supervisor is gone. `giving up after` keeps a stray one from lingering.
#[cfg(all(target_os = "macos", not(debug_assertions)))]
fn show_native_alert(reason: &str) {
    // AppleScript string literals escape exactly backslash and double quote.
    let escaped = reason.replace('\\', "\\\\").replace('"', "\\\"");
    let script = format!(
        "display alert \"arXMCP could not start\" message \"{escaped}\" \
         as critical giving up after 120"
    );
    let _ = std::process::Command::new("/usr/bin/osascript")
        .arg("-e")
        .arg(script)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
}

#[cfg(not(all(target_os = "macos", not(debug_assertions))))]
fn show_native_alert(_reason: &str) {}

fn fail(reason: &str) -> ! {
    eprintln!("supervisor: {reason}");
    show_native_alert(reason);
    std::process::exit(2);
}

/// The environment launch-plan arm, present ONLY in a debug build (#427).
///
/// It is a TEST SEAM. `test_desktop_child.py`'s fault matrix points
/// `child_argv` at the fixture sidecar, which lives in `target/debug/` and
/// therefore OUTSIDE the payload root on purpose — so the arm cannot apply
/// `resolve_inside`, and it never did. What it also cannot do is exist in a
/// shipped binary, which is what #427 measured: one environment variable made
/// the signed `.app` deserialize an attacker-chosen plan and exec whatever
/// `child_argv[0]` named, proven with `/usr/bin/touch`.
///
/// Applying containment here instead was considered and rejected: it would
/// break every fault-matrix arm, and it would still leave a
/// deserialize-and-exec path compiled into the artifact for someone to find a
/// way around. Removing the arm from the shipped binary is the smaller and
/// more complete change.
#[cfg(debug_assertions)]
fn env_plan_path() -> Option<std::ffi::OsString> {
    std::env::var_os(PLAN_ENV)
}

/// Release builds have NO environment arm. Not a runtime check that could be
/// bypassed — the deserialize-and-exec path is not compiled in at all.
#[cfg(not(debug_assertions))]
fn env_plan_path() -> Option<std::ffi::OsString> {
    None
}

#[cfg(debug_assertions)]
fn env_plan_was_ignored() -> bool {
    false
}

/// True when a release build saw the variable set and disregarded it. Ignoring
/// rather than refusing is deliberate: a stray exported variable must not stop
/// an operator's application from starting, and the event log records that it
/// happened either way.
#[cfg(not(debug_assertions))]
fn env_plan_was_ignored() -> bool {
    std::env::var_os(PLAN_ENV).is_some()
}

/// Returns the plan and the name of the arm that produced it. The arm name is
/// recorded on `supervisor-started` so a triage session can tell a bug in the
/// new self-authoring arm from a bug in the environment path — brief-2 risk 5:
/// both arms terminate at the SAME `fail()` sites downstream.
fn load_plan() -> (Plan, &'static str) {
    let Some(path) = env_plan_path() else {
        // m10: absent variable is the PRODUCTION shape, not an error. Before
        // this arm existed the next line was
        // `fail("ARXMCP_DESKTOP_LAUNCH_PLAN is required")` -> exit(2), which
        // is the RED state `test_red_state_*` in
        // tests/test_desktop_self_authored_launch.py discriminates against.
        let exe = std::env::current_exe()
            .unwrap_or_else(|_| fail("self-authored plan: supervisor path unavailable"));
        let plan = self_authored_plan(&exe, |key| std::env::var(key).ok())
            .unwrap_or_else(|reason| fail(reason));
        // Both arms run this validator. That is where the parity between them
        // ENDS, and #427 is the correction to a comment here that used to
        // claim otherwise. `validate_plan` checks argv is non-empty and the
        // smoke-knob rule; the containment story documented in
        // apps/desktop/README.md — `child_payload_root`, `resolve_inside`, the
        // symlink refusal and the identity digest — is reachable ONLY from
        // `self_authored_plan` above. So the environment arm was trusted MORE
        // than this one, not less, for as long as it existed in a release
        // build. It no longer does.
        if let Err(reason) = validate_plan(&plan) {
            fail(reason);
        }
        return (
            plan,
            if env_plan_was_ignored() {
                "self-authored (env plan ignored: release build)"
            } else {
                "self-authored"
            },
        );
    };
    let bytes = fs::read(PathBuf::from(path)).unwrap_or_else(|_| fail("launch plan unreadable"));
    // #462: serde already knows the field name, the line, the column and the
    // expected type. Collapsing all of that into one static string made a
    // typo'd field, a schema mismatch and a zero-byte file indistinguishable
    // to whoever has to repair the plan. `fail` takes &str, so the message is
    // built here and borrowed.
    let plan: Plan = match serde_json::from_slice(&bytes) {
        Ok(plan) => plan,
        Err(err) => {
            let detail = format!("launch plan malformed: {err}");
            fail(&detail);
        }
    };
    if let Err(reason) = validate_plan(&plan) {
        fail(reason);
    }
    (plan, "environment")
}

/// Collapse a path string the way `pathlib.PurePath` parsing does, because
/// the Python side of the parity pair stores every env value through
/// `Path(...)` and compares the RESULT.
///
/// `PurePosixPath` drops empty and `.` components at construction and keeps
/// `..` unresolved; POSIX's "exactly two leading slashes are
/// implementation-defined" rule means `//a` survives as `//a` while `///a`
/// collapses to `/a`. Rust's `PathBuf` preserves the raw text instead, so
/// without this `HOME=/a//b` derives `/a//b/Library/...` against Python's
/// `/a/b/Library/...` — a silent bifurcation of the operator's data root,
/// not a cosmetic difference (m10 critique M1, measured live).
fn pathlib_normalize(raw: &str) -> PathBuf {
    let leading = raw.len() - raw.trim_start_matches('/').len();
    let prefix = match leading {
        0 => "",
        2 => "//",
        _ => "/",
    };
    let mut out = String::from(prefix);
    let mut first = true;
    for part in raw.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if !first {
            out.push('/');
        }
        out.push_str(part);
        first = false;
    }
    // An all-separator or empty input degrades to what pathlib returns: the
    // root itself when absolute, `.` when not.
    if first && prefix.is_empty() {
        return PathBuf::from(".");
    }
    PathBuf::from(out)
}

/// Rust port of `server/application_paths.py::_platform_data_root` (:81-89).
///
/// ONE deliberate divergence, asserted rather than hidden: Python falls back
/// to `Path.home()` (a passwd-database read) when the platform branch needs a
/// home directory and neither `USERPROFILE` nor `HOME` is set; this refuses
/// instead. Guessing a home directory for a process that is about to create a
/// data root is the worse failure, and the parity matrix pins this exact row.
///
/// The home lookup is LAZY for the same reason Python's is: with
/// `XDG_DATA_HOME` set on Linux, or `LOCALAPPDATA` set on Windows, the base
/// never consults `home`, so refusing early would have been a SECOND
/// divergence — reachable on Linux, which the matrix does run (critique M7).
fn platform_data_root(lookup: impl Fn(&str) -> Option<String>) -> Result<PathBuf, &'static str> {
    // Python's `env.get(...) or ...` treats "" as absent; match that.
    let value = |key: &str| lookup(key).filter(|raw| !raw.is_empty());
    let home = || {
        value("USERPROFILE")
            .or_else(|| value("HOME"))
            .map(|raw| pathlib_normalize(&raw))
            .ok_or("self-authored plan: no HOME or USERPROFILE in environment")
    };
    let base = if cfg!(target_os = "windows") {
        match value("LOCALAPPDATA") {
            Some(raw) => pathlib_normalize(&raw),
            None => home()?.join("AppData").join("Local"),
        }
    } else if cfg!(target_os = "macos") {
        home()?.join("Library").join("Application Support")
    } else {
        match value("XDG_DATA_HOME") {
            Some(raw) => pathlib_normalize(&raw),
            None => home()?.join(".local").join("share"),
        }
    };
    Ok(base.join("arXMCP"))
}

/// `Plan.data_root` and `child_argv` are wire-style POSIX strings (the
/// contract's `validate_paths`), so a Windows backslash path is normalized
/// the same way the Python plan authors do it.
fn wire_path(path: &Path) -> String {
    let text = path.to_string_lossy().into_owned();
    if cfg!(target_os = "windows") {
        text.replace('\\', "/")
    } else {
        text
    }
}

/// Canonicalize BOTH sides, then require component-wise containment —
/// mirroring `server/application_paths.py::_inside` (:59-67) rather than a
/// string-prefix test, so a `payload-root-evil` sibling cannot pass and a
/// symlink out of the payload root cannot either.
///
/// RESIDUAL RISK, recorded not closed, WORST FIRST:
///
/// 1. Write access to the payload directory is equivalent to arbitrary code
///    execution as the operator — whichever of [`child_payload_candidates`]'
///    two layouts is in force (the onedir sibling, or the assembled bundle's
///    `Contents/Resources/`). This needs no trick and is the class that an
///    unpacked-in-Downloads copy or a group-writable install directory makes
///    real. The defenses are install-location permissions and, later, e4
///    code signing — not this function. Stated for operators in
///    `apps/desktop/README.md`.
/// 2. The root descends from `std::env::current_exe()`, which the Rust
///    stdlib documents as **not a security primitive** — it names PATH-search
///    and Linux-hardlink classes that can make it return an attacker-chosen
///    path. These carry NO privilege gradient here (the supervisor is not
///    setuid/setgid, so anyone who can steer them already executes as the
///    invoking user), which is why they rank below (1) rather than above it.
///
/// What this function DOES close: a `payload-root-evil` sibling cannot pass,
/// a symlinked CHILD cannot escape, and — since the m10 critique — a
/// symlinked payload ROOT cannot silently relocate the whole payload.
fn resolve_inside(root: &Path, candidate: &Path) -> Result<PathBuf, &'static str> {
    // Refuse a symlinked root BEFORE canonicalizing it. Without this, a root
    // entry pointing at /tmp/evil canonicalizes to /tmp/evil, the candidate
    // resolves inside it, containment holds, and an arbitrary binary runs —
    // the doc comment's "cannot escape" claim was false for exactly this
    // shape (critique M13). `symlink_metadata` does not follow the link.
    match fs::symlink_metadata(root) {
        Ok(meta) if meta.file_type().is_symlink() => {
            return Err("self-authored plan: child payload root is a symlink");
        }
        Ok(_) => {}
        Err(_) => return Err("self-authored plan: child payload root missing"),
    }
    let canonical_root = fs::canonicalize(root).map_err(canonicalize_reason)?;
    // #460: the SAME error for every canonicalize failure told an operator
    // whose install directory is mode 000 to go looking for a missing file.
    // EACCES, ELOOP, ENAMETOOLONG and ENOENT are four different repairs.
    let resolved = fs::canonicalize(candidate).map_err(canonicalize_reason)?;
    if !resolved.starts_with(&canonical_root) {
        return Err("self-authored plan: child executable escapes the payload root");
    }
    check_child_file(&resolved)?;
    Ok(resolved)
}

/// #484: the v1 launch frame declares FIXED probe paths, so
/// `arxmcp-desktop-probe` is a dependency of the plan — but nothing checked it
/// existed before the frame was authored. Deleting it changed no supervisor
/// behaviour at plan time; the failure surfaced later, somewhere else.
///
/// Checked at plan authoring, where the answer is cheap and the message can
/// name the missing file. Strictly weaker than the write-access-equals-code-
/// execution risk the README already concedes — this catches an INCOMPLETE
/// payload, not a hostile one, which is the ditto/unzip/partial-copy case.
/// #485: is this derivation usable as a data root?
///
/// `--print-data-root` emitted a path for a `$HOME` that is a regular FILE and
/// for a RELATIVE `$HOME`, so the probe's own output was not by itself a
/// usable data root — and `main()` catches the relative case only later, while
/// the probe never did. A diagnostic that reports something the program would
/// refuse is worse than one that reports nothing.
fn check_data_root_shape(root: &Path, home: &Path) -> Result<(), &'static str> {
    if !home.is_absolute() {
        return Err("data root: HOME is not an absolute path");
    }
    if home.exists() && !home.is_dir() {
        return Err("data root: HOME is not a directory");
    }
    if !root.is_absolute() {
        return Err("data root: derived path is not absolute");
    }
    Ok(())
}

/// Plan-time shape check for the payload (issue #484).
///
/// **Scope, stated because the first cut of this overclaimed it.** #484 named
/// three deletions — the probe, an `_internal` Mach-O, and `_CodeSignature` —
/// and this function checked only the first, then the issue was closed. It is
/// a cheap NAME check that produces a precise message before anything is
/// spawned; it is not, and cannot be, the integrity check. No manifest of
/// expected names detects a MODIFIED file or an ADDED one.
///
/// The integrity check is [`lifecycle::verify_bundle_seal`], which consults
/// the outer bundle's sealed-resource manifest and therefore covers files
/// this function never enumerates. The two are ordered deliberately: name
/// checks first (fast, specific errors), seal second (~0.3 s, total).
fn check_payload_completeness(root: &Path) -> Result<(), &'static str> {
    let probe = root.join(PROBE_EXECUTABLE_NAME);
    if !probe.is_file() {
        return Err("self-authored plan: payload is incomplete (probe missing)");
    }
    // The PyInstaller onedir runtime. The executable beside it is a launcher
    // and cannot start without this directory, so its absence is a payload
    // problem worth naming rather than a Python-level crash to decode later.
    if !root.join(PAYLOAD_RUNTIME_DIR).is_dir() {
        return Err("self-authored plan: payload is incomplete (_internal missing)");
    }
    Ok(())
}

/// #460: name the ACTUAL filesystem failure.
///
/// `resolve_inside` mapped every `canonicalize` error to "missing", so a
/// permissions problem, a symlink loop, an over-long path and a genuinely
/// absent file were indistinguishable — and each wants a different fix.
fn canonicalize_reason(err: std::io::Error) -> &'static str {
    use std::io::ErrorKind;
    match err.kind() {
        ErrorKind::NotFound => "self-authored plan: child payload path missing",
        ErrorKind::PermissionDenied => {
            "self-authored plan: child payload path unreadable (permissions)"
        }
        _ => "self-authored plan: child payload path unresolvable",
    }
}

/// Checks that containment alone does not make (issues #459, #461).
#[cfg(unix)]
fn check_child_file(path: &Path) -> Result<(), &'static str> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let meta = fs::metadata(path).map_err(canonicalize_reason)?;

    // #461: containment proved the file is INSIDE the root and never that it
    // can run. A ditto/zip round trip or a restrictive umask is enough to
    // strip the exec bit, and `--print-child-plan` — the probe m15's AC4 uses
    // to attest the artifact — then reported a payload it cannot execute as
    // healthy. The real failure surfaced ~2s later as an unqualified "child
    // spawn failed" with no errno.
    if meta.permissions().mode() & 0o111 == 0 {
        return Err("self-authored plan: child executable is not executable");
    }

    // #459: `canonicalize` resolves SYMLINKS. A hardlink has no link to
    // resolve, so content from outside the payload root passes containment
    // while presenting an in-root path — measured reproducible on APFS, not
    // the Linux-specific class the residual-risk note describes.
    //
    // A payload file placed by the assembler has exactly one link. More than
    // one means the same inode is reachable by another name, which is the
    // property containment is trying to deny. Refusing is conservative: a
    // deliberately hardlinked payload is not a shape this project produces.
    if meta.nlink() > 1 {
        return Err("self-authored plan: child executable is hardlinked");
    }
    Ok(())
}

#[cfg(not(unix))]
fn check_child_file(_path: &Path) -> Result<(), &'static str> {
    Ok(())
}

/// The single composer for a self-authored `Plan`. Tests call it directly to
/// reach `validate_plan`'s OTHER branch (`child_argv.is_empty()`) on a plan
/// this code actually authored — without it, AC2 is vacuous, because a
/// self-authored plan is never `smoke: true` and the five `!smoke`-gated
/// knobs are refused for free.
fn compose_self_authored_plan(
    child_argv: Vec<String>,
    identity_file: String,
    data_root: String,
) -> Plan {
    Plan {
        child_argv,
        component: CHILD_COMPONENT.to_owned(),
        data_root,
        identity_file,
        // A double-clicked application must NOT exit after one cycle.
        smoke: false,
        // This is the CHILD's expected executable-identity version, not the
        // supervisor's own: `lifecycle.rs` sends it as `ExecutableIdentity`
        // and `server/desktop_child.py:182` refuses the launch on mismatch,
        // where the child reports `importlib.metadata.version("arxmcp")`.
        // Using the Rust crate version is only correct while the two version
        // lines are held equal, which was true by accident until the m10
        // critique (H1/H3) and is now ASSERTED on every `make test` by
        // `tests/test_desktop_self_authored_launch.py::
        // test_supervisor_crate_version_matches_the_python_package_version`.
        // Whoever bumps one and not the other gets a red suite, not a
        // double-click that dies at bound-identity.
        version: env!("CARGO_PKG_VERSION").to_owned(),
        test_bound_timeout_ms: None,
        test_fault: None,
        test_hide_window: None,
        test_shutdown_force_after_ms: None,
        test_shutdown_grace_ms: None,
    }
}

/// Layout labels for the payload root that was selected. Reported by
/// [`CHILD_PLAN_PROBE_ARG`] so the chosen arm is OBSERVABLE against a real
/// artifact instead of being inferred from the resolved path string.
const LAYOUT_BUNDLE_RESOURCES: &str = "bundle-resources";
const LAYOUT_SUPERVISOR_SIBLING: &str = "supervisor-sibling";

/// The payload layouts, in resolution order, for a given supervisor path.
///
/// m7's onedir stages the payload as a SIBLING of the supervisor executable.
/// m15's bundle-assembly ADR (`.claude/docs/adr-desktop-bundle-assembly.md`)
/// **Decision 2a, Accepted 2026-08-12** — which SUPERSEDED Decision 2 after
/// the assembled artifact proved `codesign` cannot seal a bundle whose
/// `Contents/MacOS` holds non-Mach-O files — places the bundled payload under
/// `Contents/Resources/` instead. It is a property of the LOCATION, shown by
/// an A/B control on a six-byte data file, not of this payload.
///
/// So the payload is no longer a sibling inside a bundle, and TWO layouts
/// must coexist — the onedir shape every m10 gate and developer run uses, and
/// the bundle shape that ships:
///
/// | context | supervisor at | payload at |
/// |---|---|---|
/// | dev / m7 onedir | `<dir>/supervisor` | `<dir>/arxmcp-desktop-child/` |
/// | assembled `.app` | `Contents/MacOS/supervisor` | `Contents/Resources/arxmcp-desktop-child/` |
///
/// The bundle candidate is offered **only when the supervisor actually sits
/// in `…/Contents/MacOS`**, which is what makes this an explicit disjunction
/// rather than a speculative `../Resources` probe from every directory:
/// outside a bundle there is exactly one candidate, so there is nothing to
/// fall through to and no second root that a planted directory could steer a
/// launch onto.
fn child_payload_candidates(
    supervisor_exe: &Path,
) -> Result<Vec<(&'static str, PathBuf)>, &'static str> {
    let dir = supervisor_exe
        .parent()
        .ok_or("self-authored plan: supervisor has no parent directory")?;
    let mut candidates: Vec<(&'static str, PathBuf)> = Vec::with_capacity(2);
    let contents = dir.parent();
    let in_bundle_macos = dir.file_name().is_some_and(|name| name == "MacOS")
        && contents
            .and_then(Path::file_name)
            .is_some_and(|name| name == "Contents");
    if in_bundle_macos {
        if let Some(contents) = contents {
            candidates.push((
                LAYOUT_BUNDLE_RESOURCES,
                contents.join("Resources").join(CHILD_PAYLOAD_DIR),
            ));
        }
    }
    candidates.push((LAYOUT_SUPERVISOR_SIBLING, dir.join(CHILD_PAYLOAD_DIR)));
    Ok(candidates)
}

/// Select the payload root: the first PRESENT candidate wins, and refuse when
/// neither is present.
///
/// "Present" is `symlink_metadata`, deliberately: a SYMLINKED root counts as
/// present, so it is selected and then REFUSED by [`resolve_inside`] (m10's
/// M13 fix) rather than skipped in favour of the next candidate. Skipping it
/// would let a planted symlink decide WHICH root a launch runs from, so the
/// m10 hardening is preserved here by construction — pinned by
/// `symlinked_bundle_payload_root_does_not_fall_through`.
///
/// Validity beyond presence stays [`resolve_inside`]'s job, unchanged: it is
/// still the containment gate for whichever root this returns, and its
/// refusal strings are still the ones callers see.
fn child_payload_root(supervisor_exe: &Path) -> Result<PathBuf, &'static str> {
    Ok(child_payload_layout(supervisor_exe)?.1)
}

/// [`child_payload_root`] with the selected arm's label attached, for the
/// probe. Split out so the probe can report WHICH layout resolved without
/// Sibling of [`child_executable_name`]; declared by the v1 launch frame's
/// fixed probe paths and therefore part of a complete payload (#484).
const PROBE_EXECUTABLE_NAME: &str = "arxmcp-desktop-probe";

/// PyInstaller's onedir runtime directory, beside the child executable.
///
/// Named here because the executable is a LAUNCHER: `libpython3.12.dylib` and
/// every extension module live in this directory, which is the part #436's
/// executable-only signature check verifies nothing about.
const PAYLOAD_RUNTIME_DIR: &str = "_internal";

/// the caller re-deriving it from the path.
fn child_payload_layout(supervisor_exe: &Path) -> Result<(&'static str, PathBuf), &'static str> {
    for (layout, root) in child_payload_candidates(supervisor_exe)? {
        if fs::symlink_metadata(&root).is_ok() {
            return Ok((layout, root));
        }
    }
    // Deliberately a SUPERSET of `resolve_inside`'s own "child payload root
    // missing" wording: the two refusals are the same fact reached at
    // different depths (selection found no candidate; containment found the
    // selected one gone), and m10's runtime RED-state gate matches on that
    // substring.
    Err("self-authored plan: child payload root missing (checked the bundle Resources and supervisor-sibling layouts)")
}

fn child_executable_name() -> String {
    if cfg!(target_os = "windows") {
        format!("{CHILD_PAYLOAD_DIR}.exe")
    } else {
        CHILD_PAYLOAD_DIR.to_owned()
    }
}

/// Build [`CHILD_PLAN_PROBE_ARG`]'s report. Split from the emitter so the
/// unit tests can drive it against fabricated layouts without a subprocess.
///
/// `payload_root_is_symlink` is reported SEPARATELY from `error` even though
/// [`resolve_inside`] already refuses a symlinked root, because m15's ADR
/// requires the assembled artifact to be checked for a symlink introduced by
/// the copy or the re-seal. Reading the refusal string would conflate "the
/// assembler created a symlink" with "the payload is missing".
fn child_plan_probe(supervisor_exe: &Path) -> serde_json::Value {
    let (layout, root) = match child_payload_layout(supervisor_exe) {
        Ok(selected) => selected,
        Err(reason) => {
            return serde_json::json!({
                "supervisor_exe": wire_path(supervisor_exe),
                "layout": serde_json::Value::Null,
                "payload_root": serde_json::Value::Null,
                "payload_root_is_symlink": serde_json::Value::Null,
                "child_argv0": serde_json::Value::Null,
                "error": reason,
            });
        }
    };
    let is_symlink = fs::symlink_metadata(&root)
        .map(|meta| meta.file_type().is_symlink())
        .ok();
    let (child, error) = match resolve_inside(&root, &root.join(child_executable_name())) {
        Ok(path) => (
            serde_json::Value::String(wire_path(&path)),
            serde_json::Value::Null,
        ),
        Err(reason) => (
            serde_json::Value::Null,
            serde_json::Value::String(reason.to_owned()),
        ),
    };
    serde_json::json!({
        "supervisor_exe": wire_path(supervisor_exe),
        "layout": layout,
        "payload_root": wire_path(&root),
        "payload_root_is_symlink": is_symlink,
        "child_argv0": child,
        "error": error,
    })
}

/// Write the probe report to `DESKTOP_CHILD_PLAN_OUT` when set, else stdout.
///
/// A `current_exe()` failure is reported as a report rather than as a
/// `fail()`: under path translocation the interesting outcome is exactly what
/// this call returns, so swallowing it into exit code 2 would discard the
/// measurement this probe exists to make.
fn emit_child_plan_probe() {
    let report = match std::env::current_exe() {
        Ok(exe) => child_plan_probe(&exe),
        Err(err) => serde_json::json!({
            "supervisor_exe": serde_json::Value::Null,
            "layout": serde_json::Value::Null,
            "payload_root": serde_json::Value::Null,
            "payload_root_is_symlink": serde_json::Value::Null,
            "child_argv0": serde_json::Value::Null,
            "error": format!("current_exe unavailable: {err}"),
        }),
    };
    let text = report.to_string();
    let destination = std::env::args_os()
        .nth(2)
        .or_else(|| std::env::var_os(CHILD_PLAN_PROBE_OUT_ENV));
    match destination {
        Some(path) => {
            // #466: create-new, never truncate. This diagnostic ships enabled
            // in the signed bundle and took its destination from argv with no
            // constraint, so "ask the trusted app to overwrite a file for me"
            // was a real primitive — and becomes a privilege step under e4,
            // when this binary carries a Developer ID and TCC grants.
            //
            // create_new rather than a path constraint because the m15 AC4
            // gate legitimately probes into a pytest tmp_path OUTSIDE any data
            // root; constraining the directory would break the attestation
            // this probe exists for. Residual: a new file can still be created
            // somewhere writable. That is a far smaller step than clobbering
            // an existing one, and it is the part a path rule would have to
            // solve without breaking the gate.
            let _ = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(PathBuf::from(path))
                .and_then(|mut file| std::io::Write::write_all(&mut file, text.as_bytes()));
        }
        None => println!("{text}"),
    }
}

/// Derive the whole plan from layout + environment.
///
/// `identity_file == child_argv[0]` here, which is NOT the shape any existing
/// test fixture has: in a source checkout the child's identity is
/// `server/desktop_child.py` while argv runs `python -m server.desktop_child`.
/// Frozen, `identity_source_path()` returns `Path(sys.executable)`, so the two
/// converge — copying the source-checkout shape would author a plan whose
/// digest can never match the child's own report.
fn self_authored_plan(
    supervisor_exe: &Path,
    lookup: impl Fn(&str) -> Option<String>,
) -> Result<Plan, &'static str> {
    let payload_root = child_payload_root(supervisor_exe)?;
    let child_exe = resolve_inside(&payload_root, &payload_root.join(child_executable_name()))?;
    check_payload_completeness(&payload_root)?;
    let data_root = platform_data_root(lookup)?;
    // The fixture and the Python child both require an ALREADY-canonical
    // data_root on the wire, and canonicalize() needs the path to exist.
    fs::create_dir_all(&data_root)
        .map_err(|_| "self-authored plan: data root could not be created")?;
    let data_root =
        fs::canonicalize(&data_root).map_err(|_| "self-authored plan: data root unresolvable")?;
    let child = wire_path(&child_exe);
    Ok(compose_self_authored_plan(
        vec![child.clone()],
        child,
        wire_path(&data_root),
    ))
}

/// Split from `load_plan` so the rules are unit-testable — `fail()` exits.
fn validate_plan(plan: &Plan) -> Result<(), &'static str> {
    if plan.child_argv.is_empty() {
        return Err("launch plan child_argv is empty");
    }
    // The knobs are honored unconditionally downstream, and the grace knob
    // shrinks only the supervisor's LOCAL wait while the wire frame still
    // promises MIN_GRACE_MS — so a non-smoke plan carrying one would
    // force-kill a real server that believes it has 35s to close its LanceDB
    // and Kuzu handles. Refuse rather than break that promise. `test_hide_window`
    // is here for the same reason from the other direction: outside smoke mode
    // it would ship an operator a permanently invisible application.
    if !plan.smoke
        && (plan.test_bound_timeout_ms.is_some()
            || plan.test_fault.is_some()
            || plan.test_hide_window.is_some()
            || plan.test_shutdown_force_after_ms.is_some()
            || plan.test_shutdown_grace_ms.is_some())
    {
        return Err("launch plan carries test-only knobs outside smoke mode");
    }
    Ok(())
}

/// Barrier path must live under the data root so a test cannot point the
/// supervisor at an arbitrary filesystem location.
fn await_launch_barrier(root: &Path) -> Result<(), &'static str> {
    let Some(value) = std::env::var_os(BARRIER_ENV) else {
        return Ok(());
    };
    let barrier = PathBuf::from(value);
    if barrier.parent() != Some(root) {
        return Err("launch barrier escaped data root");
    }
    let deadline = Instant::now() + Duration::from_secs(10);
    while !barrier.is_file() {
        if Instant::now() >= deadline {
            return Err("launch barrier timeout");
        }
        std::thread::sleep(Duration::from_millis(2));
    }
    Ok(())
}

/// fs2 advisory lock is the PRIMARY single-instance defense (Spike-3: the
/// single-instance plugin alone does not close a zero-delay race). Checked
/// before any Tauri machinery; the loser never spawns a child.
fn acquire_supervisor_lock(root: &Path) -> Result<Option<fs::File>, &'static str> {
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join("supervisor.lock"))
        .map_err(|_| "supervisor lock open failed")?;
    match lock.try_lock_exclusive() {
        Ok(()) => Ok(Some(lock)),
        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => Ok(None),
        Err(_) => Err("supervisor lock failed"),
    }
}

/// Socket path `tauri-plugin-single-instance` 2.4.3 derives on macOS from the
/// `tauri.conf.json` identifier (`.` and `-` become `_`). Mirrored, not
/// called: the plugin exposes no client helper. A unit test pins it against
/// the identifier so a rename cannot silently orphan activation.
#[cfg(target_os = "macos")]
const SINGLE_INSTANCE_SOCKET: &str = "/tmp/com_arxmcp_desktop_si.sock";

/// Client half of tauri-plugin-single-instance's macOS protocol
/// (`cwd \0\0 argv.join(\0)`). Drift only degrades activation, never
/// correctness — a failed connect still means "exit without spawning".
/// `/tmp` is world-writable, so a socket this uid does not own is refused
/// rather than handed the cwd and argv (the check races a swap, but a squatter
/// must then also win that race against an owner-created socket).
#[cfg(target_os = "macos")]
fn notify_running_instance() -> std::io::Result<()> {
    use std::io::{Error, ErrorKind, Write};
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::net::UnixStream;
    // SAFETY: getuid() is always successful and takes no arguments.
    if fs::metadata(SINGLE_INSTANCE_SOCKET)?.uid() != unsafe { libc::getuid() } {
        return Err(Error::new(
            ErrorKind::PermissionDenied,
            "single-instance socket is not owned by this user",
        ));
    }
    let mut stream = UnixStream::connect(SINGLE_INSTANCE_SOCKET)?;
    let cwd = std::env::current_dir().unwrap_or_default();
    stream.write_all(cwd.to_string_lossy().as_bytes())?;
    stream.write_all(b"\0\0")?;
    let args = std::env::args().collect::<Vec<_>>().join("\0");
    stream.write_all(args.as_bytes())?;
    stream.flush()
}

/// Off macOS the plugin's activation transport is DBus (Linux `zbus`, on
/// `<identifier>.SingleInstance`) or a window message, never a Unix socket, so
/// there is no client half to speak yet. The loser still exits without
/// spawning; only the focus hand-off to the winner is absent.
#[cfg(not(target_os = "macos"))]
fn notify_running_instance() -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "activation client half is macOS-only",
    ))
}

/// Why the single-instance plugin was or was not registered (#437 / #441).
#[derive(Debug, PartialEq, Eq)]
pub enum SingleInstance {
    /// Register it: this is the shipped shape and the socket is ours.
    Register,
    /// Skip it, for the named reason. Activation is degraded; nothing else is.
    Skip(&'static str),
}

/// Decide whether to register `tauri-plugin-single-instance`.
///
/// The plugin's macOS socket is MACHINE-GLOBAL, keyed on the bundle
/// identifier and living in world-writable `/tmp`. The fs2 lock on
/// `<data_root>/supervisor.lock` is already the primary single-instance
/// defense and is correctly per-data-root, so the plugin adds only activation
/// — and adds two failure modes with it:
///
/// * **#441** — a supervisor on a DIFFERENT data root wins its own lock,
///   records `owns_lock: true`, then registers the plugin, whose socket is
///   already held by an unrelated instance. The plugin exits this process,
///   0, with no event and no stderr. A developer's debug run could kill the
///   operator's shipped application, and vice versa.
/// * **#437** — `/tmp` is world-writable, so anything can pre-create that
///   path and make every launch of the shipped app exit at startup.
///
/// So: register only when this IS the default data root (the shipped shape,
/// where activation is meaningful and two instances genuinely collide), and
/// only when nothing else already owns the socket path. Skipping degrades
/// re-activation focus and nothing else — strictly better than exiting.
pub fn single_instance_decision(
    data_root: &Path,
    default_root: Option<&Path>,
    socket_owner_uid: Option<u32>,
    our_uid: u32,
) -> SingleInstance {
    match default_root {
        Some(default) if default == data_root => {}
        Some(_) => return SingleInstance::Skip("data root is not the platform default"),
        // The default is underivable (no HOME); nothing to compare against,
        // so do not claim this is the shipped shape.
        None => return SingleInstance::Skip("platform data root underivable"),
    }
    match socket_owner_uid {
        None => SingleInstance::Register,
        Some(uid) if uid == our_uid => SingleInstance::Register,
        Some(_) => SingleInstance::Skip("single-instance socket is not owned by this user"),
    }
}

/// uid owning the plugin's socket path, or `None` when it does not exist.
#[cfg(target_os = "macos")]
fn single_instance_socket_owner() -> Option<u32> {
    use std::os::unix::fs::MetadataExt;
    fs::metadata(SINGLE_INSTANCE_SOCKET)
        .ok()
        .map(|meta| meta.uid())
}

#[cfg(not(target_os = "macos"))]
fn single_instance_socket_owner() -> Option<u32> {
    None
}

#[cfg(unix)]
fn current_uid() -> u32 {
    // SAFETY: getuid() is always successful and takes no arguments.
    unsafe { libc::getuid() }
}

#[cfg(not(unix))]
fn current_uid() -> u32 {
    0
}

/// #445: run the bounded shutdown when the OS asks us to stop.
///
/// The whole documented grace/force/reap contract — the README's "Shutdown
/// reserves at least 35,000 ms for cooperative server drain", and m5's
/// FastAPI lifespan that closes the LanceDB and Kuzu handles — is reachable
/// ONLY through Tauri's `RunEvent::Exit`. Tauri installs no signal handler,
/// so `killall`, Activity Monitor's Quit, launchd logout/restart/shutdown and
/// any supervising process manager bypassed it entirely: no shutdown frame,
/// no grace, no reap, and no `shutdown-on-exit` record for a post-mortem to
/// read. Measured: the event log simply ended at `window-ready`.
///
/// The handler itself does the minimum an async-signal context permits — set
/// a flag — and a watcher thread performs the actual shutdown. Doing the
/// shutdown inside the handler would call malloc, take a mutex and run
/// `waitpid` from a signal context, which is exactly the class of bug that
/// turns a clean stop into a hang.
#[cfg(unix)]
static TERMINATION_REQUESTED: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

#[cfg(unix)]
extern "C" fn on_termination_signal(_signum: libc::c_int) {
    // Async-signal-safe: a relaxed atomic store and nothing else.
    TERMINATION_REQUESTED.store(true, std::sync::atomic::Ordering::Relaxed);
}

/// Install the handlers and start the watcher.
///
/// Returns without doing anything off Unix; the Windows track (#419-#422)
/// owns its own console-control story.
#[cfg(unix)]
fn install_termination_handler(
    slot: Arc<Mutex<Option<lifecycle::ChildControl>>>,
    recorder: Recorder,
) {
    // SAFETY: `signal` with a plain extern "C" fn is the documented C API;
    // the handler touches only an AtomicBool.
    // Cast via a fn POINTER, not the fn item: clippy rejects the direct
    // item->integer cast, and the pointer form is what `sighandler_t` means.
    let handler = on_termination_signal as extern "C" fn(libc::c_int);
    unsafe {
        libc::signal(libc::SIGTERM, handler as libc::sighandler_t);
        libc::signal(libc::SIGINT, handler as libc::sighandler_t);
    }
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(std::time::Duration::from_millis(100));
            if !TERMINATION_REQUESTED.load(std::sync::atomic::Ordering::Relaxed) {
                continue;
            }
            // Same take-from-the-slot discipline as RunEvent::Exit, so the two
            // paths can never both run the ladder against one child.
            if let Some(control) = slot.lock().ok().and_then(|mut guard| guard.take()) {
                let code = lifecycle::shutdown_child(control);
                let _ = recorder.record(
                    "shutdown-on-signal",
                    serde_json::json!({"child_exit": code}),
                );
            } else {
                // Nothing to drain — still leave the evidence, so a
                // post-mortem can tell this path from a clean quit.
                let _ = recorder.record("shutdown-on-signal", serde_json::json!({}));
            }
            std::process::exit(0);
        }
    });
}

#[cfg(not(unix))]
fn install_termination_handler(
    _slot: Arc<Mutex<Option<lifecycle::ChildControl>>>,
    _recorder: Recorder,
) {
}

fn main() {
    // Diagnostic probe, before any plan work: prints the Rust half of the
    // cross-language `_platform_data_root` pair so the parity assertion can
    // run both. Deliberately the PRE-canonical derivation, because that is
    // what the Python function returns (canonicalization happens later, in
    // `self_authored_plan` and in `ApplicationPaths.resolve`).
    // `args_os`, not `args`: the latter PANICS on non-UTF-8 argv, and this
    // call sits on the startup path of every launch, so a stray non-UTF-8
    // argument would abort the application before any plan work (critique
    // M10). Comparing as OsStr needs no lossy conversion.
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new(DATA_ROOT_PROBE_ARG)) {
        match platform_data_root(|key| std::env::var(key).ok()) {
            Ok(root) => {
                // #485: refuse to print a path the program itself would
                // reject. The probe emitted a data root for a $HOME that is a
                // regular file and for a RELATIVE $HOME; main() caught the
                // relative case only later, and the probe never did — so its
                // output was not by itself a usable data root, which is the
                // one thing a data-root probe is for.
                let home = std::env::var_os("HOME")
                    .or_else(|| std::env::var_os("USERPROFILE"))
                    .map(PathBuf::from)
                    .unwrap_or_default();
                if let Err(reason) = check_data_root_shape(&root, &home) {
                    fail(reason);
                }
                println!("{}", wire_path(&root));
                std::process::exit(0);
            }
            Err(reason) => fail(reason),
        }
    }
    // m15's AC4 probe. Same placement rationale as the data-root probe above:
    // before any plan work, so nothing it reports can have been perturbed by
    // lock acquisition, event recording or window setup.
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new(CHILD_PLAN_PROBE_ARG)) {
        emit_child_plan_probe();
        std::process::exit(0);
    }
    let (plan, plan_source) = load_plan();
    let root = PathBuf::from(&plan.data_root);
    if !root.is_absolute() {
        fail("launch plan data_root must be absolute");
    }
    if fs::create_dir_all(root.join("logs")).is_err() {
        fail("data root logs directory unavailable");
    }
    let recorder = Recorder::new(&root).unwrap_or_else(|reason| fail(reason));
    if let Err(reason) = await_launch_barrier(&root) {
        fail(reason);
    }
    let supervisor_lock = acquire_supervisor_lock(&root).unwrap_or_else(|reason| fail(reason));
    let Some(supervisor_lock) = supervisor_lock else {
        // Loser path: NEVER registers the single-instance listener. The
        // plugin's macOS listener socket is machine-global and its own
        // notify path exits whichever process connects second — letting a
        // lock loser register it first would kill the lock winner mid-boot
        // (the zero-delay hazard Spike-3 measured). The loser instead plays
        // only the CLIENT half of the plugin protocol to activate a running
        // winner, then exits clearly without ever spawning a child.
        // Smoke (conformance) runs never touch the machine-global socket: a
        // developer's installed app must not absorb a test's cwd and argv.
        // `activated` makes the loser's real outcome observable — off macOS it
        // is always false, which the event log now says rather than implying.
        // #437 / #441, mirror image: the socket this would poke is
        // machine-global, so on a NON-default data root the process it
        // activates is an unrelated instance — the winner of THIS lock is
        // some other supervisor entirely, which never registered a listener.
        // Gate on the same decision that governs registration, so the two
        // halves cannot disagree about who owns that path.
        let may_notify = single_instance_decision(
            &root,
            platform_data_root(|key| std::env::var(key).ok())
                .ok()
                .as_deref(),
            single_instance_socket_owner(),
            current_uid(),
        ) == SingleInstance::Register;
        let activated = !plan.smoke && may_notify && notify_running_instance().is_ok();
        let _ = recorder.record(
            "lock-contended",
            serde_json::json!({"activated": activated}),
        );
        std::process::exit(0);
    };
    let _ = recorder.record(
        "supervisor-started",
        // `plan_source` is a static arm label, never a path and never a
        // secret — the event log's token-free invariant is unchanged.
        serde_json::json!({"owns_lock": true, "plan_source": plan_source}),
    );

    // Shared child handle so a window-close exit can still run the bounded
    // normal-shutdown sequence (RunEvent::Exit below).
    let child_slot: Arc<Mutex<Option<lifecycle::ChildControl>>> = Arc::new(Mutex::new(None));
    // #445: armed BEFORE the child can exist, so a signal arriving mid-boot
    // still finds the slot and drains whatever is in it.
    install_termination_handler(child_slot.clone(), recorder.clone());
    let smoke = plan.smoke;
    let activation_recorder = recorder.clone();
    let setup_recorder = recorder.clone();
    let setup_slot = child_slot.clone();
    let exit_slot = child_slot.clone();
    let exit_recorder = recorder.clone();

    // #437 / #441: the plugin's socket is machine-global and lives in
    // world-writable /tmp, so registering it unconditionally lets an
    // unrelated instance — or a squatter — exit this process at startup.
    let single_instance = single_instance_decision(
        &root,
        platform_data_root(|key| std::env::var(key).ok())
            .ok()
            .as_deref(),
        single_instance_socket_owner(),
        current_uid(),
    );
    if let SingleInstance::Skip(reason) = single_instance {
        let _ = recorder.record(
            "single-instance-skipped",
            serde_json::json!({"reason": reason}),
        );
    }

    let mut builder = tauri::Builder::default();
    if single_instance == SingleInstance::Register {
        // Only the lock WINNER gets here; later OS-level launches reach it
        // through the loser's client notify or the plugin's own notify path.
        builder = builder.plugin(tauri_plugin_single_instance::init(
            move |app, _argv, _cwd| {
                let _ = activation_recorder.record("duplicate-activation", serde_json::json!({}));
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.set_focus();
                }
            },
        ));
    }
    let app = builder
        .setup(move |app| {
            // Render state 1 of 2 ("starting"); lifecycle navigates the same
            // window to the child's `/ui/` console once ready. build() with
            // the default visible=true already creates the on-screen native
            // window (measured for issue #423: one AXStandardWindow; adding
            // show()/set_focus() changed nothing) — do not add focus-stealing
            // calls here without a measurement showing they are needed.
            let starting = tauri::Url::parse(
                "data:text/html,%3Ctitle%3EarXMCP%3C%2Ftitle%3E%3Cp%3EarXMCP%20is%20starting%E2%80%A6%3C%2Fp%3E",
            )
            .expect("static starting-page URL parses");
            let builder =
                tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(starting))
                    .title("arXMCP");
            // Smoke-mode-only injection (validate_plan refuses it elsewhere):
            // reproduces the measured negative control so the lifecycle's
            // visibility gate has a committed failing case.
            let builder = if plan.test_hide_window == Some(true) {
                builder.visible(false)
            } else {
                builder
            };
            builder.build()?;
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let code =
                    lifecycle::run_cycle(&handle, &plan, &setup_recorder, &setup_slot, smoke);
                // #425: a smoke run is a headless conformance gate — it must
                // still self-exit with the cycle's code, and the fault matrix
                // asserts exactly that. A NON-smoke failure now leaves the
                // application alive instead, because `lifecycle::show_failure`
                // has just put the reason in the window and exiting would take
                // it off screen again — which was the whole of #425. The
                // operator closes the window when done, and that runs the same
                // bounded `RunEvent::Exit` shutdown as any normal quit.
                if smoke {
                    handle.exit(code);
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .unwrap_or_else(|_| fail("tauri application build failed"));

    // tauri 2.11's run loop does NOT propagate `AppHandle::exit(code)` into
    // the process exit status (measured by the m6 fault matrix: a failed
    // cycle exited 0). Capture the requested code and exit with it ourselves
    // once the RunEvent::Exit child shutdown has run.
    let exit_code_slot: Arc<Mutex<i32>> = Arc::new(Mutex::new(0));
    app.run(move |_handle, event| {
        match event {
            tauri::RunEvent::ExitRequested {
                code: Some(code), ..
            } => {
                if let Ok(mut slot) = exit_code_slot.lock() {
                    *slot = code;
                }
            }
            // Normal user-driven exit (window close / Cmd-Q): the child's
            // parent-lifetime lease plus an authenticated shutdown, bounded
            // grace -> TERM -> KILL -> reap, before the process exits.
            tauri::RunEvent::Exit => {
                if let Some(control) = exit_slot.lock().ok().and_then(|mut slot| slot.take()) {
                    let code = lifecycle::shutdown_child(control);
                    let _ = exit_recorder
                        .record("shutdown-on-exit", serde_json::json!({"child_exit": code}));
                }
                let code = exit_code_slot.lock().map_or(0, |slot| *slot);
                if code != 0 {
                    std::process::exit(code);
                }
            }
            _ => {}
        }
    });
    drop(supervisor_lock);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plan_rejects_unknown_fields_and_empty_argv() {
        let unknown = br#"{"child_argv":["x"],"component":"c","data_root":"/r","identity_file":"/f","smoke":true,"version":"1","startup_token":"nope"}"#;
        assert!(serde_json::from_slice::<Plan>(unknown).is_err());
        let valid = br#"{"child_argv":["/usr/bin/true"],"component":"c","data_root":"/r","identity_file":"/f","smoke":false,"version":"1"}"#;
        let plan: Plan = serde_json::from_slice(valid).expect("valid plan parses");
        assert!(!plan.smoke);
        assert_eq!(plan.child_argv, vec!["/usr/bin/true".to_owned()]);
        // Test-only knobs are absent from a production plan and default off.
        assert_eq!(plan.test_fault, None);
        assert_eq!(plan.test_bound_timeout_ms, None);
        assert_eq!(plan.test_hide_window, None);
        assert_eq!(plan.test_shutdown_grace_ms, None);
        assert_eq!(plan.test_shutdown_force_after_ms, None);
    }

    /// m6 critique M6: the wire frame the supervisor already sent declares
    /// `grace_ms: MIN_GRACE_MS`, so honoring a shrunk grace outside smoke
    /// mode would make that frame a promise it does not keep.
    #[test]
    fn test_only_knobs_are_refused_outside_smoke_mode() {
        let production = br#"{"child_argv":["/usr/bin/true"],"component":"c","data_root":"/r","identity_file":"/f","smoke":false,"version":"1","test_shutdown_grace_ms":400}"#;
        let plan: Plan = serde_json::from_slice(production).expect("parses");
        assert_eq!(
            validate_plan(&plan),
            Err("launch plan carries test-only knobs outside smoke mode")
        );

        let smoke = br#"{"child_argv":["/usr/bin/true"],"component":"c","data_root":"/r","identity_file":"/f","smoke":true,"version":"1","test_shutdown_grace_ms":400,"test_fault":"ignore-shutdown"}"#;
        let plan: Plan = serde_json::from_slice(smoke).expect("parses");
        assert_eq!(validate_plan(&plan), Ok(()));

        // test_hide_window builds a permanently ordered-out window, so it is
        // refused outside smoke mode for the same reason.
        let hidden = br#"{"child_argv":["/usr/bin/true"],"component":"c","data_root":"/r","identity_file":"/f","smoke":false,"version":"1","test_hide_window":true}"#;
        let plan: Plan = serde_json::from_slice(hidden).expect("parses");
        assert_eq!(
            validate_plan(&plan),
            Err("launch plan carries test-only knobs outside smoke mode")
        );
    }

    // --- m10: the self-authored arm ------------------------------------

    fn fake_env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> + 'static {
        let owned: Vec<(String, String)> = pairs
            .iter()
            .map(|(key, value)| ((*key).to_owned(), (*value).to_owned()))
            .collect();
        move |key: &str| {
            owned
                .iter()
                .find(|(name, _)| name == key)
                .map(|(_, value)| value.clone())
        }
    }

    /// Stage m7's onedir shape: `<dir>/arxmcp-desktop-child/arxmcp-desktop-child`
    /// beside a supervisor path, and return that supervisor path.
    /// Write a stub child that is actually EXECUTABLE.
    ///
    /// The fixtures used to `fs::write` a plain file, i.e. model a payload
    /// that could never run — which is exactly what #461 added a check for,
    /// so three of them started failing against the fix. The blind spot was
    /// in the fixture as much as in the code.
    fn stage_child_executable(path: &Path) {
        fs::write(path, b"#!/bin/false\n").expect("stage child executable");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(path, fs::Permissions::from_mode(0o755))
                .expect("chmod the staged child");
        }
    }

    fn stage_payload(label: &str) -> (PathBuf, PathBuf) {
        let base = std::env::temp_dir().join(format!(
            "arxmcp-m10-{label}-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = fs::remove_dir_all(&base);
        let payload = base.join(CHILD_PAYLOAD_DIR);
        fs::create_dir_all(&payload).expect("stage payload dir");
        stage_child_executable(&payload.join(child_executable_name()));
        // #484: a COMPLETE payload includes the probe the launch frame
        // declares. The fixture staged only the child, i.e. modelled a
        // payload the completeness check correctly refuses.
        stage_child_executable(&payload.join(PROBE_EXECUTABLE_NAME));
        // #484 round 2: and the PyInstaller runtime directory. Same lesson a
        // third time — the fixture modelled a payload the completeness check
        // should refuse, so extending the check broke the fixture rather than
        // the code. A fixture that predates a check is always a candidate
        // false-green.
        fs::create_dir_all(payload.join(PAYLOAD_RUNTIME_DIR)).expect("stage payload runtime dir");
        (base.join("supervisor"), base)
    }

    /// #484: a payload missing the PyInstaller runtime is refused by NAME,
    /// before anything is spawned.
    ///
    /// This is the cheap, specific half. It does not detect a modified or an
    /// added file — `verify_bundle_seal` is what covers those — and the two
    /// must not be confused for one another.
    #[test]
    fn a_payload_without_its_runtime_directory_is_refused() {
        let (supervisor, base) = stage_payload("no-runtime");
        let payload = base.join(CHILD_PAYLOAD_DIR);
        assert!(check_payload_completeness(&payload).is_ok());
        fs::remove_dir_all(payload.join(PAYLOAD_RUNTIME_DIR)).expect("remove the runtime dir");
        let err =
            check_payload_completeness(&payload).expect_err("an absent _internal must be refused");
        assert!(err.contains("_internal"), "{err}");
        let _ = supervisor;
        let _ = fs::remove_dir_all(&base);
    }

    /// The composed production plan passes the SAME validator an external
    /// plan does, carries `smoke: false`, and carries no test knob.
    #[test]
    fn self_authored_plan_passes_the_shared_validator() {
        let (supervisor, base) = stage_payload("valid");
        let home = base.join("home");
        fs::create_dir_all(&home).expect("stage home");
        let plan = self_authored_plan(&supervisor, fake_env(&[("HOME", &home.to_string_lossy())]))
            .expect("self-authored plan");
        assert_eq!(validate_plan(&plan), Ok(()));
        assert!(!plan.smoke, "a double-clicked app must not run one cycle");
        assert_eq!(plan.component, CHILD_COMPONENT);
        assert_eq!(plan.test_fault, None);
        assert_eq!(plan.test_bound_timeout_ms, None);
        assert_eq!(plan.test_hide_window, None);
        assert_eq!(plan.test_shutdown_grace_ms, None);
        assert_eq!(plan.test_shutdown_force_after_ms, None);
        // FROZEN-case convergence: identity is the executable itself.
        assert_eq!(plan.child_argv.len(), 1);
        assert_eq!(plan.identity_file, plan.child_argv[0]);
        assert!(PathBuf::from(&plan.child_argv[0]).is_absolute());
        let _ = fs::remove_dir_all(&base);
    }

    /// AC2's non-vacuous half. The five `!smoke` knobs are refused for free
    /// on a self-authored plan (it is never `smoke: true`), so the OTHER
    /// `validate_plan` branch must be shown reachable and refused on a plan
    /// the self-authoring composer built.
    #[test]
    fn self_authored_plan_with_empty_argv_is_refused_by_the_same_validator() {
        let plan = compose_self_authored_plan(
            Vec::new(),
            "/payload/arxmcp-desktop-child".to_owned(),
            "/data".to_owned(),
        );
        assert!(!plan.smoke);
        assert_eq!(validate_plan(&plan), Err("launch plan child_argv is empty"));
    }

    /// The containment check is component-wise on CANONICAL paths, so a
    /// symlink pointing out of the payload root is refused even though its
    /// literal path string sits under the root.
    #[test]
    fn child_executable_escaping_the_payload_root_is_rejected() {
        let (supervisor, base) = stage_payload("escape");
        let payload = base.join(CHILD_PAYLOAD_DIR);
        let outside = base.join("outside");
        fs::create_dir_all(&outside).expect("stage outside dir");
        fs::write(outside.join("impostor"), b"#!/bin/false\n").expect("stage impostor");
        let link = payload.join(child_executable_name());
        fs::remove_file(&link).expect("clear staged child");
        #[cfg(unix)]
        std::os::unix::fs::symlink(outside.join("impostor"), &link).expect("symlink");
        #[cfg(not(unix))]
        fs::write(&link, b"#!/bin/false\n").expect("no symlink on this platform");
        let result = self_authored_plan(&supervisor, fake_env(&[("HOME", "/nonexistent-home")]));
        // `Plan` is not Debug/PartialEq, so compare the error side only.
        #[cfg(unix)]
        assert_eq!(
            result.err(),
            Some("self-authored plan: child executable escapes the payload root")
        );
        #[cfg(not(unix))]
        let _ = result.err();
        let _ = fs::remove_dir_all(&base);
    }

    // --- m15 Decision 2a: the two layouts, as an explicit disjunction ----

    /// Stage a `.app`-shaped tree and return `(supervisor_exe, app_root)`.
    /// Nothing is placed; each test creates the payload root(s) it needs.
    fn stage_bundle(label: &str) -> (PathBuf, PathBuf) {
        let app = std::env::temp_dir().join(format!(
            "arxmcp-m15-{label}-{}-{:?}.app",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = fs::remove_dir_all(&app);
        fs::create_dir_all(app.join("Contents").join("MacOS")).expect("stage Contents/MacOS");
        fs::create_dir_all(app.join("Contents").join("Resources"))
            .expect("stage Contents/Resources");
        (app.join("Contents").join("MacOS").join("supervisor"), app)
    }

    fn stage_child_in(root: &Path) {
        fs::create_dir_all(root).expect("stage payload root");
        stage_child_executable(&root.join(child_executable_name()));
        stage_child_executable(&root.join(PROBE_EXECUTABLE_NAME));
    }

    /// ARM 1 — the assembled `.app`. The payload is NOT a sibling of the
    /// supervisor any more (ADR Decision 2a), so this arm is the one the
    /// shipped artifact takes and it must resolve on its own evidence.
    #[test]
    fn bundle_layout_resolves_the_payload_under_contents_resources() {
        let (supervisor, app) = stage_bundle("bundle-arm");
        let resources = app
            .join("Contents")
            .join("Resources")
            .join(CHILD_PAYLOAD_DIR);
        stage_child_in(&resources);
        let (layout, root) = child_payload_layout(&supervisor).expect("bundle layout resolves");
        assert_eq!(layout, LAYOUT_BUNDLE_RESOURCES);
        assert_eq!(root, resources);
        assert_eq!(
            resolve_inside(&root, &root.join(child_executable_name())),
            Ok(fs::canonicalize(resources.join(child_executable_name())).expect("canonicalize")),
            "resolve_inside is unchanged and stays the gate for the selected root"
        );
        let _ = fs::remove_dir_all(&app);
    }

    /// ARM 2 — m7's onedir / every developer run. Unchanged behaviour, and
    /// asserted rather than inherited: this is the shape every m10 gate uses.
    #[test]
    fn sibling_layout_still_resolves_outside_a_bundle() {
        let (supervisor, base) = stage_payload("sibling-arm");
        let (layout, root) = child_payload_layout(&supervisor).expect("sibling layout resolves");
        assert_eq!(layout, LAYOUT_SUPERVISOR_SIBLING);
        assert_eq!(root, base.join(CHILD_PAYLOAD_DIR));
        let _ = fs::remove_dir_all(&base);
    }

    /// A supervisor that merely LOOKS bundled gets no bundle candidate: the
    /// `../Resources` location is offered only from `…/Contents/MacOS`, so a
    /// `Resources` directory beside an ordinary install cannot become a
    /// launch root.
    #[test]
    fn a_non_bundle_layout_offers_only_the_sibling_candidate() {
        let (supervisor, base) = stage_payload("no-bundle-candidate");
        let candidates = child_payload_candidates(&supervisor).expect("candidates");
        assert_eq!(candidates.len(), 1);
        assert_eq!(candidates[0].0, LAYOUT_SUPERVISOR_SIBLING);
        let _ = fs::remove_dir_all(&base);
    }

    /// THE REFUSAL. Neither layout holds a payload, so the resolution fails
    /// explicitly instead of returning a root that does not exist and letting
    /// a later step guess what went wrong.
    #[test]
    fn neither_layout_present_is_refused() {
        let (supervisor, app) = stage_bundle("neither");
        let candidates = child_payload_candidates(&supervisor).expect("candidates");
        assert_eq!(candidates.len(), 2, "a bundled supervisor has both arms");
        assert_eq!(candidates[0].0, LAYOUT_BUNDLE_RESOURCES);
        assert_eq!(candidates[1].0, LAYOUT_SUPERVISOR_SIBLING);
        let err = child_payload_root(&supervisor).expect_err("no payload anywhere");
        assert!(err.contains("child payload root missing"), "{err}");
        assert!(err.contains("supervisor-sibling"), "{err}");
        let plan = self_authored_plan(&supervisor, fake_env(&[("HOME", "/nonexistent-home")]));
        assert_eq!(plan.err(), Some(err));
        let _ = fs::remove_dir_all(&app);
    }

    /// Ordering, asserted on a tree where BOTH roots exist: the bundle arm
    /// wins. A stray `Contents/MacOS/arxmcp-desktop-child/` — which is where
    /// Decision 2 used to put it — must not shadow the sealed location.
    #[test]
    fn the_bundle_arm_wins_when_both_roots_exist() {
        let (supervisor, app) = stage_bundle("precedence");
        let resources = app
            .join("Contents")
            .join("Resources")
            .join(CHILD_PAYLOAD_DIR);
        stage_child_in(&resources);
        stage_child_in(&app.join("Contents").join("MacOS").join(CHILD_PAYLOAD_DIR));
        let (layout, root) = child_payload_layout(&supervisor).expect("resolves");
        assert_eq!(layout, LAYOUT_BUNDLE_RESOURCES);
        assert_eq!(root, resources);
        let _ = fs::remove_dir_all(&app);
    }

    /// m10's M13 hardening, preserved BY CONSTRUCTION across the new
    /// disjunction: a symlinked bundle payload root is REFUSED, never skipped
    /// in favour of the sibling arm. Skipping would let whoever plants the
    /// symlink choose which root the supervisor launches from.
    #[test]
    #[cfg(unix)]
    fn symlinked_bundle_payload_root_does_not_fall_through() {
        let (supervisor, app) = stage_bundle("symlink-no-fallthrough");
        let elsewhere = app.join("elsewhere");
        stage_child_in(&elsewhere);
        // A perfectly good sibling payload exists; the symlinked bundle root
        // must still win selection and then be refused.
        stage_child_in(&app.join("Contents").join("MacOS").join(CHILD_PAYLOAD_DIR));
        std::os::unix::fs::symlink(
            &elsewhere,
            app.join("Contents")
                .join("Resources")
                .join(CHILD_PAYLOAD_DIR),
        )
        .expect("symlink bundle payload root");
        let (layout, _) = child_payload_layout(&supervisor).expect("symlinked root is PRESENT");
        assert_eq!(layout, LAYOUT_BUNDLE_RESOURCES);
        let result = self_authored_plan(&supervisor, fake_env(&[("HOME", "/nonexistent-home")]));
        assert_eq!(
            result.err(),
            Some("self-authored plan: child payload root is a symlink")
        );
        let _ = fs::remove_dir_all(&app);
    }

    /// The probe reports the arm, so the assembled artifact can be checked
    /// for WHICH layout it resolved rather than only for a path string.
    #[test]
    fn the_probe_reports_the_selected_layout() {
        let (supervisor, app) = stage_bundle("probe-layout");
        stage_child_in(
            &app.join("Contents")
                .join("Resources")
                .join(CHILD_PAYLOAD_DIR),
        );
        let report = child_plan_probe(&supervisor);
        assert_eq!(report["layout"], LAYOUT_BUNDLE_RESOURCES);
        assert_eq!(report["error"], serde_json::Value::Null);
        let (sibling_supervisor, base) = stage_payload("probe-layout-sibling");
        let sibling = child_plan_probe(&sibling_supervisor);
        assert_eq!(sibling["layout"], LAYOUT_SUPERVISOR_SIBLING);
        let _ = fs::remove_dir_all(&app);
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    #[cfg(unix)]
    fn symlinked_payload_root_is_rejected() {
        // Critique M13: canonicalize-then-contain passes trivially when the
        // ROOT itself is the symlink, because the canonical root MOVES with
        // it. Stage exactly that shape and require refusal.
        let (supervisor, base) = stage_payload("symlink-root");
        let payload = base.join(CHILD_PAYLOAD_DIR);
        let elsewhere = base.join("elsewhere");
        fs::create_dir_all(&elsewhere).expect("stage elsewhere dir");
        fs::write(elsewhere.join(child_executable_name()), b"#!/bin/false\n")
            .expect("stage impostor child");
        fs::remove_dir_all(&payload).expect("clear staged payload");
        std::os::unix::fs::symlink(&elsewhere, &payload).expect("symlink payload root");
        let result = self_authored_plan(&supervisor, fake_env(&[("HOME", "/nonexistent-home")]));
        assert_eq!(
            result.err(),
            Some("self-authored plan: child payload root is a symlink")
        );
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn pathlib_normalize_matches_purepath_parsing() {
        // Pinned against real `pathlib` output (critique M1). The `//a`
        // survival is POSIX's implementation-defined two-slash rule, which
        // pathlib honors and a naive collapse would break.
        for (raw, expected) in [
            ("/a//b", "/a/b"),
            ("/a/./b", "/a/b"),
            ("//a/b", "//a/b"),
            ("///a/b", "/a/b"),
            ("/a/b/", "/a/b"),
            ("/a/../b", "/a/../b"),
            ("relative/x", "relative/x"),
        ] {
            assert_eq!(
                pathlib_normalize(raw),
                PathBuf::from(expected),
                "normalizing {raw}"
            );
        }
    }

    #[test]
    fn the_home_lookup_is_lazy_like_pythons() {
        // Critique M7: with the platform's own base variable set, Python
        // never reads HOME, so neither may this. Only the branch this build
        // owns is assertable, so assert that one.
        let with_base: &[(&str, &str)] = if cfg!(target_os = "windows") {
            &[("LOCALAPPDATA", "/base/local")]
        } else if cfg!(target_os = "macos") {
            &[("HOME", "/base/home")]
        } else {
            &[("XDG_DATA_HOME", "/base/xdg")]
        };
        assert!(
            platform_data_root(fake_env(with_base)).is_ok(),
            "the platform base variable alone must suffice"
        );
        if !cfg!(target_os = "macos") {
            // macOS has no base variable of its own — it always needs home,
            // so the no-home refusal there is the documented divergence, not
            // laziness. Everywhere else, absence of home must NOT refuse.
            assert!(platform_data_root(fake_env(with_base)).is_ok());
        }
    }

    /// A missing payload directory is the RED state's Rust half: the arm
    /// refuses rather than authoring a plan pointing at nothing.
    #[test]
    fn missing_child_payload_is_refused() {
        let base = std::env::temp_dir().join(format!("arxmcp-m10-absent-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).expect("stage empty dir");
        // m15 Decision 2a moved the refusal one layer earlier — selection now
        // reports that NEITHER layout held a root — so the message names both
        // layouts while keeping m10's "child payload root missing" wording.
        assert_eq!(
            self_authored_plan(&base.join("supervisor"), fake_env(&[("HOME", "/tmp")])).err(),
            Some(
                "self-authored plan: child payload root missing (checked the bundle Resources and supervisor-sibling layouts)"
            )
        );
        let _ = fs::remove_dir_all(&base);
    }

    /// Branch coverage for the ported function. Byte-for-byte agreement with
    /// the Python original is NOT claimed here — that is asserted by running
    /// both, in `tests/test_desktop_self_authored_launch.py`.
    #[test]
    fn platform_data_root_reads_the_branch_its_platform_owns() {
        let root = platform_data_root(fake_env(&[
            ("HOME", "/home/u"),
            ("XDG_DATA_HOME", "/xdg"),
            ("LOCALAPPDATA", "C:\\local"),
        ]))
        .expect("derives");
        let expected = if cfg!(target_os = "windows") {
            PathBuf::from("C:\\local").join("arXMCP")
        } else if cfg!(target_os = "macos") {
            PathBuf::from("/home/u/Library/Application Support/arXMCP")
        } else {
            PathBuf::from("/xdg/arXMCP")
        };
        assert_eq!(root, expected);
        // USERPROFILE wins over HOME, and "" counts as absent (Python `or`).
        let root = platform_data_root(fake_env(&[("USERPROFILE", ""), ("HOME", "/home/u")]))
            .expect("empty USERPROFILE falls through to HOME");
        assert!(root.starts_with("/home/u") || cfg!(target_os = "windows"));
        // The one documented divergence from Python: refuse, never guess.
        assert_eq!(
            platform_data_root(fake_env(&[])),
            Err("self-authored plan: no HOME or USERPROFILE in environment")
        );
    }

    #[test]
    fn barrier_outside_data_root_is_rejected() {
        // Env-var mutation is process-global; this is the only test touching
        // BARRIER_ENV so there is no parallel-test interference.
        std::env::set_var(BARRIER_ENV, "/tmp/elsewhere/barrier");
        let result = await_launch_barrier(Path::new("/tmp/data-root"));
        std::env::remove_var(BARRIER_ENV);
        assert_eq!(result, Err("launch barrier escaped data root"));
    }

    /// The path is a hand-copy of plugin internals; pin it to the identifier
    /// the plugin actually derives from so an identifier change cannot orphan
    /// activation with only the exact-pin bump as a signal.
    #[cfg(target_os = "macos")]
    // ---- issues #437 / #441: the machine-global socket ------------------
    #[test]
    fn a_non_default_data_root_never_touches_the_shared_socket() {
        // #441's measured shape: a supervisor on its OWN data root wins its
        // OWN lock, then the plugin exits it because an unrelated instance
        // holds the machine-global socket. A developer's debug run could kill
        // the operator's shipped app, and vice versa.
        let mine = PathBuf::from("/tmp/some-scratch-root");
        let default = PathBuf::from("/Users/x/Library/Application Support/arXMCP");
        assert_eq!(
            single_instance_decision(&mine, Some(&default), None, 501),
            SingleInstance::Skip("data root is not the platform default")
        );
    }

    #[test]
    fn the_default_data_root_still_registers() {
        let default = PathBuf::from("/Users/x/Library/Application Support/arXMCP");
        assert_eq!(
            single_instance_decision(&default, Some(&default), None, 501),
            SingleInstance::Register,
            "the shipped shape must keep its activation behaviour"
        );
        // Our own socket from a previous run of ourselves is fine.
        assert_eq!(
            single_instance_decision(&default, Some(&default), Some(501), 501),
            SingleInstance::Register
        );
    }

    #[test]
    fn a_squatted_socket_degrades_activation_instead_of_exiting() {
        // #437: /tmp is world-writable, so anything can pre-create that path.
        // Registering anyway makes every launch of the shipped app exit at
        // startup — a trivial local DoS. Skipping loses focus-on-reactivate
        // and nothing else.
        let default = PathBuf::from("/Users/x/Library/Application Support/arXMCP");
        assert_eq!(
            single_instance_decision(&default, Some(&default), Some(0), 501),
            SingleInstance::Skip("single-instance socket is not owned by this user")
        );
    }

    #[test]
    fn an_underivable_default_is_not_assumed_to_be_the_shipped_shape() {
        // No HOME: there is nothing to compare against, so claiming this is
        // the default root would re-open exactly the cross-talk above.
        let mine = PathBuf::from("/tmp/some-scratch-root");
        assert_eq!(
            single_instance_decision(&mine, None, None, 501),
            SingleInstance::Skip("platform data root underivable")
        );
    }

    #[test]
    fn single_instance_socket_matches_the_configured_identifier() {
        let conf: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).expect("tauri.conf.json");
        let identifier = conf["identifier"].as_str().expect("identifier is a string");
        assert_eq!(
            SINGLE_INSTANCE_SOCKET,
            format!("/tmp/{}_si.sock", identifier.replace(['.', '-'], "_"))
        );
    }

    #[test]
    fn supervisor_lock_is_exclusive_within_one_process() {
        let root = std::env::temp_dir().join(format!("arxmcp-sup-lock-{}", std::process::id()));
        fs::create_dir_all(&root).expect("create lock scratch dir");
        let first = acquire_supervisor_lock(&root).expect("first acquire");
        assert!(first.is_some());
        let second = acquire_supervisor_lock(&root).expect("second acquire");
        assert!(
            second.is_none(),
            "second holder must lose the advisory lock"
        );
        drop(first);
        let third = acquire_supervisor_lock(&root).expect("third acquire");
        assert!(third.is_some(), "released lock must be reacquirable");
        let _ = fs::remove_dir_all(&root);
    }
}

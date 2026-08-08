//! Production desktop supervisor: single-instance arbitration, one real
//! child lifecycle (launch -> bound -> ready -> MCP smoke -> window), and
//! bounded normal shutdown. Configuration arrives as a launch-plan JSON file
//! (`ARXMCP_DESKTOP_LAUNCH_PLAN`); the resolved data root is RECEIVED from
//! that plan — this binary never reimplements `ApplicationPaths` defaults.

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
    /// Test-only: shrinks the supervisor's LOCAL grace/force budgets so the
    /// escalation ladder runs at test speed. The wire frame keeps the
    /// contract-mandated MIN_GRACE_MS floor — these never change what the
    /// child is promised, only how long this process waits.
    #[serde(default)]
    pub test_shutdown_force_after_ms: Option<u64>,
    #[serde(default)]
    pub test_shutdown_grace_ms: Option<u64>,
}

fn fail(reason: &str) -> ! {
    eprintln!("supervisor: {reason}");
    std::process::exit(2);
}

fn load_plan() -> Plan {
    let Some(path) = std::env::var_os(PLAN_ENV) else {
        fail("ARXMCP_DESKTOP_LAUNCH_PLAN is required");
    };
    let bytes = fs::read(PathBuf::from(path)).unwrap_or_else(|_| fail("launch plan unreadable"));
    let plan: Plan =
        serde_json::from_slice(&bytes).unwrap_or_else(|_| fail("launch plan malformed"));
    if let Err(reason) = validate_plan(&plan) {
        fail(reason);
    }
    plan
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
    // and Kuzu handles. Refuse rather than break that promise.
    if !plan.smoke
        && (plan.test_bound_timeout_ms.is_some()
            || plan.test_fault.is_some()
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

fn main() {
    let plan = load_plan();
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
        let activated = !plan.smoke && notify_running_instance().is_ok();
        let _ = recorder.record(
            "lock-contended",
            serde_json::json!({"activated": activated}),
        );
        std::process::exit(0);
    };
    let _ = recorder.record("supervisor-started", serde_json::json!({"owns_lock": true}));

    // Shared child handle so a window-close exit can still run the bounded
    // normal-shutdown sequence (RunEvent::Exit below).
    let child_slot: Arc<Mutex<Option<lifecycle::ChildControl>>> = Arc::new(Mutex::new(None));
    let smoke = plan.smoke;
    let activation_recorder = recorder.clone();
    let setup_recorder = recorder.clone();
    let setup_slot = child_slot.clone();
    let exit_slot = child_slot.clone();
    let exit_recorder = recorder.clone();

    let app = tauri::Builder::default()
        // Only the lock WINNER registers the activation listener; later
        // OS-level launches reach it through the loser's client notify or
        // the plugin's own notify path.
        .plugin(tauri_plugin_single_instance::init(move |app, _argv, _cwd| {
            let _ = activation_recorder.record("duplicate-activation", serde_json::json!({}));
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
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
            tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(starting))
                .title("arXMCP")
                .build()?;
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let code =
                    lifecycle::run_cycle(&handle, &plan, &setup_recorder, &setup_slot, smoke);
                if smoke || code != 0 {
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

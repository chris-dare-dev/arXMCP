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

fn fail(reason: &str) -> ! {
    eprintln!("supervisor: {reason}");
    std::process::exit(2);
}

/// Returns the plan and the name of the arm that produced it. The arm name is
/// recorded on `supervisor-started` so a triage session can tell a bug in the
/// new self-authoring arm from a bug in the environment path — brief-2 risk 5:
/// both arms terminate at the SAME `fail()` sites downstream.
fn load_plan() -> (Plan, &'static str) {
    let Some(path) = std::env::var_os(PLAN_ENV) else {
        // m10: absent variable is the PRODUCTION shape, not an error. Before
        // this arm existed the next line was
        // `fail("ARXMCP_DESKTOP_LAUNCH_PLAN is required")` -> exit(2), which
        // is the RED state `test_red_state_*` in
        // tests/test_desktop_self_authored_launch.py discriminates against.
        let exe = std::env::current_exe()
            .unwrap_or_else(|_| fail("self-authored plan: supervisor path unavailable"));
        let plan = self_authored_plan(&exe, |key| std::env::var(key).ok())
            .unwrap_or_else(|reason| fail(reason));
        // The self-authored plan is NOT trusted more than an external one: it
        // goes through the same validator, under the same rules (AC2).
        if let Err(reason) = validate_plan(&plan) {
            fail(reason);
        }
        return (plan, "self-authored");
    };
    let bytes = fs::read(PathBuf::from(path)).unwrap_or_else(|_| fail("launch plan unreadable"));
    let plan: Plan =
        serde_json::from_slice(&bytes).unwrap_or_else(|_| fail("launch plan malformed"));
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
/// 1. The payload is a SIBLING directory of the installed supervisor, so
///    write access next to the supervisor binary is equivalent to arbitrary
///    code execution as the operator. This needs no trick and is the class
///    that an unpacked-in-Downloads copy or a group-writable install
///    directory makes real. The defenses are install-location permissions
///    and, later, m15/e4 code signing — not this function. Stated for
///    operators in `apps/desktop/README.md`.
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
    let canonical_root =
        fs::canonicalize(root).map_err(|_| "self-authored plan: child payload root missing")?;
    let resolved = fs::canonicalize(candidate)
        .map_err(|_| "self-authored plan: bundled child executable missing")?;
    if !resolved.starts_with(&canonical_root) {
        return Err("self-authored plan: child executable escapes the payload root");
    }
    Ok(resolved)
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

/// m7's onedir stages as a SIBLING of the supervisor executable. That is the
/// convention m10 commits to and m15 replaces: once `.app` assembly lands,
/// this parent chain becomes `Contents/MacOS` -> `Contents/Resources/...`
/// and only this function changes.
fn child_payload_root(supervisor_exe: &Path) -> Result<PathBuf, &'static str> {
    Ok(supervisor_exe
        .parent()
        .ok_or("self-authored plan: supervisor has no parent directory")?
        .join(CHILD_PAYLOAD_DIR))
}

fn child_executable_name() -> String {
    if cfg!(target_os = "windows") {
        format!("{CHILD_PAYLOAD_DIR}.exe")
    } else {
        CHILD_PAYLOAD_DIR.to_owned()
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
                println!("{}", wire_path(&root));
                std::process::exit(0);
            }
            Err(reason) => fail(reason),
        }
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
        let activated = !plan.smoke && notify_running_instance().is_ok();
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
    fn stage_payload(label: &str) -> (PathBuf, PathBuf) {
        let base = std::env::temp_dir().join(format!(
            "arxmcp-m10-{label}-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = fs::remove_dir_all(&base);
        let payload = base.join(CHILD_PAYLOAD_DIR);
        fs::create_dir_all(&payload).expect("stage payload dir");
        fs::write(payload.join(child_executable_name()), b"#!/bin/false\n")
            .expect("stage child executable");
        (base.join("supervisor"), base)
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
        assert_eq!(
            self_authored_plan(&base.join("supervisor"), fake_env(&[("HOME", "/tmp")])).err(),
            Some("self-authored plan: child payload root missing")
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

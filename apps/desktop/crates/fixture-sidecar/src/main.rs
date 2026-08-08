use arxmcp_desktop_contract::{
    encode_frame, parse_frame, read_frame, Bound, ContractError, ContractVersion, Endpoint,
    ExecutableIdentity, Extensions, Frame, Launch, Shutdown, ShutdownSemantics, StartupToken,
    HEALTH_PATH, MCP_PATH, READINESS_PATH, STARTUP_TOKEN_HEADER, UI_PATH,
};
use sha2::{Digest, Sha256};
use std::fmt;
use std::fs;
use std::io::{self, BufReader, Read, Write};
use std::net::{Ipv4Addr, TcpListener, TcpStream};
use std::path::Path;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::Duration;

const COMPONENT: &str = "arxmcp-fixture-sidecar";
/// Test-harness override for the component identity this fixture answers to.
///
/// m10's self-authoring arm derives a FIXED component from the frozen child
/// (`arxmcp-server-desktop-child`), so without this the only way to drive
/// that arm to `window-ready` would be a ~0.75 GB PyInstaller bundle, which
/// no committed gate builds alongside the supervisor.
///
/// The name is NOT `ARXMCP_`-prefixed because `lifecycle.rs` strips every
/// `ARXMCP_*` variable from the child environment — a prefixed knob would be
/// stripped before it arrived and could never work. State it that way round:
/// the un-prefixed name is what makes this knob REACHABLE, not what contains
/// it (m10 critique M2 — the original comment claimed the opposite and read
/// as a safety property).
///
/// What actually contains it: this binary is a TEST FIXTURE. It is built by
/// `make desktop-conformance`, never bundled, never signed, and never
/// installed — `apps/desktop/pyinstaller/arxmcp_desktop.spec` does not
/// reference it. The knob cannot reach an operator because the binary
/// carrying it cannot.
///
/// It does NOT weaken what the supervisor checks: the component is only half
/// of the identity, and the sha256 digest half is unconditional. See
/// `tests/test_desktop_self_authored_launch.py::
/// test_bound_identity_still_refuses_a_component_mismatch`, which drives this
/// override to a value the plan does NOT name and requires refusal — without
/// it, echoing the accepted identity back would make the comparison
/// tautological (critique M14).
const COMPONENT_OVERRIDE_ENV: &str = "DESKTOP_FIXTURE_COMPONENT";
const POLL_INTERVAL: Duration = Duration::from_millis(5);
const HTTP_READ_TIMEOUT: Duration = Duration::from_secs(2);
/// Namespaced launch-extension key carrying an m6 fault-matrix arm. Test-only
/// by construction: the production child never reads extensions.
const FAULT_EXTENSION_KEY: &str = "org.arxmcp.test-fault";
/// Abrupt-crash arms abort shortly after their trigger so Rust `Drop`
/// cleanup cannot run (spike-3 technique).
const CRASH_DELAY: Duration = Duration::from_millis(100);
/// Hard self-destruct for `IgnoreShutdown`, which is SIGTERM-immune and
/// dishonors both stdin EOF and channel disconnect: without a wall-clock
/// bound, a harness killed outside its own teardown leaves this process
/// polling `accept()` on a live loopback port forever. Two orders of
/// magnitude above the shrunk ~800ms ladder it must not mask, and the
/// harness reaps far sooner on every non-pathological path.
const IGNORE_SHUTDOWN_DEADLINE: Duration = Duration::from_secs(60);
/// Consecutive stdin read errors tolerated in the startup-timeout park loop.
/// EOF returns cleanly, so a persistent error means a wedged pipe: without a
/// bound the arm spins a core for the life of the process.
const MAX_CONSECUTIVE_READ_ERRORS: u32 = 3;

/// Fault-matrix arms driven by the REAL supervisor. Every arm except
/// `IgnoreShutdown` stays a cooperating child (exits on stdin EOF or a valid
/// authenticated shutdown) — the spike-3 non-claim stands: a wedged child
/// cannot be killed by a parent that no longer exists.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Fault {
    None,
    /// Park before binding; never emit `bound`; keep honoring the lease.
    StartupTimeout,
    /// Emit an invalid control line that EMBEDS the startup capability, then
    /// serve normally — proving the supervisor scrubs before persisting.
    MalformedBound,
    /// Abort before any bind or `bound` write.
    CrashBeforeBound,
    /// Serve normally, then abort shortly after the first authorized
    /// `/readyz` 200.
    CrashAfterReady,
    /// Ignore stdin EOF, shutdown frames, and SIGTERM: only SIGKILL ends it.
    IgnoreShutdown,
    /// Bind and answer `/healthz`, but never report ready — parks the
    /// supervisor in its readiness poll (the supervisor-crash test window).
    NeverReady,
}

#[derive(Debug)]
enum SidecarError {
    Arguments,
    MissingLaunch,
    Identity,
    DataRoot,
    Bind,
    Control(ContractError),
    Io,
    UnknownFault,
}

impl fmt::Display for SidecarError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Arguments => formatter.write_str("fixture sidecar accepts no arguments"),
            Self::MissingLaunch => formatter.write_str("launch frame required on stdin"),
            Self::Identity => formatter.write_str("fixture executable identity mismatch"),
            Self::DataRoot => formatter.write_str("fixture data root is not prepared"),
            Self::Bind => formatter.write_str("fixture loopback bind failed"),
            Self::Control(error) => write!(formatter, "{error}"),
            Self::Io => formatter.write_str("fixture control-channel I/O failed"),
            Self::UnknownFault => formatter.write_str("fixture test fault is not recognized"),
        }
    }
}

impl From<ContractError> for SidecarError {
    fn from(error: ContractError) -> Self {
        Self::Control(error)
    }
}

enum LeaseEvent {
    Shutdown,
    Eof,
    Invalid,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("fixture-sidecar: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), SidecarError> {
    if std::env::args_os().nth(1).is_some() {
        return Err(SidecarError::Arguments);
    }

    let mut control_input = BufReader::new(io::stdin());
    let bytes = read_frame(&mut control_input)?.ok_or(SidecarError::MissingLaunch)?;
    let launch = match parse_frame(&bytes)? {
        Frame::Launch(value) => value,
        _ => return Err(SidecarError::MissingLaunch),
    };
    let executable_digest = current_executable_sha256()?;
    validate_fixture_launch(&launch, &executable_digest)?;
    let fault = parse_fault(&launch)?;

    match fault {
        Fault::StartupTimeout => return park_on_lease(control_input, &launch),
        Fault::CrashBeforeBound => {
            std::thread::sleep(CRASH_DELAY);
            std::process::abort();
        }
        _ => {}
    }

    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).map_err(|_| SidecarError::Bind)?;
    listener
        .set_nonblocking(true)
        .map_err(|_| SidecarError::Bind)?;
    let address = listener.local_addr().map_err(|_| SidecarError::Bind)?;
    if address.ip().to_string() != "127.0.0.1" || address.port() == 0 {
        return Err(SidecarError::Bind);
    }

    let mut output = io::stdout().lock();
    if fault == Fault::MalformedBound {
        // Deliberately leaks the capability onto the control stream inside an
        // invalid frame: the supervisor MUST scrub it before persisting its
        // bound-frame-invalid diagnostic, and the test sweep proves it did.
        let line = format!("{{\"bound\":\"{}\"\n", launch.startup_token.expose());
        output
            .write_all(line.as_bytes())
            .map_err(|_| SidecarError::Io)?;
    } else {
        let bound = make_bound(&launch, address.port(), &executable_digest);
        let encoded = encode_frame(&Frame::Bound(bound))?;
        output.write_all(&encoded).map_err(|_| SidecarError::Io)?;
    }
    output.flush().map_err(|_| SidecarError::Io)?;
    drop(output);

    if fault == Fault::IgnoreShutdown {
        ignore_sigterm();
    }

    let token = launch.startup_token.clone();
    let receiver =
        spawn_control_reader(control_input, launch.contract.clone(), launch.startup_token);
    serve_until_stopped(listener, receiver, &token, fault)
}

fn parse_fault(launch: &Launch) -> Result<Fault, SidecarError> {
    let Some(value) = launch.extensions.get(FAULT_EXTENSION_KEY) else {
        return Ok(Fault::None);
    };
    match value.as_str() {
        Some("startup-timeout") => Ok(Fault::StartupTimeout),
        Some("malformed-bound") => Ok(Fault::MalformedBound),
        Some("crash-before-bound") => Ok(Fault::CrashBeforeBound),
        Some("crash-after-ready") => Ok(Fault::CrashAfterReady),
        Some("ignore-shutdown") => Ok(Fault::IgnoreShutdown),
        Some("never-ready") => Ok(Fault::NeverReady),
        _ => Err(SidecarError::UnknownFault),
    }
}

/// StartupTimeout park: no bind, no `bound`, but still a cooperating child —
/// mirrors the production `_watch_stdin` lease semantics.
fn park_on_lease(mut input: BufReader<io::Stdin>, launch: &Launch) -> Result<(), SidecarError> {
    let mut consecutive_errors = 0_u32;
    loop {
        match read_frame(&mut input) {
            Ok(None) => return Ok(()),
            Ok(Some(bytes)) => {
                consecutive_errors = 0;
                if let Ok(Frame::Shutdown(shutdown)) = parse_frame(&bytes) {
                    if valid_shutdown(&shutdown, &launch.contract, &launch.startup_token) {
                        return Ok(());
                    }
                }
            }
            Err(_) => {
                consecutive_errors += 1;
                if consecutive_errors >= MAX_CONSECUTIVE_READ_ERRORS {
                    return Err(SidecarError::Io);
                }
                std::thread::sleep(POLL_INTERVAL);
            }
        }
    }
}

#[cfg(unix)]
fn ignore_sigterm() {
    // SAFETY: installing SIG_IGN for SIGTERM has no preconditions.
    unsafe {
        libc::signal(libc::SIGTERM, libc::SIG_IGN);
    }
}

#[cfg(not(unix))]
fn ignore_sigterm() {}

/// The component this run answers to: the fixture's own by default.
fn expected_component() -> String {
    std::env::var(COMPONENT_OVERRIDE_ENV)
        .ok()
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| COMPONENT.to_owned())
}

fn validate_fixture_launch(launch: &Launch, executable_digest: &str) -> Result<(), SidecarError> {
    if launch.executable.component != expected_component()
        || launch.executable.version != env!("CARGO_PKG_VERSION")
        || !constant_time_equal(
            launch.executable.sha256.as_bytes(),
            executable_digest.as_bytes(),
        )
    {
        return Err(SidecarError::Identity);
    }
    let data_root = std::path::PathBuf::from(&launch.data_root);
    let log_location = std::path::PathBuf::from(&launch.log_location);
    let canonical_root = fs::canonicalize(&data_root).map_err(|_| SidecarError::DataRoot)?;
    let log_parent = log_location.parent().ok_or(SidecarError::DataRoot)?;
    let canonical_log_parent = fs::canonicalize(log_parent).map_err(|_| SidecarError::DataRoot)?;
    if !canonical_root_matches_wire_input(&canonical_root, &data_root)
        || !canonical_log_parent.starts_with(&canonical_root)
    {
        return Err(SidecarError::DataRoot);
    }
    Ok(())
}

#[cfg(windows)]
fn canonical_root_matches_wire_input(canonical_root: &Path, wire_root: &Path) -> bool {
    use std::path::{Component, Prefix};

    let mut canonical_components = canonical_root.components();
    let Some(Component::Prefix(canonical_prefix)) = canonical_components.next() else {
        return false;
    };
    let Prefix::VerbatimDisk(canonical_drive) = canonical_prefix.kind() else {
        return false;
    };

    let mut wire_components = wire_root.components();
    let Some(Component::Prefix(wire_prefix)) = wire_components.next() else {
        return false;
    };
    let Prefix::Disk(wire_drive) = wire_prefix.kind() else {
        return false;
    };

    canonical_drive == wire_drive && canonical_components.eq(wire_components)
}

#[cfg(not(windows))]
fn canonical_root_matches_wire_input(canonical_root: &Path, wire_root: &Path) -> bool {
    canonical_root == wire_root
}

fn current_executable_sha256() -> Result<String, SidecarError> {
    let path = std::env::current_exe().map_err(|_| SidecarError::Identity)?;
    let mut executable = fs::File::open(path).map_err(|_| SidecarError::Identity)?;
    let mut digest = Sha256::new();
    let mut chunk = [0_u8; 64 * 1_024];
    loop {
        let count = executable
            .read(&mut chunk)
            .map_err(|_| SidecarError::Identity)?;
        if count == 0 {
            break;
        }
        digest.update(&chunk[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn make_bound(launch: &Launch, port: u16, executable_digest: &str) -> Bound {
    let authority = format!("http://127.0.0.1:{port}");
    Bound {
        contract: launch.contract.clone(),
        data_root: launch.data_root.clone(),
        endpoint: Endpoint {
            host: "127.0.0.1".to_owned(),
            port,
        },
        executable: ExecutableIdentity {
            // Echo the identity that was ACCEPTED, so the supervisor's
            // bound-identity comparison stays an honest equality check.
            component: expected_component(),
            sha256: executable_digest.to_owned(),
            version: env!("CARGO_PKG_VERSION").to_owned(),
        },
        extensions: Extensions::new(),
        health_url: format!("{authority}{HEALTH_PATH}"),
        kind: "bound".to_owned(),
        log_location: launch.log_location.clone(),
        mcp_url: format!("{authority}{MCP_PATH}"),
        readiness_url: format!("{authority}{READINESS_PATH}"),
        shutdown: ShutdownSemantics {
            force_after_ms: launch.shutdown.force_after_ms,
            grace_ms: launch.shutdown.grace_ms,
            parent_lifetime: launch.shutdown.parent_lifetime.clone(),
            reap: launch.shutdown.reap.clone(),
        },
        ui_url: format!("{authority}{UI_PATH}"),
    }
}

fn spawn_control_reader(
    mut input: BufReader<io::Stdin>,
    version: ContractVersion,
    expected_token: StartupToken,
) -> Receiver<LeaseEvent> {
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || loop {
        let event = match read_frame(&mut input) {
            Ok(None) => LeaseEvent::Eof,
            Ok(Some(bytes)) => match parse_frame(&bytes) {
                Ok(Frame::Shutdown(shutdown))
                    if valid_shutdown(&shutdown, &version, &expected_token) =>
                {
                    LeaseEvent::Shutdown
                }
                _ => LeaseEvent::Invalid,
            },
            Err(_) => LeaseEvent::Invalid,
        };
        let terminal = matches!(event, LeaseEvent::Shutdown | LeaseEvent::Eof);
        if sender.send(event).is_err() || terminal {
            break;
        }
    });
    receiver
}

fn valid_shutdown(
    shutdown: &Shutdown,
    expected_version: &ContractVersion,
    expected_token: &StartupToken,
) -> bool {
    shutdown.contract == *expected_version
        && constant_time_equal(
            shutdown.startup_token.expose().as_bytes(),
            expected_token.expose().as_bytes(),
        )
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut difference = 0_u8;
    for (left_byte, right_byte) in left.iter().zip(right) {
        difference |= left_byte ^ right_byte;
    }
    difference == 0
}

fn serve_until_stopped(
    listener: TcpListener,
    receiver: Receiver<LeaseEvent>,
    token: &StartupToken,
    fault: Fault,
) -> Result<(), SidecarError> {
    let mut abort_at: Option<std::time::Instant> = None;
    if fault == Fault::IgnoreShutdown {
        abort_at = Some(std::time::Instant::now() + IGNORE_SHUTDOWN_DEADLINE);
    }
    loop {
        if let Some(at) = abort_at {
            if std::time::Instant::now() >= at {
                std::process::abort();
            }
        }
        match receiver.try_recv() {
            // IgnoreShutdown: the lease is deliberately dishonored so only
            // the supervisor's SIGKILL rung can end this process.
            Ok(LeaseEvent::Shutdown | LeaseEvent::Eof) if fault != Fault::IgnoreShutdown => {
                return Ok(())
            }
            Ok(_) | Err(TryRecvError::Empty) => {}
            Err(TryRecvError::Disconnected) if fault != Fault::IgnoreShutdown => return Ok(()),
            Err(TryRecvError::Disconnected) => {}
        }

        match listener.accept() {
            Ok((stream, _address)) => {
                stream
                    .set_nonblocking(false)
                    .map_err(|_| SidecarError::Io)?;
                let ready_served = respond(stream, token, fault);
                if ready_served && fault == Fault::CrashAfterReady && abort_at.is_none() {
                    abort_at = Some(std::time::Instant::now() + CRASH_DELAY);
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                std::thread::sleep(POLL_INTERVAL);
            }
            Err(_) => return Err(SidecarError::Bind),
        }
    }
}

/// The three requests `supervisor::lifecycle::mcp_smoke` makes, matched on
/// their exact serialized JSON-RPC method. `notifications/initialized`
/// CONTAINS `initialize`, so the closing quote is load-bearing.
const MCP_INITIALIZE: &str = r#""method":"initialize""#;
const MCP_INITIALIZED: &str = r#""method":"notifications/initialized""#;
const MCP_TOOLS_LIST: &str = r#""method":"tools/list""#;
/// The supervisor requires a session id on the initialize response and only
/// echoes the value back; nothing here is a real MCP session.
const MCP_SESSION_HEADER: &str = "Mcp-Session-Id: fixture-session\r\n";

/// Returns true when an AUTHORIZED `/readyz` 200 was served (the
/// crash-after-ready trigger).
fn respond(mut stream: TcpStream, token: &StartupToken, fault: Fault) -> bool {
    let _ = stream.set_read_timeout(Some(HTTP_READ_TIMEOUT));
    let mut request = Vec::new();
    let mut chunk = [0_u8; 512];
    let head_end = loop {
        let Ok(count) = stream.read(&mut chunk) else {
            return false;
        };
        if count == 0 || request.len() + count > 4_096 {
            return false;
        }
        request.extend_from_slice(&chunk[..count]);
        if let Some(index) = request.windows(4).position(|window| window == b"\r\n\r\n") {
            break index;
        }
    };

    // Owned before the body read below, which reborrows `request` mutably.
    let (request_line, authorized, declared) = {
        let Ok(text) = std::str::from_utf8(&request[..head_end]) else {
            return false;
        };
        let mut lines = text.split("\r\n");
        let request_line = lines.next().unwrap_or_default().to_owned();
        let headers: Vec<(&str, &str)> = lines
            .filter_map(|line| line.split_once(':'))
            .map(|(name, value)| (name, value.trim()))
            .collect();
        let supplied_token = headers.iter().find_map(|(name, value)| {
            name.eq_ignore_ascii_case(STARTUP_TOKEN_HEADER)
                .then_some(*value)
        });
        let authorized = supplied_token.is_some_and(|supplied| {
            constant_time_equal(supplied.as_bytes(), token.expose().as_bytes())
        });
        let declared = headers
            .iter()
            .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
            .and_then(|(_, value)| value.parse::<usize>().ok())
            .unwrap_or(0);
        (request_line, authorized, declared)
    };
    // The client writes headers and body as two syscalls, so the body is
    // usually NOT in the buffer the header scan stopped on.
    let want = head_end + 4 + declared.min(4_096);
    while request.len() < want {
        let Ok(count) = stream.read(&mut chunk) else {
            break;
        };
        if count == 0 {
            break;
        }
        request.extend_from_slice(&chunk[..count]);
    }
    let body_text = String::from_utf8_lossy(&request[head_end + 4..]).into_owned();

    let mut ready_served = false;
    let mut session_header = "";
    let (status, body) = if request_line == "GET /healthz HTTP/1.1" {
        ("200 OK", r#"{"status":"ok"}"#)
    } else if request_line == "GET /readyz HTTP/1.1" && authorized {
        if fault == Fault::NeverReady {
            ("200 OK", r#"{"status":"starting"}"#)
        } else {
            ready_served = true;
            ("200 OK", r#"{"status":"ready"}"#)
        }
    } else if request_line == "GET /readyz HTTP/1.1" {
        ("401 Unauthorized", r#"{"status":"unauthorized"}"#)
    } else if request_line == "POST /mcp HTTP/1.1" && fault == Fault::None {
        // Only the fault-free arm serves the smoke: every other arm asserts
        // an outcome reached BEFORE the window step, and answering here
        // would carry those cycles past it into a different code path.
        if body_text.contains(MCP_INITIALIZED) {
            ("202 Accepted", "")
        } else if body_text.contains(MCP_INITIALIZE) {
            session_header = MCP_SESSION_HEADER;
            (
                "200 OK",
                r#"{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2025-06-18","capabilities":{}}}"#,
            )
        } else if body_text.contains(MCP_TOOLS_LIST) {
            (
                "200 OK",
                r#"{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"fixture_probe"}]}}"#,
            )
        } else {
            ("400 Bad Request", r#"{"status":"unexpected-mcp-method"}"#)
        }
    } else {
        ("404 Not Found", r#"{"status":"not-found"}"#)
    };
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\n{session_header}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes());
    ready_served
}

#[cfg(test)]
mod tests {
    use super::canonical_root_matches_wire_input;
    use std::fs;
    use std::path::Path;

    #[cfg(windows)]
    #[test]
    fn conventional_windows_wire_path_matches_verbatim_canonical_path() {
        let canonical = Path::new(r"\\?\C:\Users\fixture\runtime data 数学");
        let wire = Path::new("C:/Users/fixture/runtime data 数学");

        assert!(canonical_root_matches_wire_input(canonical, wire));
    }

    #[cfg(windows)]
    #[test]
    fn materially_different_windows_path_does_not_match() {
        let canonical = Path::new(r"\\?\C:\Users\fixture\runtime data");
        let wire = Path::new("C:/Users/fixture/other data");

        assert!(!canonical_root_matches_wire_input(canonical, wire));
    }

    #[cfg(windows)]
    #[test]
    fn verbatim_unc_path_is_not_treated_as_a_drive_wire_path() {
        let canonical = Path::new(r"\\?\UNC\server\share\runtime data");
        let wire = Path::new("C:/server/share/runtime data");

        assert!(!canonical_root_matches_wire_input(canonical, wire));
    }

    #[cfg(windows)]
    #[test]
    fn prepared_windows_directory_matches_its_conventional_wire_spelling() {
        let root = std::env::temp_dir().join(format!(
            "arxmcp fixture runtime data 数学 {}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("create fixture root");
        let canonical = fs::canonicalize(&root).expect("canonicalize fixture root");
        let wire = std::path::PathBuf::from(root.to_string_lossy().replace('\\', "/"));

        let matches = canonical_root_matches_wire_input(&canonical, &wire);
        let _ = fs::remove_dir(&root);
        assert!(matches, "canonical={canonical:?}, wire={wire:?}");
    }

    #[cfg(not(windows))]
    #[test]
    fn non_windows_comparison_remains_exact() {
        assert!(canonical_root_matches_wire_input(
            Path::new("/tmp/runtime data"),
            Path::new("/tmp/runtime data")
        ));
        assert!(!canonical_root_matches_wire_input(
            Path::new("/tmp/runtime data"),
            Path::new("/tmp/other data")
        ));
    }
}

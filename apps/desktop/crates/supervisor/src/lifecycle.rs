//! One real child lifecycle: spawn -> launch frame -> bound -> health/ready
//! probes -> MCP smoke -> window navigate -> bounded normal shutdown.
//!
//! The startup capability lives only in the launch/shutdown frames written
//! to the retained child stdin and in the `/readyz` request header. It is
//! never recorded, logged, placed in argv/env/URLs, or persisted.

use crate::events::Recorder;
use crate::http;
use crate::process_control;
use crate::Plan;
use arxmcp_desktop_contract::{
    encode_frame, generate_startup_token, parse_frame, read_frame, Bound, ContractVersion,
    Endpoint, ExecutableIdentity, Extensions, Frame, Launch, ProbePaths, Shutdown,
    ShutdownSemantics, StartupToken, HEALTH_PATH, MCP_PATH, MIN_GRACE_MS, READINESS_PATH,
    STARTUP_TOKEN_HEADER, UI_PATH,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::{BufReader, Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::Manager;

/// Bound arrives only after the child's eager BGE-M3/LanceDB lifespan
/// warm-up (server/main.py documents 5-30s); generous headroom for load.
const BOUND_TIMEOUT: Duration = Duration::from_secs(240);
const PROBE_TIMEOUT: Duration = Duration::from_secs(2);
/// The MCP smoke has no `poll_until` retry, unlike the health (60s) and
/// readiness (120s) probes, and it runs on a machine that has just finished
/// loading BGE-M3 and LanceDB — where a 2s budget is least safe. In the
/// production path a single transient overrun quits the whole app.
const SMOKE_TIMEOUT: Duration = Duration::from_secs(15);
const HEALTH_DEADLINE: Duration = Duration::from_secs(60);
const READY_DEADLINE: Duration = Duration::from_secs(120);
/// TERM -> KILL window; the wire contract caps this at MIN_GRACE_MS.
const FORCE_AFTER_MS: u64 = 5_000;
/// Post-SIGKILL reap budget. A child wedged in uninterruptible I/O (a stalled
/// LanceDB/Kuzu read on a slow or disconnected volume) ignores SIGKILL until
/// that I/O completes, and this runs on the `RunEvent::Exit` handler — leaving
/// the process for the OS to reap beats hanging the app on quit. Exhausting it
/// returns -1, which the caller records as `shutdown-unclean`.
const REAP_BUDGET_MS: u64 = 2_000;

pub struct ChildControl {
    child: Child,
    /// Retained stdin IS the parent-lifetime lease; dropped at shutdown.
    stdin: ChildStdin,
    token: StartupToken,
    contract: ContractVersion,
    grace_ms: u64,
    force_after_ms: u64,
}

pub fn run_cycle(
    handle: &tauri::AppHandle,
    plan: &Plan,
    recorder: &Recorder,
    shared_slot: &Arc<Mutex<Option<ChildControl>>>,
    smoke: bool,
) -> i32 {
    let mut control: Option<ChildControl> = None;
    match cycle(handle, plan, recorder, &mut control, smoke) {
        Ok(()) => {
            if smoke {
                match control.take().map(shutdown_child) {
                    Some(0) => {
                        let _ = recorder.record("shutdown-clean", json!({"child_exit": 0}));
                        0
                    }
                    Some(code) => {
                        let _ = recorder.record("shutdown-unclean", json!({"child_exit": code}));
                        1
                    }
                    None => 1,
                }
            } else {
                // Hand the live child to the RunEvent::Exit handler so a
                // window-close quit still runs the bounded shutdown.
                if let Ok(mut slot) = shared_slot.lock() {
                    *slot = control.take();
                }
                0
            }
        }
        Err(reason) => {
            let _ = recorder.record("lifecycle-failed", json!({"reason": reason}));
            if let Some(orphan) = control.take() {
                let _ = shutdown_child(orphan);
            }
            1
        }
    }
}

fn cycle(
    handle: &tauri::AppHandle,
    plan: &Plan,
    recorder: &Recorder,
    control: &mut Option<ChildControl>,
    _smoke: bool,
) -> Result<(), &'static str> {
    let digest = file_sha256(&plan.identity_file)?;
    let token = generate_startup_token().map_err(|_| "startup token generation failed")?;
    let expected_identity = ExecutableIdentity {
        component: plan.component.clone(),
        sha256: digest,
        version: plan.version.clone(),
    };
    let launch = Launch {
        contract: ContractVersion { major: 1, minor: 0 },
        data_root: plan.data_root.clone(),
        endpoint_request: Endpoint {
            host: "127.0.0.1".to_owned(),
            port: 0,
        },
        executable: expected_identity.clone(),
        extensions: Extensions::new(),
        kind: "launch".to_owned(),
        log_location: format!("{}/logs/desktop-child.log", plan.data_root),
        probe_paths: ProbePaths {
            health: HEALTH_PATH.to_owned(),
            mcp: MCP_PATH.to_owned(),
            readiness: READINESS_PATH.to_owned(),
            ui: UI_PATH.to_owned(),
        },
        shutdown: ShutdownSemantics {
            force_after_ms: FORCE_AFTER_MS,
            grace_ms: MIN_GRACE_MS,
            parent_lifetime: "stdin-eof".to_owned(),
            reap: "graceful-force-reap".to_owned(),
        },
        startup_token: token.clone(),
    };
    // encode_frame re-validates the whole frame (paths, semantics, token).
    let launch_bytes = encode_frame(&Frame::Launch(launch)).map_err(|_| "launch frame invalid")?;

    let log_path = std::path::PathBuf::from(&plan.data_root)
        .join("logs")
        .join("desktop-child.log");
    let log_file = std::fs::File::create(&log_path).map_err(|_| "child log unwritable")?;
    let mut command = Command::new(&plan.child_argv[0]);
    command
        .args(&plan.child_argv[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log_file));
    // The child's entire configuration is the launch frame; scrub ambient
    // ARXMCP_* so stray operator env can neither configure the child nor
    // trip its unknown-env-var startup FATAL.
    for (key, _) in std::env::vars_os() {
        if key.to_string_lossy().starts_with("ARXMCP_") {
            command.env_remove(&key);
        }
    }
    let mut child = command.spawn().map_err(|_| "child spawn failed")?;
    let child_pid = child.id();
    let _ = recorder.record("child-spawn", json!({"child_pid": child_pid}));

    let mut stdin = child.stdin.take().ok_or("child stdin unavailable")?;
    let stdout = child.stdout.take().ok_or("child stdout unavailable")?;
    stdin
        .write_all(&launch_bytes)
        .and_then(|_| stdin.flush())
        .map_err(|_| "launch frame write failed")?;
    *control = Some(ChildControl {
        child,
        stdin,
        token: token.clone(),
        contract: ContractVersion { major: 1, minor: 0 },
        grace_ms: MIN_GRACE_MS,
        force_after_ms: FORCE_AFTER_MS,
    });

    let bound = await_bound(stdout, recorder)?;
    if bound.executable != expected_identity {
        return Err("bound identity mismatch");
    }
    if bound.data_root != plan.data_root {
        return Err("bound data root mismatch");
    }
    let port = bound.endpoint.port;
    let _ = recorder.record("child-bound", json!({"port": port}));

    poll_until(HEALTH_DEADLINE, || {
        matches!(
            http::request(port, "GET", HEALTH_PATH, &[], None, PROBE_TIMEOUT),
            Ok(response) if response.status == 200
        )
    })
    .map_err(|_| "health probe deadline")?;
    let token_header = token.expose().to_owned();
    poll_until(READY_DEADLINE, || ready_status(port, &token_header))
        .map_err(|_| "readiness probe deadline")?;
    let _ = recorder.record("child-ready", json!({}));

    let tool_count = mcp_smoke(port, plan)?;
    let _ = recorder.record("mcp-smoke-ok", json!({"tools": tool_count}));

    navigate_window(handle, &bound)?;
    let _ = recorder.record("window-ready", json!({}));
    Ok(())
}

/// Read exactly one `bound` frame; a background drain then flags any
/// further stdout bytes (child stdout is control-only after `bound`).
fn await_bound(
    stdout: std::process::ChildStdout,
    recorder: &Recorder,
) -> Result<Bound, &'static str> {
    let (sender, receiver) = mpsc::channel();
    let drain_recorder = recorder.clone();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let first = read_frame(&mut reader);
        let _ = sender.send(first);
        let mut remainder = [0_u8; 1_024];
        let mut extra = 0_usize;
        while let Ok(count) = reader.read(&mut remainder) {
            if count == 0 {
                break;
            }
            extra += count;
        }
        if extra > 0 {
            let _ = drain_recorder.record("unexpected-stdout", json!({"bytes": extra}));
        }
    });
    let frame = receiver
        .recv_timeout(BOUND_TIMEOUT)
        .map_err(|_| "bound frame timeout")?
        .map_err(|_| "bound frame read failed")?
        .ok_or("child stdout closed before bound")?;
    match parse_frame(&frame).map_err(|_| "bound frame invalid")? {
        Frame::Bound(bound) => Ok(bound),
        _ => Err("first control frame was not bound"),
    }
}

fn ready_status(port: u16, token: &str) -> bool {
    let Ok(response) = http::request(
        port,
        "GET",
        READINESS_PATH,
        &[(STARTUP_TOKEN_HEADER, token)],
        None,
        PROBE_TIMEOUT,
    ) else {
        return false;
    };
    if response.status != 200 {
        return false;
    }
    // 200 alone is insufficient: bootstrap mode also answers 200. Demand the
    // fully-warm "ready" body before rendering the console.
    serde_json::from_slice::<Value>(&response.body)
        .ok()
        .and_then(|body| body.get("status").and_then(Value::as_str).map(String::from))
        .as_deref()
        == Some("ready")
}

/// One real MCP exchange: initialize -> notifications/initialized ->
/// tools/list. Returns the served tool count.
fn mcp_smoke(port: u16, plan: &Plan) -> Result<u64, &'static str> {
    let base_headers = [
        ("Content-Type", "application/json"),
        ("Accept", "application/json, text/event-stream"),
        ("Mcp-Protocol-Version", "2025-06-18"),
    ];
    let initialize = json!({
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "arxmcp-desktop-supervisor", "version": plan.version},
        },
    });
    let response = mcp_post(port, &base_headers, &initialize)?;
    if response.status != 200 {
        return Err("initialize rejected");
    }
    let session = response
        .header("mcp-session-id")
        .ok_or("initialize returned no session id")?
        .to_owned();

    let session_headers = [
        ("Content-Type", "application/json"),
        ("Accept", "application/json, text/event-stream"),
        ("Mcp-Protocol-Version", "2025-06-18"),
        ("Mcp-Session-Id", session.as_str()),
    ];
    let initialized = json!({"jsonrpc": "2.0", "method": "notifications/initialized"});
    let response = mcp_post(port, &session_headers, &initialized)?;
    if !matches!(response.status, 200 | 202 | 204) {
        return Err("initialized notification rejected");
    }

    let list = json!({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}});
    let response = mcp_post(port, &session_headers, &list)?;
    if response.status != 200 {
        return Err("tools/list rejected");
    }
    let body: Value =
        serde_json::from_slice(&response.body).map_err(|_| "tools/list body not JSON")?;
    if body.get("error").is_some() {
        return Err("tools/list returned a JSON-RPC error");
    }
    let tools = body
        .get("result")
        .and_then(|result| result.get("tools"))
        .and_then(Value::as_array)
        .ok_or("tools/list returned no tool array")?;
    if tools.is_empty() {
        return Err("tools/list returned zero tools");
    }
    Ok(tools.len() as u64)
}

/// POST to /mcp, following one same-origin redirect (the mount answers on
/// the trailing-slash path).
fn mcp_post(
    port: u16,
    headers: &[(&str, &str)],
    body: &Value,
) -> Result<http::Response, &'static str> {
    let payload = serde_json::to_vec(body).map_err(|_| "request body encode failed")?;
    let response = http::request(
        port,
        "POST",
        MCP_PATH,
        headers,
        Some(&payload),
        SMOKE_TIMEOUT,
    )?;
    if !matches!(response.status, 307 | 308) {
        return Ok(response);
    }
    let location = response
        .header("location")
        .ok_or("redirect without location")?;
    let path = location
        .find("://")
        .and_then(|scheme| {
            location[scheme + 3..]
                .find('/')
                .map(|slash| scheme + 3 + slash)
        })
        .map_or(location, |index| &location[index..]);
    if !path.starts_with(MCP_PATH) {
        return Err("redirect escaped the MCP mount");
    }
    let path = path.to_owned();
    http::request(port, "POST", &path, headers, Some(&payload), SMOKE_TIMEOUT)
}

/// Render state 2 of 2: point the existing window at the child's console.
fn navigate_window(handle: &tauri::AppHandle, bound: &Bound) -> Result<(), &'static str> {
    let url = tauri::Url::parse(&bound.ui_url).map_err(|_| "bound ui_url unparseable")?;
    let (sender, receiver) = mpsc::channel();
    let main_handle = handle.clone();
    handle
        .run_on_main_thread(move || {
            let result = main_handle
                .get_webview_window("main")
                .ok_or("main window missing")
                .and_then(|window| window.navigate(url).map_err(|_| "window navigate failed"));
            let _ = sender.send(result);
        })
        .map_err(|_| "main-thread dispatch failed")?;
    receiver
        .recv_timeout(Duration::from_secs(10))
        .map_err(|_| "window navigate timeout")?
}

/// Bounded normal shutdown: authenticated frame + stdin-EOF lease, then
/// grace wait -> cooperative terminate -> forced kill; always reaps.
/// Returns the child exit code (-1 when it had to be force-killed).
pub fn shutdown_child(mut control: ChildControl) -> i64 {
    let shutdown = Shutdown {
        contract: control.contract.clone(),
        extensions: Extensions::new(),
        kind: "shutdown".to_owned(),
        startup_token: control.token.clone(),
    };
    if let Ok(bytes) = encode_frame(&Frame::Shutdown(shutdown)) {
        let _ = control.stdin.write_all(&bytes);
        let _ = control.stdin.flush();
    }
    drop(control.stdin);
    if let Some(code) = wait_exit(&mut control.child, control.grace_ms) {
        return code;
    }
    let _ = process_control::request_terminate(control.child.id());
    if let Some(code) = wait_exit(&mut control.child, control.force_after_ms) {
        return code;
    }
    let _ = control.child.kill();
    wait_exit(&mut control.child, REAP_BUDGET_MS).unwrap_or(-1)
}

fn wait_exit(child: &mut Child, budget_ms: u64) -> Option<i64> {
    let deadline = Instant::now() + Duration::from_millis(budget_ms);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some(status.code().map_or(-1, i64::from)),
            Ok(None) => {}
            Err(_) => return None,
        }
        if Instant::now() >= deadline {
            return None;
        }
        std::thread::sleep(Duration::from_millis(25));
    }
}

fn poll_until(budget: Duration, mut probe: impl FnMut() -> bool) -> Result<(), ()> {
    let deadline = Instant::now() + budget;
    loop {
        if probe() {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

fn file_sha256(path: &str) -> Result<String, &'static str> {
    let bytes = std::fs::read(path).map_err(|_| "identity file unreadable")?;
    let mut digest = Sha256::new();
    digest.update(&bytes);
    Ok(format!("{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redirect_location_resolves_to_mount_relative_path() {
        // Mirrors mcp_post's parsing on the absolute and relative shapes
        // Starlette emits for the trailing-slash redirect.
        for location in ["http://127.0.0.1:7733/mcp/", "/mcp/"] {
            let path = location
                .find("://")
                .and_then(|scheme| {
                    location[scheme + 3..]
                        .find('/')
                        .map(|slash| scheme + 3 + slash)
                })
                .map_or(location, |index| &location[index..]);
            assert_eq!(path, "/mcp/");
        }
    }

    #[test]
    fn wait_exit_reaps_a_fast_child_and_times_out_on_a_slow_one() {
        let mut fast = Command::new("/usr/bin/true").spawn().expect("spawn true");
        assert_eq!(wait_exit(&mut fast, 5_000), Some(0));
        let mut slow = Command::new("/bin/sleep")
            .arg("30")
            .spawn()
            .expect("spawn sleep");
        assert_eq!(wait_exit(&mut slow, 50), None);
        assert!(process_control::request_terminate(slow.id()));
        let _ = slow.wait();
    }

    /// m5 critique M3: every other test drives a child that exits on the first
    /// cooperative signal, so `shutdown_child`'s composition of
    /// `wait_exit` -> `request_terminate` -> `wait_exit` -> `kill` -> bounded
    /// reap was entirely uncovered — and it is the safety net for an
    /// unresponsive child and the only thing preventing an orphan that holds
    /// the ephemeral port and the LanceDB directory.
    #[test]
    fn shutdown_child_escalates_through_terminate_to_kill() {
        // Ignores both stdin EOF and SIGTERM, forcing the whole ladder. No
        // `exec`: that would replace the shell and lose the trap.
        let mut child = Command::new("/bin/sh")
            .args(["-c", "trap '' TERM; sleep 30"])
            .stdin(Stdio::piped())
            .spawn()
            .expect("spawn stubborn child");
        let stdin = child.stdin.take().expect("stubborn child stdin");
        let pid = child.id();
        let control = ChildControl {
            child,
            stdin,
            token: generate_startup_token().expect("startup token"),
            contract: ContractVersion { major: 1, minor: 0 },
            grace_ms: 200,
            force_after_ms: 200,
        };
        let started = Instant::now();
        let code = shutdown_child(control);
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "every step of shutdown_child must stay bounded"
        );
        assert_eq!(code, -1, "a force-killed child reports no exit code");
        // Reaped: signalling a reaped-and-not-recycled pid fails.
        assert!(!process_control::request_terminate(pid));
    }

    #[test]
    fn file_sha256_matches_known_vector() {
        let scratch = std::env::temp_dir().join(format!("arxmcp-sup-sha-{}", std::process::id()));
        std::fs::write(&scratch, b"abc").expect("write digest fixture");
        let digest = file_sha256(scratch.to_str().expect("utf-8 temp path"))
            .expect("digest fixture readable");
        assert_eq!(
            digest,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let _ = std::fs::remove_file(&scratch);
    }
}

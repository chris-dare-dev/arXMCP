//! One real child lifecycle: spawn -> launch frame -> bound -> health/ready
//! probes -> MCP smoke -> window navigate -> bounded normal shutdown.
//!
//! The startup capability lives only in the launch/shutdown frames written
//! to the retained child stdin and in the `/readyz` request header. It is
//! never recorded, logged, placed in argv/env/URLs, or persisted.

use crate::events::Recorder;
use crate::http;
use crate::process_control;
use crate::redact;
use crate::Plan;
use arxmcp_desktop_contract::{
    encode_frame, generate_startup_token, parse_frame, read_frame, Bound, ContractVersion,
    Endpoint, ExecutableIdentity, Extensions, Frame, Launch, ProbePaths, Shutdown,
    ShutdownSemantics, StartupToken, HEALTH_PATH, MCP_PATH, MIN_GRACE_MS, READINESS_PATH,
    STARTUP_TOKEN_HEADER, UI_PATH,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, Read, Seek, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::Manager;

/// Bound arrives only after the child's eager BGE-M3/LanceDB lifespan
/// warm-up (server/main.py documents 5-30s); generous headroom for load.
const BOUND_TIMEOUT: Duration = Duration::from_secs(240);

/// #442: how often the bound wait reports that it is still waiting. The
/// timeout above is NOT the bug — a cold BGE-M3 load is genuinely slow, and
/// shortening it would turn slow first runs into failures. The bug was 241
/// seconds of total silence, in which a wedged child and a warm-up are
/// indistinguishable to both the operator and a triage session.
const BOUND_PROGRESS_INTERVAL: Duration = Duration::from_secs(15);

/// #442: when to stop showing "starting…" and say why it is taking so long.
/// Past this the window explains the first-run model load rather than leaving
/// the operator to guess whether the application is wedged.
const FIRST_RUN_NOTICE: Duration = Duration::from_secs(30);

/// #443: how often the watchdog asks whether the child is still alive.
const WATCHDOG_INTERVAL: Duration = Duration::from_secs(2);
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

/// #497: how long `codesign` gets to answer before the launch is refused.
///
/// Intact-bundle verification was measured at **0.42 s**, so this is ~35x
/// headroom: no healthy machine reaches it. A launch that does trip it has a
/// real problem — a stalled network mount, an unresponsive FUSE volume, an
/// external disk spinning up, or a `syspolicyd`/Gatekeeper stall (XProtect
/// scan, translocation, notary-ticket lookup) — because `codesign` is I/O
/// bound on every sealed resource it hashes.
/// `#[allow(dead_code)]`: read only by the macOS verifiers. Kept unconditional
/// rather than `cfg`-gated so the budget and its rationale stay in one place
/// with the other lifecycle deadlines, next to `PS_BUDGET`, which every unix
/// build does use.
#[allow(dead_code)]
const CODESIGN_BUDGET: Duration = Duration::from_secs(15);

/// #497: how long the `ps` state read gets on the shutdown ladder.
///
/// Two orders of magnitude tighter than [`CODESIGN_BUDGET`] because it sits
/// INSIDE the timeout mechanism: an unbounded read here defeats
/// [`FORCE_AFTER_MS`] and [`REAP_BUDGET_MS`], which is a hole in the very
/// thing that bounds shutdown. A single `ps -o state=` answers in single-digit
/// milliseconds or it is not going to.
const PS_BUDGET: Duration = Duration::from_millis(500);

/// Poll granularity for [`output_within`]. Matches `wait_exit`'s.
const SUBPROCESS_POLL_INTERVAL: Duration = Duration::from_millis(25);

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
                // #443: from this point nothing used to wait on, poll or
                // re-probe the child EVER AGAIN. Kill the server and the
                // supervisor stayed up, logged nothing, left a zombie, and
                // pointed its WebView at a dead port — a connection-refused
                // page inside the application with no explanation anywhere.
                spawn_child_watchdog(
                    handle.clone(),
                    recorder.clone(),
                    shared_slot.clone(),
                    format!("{}/logs/desktop-child.log", plan.data_root),
                );
                0
            }
        }
        Err(reason) => {
            let _ = recorder.record("lifecycle-failed", json!({"reason": reason}));
            // #425: tell the operator, on screen, before anything else. Smoke
            // runs are headless conformance gates with no one watching, and
            // they exit immediately after this — showing a page there would be
            // dead code that the m6 fault matrix would have to tolerate.
            if !smoke {
                let log_path = format!("{}/logs/desktop-child.log", plan.data_root);
                show_failure(handle, reason, &log_path);
                let _ = recorder.record("failure-shown", json!({"reason": reason}));
            }
            if let Some(orphan) = control.take() {
                // The fault-cleanup arm: record the outcome so the m6 fault
                // matrix can assert bounded reaping, not just failure.
                let code = shutdown_child(orphan);
                let _ = recorder.record("orphan-shutdown", json!({"child_exit": code}));
            }
            1
        }
    }
}

/// #443: notice when the server dies, and say so.
///
/// The non-smoke path hands the child to `RunEvent::Exit` and returns, so
/// without this nothing observes the child for the rest of the process
/// lifetime. `try_wait` both detects the exit and reaps it, which also clears
/// the zombie the chaos run measured.
///
/// Deliberately does NOT restart the child. A crash loop that silently
/// re-launches is harder to diagnose than one that stops and explains itself,
/// and #425 gave this process somewhere to put the explanation. Restart, if
/// it is ever wanted, should be an operator-visible action rather than a
/// hidden one.
fn spawn_child_watchdog(
    handle: tauri::AppHandle,
    recorder: Recorder,
    slot: Arc<Mutex<Option<ChildControl>>>,
    log_path: String,
) {
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(WATCHDOG_INTERVAL);
            let exited = {
                let Ok(mut guard) = slot.lock() else {
                    return;
                };
                // Taken by the shutdown path: a normal quit is in progress and
                // this thread has nothing left to watch.
                let Some(control) = guard.as_mut() else {
                    return;
                };
                match control.child.try_wait() {
                    Ok(Some(status)) => {
                        // Drop the reaped control so RunEvent::Exit does not
                        // later run the ladder against a dead pid.
                        let _ = guard.take();
                        Some(status.code().map_or(-1, i64::from))
                    }
                    Ok(None) => None,
                    // try_wait failing means the handle is unusable; there is
                    // nothing further this thread can observe.
                    Err(_) => return,
                }
            };
            // The lock is released before touching the UI: `show_failure`
            // hops to the main thread, and holding the child mutex across
            // that would put this thread in the way of a concurrent quit.
            if let Some(code) = exited {
                let _ = recorder.record("child-exited", json!({"code": code}));
                show_failure(
                    &handle,
                    "The arXMCP server stopped unexpectedly.",
                    &log_path,
                );
                return;
            }
        }
    });
}

fn cycle(
    handle: &tauri::AppHandle,
    plan: &Plan,
    recorder: &Recorder,
    control: &mut Option<ChildControl>,
    _smoke: bool,
) -> Result<(), &'static str> {
    // #435: this digest is a SELF-CONSISTENCY check, and calling it anything
    // stronger was the defect. It hashes `plan.identity_file` and later
    // compares against the identity the child REPORTS about itself — but in
    // the self-authored plan `identity_file == child_argv[0]`, so both sides
    // read the same bytes. Tamper with the child and the hash and the report
    // move together and it still matches. It cannot detect tampering and
    // never could; what it DOES establish is that the process which answered
    // the handshake is the file this supervisor launched, and that the child
    // agrees about which component and version it is — a real property, and a
    // smaller one than the name suggested.
    //
    // The integrity check with an independent reference is the code-signature
    // verification below (#436), whose reference lives in the signature blob
    // rather than in the bytes being checked.
    let digest = file_sha256(&plan.identity_file)?;
    let token = generate_startup_token().map_err(|_| "startup token generation failed")?;
    let expected_identity = ExecutableIdentity {
        component: plan.component.clone(),
        sha256: digest,
        version: plan.version.clone(),
    };
    // The wire contract's sanctioned compatible-addition channel: the fault
    // switch rides a namespaced extension read ONLY by the fixture sidecar.
    // The production child never inspects extensions, so no contract bump.
    let mut extensions = Extensions::new();
    if let Some(fault) = &plan.test_fault {
        extensions.insert(
            "org.arxmcp.test-fault".to_owned(),
            Value::String(fault.clone()),
        );
    }
    let launch = Launch {
        contract: ContractVersion { major: 1, minor: 0 },
        data_root: plan.data_root.clone(),
        endpoint_request: Endpoint {
            host: "127.0.0.1".to_owned(),
            port: 0,
        },
        executable: expected_identity.clone(),
        extensions,
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
    // #488: 0600, not whatever the umask says. Both the mode-at-create and
    // the explicit set_permissions matter — mode() applies only when the file
    // is CREATED, so a log left at 0644 by an earlier version would otherwise
    // keep its permissions forever.
    let log_file = open_private_log(&log_path)?;

    // #436: consult the seal before exec, in SHIPPED builds only. A debug
    // build drives the unsigned fixture sidecar through the m6 fault matrix,
    // and #427 already established that release has exactly one arm — the
    // self-authored one, which always resolves the frozen, signed child. So
    // gating on the profile means the artifact an operator runs always
    // verifies, and the harness keeps working. `verify_signature` itself is
    // compiled in both profiles and unit-tested directly.
    #[cfg(not(debug_assertions))]
    {
        let child_path = std::path::Path::new(&plan.child_argv[0]);
        // #497: a timeout REFUSES the launch, and says so in its own words.
        // Failing open would make the seal bypassable by anyone who can stall
        // `codesign`, which is a weaker guarantee than the one #436 closed.
        match verify_signature(child_path) {
            Ok(()) => {}
            Err(VerifyError::TimedOut { budget_ms }) => {
                let _ = recorder.record("child-signature-timeout", json!({"budget_ms": budget_ms}));
                return Err("child signature check timed out");
            }
            Err(VerifyError::Rejected(detail)) => {
                let _ = recorder.record("child-signature-invalid", json!({"detail": detail}));
                return Err("child code signature invalid");
            }
        }
        // #436/#484: the executable is a PyInstaller LAUNCHER. Consult the
        // outer seal too, which covers the `_internal/` runtime it will load
        // — the part that check verifies nothing about.
        match enclosing_app_bundle(child_path) {
            Some(app) => match verify_bundle_seal(&app) {
                Ok(()) => {}
                Err(VerifyError::TimedOut { budget_ms }) => {
                    let _ = recorder.record(
                        "payload-seal-timeout",
                        json!({"budget_ms": budget_ms, "bundle": app.to_string_lossy()}),
                    );
                    return Err("child payload seal check timed out");
                }
                Err(VerifyError::Rejected(detail)) => {
                    let _ = recorder.record(
                        "payload-seal-invalid",
                        json!({"detail": detail, "bundle": app.to_string_lossy()}),
                    );
                    return Err("child payload seal invalid");
                }
            },
            None => {
                // The onedir layout: no bundle, so no seal to consult. Record
                // it rather than passing silently — "not checked" and
                // "checked and clean" must not read alike in the event log.
                let _ = recorder.record(
                    "payload-seal-unavailable",
                    json!({"reason": "child is not inside an .app bundle"}),
                );
            }
        }
    }

    let mut command = Command::new(&plan.child_argv[0]);
    command
        .args(&plan.child_argv[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        // #438: the child's stderr fd used to be wired STRAIGHT to the file,
        // so nothing in this process ever saw those bytes and no scrubber
        // could run on them. apps/desktop/README.md claimed unconditionally
        // that the startup token is never a "stdout/stderr diagnostic, or
        // persisted manifest/log artifact"; it was measured in the log
        // verbatim. redact.rs conceded the sink was "defended independently
        // by the Python RedactionFilter" — which defends nothing against a
        // child that is not the cooperating Python one, and nothing against
        // the real child's non-logging writes either (a raw "Fatal Python
        // error:" block goes to fd 2 with logging bypassed entirely, #468).
        // Pipe it instead and relay through the scrubber.
        .stderr(Stdio::piped());
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
    // #438: relay stderr -> scrubber -> log. Started immediately so nothing
    // the child writes during startup can bypass it.
    if let Some(stderr) = child.stderr.take() {
        spawn_stderr_relay(stderr, log_file, token.clone());
    }

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
        // Test-only budget shrink: the WIRE frame above keeps the contract
        // floor (MIN_GRACE_MS); only this process's local waits change, so
        // the escalation ladder runs at test speed without a contract bump.
        grace_ms: plan.test_shutdown_grace_ms.unwrap_or(MIN_GRACE_MS),
        force_after_ms: plan.test_shutdown_force_after_ms.unwrap_or(FORCE_AFTER_MS),
    });

    let bound_timeout = plan
        .test_bound_timeout_ms
        .map_or(BOUND_TIMEOUT, Duration::from_millis);
    let bound = await_bound(stdout, recorder, &token, bound_timeout, Some(handle))?;
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
    let _ = recorder.record("window-ready", json!({"window_ordered_in": true}));
    Ok(())
}

/// Read exactly one `bound` frame; a background drain then flags any
/// further stdout bytes (child stdout is control-only after `bound`).
/// An unparseable frame persists a SCRUBBED prefix for post-mortem value —
/// a misbehaving child echoing its launch frame is exactly how the startup
/// capability could reach this diagnostic, so scrub runs before persist and
/// before truncation (a boundary cut must not leave a partial secret).
fn await_bound(
    stdout: std::process::ChildStdout,
    recorder: &Recorder,
    token: &StartupToken,
    timeout: Duration,
    handle: Option<&tauri::AppHandle>,
) -> Result<Bound, &'static str> {
    let (sender, receiver) = mpsc::channel();
    let drain_recorder = recorder.clone();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let first = read_frame(&mut reader);
        let _ = sender.send(first);
        // #486: the drain had no byte cap and no deadline — it exited only on
        // EOF or a read error, so a child that streams indefinitely kept this
        // thread and the pipe alive for the life of the supervisor, burning
        // CPU on entirely child-controlled input. Child stdout is CONTROL-ONLY
        // after `bound`; anything arriving here is already a contract
        // violation, and counting it past a point proves nothing more.
        const DRAIN_CAP_BYTES: usize = 64 * 1024;
        let mut remainder = [0_u8; 1_024];
        let mut extra = 0_usize;
        let mut capped = false;
        while let Ok(count) = reader.read(&mut remainder) {
            if count == 0 {
                break;
            }
            extra += count;
            if extra >= DRAIN_CAP_BYTES {
                capped = true;
                break;
            }
        }
        if extra > 0 {
            let _ = drain_recorder.record(
                "unexpected-stdout",
                json!({"bytes": extra, "capped": capped}),
            );
        }
    });
    // #442: wait in slices instead of one opaque block. Same deadline, same
    // outcome — but the event log now shows progress, and past
    // FIRST_RUN_NOTICE the window stops claiming "starting…" and says why it
    // is slow. Before this the operator saw a frozen static page for up to
    // four minutes with no way to tell a warm-up from a wedge.
    let started = Instant::now();
    let deadline = started + timeout;
    let mut explained = false;
    let received = loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err("bound frame timeout");
        }
        match receiver.recv_timeout(remaining.min(BOUND_PROGRESS_INTERVAL)) {
            Ok(result) => break result,
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // Don't announce progress at the instant the deadline expires:
                // the next loop turn returns the timeout error, and a
                // "still waiting" line stamped the same millisecond as
                // `lifecycle-failed` reads like a contradiction in the log.
                if Instant::now() >= deadline {
                    return Err("bound frame timeout");
                }
                let waited = started.elapsed();
                let _ =
                    recorder.record("waiting-for-bound", json!({"elapsed_s": waited.as_secs()}));
                if !explained && waited >= FIRST_RUN_NOTICE {
                    explained = true;
                    if let Some(handle) = handle {
                        show_slow_start(handle);
                    }
                }
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err("child stdout closed before bound")
            }
        }
    };
    let frame = received
        .map_err(|_| "bound frame read failed")?
        .ok_or("child stdout closed before bound")?;
    match parse_frame(&frame) {
        Ok(Frame::Bound(bound)) => Ok(bound),
        Ok(_) => Err("first control frame was not bound"),
        Err(_) => {
            // #439: scrub_child_text, NOT scrub. The frame is bytes the CHILD
            // chose, so exact matching misses an uppercase copy or a
            // truncated prefix — both measured surviving into this very
            // diagnostic, from which `tr A-F a-f` recovered the capability.
            let scrubbed =
                redact::scrub_child_text(&String::from_utf8_lossy(&frame), token.expose());
            // #487: `frame_prefix` is the ONE event field carrying raw
            // child-chosen bytes, and NUL and control characters were landing
            // in the log verbatim. JSON encoding keeps the file parseable, so
            // this is log-injection hygiene rather than corruption — but
            // redact.rs's own module doc concedes the surrounding discipline
            // is call-site-only with "nothing structural enforces that yet",
            // and #439 is the case where relying on one scrub call
            // demonstrably failed on this exact field. Restrict the charset
            // rather than add a second thing to remember.
            let prefix: String = printable_ascii(&scrubbed).chars().take(256).collect();
            let _ = recorder.record("bound-frame-invalid", json!({"frame_prefix": prefix}));
            Err("bound frame invalid")
        }
    }
}

/// Restrict child-chosen text to printable ASCII (issue #487).
///
/// Anything outside `0x20..=0x7E` (plus tab) becomes `\xNN`, so a NUL, an
/// escape sequence or a stray newline cannot alter how the persisted event
/// line reads. Lossy on purpose: this is a diagnostic prefix, and being able
/// to trust what it says matters more than reproducing every byte.
fn printable_ascii(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for ch in input.chars() {
        if ch == '\t' || (' '..='~').contains(&ch) {
            out.push(ch);
        } else {
            for byte in ch.to_string().as_bytes() {
                out.push_str(&format!("\\x{byte:02X}"));
            }
        }
    }
    out
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
///
/// Ok attests ONE axis and no more: the toolkit reported the native window
/// ORDERED IN — on macOS a bare `NSWindow.isVisible` (tao 0.35
/// `platform_impl/macos/window.rs`). That is a real observation because it
/// discriminates: measured `false` for a `.visible(false)` build and `true`
/// for the default one, where `navigate` succeeding proves only that Tauri's
/// registry has an entry (issue #423). It does NOT establish that the window
/// is unoccluded, on-screen, non-zero-sized, on the active Space, or that the
/// WebView rendered — AppKit reports `isVisible` true for a window fully
/// covered by another. `window-ready` is emitted only on this path and names
/// exactly that axis (`window_ordered_in`), never a bare "visible".
fn navigate_window(handle: &tauri::AppHandle, bound: &Bound) -> Result<(), &'static str> {
    let url = tauri::Url::parse(&bound.ui_url).map_err(|_| "bound ui_url unparseable")?;
    let (sender, receiver) = mpsc::channel();
    let main_handle = handle.clone();
    handle
        .run_on_main_thread(move || {
            let result = main_handle
                .get_webview_window("main")
                .ok_or("main window missing")
                .and_then(|window| {
                    window.navigate(url).map_err(|_| "window navigate failed")?;
                    match window.is_visible() {
                        Ok(true) => Ok(()),
                        Ok(false) => Err("window not visible after navigate"),
                        Err(_) => Err("window visibility unobservable"),
                    }
                });
            let _ = sender.send(result);
        })
        .map_err(|_| "main-thread dispatch failed")?;
    receiver
        .recv_timeout(Duration::from_secs(10))
        .map_err(|_| "window navigate timeout")?
}

/// Verify a Mach-O's own code signature (#436). macOS only.
///
/// **What this catches, measured 2026-08-22:** flipping one byte in the signed
/// child makes `codesign --verify --strict` exit 1 with
/// `invalid signature (code or signature have been modified)`. Before this,
/// nothing ran `codesign` at launch, so that tampered binary executed
/// normally — the seal was real and simply never consulted.
///
/// **What it does NOT catch, also measured:** the payload is ad-hoc signed,
/// so `codesign --force --sign -` re-signs a tampered binary and verification
/// passes again (exit 0). An attacker who can WRITE to the payload can
/// therefore defeat this. That is not a gap this function can close: with no
/// Developer ID there is no identity to pin, and
/// `apps/desktop/README.md` already records that write access to the payload
/// directory is equivalent to arbitrary code execution as the operator.
/// Closing it is e4's release-signing work, after which this call can pin a
/// Designated Requirement instead of accepting any signature.
///
/// So the honest scope is: **corruption and casual tampering** — a truncated
/// copy, a failed update, a bad disk, an edited binary — none of which
/// re-sign themselves. That is worth catching before exec, and it is exactly
/// the case #436 reproduced.
/// **A timeout refuses the launch (#497).** Bounded by [`CODESIGN_BUDGET`];
/// exhausting it is a verification failure, not permission to proceed. The
/// reasoning is written out in full on [`verify_bundle_seal`]. Recorded as
/// `child-signature-timeout`, never as `child-signature-invalid` — a stalled
/// mount and a tampered binary are different operator problems.
///
/// `#[allow(dead_code)]`: the only call site is release-gated, so a debug
/// build sees this as unused. It stays compiled in BOTH profiles on purpose —
/// the unit tests below exercise the real verifier against a real signed
/// binary, which they could not do if the release-only shape were the only
/// one that existed.
/// Why a verification failed. #497.
///
/// The two arms are different operator problems with different fixes, and
/// collapsing them into one string is the mistake #444 already corrected once
/// for the child log. "The signature is invalid" means a corrupt or tampered
/// payload; "we could not check in time" means a stalled mount or a wedged
/// `syspolicyd`. Both refuse the launch — see [`verify_signature`] on why a
/// timeout fails CLOSED — but they must not render alike.
/// `#[allow(dead_code)]`: both variants are constructed only by the macOS
/// `codesign_verify`. A non-macOS build compiles the type (the stub verifiers
/// return `Result<(), VerifyError>` so the signature is one shape everywhere)
/// without ever building one. Same reason as [`CODESIGN_BUDGET`] below.
#[allow(dead_code)]
#[derive(Debug, PartialEq, Eq)]
pub enum VerifyError {
    /// `codesign` answered, and the answer was no — or it could not be run at
    /// all. Both are "this payload is not what it should be" and both already
    /// failed closed before #497; they stay folded together.
    Rejected(String),
    /// `codesign` did not answer within its budget.
    TimedOut { budget_ms: u64 },
}

/// Why a bounded subprocess did not produce output. #497.
#[allow(dead_code)]
#[derive(Debug)]
enum RunFailure {
    /// The process could not be started.
    Spawn(String),
    /// It started but did not finish inside the budget, or its state could not
    /// be established. Both mean the same thing to a caller: no answer.
    TimedOut,
}

/// Run a command to completion, or kill it and report a timeout. #497.
///
/// `Command::output()` blocks until the child exits AND both pipes reach EOF,
/// with no deadline whatsoever. That is the defect this closes: three call
/// sites used it, two of them before `exec` on the launch path, where a hang
/// means no child, no window and no dialog — the invisible cold-start failure
/// #444 exists to prevent, reintroduced through a different cause.
///
/// **The pipes are drained on threads, deliberately.** The obvious shape — a
/// `try_wait()` poll loop over a piped child — deadlocks the moment the child
/// fills a 64 KiB pipe buffer nobody is reading: it blocks on write, never
/// exits, and the poll loop runs to its deadline against a child that was
/// merely chatty. `spawn_stderr_relay` documents the same trap from the other
/// side. `codesign` is not chatty, but a bounded helper that is only correct
/// for quiet children is a trap for its next caller.
///
/// A timed-out child is killed AND reaped. Leaving it would leak a process per
/// launch attempt against whatever stalled it in the first place.
#[allow(dead_code)]
fn output_within(
    command: &mut Command,
    budget: Duration,
) -> Result<std::process::Output, RunFailure> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    // Its own process group, so the timeout path can kill a GRANDCHILD too --
    // see `process_control::force_kill_group` for what that costs when it is
    // missing. It also stops these helpers receiving terminal signals aimed
    // at the supervisor.
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command
        .spawn()
        .map_err(|err| RunFailure::Spawn(err.to_string()))?;

    let mut out_pipe = child.stdout.take();
    let mut err_pipe = child.stderr.take();
    let drain_out = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(pipe) = out_pipe.as_mut() {
            let _ = pipe.read_to_end(&mut buf);
        }
        buf
    });
    let drain_err = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(pipe) = err_pipe.as_mut() {
            let _ = pipe.read_to_end(&mut buf);
        }
        buf
    });

    let deadline = Instant::now() + budget;
    let finished = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            // A `try_wait` error is "we cannot establish that it finished",
            // which is the same situation for a caller as a timeout.
            Err(_) => break None,
            Ok(None) => {}
        }
        if Instant::now() >= deadline {
            break None;
        }
        std::thread::sleep(SUBPROCESS_POLL_INTERVAL);
    };

    let Some(status) = finished else {
        // The GROUP, not just the child: a grandchild holding the inherited
        // pipes keeps the drains from ever seeing EOF, and joining them would
        // block for as long as it lives. Then the direct child is killed and
        // reaped regardless, so nothing is left for the OS to collect.
        process_control::force_kill_group(child.id());
        let _ = child.kill();
        let _ = child.wait();
        // With the group gone the pipes are closed, so both drains hit EOF.
        // Joined rather than detached so no thread outlives the call.
        let _ = drain_out.join();
        let _ = drain_err.join();
        return Err(RunFailure::TimedOut);
    };

    Ok(std::process::Output {
        status,
        stdout: drain_out.join().unwrap_or_default(),
        stderr: drain_err.join().unwrap_or_default(),
    })
}

/// One bounded `codesign --verify` invocation. #497.
///
/// `tool` is a parameter only so the tests can drive the TIMEOUT arm against a
/// stand-in that is guaranteed to hang; every production caller passes the
/// absolute [`CODESIGN`]. It is deliberately NOT an env override — the whole
/// point of that constant is that nothing the environment controls gets to
/// answer this question.
#[cfg(target_os = "macos")]
fn codesign_verify(
    tool: &str,
    budget: Duration,
    args: &[&std::ffi::OsStr],
) -> Result<(), VerifyError> {
    let mut command = Command::new(tool);
    command.args(args);
    let output = match output_within(&mut command, budget) {
        Ok(output) => output,
        Err(RunFailure::Spawn(err)) => {
            return Err(VerifyError::Rejected(format!(
                "codesign could not be run: {err}"
            )))
        }
        Err(RunFailure::TimedOut) => {
            return Err(VerifyError::TimedOut {
                budget_ms: u64::try_from(budget.as_millis()).unwrap_or(u64::MAX),
            })
        }
    };
    if output.status.success() {
        return Ok(());
    }
    // codesign writes its reason to stderr; keep the first line, which names
    // the failure ("invalid signature (code or signature have been
    // modified)") without the architecture trailer.
    let stderr = String::from_utf8_lossy(&output.stderr);
    let reason = stderr.lines().next().unwrap_or("unspecified").trim();
    Err(VerifyError::Rejected(reason.to_owned()))
}

/// Absolute on purpose: a PATH lookup would let a planted `codesign` earlier
/// on PATH answer this question. Verified present at this path on macOS 26.6;
/// it is NOT `/usr/sbin/codesign`, which is where the first draft looked.
#[cfg(target_os = "macos")]
const CODESIGN: &str = "/usr/bin/codesign";

#[allow(dead_code)]
#[cfg(target_os = "macos")]
pub fn verify_signature(path: &std::path::Path) -> Result<(), VerifyError> {
    codesign_verify(
        CODESIGN,
        CODESIGN_BUDGET,
        &[
            std::ffi::OsStr::new("--verify"),
            std::ffi::OsStr::new("--strict"),
            path.as_os_str(),
        ],
    )
}

/// Non-macOS builds have no equivalent seal to consult. Returning Ok is the
/// honest answer — "not checked here" — and `verify_signature`'s only caller
/// is macOS-shaped anyway. The Windows track (#419-#422) owns its own
/// integrity story.
#[allow(dead_code)]
#[cfg(not(target_os = "macos"))]
pub fn verify_signature(_path: &std::path::Path) -> Result<(), VerifyError> {
    Ok(())
}

/// The `.app` that encloses this child executable, when there is one.
///
/// The bundled payload sits at
/// `<name>.app/Contents/Resources/arxmcp-desktop-child/arxmcp-desktop-child`
/// (m15 ADR Decision 2a), so the bundle root is four levels up — but only
/// when the intervening components are exactly `Resources` and `Contents` and
/// the root ends in `.app`. Anything else is the m7 onedir layout, which has
/// no bundle and therefore no seal to consult.
///
/// Derived from the child path rather than threaded through the launch plan
/// on purpose: the plan is a WIRE CONTRACT with a fixed schema, its own
/// probe output and a fault matrix built around it. A new field there is a
/// far larger change than reading four path components here, and the two
/// would have to agree anyway.
/// `#[allow(dead_code)]` for the same reason as [`verify_signature`]: the
/// only call site is release-gated, so a debug build sees no caller.
#[allow(dead_code)]
fn enclosing_app_bundle(child_exe: &std::path::Path) -> Option<std::path::PathBuf> {
    let payload_dir = child_exe.parent()?;
    let resources = payload_dir.parent()?;
    if resources.file_name()? != "Resources" {
        return None;
    }
    let contents = resources.parent()?;
    if contents.file_name()? != "Contents" {
        return None;
    }
    let app = contents.parent()?;
    if app.extension()? != "app" {
        return None;
    }
    Some(app.to_path_buf())
}

/// Ask the OUTER bundle's seal about the whole payload (issues #436, #484).
///
/// [`verify_signature`] validates one Mach-O: the executable about to be
/// exec'd. That is not the payload. The child is a PyInstaller **onedir**, so
/// the executable is a launcher and the actual runtime — `libpython3.12.dylib`,
/// every extension module, every data file — lives beside it in `_internal/`.
/// An external review deleted `_internal/libpython3.12.dylib` from a copy of
/// the assembled bundle and both of this crate's checks passed, while the
/// bundle's own seal reported the tamper.
///
/// The payload is sealed as RESOURCES of the outer bundle
/// (`Contents/_CodeSignature/CodeResources`), which is why one check covers
/// files this crate never enumerates — including files an attacker ADDS,
/// which no manifest of expected names can catch. Measured on the assembled
/// artifact, three mutations against a clone:
///
/// | mutation | `verify` child exe | `verify` bundle |
/// |---|---|---|
/// | delete `_internal/libpython3.12.dylib` | **passes** | fails |
/// | flip one byte in a payload `.so` | **passes** | fails |
/// | add `_internal/evil.dylib` | **passes** | fails |
///
/// Plain `--verify`, deliberately: `--strict` and `--deep` were measured at
/// ~0.6 s against ~0.3 s and detected nothing further HERE, because sealed
/// resources are covered by hash either way and `--deep` recurses into nested
/// CODE this layout does not have. (The ADR's ban on `--deep` is about
/// SIGNING; verification is a different operation. It is simply not needed.)
///
/// ~0.3 s on the launch path is the cost. That buys the difference between
/// "the file we exec is intact" and "the payload it will load is intact".
///
/// **A timeout refuses the launch (#497).** `codesign` is bounded by
/// [`CODESIGN_BUDGET`], and exhausting it is treated as a verification
/// failure, not as permission to proceed. Failing open would make this seal
/// bypassable by anyone who can stall `codesign` — which is exactly the
/// property #436 and #484 exist to provide, given away to whoever can arrange
/// slow I/O. An integrity check that can be skipped by stalling it is not an
/// integrity check. The accepted cost is that a machine where `codesign` is
/// reliably slow is a machine where the app refuses to start; that cost is
/// bounded by a budget no healthy machine reaches (0.42 s measured, 15 s
/// allowed). The refusal is recorded as `payload-seal-timeout`, never as
/// `payload-seal-invalid`.
///
/// **Bound honestly:** this consults an AD-HOC seal, which anyone can
/// re-create over modified bytes. It detects tampering, not a determined
/// attacker, and says nothing about Apple's notary — ADR Decision 3, still
/// open. It is also unavailable in the onedir layout, which has no bundle;
/// there the caller falls back to the executable check alone.
#[allow(dead_code)]
#[cfg(target_os = "macos")]
pub fn verify_bundle_seal(app: &std::path::Path) -> Result<(), VerifyError> {
    codesign_verify(
        CODESIGN,
        CODESIGN_BUDGET,
        &[std::ffi::OsStr::new("--verify"), app.as_os_str()],
    )
}

/// Non-macOS builds have no bundle seal to consult: `codesign` is a macOS
/// tool and `CODESIGN` is `#[cfg(target_os = "macos")]`, so the real verifier
/// above cannot compile elsewhere. This stub keeps the SHARED supervisor
/// buildable on Linux/Windows; it deliberately mirrors the non-macOS
/// [`verify_signature`] and returns Ok — "not checked here". The Windows
/// track (#419-#422) owns its own integrity story.
///
/// The launch-path caller is gated on `not(debug_assertions)`, not on OS, so
/// this arm IS reachable in a non-macOS release build. It must therefore be a
/// real function rather than a `compile_error!`.
#[allow(dead_code)]
#[cfg(not(target_os = "macos"))]
pub fn verify_bundle_seal(_app: &std::path::Path) -> Result<(), VerifyError> {
    Ok(())
}

/// Percent-encode for a `data:` URL body. Conservative on purpose: everything
/// outside the unreserved set is escaped, so no operator-controlled byte in a
/// filesystem path can terminate the URL or introduce a new attribute.
fn percent_encode(input: &str) -> String {
    let mut out = String::with_capacity(input.len() * 3);
    for byte in input.as_bytes() {
        let c = *byte as char;
        if c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '~') {
            out.push(c);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

/// Escape for HTML text content. The reason is one of this crate's own
/// `&'static str`s, but the log path is derived from the plan's `data_root`
/// and is therefore operator-controlled.
fn html_escape(input: &str) -> String {
    input
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

/// #444: the last few lines the child wrote before it died.
///
/// The supervisor's own reason for a pre-bound failure is structural — "child
/// stdout closed before bound" — and says nothing about WHY. The child's own
/// message is specific, actionable and already well worded, and it was
/// sitting in a log file the operator would never find. The measured case was
/// a cold-start corpus refusal that named its own remedy.
///
/// Bounded read from the END of the file: a child that spewed megabytes must
/// not be read into memory to show the last line of it. The bytes have
/// already passed through the #438 stderr relay, so they are scrubbed; the
/// extra `redact_hex_runs` pass here costs nothing and means this display
/// path does not depend on that being true elsewhere.
fn child_log_tail(path: &std::path::Path, max_lines: usize) -> Option<String> {
    const WINDOW: u64 = 8 * 1024;
    let mut file = std::fs::File::open(path).ok()?;
    let len = file.metadata().ok()?.len();
    let start = len.saturating_sub(WINDOW);
    file.seek(std::io::SeekFrom::Start(start)).ok()?;
    let mut bytes = Vec::new();
    file.take(WINDOW).read_to_end(&mut bytes).ok()?;
    let text = String::from_utf8_lossy(&bytes);
    let lines: Vec<&str> = text
        .lines()
        // A partial first line when the window cut mid-line.
        .skip(usize::from(start > 0))
        .collect();
    // #444 round 2: only THIS launch's lines. The boundary is written by
    // `open_private_log` before the child can produce anything, so a failure
    // that happens before the child speaks finds nothing after it and this
    // returns None — the failure page then shows the supervisor's reason with
    // no "The server reported:" block, rather than quoting the last run.
    //
    // Absent from the window means this launch already wrote 8 KiB, so
    // everything in the window is still this launch's. (A log written by a
    // build that predates the boundary has none at all; there the old
    // whole-window behaviour stands, once, until the next launch.)
    let after_banner = lines
        .iter()
        .rposition(|line| line.starts_with(LAUNCH_BANNER))
        .map_or(0, |index| index + 1);
    let tail: Vec<&str> = lines[after_banner..]
        .iter()
        .copied()
        .filter(|line| !line.trim().is_empty())
        .collect();
    if tail.is_empty() {
        return None;
    }
    let from = tail.len().saturating_sub(max_lines);
    Some(redact::scrub_child_text(&tail[from..].join("\n"), ""))
}

/// Issue #442: replace "starting…" with an explanation once the wait is long
/// enough to look like a hang.
///
/// The first run loads BGE-M3 from a cold cache, which is genuinely slow, and
/// the measured failure was not the duration — it was that a warm-up and a
/// wedged child looked identical for up to four minutes. Same best-effort
/// contract as `show_failure`: every step discards its error.
pub fn show_slow_start(handle: &tauri::AppHandle) {
    let body = "<!doctype html><meta charset=\"utf-8\"><title>arXMCP is starting</title>\
        <style>body{font:14px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;\
        margin:0;padding:2.5rem;background:#161e20;color:#e0e8e8}\
        h1{font-size:1.3rem;margin:0 0 .75rem}p{margin:0 0 1rem;max-width:64ch}\
        .m{color:#8b9e9f}</style>\
        <h1>arXMCP is still starting</h1>\
        <p>The first launch loads the retrieval model, which can take several \
        minutes on a cold cache. Later launches are much faster.</p>\
        <p class=\"m\">If this window does not change within a few more minutes, \
        arXMCP will stop on its own and tell you why.</p>";
    let Ok(url) = tauri::Url::parse(&format!(
        "data:text/html;charset=utf-8,{}",
        percent_encode(body)
    )) else {
        return;
    };
    let main_handle = handle.clone();
    let _ = handle.run_on_main_thread(move || {
        if let Some(window) = main_handle.get_webview_window("main") {
            let _ = window.navigate(url);
        }
    });
}

/// Issue #425: put a launch failure on screen.
///
/// Before this, every failure path was `eprintln!` plus an exit. Under
/// LaunchServices a double-clicked application's stderr goes nowhere the
/// operator will ever look, so the measured experience was: no dialog, no
/// message, `open` exits 0, and the process gone in five to seven seconds.
/// The only trace was an NDJSON file the next launch truncated (#464).
///
/// The window already exists — `main.rs`'s setup builds it showing
/// "arXMCP is starting…" — so the fix is to navigate that same window to an
/// explanation rather than to invent a dialog. Best effort by construction:
/// a failure to SHOW the failure must never mask the original one, so every
/// step here discards its error and the caller's return value is unchanged.
pub fn show_failure(handle: &tauri::AppHandle, reason: &str, log_path: &str) {
    // #444: the child's own last words, when it left any. Without this the
    // page shows only the supervisor's structural reason, which names the
    // symptom and never the cause.
    let tail = child_log_tail(std::path::Path::new(log_path), 12);
    let detail = match &tail {
        Some(text) => format!(
            "<p>The server reported:</p><pre>{}</pre>",
            html_escape(text)
        ),
        None => String::new(),
    };
    let body = format!(
        "<!doctype html><meta charset=\"utf-8\"><title>arXMCP could not start</title>\
         <style>body{{font:14px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;\
         margin:0;padding:2.5rem;background:#161e20;color:#e0e8e8}}\
         h1{{font-size:1.3rem;margin:0 0 .75rem}}code{{font:12px/1.5 ui-monospace,monospace;\
         background:#0f1516;padding:.15rem .35rem;border-radius:3px;word-break:break-all}}\
         p{{margin:0 0 1rem;max-width:64ch}}.r{{color:#fda29b}}\
         pre{{background:#0f1516;padding:.75rem;border-radius:3px;overflow-x:auto;\
         font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap;max-width:80ch}}</style>\
         <h1>arXMCP could not start</h1>\
         <p class=\"r\">{reason}</p>\
         {detail}\
         <p>The full log for this launch is at:</p><p><code>{log}</code></p>\
         <p>That file keeps the last two launches, so it is safe to try \
         again before reporting this.</p>",
        reason = html_escape(reason),
        detail = detail,
        log = html_escape(log_path),
    );
    let Ok(url) = tauri::Url::parse(&format!(
        "data:text/html;charset=utf-8,{}",
        percent_encode(&body)
    )) else {
        return;
    };
    let main_handle = handle.clone();
    let _ = handle.run_on_main_thread(move || {
        if let Some(window) = main_handle.get_webview_window("main") {
            let _ = window.navigate(url);
            let _ = window.set_focus();
        }
    });
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
    // #442: a STOPPED child cannot be shut down cooperatively, and the
    // measured cost of pretending otherwise was 35.8s on top of a 240s bound
    // timeout — 281s of a frozen window.
    //
    // The discriminator is deliberately "stopped", NOT "never bound". A first
    // attempt used the latter and the m6 fault matrix rejected it, correctly:
    // its startup-timeout arm is a *parked but cooperating* child that never
    // emits `bound` and still honours the shutdown frame with a clean exit 0,
    // and its malformed-bound arm is alive enough to have spoken badly. Both
    // deserve the grace. A SIGSTOP'd process is the one that provably cannot
    // use it: it cannot observe stdin EOF, cannot act on the shutdown frame,
    // and does not even receive SIGTERM until it continues. SIGKILL is the
    // only signal that lands, so go straight to it.
    if is_stopped(control.child.id()) {
        let _ = control.child.kill();
        return wait_exit(&mut control.child, REAP_BUDGET_MS).unwrap_or(-1);
    }
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

/// #442: is this pid stopped (SIGSTOP'd)?
///
/// `ps` rather than a syscall because this crate has no `libc` dependency,
/// and because `ps` is already a hard binary prerequisite of the m6
/// cleanup-evidence probes. Absolute path: a planted `ps` earlier on PATH
/// must not be able to answer this. Any failure to determine the state
/// returns false — the SAFE default, which keeps the full cooperative ladder
/// rather than force-killing a healthy server on a bad reading.
#[cfg(unix)]
fn is_stopped(pid: u32) -> bool {
    // #497: bounded. This sits INSIDE the shutdown ladder, so an unbounded
    // read here defeats FORCE_AFTER_MS and REAP_BUDGET_MS. Note this does NOT
    // fail closed the way the verifiers do -- a timeout takes the same safe
    // default as every other unreadable state, per the docstring above.
    let mut command = Command::new("/bin/ps");
    command.args(["-o", "state=", "-p", &pid.to_string()]);
    let Ok(output) = output_within(&mut command, PS_BUDGET) else {
        return false;
    };
    // BSD/macOS state codes: T = stopped by a signal, plus optional
    // modifier characters after the first.
    String::from_utf8_lossy(&output.stdout)
        .trim()
        .starts_with('T')
}

#[cfg(not(unix))]
fn is_stopped(_pid: u32) -> bool {
    false
}

/// Rotate `desktop-child.log` once it passes this size (#464).
///
/// One generation only (`desktop-child.log.1`). Two launches' worth of
/// evidence is what the append change was for; an unbounded file was not.
const LOG_ROTATE_BYTES: u64 = 4 * 1024 * 1024;

/// Per-launch ceiling on relayed child stderr (#464).
///
/// Separate from [`DRAIN_CAP_BYTES`], which bounds the post-bound STDOUT
/// drain. A spewing child hits this one first; the relay keeps READING after
/// it (never writing), because a reader that stops draining a pipe blocks the
/// child on its next write.
const RELAY_CAP_BYTES: u64 = 1024 * 1024;

/// The most of ONE stderr record held in memory at a time (#464 round 2).
///
/// [`RELAY_CAP_BYTES`] bounds the launch TOTAL, but it is only consulted
/// between records, so it bounded nothing on its own: `read_until(b'\n')`
/// against a child that never emits a newline buffers the whole stream into
/// one `Vec` before the cap is ever read. A faulty child could exhaust memory
/// and write far past the advertised cap in a single record.
///
/// So the read itself is bounded. A newline-free record simply arrives as
/// successive 64 KiB pieces: memory stays flat, the total cap is re-checked
/// every piece, and the overshoot past `RELAY_CAP_BYTES` is at most one
/// piece instead of unbounded. Scrubbing still happens before every write.
///
/// 64 KiB because a real stderr line is orders of magnitude smaller, so no
/// legitimate record is ever split, and a split one is still readable.
const RELAY_RECORD_CAP_BYTES: u64 = 64 * 1024;

/// First token of the per-launch boundary line written by [`open_private_log`].
///
/// A child could emit this string itself. That can only SHORTEN the tail —
/// the forged line is still inside the launch that wrote it, so lines after
/// it still belong to that launch — never attribute one launch's output to
/// another, which is the failure this boundary exists to prevent.
const LAUNCH_BANNER: &str = "===== arXMCP launch";

/// #488: open a log file readable only by its owner.
///
/// `mode()` covers creation; `set_permissions` covers a file that already
/// exists — which is the case that matters, since a log written by an earlier
/// version is sitting there at 0644 right now. Both files are documented to
/// be able to contain a live startup token (#438 / #439), so the default
/// umask is not an acceptable answer even though $HOME's 0700 usually hides
/// them.
pub fn open_private_log(path: &std::path::Path) -> Result<std::fs::File, &'static str> {
    // #464: APPEND, not truncate. The event log beside it is already
    // append-only (`events.rs`), so this was an inconsistency rather than a
    // considered choice — and a costly one: `desktop-child.log` is the ONLY
    // place a cold-start failure's real reason exists (#444), so a user who
    // double-clicks a second time destroyed the evidence before anyone could
    // ask them for it.
    // #464 round 2: appending forever is unbounded, and the docstring that
    // shipped with the append change deflected that onto #486 — which is the
    // post-bound STDOUT DRAIN cap, a different path entirely. Nothing capped
    // this file. Rotate one generation instead: the previous launch's
    // evidence survives a second double-click, which is the whole point of
    // appending, while total growth is bounded at 2x.
    if let Ok(meta) = std::fs::metadata(path) {
        if meta.len() > LOG_ROTATE_BYTES {
            let _ = std::fs::rename(path, path.with_extension("log.1"));
        }
    }
    let mut options = std::fs::OpenOptions::new();
    options.create(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|_| "child log unwritable")?;
    // #444 round 2: mark where THIS launch begins. Without a boundary,
    // `child_log_tail` showed the previous launch's last twelve lines under
    // "The server reported:" for any failure that happened before the child
    // wrote anything — a signature refusal, a spawn failure — which is worse
    // than showing nothing, because it is confidently wrong.
    let _ = writeln!(file, "{LAUNCH_BANNER} pid={} =====", std::process::id());
    let _ = file.flush();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
    }
    Ok(file)
}

/// #438: copy child stderr into the log, scrubbing every line first.
///
/// Line-oriented via `read_until` rather than `read_line`: child stderr is
/// arbitrary bytes and a UTF-8 error must not silently end the relay, so the
/// bytes are lossily decoded AFTER the split. Scrubbing happens before the
/// write, never after, so a boundary can never leave half a secret on disk.
///
/// Capped two ways (#464): [`RELAY_RECORD_CAP_BYTES`] bounds any single
/// record held in memory, and [`RELAY_CAP_BYTES`] bounds the launch total.
/// The first exists because the second alone is bypassable — see its
/// docstring. Past the total cap the thread
/// keeps READING and stops WRITING: a reader that stops draining the pipe
/// blocks the child on its next write, which would turn a chatty child into a
/// hung one. One truncation notice is written, so a reader of the log can
/// tell a quiet child from a silenced one.
///
/// An earlier revision of this docstring called the relay unbounded and
/// deflected the concern onto #486. That was wrong: #486 caps the post-bound
/// STDOUT DRAIN, which is a different path and never touched this file.
fn spawn_stderr_relay(
    stderr: std::process::ChildStderr,
    mut log_file: std::fs::File,
    token: StartupToken,
) {
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        let mut line: Vec<u8> = Vec::new();
        let mut written: u64 = 0;
        let mut capped = false;
        loop {
            line.clear();
            // #464: bound ONE record. `Take` is re-applied each iteration, so
            // `Ok(0)` still means EOF and not "limit reached".
            match (&mut reader)
                .take(RELAY_RECORD_CAP_BYTES)
                .read_until(b'\n', &mut line)
            {
                Ok(0) | Err(_) => break,
                Ok(_) => {}
            }
            if capped {
                // Drain and discard. Still reading is the point.
                continue;
            }
            let text = String::from_utf8_lossy(&line);
            let scrubbed = redact::scrub_child_text(&text, token.expose());
            if log_file.write_all(scrubbed.as_bytes()).is_err() {
                break;
            }
            written += scrubbed.len() as u64;
            if written > RELAY_CAP_BYTES {
                capped = true;
                let _ = writeln!(
                    log_file,
                    "[arXMCP] child stderr exceeded {RELAY_CAP_BYTES} bytes \
                     this launch; further output is being read and discarded."
                );
            }
            let _ = log_file.flush();
        }
    });
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
    // ---- issues #436 / #484: the payload, not just the executable --------

    #[test]
    fn a_bundled_child_resolves_its_enclosing_app() {
        let child = std::path::Path::new(
            "/Applications/arXMCP.app/Contents/Resources/arxmcp-desktop-child/arxmcp-desktop-child",
        );
        assert_eq!(
            super::enclosing_app_bundle(child),
            Some(std::path::PathBuf::from("/Applications/arXMCP.app")),
        );
    }

    #[test]
    fn the_onedir_layout_has_no_enclosing_app() {
        // m7's shape: payload is a sibling of the supervisor, no bundle.
        // Returning a spurious path here would make the seal check refuse
        // every developer run.
        let child = std::path::Path::new("/build/dist/arxmcp-desktop-child/arxmcp-desktop-child");
        assert_eq!(super::enclosing_app_bundle(child), None);
    }

    #[test]
    fn a_near_miss_layout_is_not_treated_as_a_bundle() {
        // Each component is checked, so a path that merely LOOKS bundle-ish
        // cannot borrow a seal from somewhere else. The failure direction
        // matters: a false Some() points `codesign --verify` at an unrelated
        // directory, and whatever it answers is about the wrong thing.
        for path in [
            "/x/arXMCP.app/Contents/Frameworks/arxmcp-desktop-child/arxmcp-desktop-child",
            "/x/arXMCP.app/Wrapper/Resources/arxmcp-desktop-child/arxmcp-desktop-child",
            "/x/arXMCP.bundle/Contents/Resources/arxmcp-desktop-child/arxmcp-desktop-child",
            "/x/Contents/Resources/arxmcp-desktop-child/arxmcp-desktop-child",
        ] {
            assert_eq!(
                super::enclosing_app_bundle(std::path::Path::new(path)),
                None,
                "{path} must not resolve to a bundle",
            );
        }
    }

    #[test]
    #[cfg(target_os = "macos")]
    fn an_unsealed_directory_fails_the_seal_check() {
        // The refusal must carry codesign's own first line, not a generic
        // string: "code object is not signed at all" and "a sealed resource
        // is missing or invalid" are different operator problems.
        let dir = std::env::temp_dir().join(format!("arxmcp-seal-test-{}.app", std::process::id()));
        let _ = std::fs::create_dir_all(dir.join("Contents").join("MacOS"));
        let result = super::verify_bundle_seal(&dir);
        let _ = std::fs::remove_dir_all(&dir);
        let detail = match result.expect_err("an unsigned directory must not verify") {
            VerifyError::Rejected(detail) => detail,
            other => panic!("an unsigned directory is a rejection, not {other:?}"),
        };
        assert!(!detail.is_empty(), "the refusal must name a reason");
    }

    use super::*;

    // ---- issue #444: the child's own error reaches the operator ----------

    fn scratch(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(name);
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch dir");
        dir
    }

    /// #444 round 2: THE case. A failure before the child speaks must show
    /// nothing, not the previous launch.
    #[test]
    fn a_pre_spawn_failure_quotes_nothing_from_the_previous_launch() {
        let dir = scratch("arxmcp-tail-boundary");
        let path = dir.join("desktop-child.log");
        // Launch 1 ran and said something memorable.
        std::fs::write(&path, "ModuleNotFoundError: no module named 'torch'\n")
            .expect("seed the previous launch");
        // Launch 2 opens the log and then fails before the child writes.
        let _file = super::open_private_log(&path).expect("open");
        assert!(
            super::child_log_tail(&path, 12).is_none(),
            "a launch whose child never spoke must contribute no tail; \
             quoting launch 1 here is worse than silence — it reads as the \
             cause of launch 2's failure",
        );
    }

    #[test]
    fn the_tail_is_this_launch_only() {
        let dir = scratch("arxmcp-tail-thislaunch");
        let path = dir.join("desktop-child.log");
        std::fs::write(&path, "OLD LAUNCH LINE\n").expect("seed");
        let mut file = super::open_private_log(&path).expect("open");
        writeln!(file, "fresh failure detail").expect("write");
        let tail = super::child_log_tail(&path, 12).expect("tail");
        assert!(tail.contains("fresh failure detail"), "{tail}");
        assert!(!tail.contains("OLD LAUNCH LINE"), "{tail}");
    }

    #[test]
    fn a_log_without_a_boundary_still_tails() {
        // Backwards compatibility: a file written by a build that predates
        // the boundary must not silently stop producing diagnostics.
        let dir = scratch("arxmcp-tail-legacy");
        let path = dir.join("desktop-child.log");
        std::fs::write(&path, "legacy line one\nlegacy line two\n").expect("seed");
        let tail = super::child_log_tail(&path, 12).expect("tail");
        assert!(tail.contains("legacy line two"), "{tail}");
    }

    #[test]
    fn a_forged_banner_can_only_shorten_the_tail() {
        // A child emitting the boundary string itself is possible. The bound
        // that matters: lines after ANY banner still belong to the launch
        // that wrote them, so no other launch's output can be attributed here.
        let dir = scratch("arxmcp-tail-forged");
        let path = dir.join("desktop-child.log");
        std::fs::write(&path, "PREVIOUS LAUNCH\n").expect("seed");
        let mut file = super::open_private_log(&path).expect("open");
        writeln!(file, "early line").expect("write");
        writeln!(file, "{} pid=999 =====", super::LAUNCH_BANNER).expect("forge");
        writeln!(file, "late line").expect("write");
        let tail = super::child_log_tail(&path, 12).expect("tail");
        assert!(tail.contains("late line"), "{tail}");
        assert!(
            !tail.contains("PREVIOUS LAUNCH"),
            "the bound that matters: {tail}"
        );
    }

    /// #464 round 2: the append change made growth unbounded, and the fix
    /// that shipped pointed at #486, which caps a different path.
    #[test]
    fn an_oversized_log_rotates_one_generation() {
        let dir = scratch("arxmcp-log-rotate");
        let path = dir.join("desktop-child.log");
        let previous = path.with_extension("log.1");
        std::fs::write(&path, vec![b'x'; (super::LOG_ROTATE_BYTES + 1) as usize])
            .expect("seed an oversized log");
        let _file = super::open_private_log(&path).expect("open");
        assert!(previous.is_file(), "the oversized log must be kept as .1");
        let fresh = std::fs::metadata(&path).expect("fresh log").len();
        assert!(
            fresh < super::LOG_ROTATE_BYTES,
            "the live log must start fresh, found {fresh} bytes",
        );
    }

    #[test]
    fn a_log_under_the_threshold_is_not_rotated() {
        // The negative control. Rotating every launch would destroy exactly
        // the evidence #464 exists to preserve.
        let dir = scratch("arxmcp-log-norotate");
        let path = dir.join("desktop-child.log");
        std::fs::write(&path, b"small\n").expect("seed");
        let _file = super::open_private_log(&path).expect("open");
        assert!(!path.with_extension("log.1").is_file());
        let text = std::fs::read_to_string(&path).expect("read");
        assert!(text.contains("small"), "the previous launch must survive");
    }

    /// #464 round 2: a spewing child must not grow the log without bound —
    /// and must not be blocked by the relay that stops writing.
    #[test]
    fn the_relay_caps_its_writes_and_keeps_draining() {
        let dir = scratch("arxmcp-relay-cap");
        let path = dir.join("desktop-child.log");
        let log = super::open_private_log(&path).expect("open");
        // A child that writes far more than the cap and then exits 0. If the
        // relay stopped READING, this would block on a full pipe and never
        // reach the exit.
        let mut child = std::process::Command::new("/bin/sh")
            .arg("-c")
            // NOT hex characters. The first draft spewed 'a' x 60 and the
            // cap never fired: `scrub_child_text` collapses any run of >= 32
            // hex digits to `[REDACTED-HEX]` (#439), so each 61-byte line
            // reached the log as ~15 bytes and the size assertion below
            // passed for entirely the wrong reason.
            .arg(
                "i=0; while [ $i -lt 40000 ]; do echo \
                 'zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz' >&2; \
                 i=$((i+1)); done; exit 0",
            )
            .stderr(std::process::Stdio::piped())
            .stdout(std::process::Stdio::null())
            .spawn()
            .expect("spawn a chatty child");
        let stderr = child.stderr.take().expect("stderr");
        super::spawn_stderr_relay(
            stderr,
            log,
            StartupToken::parse("0".repeat(64)).expect("fixture token"),
        );
        let status = child
            .wait()
            .expect("the child must not block on a full pipe");
        assert!(status.success(), "child exited {status:?}");
        // Give the relay a moment to finish draining after the child exits.
        for _ in 0..100 {
            if std::fs::read_to_string(&path).is_ok_and(|text| text.contains("exceeded")) {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        let len = std::fs::metadata(&path).expect("log").len();
        let produced = 40_000_u64 * 61;
        assert!(
            len < produced / 2,
            "the log must be capped well below the {produced} bytes written, found {len}",
        );
        let text = std::fs::read_to_string(&path).expect("read");
        assert!(
            text.contains("exceeded"),
            "a truncated log must SAY it was truncated, or a quiet child and \
             a silenced one read alike",
        );
    }

    #[test]
    fn a_newline_free_child_cannot_outrun_the_relay_cap() {
        // #464 round 2. The launch-total cap is only consulted BETWEEN
        // records, so before `RELAY_RECORD_CAP_BYTES` a child that never
        // emits a newline held the whole stream in one `Vec` and wrote it
        // out in one go -- unbounded memory, and a log far past the cap.
        //
        // `printf` in a loop with no trailing newline, and NOT hex bytes:
        // `scrub_child_text` collapses long hex runs, which is how the
        // sibling test above first passed for the wrong reason.
        let dir = scratch("arxmcp-relay-noeol");
        let path = dir.join("desktop-child.log");
        let log = super::open_private_log(&path).expect("open");
        let mut child = std::process::Command::new("/bin/sh")
            .arg("-c")
            .arg(
                "i=0; while [ $i -lt 40000 ]; do \
                 printf 'zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz' >&2; \
                 i=$((i+1)); done; exit 0",
            )
            .stderr(std::process::Stdio::piped())
            .stdout(std::process::Stdio::null())
            .spawn()
            .expect("spawn a newline-free child");
        let stderr = child.stderr.take().expect("stderr");
        super::spawn_stderr_relay(
            stderr,
            log,
            StartupToken::parse("0".repeat(64)).expect("fixture token"),
        );
        let status = child
            .wait()
            .expect("the child must not block on a full pipe");
        assert!(status.success(), "child exited {status:?}");
        for _ in 0..100 {
            if std::fs::read_to_string(&path).is_ok_and(|text| text.contains("exceeded")) {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        let len = std::fs::metadata(&path).expect("log").len();
        let produced = 40_000_u64 * 60;
        assert!(
            text_contains_truncation_notice(&path),
            "a silenced newline-free child must still say it was truncated",
        );
        // The overshoot past the total cap is now bounded by ONE record
        // buffer, so a generous ceiling still fails loudly on a regression:
        // before the fix this file was the full 2.4 MB the child produced.
        let ceiling = RELAY_CAP_BYTES + 4 * RELAY_RECORD_CAP_BYTES;
        assert!(
            len <= ceiling,
            "the log must stay within {ceiling} bytes (cap plus one record's \
             overshoot) of the {produced} bytes written, found {len}",
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    fn text_contains_truncation_notice(path: &std::path::Path) -> bool {
        std::fs::read_to_string(path).is_ok_and(|text| text.contains("exceeded"))
    }

    #[test]
    fn child_log_tail_returns_the_last_lines() {
        let dir = scratch("arxmcp-tail-basic");
        let path = dir.join("desktop-child.log");
        std::fs::write(&path, "one\ntwo\nthree\nfour\n").expect("write log");
        let tail = child_log_tail(&path, 2).expect("tail");
        assert_eq!(tail, "three\nfour");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn child_log_tail_surfaces_the_measured_cold_start_error() {
        // The line #444 found sitting in a file nobody would look at.
        let dir = scratch("arxmcp-tail-fatal");
        let path = dir.join("desktop-child.log");
        std::fs::write(
            &path,
            "boot\nFATAL: Resources.startup failed: corpus-version.json not found\n",
        )
        .expect("write log");
        let tail = child_log_tail(&path, 12).expect("tail");
        assert!(tail.contains("corpus-version.json not found"), "{tail}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn child_log_tail_is_bounded_and_drops_a_cut_first_line() {
        // A child that spewed megabytes must not be read into memory, and the
        // window will land mid-line — that fragment must not be shown as if
        // it were a whole message.
        let dir = scratch("arxmcp-tail-big");
        let path = dir.join("desktop-child.log");
        let mut body = "x".repeat(40_000);
        body.push_str("\nlast-line\n");
        std::fs::write(&path, &body).expect("write log");
        let tail = child_log_tail(&path, 3).expect("tail");
        assert!(tail.len() < 9_000, "tail must stay bounded: {}", tail.len());
        assert!(tail.contains("last-line"), "{tail}");
        assert!(!tail.starts_with('x'), "the cut first line must be dropped");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn child_log_tail_is_none_when_there_is_nothing_to_show() {
        let dir = scratch("arxmcp-tail-empty");
        let missing = dir.join("absent.log");
        assert!(child_log_tail(&missing, 5).is_none());
        let empty = dir.join("empty.log");
        std::fs::write(&empty, "").expect("write log");
        assert!(child_log_tail(&empty, 5).is_none());
        let blank = dir.join("blank.log");
        std::fs::write(&blank, "\n\n   \n").expect("write log");
        assert!(child_log_tail(&blank, 5).is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn child_log_tail_redacts_hex_even_though_the_relay_already_did() {
        // Defence in depth: this display path must not depend on the #438
        // relay having scrubbed correctly.
        let dir = scratch("arxmcp-tail-hex");
        let path = dir.join("desktop-child.log");
        let token = "13f7e5bc3420046bd0d28be56d0e24a5eae57989d91bbf6e6470bff75b08fd4d";
        std::fs::write(&path, format!("leaked {token}\n")).expect("write log");
        let tail = child_log_tail(&path, 5).expect("tail");
        assert!(!tail.contains(token), "{tail}");
        assert!(tail.contains("[REDACTED-HEX]"), "{tail}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ---- issue #442: a never-bound child does not get the grace ----------

    /// A child that ignores TERM, so the ladder must escalate to KILL.
    fn stubborn_control(grace_ms: u64) -> ChildControl {
        let mut child = Command::new("/bin/sh")
            .args(["-c", "trap '' TERM; sleep 30"])
            .stdin(Stdio::piped())
            .spawn()
            .expect("spawn stubborn child");
        let stdin = child.stdin.take().expect("stubborn child stdin");
        ChildControl {
            child,
            stdin,
            token: generate_startup_token().expect("startup token"),
            contract: ContractVersion { major: 1, minor: 0 },
            grace_ms,
            force_after_ms: 200,
        }
    }

    #[test]
    fn a_stopped_child_skips_straight_to_kill() {
        // #442's measured pathology. A SIGSTOP'd child cannot observe stdin
        // EOF, cannot act on the shutdown frame, and does not receive SIGTERM
        // until it continues — so grace and TERM are both dead time. A 3s
        // grace makes the difference unambiguous.
        let control = stubborn_control(3_000);
        let pid = control.child.id();
        // SIGSTOP delivery is ASYNCHRONOUS, and under parallel-test load the
        // first one has been observed not to take at all (measured: ~2 in 5
        // runs never reached state T within 5s, while the same shape outside
        // the harness stopped 6/6). Re-send until `ps` confirms rather than
        // asserting once — this is establishing the test's PRECONDITION, so a
        // flake here would report a product failure that is not one.
        let settle = Instant::now() + Duration::from_secs(10);
        while Instant::now() < settle {
            if is_stopped(pid) {
                break;
            }
            let _ = Command::new("/bin/kill")
                .args(["-STOP", &pid.to_string()])
                .status();
            std::thread::sleep(Duration::from_millis(50));
        }
        let observed = Command::new("/bin/ps")
            .args(["-o", "state=,command=", "-p", &pid.to_string()])
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned())
            .unwrap_or_default();
        assert!(
            is_stopped(pid),
            "could not stop the fixture, so the shortcut is untestable here; \
             ps said {observed:?}"
        );

        let started = Instant::now();
        let code = shutdown_child(control);
        let elapsed = started.elapsed();
        assert_eq!(code, -1, "a force-killed child reports no exit code");
        assert!(
            elapsed < Duration::from_secs(3),
            "a stopped child must not be waited on for the cooperative grace \
             — took {elapsed:?} (#442)"
        );
    }

    #[test]
    fn a_running_child_still_gets_its_full_grace() {
        // The negative control, and the reason the shortcut is narrow. The m6
        // fault matrix has TWO arms that never emit `bound` and still exit 0
        // cooperatively — parked-but-cooperating, and malformed-bound. An
        // earlier draft keyed the shortcut on "never bound" and broke both.
        // A running server also holds LanceDB and Kuzu handles, which is what
        // MIN_GRACE_MS exists to let it close.
        let control = stubborn_control(3_000);
        assert!(!is_stopped(control.child.id()));
        let started = Instant::now();
        let code = shutdown_child(control);
        let elapsed = started.elapsed();
        assert_eq!(code, -1);
        assert!(
            elapsed >= Duration::from_secs(3),
            "a running child must still get its full grace — took {elapsed:?}"
        );
    }

    // ---- issue #497: the subprocesses are bounded ------------------------

    #[test]
    fn output_within_returns_a_fast_child_whole() {
        let mut command = Command::new("/bin/echo");
        command.arg("hello");
        let output = output_within(&mut command, Duration::from_secs(5))
            .expect("a fast child must not time out");
        assert!(output.status.success());
        assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "hello");
    }

    #[test]
    fn output_within_does_not_deadlock_on_a_chatty_child() {
        // The whole reason the pipes are drained on threads. A `try_wait`
        // poll loop over an undrained pipe wedges once the child fills the
        // 64 KiB buffer: it blocks on write, never exits, and the loop burns
        // its entire budget against a child that was only verbose. 4 MB is
        // far past any pipe buffer, and the budget is far below the time a
        // deadlocked version would take to give up.
        let mut command = Command::new("/bin/sh");
        command.args([
            "-c",
            "i=0; while [ $i -lt 65536 ]; do printf '0123456789012345678901234567890123456789012345678901234567890123'; i=$((i+1)); done",
        ]);
        let started = Instant::now();
        let output = output_within(&mut command, Duration::from_secs(30))
            .expect("a chatty child must complete, not deadlock");
        assert!(output.status.success());
        assert_eq!(output.stdout.len(), 65_536 * 64);
        assert!(
            started.elapsed() < Duration::from_secs(30),
            "completed only by exhausting the budget, which means it deadlocked",
        );
    }

    #[test]
    fn output_within_kills_a_slow_child_rather_than_orphaning_it() {
        // The child records its own pid, so the kill can be VERIFIED rather
        // than assumed. A timed-out `codesign` left running against whatever
        // stalled it would leak one process per launch attempt.
        let dir = scratch("arxmcp-bounded-kill");
        let pid_file = dir.join("pid");
        let mut command = Command::new("/bin/sh");
        command.args(["-c", &format!("echo $$ > {}; sleep 30", pid_file.display())]);
        let started = Instant::now();
        let failure = output_within(&mut command, Duration::from_millis(300))
            .expect_err("a 30s child must not finish inside a 300ms budget");
        let elapsed = started.elapsed();
        assert!(
            matches!(failure, RunFailure::TimedOut),
            "expected a timeout, got {failure:?}",
        );
        // The budget is the point: it must give up ON TIME, not eventually.
        assert!(
            elapsed < Duration::from_secs(5),
            "the budget was not honoured — took {elapsed:?}",
        );

        let pid: u32 = std::fs::read_to_string(&pid_file)
            .expect("the child must have recorded its pid")
            .trim()
            .parse()
            .expect("pid parses");
        // The direct child is reaped by `output_within` itself, so `ps` can
        // no longer see it. Poll briefly: the kill is not instantaneous.
        let gone = poll_until(Duration::from_secs(5), || {
            !Command::new("/bin/ps")
                .args(["-o", "state=", "-p", &pid.to_string()])
                .output()
                .is_ok_and(|out| !out.stdout.trim_ascii().is_empty())
        });
        assert!(gone.is_ok(), "pid {pid} outlived the timeout — orphaned");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn a_codesign_that_never_answers_is_a_timeout_not_a_rejection() {
        // #497 AC4. The stand-in hangs the way a `codesign` blocked on a
        // stalled mount would, and the verdict must be TimedOut: the launch
        // path picks `child-signature-timeout` off this variant, and a
        // rejection here would render a stalled disk as a tampered binary.
        let started = Instant::now();
        let result = codesign_verify(
            "/bin/sleep",
            Duration::from_millis(300),
            &[std::ffi::OsStr::new("30")],
        );
        let elapsed = started.elapsed();
        assert_eq!(result, Err(VerifyError::TimedOut { budget_ms: 300 }));
        assert!(
            elapsed < Duration::from_secs(5),
            "the launch must fail WITHIN the budget — took {elapsed:?}",
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn a_missing_codesign_is_still_a_rejection_not_a_timeout() {
        // Fail-closed on an unrunnable tool predates #497 and must survive it:
        // it is a rejection, and it must not be reported as a stall.
        let result = codesign_verify(
            "/nonexistent/codesign",
            Duration::from_secs(5),
            &[std::ffi::OsStr::new("--verify")],
        );
        match result.expect_err("a missing tool must not verify") {
            VerifyError::Rejected(detail) => {
                assert!(detail.contains("could not be run"), "got {detail:?}")
            }
            other => panic!("a missing tool is a rejection, not {other:?}"),
        }
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn the_healthy_verification_path_never_reaches_its_budget() {
        // The other half of the fail-closed trade: refusing on timeout is only
        // acceptable while no healthy machine trips it. Measured at ~0.42s
        // against a real bundle; asserted well inside CODESIGN_BUDGET so a
        // regression that makes verification slow is caught here rather than
        // by an operator whose app stops starting.
        let dir = std::env::temp_dir().join("arxmcp-sig-budget");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch dir");
        let binary = signed_fixture(&dir, "child");
        let started = Instant::now();
        assert_eq!(verify_signature(&binary), Ok(()));
        let elapsed = started.elapsed();
        assert!(
            elapsed * 3 < CODESIGN_BUDGET,
            "healthy verification took {elapsed:?}, uncomfortably close to the \
             {CODESIGN_BUDGET:?} budget that refuses a launch",
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn is_stopped_is_false_for_an_unknown_pid() {
        // The safe default: an unreadable state must keep the full ladder,
        // never force-kill a healthy server on a bad reading.
        assert!(!is_stopped(u32::MAX));
    }

    // ---- issue #436: the seal is actually consulted ----------------------

    /// Ad-hoc sign a copy of a small system binary into `dir`, returning it.
    /// Uses a REAL Mach-O and a REAL codesign invocation — a hand-built fake
    /// would prove only that the fake matches its own expectations.
    #[cfg(target_os = "macos")]
    fn signed_fixture(dir: &std::path::Path, name: &str) -> std::path::PathBuf {
        let target = dir.join(name);
        // /bin/sh, not /usr/bin/true: the latter is small enough that a
        // mid-file flip lands outside __TEXT and leaves a structurally broken
        // Mach-O ("main executable failed strict validation"), which is a
        // DIFFERENT failure from the tamper this is meant to model, and one
        // codesign then cannot re-sign. Measured both, 2026-08-22.
        std::fs::copy("/bin/sh", &target).expect("copy /bin/sh");
        let status = Command::new(CODESIGN)
            .args(["--force", "--sign", "-"])
            .arg(&target)
            .status()
            .expect("codesign runs");
        assert!(status.success(), "ad-hoc signing the fixture failed");
        target
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn verify_signature_accepts_an_untouched_binary() {
        let dir = std::env::temp_dir().join("arxmcp-sig-ok");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch dir");
        let binary = signed_fixture(&dir, "child");
        assert_eq!(verify_signature(&binary), Ok(()));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn verify_signature_rejects_a_single_flipped_byte() {
        // This is #436's exact repro: one byte, in a signed Mach-O, which
        // used to execute anyway because nothing consulted the seal.
        let dir = std::env::temp_dir().join("arxmcp-sig-tamper");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch dir");
        let binary = signed_fixture(&dir, "child");

        let mut bytes = std::fs::read(&binary).expect("read fixture");
        let offset = bytes.len() / 2;
        bytes[offset] ^= 0xFF;
        std::fs::write(&binary, &bytes).expect("write tampered fixture");

        let result = verify_signature(&binary);
        assert!(
            result.is_err(),
            "a flipped byte must not verify: {result:?}"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn an_adhoc_resign_defeats_verification_and_that_is_the_known_limit() {
        // Pinned deliberately. Without a Developer ID there is no identity to
        // require, so anyone who can WRITE the payload can re-sign it and
        // pass. Documented in verify_signature and in apps/desktop/README.md;
        // asserted here so the limitation cannot be quietly forgotten, and so
        // e4's release signing has a test that will START FAILING when the
        // guarantee actually improves.
        //
        // Modelled as a binary SWAP rather than a byte flip: it is the more
        // realistic attack, and every codesign call then operates on a
        // well-formed Mach-O instead of one a flip may have mangled.
        let dir = std::env::temp_dir().join("arxmcp-sig-resign");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch dir");
        let binary = signed_fixture(&dir, "child");
        assert_eq!(
            verify_signature(&binary),
            Ok(()),
            "fixture must start valid"
        );

        // The attacker swaps in a different program and strips its signature.
        std::fs::copy("/usr/bin/true", &binary).expect("swap the payload");
        let stripped = Command::new(CODESIGN)
            .args(["--remove-signature"])
            .arg(&binary)
            .status()
            .expect("codesign runs");
        assert!(stripped.success());
        assert!(
            verify_signature(&binary).is_err(),
            "an unsigned swapped-in binary must be refused"
        );

        // ...and then ad-hoc signs it. This is the hole.
        let status = Command::new(CODESIGN)
            .args(["--force", "--sign", "-"])
            .arg(&binary)
            .status()
            .expect("codesign runs");
        assert!(status.success());
        assert_eq!(
            verify_signature(&binary),
            Ok(()),
            "if this now FAILS, ad-hoc re-signing no longer defeats the check \
             — the guarantee improved and this test should be rewritten, not deleted"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn verify_signature_reports_a_missing_file_rather_than_passing_it() {
        let missing = std::path::Path::new("/nonexistent/arxmcp-desktop-child");
        assert!(verify_signature(missing).is_err());
    }

    // ---- issue #425: the failure page's encoders -------------------------

    #[test]
    fn percent_encode_escapes_everything_outside_the_unreserved_set() {
        assert_eq!(percent_encode("abcXYZ019-_.~"), "abcXYZ019-_.~");
        // The bytes that would end the data: URL or start a new attribute.
        assert_eq!(percent_encode("<>\"'"), "%3C%3E%22%27");
        assert_eq!(percent_encode(" "), "%20");
        assert_eq!(percent_encode("#?&="), "%23%3F%26%3D");
        assert_eq!(percent_encode("/a/b"), "%2Fa%2Fb");
    }

    #[test]
    fn percent_encode_is_byte_wise_over_multibyte_utf8() {
        // A data root can contain any UTF-8. Encoding per-char rather than
        // per-byte would emit a lone codepoint the URL parser rejects.
        assert_eq!(percent_encode("é"), "%C3%A9");
        assert_eq!(percent_encode("🧨"), "%F0%9F%A7%A8");
    }

    #[test]
    fn html_escape_neutralises_markup_in_an_operator_path() {
        assert_eq!(
            html_escape("/Users/x/<img src=y onerror=z>/logs"),
            "/Users/x/&lt;img src=y onerror=z&gt;/logs"
        );
        // Ampersand first, or the other replacements get double-escaped.
        assert_eq!(html_escape("a&b<c"), "a&amp;b&lt;c");
        assert_eq!(html_escape("\"q\""), "&quot;q&quot;");
    }

    #[test]
    fn a_hostile_data_root_cannot_break_out_of_the_failure_page() {
        // The composed body is HTML-escaped and then percent-encoded, so
        // neither layer can be terminated by a path an operator chose.
        let hostile = "/tmp/</style><script>alert(1)</script>";
        let escaped = html_escape(hostile);
        assert!(!escaped.contains('<'), "{escaped}");
        let encoded = percent_encode(&escaped);
        for forbidden in ['<', '>', '"', '\''] {
            assert!(
                !encoded.contains(forbidden),
                "{encoded} contains {forbidden}"
            );
        }
    }

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

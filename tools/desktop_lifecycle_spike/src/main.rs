use arxmcp_desktop_lifecycle_spike::{
    startup_token, validate_bound, Bootstrap, Bound, Fault, Shutdown, FRAME_LIMIT,
    PRODUCTION_GRACE_MS, PROTOCOL_VERSION, TOKEN_CANARY,
};
use serde::Serialize;
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::async_runtime::Receiver;
use tauri_plugin_shell::process::{CommandChild, CommandEvent, TerminatedPayload};
use tauri_plugin_shell::ShellExt;

const STARTUP_LIMIT: Duration = Duration::from_millis(1_500);
const FIXTURE_SHUTDOWN_GRACE: Duration = Duration::from_millis(350);
const SIGNAL_GRACE: Duration = Duration::from_millis(250);
const SIDECAR_NAME: &str = concat!("fixture-sidecar-", env!("TAURI_ENV_TARGET_TRIPLE"));

static DUPLICATE_ACTIVATIONS: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Scenario {
    Fault(Fault),
    Duplicate,
    ParentCrash,
}

impl Scenario {
    fn parse(value: &str) -> Result<Self, &'static str> {
        match value {
            "duplicate" => Ok(Self::Duplicate),
            "parent-crash" => Ok(Self::ParentCrash),
            other => Fault::from_str(other)
                .map(Self::Fault)
                .map_err(|_| "unknown scenario"),
        }
    }

    fn fault(self) -> Fault {
        match self {
            Self::Fault(fault) => fault,
            Self::Duplicate | Self::ParentCrash => Fault::Normal,
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Duplicate => "duplicate",
            Self::ParentCrash => "parent-crash",
            Self::Fault(Fault::Normal) => "normal",
            Self::Fault(Fault::StartupTimeout) => "startup-timeout",
            Self::Fault(Fault::NeverReady) => "never-ready",
            Self::Fault(Fault::MalformedBound) => "malformed-bound",
            Self::Fault(Fault::WildcardV4) => "wildcard-v4",
            Self::Fault(Fault::WildcardV6) => "wildcard-v6",
            Self::Fault(Fault::CrashBeforeBound) => "crash-before-bound",
            Self::Fault(Fault::CrashAfterReady) => "crash-after-ready",
            Self::Fault(Fault::IgnoreShutdown) => "ignore-shutdown",
        }
    }
}

#[derive(Clone)]
struct Recorder {
    inner: Arc<Mutex<RecorderInner>>,
}

struct RecorderInner {
    path: PathBuf,
    run_id: String,
    scenario: String,
    started: Instant,
    sequence: u64,
}

#[derive(Serialize)]
struct Record<'a> {
    v: u8,
    seq: u64,
    elapsed_ms: u128,
    event: &'a str,
    host_pid: u32,
    run_id: &'a str,
    scenario: &'a str,
    fields: Value,
}

impl Recorder {
    fn new(root: &Path, run_id: String, scenario: Scenario) -> Result<Self, &'static str> {
        fs::create_dir_all(root).map_err(|_| "data root creation failed")?;
        Ok(Self {
            inner: Arc::new(Mutex::new(RecorderInner {
                path: root.join("events.ndjson"),
                run_id,
                scenario: scenario.name().to_owned(),
                started: Instant::now(),
                sequence: 0,
            })),
        })
    }

    fn record(&self, event: &str, fields: Value) -> Result<(), &'static str> {
        let mut state = self.inner.lock().map_err(|_| "event recorder poisoned")?;
        state.sequence += 1;
        let record = Record {
            v: PROTOCOL_VERSION,
            seq: state.sequence,
            elapsed_ms: state.started.elapsed().as_millis(),
            event,
            host_pid: std::process::id(),
            run_id: &state.run_id,
            scenario: &state.scenario,
            fields,
        };
        let mut output = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&state.path)
            .map_err(|_| "event log open failed")?;
        serde_json::to_writer(&mut output, &record).map_err(|_| "event log write failed")?;
        output
            .write_all(b"\n")
            .and_then(|_| output.flush())
            .map_err(|_| "event log flush failed")
    }
}

#[derive(Debug, Eq, PartialEq)]
enum Probe {
    Health,
    Starting,
    Ready,
    Unavailable,
    Invalid,
}

fn request(port: u16, path: &str, token: Option<&str>) -> Probe {
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    let Ok(mut stream) = TcpStream::connect_timeout(&address.into(), Duration::from_millis(100))
    else {
        return Probe::Unavailable;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(100)));
    let capability = token
        .map(|value| format!("X-ArXMCP-Capability: {value}\r\n"))
        .unwrap_or_default();
    let request =
        format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n{capability}Connection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return Probe::Unavailable;
    }
    let mut response = Vec::new();
    if stream.take(1024).read_to_end(&mut response).is_err() {
        return Probe::Unavailable;
    }
    match response.as_slice() {
        bytes
            if bytes.starts_with(b"HTTP/1.1 200 OK\r\n")
                && bytes.ends_with(b"{\"status\":\"ok\"}") =>
        {
            Probe::Health
        }
        bytes
            if bytes.starts_with(b"HTTP/1.1 503 Service Unavailable\r\n")
                && bytes.ends_with(b"{\"status\":\"starting\"}") =>
        {
            Probe::Starting
        }
        bytes
            if bytes.starts_with(b"HTTP/1.1 200 OK\r\n")
                && bytes.ends_with(b"{\"status\":\"ready\"}") =>
        {
            Probe::Ready
        }
        _ => Probe::Invalid,
    }
}

struct Sidecar {
    events: Receiver<CommandEvent>,
    child: CommandChild,
    pid: u32,
    token: String,
    stdout: Vec<u8>,
}

impl Sidecar {
    fn output_is_clean(&self, bytes: &[u8]) -> bool {
        !bytes
            .windows(self.token.len())
            .any(|window| window == self.token.as_bytes())
            && !bytes
                .windows(TOKEN_CANARY.len())
                .any(|window| window == TOKEN_CANARY.as_bytes())
    }

    fn inspect_output(&self, bytes: &[u8]) -> Result<(), &'static str> {
        if bytes.len() > FRAME_LIMIT || !self.output_is_clean(bytes) {
            return Err("sidecar output failed bounded secret scan");
        }
        Ok(())
    }

    async fn event(&mut self, timeout: Duration) -> Result<CommandEvent, &'static str> {
        tokio::time::timeout(timeout, self.events.recv())
            .await
            .map_err(|_| "sidecar event timeout")?
            .ok_or("sidecar event stream closed")
    }

    async fn bound(&mut self, deadline: Instant) -> Result<Bound, &'static str> {
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err("bound frame timeout");
            }
            match self.event(remaining).await? {
                CommandEvent::Stdout(bytes) => {
                    self.inspect_output(&bytes)?;
                    if self.stdout.len() + bytes.len() > FRAME_LIMIT {
                        return Err("oversized protocol output");
                    }
                    self.stdout.extend(bytes);
                    if let Some(index) = self.stdout.iter().position(|byte| *byte == b'\n') {
                        return validate_bound(&self.stdout[..index], self.pid);
                    }
                }
                CommandEvent::Stderr(bytes) => self.inspect_output(&bytes)?,
                CommandEvent::Terminated(_) => return Err("sidecar exited before bound"),
                CommandEvent::Error(_) => return Err("sidecar event error"),
                _ => {}
            }
        }
    }

    async fn terminated(&mut self, timeout: Duration) -> Result<TerminatedPayload, &'static str> {
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err("sidecar termination timeout");
            }
            match self.event(remaining).await? {
                CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                    self.inspect_output(&bytes)?;
                }
                CommandEvent::Terminated(status) => return Ok(status),
                CommandEvent::Error(_) => return Err("sidecar event error"),
                _ => {}
            }
        }
    }

    fn write<T: Serialize>(&mut self, frame: &T) -> Result<(), &'static str> {
        let mut bytes = serde_json::to_vec(frame).map_err(|_| "control frame encoding failed")?;
        if bytes.len() + 1 > FRAME_LIMIT {
            return Err("control frame too large");
        }
        bytes.push(b'\n');
        self.child
            .write(&bytes)
            .map_err(|_| "control frame write failed")
    }
}

fn signal_group(pid: u32, signal: i32) -> Result<(), &'static str> {
    let group = i32::try_from(pid).map_err(|_| "sidecar pid out of range")?;
    // SAFETY: kill is called with a validated positive child PID negated to address
    // only the process group created by the fixture sidecar.
    let result = unsafe { libc::kill(-group, signal) };
    if result == 0 {
        return Ok(());
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        return Ok(());
    }
    Err("process-group signal failed")
}

async fn force_group_stop(
    sidecar: &mut Sidecar,
    recorder: &Recorder,
) -> Result<TerminatedPayload, &'static str> {
    signal_group(sidecar.pid, libc::SIGTERM)?;
    recorder.record("group_sigterm", json!({"pgid": sidecar.pid}))?;
    match sidecar.terminated(SIGNAL_GRACE).await {
        Ok(status) => Ok(status),
        Err("sidecar termination timeout") | Err("sidecar event timeout") => {
            signal_group(sidecar.pid, libc::SIGKILL)?;
            recorder.record("group_sigkill", json!({"pgid": sidecar.pid}))?;
            sidecar.terminated(Duration::from_secs(2)).await
        }
        Err(error) => Err(error),
    }
}

fn status_fields(status: &TerminatedPayload) -> Value {
    json!({"code": status.code, "signal": status.signal})
}

async fn spawn_sidecar(
    app: &tauri::AppHandle,
    root: &Path,
    fault: Fault,
    recorder: &Recorder,
) -> Result<Sidecar, &'static str> {
    let token = startup_token()?;
    let (events, child) = app
        .shell()
        .sidecar(SIDECAR_NAME)
        .map_err(|_| "sidecar path resolution failed")?
        .env_clear()
        .env("ARXMCP_SPIKE_DATA_DIR", root)
        .set_raw_out(true)
        .spawn()
        .map_err(|_| "sidecar spawn failed")?;
    let pid = child.pid();
    recorder.record(
        "sidecar_spawned",
        json!({"pid": pid, "sidecar": SIDECAR_NAME}),
    )?;
    let mut sidecar = Sidecar {
        events,
        child,
        pid,
        token,
        stdout: Vec::new(),
    };
    let bootstrap_token = sidecar.token.clone();
    sidecar.write(&Bootstrap {
        v: PROTOCOL_VERSION,
        kind: "init".to_owned(),
        token: bootstrap_token,
        data_root: root.to_path_buf(),
        bind_host: "127.0.0.1".to_owned(),
        fault,
        production_grace_ms: PRODUCTION_GRACE_MS,
    })?;
    recorder.record(
        "bootstrap_sent",
        json!({
            "bind_host": "127.0.0.1",
            "production_grace_ms": PRODUCTION_GRACE_MS,
            "token_entropy_bits": 256
        }),
    )?;
    Ok(sidecar)
}

async fn wait_ready(
    sidecar: &mut Sidecar,
    port: u16,
    deadline: Instant,
) -> Result<(), &'static str> {
    loop {
        match request(port, "/readyz", Some(&sidecar.token)) {
            Probe::Ready => return Ok(()),
            Probe::Starting | Probe::Unavailable => {}
            _ => return Err("readiness response contract failed"),
        }
        if Instant::now() >= deadline {
            return Err("readiness timeout");
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

async fn wait_health(port: u16, deadline: Instant) -> Result<(), &'static str> {
    loop {
        match request(port, "/healthz", None) {
            Probe::Health => return Ok(()),
            Probe::Unavailable => {}
            _ => return Err("health response contract failed"),
        }
        if Instant::now() >= deadline {
            return Err("health deadline exceeded");
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

async fn run_cycle(
    app: tauri::AppHandle,
    root: PathBuf,
    scenario: Scenario,
    recorder: Recorder,
) -> Result<(), &'static str> {
    recorder.record(
        "lifecycle_started",
        json!({"fixture_shutdown_grace_ms": FIXTURE_SHUTDOWN_GRACE.as_millis()}),
    )?;
    let mut sidecar = spawn_sidecar(&app, &root, scenario.fault(), &recorder).await?;
    let deadline = Instant::now() + STARTUP_LIMIT;

    if scenario == Scenario::Fault(Fault::CrashBeforeBound) {
        let status = sidecar.terminated(STARTUP_LIMIT).await?;
        if status.code == Some(0) {
            return Err("crash-before-bound exited successfully");
        }
        recorder.record("expected_crash_before_bound", status_fields(&status))?;
        recorder.record("secret_scan_clean", json!({"clean": true}))?;
        return Ok(());
    }

    let bound = match sidecar.bound(deadline).await {
        Ok(bound) => bound,
        Err(error) if scenario == Scenario::Fault(Fault::StartupTimeout) => {
            if error != "sidecar event timeout" && error != "bound frame timeout" {
                let _ = force_group_stop(&mut sidecar, &recorder).await;
                return Err(error);
            }
            recorder.record("startup_deadline_enforced", json!({}))?;
            let status = force_group_stop(&mut sidecar, &recorder).await?;
            recorder.record("sidecar_reaped", status_fields(&status))?;
            recorder.record("secret_scan_clean", json!({"clean": true}))?;
            return Ok(());
        }
        Err(error)
            if matches!(
                scenario,
                Scenario::Fault(Fault::MalformedBound | Fault::WildcardV4 | Fault::WildcardV6)
            ) =>
        {
            recorder.record("invalid_bound_rejected", json!({"reason": error}))?;
            let status = force_group_stop(&mut sidecar, &recorder).await?;
            recorder.record("sidecar_reaped", status_fields(&status))?;
            recorder.record("secret_scan_clean", json!({"clean": true}))?;
            return Ok(());
        }
        Err(error) => {
            let _ = force_group_stop(&mut sidecar, &recorder).await;
            return Err(error);
        }
    };
    recorder.record(
        "bound_validated",
        json!({
            "pid": bound.pid,
            "pgid": bound.pgid,
            "canary_pid": bound.canary_pid,
            "host": bound.host,
            "port": bound.port
        }),
    )?;
    if wait_health(bound.port, deadline).await.is_err() {
        let _ = force_group_stop(&mut sidecar, &recorder).await;
        return Err("health response contract failed");
    }
    recorder.record("health_ok", json!({"port": bound.port}))?;

    if scenario == Scenario::Fault(Fault::NeverReady) {
        let result = wait_ready(&mut sidecar, bound.port, deadline).await;
        if result != Err("readiness timeout") {
            let _ = force_group_stop(&mut sidecar, &recorder).await;
            return Err("never-ready fault did not time out");
        }
        recorder.record("readiness_deadline_enforced", json!({}))?;
        let status = force_group_stop(&mut sidecar, &recorder).await?;
        recorder.record("sidecar_reaped", status_fields(&status))?;
        recorder.record("secret_scan_clean", json!({"clean": true}))?;
        return Ok(());
    }

    wait_ready(&mut sidecar, bound.port, deadline).await?;
    recorder.record("ready_authenticated", json!({"port": bound.port}))?;

    if scenario == Scenario::Fault(Fault::CrashAfterReady) {
        let status = sidecar.terminated(STARTUP_LIMIT).await?;
        if status.code == Some(0) {
            return Err("crash-after-ready exited successfully");
        }
        recorder.record("expected_crash_after_ready", status_fields(&status))?;
        recorder.record("secret_scan_clean", json!({"clean": true}))?;
        return Ok(());
    }

    if scenario == Scenario::Duplicate {
        let duplicate_deadline = Instant::now() + STARTUP_LIMIT;
        while DUPLICATE_ACTIVATIONS.load(Ordering::Acquire) == 0 {
            if Instant::now() >= duplicate_deadline {
                let _ = force_group_stop(&mut sidecar, &recorder).await;
                return Err("duplicate activation not observed");
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        recorder.record(
            "duplicate_routed_to_primary",
            json!({"activations": DUPLICATE_ACTIVATIONS.load(Ordering::Relaxed)}),
        )?;
    }

    if scenario == Scenario::ParentCrash {
        recorder.record("awaiting_parent_sigkill", json!({"stdin_lease": true}))?;
        std::future::pending::<()>().await;
        return Err("parent crash sentinel unexpectedly resumed");
    }

    let shutdown_token = sidecar.token.clone();
    sidecar.write(&Shutdown {
        v: PROTOCOL_VERSION,
        kind: "shutdown".to_owned(),
        token: shutdown_token,
    })?;
    recorder.record("shutdown_sent", json!({}))?;
    let status = match sidecar.terminated(FIXTURE_SHUTDOWN_GRACE).await {
        Ok(status) => status,
        Err("sidecar termination timeout") | Err("sidecar event timeout")
            if scenario == Scenario::Fault(Fault::IgnoreShutdown) =>
        {
            recorder.record("shutdown_grace_expired", json!({}))?;
            force_group_stop(&mut sidecar, &recorder).await?
        }
        Err(error) => return Err(error),
    };
    if scenario != Scenario::Fault(Fault::IgnoreShutdown) && status.code != Some(0) {
        return Err("cooperative shutdown failed");
    }
    recorder.record("sidecar_reaped", status_fields(&status))?;
    recorder.record("secret_scan_clean", json!({"clean": true}))?;
    Ok(())
}

fn required_env(name: &str) -> Result<String, &'static str> {
    std::env::var(name).map_err(|_| "required configuration missing")
}

fn main() {
    let root = match required_env("ARXMCP_SPIKE_DATA_DIR").map(PathBuf::from) {
        Ok(root) => root,
        Err(_) => std::process::exit(2),
    };
    let run_id = match required_env("ARXMCP_SPIKE_RUN_ID") {
        Ok(value) if !value.is_empty() && value.len() <= 128 => value,
        _ => std::process::exit(2),
    };
    let scenario =
        match required_env("ARXMCP_SPIKE_SCENARIO").and_then(|value| Scenario::parse(&value)) {
            Ok(value) => value,
            Err(_) => std::process::exit(2),
        };
    let recorder = match Recorder::new(&root, run_id, scenario) {
        Ok(value) => value,
        Err(_) => std::process::exit(2),
    };
    let duplicate_recorder = recorder.clone();

    let result = tauri::Builder::default()
        // The single-instance plugin is intentionally first: no sidecar-capable
        // plugin or setup callback is registered before duplicate arbitration.
        .plugin(tauri_plugin_single_instance::init(move |_, _argv, _cwd| {
            DUPLICATE_ACTIVATIONS.fetch_add(1, Ordering::Release);
            let _ = duplicate_recorder.record("duplicate_activation", json!({}));
        }))
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let handle = app.handle().clone();
            let task_recorder = recorder.clone();
            let task_root = root.clone();
            tauri::async_runtime::spawn(async move {
                let result =
                    run_cycle(handle.clone(), task_root, scenario, task_recorder.clone()).await;
                let exit_code = if result.is_ok() { 0 } else { 1 };
                let _ = task_recorder.record(
                    "host_completed",
                    json!({"ok": result.is_ok(), "error": result.err()}),
                );
                handle.exit(exit_code);
            });
            Ok(())
        })
        .run(tauri::generate_context!());
    if result.is_err() {
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::{request, Probe, Scenario, SIDECAR_NAME};
    use arxmcp_desktop_lifecycle_spike::Fault;
    use std::io::{Read, Write};
    use std::net::{Ipv4Addr, TcpListener};

    #[test]
    fn scenario_parser_covers_host_and_fixture_modes() {
        assert_eq!(Scenario::parse("duplicate"), Ok(Scenario::Duplicate));
        assert_eq!(Scenario::parse("parent-crash"), Ok(Scenario::ParentCrash));
        assert_eq!(
            Scenario::parse("ignore-shutdown"),
            Ok(Scenario::Fault(Fault::IgnoreShutdown))
        );
        assert_eq!(
            Scenario::parse("startup-timeout"),
            Ok(Scenario::Fault(Fault::StartupTimeout))
        );
        assert!(Scenario::parse("unknown").is_err());
    }

    #[test]
    fn sidecar_name_contains_compiled_target_triple() {
        assert!(SIDECAR_NAME.starts_with("fixture-sidecar-"));
        assert!(SIDECAR_NAME.len() > "fixture-sidecar-".len());
    }

    #[test]
    fn probe_requires_exact_health_response() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind test listener");
        let port = listener.local_addr().expect("test address").port();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept request");
            let mut request = [0_u8; 512];
            let _ = stream.read(&mut request).expect("read request");
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}",
                )
                .expect("write response");
        });
        assert_eq!(request(port, "/healthz", None), Probe::Health);
        server.join().expect("join probe server");
    }
}

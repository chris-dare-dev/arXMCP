use getrandom::fill;
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

const FRAME_LIMIT: usize = 4096;
const STARTUP_LIMIT: Duration = Duration::from_secs(3);
static DUPLICATE_ACTIVATIONS: AtomicU64 = AtomicU64::new(0);

#[derive(Serialize)]
struct Bootstrap<'a> {
    v: u8,
    kind: &'static str,
    token: &'a str,
    data_root: &'a Path,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Bound {
    v: u8,
    seq: u8,
    kind: String,
    pid: u32,
    host: String,
    port: u16,
}

fn token() -> Result<String, &'static str> {
    let mut bytes = [0_u8; 32];
    fill(&mut bytes).map_err(|_| "secure randomness unavailable")?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn validate_bound(line: &[u8], pid: u32) -> Result<u16, &'static str> {
    if line.len() > FRAME_LIMIT {
        return Err("oversized bound frame");
    }
    let frame: Bound = serde_json::from_slice(line).map_err(|_| "malformed bound frame")?;
    if frame.v != 1 || frame.seq != 1 || frame.kind != "bound" || frame.pid != pid {
        return Err("invalid bound identity");
    }
    if frame.host != "127.0.0.1" || frame.port == 0 {
        return Err("non-loopback bound endpoint");
    }
    Ok(frame.port)
}

fn request(port: u16, path: &str, token: Option<&str>) -> bool {
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    let Ok(mut stream) = TcpStream::connect_timeout(&address.into(), Duration::from_millis(100))
    else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(100)));
    let capability = token
        .map(|value| format!("X-ArXMCP-Capability: {value}\r\n"))
        .unwrap_or_default();
    let request =
        format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n{capability}Connection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = Vec::new();
    stream.take(1024).read_to_end(&mut response).is_ok() && response.starts_with(b"HTTP/1.1 200")
}

async fn run_cycle(
    app: tauri::AppHandle,
    sidecar: PathBuf,
    root: PathBuf,
) -> Result<(), &'static str> {
    let secret = token()?;
    let (mut events, mut child) = app
        .shell()
        .command(sidecar)
        .env_clear()
        .env("ARXMCP_DATA_DIR", &root)
        .set_raw_out(true)
        .spawn()
        .map_err(|_| "sidecar spawn failed")?;
    let pid = child.pid();
    let mut init = serde_json::to_vec(&Bootstrap {
        v: 1,
        kind: "init",
        token: &secret,
        data_root: &root,
    })
    .map_err(|_| "bootstrap encoding failed")?;
    init.push(b'\n');
    child.write(&init).map_err(|_| "bootstrap write failed")?;

    let deadline = Instant::now() + STARTUP_LIMIT;
    let mut stdout = Vec::new();
    let port = loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let event = tokio::time::timeout(remaining, events.recv())
            .await
            .map_err(|_| "bound frame timeout")?
            .ok_or("sidecar event stream closed")?;
        match event {
            CommandEvent::Stdout(bytes) => {
                if stdout.len() + bytes.len() > FRAME_LIMIT {
                    return Err("oversized protocol output");
                }
                stdout.extend(bytes);
                if let Some(index) = stdout.iter().position(|byte| *byte == b'\n') {
                    break validate_bound(&stdout[..index], pid)?;
                }
            }
            CommandEvent::Terminated(_) => return Err("sidecar exited before bound"),
            CommandEvent::Error(_) => return Err("sidecar event error"),
            CommandEvent::Stderr(bytes) if bytes.len() > FRAME_LIMIT => {
                return Err("oversized sidecar diagnostics")
            }
            _ => {}
        }
    };
    if !request(port, "/healthz", None) {
        return Err("health probe failed");
    }
    while Instant::now() < deadline && !request(port, "/readyz", Some(&secret)) {
        std::thread::sleep(Duration::from_millis(20));
    }
    if Instant::now() >= deadline {
        child.kill().map_err(|_| "timeout kill failed")?;
        return Err("readiness timeout");
    }
    let shutdown = serde_json::json!({"v": 1, "kind": "shutdown", "token": secret});
    let mut bytes = serde_json::to_vec(&shutdown).map_err(|_| "shutdown encoding failed")?;
    bytes.push(b'\n');
    child.write(&bytes).map_err(|_| "shutdown write failed")?;
    loop {
        match tokio::time::timeout(Duration::from_secs(2), events.recv()).await {
            Ok(Some(CommandEvent::Terminated(status))) if status.code == Some(0) => return Ok(()),
            Ok(Some(CommandEvent::Terminated(_))) => return Err("sidecar stop failed"),
            Ok(Some(_)) => {}
            _ => return Err("sidecar termination timeout"),
        }
    }
}

fn main() {
    let sidecar = std::env::var_os("ARXMCP_SPIKE_SIDECAR").map(PathBuf::from);
    let root = std::env::var_os("ARXMCP_SPIKE_DATA_DIR").map(PathBuf::from);
    let (Some(sidecar), Some(root)) = (sidecar, root) else {
        eprintln!(r#"{{"event":"configuration_missing"}}"#);
        std::process::exit(2);
    };
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|_, _, _| {
            DUPLICATE_ACTIVATIONS.fetch_add(1, Ordering::Relaxed);
            eprintln!(r#"{{"event":"duplicate_activation"}}"#);
        }))
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let exit = if run_cycle(handle.clone(), sidecar, root).await.is_ok() {
                    0
                } else {
                    1
                };
                handle.exit(exit);
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .unwrap_or_else(|_| std::process::exit(1));
}

#[cfg(test)]
mod tests {
    use super::validate_bound;

    #[test]
    fn bound_validation_rejects_wildcard_and_wrong_pid() {
        let wildcard = br#"{"v":1,"seq":1,"kind":"bound","pid":7,"host":"0.0.0.0","port":8}"#;
        let wrong_pid = br#"{"v":1,"seq":1,"kind":"bound","pid":8,"host":"127.0.0.1","port":9}"#;
        assert!(validate_bound(wildcard, 7).is_err());
        assert!(validate_bound(wrong_pid, 7).is_err());
    }
}

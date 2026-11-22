use arxmcp_desktop_lifecycle_spike::{
    read_frame, valid_token, validate_bind_host, Bootstrap, Bound, Fault, Shutdown, FRAME_LIMIT,
    PROTOCOL_VERSION,
};
use fs2::FileExt;
use serde::Serialize;
use std::fs::{self, OpenOptions};
use std::io::{self, BufReader, Read, Write};
use std::net::{Ipv4Addr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

const READY_DELAY: Duration = Duration::from_millis(150);
const CRASH_BEFORE_BOUND_DELAY: Duration = Duration::from_millis(100);
const CRASH_AFTER_READY_DELAY: Duration = Duration::from_millis(100);
const SOURCE_SHA256: &str = env!("ARXMCP_SPIKE_SOURCE_SHA256");

#[derive(Serialize)]
struct ListenerMeta<'a> {
    v: u8,
    pid: u32,
    pgid: u32,
    canary_pid: u32,
    host: &'a str,
    port: u16,
}

enum LeaseEvent {
    Shutdown,
    Closed,
}

struct Canary {
    child: Child,
}

impl Canary {
    fn spawn() -> Result<Self, &'static str> {
        let executable = std::env::current_exe().map_err(|_| "canary path unavailable")?;
        let child = Command::new(executable)
            .arg("--canary")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "canary spawn failed")?;
        Ok(Self { child })
    }

    fn pid(&self) -> u32 {
        self.child.id()
    }
}

impl Drop for Canary {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn run_canary() -> ! {
    loop {
        std::thread::park_timeout(Duration::from_secs(60));
    }
}

fn response(mut stream: TcpStream, ready: bool, token: &str) {
    let _ = stream.set_read_timeout(Some(Duration::from_millis(100)));
    let mut request = Vec::new();
    let mut chunk = [0_u8; 512];
    loop {
        let Ok(count) = stream.read(&mut chunk) else {
            return;
        };
        if count == 0 || request.len() + count > FRAME_LIMIT {
            return;
        }
        request.extend_from_slice(&chunk[..count]);
        if request.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
    }
    let text = String::from_utf8_lossy(&request);
    let health = text.starts_with("GET /healthz HTTP/1.1\r\n");
    let capability = format!("\r\nX-ArXMCP-Capability: {token}\r\n");
    let authorized_ready =
        ready && text.starts_with("GET /readyz HTTP/1.1\r\n") && text.contains(&capability);
    let (status, body) = if health {
        ("200 OK", r#"{"status":"ok"}"#)
    } else if authorized_ready {
        ("200 OK", r#"{"status":"ready"}"#)
    } else {
        ("503 Service Unavailable", r#"{"status":"starting"}"#)
    };
    let reply = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(reply.as_bytes());
}

fn write_bound(bound: &Bound, fault: Fault) -> Result<(), &'static str> {
    let mut output = io::stdout().lock();
    match fault {
        Fault::MalformedBound => output
            .write_all(b"{\"v\":1,\"seq\":1,\"kind\":\"bound\"\n")
            .map_err(|_| "malformed frame write failed")?,
        _ => {
            serde_json::to_writer(&mut output, bound).map_err(|_| "bound frame write failed")?;
            output
                .write_all(b"\n")
                .map_err(|_| "bound frame write failed")?;
        }
    }
    output.flush().map_err(|_| "bound frame flush failed")
}

fn configure_group(ignore_shutdown: bool) -> Result<(), &'static str> {
    // SAFETY: setpgid(0, 0) changes only this child into its own process-group
    // leader before it creates the same-group canary.
    if unsafe { libc::setpgid(0, 0) } != 0 {
        return Err("process group setup failed");
    }
    if ignore_shutdown {
        // SAFETY: the ignore-shutdown fixture deliberately installs SIG_IGN before
        // spawning the canary so the whole group requires the SIGKILL escalation.
        if unsafe { libc::signal(libc::SIGTERM, libc::SIG_IGN) } == libc::SIG_ERR {
            return Err("signal fixture setup failed");
        }
    }
    Ok(())
}

fn parse_bootstrap(
    input: &mut BufReader<io::Stdin>,
    expected_root: &PathBuf,
) -> Result<Bootstrap, &'static str> {
    let bytes = read_frame(input)
        .map_err(|_| "bootstrap frame rejected")?
        .ok_or("bootstrap EOF")?;
    let init: Bootstrap = serde_json::from_slice(&bytes).map_err(|_| "bootstrap frame rejected")?;
    if init.v != PROTOCOL_VERSION
        || init.kind != "init"
        || init.data_root != *expected_root
        || !valid_token(&init.token)
        || init.production_grace_ms != 35_000
        || validate_bind_host(&init.bind_host).is_err()
    {
        return Err("bootstrap frame rejected");
    }
    Ok(init)
}

fn run() -> Result<(), &'static str> {
    let expected_root = std::env::var_os("ARXMCP_SPIKE_DATA_DIR")
        .map(PathBuf::from)
        .ok_or("missing data root")?;
    fs::create_dir_all(&expected_root).map_err(|_| "data root creation failed")?;
    let mut input = BufReader::new(io::stdin());
    let init = parse_bootstrap(&mut input, &expected_root)?;
    if init.fault == Fault::StartupTimeout {
        // Deliberately stall before setpgid: the supervisor must fall back to
        // its retained direct-child PID when the PID-named group is absent.
        loop {
            std::thread::park_timeout(Duration::from_secs(60));
        }
    }
    configure_group(init.fault == Fault::IgnoreShutdown)?;

    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(expected_root.join("lifecycle.lock"))
        .map_err(|_| "lock open failed")?;
    lock.try_lock_exclusive()
        .map_err(|_| "lifecycle lock busy")?;
    let canary = Canary::spawn()?;

    let listener =
        TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).map_err(|_| "loopback bind failed")?;
    listener
        .set_nonblocking(true)
        .map_err(|_| "listener setup failed")?;
    let port = listener
        .local_addr()
        .map_err(|_| "listener address failed")?
        .port();
    let pid = std::process::id();
    let announced_host = match init.fault {
        Fault::WildcardV4 => "0.0.0.0",
        Fault::WildcardV6 => "::",
        _ => "127.0.0.1",
    };
    let bound = Bound {
        v: PROTOCOL_VERSION,
        seq: 1,
        kind: "bound".to_owned(),
        pid,
        pgid: pid,
        canary_pid: canary.pid(),
        host: announced_host.to_owned(),
        port,
    };
    let metadata = ListenerMeta {
        v: PROTOCOL_VERSION,
        pid,
        pgid: pid,
        canary_pid: canary.pid(),
        host: "127.0.0.1",
        port,
    };
    let metadata_file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(expected_root.join("listener-meta.json"))
        .map_err(|_| "listener metadata open failed")?;
    serde_json::to_writer(metadata_file, &metadata)
        .map_err(|_| "listener metadata write failed")?;
    if init.fault == Fault::CrashBeforeBound {
        std::thread::sleep(CRASH_BEFORE_BOUND_DELAY);
        std::process::abort();
    }
    if matches!(
        init.fault,
        Fault::MalformedBound | Fault::WildcardV4 | Fault::WildcardV6
    ) {
        std::thread::sleep(Duration::from_millis(100));
    }
    write_bound(&bound, init.fault)?;

    let token = init.token;
    let reader_token = token.clone();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || loop {
        match read_frame(&mut input) {
            Ok(Some(bytes)) => {
                let valid = serde_json::from_slice::<Shutdown>(&bytes)
                    .ok()
                    .is_some_and(|item| {
                        item.v == PROTOCOL_VERSION
                            && item.kind == "shutdown"
                            && item.token == reader_token
                    });
                if valid && tx.send(LeaseEvent::Shutdown).is_err() {
                    break;
                }
            }
            _ => {
                let _ = tx.send(LeaseEvent::Closed);
                break;
            }
        }
    });

    let ready_at = Instant::now() + READY_DELAY;
    let crash_at = ready_at + CRASH_AFTER_READY_DELAY;
    loop {
        match rx.try_recv() {
            Ok(LeaseEvent::Closed) => break,
            Ok(LeaseEvent::Shutdown) if init.fault != Fault::IgnoreShutdown => break,
            Ok(LeaseEvent::Shutdown) | Err(mpsc::TryRecvError::Empty) => {}
            Err(mpsc::TryRecvError::Disconnected) => break,
        }
        let now = Instant::now();
        if init.fault == Fault::CrashAfterReady && now >= crash_at {
            std::process::abort();
        }
        match listener.accept() {
            Ok((stream, _)) => {
                let ready = init.fault != Fault::NeverReady && now >= ready_at;
                response(stream, ready, &token);
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(5));
            }
            Err(_) => return Err("listener accept failed"),
        }
    }
    drop(listener);
    drop(canary);
    let mut output = io::stdout().lock();
    output
        .write_all(b"{\"v\":1,\"seq\":2,\"kind\":\"stopped\"}\n")
        .and_then(|_| output.flush())
        .map_err(|_| "stopped frame write failed")?;
    Ok(())
}

fn main() {
    match std::env::args_os().nth(1).as_deref() {
        Some(value) if value == std::ffi::OsStr::new("--provenance") => {
            println!(
                "{}",
                serde_json::json!({
                    "schema_version": 1,
                    "role": "fixture-sidecar",
                    "tauri_host": false,
                    "source_sha256": SOURCE_SHA256,
                    "dependencies": {
                        "tauri": "2.11.5",
                        "tauri-plugin-shell": "2.3.5",
                        "tauri-plugin-single-instance": "2.4.3"
                    }
                })
            );
            return;
        }
        Some(value) if value == std::ffi::OsStr::new("--canary") => run_canary(),
        _ => {}
    }
    if run().is_err() {
        eprintln!("{{\"event\":\"fixture_failed\"}}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::{response, FRAME_LIMIT};
    use std::io::{Cursor, Read, Write};
    use std::net::{Ipv4Addr, TcpListener, TcpStream};

    #[test]
    fn protocol_frame_limit_is_bounded() {
        let mut input = Cursor::new(vec![b'x'; FRAME_LIMIT + 1]);
        assert!(arxmcp_desktop_lifecycle_spike::read_frame(&mut input).is_err());
    }

    #[test]
    fn ready_requires_the_capability() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind test listener");
        let address = listener.local_addr().expect("test listener address");
        let thread = std::thread::spawn(move || {
            let (stream, _) = listener.accept().expect("accept test request");
            response(stream, true, "secret");
        });
        let mut client = TcpStream::connect(address).expect("connect test listener");
        client
            .write_all(b"GET /readyz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            .expect("write test request");
        let mut response_bytes = Vec::new();
        client
            .read_to_end(&mut response_bytes)
            .expect("read test response");
        thread.join().expect("join response thread");
        assert!(response_bytes.starts_with(b"HTTP/1.1 503 Service Unavailable"));
    }
}

use fs2::FileExt;
use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::mpsc;
use std::time::{Duration, Instant};

const FRAME_LIMIT: usize = 4096;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Bootstrap {
    v: u8,
    kind: String,
    token: String,
    data_root: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Shutdown {
    v: u8,
    kind: String,
    token: String,
}

#[derive(Serialize)]
struct Event<'a> {
    v: u8,
    seq: u8,
    kind: &'a str,
    pid: u32,
    host: &'a str,
    port: u16,
}

fn frame<R: BufRead>(reader: &mut R) -> io::Result<Option<Vec<u8>>> {
    let mut bytes = Vec::new();
    let count = reader
        .take((FRAME_LIMIT + 1) as u64)
        .read_until(b'\n', &mut bytes)?;
    if count == 0 {
        return Ok(None);
    }
    if count > FRAME_LIMIT || bytes.last() != Some(&b'\n') {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid control frame",
        ));
    }
    bytes.pop();
    Ok(Some(bytes))
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
    let reply = format!("HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
    let _ = stream.write_all(reply.as_bytes());
}

fn run() -> Result<(), &'static str> {
    if unsafe { libc::setpgid(0, 0) } != 0 {
        return Err("process group setup failed");
    }
    let expected_root = std::env::var_os("ARXMCP_DATA_DIR")
        .map(PathBuf::from)
        .ok_or("missing data root")?;
    fs::create_dir_all(&expected_root).map_err(|_| "data root creation failed")?;
    let mut input = BufReader::new(io::stdin());
    let bytes = frame(&mut input)
        .map_err(|_| "bootstrap frame rejected")?
        .ok_or("bootstrap EOF")?;
    let init: Bootstrap = serde_json::from_slice(&bytes).map_err(|_| "bootstrap frame rejected")?;
    if init.v != 1
        || init.kind != "init"
        || init.data_root != expected_root
        || init.token.len() != 64
        || !init.token.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err("bootstrap frame rejected");
    }
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(expected_root.join("lifecycle.lock"))
        .map_err(|_| "lock open failed")?;
    lock.try_lock_exclusive()
        .map_err(|_| "lifecycle lock busy")?;
    let listener =
        TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).map_err(|_| "loopback bind failed")?;
    listener
        .set_nonblocking(true)
        .map_err(|_| "listener setup failed")?;
    let port = listener
        .local_addr()
        .map_err(|_| "listener address failed")?
        .port();
    serde_json::to_writer(
        io::stdout(),
        &Event {
            v: 1,
            seq: 1,
            kind: "bound",
            pid: std::process::id(),
            host: "127.0.0.1",
            port,
        },
    )
    .map_err(|_| "bound frame write failed")?;
    println!();

    let secret = init.token;
    let reader_secret = secret.clone();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || loop {
        match frame(&mut input) {
            Ok(Some(bytes)) => {
                let valid = serde_json::from_slice::<Shutdown>(&bytes)
                    .ok()
                    .is_some_and(|item| {
                        item.v == 1 && item.kind == "shutdown" && item.token == reader_secret
                    });
                if valid {
                    let _ = tx.send(());
                    break;
                }
            }
            _ => {
                let _ = tx.send(());
                break;
            }
        }
    });
    let ready_at = Instant::now() + Duration::from_millis(75);
    loop {
        if rx.try_recv().is_ok() {
            break;
        }
        match listener.accept() {
            Ok((stream, _)) => response(stream, Instant::now() >= ready_at, &secret),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(5));
            }
            Err(_) => return Err("listener accept failed"),
        }
    }
    drop(listener);
    println!(r#"{{"v":1,"seq":2,"kind":"stopped"}}"#);
    Ok(())
}

fn main() {
    if run().is_err() {
        eprintln!(r#"{{"event":"fixture_failed"}}"#);
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::{frame, FRAME_LIMIT};
    use std::io::Cursor;

    #[test]
    fn frame_reader_rejects_unbounded_input() {
        let mut input = Cursor::new(vec![b'x'; FRAME_LIMIT + 1]);
        assert!(frame(&mut input).is_err());
    }
}

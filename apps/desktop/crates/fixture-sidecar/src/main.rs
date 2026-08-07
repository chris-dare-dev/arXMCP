use arxmcp_desktop_contract::{
    encode_frame, parse_frame, read_frame, Bound, ContractError, ContractVersion, Endpoint,
    ExecutableIdentity, Extensions, Frame, Launch, Shutdown, ShutdownSemantics, StartupToken,
    HEALTH_PATH, MCP_PATH, READINESS_PATH, STARTUP_TOKEN_HEADER, UI_PATH,
};
use std::fmt;
use std::fs;
use std::io::{self, BufReader, Read, Write};
use std::net::{Ipv4Addr, TcpListener, TcpStream};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::Duration;

const COMPONENT: &str = "arxmcp-fixture-sidecar";
const POLL_INTERVAL: Duration = Duration::from_millis(5);
const HTTP_READ_TIMEOUT: Duration = Duration::from_millis(200);

#[derive(Debug)]
enum SidecarError {
    Arguments,
    MissingLaunch,
    Identity,
    DataRoot,
    Bind,
    Control(ContractError),
    Io,
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
    validate_fixture_launch(&launch)?;

    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).map_err(|_| SidecarError::Bind)?;
    listener
        .set_nonblocking(true)
        .map_err(|_| SidecarError::Bind)?;
    let address = listener.local_addr().map_err(|_| SidecarError::Bind)?;
    if address.ip().to_string() != "127.0.0.1" || address.port() == 0 {
        return Err(SidecarError::Bind);
    }

    let bound = make_bound(&launch, address.port());
    let encoded = encode_frame(&Frame::Bound(bound))?;
    let mut output = io::stdout().lock();
    output.write_all(&encoded).map_err(|_| SidecarError::Io)?;
    output.flush().map_err(|_| SidecarError::Io)?;
    drop(output);

    let token = launch.startup_token.clone();
    let receiver =
        spawn_control_reader(control_input, launch.contract.clone(), launch.startup_token);
    serve_until_stopped(listener, receiver, &token)
}

fn validate_fixture_launch(launch: &Launch) -> Result<(), SidecarError> {
    if launch.executable.component != COMPONENT
        || launch.executable.version != env!("CARGO_PKG_VERSION")
    {
        return Err(SidecarError::Identity);
    }
    let canonical_root = fs::canonicalize(&launch.data_root).map_err(|_| SidecarError::DataRoot)?;
    let log_parent = launch.log_location.parent().ok_or(SidecarError::DataRoot)?;
    let canonical_log_parent = fs::canonicalize(log_parent).map_err(|_| SidecarError::DataRoot)?;
    if canonical_root != launch.data_root || !canonical_log_parent.starts_with(&canonical_root) {
        return Err(SidecarError::DataRoot);
    }
    Ok(())
}

fn make_bound(launch: &Launch, port: u16) -> Bound {
    let authority = format!("http://127.0.0.1:{port}");
    Bound {
        contract: launch.contract.clone(),
        data_root: launch.data_root.clone(),
        endpoint: Endpoint {
            host: "127.0.0.1".to_owned(),
            port,
        },
        executable: ExecutableIdentity {
            component: COMPONENT.to_owned(),
            sha256: launch.executable.sha256.clone(),
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
) -> Result<(), SidecarError> {
    loop {
        match receiver.try_recv() {
            Ok(LeaseEvent::Shutdown | LeaseEvent::Eof) => return Ok(()),
            Ok(LeaseEvent::Invalid) | Err(TryRecvError::Empty) => {}
            Err(TryRecvError::Disconnected) => return Ok(()),
        }

        match listener.accept() {
            Ok((stream, _address)) => respond(stream, token),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                std::thread::sleep(POLL_INTERVAL);
            }
            Err(_) => return Err(SidecarError::Bind),
        }
    }
}

fn respond(mut stream: TcpStream, token: &StartupToken) {
    let _ = stream.set_read_timeout(Some(HTTP_READ_TIMEOUT));
    let mut request = Vec::new();
    let mut chunk = [0_u8; 512];
    loop {
        let Ok(count) = stream.read(&mut chunk) else {
            return;
        };
        if count == 0 || request.len() + count > 4_096 {
            return;
        }
        request.extend_from_slice(&chunk[..count]);
        if request.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
    }

    let Ok(text) = std::str::from_utf8(&request) else {
        return;
    };
    let mut lines = text.split("\r\n");
    let request_line = lines.next().unwrap_or_default();
    let supplied_token = lines
        .filter_map(|line| line.split_once(':'))
        .find_map(|(name, value)| {
            name.eq_ignore_ascii_case(STARTUP_TOKEN_HEADER)
                .then(|| value.trim())
        });
    let authorized = supplied_token.is_some_and(|supplied| {
        constant_time_equal(supplied.as_bytes(), token.expose().as_bytes())
    });

    let (status, body) = if request_line == "GET /healthz HTTP/1.1" {
        ("200 OK", r#"{"status":"ok"}"#)
    } else if request_line == "GET /readyz HTTP/1.1" && authorized {
        ("200 OK", r#"{"status":"ready"}"#)
    } else if request_line == "GET /readyz HTTP/1.1" {
        ("401 Unauthorized", r#"{"status":"unauthorized"}"#)
    } else {
        ("404 Not Found", r#"{"status":"not-found"}"#)
    };
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes());
}

//! Minimal blocking loopback HTTP/1.1 client for probes and the MCP smoke.
//! `Connection: close` on every request; the body is read to EOF, bounded.
//! The startup capability travels ONLY as the `X-ArXMCP-Startup-Token`
//! request header; it never appears in URLs or in returned errors.

use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::time::Duration;

const RESPONSE_LIMIT: usize = 4 * 1024 * 1024;

pub struct Response {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl Response {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(key, _)| key.eq_ignore_ascii_case(name))
            .map(|(_, value)| value.as_str())
    }
}

pub fn request(
    port: u16,
    method: &str,
    path: &str,
    headers: &[(&str, &str)],
    body: Option<&[u8]>,
    timeout: Duration,
) -> Result<Response, &'static str> {
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    let mut stream =
        TcpStream::connect_timeout(&address.into(), timeout).map_err(|_| "connect failed")?;
    stream
        .set_read_timeout(Some(timeout))
        .map_err(|_| "socket configuration failed")?;
    stream
        .set_write_timeout(Some(timeout))
        .map_err(|_| "socket configuration failed")?;

    let mut request = format!("{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n");
    for (name, value) in headers {
        request.push_str(&format!("{name}: {value}\r\n"));
    }
    let payload = body.unwrap_or(&[]);
    if body.is_some() {
        request.push_str(&format!("Content-Length: {}\r\n", payload.len()));
    }
    request.push_str("Connection: close\r\n\r\n");
    stream
        .write_all(request.as_bytes())
        .and_then(|_| stream.write_all(payload))
        .map_err(|_| "request write failed")?;

    let mut raw = Vec::new();
    stream
        .take(RESPONSE_LIMIT as u64 + 1)
        .read_to_end(&mut raw)
        .map_err(|_| "response read failed")?;
    if raw.len() > RESPONSE_LIMIT {
        return Err("response exceeds bound");
    }
    parse_response(&raw)
}

pub fn parse_response(raw: &[u8]) -> Result<Response, &'static str> {
    let split = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or("response missing header terminator")?;
    let head = std::str::from_utf8(&raw[..split]).map_err(|_| "response head not UTF-8")?;
    let mut lines = head.split("\r\n");
    let status_line = lines.next().ok_or("response missing status line")?;
    let mut parts = status_line.splitn(3, ' ');
    if parts.next() != Some("HTTP/1.1") {
        return Err("unsupported HTTP version");
    }
    let status: u16 = parts
        .next()
        .and_then(|code| code.parse().ok())
        .ok_or("unparseable status code")?;
    let headers = lines
        .filter_map(|line| line.split_once(':'))
        .map(|(name, value)| (name.trim().to_owned(), value.trim().to_owned()))
        .collect();
    Ok(Response {
        status,
        headers,
        body: raw[split + 4..].to_vec(),
    })
}

#[cfg(test)]
mod tests {
    use super::parse_response;

    #[test]
    fn parses_status_headers_and_body() {
        let raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nMcp-Session-Id: abc123\r\n\r\n{\"ok\":true}";
        let response = parse_response(raw).expect("well-formed response parses");
        assert_eq!(response.status, 200);
        assert_eq!(response.header("mcp-session-id"), Some("abc123"));
        assert_eq!(response.body, b"{\"ok\":true}");
    }

    #[test]
    fn rejects_torn_responses() {
        assert!(parse_response(b"HTTP/1.1 200 OK\r\nNo-Terminator: yes").is_err());
        assert!(parse_response(b"SPDY/9 200\r\n\r\n").is_err());
    }
}

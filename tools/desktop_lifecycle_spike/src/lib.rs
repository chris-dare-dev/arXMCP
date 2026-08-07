use getrandom::fill;
use serde::{Deserialize, Serialize};
use std::io::{self, BufRead, Read};
use std::path::PathBuf;
use std::str::FromStr;

pub const FRAME_LIMIT: usize = 4096;
pub const PROTOCOL_VERSION: u8 = 1;
pub const TOKEN_CANARY: &str = "ARXMCP_SECRET_CANARY:";
pub const PRODUCTION_GRACE_MS: u64 = 35_000;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "kebab-case")]
pub enum Fault {
    Normal,
    StartupTimeout,
    NeverReady,
    MalformedBound,
    WildcardV4,
    WildcardV6,
    CrashBeforeBound,
    CrashAfterReady,
    IgnoreShutdown,
}

impl FromStr for Fault {
    type Err = ();

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "normal" => Ok(Self::Normal),
            "startup-timeout" => Ok(Self::StartupTimeout),
            "never-ready" => Ok(Self::NeverReady),
            "malformed-bound" => Ok(Self::MalformedBound),
            "wildcard-v4" => Ok(Self::WildcardV4),
            "wildcard-v6" => Ok(Self::WildcardV6),
            "crash-before-bound" => Ok(Self::CrashBeforeBound),
            "crash-after-ready" => Ok(Self::CrashAfterReady),
            "ignore-shutdown" => Ok(Self::IgnoreShutdown),
            _ => Err(()),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Bootstrap {
    pub v: u8,
    pub kind: String,
    pub token: String,
    pub data_root: PathBuf,
    pub bind_host: String,
    pub fault: Fault,
    pub production_grace_ms: u64,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Shutdown {
    pub v: u8,
    pub kind: String,
    pub token: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Bound {
    pub v: u8,
    pub seq: u8,
    pub kind: String,
    pub pid: u32,
    pub pgid: u32,
    pub canary_pid: u32,
    pub host: String,
    pub port: u16,
}

pub fn startup_token() -> Result<String, &'static str> {
    let mut bytes = [0_u8; 32];
    fill(&mut bytes).map_err(|_| "secure randomness unavailable")?;
    let random: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    Ok(format!("{TOKEN_CANARY}{random}"))
}

pub fn valid_token(value: &str) -> bool {
    value.strip_prefix(TOKEN_CANARY).is_some_and(|random| {
        random.len() == 64 && random.bytes().all(|byte| byte.is_ascii_hexdigit())
    })
}

pub fn validate_bind_host(value: &str) -> Result<(), &'static str> {
    if value != "127.0.0.1" {
        return Err("non-loopback bind rejected");
    }
    Ok(())
}

pub fn validate_bound(line: &[u8], expected_pid: u32) -> Result<Bound, &'static str> {
    if line.len() > FRAME_LIMIT {
        return Err("oversized bound frame");
    }
    let frame: Bound = serde_json::from_slice(line).map_err(|_| "malformed bound frame")?;
    if frame.v != PROTOCOL_VERSION
        || frame.seq != 1
        || frame.kind != "bound"
        || frame.pid != expected_pid
        || frame.pgid != expected_pid
        || frame.canary_pid == 0
        || frame.canary_pid == expected_pid
    {
        return Err("invalid bound identity");
    }
    validate_bind_host(&frame.host)?;
    if frame.port == 0 {
        return Err("invalid bound port");
    }
    Ok(frame)
}

pub fn read_frame<R: BufRead>(reader: &mut R) -> io::Result<Option<Vec<u8>>> {
    let mut bytes = Vec::new();
    let count = reader
        .by_ref()
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn bound(host: &str) -> Vec<u8> {
        serde_json::to_vec(&Bound {
            v: 1,
            seq: 1,
            kind: "bound".into(),
            pid: 7,
            pgid: 7,
            canary_pid: 8,
            host: host.into(),
            port: 9,
        })
        .expect("serialize test bound")
    }

    #[test]
    fn bound_validation_rejects_wildcards_and_wrong_identity() {
        assert!(validate_bound(&bound("0.0.0.0"), 7).is_err());
        assert!(validate_bound(&bound("::"), 7).is_err());
        assert!(validate_bound(&bound("127.0.0.1"), 8).is_err());
    }

    #[test]
    fn token_has_canary_and_full_entropy_payload() {
        let token = startup_token().expect("create startup token");
        assert!(valid_token(&token));
        assert_eq!(token.len(), TOKEN_CANARY.len() + 64);
    }

    #[test]
    fn frame_reader_rejects_unbounded_input() {
        let mut input = Cursor::new(vec![b'x'; FRAME_LIMIT + 1]);
        assert!(read_frame(&mut input).is_err());
    }
}

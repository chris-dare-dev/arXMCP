//! Versioned, bounded desktop/server control protocol.
//!
//! The secret-bearing launch capability travels only in supervisor-to-child
//! NDJSON frames.  The child-to-supervisor `bound` manifest is deliberately
//! token-free and may be persisted for diagnostics.

use getrandom::fill;
use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::fmt;
use std::io::{self, BufRead, Read};
use std::path::{Component, Path, PathBuf};

pub const FRAME_LIMIT: usize = 4_096;
pub const SUPPORTED_MAJOR: u16 = 1;
pub const MIN_GRACE_MS: u64 = 35_000;
pub const STARTUP_TOKEN_HEADER: &str = "X-ArXMCP-Startup-Token";
pub const HEALTH_PATH: &str = "/healthz";
pub const READINESS_PATH: &str = "/readyz";
pub const MCP_PATH: &str = "/mcp";
pub const UI_PATH: &str = "/ui/";

const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const MAX_JSON_DEPTH: usize = 32;
const MAX_EXTENSION_KEYS: usize = 32;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ContractError {
    FrameTooLarge,
    MissingNewline,
    InvalidEncoding,
    InvalidJson,
    DuplicateKey,
    UnsupportedMajor(u64),
    InvalidFrame(&'static str),
    InvalidSequence,
    RandomnessUnavailable,
    Io,
}

impl fmt::Display for ContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::FrameTooLarge => formatter.write_str("control frame exceeds 4096 bytes"),
            Self::MissingNewline => formatter.write_str("control frame must end with one LF"),
            Self::InvalidEncoding => formatter.write_str("control frame is not valid UTF-8"),
            Self::InvalidJson => formatter.write_str("control frame is not valid canonical JSON"),
            Self::DuplicateKey => formatter.write_str("control frame contains a duplicate key"),
            Self::UnsupportedMajor(major) => {
                write!(formatter, "unsupported desktop contract major {major}")
            }
            Self::InvalidFrame(reason) => write!(formatter, "invalid control frame: {reason}"),
            Self::InvalidSequence => formatter.write_str("invalid control-frame sequence"),
            Self::RandomnessUnavailable => formatter.write_str("secure randomness unavailable"),
            Self::Io => formatter.write_str("control-channel I/O failed"),
        }
    }
}

impl std::error::Error for ContractError {}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct StartupToken(String);

impl StartupToken {
    pub fn parse(value: String) -> Result<Self, ContractError> {
        if value.len() != 64
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(ContractError::InvalidFrame("invalid startup token"));
        }
        Ok(Self(value))
    }

    pub fn expose(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for StartupToken {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("StartupToken([REDACTED])")
    }
}

pub fn generate_startup_token() -> Result<StartupToken, ContractError> {
    let mut random = [0_u8; 32];
    fill(&mut random).map_err(|_| ContractError::RandomnessUnavailable)?;
    let mut encoded = String::with_capacity(64);
    for byte in random {
        use std::fmt::Write as _;
        write!(&mut encoded, "{byte:02x}").map_err(|_| ContractError::RandomnessUnavailable)?;
    }
    StartupToken::parse(encoded)
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContractVersion {
    pub major: u16,
    pub minor: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutableIdentity {
    pub component: String,
    pub sha256: String,
    pub version: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Endpoint {
    pub host: String,
    pub port: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProbePaths {
    pub health: String,
    pub mcp: String,
    pub readiness: String,
    pub ui: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ShutdownSemantics {
    pub force_after_ms: u64,
    pub grace_ms: u64,
    pub parent_lifetime: String,
    pub reap: String,
}

pub type Extensions = BTreeMap<String, Value>;

#[derive(Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Launch {
    pub contract: ContractVersion,
    pub data_root: PathBuf,
    pub endpoint_request: Endpoint,
    pub executable: ExecutableIdentity,
    pub extensions: Extensions,
    pub kind: String,
    pub log_location: PathBuf,
    pub probe_paths: ProbePaths,
    pub shutdown: ShutdownSemantics,
    pub startup_token: StartupToken,
}

impl fmt::Debug for Launch {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Launch")
            .field("contract", &self.contract)
            .field("data_root", &self.data_root)
            .field("endpoint_request", &self.endpoint_request)
            .field("executable", &self.executable)
            .field("extensions", &self.extensions)
            .field("kind", &self.kind)
            .field("log_location", &self.log_location)
            .field("probe_paths", &self.probe_paths)
            .field("shutdown", &self.shutdown)
            .field("startup_token", &self.startup_token)
            .finish()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bound {
    pub contract: ContractVersion,
    pub data_root: PathBuf,
    pub endpoint: Endpoint,
    pub executable: ExecutableIdentity,
    pub extensions: Extensions,
    pub health_url: String,
    pub kind: String,
    pub log_location: PathBuf,
    pub mcp_url: String,
    pub readiness_url: String,
    pub shutdown: ShutdownSemantics,
    pub ui_url: String,
}

#[derive(Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Shutdown {
    pub contract: ContractVersion,
    pub extensions: Extensions,
    pub kind: String,
    pub startup_token: StartupToken,
}

impl fmt::Debug for Shutdown {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Shutdown")
            .field("contract", &self.contract)
            .field("extensions", &self.extensions)
            .field("kind", &self.kind)
            .field("startup_token", &self.startup_token)
            .finish()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Frame {
    Launch(Launch),
    Bound(Bound),
    Shutdown(Shutdown),
}

impl Frame {
    pub fn contract(&self) -> &ContractVersion {
        match self {
            Self::Launch(frame) => &frame.contract,
            Self::Bound(frame) => &frame.contract,
            Self::Shutdown(frame) => &frame.contract,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ChildControlState {
    #[default]
    AwaitingLaunch,
    Running,
    Stopped,
}

impl ChildControlState {
    pub fn accept(&mut self, frame: &Frame) -> Result<(), ContractError> {
        match (*self, frame) {
            (Self::AwaitingLaunch, Frame::Launch(_)) => *self = Self::Running,
            (Self::Running, Frame::Shutdown(_)) => *self = Self::Stopped,
            _ => return Err(ContractError::InvalidSequence),
        }
        Ok(())
    }
}

pub fn parse_frame(frame: &[u8]) -> Result<Frame, ContractError> {
    let payload = frame_payload(frame)?;
    let mut deserializer = serde_json::Deserializer::from_slice(payload);
    let unique = UniqueValue::deserialize(&mut deserializer).map_err(map_json_error)?;
    deserializer.end().map_err(|_| ContractError::InvalidJson)?;
    validate_json_value(&unique.0, 0)?;

    let object = unique.0.as_object().ok_or(ContractError::InvalidFrame(
        "top-level JSON must be an object",
    ))?;
    preflight_major(object)?;
    let kind = object
        .get("kind")
        .and_then(Value::as_str)
        .ok_or(ContractError::InvalidFrame("missing frame kind"))?;

    match kind {
        "launch" => {
            let value: Launch = serde_json::from_value(unique.0)
                .map_err(|_| ContractError::InvalidFrame("malformed launch frame"))?;
            validate_launch(&value)?;
            Ok(Frame::Launch(value))
        }
        "bound" => {
            let value: Bound = serde_json::from_value(unique.0)
                .map_err(|_| ContractError::InvalidFrame("malformed bound frame"))?;
            validate_bound(&value)?;
            Ok(Frame::Bound(value))
        }
        "shutdown" => {
            let value: Shutdown = serde_json::from_value(unique.0)
                .map_err(|_| ContractError::InvalidFrame("malformed shutdown frame"))?;
            validate_shutdown(&value)?;
            Ok(Frame::Shutdown(value))
        }
        _ => Err(ContractError::InvalidFrame("unsupported frame kind")),
    }
}

pub fn encode_frame(frame: &Frame) -> Result<Vec<u8>, ContractError> {
    match frame {
        Frame::Launch(value) => validate_launch(value)?,
        Frame::Bound(value) => validate_bound(value)?,
        Frame::Shutdown(value) => validate_shutdown(value)?,
    }
    let value = match frame {
        Frame::Launch(value) => serde_json::to_value(value),
        Frame::Bound(value) => serde_json::to_value(value),
        Frame::Shutdown(value) => serde_json::to_value(value),
    }
    .map_err(|_| ContractError::InvalidJson)?;
    validate_json_value(&value, 0)?;
    let mut encoded =
        serde_json::to_vec(&sorted_value(value)).map_err(|_| ContractError::InvalidJson)?;
    encoded.push(b'\n');
    if encoded.len() > FRAME_LIMIT {
        return Err(ContractError::FrameTooLarge);
    }
    Ok(encoded)
}

pub fn canonicalize_frame(frame: &[u8]) -> Result<Vec<u8>, ContractError> {
    encode_frame(&parse_frame(frame)?)
}

pub fn read_frame<R: BufRead>(reader: &mut R) -> Result<Option<Vec<u8>>, ContractError> {
    let mut bytes = Vec::new();
    let count = reader
        .by_ref()
        .take((FRAME_LIMIT + 1) as u64)
        .read_until(b'\n', &mut bytes)
        .map_err(|_| ContractError::Io)?;
    if count == 0 {
        return Ok(None);
    }
    if count > FRAME_LIMIT {
        return Err(ContractError::FrameTooLarge);
    }
    frame_payload(&bytes)?;
    Ok(Some(bytes))
}

pub fn validate_launch(frame: &Launch) -> Result<(), ContractError> {
    validate_version(&frame.contract)?;
    if frame.kind != "launch" {
        return Err(ContractError::InvalidFrame("launch kind mismatch"));
    }
    validate_identity(&frame.executable)?;
    if frame.endpoint_request.host != "127.0.0.1" || frame.endpoint_request.port != 0 {
        return Err(ContractError::InvalidFrame(
            "launch endpoint must be 127.0.0.1:0",
        ));
    }
    validate_paths(&frame.data_root, &frame.log_location)?;
    validate_probe_paths(&frame.probe_paths)?;
    validate_shutdown_semantics(&frame.shutdown)?;
    StartupToken::parse(frame.startup_token.0.clone())?;
    validate_extensions(&frame.extensions)
}

pub fn validate_bound(frame: &Bound) -> Result<(), ContractError> {
    validate_version(&frame.contract)?;
    if frame.kind != "bound" {
        return Err(ContractError::InvalidFrame("bound kind mismatch"));
    }
    validate_identity(&frame.executable)?;
    if frame.endpoint.host != "127.0.0.1" || frame.endpoint.port == 0 {
        return Err(ContractError::InvalidFrame(
            "bound endpoint must use a nonzero loopback port",
        ));
    }
    validate_paths(&frame.data_root, &frame.log_location)?;
    validate_shutdown_semantics(&frame.shutdown)?;
    let authority = format!("http://127.0.0.1:{}", frame.endpoint.port);
    if frame.health_url != format!("{authority}{HEALTH_PATH}")
        || frame.readiness_url != format!("{authority}{READINESS_PATH}")
        || frame.mcp_url != format!("{authority}{MCP_PATH}")
        || frame.ui_url != format!("{authority}{UI_PATH}")
    {
        return Err(ContractError::InvalidFrame(
            "bound URL does not match announced endpoint",
        ));
    }
    validate_extensions(&frame.extensions)
}

pub fn validate_shutdown(frame: &Shutdown) -> Result<(), ContractError> {
    validate_version(&frame.contract)?;
    if frame.kind != "shutdown" {
        return Err(ContractError::InvalidFrame("shutdown kind mismatch"));
    }
    StartupToken::parse(frame.startup_token.0.clone())?;
    validate_extensions(&frame.extensions)
}

fn validate_version(version: &ContractVersion) -> Result<(), ContractError> {
    if version.major != SUPPORTED_MAJOR {
        return Err(ContractError::UnsupportedMajor(version.major.into()));
    }
    Ok(())
}

fn validate_identity(identity: &ExecutableIdentity) -> Result<(), ContractError> {
    let component_ok = !identity.component.is_empty()
        && identity.component.len() <= 64
        && identity
            .component
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-');
    let version_ok = !identity.version.is_empty()
        && identity.version.len() <= 64
        && identity
            .version
            .bytes()
            .all(|byte| byte.is_ascii_graphic() && byte != b'/' && byte != b'\\');
    let digest_ok = identity.sha256.len() == 64
        && identity
            .sha256
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte));
    if !component_ok || !version_ok || !digest_ok {
        return Err(ContractError::InvalidFrame("invalid executable identity"));
    }
    Ok(())
}

fn validate_paths(root: &Path, log: &Path) -> Result<(), ContractError> {
    validate_absolute_path(root, "data root must be canonical and absolute")?;
    validate_absolute_path(log, "log location must be canonical and absolute")?;
    let relative = log
        .strip_prefix(root)
        .map_err(|_| ContractError::InvalidFrame("log location escapes data root"))?;
    let mut components = relative.components();
    if components.next() != Some(Component::Normal("logs".as_ref())) || components.next().is_none()
    {
        return Err(ContractError::InvalidFrame(
            "log location must name a file beneath data_root/logs",
        ));
    }
    Ok(())
}

fn validate_absolute_path(path: &Path, reason: &'static str) -> Result<(), ContractError> {
    if !path.is_absolute()
        || path.as_os_str().is_empty()
        || path.to_str().is_none()
        || path
            .components()
            .any(|part| matches!(part, Component::CurDir | Component::ParentDir))
    {
        return Err(ContractError::InvalidFrame(reason));
    }
    Ok(())
}

fn validate_probe_paths(paths: &ProbePaths) -> Result<(), ContractError> {
    if paths.health != HEALTH_PATH
        || paths.readiness != READINESS_PATH
        || paths.mcp != MCP_PATH
        || paths.ui != UI_PATH
    {
        return Err(ContractError::InvalidFrame("unsupported probe paths"));
    }
    Ok(())
}

fn validate_shutdown_semantics(value: &ShutdownSemantics) -> Result<(), ContractError> {
    if value.grace_ms < MIN_GRACE_MS
        || value.force_after_ms == 0
        || value.force_after_ms > MIN_GRACE_MS
        || value.parent_lifetime != "stdin-eof"
        || value.reap != "graceful-force-reap"
    {
        return Err(ContractError::InvalidFrame("invalid shutdown semantics"));
    }
    Ok(())
}

fn validate_extensions(extensions: &Extensions) -> Result<(), ContractError> {
    if extensions.len() > MAX_EXTENSION_KEYS {
        return Err(ContractError::InvalidFrame("too many extension keys"));
    }
    for (key, value) in extensions {
        if !valid_extension_key(key, true) {
            return Err(ContractError::InvalidFrame("invalid extension namespace"));
        }
        validate_extension_value(value, 0)?;
    }
    Ok(())
}

fn validate_extension_value(value: &Value, depth: usize) -> Result<(), ContractError> {
    if depth > MAX_JSON_DEPTH {
        return Err(ContractError::InvalidFrame("extension nesting is too deep"));
    }
    match value {
        Value::Object(values) => {
            for (key, nested) in values {
                if !valid_extension_key(key, false) {
                    return Err(ContractError::InvalidFrame("invalid extension key"));
                }
                validate_extension_value(nested, depth + 1)?;
            }
        }
        Value::Array(values) => {
            for nested in values {
                validate_extension_value(nested, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn valid_extension_key(key: &str, namespaced: bool) -> bool {
    !key.is_empty()
        && key.len() <= 128
        && key.is_ascii()
        && (!namespaced || key.contains('.'))
        && key.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'.' | b'_' | b'-')
        })
        && key
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_alphanumeric)
        && key.as_bytes().last().is_some_and(u8::is_ascii_alphanumeric)
}

fn frame_payload(frame: &[u8]) -> Result<&[u8], ContractError> {
    if frame.len() > FRAME_LIMIT {
        return Err(ContractError::FrameTooLarge);
    }
    if frame.len() < 2
        || frame.last() != Some(&b'\n')
        || frame.get(frame.len().saturating_sub(2)) == Some(&b'\r')
    {
        return Err(ContractError::MissingNewline);
    }
    let payload = &frame[..frame.len() - 1];
    if payload.contains(&b'\n') || payload.starts_with(&[0xef, 0xbb, 0xbf]) {
        return Err(ContractError::InvalidEncoding);
    }
    std::str::from_utf8(payload).map_err(|_| ContractError::InvalidEncoding)?;
    Ok(payload)
}

fn preflight_major(object: &Map<String, Value>) -> Result<(), ContractError> {
    let contract = object
        .get("contract")
        .and_then(Value::as_object)
        .ok_or(ContractError::InvalidFrame("missing contract version"))?;
    let major = contract
        .get("major")
        .and_then(Value::as_u64)
        .ok_or(ContractError::InvalidFrame("invalid contract major"))?;
    if major != u64::from(SUPPORTED_MAJOR) {
        return Err(ContractError::UnsupportedMajor(major));
    }
    Ok(())
}

fn validate_json_value(value: &Value, depth: usize) -> Result<(), ContractError> {
    if depth > MAX_JSON_DEPTH {
        return Err(ContractError::InvalidJson);
    }
    match value {
        Value::Number(number) => {
            let safe = number
                .as_i64()
                .is_some_and(|value| value.unsigned_abs() <= MAX_SAFE_INTEGER)
                || number
                    .as_u64()
                    .is_some_and(|value| value <= MAX_SAFE_INTEGER);
            if !safe {
                return Err(ContractError::InvalidJson);
            }
        }
        Value::Array(values) => {
            for nested in values {
                validate_json_value(nested, depth + 1)?;
            }
        }
        Value::Object(values) => {
            for nested in values.values() {
                validate_json_value(nested, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn sorted_value(value: Value) -> Value {
    match value {
        Value::Array(values) => Value::Array(values.into_iter().map(sorted_value).collect()),
        Value::Object(values) => {
            let sorted: BTreeMap<_, _> = values
                .into_iter()
                .map(|(key, nested)| (key, sorted_value(nested)))
                .collect();
            Value::Object(sorted.into_iter().collect())
        }
        scalar => scalar,
    }
}

fn map_json_error(error: serde_json::Error) -> ContractError {
    if error.to_string().starts_with("duplicate key") {
        ContractError::DuplicateKey
    } else {
        ContractError::InvalidJson
    }
}

struct UniqueValue(Value);

impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(UniqueValueVisitor)
    }
}

struct UniqueValueVisitor;

impl<'de> Visitor<'de> for UniqueValueVisitor {
    type Value = UniqueValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON value with unique object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(value.into())))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(value.into())))
    }

    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        Err(E::custom("floating-point JSON values are not supported"))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        Ok(UniqueValue(Value::String(value.to_owned())))
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::String(value)))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<UniqueValue>()? {
            values.push(value.0);
        }
        Ok(UniqueValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(de::Error::custom("duplicate key"));
            }
            let value = object.next_value::<UniqueValue>()?;
            values.insert(key, value.0);
        }
        Ok(UniqueValue(Value::Object(values)))
    }
}

impl From<ContractError> for io::Error {
    fn from(error: ContractError) -> Self {
        io::Error::new(io::ErrorKind::InvalidData, error)
    }
}

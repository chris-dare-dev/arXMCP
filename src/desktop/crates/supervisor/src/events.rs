//! Token-free NDJSON lifecycle event log shared by racing supervisor
//! processes (fs2-locked appends). Persisted under the data root, so its
//! contents are covered by the milestone's on-disk secret scans: events
//! carry structural fields only — never the startup capability and never
//! any 64-hex digest.

use fs2::FileExt;
use serde_json::{json, Value};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Instant;

#[derive(Clone)]
pub struct Recorder {
    inner: Arc<Mutex<Inner>>,
}

struct Inner {
    path: PathBuf,
    started: Instant,
    sequence: u64,
}

impl Recorder {
    pub fn new(root: &Path) -> Result<Self, &'static str> {
        std::fs::create_dir_all(root.join("logs")).map_err(|_| "event log dir failed")?;
        Ok(Self {
            inner: Arc::new(Mutex::new(Inner {
                path: root.join("logs").join("supervisor-events.ndjson"),
                started: Instant::now(),
                sequence: 0,
            })),
        })
    }

    pub fn record(&self, event: &str, fields: Value) -> Result<(), &'static str> {
        let mut state = self.inner.lock().map_err(|_| "event recorder poisoned")?;
        state.sequence += 1;
        let record = json!({
            "elapsed_ms": u64::try_from(state.started.elapsed().as_millis()).unwrap_or(u64::MAX),
            "event": event,
            "fields": fields,
            "pid": std::process::id(),
            "seq": state.sequence,
        });
        // #488: 0600. mode() applies at CREATE only, so the explicit
        // set_permissions below is what fixes an event log an earlier version
        // already left at 0644 — and this file is exactly the one #439
        // measured a recoverable token in.
        let mut open_options = OpenOptions::new();
        open_options.create(true).append(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            open_options.mode(0o600);
        }
        let mut output = open_options
            .open(&state.path)
            .map_err(|_| "event log open failed")?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&state.path, std::fs::Permissions::from_mode(0o600));
        }
        output
            .lock_exclusive()
            .map_err(|_| "event log lock failed")?;
        let mut line = serde_json::to_vec(&record).map_err(|_| "event encode failed")?;
        line.push(b'\n');
        let result = output
            .write_all(&line)
            .and_then(|_| output.flush())
            .map_err(|_| "event log write failed");
        let _ = fs2::FileExt::unlock(&output);
        result
    }
}

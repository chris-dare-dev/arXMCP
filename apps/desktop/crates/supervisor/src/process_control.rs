//! Platform seam for cooperative process termination. The lifecycle state
//! machine calls this named boundary instead of encoding Unix signal names
//! inline, keeping the wire protocol's grace/force/reap semantics
//! platform-neutral (apps/desktop/README.md "Supported boundary"). A future
//! Windows port supplies a Job-Object implementation behind the same
//! signature; forced kill + reap stay on portable `std::process::Child`.

/// Ask the child to terminate cooperatively. Returns false when the process
/// is already gone or cannot be signalled.
#[cfg(unix)]
pub fn request_terminate(pid: u32) -> bool {
    let Ok(pid) = i32::try_from(pid) else {
        return false;
    };
    // SAFETY: pid is the retained, validated direct-child PID; SIGTERM only.
    (unsafe { libc::kill(pid, libc::SIGTERM) }) == 0
}

#[cfg(not(unix))]
pub fn request_terminate(_pid: u32) -> bool {
    // No cooperative-terminate primitive is wired for this platform yet;
    // the caller escalates to the portable forced kill.
    false
}

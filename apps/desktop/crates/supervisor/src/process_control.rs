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

/// Forcibly kill a bounded helper subprocess AND anything it spawned. #497.
///
/// `lifecycle::output_within` puts these children in their own process group
/// precisely so this call can reach a GRANDCHILD. Killing only the direct
/// child is not enough, and the difference is not theoretical: a shell that
/// forks rather than execs leaves its grandchild holding the inherited stdout
/// and stderr pipes, so the reader threads never see EOF and the "bounded"
/// helper blocks for as long as the grandchild lives. Measured while building
/// #497: a 300 ms budget took 30.007 s.
///
/// Windows needs the Job Object this module's header already anticipates;
/// until then the non-unix arm returns false and the caller falls back to
/// killing the direct child alone.
#[cfg(unix)]
pub fn force_kill_group(pgid: u32) -> bool {
    let Ok(pgid) = i32::try_from(pgid) else {
        return false;
    };
    // SAFETY: pgid is the group `output_within` created with
    // `process_group(0)`, which makes it equal to that direct child's PID.
    // SIGKILL only, and only to a group this process created.
    (unsafe { libc::killpg(pgid, libc::SIGKILL) }) == 0
}

#[cfg(not(unix))]
pub fn force_kill_group(_pgid: u32) -> bool {
    false
}

#[cfg(not(unix))]
pub fn request_terminate(_pid: u32) -> bool {
    // No cooperative-terminate primitive is wired for this platform yet;
    // the caller escalates to the portable forced kill.
    false
}

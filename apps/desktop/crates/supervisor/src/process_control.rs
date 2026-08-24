//! Platform seam for cooperative process termination. The lifecycle state
//! machine calls this named boundary instead of encoding Unix signal names
//! inline, keeping the wire protocol's grace/force/reap semantics
//! platform-neutral (apps/desktop/README.md "Supported boundary"). A future
//! Windows port supplies a Job-Object implementation behind the same
//! signature; forced kill + reap stay on portable `std::process::Child`.

/// Ask ONE process to terminate cooperatively. Returns false when it is
/// already gone or cannot be signalled.
///
/// **Not the shutdown ladder's primitive any more (#467).** Signalling only
/// the direct child is what let a grandchild outlive a complete
/// grace/TERM/KILL/reap sequence and reparent to launchd, still holding a
/// LanceDB staging directory. Use [`request_terminate_group`] there; this
/// per-PID form is retained because a caller that must NOT signal a whole
/// group has no other option — notably a test signalling a process that
/// shares the test runner's own group, where `killpg` would take down the
/// harness.
///
/// `#[allow(dead_code)]`: no production caller today, by design.
#[allow(dead_code)]
#[cfg(unix)]
pub fn request_terminate(pid: u32) -> bool {
    let Ok(pid) = i32::try_from(pid) else {
        return false;
    };
    // SAFETY: pid is the retained, validated direct-child PID; SIGTERM only.
    (unsafe { libc::kill(pid, libc::SIGTERM) }) == 0
}

/// Ask an entire process group to terminate cooperatively. #467.
///
/// The group-wide twin of [`request_terminate`]. The supervisor's child is
/// spawned into its own group, so this reaches the descendants that the
/// per-PID `kill` never could — a `tools.notebook_ingest` grandchild holding
/// a notebook's LanceDB staging directory, in the case #467 measured.
#[cfg(unix)]
pub fn request_terminate_group(pgid: u32) -> bool {
    let Ok(pgid) = i32::try_from(pgid) else {
        return false;
    };
    // SAFETY: pgid is a group this process created via `process_group(0)`;
    // SIGTERM only.
    (unsafe { libc::killpg(pgid, libc::SIGTERM) }) == 0
}

#[cfg(not(unix))]
pub fn request_terminate_group(_pgid: u32) -> bool {
    false
}

/// Does this process group still have any member? #467.
///
/// Signal 0 performs the permission and existence checks without delivering
/// anything, which is the portable way to ask.
///
/// **This is also what makes the post-reap sweep safe from PID reuse.** A
/// process-group lifetime ends only when its LAST member leaves, and a PID
/// cannot be recycled while it is still in use as a PGID. So if this returns
/// true after the direct child has been reaped, the group is still the one we
/// created — not an unrelated process that inherited a recycled number.
#[cfg(unix)]
pub fn group_has_members(pgid: u32) -> bool {
    let Ok(pgid) = i32::try_from(pgid) else {
        return false;
    };
    // SAFETY: signal 0 delivers nothing; it only reports whether the group
    // exists and is signallable by this process.
    (unsafe { libc::killpg(pgid, 0) }) == 0
}

#[cfg(not(unix))]
pub fn group_has_members(_pgid: u32) -> bool {
    false
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

#[allow(dead_code)]
#[cfg(not(unix))]
pub fn request_terminate(_pid: u32) -> bool {
    // No cooperative-terminate primitive is wired for this platform yet;
    // the caller escalates to the portable forced kill.
    false
}
